import pytest

from cheiron.application.answers import answer_context, check, write_answer
from cheiron.application.planning import Question, Refusal
from cheiron.application.ports import TrialSearchResult
from cheiron.application.run_plan import CohortReport, PlanResult
from cheiron.application.writing import AnswerDraft, Item
from cheiron.domain.analysis import Cohort, CountBy, Dimension
from cheiron.domain.trial import Phase
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Channel, ChartType, Citation, Citations, FieldType, Visualization
from tests.application.planning_factories import cohort, draft, text
from tests.application.test_run_plan import FakeSource
from tests.domain.factories import trial

pytestmark = pytest.mark.anyio

CITED = Citations(1, (Citation.of("NCT1", "A trial", ()),))
PEMBRO = Cohort("Pembrolizumab", TrialFilter(intervention="pembrolizumab"))


def result(data, notes=(), note_citations=()) -> PlanResult:
    viz = Visualization(ChartType.BAR, "Trials by phase — Pembrolizumab", {}, data, notes, note_citations)
    return PlanResult(viz, (CohortReport("Pembrolizumab", PEMBRO.filter, 2974, 2974),), ())


def sentences(*pairs) -> AnswerDraft:
    return AnswerDraft(sentences=[{"text": t, "refs": list(r)} for t, r in pairs], follow_ups=[])


def test_items_are_the_cohorts_rows_and_notes_with_where_they_sit_in_the_response() -> None:
    rows = [{"phase": "Phase 2", "trial_count": 1777, "citations": CITED}, {"phase": "Phase 3", "trial_count": 369, "citations": CITED}]
    counted = "175 of 2974 trials have no registered phase and are not shown."

    context = answer_context("Pembrolizumab trials by phase?", result(rows, ("Showing every phase.", counted), ((counted, CITED),)))

    assert context.chart == "bar_chart: Trials by phase — Pembrolizumab"
    assert [(i.id, i.pointer) for i in context.items] == [
        ("c0", "#/meta/cohorts/0"),
        ("r0", "#/visualization/data/0"),
        ("r1", "#/visualization/data/1"),
        ("t0", None),  # a note without citations can be cited but not opened
        ("t1", "#/meta/note_citations/0/citations"),
    ]
    assert context.items[1].fields == (("phase", "Phase 2"), ("trial_count", 1777), ("rank_by_trials", 1))


def test_network_nodes_and_links_are_items_of_their_own() -> None:
    network = {"nodes": [{"id": "drug:a", "trial_count": 9, "citations": CITED}], "edges": [{"source": "drug:a", "target": "drug:b", "trial_count": 4, "citations": CITED}]}

    context = answer_context("Drugs combined with a?", result(network))

    assert [(i.id, i.pointer) for i in context.items[1:]] == [("n0", "#/visualization/data/nodes/0"), ("e0", "#/visualization/data/edges/0")]


CONTEXT = answer_context(
    "How have pembrolizumab trials changed since 2015?",
    result([{"phase": "Phase 2", "trial_count": 1777, "citations": CITED}, {"phase": "Phase 3", "trial_count": 369, "citations": CITED}]),
)


def test_a_sentence_is_kept_when_its_numbers_are_in_the_items_it_cites() -> None:
    kept, dropped = check(sentences(("Phase 2 leads with 1,777 trials of 2,974 since 2015.", ["r0", "c0"])), CONTEXT)

    # "2" comes from the label "Phase 2", 2015 from the question, and the counts from the items
    assert (dropped, kept[0].refs) == (0, ("#/visualization/data/0", "#/meta/cohorts/0"))


@pytest.mark.parametrize(
    ("text", "refs"),
    [
        ("Phase 3 has 369 trials.", ["r0"]),  # 369 is in r1, which it does not cite
        ("Phase 2 has 1,800 trials.", ["r0"]),  # rounded
        ("Phase 2 is 60% of all trials.", ["r0", "c0"]),  # computed
        ("Phase 2 leads.", []),  # cites nothing
        ("Phase 2 leads with 1,777 trials.", ["r0", "r9"]),  # cites an unknown item
    ],
)
def test_a_sentence_is_dropped_when_a_number_is_not_in_the_items_it_cites(text, refs) -> None:
    kept, dropped = check(sentences((text, refs)), CONTEXT)

    assert (kept, dropped) == ((), 1)


class Writer:
    def __init__(self, follow_ups: list[str]) -> None:
        self.follow_ups = follow_ups
        self.contexts = []

    async def write(self, context):
        self.contexts.append(context)
        return AnswerDraft(sentences=[{"text": "There are 2 trials.", "refs": ["c0"]}], follow_ups=self.follow_ups)


class Planner:
    """Plans by question text; questions it does not know are refused."""

    def __init__(self, drafts: dict) -> None:
        self.drafts = drafts
        self.questions: list[Question] = []

    async def draft(self, question, feedback=()):
        self.questions.append(question)
        return self.drafts.get(question.text) or draft(answerable=False, refusal=Refusal.OTHER, kind=None)


async def test_follow_ups_are_offered_only_when_they_plan_to_another_analysis() -> None:
    by_status = draft(interpretation="By status.", cohorts=[cohort(intervention=text("pembrolizumab"))], dimension="status")
    same = draft(cohorts=[cohort(intervention=text("pembrolizumab"))], dimension="phase")
    planner = Planner({"By status instead": by_status, "Statuses, please": by_status, "Phases again": same})
    writer = Writer(["By status instead", "Phases again", "What should I take?", "Statuses, please"])
    plan = CountBy((Cohort("", PEMBRO.filter),), Dimension.PHASE)
    source = FakeSource({PEMBRO.filter: TrialSearchResult((trial("NCT1", phases=(Phase.PHASE2,)), trial("NCT2")), total_count=2)})
    question = Question("Pembrolizumab trials by phase?", earlier=("Pembrolizumab trials?",), previous_plan="{}")

    answer = await write_answer(question, plan, '{"kind":"count_by"}', writer, planner, source)

    assert [s.text for s in answer.sentences] == ["There are 2 trials."]
    # The same analysis again, a refusal, and a second question for the status chart are left
    # out; only the first three suggestions are planned.
    assert [(f.query, f.interpretation) for f in answer.follow_ups] == [("By status instead", "By status.")]
    assert [q.text for q in planner.questions] == ["By status instead", "Phases again", "What should I take?"]
    asked = planner.questions[0]
    assert (asked.earlier, asked.previous_plan) == (("Pembrolizumab trials?", "Pembrolizumab trials by phase?"), '{"kind":"count_by"}')


def test_items_carry_only_scalar_fields() -> None:
    item = answer_context("q", result([{"phase": "Phase 2", "groups": ["a"], "trial_count": 3, "citations": CITED}])).items[1]

    assert item == Item("r0", "#/visualization/data/0", (("phase", "Phase 2"), ("trial_count", 3), ("rank_by_trials", 1)))


def test_rows_are_ranked_by_trials_within_their_series() -> None:
    rows = [
        {"phase": "Phase 2", "cohort": "A", "trial_count": 4590, "citations": CITED},
        {"phase": "Phase 2", "cohort": "B", "trial_count": 10, "citations": CITED},
        {"phase": "Not applicable", "cohort": "A", "trial_count": 4962, "citations": CITED},
        {"phase": "Not applicable", "cohort": "B", "trial_count": 30, "citations": CITED},
    ]
    viz = Visualization(ChartType.GROUPED_BAR, "t", {"series": Channel("cohort", FieldType.NOMINAL, "Cohort")}, rows, ())
    context = answer_context("q", PlanResult(viz, (), ()))

    assert [dict(i.fields)["rank_by_trials"] for i in context.items] == [2, 2, 1, 1]
