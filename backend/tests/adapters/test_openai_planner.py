import json
from datetime import date

import httpx
import pytest
from openai import AsyncOpenAI

from cheiron.adapters.outbound.openai_planner import OpenAIPlanner, render_input
from cheiron.application.planning import Question, StructuredFields
from cheiron.application.ports import PlannerError
from tests.application.planning_factories import cohort, draft, text

pytestmark = pytest.mark.anyio

QUESTION = Question("How are breast cancer trials distributed across phases?")


def planner_answering(handler) -> tuple[OpenAIPlanner, list[dict]]:
    requests: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(request)

    client = AsyncOpenAI(
        api_key="test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(record))
    )
    return OpenAIPlanner(client, "gpt-5.4-mini", reasoning_effort="low", today=lambda: date(2026, 10, 13)), requests


def response_with(output_text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "resp_1",
            "object": "response",
            "created_at": 0,
            "model": "gpt-5.4-mini",
            "status": "completed",
            "output": [
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": output_text, "annotations": []}],
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        },
    )


def test_input_lists_question_structured_fields_and_feedback() -> None:
    question = Question("How has this drug changed over time?", StructuredFields(drug_name="Pembrolizumab"))

    rendered = render_input(question, ["count_by requires dimension."])

    assert rendered == (
        "Question: How has this drug changed over time?\n"
        'Structured fields (applied automatically): {"drug_name": "Pembrolizumab"}\n'
        "\n"
        "Your previous plan was rejected. Return a corrected plan.\n"
        "- count_by requires dimension."
    )


async def test_requests_a_strict_plan_draft_and_parses_it() -> None:
    expected = draft(cohorts=[cohort("Breast cancer", condition=text("breast cancer"))])
    planner, requests = planner_answering(lambda _: response_with(expected.model_dump_json()))

    result = await planner.draft(QUESTION)

    assert result == expected
    [body] = requests
    assert body["model"] == "gpt-5.4-mini"
    assert body["reasoning"] == {"effort": "low"}
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert "Today is 2026-10-13" in body["instructions"]
    assert body["input"].startswith("Question: How are breast cancer trials")


async def test_api_failures_become_planner_errors() -> None:
    planner, _ = planner_answering(lambda _: httpx.Response(500, json={"error": {"message": "boom"}}))

    with pytest.raises(PlannerError, match="unavailable"):
        await planner.draft(QUESTION)


def test_a_follow_up_lists_the_earlier_questions_and_plan_first() -> None:
    question = Question(
        "Only recruiting ones", earlier=("How are breast cancer trials distributed across phases?",), previous_plan='{"kind":"count_by"}'
    )

    assert render_input(question) == (
        "Earlier questions in this conversation, oldest first:\n"
        "- How are breast cancer trials distributed across phases?\n"
        'Plan that answered the last one: {"kind":"count_by"}\n'
        "\n"
        "Question: Only recruiting ones\n"
        "Structured fields (applied automatically): none"
    )
