"""Use case: answer a natural-language question with a visualization.

The planner drafts a plan; `ground` checks it against the question; a rejected draft gets
one more attempt with the problems as feedback. Only a grounded plan is run, by the same
deterministic pipeline as structured requests.

Measured on the planner eval (tests/llm/test_planner_eval.py): gpt-4.1-mini paraphrased quotes
("trials involving Opdivo" for "Keytruda vs Opdivo"); silently dropping that filter compared
Keytruda with the whole registry. Hence the correction round before anything is dropped.
"""

from dataclasses import dataclass

from cheiron.application.planning import DraftRejected, GroundedPlan, Question, ground
from cheiron.application.ports import QueryPlanner, TrialSource
from cheiron.application.run_plan import DEFAULT_MAX_TRIALS, PlanResult, run_plan
from cheiron.domain.analysis import AnalysisPlan

MAX_ATTEMPTS = 2


class PlanningFailed(Exception):
    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Answer:
    plan: AnalysisPlan
    interpretation: str
    result: PlanResult
    notes: tuple[str, ...]
    """Planning notes (ignored filters, applied fields) and empty-cohort warnings."""


async def plan_question(question: Question, planner: QueryPlanner) -> GroundedPlan:
    """Draft and ground a plan, with one correction round. Raises UnsupportedQuestion or PlanningFailed."""
    feedback: tuple[str, ...] = ()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        draft = await planner.draft(question, feedback)
        try:
            # UnsupportedQuestion propagates: retrying will not help. Unquoted filters get one
            # chance to be corrected and are dropped on the last attempt.
            return ground(draft, question, drop_unquoted=attempt == MAX_ATTEMPTS)
        except DraftRejected as rejected:
            problems = rejected.problems
            feedback = (f"Previous plan: {draft.model_dump_json()}", *problems)
    raise PlanningFailed(problems)


async def visualize(
    question: Question,
    planner: QueryPlanner,
    source: TrialSource,
    max_trials_per_cohort: int = DEFAULT_MAX_TRIALS,
    all_citation_ids: bool = False,
) -> Answer:
    """Cohorts that match nothing are reported by run_plan's notes."""
    grounded = await plan_question(question, planner)
    result = await run_plan(grounded.plan, source, max_trials_per_cohort, all_citation_ids=all_citation_ids)
    return Answer(grounded.plan, grounded.interpretation, result, grounded.notes)
