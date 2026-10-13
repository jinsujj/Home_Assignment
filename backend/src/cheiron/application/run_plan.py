"""Use case: execute an AnalysisPlan against the registry."""

import asyncio
from dataclasses import dataclass

from cheiron.application.ports import Registry, TrialCandidate
from cheiron.application.trial_lookup import NoPostedResults, choose_trial
from cheiron.domain.analysis import AnalysisPlan, TrialResults, needs_sites
from cheiron.domain.charts import DEFAULT_MAX_CITATIONS, build_visualization
from cheiron.domain.charts.trial_results import build_trial_results
from cheiron.domain.charts.views import alternative_views
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Visualization

DEFAULT_MAX_TRIALS = 5000


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
class TrialReport:
    """The single trial whose posted results were charted, and other trials the name matched."""

    nct_id: str
    title: str
    alternatives: tuple[TrialCandidate, ...] = ()


@dataclass(frozen=True)
class PlanResult:
    visualization: Visualization
    cohorts: tuple[CohortReport, ...]
    notes: tuple[str, ...]
    """Notes about data retrieval, complementing the visualization's own notes."""
    trial: TrialReport | None = None
    alternatives: tuple[Visualization, ...] = ()
    """The same data in other chart forms (charts.views)."""


async def run_plan(
    plan: AnalysisPlan,
    source: Registry,
    max_trials_per_cohort: int = DEFAULT_MAX_TRIALS,
    max_citations: int = DEFAULT_MAX_CITATIONS,
) -> PlanResult:
    if isinstance(plan, TrialResults):
        return await _run_trial_results(plan, source)

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
    if any(c.filter.country for c in cohorts):
        notes += (
            "A country filter keeps trials with at least one site in that country, "
            "so multinational trials are included.",
        )
    return PlanResult(visualization, reports, notes, alternatives=alternative_views(visualization))


async def _run_trial_results(plan: TrialResults, source: Registry) -> PlanResult:
    """Raises TrialNotFound or NoPostedResults."""
    choice = None if plan.nct_id else await choose_trial(plan.trial, source)
    nct_id = plan.nct_id or choice.chosen.nct_id
    results = await source.posted_results(nct_id)
    if results is None:
        raise NoPostedResults(nct_id, choice.chosen.title if choice else None)
    note = choice.note(plan.trial) if choice else None
    visualization = build_trial_results(plan, results)
    return PlanResult(
        visualization,
        cohorts=(),
        notes=(note,) if note else (),
        trial=TrialReport(results.nct_id, results.title, choice.alternatives if choice else ()),
        alternatives=alternative_views(visualization),
    )
