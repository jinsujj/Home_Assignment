from collections.abc import Sequence

import pytest

from cheiron.application.planning import PlanDraft, Question, UnsupportedQuestion
from cheiron.application.ports import TrialSearchResult
from cheiron.application.visualize import PlanningFailed, plan_question, visualize
from cheiron.domain.trial import Phase
from cheiron.domain.trial_filter import TrialFilter
from tests.application.planning_factories import cohort, draft, text
from tests.domain.factories import trial

pytestmark = pytest.mark.anyio

QUESTION = Question("How are breast cancer trials distributed across phases?")
GOOD = draft(cohorts=[cohort("Breast cancer", condition=text("breast cancer"))])
UNQUOTED = draft(cohorts=[cohort("Breast cancer", condition=text("breast cancer"), phases={"values": ["PHASE3"], "quote": "phase 3"})])


class ScriptedPlanner:
    """Returns the given drafts in order and records the feedback it received."""

    def __init__(self, *drafts: PlanDraft) -> None:
        self.drafts = list(drafts)
        self.feedback: list[tuple[str, ...]] = []

    async def draft(self, question: Question, feedback: Sequence[str] = ()) -> PlanDraft:
        self.feedback.append(tuple(feedback))
        return self.drafts.pop(0)


class FakeSource:
    def __init__(self, total: int = 1) -> None:
        self.total = total

    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        trials = (trial("NCT1", phases=(Phase.PHASE2,)),) if self.total else ()
        return TrialSearchResult(trials, self.total)

    async def count_by(self, criteria, dimension, keys):
        return None


async def test_a_grounded_first_draft_is_used_as_is() -> None:
    planner = ScriptedPlanner(GOOD)

    grounded = await plan_question(QUESTION, planner)

    assert grounded.plan.cohorts[0].filter == TrialFilter(condition="breast cancer")
    assert planner.feedback == [()]


async def test_a_rejected_draft_gets_one_correction_round_with_the_problems() -> None:
    planner = ScriptedPlanner(UNQUOTED, GOOD)

    grounded = await plan_question(QUESTION, planner)

    assert grounded.notes == ()
    previous, problem = planner.feedback[1]
    assert previous.startswith("Previous plan: {")
    assert "the quote 'phase 3' for phases is not in the question" in problem


async def test_unquoted_filters_are_dropped_on_the_last_attempt() -> None:
    planner = ScriptedPlanner(UNQUOTED, UNQUOTED)

    grounded = await plan_question(QUESTION, planner)

    assert grounded.plan.cohorts[0].filter == TrialFilter(condition="breast cancer")
    assert "Ignored a phases filter" in grounded.notes[0]


async def test_planning_fails_after_the_correction_round() -> None:
    incomplete = draft(dimension=None)
    planner = ScriptedPlanner(incomplete, incomplete)

    with pytest.raises(PlanningFailed) as failed:
        await plan_question(QUESTION, planner)

    assert failed.value.problems == ("count_by requires dimension.",)


async def test_unsupported_questions_are_not_retried() -> None:
    planner = ScriptedPlanner(draft(answerable=False, refusal="medical_advice", kind=None))

    with pytest.raises(UnsupportedQuestion):
        await plan_question(Question("Should I take metformin for weight loss?"), planner)
    assert len(planner.feedback) == 1


async def test_visualize_runs_the_grounded_plan() -> None:
    answer = await visualize(QUESTION, ScriptedPlanner(GOOD), FakeSource())

    assert answer.interpretation == "Trials by phase."
    assert answer.result.visualization.title == "Trials by phase — Breast cancer"
    assert answer.notes == ()


async def test_visualize_warns_about_cohorts_that_match_nothing() -> None:
    answer = await visualize(QUESTION, ScriptedPlanner(GOOD), FakeSource(total=0))

    assert answer.notes == ("No trials matched Breast cancer; check the spelling of its filters.",)
