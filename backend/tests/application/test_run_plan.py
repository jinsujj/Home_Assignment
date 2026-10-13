import pytest

from cheiron.application.ports import TrialCandidate, TrialSearchResult, TrialSourceError
from cheiron.application.run_plan import MAX_COUNT_REQUESTS, CohortReport, run_plan
from cheiron.application.trial_lookup import NoPostedResults
from cheiron.domain.analysis import Cohort, CoOccurrence, CountBy, Dimension, Distribution, Entity, Measure, TrialResults
from cheiron.domain.results import PostedResults
from cheiron.domain.trial import Phase, Status
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import ChartType, RegistryCount
from tests.domain.factories import drug, trial

pytestmark = pytest.mark.anyio

A = Cohort("A", TrialFilter(intervention="a"))
B = Cohort("B", TrialFilter(intervention="b"))
SNAPSHOT = "2026-10-09T09:00:05"


class FakeSource:
    def __init__(
        self, results: dict[TrialFilter, TrialSearchResult], counts=None, count_error=None, mentioned=None, texts=None
    ) -> None:
        self.results = results
        self.texts: dict[str, dict[str, tuple[str, ...]]] = texts or {}
        self.text_calls: list[tuple[str, ...]] = []
        self.mentioned: dict[tuple[TrialFilter, str], frozenset[str] | None] = mentioned or {}
        self.counts: dict[TrialFilter, dict[str, int]] = counts or {}
        self.count_error = count_error
        self.calls: list[tuple[TrialFilter, int]] = []
        self.count_calls: list[tuple[TrialFilter, Dimension, tuple[str, ...]]] = []
        self.include_sites: list[bool] = []

    async def count_by(self, criteria: TrialFilter, dimension: Dimension, keys) -> dict[str, RegistryCount] | None:
        self.count_calls.append((criteria, dimension, tuple(keys)))
        if self.count_error:
            raise self.count_error
        counts = self.counts.get(criteria)
        return {k: RegistryCount(n, f"query {k}") for k, n in counts.items()} if counts else None

    async def category_ids(self, criteria: TrialFilter, dimension: Dimension, key: str, limit: int):
        n = self.counts[criteria][key]
        return tuple(f"NCT{key}{i}" for i in range(n)) if n <= limit else None

    async def data_version(self) -> str:
        return SNAPSHOT

    async def mentioned_only(self, criteria: TrialFilter, criterion: str, limit: int) -> frozenset[str] | None:
        return self.mentioned.get((criteria, criterion), frozenset())

    async def trial_texts(self, nct_ids):
        self.text_calls.append(tuple(nct_ids))
        return {n: self.texts[n] for n in nct_ids if n in self.texts}

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
    assert result.cohorts == (CohortReport("A", A.filter, 1, 1, names=("a",)), CohortReport("B", B.filter, 40, 1, names=("b",)))
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


async def test_country_filters_are_explained() -> None:
    korea = Cohort("Pembrolizumab", TrialFilter(intervention="pembrolizumab", country="South Korea"))
    source = FakeSource({korea.filter: TrialSearchResult((trial("NCT1", phases=(Phase.PHASE2,)),), total_count=1)})

    result = await run_plan(CountBy((korea,), Dimension.PHASE), source)

    assert result.notes == (
        "A country filter keeps trials with at least one site in that country, so multinational trials are included.",
    )


class ResultsRegistry:
    def __init__(self, results, candidates=()) -> None:
        self.results, self.candidates = results, candidates
        self.requested: list[str] = []

    async def find_trials(self, name):
        return self.candidates

    async def posted_results(self, nct_id):
        self.requested.append(nct_id)
        return self.results

    async def data_version(self) -> str:
        return SNAPSHOT


async def test_trial_results_by_name_report_the_trial_and_alternatives() -> None:
    main = TrialCandidate("NCT02578680", "Main", None, True, 616, "title")
    extension = TrialCandidate("NCT03950674", "Extension", None, True, 40, "study_id")
    registry = ResultsRegistry(PostedResults("NCT02578680", "Main", None, (), ()), (main, extension))

    result = await run_plan(TrialResults("KEYNOTE-189"), registry)

    assert registry.requested == ["NCT02578680"]
    assert result.trial.nct_id == "NCT02578680" and result.trial.alternatives == (extension,)
    assert result.cohorts == ()
    assert result.notes[0].startswith("'KEYNOTE-189' matches 2 trials")


async def test_trial_results_by_nct_id_skip_the_name_lookup() -> None:
    registry = ResultsRegistry(None)

    with pytest.raises(NoPostedResults):
        await run_plan(TrialResults("nct05908799"), registry)
    assert registry.requested == ["NCT05908799"]


# --- Registry counts for truncated cohorts ------------------------------------------------


def _phases(*phases: Phase) -> tuple:
    return tuple(trial(f"NCT{i}", phases=(p,)) for i, p in enumerate(phases))


async def test_truncated_cohorts_are_counted_by_the_registry() -> None:
    source = FakeSource(
        {
            A.filter: TrialSearchResult(_phases(Phase.PHASE1, Phase.PHASE2), total_count=40),
            B.filter: TrialSearchResult(_phases(Phase.PHASE2), total_count=1),
        },
        counts={A.filter: {"PHASE1": 12, "PHASE2": 30}},
    )

    result = await run_plan(CountBy((A, B), Dimension.PHASE), source, max_trials_per_cohort=2)

    assert source.count_calls == [(A.filter, Dimension.PHASE, ("PHASE1", "PHASE2"))]  # B is complete
    rows = [(r["phase"], r["cohort"], r["trial_count"], r["citations"].total) for r in result.visualization.data]
    assert rows == [("Phase 1", "A", 12, 1), ("Phase 1", "B", 0, 0), ("Phase 2", "A", 30, 1), ("Phase 2", "B", 1, 1)]
    assert result.cohorts[0] == CohortReport("A", A.filter, 40, 2, exact_counts=True, names=("a",))
    assert result.notes == (
        "Counts cover all 40 matching trials for A, counted per category by ClinicalTrials.gov; "
        "citations and other notes cover the first 2 analyzed.",
    )


async def test_analyzed_trials_are_charted_when_counting_is_unavailable() -> None:
    truncated = TrialSearchResult(_phases(Phase.PHASE1, Phase.PHASE2), total_count=40)
    many = TrialSearchResult(tuple(trial(f"NCT{i}", status=s) for i, s in enumerate(Status)), total_count=99)
    cases = [
        (FakeSource({A.filter: truncated}), CountBy((A,), Dimension.PHASE)),  # source cannot count
        (FakeSource({A.filter: truncated}, count_error=TrialSourceError("429")), CountBy((A,), Dimension.PHASE)),
        (FakeSource({A.filter: truncated}), CountBy((A,), Dimension.PHASE, split_by=Dimension.STATUS)),
    ]
    for source, plan in cases:
        result = await run_plan(plan, source, max_trials_per_cohort=2)
        assert not result.cohorts[0].exact_counts
        assert result.notes == ("Analyzed the first 2 of 40 matching trials for A; figures cover the analyzed trials only.",)

    # Two truncated cohorts with every status are more requests than an answer may spend.
    assert len(Status) * 2 > MAX_COUNT_REQUESTS
    source = FakeSource({A.filter: many, B.filter: many})
    await run_plan(CountBy((A, B), Dimension.STATUS), source)
    assert source.count_calls == []


async def test_answers_name_their_data_snapshot_but_do_not_depend_on_it() -> None:
    class NoVersion(FakeSource):
        async def data_version(self) -> str:
            raise TrialSourceError("/version is down")

    results = {A.filter: TrialSearchResult((trial("NCT1", phases=(Phase.PHASE1,)),), total_count=1)}

    assert (await run_plan(CountBy((A,), Dimension.PHASE), FakeSource(results))).data_version == SNAPSHOT
    assert (await run_plan(CountBy((A,), Dimension.PHASE), NoVersion(results))).data_version is None


async def test_cohorts_without_any_match_are_named() -> None:
    source = FakeSource({A.filter: TrialSearchResult((), total_count=0)})

    result = await run_plan(CountBy((A,), Dimension.PHASE), source)

    assert result.notes == ("No trials match the filters for A; check the spelling or try a broader term.",)


async def test_citations_show_why_each_trial_is_in_its_cohort() -> None:
    registered = trial("NCT1", phases=(Phase.PHASE2,), interventions=(drug("Pembrolizumab"),))
    mentioning = trial("NCT2", phases=(Phase.PHASE2,), interventions=(drug("Fecal microbiota"),))
    source = FakeSource(
        {A.filter: TrialSearchResult((mentioning, registered), total_count=2)},
        mentioned={(A.filter, "intervention"): frozenset({"NCT2"})},
    )

    result = await run_plan(CountBy((A,), Dimension.PHASE), source)

    first, second = result.visualization.data[0]["citations"].items
    assert (first.nct_id, first.excerpt, first.mentioned_only) == ("NCT1", "phases: PHASE2; interventions.name: Pembrolizumab", ())
    assert (second.nct_id, second.excerpt, second.mentioned_only) == ("NCT2", "phases: PHASE2", ("a",))
    assert result.notes == (
        "1 of 2 analyzed trials for A mention 'a' without registering it as an intervention (ClinicalTrials.gov's "
        "search also matches text such as descriptions, and a narrower registered name, e.g. a subtype, does not "
        "count); their citations list it under mentioned_only.",
    )


async def test_mentions_that_cannot_be_checked_are_reported() -> None:
    source = FakeSource(
        {A.filter: TrialSearchResult((trial("NCT1", phases=(Phase.PHASE2,)),), total_count=1)},
        mentioned={(A.filter, "intervention"): None},
    )

    result = await run_plan(CountBy((A,), Dimension.PHASE), source)

    assert result.notes == ("Trials that only mention 'a' for A could not be told apart from the others.",)
    assert result.visualization.data[0]["citations"].items[0].mentioned_only == ()


async def test_cited_trials_quote_the_passage_naming_the_filtered_drug() -> None:
    cited = trial("NCT1", phases=(Phase.PHASE2,), interventions=(drug("Pembrolizumab"),))
    texts = {"NCT1": {"protocolSection.descriptionModule.briefSummary": ("This study adds pembrolizumab to chemotherapy.",)}}
    source = FakeSource({A.filter: TrialSearchResult((cited,), total_count=1)}, texts=texts)

    result = await run_plan(CountBy((A,), Dimension.PHASE), source)

    [citation] = result.visualization.data[0]["citations"].items
    assert citation.excerpt == (
        "phases: PHASE2; interventions.name: Pembrolizumab; briefSummary: This study adds pembrolizumab to chemotherapy."
    )
    assert source.text_calls == [("NCT1",)]


async def test_without_free_text_filters_no_text_is_fetched() -> None:
    by_phase = Cohort("Phase 3", TrialFilter(phases=frozenset({Phase.PHASE3})))
    source = FakeSource({by_phase.filter: TrialSearchResult((trial("NCT1", phases=(Phase.PHASE3,)),), total_count=1)})

    await run_plan(CountBy((by_phase,), Dimension.STATUS), source)

    assert source.text_calls == []


async def test_every_trial_behind_registry_counts_is_listed_on_request() -> None:
    source = FakeSource(
        {A.filter: TrialSearchResult(_phases(Phase.PHASE1, Phase.PHASE2), total_count=40)},
        counts={A.filter: {"PHASE1": 12, "PHASE2": 30}},
    )

    result = await run_plan(CountBy((A,), Dimension.PHASE), source, max_trials_per_cohort=2, all_citation_ids=True)

    phase2 = result.visualization.data[1]["citations"]
    assert (phase2.total, len(phase2.nct_ids), phase2.registry_query) == (30, 30, "query PHASE2")
    assert len(phase2.items) == 1  # still the analyzed trial, with its evidence
