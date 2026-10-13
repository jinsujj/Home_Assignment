"""Use case: execute an AnalysisPlan against the registry."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from cheiron.application.ports import Registry, TrialCandidate, TrialSearchResult, TrialSourceError
from cheiron.application.trial_lookup import NoPostedResults, choose_trial
from cheiron.domain.analysis import AnalysisPlan, Cohort, CountBy, TrialResults, needs_sites
from cheiron.domain.charts import DEFAULT_MAX_CITATIONS, build_visualization
from cheiron.domain.charts.trial_results import build_trial_results
from cheiron.domain.charts.views import alternative_views
from cheiron.domain.facets import dimension_facets
from cheiron.domain.membership import FREE_TEXT_CRITERIA, Membership, cite_memberships, memberships
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Visualization

DEFAULT_MAX_TRIALS = 5000
MAX_COUNT_REQUESTS = 20
"""Registry counts cost one request per category, and the API serves about one per second."""
_REGISTERED_AS = {"intervention": "an intervention", "condition": "a condition", "sponsor": "a sponsor or collaborator"}


@dataclass(frozen=True)
class CohortReport:
    label: str
    filter: TrialFilter
    matched: int
    """Trials matching the filter at the source."""
    analyzed: int
    """Trials actually fetched and aggregated (at most the per-cohort cap)."""
    exact_counts: bool = False
    """The chart's counts cover all `matched` trials (registry counts per category)."""

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
    data_version: str | None = None
    """The registry data snapshot the answer was computed from."""


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
    totals = await _registry_counts(plan, results, source)
    by_cohort, mention_notes = await _memberships(cohorts, results, source, max_trials_per_cohort)
    # Trials that register the filtered terms come first, so they are the ones cited in full.
    trials = {
        c.label: sorted(r.trials, key=lambda t: bool(by_cohort[c.label][t.nct_id].mentioned_only))
        for c, r in zip(cohorts, results, strict=True)
    }
    visualization = cite_memberships(
        build_visualization(plan, trials, max_citations, totals),
        by_cohort,
        cohorts[0].label if len(cohorts) == 1 else None,
    )
    reports = tuple(
        CohortReport(c.label, c.filter, r.total_count, len(r.trials), exact_counts=c.label in totals)
        for c, r in zip(cohorts, results, strict=True)
    )
    notes = tuple(
        f"Counts cover all {r.matched:,} matching trials{f' for {r.label}' if r.label else ''}, counted per "
        f"category by ClinicalTrials.gov; citations and other notes cover the first {r.analyzed:,} analyzed."
        if r.exact_counts
        else f"Analyzed the first {r.analyzed:,} of {r.matched:,} matching trials"
        f"{f' for {r.label}' if r.label else ''}; figures cover the analyzed trials only."
        for r in reports
        if r.truncated
    )
    notes += mention_notes
    notes += tuple(
        f"No trials match the filters{f' for {r.label}' if r.label else ''}; "
        "check the spelling or try a broader term."
        for r in reports
        if not r.matched
    )
    if any(c.filter.country for c in cohorts):
        notes += (
            "A country filter keeps trials with at least one site in that country, "
            "so multinational trials are included.",
        )
    return PlanResult(
        visualization,
        reports,
        notes,
        alternatives=alternative_views(visualization),
        data_version=await _data_version(source),
    )


async def _memberships(
    cohorts: Sequence[Cohort], results: Sequence[TrialSearchResult], source: Registry, limit: int
) -> tuple[dict[str, dict[str, Membership]], tuple[str, ...]]:
    """Why each analyzed trial is in its cohort, by cohort label, and notes on trials that only
    mention a free-text filter. One request per free-text filter, plus pages of IDs if many."""
    by_cohort, notes = {}, []
    for cohort, result in zip(cohorts, results, strict=True):
        mentioned: dict[str, frozenset[str] | None] = {}
        for criterion in FREE_TEXT_CRITERIA:
            if not (term := getattr(cohort.filter, criterion)):
                continue
            try:
                mentioned[criterion] = await source.mentioned_only(cohort.filter, criterion, limit)
            except TrialSourceError:
                mentioned[criterion] = None
            where = f" for {cohort.label}" if cohort.label else ""
            if (ids := mentioned[criterion]) is None:
                notes.append(f"Trials that only mention {term!r}{where} could not be told apart from the others.")
            elif count := sum(t.nct_id in ids for t in result.trials):
                notes.append(
                    f"{count:,} of {len(result.trials):,} analyzed trials{where} mention {term!r} without registering "
                    f"it as {_REGISTERED_AS[criterion]} (ClinicalTrials.gov's search also matches text such as "
                    "descriptions); their citations list it under mentioned_only."
                )
        by_cohort[cohort.label] = memberships(result.trials, cohort.filter, mentioned)
    return by_cohort, tuple(notes)


async def _registry_counts(
    plan: AnalysisPlan, results: Sequence[TrialSearchResult], source: Registry
) -> dict[str, dict[str, int]]:
    """Exact category counts for truncated cohorts, by cohort label, where the registry can count them.

    Categories are those of the analyzed trials. Without a split, the counts are one number per
    bar; beyond MAX_COUNT_REQUESTS, or when counting fails, the analyzed trials are charted.
    """
    if not isinstance(plan, CountBy) or plan.split_by:
        return {}
    wanted = {
        cohort: sorted({f.key for t in result.trials for f in dimension_facets(t, plan.dimension)}, key=str)
        for cohort, result in zip(plan.cohorts, results, strict=True)
        if result.truncated
    }
    if not wanted or sum(len(keys) for keys in wanted.values()) > MAX_COUNT_REQUESTS:
        return {}
    totals = {}
    try:
        for cohort, keys in wanted.items():
            counts = await source.count_by(cohort.filter, plan.dimension, keys)
            if counts is None:
                return {}
            totals[cohort.label] = counts
    except TrialSourceError:
        return {}
    return totals


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
        data_version=await _data_version(source),
    )


async def _data_version(source: Registry) -> str | None:
    """The answer stands without it, so an unreachable /version does not fail the answer."""
    try:
        return await source.data_version()
    except TrialSourceError:
        return None
