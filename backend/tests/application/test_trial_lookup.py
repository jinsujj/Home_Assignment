import pytest

from cheiron.application.ports import TrialCandidate
from cheiron.application.trial_lookup import NoPostedResults, TrialNotFound, choose_trial

pytestmark = pytest.mark.anyio


def candidate(nct_id: str, matched_by, has_results: bool = True, enrollment: int | None = 100) -> TrialCandidate:
    return TrialCandidate(nct_id, f"Title {nct_id}", None, has_results, enrollment, matched_by)


class Candidates:
    def __init__(self, *candidates: TrialCandidate) -> None:
        self.candidates = candidates

    async def find_trials(self, name: str) -> tuple[TrialCandidate, ...]:
        return self.candidates


async def test_keynote_189_picks_the_main_trial_over_its_extension_and_emulations() -> None:
    source = Candidates(
        candidate("NCT03950674", "study_id", enrollment=40),  # Japan extension
        candidate("NCT02578680", "title", enrollment=616),  # main trial
        candidate("NCT06607393", "title", has_results=False, enrollment=851),  # real-world emulation
    )

    choice = await choose_trial("KEYNOTE-189", source)

    assert choice.chosen.nct_id == "NCT02578680"
    assert [c.nct_id for c in choice.alternatives] == ["NCT03950674"]
    assert choice.note("KEYNOTE-189") == (
        "'KEYNOTE-189' matches 2 trials with posted results; showing NCT02578680, the largest (616 participants). "
        "Also matching: NCT03950674 (40 participants)."
    )


async def test_an_exact_acronym_wins_over_ids_and_titles() -> None:
    source = Candidates(candidate("NCT1", "title", enrollment=5000), candidate("NCT2", "acronym", enrollment=50))

    assert (await choose_trial("CheckMate 227", source)).chosen.nct_id == "NCT2"


async def test_common_words_only_match_acronyms() -> None:
    source = Candidates(candidate("NCT1", "title", enrollment=5000))

    with pytest.raises(TrialNotFound):
        await choose_trial("RECOVERY", source)


async def test_matches_without_posted_results() -> None:
    source = Candidates(candidate("NCT1", "title", has_results=False, enrollment=10), candidate("NCT2", "title", has_results=False, enrollment=900))

    with pytest.raises(NoPostedResults) as missing:
        await choose_trial("Study 12", source)

    assert missing.value.nct_id == "NCT2"


async def test_loose_matches_are_not_trials_of_that_name() -> None:
    with pytest.raises(TrialNotFound):
        await choose_trial("KEYNOTE-189", Candidates(candidate("NCT1", None)))


async def test_a_single_match_has_no_alternatives_note() -> None:
    choice = await choose_trial("CheckMate 227", Candidates(candidate("NCT02477826", "acronym")))

    assert choice.alternatives == () and choice.note("CheckMate 227") is None
