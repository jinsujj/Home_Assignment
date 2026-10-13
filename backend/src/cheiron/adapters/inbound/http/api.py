"""HTTP API. Adapters are provided through app.state by the composition root (cheiron.main)."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from cheiron.adapters.inbound.http.schemas import (
    MentionsRequest,
    MentionsResponse,
    MentionVerdictOut,
    PlanRequest,
    VisualizationResponse,
    VisualizeRequest,
    plan_from_domain,
)
from cheiron.application.options import SearchOptions, SearchOptionsProvider
from cheiron.application.planning import UnsupportedQuestion
from cheiron.application.mentions import explain_mentions
from cheiron.application.ports import MentionJudge, MentionJudgeError, PlannerError, QueryPlanner, Registry, TrialSourceError
from cheiron.application.run_plan import run_plan
from cheiron.application.trial_lookup import NoPostedResults, TrialNotFound
from cheiron.application.visualize import PlanningFailed, visualize
from cheiron.domain.visualization import STUDY_URL

router = APIRouter(prefix="/api")


def trial_source(request: Request) -> Registry:
    return request.app.state.trial_source


def query_planner(request: Request) -> QueryPlanner:
    planner = getattr(request.app.state, "planner", None)
    if planner is None:
        raise HTTPException(503, "Natural-language questions need OPENAI_API_KEY; POST /api/plans works without it.")
    return planner


def mention_judge(request: Request) -> MentionJudge:
    judge = getattr(request.app.state, "mention_judge", None)
    if judge is None:
        raise HTTPException(503, "Judging mentions needs OPENAI_API_KEY.")
    return judge


def options_provider(request: Request) -> SearchOptionsProvider:
    return request.app.state.options


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/version",
    summary="The registry data snapshot being served",
    description="ClinicalTrials.gov publishes new data about once per US business day. Answers carry the "
    "snapshot they were computed from in `meta.data_version`; a different value here means newer data.",
)
async def data_version(source: Annotated[Registry, Depends(trial_source)]) -> dict[str, str | None]:
    return {"data_version": await source.data_version()}


@router.get(
    "/options",
    summary="Choices for building filters",
    description="Every country in the registry (exact spellings, with trial counts), the most common "
    "conditions, interventions and sponsors as suggestions, and the phase and status codes.",
)
async def search_options(provider: Annotated[SearchOptionsProvider, Depends(options_provider)]) -> SearchOptions:
    return await provider.get()


@router.post(
    "/visualize",
    summary="Answer a question about clinical trials with a visualization",
    description="An LLM drafts an analysis plan, which is checked against the question before it runs. "
    "`meta.interpretation` and `meta.plan` show how the question was understood.",
    responses={
        422: {"description": "Invalid request, a question no analysis can answer, or no valid plan could be made."},
        502: {"description": "ClinicalTrials.gov rejected the query or is unavailable."},
        503: {"description": "The language model is not configured or unavailable."},
    },
)
async def visualize_question(
    body: VisualizeRequest,
    source: Annotated[Registry, Depends(trial_source)],
    planner: Annotated[QueryPlanner, Depends(query_planner)],
) -> VisualizationResponse:
    answer = await visualize(
        body.to_question(), planner, source, body.max_trials_per_cohort, all_citation_ids=body.all_citation_ids
    )
    return VisualizationResponse.of(
        plan_from_domain(answer.plan),
        answer.result,
        query=body.query,
        interpretation=answer.interpretation,
        planning_notes=answer.notes,
        all_citation_ids=body.all_citation_ids,
    )


@router.post(
    "/plans",
    summary="Run a structured analysis plan",
    description="Executes an analysis plan directly, without the natural-language planner. "
    "Useful for reproducible results and for clients that build plans themselves.",
    responses={502: {"description": "ClinicalTrials.gov rejected the query or is unavailable."}},
)
async def run_structured_plan(
    body: PlanRequest, source: Annotated[Registry, Depends(trial_source)]
) -> VisualizationResponse:
    result = await run_plan(
        body.plan.to_domain(), source, body.max_trials_per_cohort, all_citation_ids=body.all_citation_ids
    )
    return VisualizationResponse.of(body.plan, result, all_citation_ids=body.all_citation_ids)


@router.post(
    "/mentions",
    summary="Judge why trials mention a filtered entity",
    description="For trials whose citations list a term under `mentioned_only` (or any others), a language model "
    "reads the passages of each record that name the entity and says what it is to the trial: studied, given "
    "alongside, eligibility, background or unclear. Every verdict quotes the record; a quote not found there makes "
    "the role `unclear`.",
    responses={503: {"description": "The language model is not configured or unavailable."}},
)
async def judge_mentions(
    body: MentionsRequest,
    source: Annotated[Registry, Depends(trial_source)],
    judge: Annotated[MentionJudge, Depends(mention_judge)],
) -> MentionsResponse:
    verdicts = await explain_mentions(body.nct_ids, body.names, source, judge)
    return MentionsResponse(
        verdicts=[MentionVerdictOut(nct_id=v.nct_id, role=v.role, quote=v.quote, passages=v.passages) for v in verdicts]
    )


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
    # Citations repeat titles and passages across rows and views: a drug network shrinks ~10x.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.exception_handler(TrialSourceError)
    async def upstream_failed(_: Request, exc: TrialSourceError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(PlannerError)
    async def planner_failed(_: Request, exc: PlannerError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(MentionJudgeError)
    async def judge_failed(_: Request, exc: MentionJudgeError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(UnsupportedQuestion)
    async def unsupported(_: Request, exc: UnsupportedQuestion) -> JSONResponse:
        detail = {"code": "unsupported_question", "reason": exc.reason, "message": exc.message}
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(TrialNotFound)
    async def trial_not_found(_: Request, exc: TrialNotFound) -> JSONResponse:
        detail = {
            "code": "trial_not_found",
            "message": f"No trial registered as '{exc.name}' was found on ClinicalTrials.gov; try its NCT ID.",
        }
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(NoPostedResults)
    async def no_results(_: Request, exc: NoPostedResults) -> JSONResponse:
        detail = {
            "code": "no_posted_results",
            "message": f"{exc.nct_id}{f' ({exc.title})' if exc.title else ''} has not posted results on ClinicalTrials.gov.",
            "trial": {"nct_id": exc.nct_id, "url": STUDY_URL.format(nct_id=exc.nct_id)},
        }
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(PlanningFailed)
    async def unplannable(_: Request, exc: PlanningFailed) -> JSONResponse:
        detail = {
            "code": "plan_rejected",
            "message": "The question could not be turned into a valid analysis; try rephrasing it.",
            "problems": list(exc.problems),
        }
        return JSONResponse(status_code=422, content={"detail": detail})

    return app
