"""Composition root: wires the real adapters into the HTTP app.

Run with: uv run --env-file ../.env uvicorn cheiron.main:app

Environment:
  OPENAI_API_KEY           enables POST /api/visualize (POST /api/plans works without it)
  OPENAI_MODEL             planner model, default gpt-5.4-mini
  OPENAI_REASONING_EFFORT  reasoning effort for reasoning models, default low; empty to omit
"""

import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI
from openai import AsyncOpenAI

from cheiron.adapters.inbound.http.api import create_app
from cheiron.adapters.outbound.caching import CachingTrialSource
from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.adapters.outbound.openai_planner import OpenAIPlanner

DEFAULT_MODEL = "gpt-5.4-mini"  # most accurate and fastest of those compared in tests/llm/test_planner_eval.py


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
        ctgov = CtGovTrialSource(http)
        app.state.trial_source = CachingTrialSource(ctgov, data_version=ctgov.data_version)

        app.state.planner = None
        if os.environ.get("OPENAI_API_KEY"):
            client = await stack.enter_async_context(AsyncOpenAI())
            app.state.planner = OpenAIPlanner(
                client,
                model=os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
                reasoning_effort=os.environ.get("OPENAI_REASONING_EFFORT", "low") or None,
            )
        yield


app = create_app(lifespan)
