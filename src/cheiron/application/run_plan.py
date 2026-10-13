"""Use case: execute an AnalysisPlan against a TrialSource."""

import asyncio
from dataclasses import dataclass

from cheiron.application.ports import TrialSource
from cheiron.domain.analysis import AnalysisPlan, needs_sites
from cheiron.domain.charts import DEFAULT_MAX_CITATIONS, build_visualization
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Visualization

DEFAULT_MAX_TRIALS = 2000


@dataclass(frozen=True)
class CohortReport:
    label: str
    filter: TrialFilter
    matched: int
    """Trials matching the filter at the source."""
    analyzed: int
    """Trials actually fetched and aggregated (at most the per-cohort cap)."""

    @property
    def truncated(self) -> bool:
        return self.analyzed < self.matched


@dataclass(frozen=True)
class PlanResult:
    visualization: Visualization
    cohorts: tuple[CohortReport, ...]
    notes: tuple[str, ...]
    """Notes about data retrieval, complementing the visualization's own notes."""


async def run_plan(
    plan: AnalysisPlan,
    source: TrialSource,
    max_trials_per_cohort: int = DEFAULT_MAX_TRIALS,
    max_citations: int = DEFAULT_MAX_CITATIONS,
) -> PlanResult:
    cohorts = plan.cohorts
    include_sites = needs_sites(plan)
    results = await asyncio.gather(
        *(source.search(c.filter, max_trials_per_cohort, include_sites=include_sites) for c in cohorts)
    )
    visualization = build_visualization(
        plan, {c.label: r.trials for c, r in zip(cohorts, results, strict=True)}, max_citations
    )
    reports = tuple(
        CohortReport(c.label, c.filter, r.total_count, len(r.trials)) for c, r in zip(cohorts, results, strict=True)
    )
    notes = tuple(
        f"Analyzed the first {r.analyzed:,} of {r.matched:,} matching trials"
        f"{f' for {r.label}' if r.label else ''}; figures cover the analyzed trials only."
        for r in reports
        if r.truncated
    )
    return PlanResult(visualization, reports, notes)
