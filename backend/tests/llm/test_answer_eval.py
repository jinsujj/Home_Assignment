"""Answer-writer evaluation against the real model and the live registry: each answer must keep
at least one sentence (every number found in the data it cites) and offer at least one
follow-up that plans.

Run: uv run --env-file ../.env pytest -m llm -k answer -s   (-s prints each answer)
"""

import os
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from openai import AsyncOpenAI

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.adapters.outbound.openai_answers import OpenAIAnswerWriter
from cheiron.adapters.outbound.openai_planner import OpenAIPlanner
from cheiron.application.answers import write_answer
from cheiron.application.planning import Question
from cheiron.application.visualize import plan_question
from cheiron.main import DEFAULT_MODEL

pytestmark = [pytest.mark.llm, pytest.mark.live, pytest.mark.anyio]

QUESTIONS = [
    "How has the number of trials for pembrolizumab changed per year since 2015?",
    "Compare phases for trials involving Keytruda vs Opdivo.",
    "Which countries have the most recruiting trials for lung cancer?",
    "Which drugs are combined with pembrolizumab?",
    "What were the results of the KEYNOTE-189 trial?",
]


@pytest.fixture
async def services() -> AsyncIterator[tuple]:
    model = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "low") or None
    async with AsyncOpenAI() as client, httpx.AsyncClient(timeout=30) as http:
        yield (
            OpenAIPlanner(client, model, reasoning_effort=effort),
            OpenAIAnswerWriter(client, model, reasoning_effort=effort),
            CtGovTrialSource(http),
        )


@pytest.mark.parametrize("text", QUESTIONS, ids=[q[:40] for q in QUESTIONS])
async def test_answers_keep_verified_sentences_and_offer_follow_ups(services, text) -> None:
    planner, writer, source = services
    question = Question(text)
    grounded = await plan_question(question, planner)

    started = time.perf_counter()
    answer = await write_answer(question, grounded.plan, "{}", writer, planner, source)
    print(f"\n{text}\n  {time.perf_counter() - started:.1f} s, dropped {answer.dropped}")
    for sentence in answer.sentences:
        print(f"  * {sentence.text}")
    for follow_up in answer.follow_ups:
        print(f"  -> {follow_up.query}")

    assert answer.sentences
    assert answer.follow_ups
