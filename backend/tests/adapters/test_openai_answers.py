import json

import httpx
import pytest
from openai import AsyncOpenAI

from cheiron.adapters.outbound.openai_answers import OpenAIAnswerWriter, render_input
from cheiron.application.ports import AnswerWriterError
from cheiron.application.writing import AnswerContext, Item
from tests.adapters.test_openai_planner import response_with

pytestmark = pytest.mark.anyio

CONTEXT = AnswerContext(
    "Pembrolizumab trials by phase?",
    "bar_chart: Trials by phase — Pembrolizumab",
    (
        Item("c0", "#/meta/cohorts/0", (("cohort", "Pembrolizumab"), ("matched", 2974), ("analyzed", 2974))),
        Item("r0", "#/visualization/data/0", (("phase", "Phase 2"), ("trial_count", 1777))),
        Item("t0", None, (("note", "175 of 2974 trials have no registered phase."),)),
    ),
)


def writer_answering(handler) -> tuple[OpenAIAnswerWriter, list[dict]]:
    requests: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(request)

    client = AsyncOpenAI(api_key="test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(record)))
    return OpenAIAnswerWriter(client, "gpt-5.4-mini", reasoning_effort="low"), requests


def test_input_lists_the_question_chart_and_items_by_id() -> None:
    assert render_input(CONTEXT) == (
        "Question: Pembrolizumab trials by phase?\n"
        "Chart: bar_chart: Trials by phase — Pembrolizumab\n"
        "Items:\n"
        "c0: cohort=Pembrolizumab; matched=2974; analyzed=2974\n"
        "r0: phase=Phase 2; trial_count=1777\n"
        "t0: note=175 of 2974 trials have no registered phase."
    )


async def test_requests_a_strict_answer_draft_and_parses_it() -> None:
    answer = {"sentences": [{"text": "Phase 2 leads with 1,777 trials.", "refs": ["r0"]}], "follow_ups": ["Only recruiting trials"]}
    writer, requests = writer_answering(lambda _: response_with(json.dumps(answer)))

    draft = await writer.write(CONTEXT)

    assert (draft.sentences[0].refs, draft.follow_ups) == (["r0"], ["Only recruiting trials"])
    assert requests[0]["text"]["format"]["strict"] is True and requests[0]["reasoning"] == {"effort": "low"}


async def test_api_failures_become_writer_errors() -> None:
    writer, _ = writer_answering(lambda _: httpx.Response(500, json={"error": {"message": "boom"}}))

    with pytest.raises(AnswerWriterError):
        await writer.write(CONTEXT)
