import json

import httpx
import pytest
from openai import AsyncOpenAI

from cheiron.adapters.outbound.openai_mentions import OpenAIMentionJudge, render_input
from cheiron.application.ports import MentionCase, MentionJudgeError
from cheiron.domain.facets import ARM_GROUP_DESCRIPTION, ELIGIBILITY_CRITERIA
from cheiron.domain.membership import MentionRole
from cheiron.domain.visualization import Evidence
from tests.adapters.test_openai_planner import response_with

pytestmark = pytest.mark.anyio

CASE = MentionCase(
    "NCT1",
    ("pembrolizumab", "Pembrolizumab"),
    (Evidence(ELIGIBILITY_CRITERIA, "* Prior pembrolizumab allowed."), Evidence(ARM_GROUP_DESCRIPTION, "Arm A: omega-3.")),
    "Omega-3 and Immunotherapy",
)


def judge_answering(handler) -> tuple[OpenAIMentionJudge, list[dict]]:
    requests: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(request)

    client = AsyncOpenAI(api_key="test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(record)))
    return OpenAIMentionJudge(client, "gpt-5.4-mini", reasoning_effort="low"), requests


def test_input_lists_each_trials_passages_with_their_section() -> None:
    assert render_input([CASE]) == (
        "Trial NCT1: Omega-3 and Immunotherapy\n"
        "The entity is named: pembrolizumab, Pembrolizumab\n"
        "[eligibility criteria] * Prior pembrolizumab allowed.\n"
        "[arm groups description] Arm A: omega-3."
    )


async def test_requests_strict_verdicts_and_keeps_only_asked_trials() -> None:
    answer = {"verdicts": [
        {"nct_id": "NCT1", "role": "eligibility", "quote": "Prior pembrolizumab allowed"},
        {"nct_id": "NCT9", "role": "studied", "quote": "not asked"},
    ]}
    judge, requests = judge_answering(lambda _: response_with(json.dumps(answer)))

    verdicts = await judge.judge([CASE])

    assert verdicts == {"NCT1": (MentionRole.ELIGIBILITY, "Prior pembrolizumab allowed")}
    request = requests[0]
    assert request["text"]["format"]["type"] == "json_schema" and request["text"]["format"]["strict"] is True
    assert request["reasoning"] == {"effort": "low"}


async def test_api_failures_become_judge_errors() -> None:
    judge, _ = judge_answering(lambda _: httpx.Response(500, json={"error": {"message": "boom"}}))

    with pytest.raises(MentionJudgeError):
        await judge.judge([CASE])
