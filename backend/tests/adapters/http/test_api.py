import httpx
import pytest

from cheiron.adapters.inbound.http.api import create_app
from cheiron.application.ports import TrialSearchResult, TrialSourceError
from cheiron.domain.trial import InterventionType, Phase
from cheiron.domain.trial_filter import TrialFilter
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
                    }
                ],
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
