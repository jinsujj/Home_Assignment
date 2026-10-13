import pytest

from cheiron.application.ports import TrialSearchResult
from cheiron.application.run_plan import CohortReport, run_plan
from cheiron.domain.analysis import Cohort, CoOccurrence, CountBy, Dimension, Distribution, Entity, Measure
from cheiron.domain.trial import Phase
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import ChartType
from tests.domain.factories import trial

pytestmark = pytest.mark.anyio

A = Cohort("A", TrialFilter(intervention="a"))
B = Cohort("B", TrialFilter(intervention="b"))


class FakeSource:
    def __init__(self, results: dict[TrialFilter, TrialSearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[TrialFilter, int]] = []
        self.include_sites: list[bool] = []

    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        self.calls.append((criteria, max_trials))
        self.include_sites.append(include_sites)
        return self.results[criteria]


async def test_fetches_every_cohort_and_reports_coverage() -> None:
    source = FakeSource(
        {
            A.filter: TrialSearchResult((trial("NCT1", phases=(Phase.PHASE1,)),), total_count=1),
            B.filter: TrialSearchResult((trial("NCT2", phases=(Phase.PHASE2,)),), total_count=40),
        }
    )

    result = await run_plan(CountBy((A, B), Dimension.PHASE), source, max_trials_per_cohort=1)

    assert sorted(source.calls, key=lambda c: c[0].intervention) == [(A.filter, 1), (B.filter, 1)]
    assert result.visualization.type is ChartType.GROUPED_BAR
    assert result.cohorts == (CohortReport("A", A.filter, 1, 1), CohortReport("B", B.filter, 40, 1))
    assert result.notes == ("Analyzed the first 1 of 40 matching trials for B; figures cover the analyzed trials only.",)


async def test_single_cohort_plans() -> None:
    source = FakeSource({A.filter: TrialSearchResult((trial("NCT1", enrollment=10),), total_count=1)})

    result = await run_plan(Distribution(A, Measure.ENROLLMENT), source)

    assert result.visualization.type is ChartType.HISTOGRAM
    assert result.notes == ()
    assert source.include_sites == [False]


async def test_sites_are_fetched_only_for_plans_that_use_them() -> None:
    source = FakeSource({A.filter: TrialSearchResult((), total_count=0)})

    await run_plan(CoOccurrence(A, Entity.SITE, Entity.DRUG), source)
    await run_plan(CoOccurrence(A, Entity.SPONSOR, Entity.DRUG), source)

    assert source.include_sites == [True, False]
