from collections.abc import Callable

import httpx
import pytest

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.application.ports import TermCount, TrialSourceError, Vocabulary
from cheiron.domain.analysis import Dimension
from cheiron.domain.trial import Phase
from cheiron.domain.trial_filter import TrialFilter
from tests.conftest import load_fixture

PAGE1 = load_fixture("ctgov/pembrolizumab_page1.json")
PAGE2 = load_fixture("ctgov/pembrolizumab_page2.json")
CRITERIA = TrialFilter(intervention="pembrolizumab")

pytestmark = pytest.mark.anyio


def _source(handler: Callable[[httpx.Request], httpx.Response]) -> CtGovTrialSource:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CtGovTrialSource(http, retry_delays=(0, 0, 0))


def _paged(requests: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    """Serves the two recorded pages as the whole result set; ignores pageSize."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        token = request.url.params.get("pageToken")
        if token is None:
            return httpx.Response(200, json=PAGE1)
        assert token == PAGE1["nextPageToken"]
        return httpx.Response(200, json={**PAGE2, "nextPageToken": None})

    return handler


async def test_follows_page_tokens_and_reports_total() -> None:
    requests: list[httpx.Request] = []

    result = await _source(_paged(requests)).search(CRITERIA, max_trials=6)

    assert [t.nct_id for t in result.trials][:3] == ["NCT03772899", "NCT05508867", "NCT06558799"]
    assert len(result.trials) == 6
    assert result.total_count == 2974
    assert result.truncated
    assert len(requests) == 2


async def test_later_pages_repeat_first_page_params() -> None:
    requests: list[httpx.Request] = []

    await _source(_paged(requests)).search(CRITERIA, max_trials=6)

    first, second = (dict(r.url.params) for r in requests)
    assert first.pop("countTotal") == "true"
    assert second.pop("pageToken") == PAGE1["nextPageToken"]
    first.pop("pageSize"), second.pop("pageSize")
    assert first == second
    assert first["query.intr"] == "pembrolizumab"


async def test_stops_at_max_trials_and_requests_only_what_is_missing() -> None:
    requests: list[httpx.Request] = []

    result = await _source(_paged(requests)).search(CRITERIA, max_trials=4)

    assert len(result.trials) == 4
    assert [r.url.params["pageSize"] for r in requests] == ["4", "1"]


async def test_page_size_is_capped_at_api_maximum() -> None:
    requests: list[httpx.Request] = []

    await _source(_paged(requests)).search(CRITERIA, max_trials=5000)

    assert requests[0].url.params["pageSize"] == "1000"


async def test_stops_when_no_next_page() -> None:
    last_page = {**PAGE1, "nextPageToken": None}
    result = await _source(lambda _: httpx.Response(200, json=last_page)).search(CRITERIA, max_trials=100)

    assert len(result.trials) == 3


async def test_retries_rate_limit_then_succeeds() -> None:
    responses = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json={**PAGE1, "nextPageToken": None})])

    result = await _source(lambda _: next(responses)).search(CRITERIA, max_trials=3)

    assert len(result.trials) == 3


async def test_gives_up_after_retries() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(TrialSourceError, match="after 4 attempts"):
        await _source(handler).search(CRITERIA, max_trials=3)
    assert calls == 4


async def test_bad_request_fails_fast_with_api_message() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="Error parsing query in advanced filter: missing ')'")

    with pytest.raises(TrialSourceError, match="missing '\\)'"):
        await _source(handler).search(CRITERIA, max_trials=3)
    assert calls == 1


async def test_network_errors_are_retried_then_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(TrialSourceError, match="unreachable"):
        await _source(handler).search(CRITERIA, max_trials=3)


async def test_rejects_non_positive_max_trials() -> None:
    with pytest.raises(ValueError):
        await _source(_paged([])).search(CRITERIA, max_trials=0)


async def test_site_fields_are_requested_only_on_demand() -> None:
    requests: list[httpx.Request] = []
    source = _source(_paged(requests))

    await source.search(CRITERIA, max_trials=3)
    await source.search(CRITERIA, max_trials=3, include_sites=True)

    without, with_sites = (set(r.url.params["fields"].split(",")) for r in (requests[0], requests[-1]))
    assert {"LocationFacility", "LocationCity"} <= with_sites
    assert not {"LocationFacility", "LocationCity"} & without
    assert with_sites - without == {"LocationFacility", "LocationCity"}


async def test_data_version_is_the_published_snapshot_timestamp() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/version"
        return httpx.Response(200, json={"apiVersion": "2.0.5", "dataTimestamp": "2026-10-09T09:00:05"})

    assert await _source(handler).data_version() == "2026-10-09T09:00:05"


async def test_common_terms_come_from_registry_wide_field_stats() -> None:
    stats = [
        {"piece": "LocationCountry", "topValues": [{"value": "United States", "studiesCount": 196050}]},
        {"piece": "Condition", "topValues": [{"value": "Breast Cancer", "studiesCount": 8921}]},
        {"piece": "InterventionName", "topValues": [{"value": "Pembrolizumab", "studiesCount": 2000}]},
        {"piece": "LeadSponsorName", "topValues": []},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/stats/field/values"
        assert request.url.params["fields"] == "LocationCountry,Condition,InterventionName,LeadSponsorName"
        return httpx.Response(200, json=stats)

    terms = await _source(handler).common_terms()

    assert terms[Vocabulary.COUNTRY] == (TermCount("United States", 196050),)
    assert terms[Vocabulary.INTERVENTION] == (TermCount("Pembrolizumab", 2000),)
    assert terms[Vocabulary.SPONSOR] == ()


async def test_find_trials_searches_acronyms_apart_and_name_variants() -> None:
    pages = load_fixture("ctgov/keynote189_candidates.json")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        acronym_only = request.url.params["filter.advanced"].startswith("AREA[Acronym]")
        return httpx.Response(200, json=pages["by_acronym" if acronym_only else "by_id_or_title"])

    candidates = await _source(handler).find_trials("keynote 189")

    assert {c.nct_id for c in candidates} >= {"NCT02578680", "NCT03950674"}
    acronym_query, other_query = (r.url.params["filter.advanced"] for r in requests)
    assert acronym_query == 'AREA[Acronym]"keynote 189" OR AREA[Acronym]"keynote-189"'
    assert 'AREA[OfficialTitle]"keynote-189"' in other_query and 'AREA[SecondaryId]"keynote 189"' in other_query


async def test_posted_results_of_a_missing_or_unreported_trial_are_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("NCT00000000"):
            return httpx.Response(404, text="Not found")
        return httpx.Response(200, json={"protocolSection": {"identificationModule": {"nctId": "NCT05908799"}}, "hasResults": False})

    source = _source(handler)

    assert await source.posted_results("NCT00000000") is None
    assert await source.posted_results("NCT05908799") is None


async def test_posted_results_are_mapped() -> None:
    study = load_fixture("ctgov/keynote189_results.json")

    results = await _source(lambda _: httpx.Response(200, json=study)).posted_results("NCT02578680")

    assert results.nct_id == "NCT02578680" and len(results.outcomes) == 7


async def test_counts_each_category_with_one_count_only_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"totalCount": len(requests) * 10, "studies": []})

    criteria = TrialFilter(condition="breast cancer", phases=frozenset({Phase.PHASE2, Phase.PHASE3}))
    counts = await _source(handler).count_by(criteria, Dimension.PHASE, ["PHASE2", "PHASE3"])

    assert {k: c.trials for k, c in counts.items()} == {"PHASE2": 10, "PHASE3": 20}
    # The query that reproduces a count lists the trials too (default pages, with titles).
    reproduced = httpx.URL(counts["PHASE2"].query)
    assert reproduced.path == "/api/v2/studies"
    assert reproduced.params["filter.advanced"] == "AREA[Phase](PHASE2 OR PHASE3) AND AREA[Phase]PHASE2"
    assert (reproduced.params["countTotal"], reproduced.params["fields"]) == ("true", "NCTId,BriefTitle")
    params = requests[0].url.params
    # The category is added to the cohort's own criteria, so a Phase 2/3 trial counts under both.
    assert params["filter.advanced"] == "AREA[Phase](PHASE2 OR PHASE3) AND AREA[Phase]PHASE2"
    assert (params["query.cond"], params["countTotal"], params["pageSize"]) == ("breast cancer", "true", "1")


async def test_dimensions_the_registry_cannot_count_send_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert await _source(handler).count_by(CRITERIA, Dimension.START_YEAR, ["2020"]) is None


def _ids(*ids: str) -> list[dict]:
    return [{"protocolSection": {"identificationModule": {"nctId": i}}} for i in ids]


async def test_mention_only_trials_are_listed_page_by_page_up_to_a_limit() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("pageToken") is None:
            return httpx.Response(200, json={"totalCount": 3, "studies": _ids("NCT1", "NCT2"), "nextPageToken": "t"})
        return httpx.Response(200, json={"studies": _ids("NCT3")})

    source = _source(handler)

    assert await source.mentioned_only(CRITERIA, "intervention", limit=3) == {"NCT1", "NCT2", "NCT3"}
    assert requests[0].url.params["filter.advanced"].startswith("NOT (AREA[InterventionName](pembrolizumab)")
    assert requests[0].url.params["fields"] == "NCTId"
    assert await source.mentioned_only(CRITERIA, "intervention", limit=2) is None  # more than the limit
    assert await source.mentioned_only(CRITERIA, "condition", limit=3) == frozenset()  # no condition filter
    assert len(requests) == 3


async def test_texts_of_cited_trials_are_fetched_by_id_in_chunks() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        ids = request.url.params["filter.ids"].split(",")
        studies = [{"protocolSection": {"identificationModule": {"nctId": i, "briefTitle": f"Title {i}"}}} for i in ids]
        return httpx.Response(200, json={"studies": studies})

    ids = [f"NCT{i:08d}" for i in range(250)]
    texts = await _source(handler).trial_texts(ids)

    assert [len(r.url.params["filter.ids"].split(",")) for r in requests] == [200, 50]
    assert texts["NCT00000007"] == {"protocolSection.identificationModule.briefTitle": ("Title NCT00000007",)}


async def test_every_trial_behind_a_category_is_listed_up_to_a_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filter.advanced"] == "AREA[Phase]PHASE3"
        return httpx.Response(200, json={"totalCount": 2, "studies": _ids("NCT1", "NCT2")})

    source = _source(handler)

    assert await source.category_ids(TrialFilter(), Dimension.PHASE, "PHASE3", limit=2) == ("NCT1", "NCT2")
    assert await source.category_ids(TrialFilter(), Dimension.PHASE, "PHASE3", limit=1) is None
