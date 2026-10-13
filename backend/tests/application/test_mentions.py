import pytest

from cheiron.application.mentions import explain_mentions
from cheiron.application.ports import MentionCase
from cheiron.domain.facets import BRIEF_SUMMARY, BRIEF_TITLE, ELIGIBILITY_CRITERIA
from cheiron.domain.membership import MentionRole
from cheiron.domain.visualization import Evidence

pytestmark = pytest.mark.anyio

SUMMARY = "Anti-PD-1 drugs such as pembrolizumab remove the brakes. This study tests omega-3."
TEXTS = {
    "NCT1": {BRIEF_SUMMARY: (SUMMARY,)},
    "NCT2": {ELIGIBILITY_CRITERIA: ("* Prior   treatment with Pembrolizumab.",)},
    "NCT3": {BRIEF_SUMMARY: ("This study tests omega-3.",)},
    "NCT4": {BRIEF_SUMMARY: ("Standard immunotherapy [e.g., pembrolizumab, etc.\\] is continued.",)},
}


class Source:
    async def trial_texts(self, nct_ids):
        return {n: {BRIEF_TITLE: (f"Title of {n}: omega-3 in melanoma",), **TEXTS[n]} for n in nct_ids if n in TEXTS}


class Judge:
    def __init__(self, answers) -> None:
        self.answers, self.cases = answers, []

    async def judge(self, cases):
        self.cases += cases
        return self.answers


async def test_verdicts_keep_the_registered_passage_their_quote_comes_from() -> None:
    judge = Judge({
        "NCT1": (MentionRole.BACKGROUND, "drugs such as pembrolizumab"),
        "NCT2": (MentionRole.ELIGIBILITY, "prior treatment with pembrolizumab"),  # case and spacing differ
    })

    verdicts = await explain_mentions(["NCT1", "NCT2", "NCT3"], ["pembrolizumab"], Source(), judge)

    assert [(v.nct_id, v.role, v.quote, v.passages) for v in verdicts] == [
        ("NCT1", MentionRole.BACKGROUND, Evidence(BRIEF_SUMMARY, "Anti-PD-1 drugs such as pembrolizumab remove the brakes."), 1),
        ("NCT2", MentionRole.ELIGIBILITY, Evidence(ELIGIBILITY_CRITERIA, "* Prior   treatment with Pembrolizumab."), 1),
        ("NCT3", MentionRole.UNCLEAR, None, 0),  # no passage names it: not sent to the model
    ]
    assert [c.nct_id for c in judge.cases] == ["NCT1", "NCT2"]


async def test_a_quote_not_in_the_record_makes_the_role_unclear() -> None:
    judge = Judge({
        "NCT1": (MentionRole.STUDIED, "patients receive pembrolizumab every three weeks"),  # invented
        "NCT2": (MentionRole.ELIGIBILITY, "Pembrolizumab"),  # too short to show a role
    })

    verdicts = await explain_mentions(["NCT1", "NCT2"], ["pembrolizumab"], Source(), judge)

    assert [(v.role, v.quote) for v in verdicts] == [(MentionRole.UNCLEAR, None), (MentionRole.UNCLEAR, None)]


async def test_cases_carry_every_passage_naming_the_entity() -> None:
    judge = Judge({})

    await explain_mentions(["NCT1"], ["pembrolizumab", "omega-3"], Source(), judge)

    assert judge.cases == [
        MentionCase(
            "NCT1",
            ("pembrolizumab", "omega-3"),
            (
                Evidence(BRIEF_TITLE, "Title of NCT1: omega-3 in melanoma"),  # the title names omega-3 too
                Evidence(BRIEF_SUMMARY, "Anti-PD-1 drugs such as pembrolizumab remove the brakes."),
                Evidence(BRIEF_SUMMARY, "This study tests omega-3."),
            ),
            "Title of NCT1: omega-3 in melanoma",
        )
    ]


async def test_markdown_escapes_in_the_record_do_not_hide_a_quote() -> None:
    judge = Judge({"NCT4": (MentionRole.GIVEN_ALONGSIDE, "pembrolizumab, etc.] is continued")})

    [verdict] = await explain_mentions(["NCT4"], ["pembrolizumab"], Source(), judge)

    assert verdict.role is MentionRole.GIVEN_ALONGSIDE


async def test_a_section_label_copied_into_the_quote_is_ignored() -> None:
    judge = Judge({"NCT2": (MentionRole.ELIGIBILITY, "[eligibility criteria] * Prior treatment with pembrolizumab.")})

    [verdict] = await explain_mentions(["NCT2"], ["pembrolizumab"], Source(), judge)

    assert verdict.role is MentionRole.ELIGIBILITY


async def test_a_quote_from_the_title_counts_as_registered_text() -> None:
    judge = Judge({"NCT1": (MentionRole.BACKGROUND, "omega-3 in melanoma")})

    [verdict] = await explain_mentions(["NCT1"], ["pembrolizumab"], Source(), judge)

    assert verdict.quote == Evidence(BRIEF_TITLE, "Title of NCT1: omega-3 in melanoma")
