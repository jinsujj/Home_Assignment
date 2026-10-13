from collections.abc import Callable

import httpx
import pytest

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.application.ports import TrialSourceError
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
