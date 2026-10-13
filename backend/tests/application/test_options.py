import pytest

from cheiron.application.options import Choice, SearchOptionsProvider
from cheiron.application.ports import TermCount, Vocabulary

pytestmark = pytest.mark.anyio


class FakeVocabulary:
    def __init__(self) -> None:
        self.calls = 0

    async def common_terms(self) -> dict[Vocabulary, tuple[TermCount, ...]]:
        self.calls += 1
        return {
            Vocabulary.COUNTRY: (TermCount("United States", 196050), TermCount("South Korea", 17784), TermCount("Austria", 5000)),
            Vocabulary.CONDITION: (TermCount("Breast Cancer", 8921), TermCount("breast cancer", 4000), TermCount("Obesity", 7608)),
            Vocabulary.INTERVENTION: (
                TermCount("Placebo", 37642),
                TermCount("Control", 2078),
                TermCount("Cyclophosphamide", 2044),
                TermCount("No intervention", 1900),
                TermCount("Usual Care", 1000),
                TermCount("Questionnaire Administration", 900),
                TermCount("cyclophosphamide", 800),
                TermCount("Pembrolizumab", 700),
            ),
            Vocabulary.SPONSOR: (TermCount("GlaxoSmithKline", 3646),),
        }


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_countries_are_the_full_list_alphabetically_with_counts() -> None:
    options = await SearchOptionsProvider(FakeVocabulary()).get()

    assert [c.value for c in options.countries] == ["Austria", "South Korea", "United States"]
    assert options.countries[1] == Choice("South Korea", "South Korea", 17784)


async def test_suggestions_drop_non_search_terms_and_case_duplicates() -> None:
    options = await SearchOptionsProvider(FakeVocabulary()).get()

    assert [c.value for c in options.interventions] == ["Cyclophosphamide", "Pembrolizumab"]
    assert [c.value for c in options.conditions] == ["Breast Cancer", "Obesity"]


async def test_phases_and_statuses_are_codes_with_labels() -> None:
    options = await SearchOptionsProvider(FakeVocabulary()).get()

    assert options.phases[0] == Choice("EARLY_PHASE1", "Early Phase 1")
    assert options.statuses[0] == Choice("RECRUITING", "Recruiting")


async def test_options_are_cached() -> None:
    vocabulary, clock = FakeVocabulary(), Clock()
    provider = SearchOptionsProvider(vocabulary, ttl_seconds=60, clock=clock)

    await provider.get()
    clock.now = 59
    await provider.get()
    clock.now = 61
    await provider.get()

    assert vocabulary.calls == 2
