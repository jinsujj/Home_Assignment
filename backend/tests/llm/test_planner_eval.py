"""Planner evaluation against the real model: question -> grounded plan, as the API plans it.

Run: uv run --env-file ../.env pytest -m llm   (OPENAI_MODEL / OPENAI_REASONING_EFFORT select the model)
Calls OpenAI only; ClinicalTrials.gov is not queried. Each case asserts what a correct plan
must contain, including that no unrequested filter was added, and refusals assert their reason.
"""

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from openai import AsyncOpenAI

from cheiron.adapters.outbound.openai_planner import OpenAIPlanner
from cheiron.application.planning import Question, Refusal, StructuredFields, UnsupportedQuestion
from cheiron.application.visualize import plan_question
from cheiron.domain.analysis import (
    CoOccurrence,
    Correlation,
    CountBy,
    Dimension,
    Distribution,
    Entity,
    Link,
    Measure,
    ResultFocus,
    TrialResults,
)
from cheiron.domain.trial import Phase, Status
from cheiron.domain.trial_filter import TrialFilter
from cheiron.main import DEFAULT_MODEL

pytestmark = [pytest.mark.llm, pytest.mark.anyio]

TODAY = date(2026, 10, 13)


@pytest.fixture
async def planner() -> AsyncIterator[OpenAIPlanner]:
    async with AsyncOpenAI() as client:  # closed within the test's own event loop
        yield OpenAIPlanner(
            client,
            os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
            reasoning_effort=os.environ.get("OPENAI_REASONING_EFFORT", "low") or None,
            today=lambda: TODAY,
        )


def filters(plan) -> list[TrialFilter]:
    return [c.filter for c in plan.cohorts]


def folded(criteria: TrialFilter) -> TrialFilter:
    """Case-insensitive comparison of free-text filters."""
    lower = {k: (getattr(criteria, k) or None) and getattr(criteria, k).casefold() for k in ("condition", "intervention", "sponsor", "country")}
    return TrialFilter(**(vars(criteria) | lower))


CASES = [
    (
        "How has the number of trials for pembrolizumab changed per year since 2015?",
        CountBy,
        {"dimension": Dimension.START_YEAR},
        [TrialFilter(intervention="pembrolizumab", start_year_from=2015)],
    ),
    (
        "How many trials started each year for type 2 diabetes?",
        CountBy,
        {"dimension": Dimension.START_YEAR},
        [TrialFilter(condition="type 2 diabetes")],
    ),
    (
        "How are breast cancer trials distributed across phases?",
        CountBy,
        {"dimension": Dimension.PHASE},
        [TrialFilter(condition="breast cancer")],
    ),
    (
        "What are the most common intervention types for asthma trials?",
        CountBy,
        {"dimension": Dimension.INTERVENTION_TYPE},
        [TrialFilter(condition="asthma")],
    ),
    (
        "Compare phases for trials involving Keytruda vs Opdivo.",
        CountBy,
        {"dimension": Dimension.PHASE},
        [TrialFilter(intervention="keytruda"), TrialFilter(intervention="opdivo")],
    ),
    (
        "Compare sponsor categories across asthma and COPD trials.",
        CountBy,
        {"dimension": Dimension.LEAD_SPONSOR_CLASS},
        [TrialFilter(condition="asthma"), TrialFilter(condition="copd")],
    ),
    (
        "Which countries have the most recruiting trials for lung cancer?",
        CountBy,
        {"dimension": Dimension.COUNTRY},
        [TrialFilter(condition="lung cancer", statuses=frozenset({Status.RECRUITING}))],
    ),
    (
        "Show a network of sponsors and drugs for melanoma trials.",
        CoOccurrence,
        {"source": Entity.SPONSOR, "target": Entity.DRUG, "link": Link.SAME_TRIAL},
        [TrialFilter(condition="melanoma")],
    ),
    (
        "Which drugs frequently co-occur in combination studies for pancreatic cancer?",
        CoOccurrence,
        {"source": Entity.DRUG, "target": Entity.DRUG, "link": Link.SAME_ARM},
        [TrialFilter(condition="pancreatic cancer")],
    ),
    (
        "Which drugs frequently co-occur in combination studies (drug ↔ drug network)?",
        CoOccurrence,
        {"source": Entity.DRUG, "target": Entity.DRUG, "link": Link.SAME_ARM},
        [TrialFilter()],
    ),
    (
        "Which drugs are compared against pembrolizumab in head-to-head trials?",
        CoOccurrence,
        {"source": Entity.DRUG, "target": Entity.DRUG, "link": Link.DIFFERENT_ARMS},
        [TrialFilter(intervention="pembrolizumab")],
    ),
    (
        "Which hospitals run pembrolizumab trials together?",
        CoOccurrence,
        {"source": Entity.SITE, "target": Entity.SITE, "link": Link.SAME_TRIAL},
        [TrialFilter(intervention="pembrolizumab")],
    ),
    (
        "How large are phase 3 obesity trials?",
        Distribution,
        {"measure": Measure.ENROLLMENT},
        [TrialFilter(condition="obesity", phases=frozenset({Phase.PHASE3}))],
    ),
    (
        "Do longer phase 3 pembrolizumab trials enroll more patients?",
        Correlation,
        {"x": Measure.DURATION_MONTHS, "y": Measure.ENROLLMENT},
        [TrialFilter(intervention="pembrolizumab", phases=frozenset({Phase.PHASE3}))],
    ),
]


@pytest.mark.parametrize(("question", "kind", "fields", "expected_filters"), CASES, ids=[c[0][:50] for c in CASES])
async def test_plans_the_question(planner, question, kind, fields, expected_filters) -> None:
    plan = (await plan_question(Question(question), planner)).plan

    assert isinstance(plan, kind)
    for name, value in fields.items():
        assert getattr(plan, name) == value, name
    assert sorted(map(folded, filters(plan)), key=repr) == sorted(expected_filters, key=repr)


async def test_this_drug_refers_to_the_structured_field(planner) -> None:
    question = Question("How has the number of trials for this drug changed over time?", StructuredFields(drug_name="Pembrolizumab"))

    grounded = await plan_question(question, planner)

    assert isinstance(grounded.plan, CountBy) and grounded.plan.dimension is Dimension.START_YEAR
    assert filters(grounded.plan) == [TrialFilter(intervention="Pembrolizumab")]


async def test_relative_periods_resolve_against_today(planner) -> None:
    plan = (await plan_question(Question("How many trials started in the last 5 years for long COVID, by status?"), planner)).plan

    assert isinstance(plan, CountBy) and plan.dimension is Dimension.STATUS
    [criteria] = filters(plan)
    assert criteria.condition.casefold() == "long covid"
    assert criteria.start_year_from in (2021, 2022)
    assert criteria.start_year_to in (None, 2026)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What were the results of the KEYNOTE-189 trial?", TrialResults("KEYNOTE-189")),
        ("What was the overall survival in NCT02578680?", TrialResults("NCT02578680", ResultFocus.OUTCOMES, "overall survival")),
        ("What side effects were reported in CheckMate 227?", TrialResults("CheckMate 227", ResultFocus.ADVERSE_EVENTS)),
    ],
)
async def test_plans_a_named_trials_results(planner, question, expected) -> None:
    plan = (await plan_question(Question(question), planner)).plan

    assert isinstance(plan, TrialResults)
    assert (plan.trial.casefold(), plan.focus, plan.outcome and plan.outcome.casefold()) == (
        expected.trial.casefold(),
        expected.focus,
        expected.outcome,
    )


@pytest.mark.parametrize(
    ("question", "reason"),
    [
        ("Should I take metformin for weight loss?", Refusal.MEDICAL_ADVICE),
        ("What is the capital of France?", Refusal.NOT_ABOUT_TRIALS),
    ],
)
async def test_refuses_questions_no_analysis_can_answer(planner, question, reason) -> None:
    with pytest.raises(UnsupportedQuestion) as refused:
        await plan_question(Question(question), planner)

    assert refused.value.reason is reason
