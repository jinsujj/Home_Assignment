"""HTTP API. Adapters are provided through app.state by the composition root (cheiron.main)."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from cheiron.adapters.inbound.http.schemas import PlanRequest, VisualizationResponse
from cheiron.application.ports import TrialSource, TrialSourceError
from cheiron.application.run_plan import run_plan

router = APIRouter(prefix="/api")


def trial_source(request: Request) -> TrialSource:
    return request.app.state.trial_source


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/plans",
    summary="Run a structured analysis plan",
    description="Executes an analysis plan directly, without the natural-language planner. "
    "Useful for reproducible results and for clients that build plans themselves.",
    responses={502: {"description": "ClinicalTrials.gov rejected the query or is unavailable."}},
)
async def run_structured_plan(
    body: PlanRequest, source: Annotated[TrialSource, Depends(trial_source)]
) -> VisualizationResponse:
    result = await run_plan(body.plan.to_domain(), source, body.max_trials_per_cohort)
    return VisualizationResponse.of(body.plan, result)


def create_app(lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None) -> FastAPI:
    app = FastAPI(
        title="Cheiron",
        version="0.1.0",
        description="Turns questions about clinical trials into visualization specifications backed by ClinicalTrials.gov.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.include_router(router)

    @app.exception_handler(TrialSourceError)
    async def upstream_failed(_: Request, exc: TrialSourceError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    return app
