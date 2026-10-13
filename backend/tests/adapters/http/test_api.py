import httpx
import pytest

from cheiron.adapters.inbound.http.api import create_app
from cheiron.application.options import SearchOptionsProvider
from cheiron.application.planning import REFUSAL_MESSAGES, Refusal
from cheiron.application.ports import PlannerError, TrialCandidate, TrialSearchResult, TrialSourceError
from cheiron.domain.results import GroupValue, Outcome, OutcomeType, PostedResults
from cheiron.domain.trial import InterventionType, Phase
from cheiron.domain.trial_filter import TrialFilter
from tests.application.planning_factories import cohort, draft
from tests.application.test_options import FakeVocabulary
from tests.domain.factories import drug, trial

PEMBRO = {"label": "Pembrolizumab", "filter": {"intervention": "pembrolizumab"}}


class FakeSource:
    def __init__(self, trials=(), total: int | None = None, error: Exception | None = None) -> None:
        self.trials, self.total, self.error = tuple(trials), total, error
        self.calls: list[tuple[TrialFilter, int, bool]] = []

    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        self.calls.append((criteria, max_trials, include_sites))
        if self.error:
            raise self.error
        return TrialSearchResult(self.trials, self.total if self.total is not None else len(self.trials))


pytestmark = pytest.mark.anyio


def client_for(source: FakeSource) -> httpx.AsyncClient:
    app = create_app()
    app.state.trial_source = source
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health() -> None:
    assert (await client_for(FakeSource()).get("/api/health")).json() == {"status": "ok"}


async def test_runs_a_plan_and_returns_spec_with_citations_and_meta() -> None:
    source = FakeSource([trial("NCT1", phases=(Phase.PHASE2,)), trial("NCT2")], total=40)

    response = await client_for(source).post(
        "/api/plans",
        json={"plan": {"kind": "count_by", "cohorts": [PEMBRO], "dimension": "phase"}, "max_trials_per_cohort": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert source.calls == [(TrialFilter(intervention="pembrolizumab"), 2, False)]
    viz = body["visualization"]
    assert viz["type"] == "bar_chart"
    assert viz["encoding"]["x"] == {
        "field": "phase",
        "type": "ordinal",
        "title": "Phase",
        "order": ["Phase 2"],
        "unit": None,
        "time_unit": None,
    }
    assert viz["data"] == [
        {
            "phase": "Phase 2",
            "trial_count": 1,
            "citations": {
                "total": 1,
                "items": [
                    {
                        "nct_id": "NCT1",
                        "title": "Title of NCT1",
                        "url": "https://clinicaltrials.gov/study/NCT1",
                        "evidence": [{"field": "protocolSection.designModule.phases", "value": "PHASE2"}],
                        "excerpt": "phases: PHASE2",
                    }
                ],
                "nct_ids": None,
            },
        }
    ]
    meta = body["meta"]
    assert meta["source"] == "clinicaltrials.gov"
    assert meta["plan"]["cohorts"][0]["filter"]["intervention"] == "pembrolizumab"
    assert meta["cohorts"] == [{"label": "Pembrolizumab", "matched": 40, "analyzed": 2, "truncated": True}]
    assert "1 of 2 trials have no registered phase and are not shown." in meta["notes"]
    assert any(n.startswith("Analyzed the first 2 of 40") for n in meta["notes"])


async def test_network_data_is_nodes_and_edges() -> None:
    source = FakeSource([trial("NCT1", interventions=(drug("A"), drug("B", InterventionType.BIOLOGICAL)))])

    body = (await client_for(source).post(
        "/api/plans",
        json={"plan": {"kind": "co_occurrence", "cohort": PEMBRO, "source": "drug", "target": "drug"}},
    )).json()

    assert body["visualization"]["type"] == "network_graph"
    assert [n["id"] for n in body["visualization"]["data"]["nodes"]] == ["drug:a", "drug:b"]
    assert body["visualization"]["data"]["edges"][0]["citations"]["total"] == 1


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        ({"kind": "count_by", "cohorts": [PEMBRO], "dimension": "colour"}, "dimension"),
        ({"kind": "count_by", "cohorts": [], "dimension": "phase"}, "at least 1"),
        ({"kind": "count_by", "cohorts": [PEMBRO, PEMBRO], "dimension": "phase"}, "unique"),
        ({"kind": "count_by", "cohorts": [PEMBRO], "dimension": "start_year", "top_n": 5}, "start_year"),
        ({"kind": "correlation", "cohort": PEMBRO, "x": "enrollment", "y": "enrollment"}, "different"),
        ({"kind": "distribution", "cohort": {"filter": {"start_year_from": 2020, "start_year_to": 2010}}, "measure": "enrollment"}, "after"),
        ({"kind": "pie", "cohort": PEMBRO}, "kind"),
        ({"kind": "distribution", "cohort": PEMBRO, "measure": "enrollment", "colour": "red"}, "colour"),
    ],
)
async def test_invalid_plans_are_rejected_with_an_explanation(plan: dict, message: str) -> None:
    source = FakeSource()

    response = await client_for(source).post("/api/plans", json={"plan": plan})

    assert response.status_code == 422
    assert message in response.text
    assert source.calls == []


async def test_upstream_failure_is_a_bad_gateway() -> None:
    source = FakeSource(error=TrialSourceError("ClinicalTrials.gov unavailable after 4 attempts (503)"))

    response = await client_for(source).post(
        "/api/plans", json={"plan": {"kind": "distribution", "cohort": PEMBRO, "measure": "enrollment"}}
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "ClinicalTrials.gov unavailable after 4 attempts (503)"}


# --- POST /api/visualize --------------------------------------------------------------------


class ScriptedPlanner:
    def __init__(self, *drafts, error: Exception | None = None) -> None:
        self.drafts, self.error = list(drafts), error
        self.questions = []

    async def draft(self, question, feedback=()):
        self.questions.append(question)
        if self.error:
            raise self.error
        return self.drafts.pop(0)


def client_with_planner(source: FakeSource, planner) -> httpx.AsyncClient:
    app = create_app()
    app.state.trial_source = source
    app.state.planner = planner
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


PHASES_OF_THIS_DRUG = draft(
    interpretation="Trials of Pembrolizumab counted by phase.",
    cohorts=[cohort("Pembrolizumab", phases={"values": ["PHASE3"], "quote": "late phase"})],
)


async def test_visualize_answers_a_question_with_its_interpretation() -> None:
    source = FakeSource([trial("NCT1", phases=(Phase.PHASE2,))])
    planner = ScriptedPlanner(PHASES_OF_THIS_DRUG, PHASES_OF_THIS_DRUG)

    response = await client_with_planner(source, planner).post(
        "/api/visualize",
        json={"query": "How are trials of this drug distributed across phases?", "drug_name": "Pembrolizumab"},
    )

    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["query"] == "How are trials of this drug distributed across phases?"
    assert meta["interpretation"] == "Trials of Pembrolizumab counted by phase."
    assert meta["plan"]["kind"] == "count_by"
    assert meta["plan"]["cohorts"][0]["filter"]["intervention"] == "Pembrolizumab"
    assert meta["plan"]["cohorts"][0]["filter"]["phases"] == []
    assert meta["notes"][:2] == [
        "Ignored a phases filter on the cohort: its justification 'late phase' does not appear in the question.",
        "Applied the request's structured fields to every cohort: drug_name=Pembrolizumab.",
    ]
    assert source.calls[0][0] == TrialFilter(intervention="Pembrolizumab")
    assert planner.questions[0].fields.drug_name == "Pembrolizumab"


async def test_visualize_refuses_unanswerable_questions() -> None:
    planner = ScriptedPlanner(draft(answerable=False, refusal="medical_advice", kind=None))
    source = FakeSource()

    response = await client_with_planner(source, planner).post(
        "/api/visualize", json={"query": "Should I take metformin for weight loss?"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "unsupported_question",
        "reason": "medical_advice",
        "message": REFUSAL_MESSAGES[Refusal.MEDICAL_ADVICE],
    }
    assert source.calls == []


async def test_visualize_reports_plans_that_stay_invalid() -> None:
    planner = ScriptedPlanner(draft(dimension=None), draft(dimension=None))

    response = await client_with_planner(FakeSource(), planner).post("/api/visualize", json={"query": "trials?"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "plan_rejected"
    assert response.json()["detail"]["problems"] == ["count_by requires dimension."]


@pytest.mark.parametrize(
    "body",
    [{}, {"query": ""}, {"query": "x", "start_year": 2020, "end_year": 2010}, {"query": "x", "phases": ["PHASE9"]}],
)
async def test_visualize_validates_the_request(body: dict) -> None:
    response = await client_with_planner(FakeSource(), ScriptedPlanner()).post("/api/visualize", json=body)

    assert response.status_code == 422


async def test_visualize_without_a_configured_planner_is_unavailable() -> None:
    response = await client_for(FakeSource()).post("/api/visualize", json={"query": "trials by phase"})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


async def test_visualize_reports_an_unreachable_planner() -> None:
    planner = ScriptedPlanner(error=PlannerError("The language model is unavailable: timeout"))

    response = await client_with_planner(FakeSource(), planner).post("/api/visualize", json={"query": "trials by phase"})

    assert response.status_code == 503
    assert response.json() == {"detail": "The language model is unavailable: timeout"}


async def test_options_list_choices_for_building_filters() -> None:
    app = create_app()
    app.state.options = SearchOptionsProvider(FakeVocabulary())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    body = (await client.get("/api/options")).json()

    assert body["countries"][1] == {"value": "South Korea", "label": "South Korea", "trials": 17784}
    assert body["phases"][2] == {"value": "PHASE2", "label": "Phase 2", "trials": None}
    assert set(body) == {"countries", "conditions", "interventions", "sponsors", "phases", "statuses"}


# --- single-trial results -------------------------------------------------------------------


class ResultsSource(FakeSource):
    def __init__(self, results=None, candidates=()) -> None:
        super().__init__()
        self.results, self.candidates = results, candidates

    async def find_trials(self, name):
        return self.candidates

    async def posted_results(self, nct_id):
        return self.results


MAIN = TrialCandidate("NCT02578680", "Main trial", None, True, 616, "title")
EXTENSION = TrialCandidate("NCT03950674", "Japan extension", None, True, 40, "study_id")
POSTED = PostedResults(
    "NCT02578680",
    "Main trial",
    None,
    (Outcome(OutcomeType.PRIMARY, "Overall Survival", None, "MEDIAN", "95% Confidence Interval", "Months", "21 months", (GroupValue("Control", "11.3", "8.7", "15.1"),)),),
    (),
)


async def test_plans_endpoint_charts_a_trials_posted_results() -> None:
    response = await client_for(ResultsSource(POSTED, (MAIN, EXTENSION))).post(
        "/api/plans", json={"plan": {"kind": "trial_results", "trial": "KEYNOTE-189"}}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["visualization"]["title"] == "Primary outcomes — KEYNOTE-189 (NCT02578680)"
    assert body["visualization"]["encoding"]["y_lower"]["field"] == "lower"
    assert body["meta"]["trial"] == {
        "nct_id": "NCT02578680",
        "title": "Main trial",
        "url": "https://clinicaltrials.gov/study/NCT02578680",
        "alternatives": [
            {"nct_id": "NCT03950674", "title": "Japan extension", "url": "https://clinicaltrials.gov/study/NCT03950674", "enrollment": 40}
        ],
    }
    assert body["meta"]["cohorts"] == []


async def test_visualize_passes_a_chosen_nct_id_to_the_plan() -> None:
    planner = ScriptedPlanner(draft(kind="trial_results", cohorts=[], dimension=None, trial={"value": "KEYNOTE-189", "quote": "KEYNOTE-189"}))

    response = await client_with_planner(ResultsSource(POSTED), planner).post(
        "/api/visualize", json={"query": "Results of KEYNOTE-189?", "nct_id": "NCT02578680"}
    )

    assert response.json()["meta"]["plan"] == {"kind": "trial_results", "trial": "NCT02578680", "focus": "outcomes", "outcome": None}


@pytest.mark.parametrize(
    ("source", "code", "message"),
    [
        (ResultsSource(None, ()), "trial_not_found", "No trial registered as 'KEYNOTE-999' was found"),
        (ResultsSource(None, (TrialCandidate("NCT05908799", "Emulation", None, False, 1854, "title"),)), "no_posted_results", "NCT05908799 (Emulation) has not posted results"),
    ],
)
async def test_trials_that_cannot_answer_explain_why(source, code: str, message: str) -> None:
    response = await client_for(source).post("/api/plans", json={"plan": {"kind": "trial_results", "trial": "KEYNOTE-999"}})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert message in response.json()["detail"]["message"]


async def test_nct_id_field_is_validated() -> None:
    response = await client_with_planner(FakeSource(), ScriptedPlanner()).post("/api/visualize", json={"query": "x", "nct_id": "KEYNOTE-189"})

    assert response.status_code == 422


async def test_responses_carry_alternative_views_with_their_notes() -> None:
    source = FakeSource([trial("NCT1", phases=(Phase.PHASE2,))])

    body = (await client_for(source).post("/api/plans", json={"plan": {"kind": "count_by", "cohorts": [PEMBRO], "dimension": "phase"}})).json()

    [donut] = body["alternatives"]
    assert donut["type"] == "donut_chart"
    assert donut["data"][0]["share"] == 100.0
    assert donut["data"][0]["citations"]["total"] == 1
    assert donut["notes"][0] == "Each slice is its share of the counts in the bar chart."


async def test_every_contributing_trial_is_listed_on_request() -> None:
    source = FakeSource([trial(f"NCT{i}", phases=(Phase.PHASE2,)) for i in range(7)])
    plan = {"kind": "count_by", "cohorts": [PEMBRO], "dimension": "phase"}

    response = await client_for(source).post("/api/plans", json={"plan": plan, "all_citation_ids": True})

    body = response.json()
    for view in [body["visualization"], *body["alternatives"]]:
        cited = view["data"][0]["citations"]
        assert (cited["total"], len(cited["items"])) == (7, 5)
        assert cited["nct_ids"] == [f"NCT{i}" for i in range(7)]
