"""Results a trial posted to ClinicalTrials.gov: outcome measures and adverse events.

Values keep the registered text next to the parsed number ("NA" when a median was not
reached), so citations quote exactly what was posted.
"""

from dataclasses import dataclass
from enum import StrEnum


class OutcomeType(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    OTHER_PRE_SPECIFIED = "OTHER_PRE_SPECIFIED"
    POST_HOC = "POST_HOC"


@dataclass(frozen=True)
class GroupValue:
    """One group's value for one outcome row."""

    group: str
    raw: str
    """As posted, e.g. "8.8" or "NA" (not estimable)."""
    lower: str | None = None
    upper: str | None = None
    spread: str | None = None
    """Posted instead of limits for e.g. a standard deviation: the interval is value ± spread."""

    @property
    def value(self) -> float | None:
        return _number(self.raw)

    @property
    def interval(self) -> tuple[float | None, float | None]:
        if self.lower is None and self.upper is None and self.spread is not None:
            value, spread = self.value, _number(self.spread)
            if value is not None and spread is not None:
                return value - spread, value + spread
        return _number(self.lower), _number(self.upper)


@dataclass(frozen=True)
class Comparison:
    """A posted statistical analysis between groups, e.g. a hazard ratio."""

    groups: tuple[str, ...]
    statistic: str
    value: str
    ci_percent: str | None = None
    ci_lower: str | None = None
    ci_upper: str | None = None
    p_value: str | None = None


@dataclass(frozen=True)
class Outcome:
    type: OutcomeType | None
    title: str
    """The measure's title as posted."""
    row: str | None
    """Class or category title when the measure is split into several rows, e.g. "Complete Response"."""
    measure: str
    """What the values are, e.g. MEDIAN, NUMBER, COUNT_OF_PARTICIPANTS."""
    dispersion: str | None
    """What lower/upper mean, e.g. "95% Confidence Interval" or "Full Range"."""
    unit: str
    time_frame: str
    values: tuple[GroupValue, ...]
    comparisons: tuple[Comparison, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.title} — {self.row}" if self.row else self.title


@dataclass(frozen=True)
class AdverseEvent:
    term: str
    organ_system: str
    serious: bool
    group: str
    affected: int
    at_risk: int


@dataclass(frozen=True)
class PostedResults:
    nct_id: str
    title: str
    acronym: str | None
    outcomes: tuple[Outcome, ...]
    adverse_events: tuple[AdverseEvent, ...]


def _number(raw: str | None) -> float | None:
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None
