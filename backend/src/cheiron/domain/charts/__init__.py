"""Deterministic AnalysisPlan + trials -> Visualization."""

from collections.abc import Mapping, Sequence

from cheiron.domain.analysis import AnalysisPlan, CoOccurrence, Correlation, CountBy, Distribution, TrialResults
from cheiron.domain.charts.co_occurrence import build_co_occurrence
from cheiron.domain.charts.correlation import build_correlation
from cheiron.domain.charts.count_by import build_count_by
from cheiron.domain.charts.distribution import build_distribution
from cheiron.domain.trial import Trial
from cheiron.domain.visualization import RegistryCount, Visualization

DEFAULT_MAX_CITATIONS = 5


def build_visualization(
    plan: AnalysisPlan,
    trials_by_cohort: Mapping[str, Sequence[Trial]],
    max_citations: int = DEFAULT_MAX_CITATIONS,
    totals: Mapping[str, Mapping[str | int, RegistryCount]] | None = None,
) -> Visualization:
    """`trials_by_cohort` maps each cohort label of the plan to its trials.

    `totals` gives CountBy registry counts per category for cohorts whose trials are a
    truncated subset, by cohort label; their bars show these counts.
    """
    match plan:
        case CountBy():
            return build_count_by(plan, trials_by_cohort, max_citations, totals or {})
        case CoOccurrence():
            return build_co_occurrence(plan, trials_by_cohort[plan.cohort.label], max_citations)
        case Distribution():
            return build_distribution(plan, trials_by_cohort[plan.cohort.label], max_citations)
        case Correlation():
            return build_correlation(plan, trials_by_cohort[plan.cohort.label], max_citations)
        case TrialResults():
            raise TypeError("TrialResults charts posted results, not trials: use charts.trial_results")
