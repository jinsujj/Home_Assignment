"""From a question to an AnalysisPlan the deterministic pipeline can run.

A planner (an LLM) writes a PlanDraft: the plan, plus for every filter the words of the
question that state it. `ground` checks the draft against the question before anything runs:

- a filter whose quote is not in the question was invented, so it is dropped (and reported);
- a free-text value must be taken from its quote, so search terms are the user's own words;
- kind-specific fields and the domain's invariants must hold, otherwise the draft is
  rejected with problems the planner can correct.

PlanDraft is a Pydantic model because it doubles as the JSON Schema that constrains the
LLM's output: every categorical field is an enum, so the model can only pick valid values.
"""

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cheiron.domain.analysis import (
    AnalysisPlan,
    Cohort,
    CoOccurrence,
    Correlation,
    CountBy,
    Dimension,
    Distribution,
    Entity,
    Measure,
)
from cheiron.domain.trial import Phase, Status, StudyType
from cheiron.domain.trial_filter import TrialFilter

# --- What the planner writes --------------------------------------------------------------


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextFilter(_Draft):
    value: str = Field(description="The term exactly as written in the question, e.g. 'lung cancer' or 'Keytruda'.")
    quote: str = Field(description="The exact words of the question that state this filter.")


class PhaseFilter(_Draft):
    values: list[Phase]
    quote: str = Field(description="The exact words of the question that state these phases.")


class StatusFilter(_Draft):
    values: list[Status]
    quote: str = Field(description="The exact words of the question that state these statuses.")


class StudyTypeFilter(_Draft):
    value: StudyType
    quote: str = Field(description="The exact words of the question that state the study type.")


class YearFilter(_Draft):
    value: int = Field(description="A trial start year.")
    quote: str = Field(description="The exact words of the question that state this year or period.")


class FilterDraft(_Draft):
    """Only the filters the question states; null for everything else."""

    condition: TextFilter | None
    intervention: TextFilter | None = Field(description="Drug or other intervention.")
    sponsor: TextFilter | None
    country: TextFilter | None
    phases: PhaseFilter | None
    statuses: StatusFilter | None
    study_type: StudyTypeFilter | None
    start_year_from: YearFilter | None = Field(description="Earliest trial start year, inclusive.")
    start_year_to: YearFilter | None = Field(description="Latest trial start year, inclusive.")


class CohortDraft(_Draft):
    label: str = Field(description="Short legend name such as 'Pembrolizumab'; empty for a single unnamed cohort.")
    filter: FilterDraft


class PlanDraft(_Draft):
    interpretation: str = Field(
        description="One sentence describing the planned analysis and its filters, for the user to check."
    )
    answerable: bool = Field(description="False if no analysis below can answer the question from registry data.")
    unsupported_reason: str | None = Field(description="Why the question cannot be answered; null if answerable.")
    kind: Literal["count_by", "co_occurrence", "distribution", "correlation"] | None
    cohorts: list[CohortDraft] = Field(description="One cohort, or one per compared group (count_by only, up to 5).")
    dimension: Dimension | None = Field(description="count_by: what to count trials by; start_year for trends.")
    split_by: Dimension | None = Field(description="count_by with one cohort: optional second dimension.")
    top_n: int | None = Field(description="count_by: keep the N most frequent values, if the question asks for a top N.")
    source: Entity | None = Field(description="co_occurrence: first node kind.")
    target: Entity | None = Field(description="co_occurrence: second node kind; equal to source for e.g. drug-drug.")
    measure: Measure | None = Field(description="distribution: the numeric attribute to histogram.")
    x: Measure | None = Field(description="correlation: horizontal measure.")
    y: Measure | None = Field(description="correlation: vertical measure.")


# --- The question ----------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuredFields:
    """Optional request fields; they apply to every cohort and override the planner's filters."""

    drug_name: str | None = None
    condition: str | None = None
    sponsor: str | None = None
    country: str | None = None
    phases: frozenset[Phase] = frozenset()
    statuses: frozenset[Status] = frozenset()
    start_year: int | None = None
    end_year: int | None = None

    def described(self) -> dict[str, object]:
        return {
            name: sorted(str(v) for v in value) if isinstance(value, frozenset) else value
            for name, value in dataclasses.asdict(self).items()
            if value not in (None, frozenset())
        }


@dataclass(frozen=True)
class Question:
    text: str
    fields: StructuredFields = StructuredFields()


# --- Grounding -------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroundedPlan:
    plan: AnalysisPlan
    interpretation: str
    notes: tuple[str, ...]


class UnsupportedQuestion(Exception):
    def __init__(self, reason: str, interpretation: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.interpretation = interpretation


class DraftRejected(Exception):
    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


_TEXT_FIELDS = ("condition", "intervention", "sponsor", "country")
_OTHER_FIELDS = ("phases", "statuses", "study_type", "start_year_from", "start_year_to")
_STRUCTURED = {  # TrialFilter field -> structured field overriding it
    "intervention": "drug_name",
    "condition": "condition",
    "sponsor": "sponsor",
    "country": "country",
    "phases": "phases",
    "statuses": "statuses",
    "start_year_from": "start_year",
    "start_year_to": "end_year",
}


def ground(draft: PlanDraft, question: Question, *, drop_unquoted: bool = False) -> GroundedPlan:
    """Check a draft against the question. Raises UnsupportedQuestion or DraftRejected.

    A filter whose quote is not in the question is a problem to correct, or with
    `drop_unquoted` (the last attempt) is dropped and reported in the notes.
    """
    if not draft.answerable:
        raise UnsupportedQuestion(draft.unsupported_reason or "The question cannot be answered.", draft.interpretation)

    problems: list[str] = []
    notes: list[str] = []
    text = _fold(question.text)
    structured = {f: getattr(question.fields, s) for f, s in _STRUCTURED.items()}
    given = {f for f, v in structured.items() if v not in (None, frozenset())}

    cohorts = []
    for number, cohort in enumerate(draft.cohorts, start=1):
        where = f"cohort {number}" if len(draft.cohorts) > 1 else "the cohort"
        values: dict[str, object] = {}
        for name in _TEXT_FIELDS + _OTHER_FIELDS:
            proposed = getattr(cohort.filter, name)
            if proposed is None or name in given:
                continue
            if _fold(proposed.quote) not in text:
                if drop_unquoted:
                    notes.append(
                        f"Ignored a {name.replace('_', ' ')} filter on {where}: its justification "
                        f"'{proposed.quote}' does not appear in the question."
                    )
                else:
                    problems.append(
                        f"{where}: the quote '{proposed.quote}' for {name} is not in the question; "
                        "copy the question's exact words, or remove the filter if the question does not state it."
                    )
                continue
            if name in _TEXT_FIELDS and _fold(proposed.value) not in _fold(proposed.quote):
                problems.append(f"{where}: {name} '{proposed.value}' must be words taken from its quote '{proposed.quote}'.")
                continue
            values[name] = frozenset(proposed.values) if name in ("phases", "statuses") else proposed.value
        values |= {name: structured[name] for name in given}
        try:
            criteria = TrialFilter(**values)
        except ValueError as error:
            problems.append(f"{where}: {error}")
            continue
        cohorts.append(Cohort(cohort.label.strip() or _default_label(criteria, len(draft.cohorts)), criteria))

    if len(cohorts) > 1:
        # A compared cohort without a filter of its own is "all trials" (e.g. after dropping an
        # unquoted filter), which would silently compare one group with the whole registry.
        shared = TrialFilter(**{name: structured[name] for name in given})
        for cohort in cohorts:
            if cohort.filter == shared:
                problems.append(f"Compared cohort '{cohort.label}' has no filter of its own, so it would select all trials.")
        filters = [c.filter for c in cohorts]
        if len(set(filters)) < len(filters):
            problems.append("Compared cohorts must differ in their filters; two cohorts select the same trials.")

    if given:
        applied = ", ".join(f"{k}={v}" for k, v in question.fields.described().items())
        notes.append(f"Applied the request's structured fields to every cohort: {applied}.")

    plan = None if problems else _build(draft, tuple(cohorts), problems)
    if problems or plan is None:
        raise DraftRejected(problems)
    return GroundedPlan(plan, draft.interpretation, tuple(notes))


def _build(draft: PlanDraft, cohorts: tuple[Cohort, ...], problems: list[str]) -> AnalysisPlan | None:
    required = {
        "count_by": ("dimension",),
        "co_occurrence": ("source", "target"),
        "distribution": ("measure",),
        "correlation": ("x", "y"),
    }
    if draft.kind is None:
        problems.append("kind is required for an answerable question.")
        return None
    missing = [name for name in required[draft.kind] if getattr(draft, name) is None]
    if missing:
        problems.append(f"{draft.kind} requires {', '.join(missing)}.")
        return None
    if draft.kind != "count_by" and len(cohorts) != 1:
        problems.append(f"{draft.kind} takes exactly one cohort; comparisons of several cohorts need count_by.")
        return None
    try:
        match draft.kind:
            case "count_by":
                return CountBy(cohorts, draft.dimension, draft.split_by, draft.top_n)
            case "co_occurrence":
                return CoOccurrence(cohorts[0], draft.source, draft.target)
            case "distribution":
                return Distribution(cohorts[0], draft.measure)
            case "correlation":
                return Correlation(cohorts[0], draft.x, draft.y)
    except ValueError as error:
        problems.append(str(error))
        return None


def _default_label(criteria: TrialFilter, cohort_count: int) -> str:
    named = criteria.intervention or criteria.condition or criteria.sponsor or criteria.country
    return named or ("" if cohort_count == 1 else "All trials")


def _fold(text: str) -> str:
    """Case-, spacing- and edge-punctuation-insensitive form for containment checks."""
    return " ".join(re.sub(r"[“”‘’\"']", "", text).casefold().split()).strip(" .,;:!?()")
