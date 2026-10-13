"""AnalysisPlan: the small grammar every supported question is expressed in.

Four analysis kinds over many trials, each parameterised by enums, cover the question
classes of the assignment (trends, distributions, comparisons, geography, relationships)
without per-question code paths; a fifth reads one trial's posted results. The LLM
planner only ever produces one of these; everything downstream is deterministic.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from cheiron.domain.trial_filter import TrialFilter

MAX_COHORTS = 5


class Dimension(StrEnum):
    """A categorical (or yearly) trial attribute to count trials by."""

    PHASE = "phase"
    STATUS = "status"
    STUDY_TYPE = "study_type"
    START_YEAR = "start_year"
    COUNTRY = "country"
    CONDITION = "condition"
    INTERVENTION = "intervention"
    INTERVENTION_TYPE = "intervention_type"
    LEAD_SPONSOR = "lead_sponsor"
    LEAD_SPONSOR_CLASS = "lead_sponsor_class"


class Entity(StrEnum):
    """A node kind in a relationship network."""

    DRUG = "drug"
    SPONSOR = "sponsor"
    CONDITION = "condition"
    COUNTRY = "country"
    INVESTIGATOR = "investigator"
    SITE = "site"


class Measure(StrEnum):
    """A numeric per-trial attribute."""

    ENROLLMENT = "enrollment"
    DURATION_MONTHS = "duration_months"
    START_YEAR = "start_year"


@dataclass(frozen=True)
class Cohort:
    """A labelled set of trials, e.g. "Pembrolizumab" -> TrialFilter(intervention=...)."""

    label: str
    filter: TrialFilter


@dataclass(frozen=True)
class CountBy:
    """Count trials per value of `dimension`.

    Several cohorts compare those counts side by side; `split_by` breaks a single
    cohort down by a second dimension. `top_n` keeps the largest categories.
    """

    cohorts: tuple[Cohort, ...]
    dimension: Dimension
    split_by: Dimension | None = None
    top_n: int | None = None

    def __post_init__(self) -> None:
        _check_cohorts(self.cohorts)
        if self.split_by is not None and len(self.cohorts) > 1:
            raise ValueError("split_by applies to a single cohort; several cohorts already form the series")
        if self.split_by == self.dimension:
            raise ValueError("split_by must differ from dimension")
        if self.top_n is not None and self.top_n < 1:
            raise ValueError("top_n must be at least 1")
        if self.top_n is not None and self.dimension is Dimension.START_YEAR:
            raise ValueError("top_n does not apply to start_year; narrow the year range instead")


class Link(StrEnum):
    """What makes two drugs linked in a drug <-> drug network."""

    SAME_TRIAL = "same_trial"  # registered on the same trial
    SAME_ARM = "same_arm"  # given together in one arm: a combination
    DIFFERENT_ARMS = "different_arms"  # only in different arms: compared, or alternatives


@dataclass(frozen=True)
class CoOccurrence:
    """Network of entities registered on the same trial.

    `source == target` links entities of one kind (drug <-> drug); otherwise the
    network is bipartite (sponsor <-> drug). Edge weight is the number of shared trials.
    """

    cohort: Cohort
    source: Entity
    target: Entity
    max_nodes: int = 30
    min_shared_trials: int = 1
    link: Link = Link.SAME_TRIAL

    def __post_init__(self) -> None:
        if not 2 <= self.max_nodes <= 200:
            raise ValueError("max_nodes must be between 2 and 200")
        if self.min_shared_trials < 1:
            raise ValueError("min_shared_trials must be at least 1")
        if self.link is not Link.SAME_TRIAL and not (self.source is Entity.DRUG and self.target is Entity.DRUG):
            raise ValueError(f"link {self.link} needs a drug-drug network (source = target = drug)")

    @property
    def cohorts(self) -> tuple[Cohort, ...]:
        return (self.cohort,)


@dataclass(frozen=True)
class Distribution:
    """Histogram of a numeric attribute."""

    cohort: Cohort
    measure: Measure
    bins: int = 20

    def __post_init__(self) -> None:
        if not 1 <= self.bins <= 100:
            raise ValueError("bins must be between 1 and 100")

    @property
    def cohorts(self) -> tuple[Cohort, ...]:
        return (self.cohort,)


@dataclass(frozen=True)
class Correlation:
    """One point per trial, positioned by two numeric attributes."""

    cohort: Cohort
    x: Measure
    y: Measure

    def __post_init__(self) -> None:
        if self.x == self.y:
            raise ValueError("x and y must be different measures")

    @property
    def cohorts(self) -> tuple[Cohort, ...]:
        return (self.cohort,)


class ResultFocus(StrEnum):
    OUTCOMES = "outcomes"
    ADVERSE_EVENTS = "adverse_events"


_NCT_ID = re.compile(r"^NCT\d{8}$", re.IGNORECASE)


@dataclass(frozen=True)
class TrialResults:
    """The posted results of one trial, named by NCT ID or by name (acronym, study ID, title)."""

    trial: str
    focus: ResultFocus = ResultFocus.OUTCOMES
    outcome: str | None = None
    """Words from the outcome measure's title, e.g. "overall survival"; None for primary outcomes."""

    def __post_init__(self) -> None:
        if not self.trial.strip():
            raise ValueError("trial_results needs a trial name or NCT ID")

    @property
    def nct_id(self) -> str | None:
        return self.trial.strip().upper() if _NCT_ID.match(self.trial.strip()) else None

    @property
    def cohorts(self) -> tuple[Cohort, ...]:
        return ()


type AnalysisPlan = CountBy | CoOccurrence | Distribution | Correlation | TrialResults


def needs_sites(plan: AnalysisPlan) -> bool:
    """Whether the plan reads trial sites, which are costly to fetch."""
    return isinstance(plan, CoOccurrence) and Entity.SITE in (plan.source, plan.target)


def _check_cohorts(cohorts: tuple[Cohort, ...]) -> None:
    if not 1 <= len(cohorts) <= MAX_COHORTS:
        raise ValueError(f"between 1 and {MAX_COHORTS} cohorts are supported")
    labels = [c.label for c in cohorts]
    if len(set(labels)) != len(labels):
        raise ValueError(f"cohort labels must be unique: {labels}")
