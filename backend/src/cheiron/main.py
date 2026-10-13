"""Composition root: wires the real adapters into the HTTP app.

Run with: uv run uvicorn cheiron.main:app
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from cheiron.adapters.inbound.http.api import create_app
from cheiron.adapters.outbound.caching import CachingTrialSource
from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        ctgov = CtGovTrialSource(http)
        app.state.trial_source = CachingTrialSource(ctgov, data_version=ctgov.data_version)
        yield


app = create_app(lifespan)
