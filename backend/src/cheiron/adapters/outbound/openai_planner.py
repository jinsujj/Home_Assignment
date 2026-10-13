"""QueryPlanner backed by an OpenAI model with structured outputs.

The response format is PlanDraft's JSON Schema in strict mode, so the model can only return
a well-formed draft whose categorical fields are valid enum values. Grounding and repair are
the application's job (cheiron.application.planning / visualize), not this adapter's.
"""

import json
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import openai
from openai import AsyncOpenAI

from cheiron.application.planning import PlanDraft, Question
from cheiron.application.ports import PlannerError

INSTRUCTIONS = """\
You turn a question about clinical trials registered on ClinicalTrials.gov into an analysis plan.
A program runs the plan against the registry and draws the chart. You never answer the question
yourself and never state numbers.

Choose `kind`:
- count_by: count trials per value of `dimension` (bar chart). Use dimension=start_year for trends
  over time. To compare groups (drug A vs drug B, condition X vs Y), use one cohort per group with
  the same dimension. `split_by` breaks a single cohort down by a second dimension.
- co_occurrence: a network of entities registered on the same trials, e.g. sponsors and drugs
  (source=sponsor, target=drug). Entities of one kind working or used together have that kind at
  both ends: drugs with each other (source=target=drug), sponsors collaborating, hospitals (sites)
  or investigators running trials together (source=target=site or investigator).
  For drug-drug networks set `link`: same_arm when the question is about drugs combined or given
  together (combination studies, regimens, "combined with"), different_arms when it is about drugs
  compared against each other ("versus", head-to-head, comparators), same_trial otherwise. Other
  networks leave `link` null.
- distribution: a histogram of one measure (enrollment = trial size, duration_months, start_year).
- correlation: one point per trial positioned by two measures.
- trial_results: the posted results of ONE named trial ("results of KEYNOTE-189", "adverse events
  in NCT02578680"). Set `trial` to the NCT ID or name exactly as written, `result_focus` to
  outcomes (efficacy, survival, response) or adverse_events (safety, side effects), and `outcome`
  only when the question names a specific outcome ("overall survival"). Leave cohorts empty.

Dimensions: phase, status (overall status), study_type, start_year, country (of trial locations),
condition, intervention, intervention_type, lead_sponsor, lead_sponsor_class (industry, NIH,
other government, university/hospital, ...).

Filters, per cohort. Include only what the question states:
- Never add a filter the question does not state: no default phases, statuses, years, study types
  or countries.
- Every filter carries `quote`: the exact words of the question that state it, copied verbatim.
- Text filters (condition, intervention, sponsor, country): `value` is the term as written in the
  question, keeping brand names, codes and spelling (e.g. "Keytruda"); the registry resolves
  synonyms itself.
- Years filter on trial start dates. Today is {today}; resolve relative periods such as
  "in the last 5 years" against it.
- "recruiting" means status RECRUITING; "phase 2/3" means [PHASE2, PHASE3].
- Structured fields listed with the question are applied to every cohort automatically. Do not
  repeat them as filters, but use them to resolve references such as "this drug" and for labels.

Follow-ups: the input may list earlier questions and the plan that answered the last one. A
question that names only what to change refines that plan: narrowing ("only recruiting ones",
"in the United States", "since 2020"), regrouping ("by country instead") or comparing ("compare
with nivolumab"). Return the whole plan with the change applied, keeping every filter and setting
it does not change; the quotes of kept filters are words of the earlier questions. A question that
names its own subject (another drug, condition or sponsor without "compare") asks something new:
plan it on its own and keep nothing from before.

Labels: short legend names, e.g. "Pembrolizumab" and "Nivolumab" for a comparison.
Use top_n when the question asks for a top N or "the most" of a many-valued dimension
(countries, conditions, sponsors, interventions); 10 is a good default for "the most".

Set answerable=false only when no analysis above can answer the question, and pick `refusal`:
- medical_advice: asks what someone should take or do.
- not_about_trials: unrelated to clinical trials.
- unavailable_data: about trials, but needs data none of the analyses use (eligibility details,
  contacts, prices, individual patients, or results pooled across many trials).
- other: anything else.

`interpretation`: one sentence describing the analysis you planned, including its filters, so the
user can check that the question was understood.
"""


class OpenAIPlanner:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        reasoning_effort: str | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._today = today

    async def draft(self, question: Question, feedback: Sequence[str] = ()) -> PlanDraft:
        options: dict[str, Any] = {}
        if self._reasoning_effort:
            options["reasoning"] = {"effort": self._reasoning_effort}
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=INSTRUCTIONS.format(today=self._today().isoformat()),
                input=render_input(question, feedback),
                text_format=PlanDraft,
                **options,
            )
        except openai.OpenAIError as error:
            raise PlannerError(f"The language model is unavailable: {error}") from error
        if response.output_parsed is None:
            raise PlannerError("The language model returned no plan.")
        return response.output_parsed


def render_input(question: Question, feedback: Sequence[str] = ()) -> str:
    fields = question.fields.described()
    lines = []
    if question.earlier:
        lines += [
            "Earlier questions in this conversation, oldest first:",
            *(f"- {q}" for q in question.earlier),
            f"Plan that answered the last one: {question.previous_plan or 'none'}",
            "",
        ]
    lines += [
        f"Question: {question.text}",
        f"Structured fields (applied automatically): {json.dumps(fields) if fields else 'none'}",
    ]
    if feedback:
        lines += ["", "Your previous plan was rejected. Return a corrected plan.", *(f"- {f}" for f in feedback)]
    return "\n".join(lines)
