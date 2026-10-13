from datetime import date

import pytest

from cheiron.adapters.outbound.caching import CachingAnswerWriter, CachingMentionJudge, CachingPlanner, CachingTrialSource
from cheiron.application.writing import AnswerContext, AnswerDraft, Item
from cheiron.application.planning import Question, StructuredFields
from cheiron.application.ports import MentionCase, PlannerError, TrialSearchResult, TrialSourceError
from cheiron.domain.analysis import Dimension
from cheiron.domain.membership import MentionRole
from cheiron.domain.trial_filter import TrialFilter
from tests.application.planning_factories import draft
from tests.domain.factories import trial

pytestmark = pytest.mark.anyio

PEMBRO = TrialFilter(intervention="pembrolizumab")
NIVO = TrialFilter(intervention="nivolumab")
ASTHMA = TrialFilter(condition="asthma")


class CountingSource:
    def __init__(self, size: int = 1) -> None:
        self.size = size
        self.calls: list[tuple[TrialFilter, int, bool]] = []
        self.fail = False

    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        self.calls.append((criteria, max_trials, include_sites))
        if self.fail:
            raise TrialSourceError("down")
        return TrialSearchResult(tuple(trial(f"NCT{i}") for i in range(self.size)), self.size)

    async def count_by(self, criteria: TrialFilter, dimension, keys) -> dict[str, int]:
        self.calls.append(("count", criteria, dimension, tuple(keys)))
        return {k: 1 for k in keys}

    async def find_trials(self, name: str) -> tuple:
        self.calls.append(("find", name))
        return ()

    async def posted_results(self, nct_id: str):
        self.calls.append(("results", nct_id))
        return None


class Version:
    def __init__(self) -> None:
        self.value = "2026-10-09T09:00:05"
        self.calls = 0
        self.fail = False

    async def __call__(self) -> str:
        self.calls += 1
        if self.fail:
            raise TrialSourceError("down")
        return self.value


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def cache_for(inner: CountingSource, version: Version | None = None, clock: Clock | None = None, **kwargs) -> CachingTrialSource:
    return CachingTrialSource(inner, version or Version(), clock=clock or Clock(), **kwargs)


async def test_repeated_searches_are_served_from_memory() -> None:
    inner = CountingSource()
    cache = cache_for(inner)

    first = await cache.search(PEMBRO, 100)
    second = await cache.search(PEMBRO, 100)

    assert second is first
    assert len(inner.calls) == 1


async def test_results_differ_by_filter_cap_and_sites() -> None:
    inner = CountingSource()
    cache = cache_for(inner)

    for criteria, cap, sites in [(PEMBRO, 100, False), (NIVO, 100, False), (PEMBRO, 200, False), (PEMBRO, 100, True)]:
        await cache.search(criteria, cap, include_sites=sites)

    assert len(inner.calls) == 4


async def test_newly_published_data_clears_the_cache() -> None:
    inner, version, clock = CountingSource(), Version(), Clock()
    cache = cache_for(inner, version, clock, version_check_seconds=600)

    await cache.search(PEMBRO, 100)
    version.value = "2026-10-13T09:00:04"
    clock.now = 599
    await cache.search(PEMBRO, 100)  # not checked yet: still the old snapshot
    clock.now = 601
    await cache.search(PEMBRO, 100)  # checked: new snapshot, fetched again

    assert len(inner.calls) == 2
    assert version.calls == 2


async def test_unchanged_data_stays_cached_across_checks() -> None:
    inner, version, clock = CountingSource(), Version(), Clock()
    cache = cache_for(inner, version, clock, version_check_seconds=600)

    await cache.search(PEMBRO, 100)
    clock.now = 3 * 3600  # e.g. a weekend: checked again, same snapshot
    await cache.search(PEMBRO, 100)

    assert len(inner.calls) == 1
    assert version.calls == 2


async def test_failed_version_checks_keep_serving_until_max_age() -> None:
    inner, version, clock = CountingSource(), Version(), Clock()
    cache = cache_for(inner, version, clock, version_check_seconds=600, max_age_seconds=3600)

    await cache.search(PEMBRO, 100)
    version.fail = True
    clock.now = 1800
    await cache.search(PEMBRO, 100)
    clock.now = 3601
    await cache.search(PEMBRO, 100)

    assert len(inner.calls) == 2


async def test_least_recently_used_results_are_evicted_beyond_capacity() -> None:
    inner = CountingSource(size=10)
    cache = cache_for(inner, max_cached_trials=20)

    await cache.search(PEMBRO, 100)
    await cache.search(NIVO, 100)
    await cache.search(PEMBRO, 100)  # hit; NIVO is now least recently used
    await cache.search(ASTHMA, 100)  # 30 trials > 20: evicts NIVO
    await cache.search(PEMBRO, 100)
    await cache.search(NIVO, 100)

    assert [c[0] for c in inner.calls] == [PEMBRO, NIVO, ASTHMA, NIVO]


async def test_site_results_weigh_more() -> None:
    inner = CountingSource(size=10)
    cache = cache_for(inner, max_cached_trials=35)

    await cache.search(PEMBRO, 100)
    await cache.search(PEMBRO, 100, include_sites=True)  # 10 + 30 > 35: evicts the plain result
    await cache.search(PEMBRO, 100)

    assert len(inner.calls) == 3


async def test_failures_are_not_cached() -> None:
    inner = CountingSource()
    cache = cache_for(inner)
    inner.fail = True
    with pytest.raises(TrialSourceError):
        await cache.search(PEMBRO, 100)

    inner.fail = False
    await cache.search(PEMBRO, 100)

    assert len(inner.calls) == 2


async def test_name_lookups_and_posted_results_are_cached_too() -> None:
    inner, version, clock = CountingSource(), Version(), Clock()
    cache = cache_for(inner, version, clock, version_check_seconds=600)

    await cache.find_trials("KEYNOTE-189")
    await cache.find_trials("keynote-189 ")
    await cache.posted_results("nct02578680")
    await cache.posted_results("NCT02578680")
    version.value = "2026-10-13T09:00:04"
    clock.now = 601
    await cache.posted_results("NCT02578680")

    assert inner.calls == [("find", "KEYNOTE-189"), ("results", "nct02578680"), ("results", "NCT02578680")]


async def test_posted_results_weigh_like_many_trials() -> None:
    inner = CountingSource(size=10)
    cache = cache_for(inner, max_cached_trials=505)

    await cache.search(PEMBRO, 100)  # 10
    await cache.posted_results("NCT02578680")  # + 500 > 505: evicts the search
    await cache.search(PEMBRO, 100)

    assert [c[0] for c in inner.calls] == [PEMBRO, "results", PEMBRO]


# --- CachingPlanner ---------------------------------------------------------------------------


class CountingPlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail = False

    async def draft(self, question, feedback=()):
        self.calls.append((question.text, tuple(feedback)))
        if self.fail:
            raise PlannerError("down")
        return draft(interpretation=f"draft {len(self.calls)}")


class Today:
    def __init__(self) -> None:
        self.value = date(2026, 10, 13)

    def __call__(self) -> date:
        return self.value


async def test_the_same_question_is_planned_once() -> None:
    inner = CountingPlanner()
    planner = CachingPlanner(inner)

    first = await planner.draft(Question("Which drugs are combined with pembrolizumab?"))
    again = await planner.draft(Question("  which drugs are combined with PEMBROLIZUMAB "))

    assert again is first
    assert len(inner.calls) == 1


async def test_fields_feedback_and_date_are_part_of_the_question() -> None:
    inner, today = CountingPlanner(), Today()
    planner = CachingPlanner(inner, today=today)
    question = Question("How has this drug changed over time?")

    await planner.draft(question)
    await planner.draft(Question(question.text, StructuredFields(drug_name="Pembrolizumab")))
    await planner.draft(question, ["count_by requires dimension."])
    await planner.draft(question, ["count_by requires dimension."])
    today.value = date(2026, 10, 14)  # "in the last 5 years" may now mean other years
    await planner.draft(question)

    assert len(inner.calls) == 4


async def test_planner_failures_are_not_cached_and_old_plans_are_evicted() -> None:
    inner = CountingPlanner()
    planner = CachingPlanner(inner, max_plans=2)
    inner.fail = True
    with pytest.raises(PlannerError):
        await planner.draft(Question("a"))
    inner.fail = False

    for text in ("a", "b", "c", "a"):
        await planner.draft(Question(text))

    assert [text for text, _ in inner.calls] == ["a", "a", "b", "c", "a"]


async def test_category_counts_are_cached_per_filter_dimension_and_keys() -> None:
    inner = CountingSource()
    cache = CachingTrialSource(inner, Version())

    first = await cache.count_by(PEMBRO, Dimension.PHASE, ["PHASE2", "PHASE3"])
    again = await cache.count_by(PEMBRO, Dimension.PHASE, ("PHASE2", "PHASE3"))
    await cache.count_by(PEMBRO, Dimension.STATUS, ["PHASE2", "PHASE3"])

    assert again is first
    assert len(inner.calls) == 2


async def test_reports_the_snapshot_its_data_belongs_to() -> None:
    version, clock = Version(), Clock()
    cache = CachingTrialSource(CountingSource(), version, version_check_seconds=600, clock=clock)

    assert await cache.data_version() == version.value
    version.value = "2026-10-10T09:00:00"
    assert await cache.data_version() != version.value  # checked at most every 10 minutes
    clock.now += 601
    assert await cache.data_version() == "2026-10-10T09:00:00"


async def test_mention_checks_are_cached() -> None:
    class Mentions(CountingSource):
        async def mentioned_only(self, criteria, criterion, limit):
            self.calls.append(("mentioned", criterion))
            return frozenset({"NCT1"})

    inner = Mentions()
    cache = CachingTrialSource(inner, Version())

    assert await cache.mentioned_only(PEMBRO, "intervention", 5000) == {"NCT1"}
    assert await cache.mentioned_only(PEMBRO, "intervention", 5000) == {"NCT1"}
    assert inner.calls == [("mentioned", "intervention")]


async def test_each_trials_mentions_are_judged_once() -> None:
    class Judge:
        def __init__(self) -> None:
            self.asked: list[list[str]] = []

        async def judge(self, cases):
            self.asked.append([c.nct_id for c in cases])
            return {c.nct_id: (MentionRole.BACKGROUND, "drugs such as x") for c in cases}

    inner = Judge()
    judge = CachingMentionJudge(inner)
    a, b = MentionCase("NCT1", ("x",), ()), MentionCase("NCT2", ("x",), ())

    await judge.judge([a])
    verdicts = await judge.judge([a, b])

    assert inner.asked == [["NCT1"], ["NCT2"]]
    assert set(verdicts) == {"NCT1", "NCT2"}


async def test_tallies_are_cached() -> None:
    class Tallies(CountingSource):
        async def tally(self, criteria, dimension, limit):
            self.calls.append(("tally", dimension))
            return {}

    inner = Tallies()
    cache = CachingTrialSource(inner, Version())

    await cache.tally(PEMBRO, Dimension.START_YEAR, 25_000)
    await cache.tally(PEMBRO, Dimension.START_YEAR, 25_000)

    assert inner.calls == [("tally", Dimension.START_YEAR)]


async def test_a_follow_up_is_planned_apart_from_the_same_words_asked_alone() -> None:
    inner = CountingPlanner()
    planner = CachingPlanner(inner)

    await planner.draft(Question("Only recruiting ones"))
    await planner.draft(Question("Only recruiting ones", earlier=("Breast cancer trials by phase",), previous_plan="{}"))
    await planner.draft(Question("Only recruiting ones", earlier=("Lung cancer trials by phase",), previous_plan="{}"))

    assert len(inner.calls) == 3


async def test_the_same_question_over_the_same_data_is_written_once() -> None:
    class Writer:
        def __init__(self) -> None:
            self.calls = 0

        async def write(self, context):
            self.calls += 1
            return AnswerDraft(sentences=[], follow_ups=[])

    inner = Writer()
    writer = CachingAnswerWriter(inner)
    context = AnswerContext("q", "bar_chart: t", (Item("r0", "#/visualization/data/0", (("trial_count", 3),)),))
    other = AnswerContext("q", "bar_chart: t", (Item("r0", "#/visualization/data/0", (("trial_count", 4),)),))

    first = await writer.write(context)
    assert await writer.write(context) is first
    await writer.write(other)  # new data, new answer

    assert inner.calls == 2
