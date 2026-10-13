"""HTTP request and response schemas.

The plan models are the public form of the domain's AnalysisPlan. They also serve as the
LLM planner's output schema, so field descriptions are written for both readers.
Domain invariants (e.g. split_by with several cohorts) surface as 422 validation errors.
"""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cheiron.application.run_plan import DEFAULT_MAX_TRIALS, PlanResult
from cheiron.domain.analysis import (
    MAX_COHORTS,
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
from cheiron.domain.visualization import Channel, ChartType

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


type PlanIn = Annotated[CountByIn | CoOccurrenceIn | DistributionIn | CorrelationIn, Field(discriminator="kind")]


class PlanRequest(_Schema):
    plan: PlanIn
    max_trials_per_cohort: int = Field(
        DEFAULT_MAX_TRIALS,
        ge=1,
        le=MAX_TRIALS_LIMIT,
        description="Trials fetched and analyzed per cohort; larger result sets are truncated and flagged in meta.",
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


class CohortMeta(BaseModel):
    label: str
    matched: int = Field(description="Trials matching the cohort's filter at ClinicalTrials.gov.")
    analyzed: int = Field(description="Trials fetched and aggregated; below `matched` when truncated.")
    truncated: bool


class Meta(BaseModel):
    source: Literal["clinicaltrials.gov"] = "clinicaltrials.gov"
    plan: PlanIn = Field(description="The analysis that was run, including every filter applied.")
    cohorts: list[CohortMeta]
    notes: list[str] = Field(description="Assumptions and caveats in plain sentences.")


class VisualizationResponse(BaseModel):
    visualization: VisualizationOut
    meta: Meta

    @classmethod
    def of(cls, plan: CountByIn | CoOccurrenceIn | DistributionIn | CorrelationIn, result: PlanResult) -> Self:
        viz = result.visualization
        return cls(
            visualization=VisualizationOut(type=viz.type, title=viz.title, encoding=viz.encoding, data=viz.data),
            meta=Meta(
                plan=plan,
                cohorts=[CohortMeta(label=c.label, matched=c.matched, analyzed=c.analyzed, truncated=c.truncated) for c in result.cohorts],
                notes=[*viz.notes, *result.notes],
            ),
        )
