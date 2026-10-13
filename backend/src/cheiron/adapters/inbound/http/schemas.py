"""HTTP request and response schemas.

The plan models are the public form of the domain's AnalysisPlan. They also serve as the
LLM planner's output schema, so field descriptions are written for both readers.
Domain invariants (e.g. split_by with several cohorts) surface as 422 validation errors.
"""

from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cheiron.application.planning import Question, StructuredFields
from cheiron.application.run_plan import DEFAULT_MAX_TRIALS, PlanResult
from cheiron.domain.analysis import (
    MAX_COHORTS,
    AnalysisPlan,
    Cohort,
    CoOccurrence,
    Correlation,
    CountBy,
    Dimension,
    Distribution,
    Entity,
    Measure,
    ResultFocus,
    TrialResults,
)
from cheiron.domain.trial import Phase, Status, StudyType
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import STUDY_URL, Channel, ChartType

MAX_TRIALS_LIMIT = 10_000


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilterIn(_Schema):
    """Which trials to include. All given criteria must hold; list criteria match any value."""

    condition: str | None = Field(None, max_length=200, description="Disease or condition, e.g. 'breast cancer'.")
    intervention: str | None = Field(
        None,
        max_length=200,
        description="Drug or other intervention. Brand names and codes resolve to the same trials, e.g. 'Keytruda'.",
    )
    sponsor: str | None = Field(None, max_length=200, description="Sponsor or collaborator organisation.")
    country: str | None = Field(None, max_length=100, description="Country of a trial location, e.g. 'United States'.")
    phases: list[Phase] = Field(default_factory=list, description="Trials in any of these phases.")
    statuses: list[Status] = Field(default_factory=list, description="Trials with any of these overall statuses.")
    study_type: StudyType | None = None
    start_year_from: int | None = Field(None, ge=1900, le=2100, description="Earliest start year, inclusive.")
    start_year_to: int | None = Field(None, ge=1900, le=2100, description="Latest start year, inclusive.")

    @classmethod
    def from_domain(cls, criteria: TrialFilter) -> Self:
        return cls(
            condition=criteria.condition,
            intervention=criteria.intervention,
            sponsor=criteria.sponsor,
            country=criteria.country,
            phases=sorted(criteria.phases),
            statuses=sorted(criteria.statuses),
            study_type=criteria.study_type,
            start_year_from=criteria.start_year_from,
            start_year_to=criteria.start_year_to,
        )

    def to_domain(self) -> TrialFilter:
        return TrialFilter(
            condition=self.condition,
            intervention=self.intervention,
            sponsor=self.sponsor,
            country=self.country,
            phases=frozenset(self.phases),
            statuses=frozenset(self.statuses),
            study_type=self.study_type,
            start_year_from=self.start_year_from,
            start_year_to=self.start_year_to,
        )


class CohortIn(_Schema):
    """A labelled set of trials. Comparisons use one cohort per compared group."""

    label: str = Field("", max_length=80, description="Name shown in titles and legends, e.g. 'Pembrolizumab'.")
    filter: FilterIn = Field(default_factory=FilterIn)

    @classmethod
    def from_domain(cls, cohort: Cohort) -> Self:
        return cls(label=cohort.label, filter=FilterIn.from_domain(cohort.filter))

    def to_domain(self) -> Cohort:
        return Cohort(self.label, self.filter.to_domain())


class _PlanIn(_Schema):
    @model_validator(mode="after")
    def _check_domain_rules(self) -> Self:
        self.to_domain()  # raises ValueError with the domain's explanation
        return self

    def to_domain(self) -> Any:
        raise NotImplementedError


class CountByIn(_PlanIn):
    """Count trials per value of a dimension -> bar chart, grouped bar chart or time series."""

    kind: Literal["count_by"]
    cohorts: list[CohortIn] = Field(min_length=1, max_length=MAX_COHORTS, description="One cohort, or one per compared group.")
    dimension: Dimension = Field(description="What to count trials by; start_year gives a time series.")
    split_by: Dimension | None = Field(None, description="Second dimension for a single cohort, shown as series.")
    top_n: int | None = Field(None, ge=1, le=100, description="Keep only the N most frequent values.")

    def to_domain(self) -> CountBy:
        return CountBy(tuple(c.to_domain() for c in self.cohorts), self.dimension, self.split_by, self.top_n)


class CoOccurrenceIn(_PlanIn):
    """Network of entities registered on the same trials; source == target links one kind."""

    kind: Literal["co_occurrence"]
    cohort: CohortIn
    source: Entity
    target: Entity
    max_nodes: int = Field(30, ge=2, le=200)
    min_shared_trials: int = Field(1, ge=1, description="Hide links shared by fewer trials.")

    def to_domain(self) -> CoOccurrence:
        return CoOccurrence(self.cohort.to_domain(), self.source, self.target, self.max_nodes, self.min_shared_trials)


class DistributionIn(_PlanIn):
    """Histogram of a numeric trial attribute."""

    kind: Literal["distribution"]
    cohort: CohortIn
    measure: Measure
    bins: int = Field(20, ge=1, le=100, description="Approximate number of bins.")

    def to_domain(self) -> Distribution:
        return Distribution(self.cohort.to_domain(), self.measure, self.bins)


class CorrelationIn(_PlanIn):
    """Scatter plot of two numeric trial attributes, one point per trial."""

    kind: Literal["correlation"]
    cohort: CohortIn
    x: Measure
    y: Measure

    def to_domain(self) -> Correlation:
        return Correlation(self.cohort.to_domain(), self.x, self.y)


class TrialResultsIn(_PlanIn):
    """Posted results of one trial -> grouped bar chart of its outcomes or adverse events."""

    kind: Literal["trial_results"]
    trial: str = Field(min_length=1, max_length=200, description="NCT ID, acronym or name, e.g. 'KEYNOTE-189'.")
    focus: ResultFocus = ResultFocus.OUTCOMES
    outcome: str | None = Field(None, max_length=200, description="Words from an outcome title; primary outcomes if null.")

    def to_domain(self) -> TrialResults:
        return TrialResults(self.trial, self.focus, self.outcome)


type AnyPlanIn = CountByIn | CoOccurrenceIn | DistributionIn | CorrelationIn | TrialResultsIn
type PlanIn = Annotated[AnyPlanIn, Field(discriminator="kind")]


def plan_from_domain(plan: AnalysisPlan) -> AnyPlanIn:
    match plan:
        case CountBy():
            cohorts = [CohortIn.from_domain(c) for c in plan.cohorts]
            return CountByIn(kind="count_by", cohorts=cohorts, dimension=plan.dimension, split_by=plan.split_by, top_n=plan.top_n)
        case CoOccurrence():
            return CoOccurrenceIn(
                kind="co_occurrence",
                cohort=CohortIn.from_domain(plan.cohort),
                source=plan.source,
                target=plan.target,
                max_nodes=plan.max_nodes,
                min_shared_trials=plan.min_shared_trials,
            )
        case Distribution():
            return DistributionIn(kind="distribution", cohort=CohortIn.from_domain(plan.cohort), measure=plan.measure, bins=plan.bins)
        case Correlation():
            return CorrelationIn(kind="correlation", cohort=CohortIn.from_domain(plan.cohort), x=plan.x, y=plan.y)
        case TrialResults():
            return TrialResultsIn(kind="trial_results", trial=plan.trial, focus=plan.focus, outcome=plan.outcome)


class PlanRequest(_Schema):
    plan: PlanIn
    max_trials_per_cohort: int = Field(
        DEFAULT_MAX_TRIALS,
        ge=1,
        le=MAX_TRIALS_LIMIT,
        description="Trials fetched and analyzed per cohort; larger result sets are truncated and flagged in meta.",
    )


class VisualizeRequest(_Schema):
    """A question plus optional structured fields, which apply to every cohort and take precedence."""

    query: str = Field(min_length=1, max_length=1000, description="A question about clinical trials.")
    drug_name: str | None = Field(None, max_length=200, description="Intervention filter, e.g. 'Pembrolizumab'.")
    condition: str | None = Field(None, max_length=200, description="Condition filter, e.g. 'breast cancer'.")
    sponsor: str | None = Field(None, max_length=200, description="Sponsor or collaborator filter.")
    country: str | None = Field(None, max_length=100, description="Trial location country filter.")
    phases: list[Phase] = Field(default_factory=list, description="Trials in any of these phases.")
    statuses: list[Status] = Field(default_factory=list, description="Trials with any of these statuses.")
    start_year: int | None = Field(None, ge=1900, le=2100, description="Trials starting in or after this year.")
    end_year: int | None = Field(None, ge=1900, le=2100, description="Trials starting in or before this year.")
    nct_id: str | None = Field(
        None, pattern=r"^NCT\d{8}$", description="For a single trial's results: use this trial, e.g. to pick an alternative."
    )
    max_trials_per_cohort: int = Field(DEFAULT_MAX_TRIALS, ge=1, le=MAX_TRIALS_LIMIT)

    @model_validator(mode="after")
    def _check_years(self) -> Self:
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("start_year must not be after end_year")
        return self

    def to_question(self) -> Question:
        return Question(
            self.query,
            StructuredFields(
                drug_name=self.drug_name,
                condition=self.condition,
                sponsor=self.sponsor,
                country=self.country,
                phases=frozenset(self.phases),
                statuses=frozenset(self.statuses),
                start_year=self.start_year,
                end_year=self.end_year,
                nct_id=self.nct_id,
            ),
        )


class NetworkData(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class VisualizationOut(BaseModel):
    type: ChartType
    title: str
    encoding: dict[str, Channel] = Field(description="Visual channel -> data field. Keys depend on `type`.")
    data: list[dict[str, Any]] | NetworkData = Field(
        description="Rows (each with `citations`), or nodes and edges for network_graph."
    )


class ViewOut(VisualizationOut):
    """Another chart form of the same data; its notes are specific to this form."""

    notes: list[str]


class CohortMeta(BaseModel):
    label: str
    matched: int = Field(description="Trials matching the cohort's filter at ClinicalTrials.gov.")
    analyzed: int = Field(description="Trials fetched and aggregated; below `matched` when truncated.")
    truncated: bool


class TrialOption(BaseModel):
    nct_id: str
    title: str
    url: str
    enrollment: int | None = None


class TrialMeta(BaseModel):
    """The single trial whose posted results are charted."""

    nct_id: str
    title: str
    url: str
    alternatives: list[TrialOption] = Field(description="Other trials with posted results that the name matched.")


class Meta(BaseModel):
    source: Literal["clinicaltrials.gov"] = "clinicaltrials.gov"
    query: str | None = Field(None, description="The question, for POST /api/visualize.")
    interpretation: str | None = Field(None, description="How the question was understood, in one sentence.")
    plan: PlanIn = Field(description="The analysis that was run, including every filter applied.")
    cohorts: list[CohortMeta]
    trial: TrialMeta | None = Field(None, description="For trial_results: the trial used.")
    notes: list[str] = Field(description="Assumptions and caveats in plain sentences.")


class VisualizationResponse(BaseModel):
    visualization: VisualizationOut
    alternatives: list[ViewOut] = Field(
        default_factory=list, description="The same data in other chart forms, computed from the same rows."
    )
    meta: Meta

    @classmethod
    def of(
        cls,
        plan: AnyPlanIn,
        result: PlanResult,
        query: str | None = None,
        interpretation: str | None = None,
        planning_notes: Sequence[str] = (),
    ) -> Self:
        viz = result.visualization
        return cls(
            visualization=VisualizationOut(type=viz.type, title=viz.title, encoding=viz.encoding, data=viz.data),
            alternatives=[
                ViewOut(type=v.type, title=v.title, encoding=v.encoding, data=v.data, notes=list(v.notes))
                for v in result.alternatives
            ],
            meta=Meta(
                query=query,
                interpretation=interpretation,
                plan=plan,
                cohorts=[CohortMeta(label=c.label, matched=c.matched, analyzed=c.analyzed, truncated=c.truncated) for c in result.cohorts],
                trial=_trial_meta(result),
                notes=[*planning_notes, *viz.notes, *result.notes],
            ),
        )


def _trial_meta(result: PlanResult) -> TrialMeta | None:
    if result.trial is None:
        return None
    return TrialMeta(
        nct_id=result.trial.nct_id,
        title=result.trial.title,
        url=STUDY_URL.format(nct_id=result.trial.nct_id),
        alternatives=[
            TrialOption(nct_id=c.nct_id, title=c.title, url=STUDY_URL.format(nct_id=c.nct_id), enrollment=c.enrollment)
            for c in result.trial.alternatives
        ],
    )
