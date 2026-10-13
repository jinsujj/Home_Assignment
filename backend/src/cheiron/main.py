"""Composition root: wires the real adapters into the HTTP app.

Run with: uv run --env-file ../.env uvicorn cheiron.main:app

Environment:
  OPENAI_API_KEY           enables POST /api/visualize and /api/mentions (POST /api/plans works without it)
  OPENAI_MODEL             planner and mention-judge model, default gpt-5.4-mini
  OPENAI_REASONING_EFFORT  reasoning effort for reasoning models, default low; empty to omit
  OPENAI_MENTION_REASONING_EFFORT  the same for judging mentions (POST /api/mentions), default high
"""

import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI
from openai import AsyncOpenAI

from cheiron.adapters.inbound.http.api import create_app
from cheiron.adapters.outbound.caching import CachingMentionJudge, CachingPlanner, CachingTrialSource
from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.adapters.outbound.openai_mentions import OpenAIMentionJudge
from cheiron.adapters.outbound.openai_planner import OpenAIPlanner
from cheiron.application.options import SearchOptionsProvider

DEFAULT_MODEL = "gpt-5.4-mini"  # most accurate and fastest of those compared in tests/llm/test_planner_eval.py


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
        ctgov = CtGovTrialSource(http)
        app.state.trial_source = CachingTrialSource(ctgov, data_version=ctgov.data_version)
        app.state.options = SearchOptionsProvider(ctgov)

        app.state.planner = app.state.mention_judge = None
        if os.environ.get("OPENAI_API_KEY"):
            client = await stack.enter_async_context(AsyncOpenAI())
            model = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
            effort = os.environ.get("OPENAI_REASONING_EFFORT", "low") or None
            app.state.planner = CachingPlanner(OpenAIPlanner(client, model=model, reasoning_effort=effort))
            mention_effort = os.environ.get("OPENAI_MENTION_REASONING_EFFORT", "high") or None
            app.state.mention_judge = CachingMentionJudge(OpenAIMentionJudge(client, model, reasoning_effort=mention_effort))
        yield


app = create_app(lifespan)
