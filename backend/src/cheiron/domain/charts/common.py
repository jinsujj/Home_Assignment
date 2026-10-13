"""Building blocks shared by the chart builders."""

from collections import Counter

from cheiron.domain.analysis import Cohort, Dimension, Entity, Measure
from cheiron.domain.facets import PHASE_ORDER, label
from cheiron.domain.trial import Trial
from cheiron.domain.visualization import Channel, Citation, Citations, Evidence, FieldType

DIMENSION_TITLES = {
    Dimension.PHASE: "Phase",
    Dimension.STATUS: "Overall status",
    Dimension.STUDY_TYPE: "Study type",
    Dimension.START_YEAR: "Start year",
    Dimension.COUNTRY: "Country",
    Dimension.CONDITION: "Condition",
    Dimension.INTERVENTION: "Intervention",
    Dimension.INTERVENTION_TYPE: "Intervention type",
    Dimension.LEAD_SPONSOR: "Lead sponsor",
    Dimension.LEAD_SPONSOR_CLASS: "Lead sponsor class",
}
ENTITY_TITLES = {
    Entity.DRUG: "Drug",
    Entity.SPONSOR: "Sponsor",
    Entity.CONDITION: "Condition",
    Entity.COUNTRY: "Country",
    Entity.INVESTIGATOR: "Investigator",
    Entity.SITE: "Site",
}
MEASURE_TITLES = {
    Measure.ENROLLMENT: ("Enrollment", "participants"),
    Measure.DURATION_MONTHS: ("Duration from start to completion", "months"),
    Measure.START_YEAR: ("Start year", "year"),
}

TRIAL_COUNT = Channel("trial_count", FieldType.QUANTITATIVE, "Number of trials", unit="trials")


class Bucket:
    """The trials behind one datum (a bar, a time bucket, a node, an edge, a bin)."""

    def __init__(self) -> None:
        self._labels: Counter[str] = Counter()
        self._citations: list[Citation] = []

    def add(self, trial: Trial, evidence: tuple[Evidence, ...], label: str | None = None) -> None:
        if label:
            self._labels[label] += 1
        self._citations.append(Citation.of(trial.nct_id, trial.title, evidence))

    @property
    def count(self) -> int:
        return len(self._citations)

    @property
    def label(self) -> str:
        """The most frequent spelling among contributing trials."""
        return self._labels.most_common(1)[0][0]

    def citations(self, max_items: int) -> Citations:
        return Citations(
            total=self.count,
            items=tuple(self._citations[:max_items]),
            nct_ids=tuple(dict.fromkeys(c.nct_id for c in self._citations)),
        )


def cohort_suffix(cohorts: tuple[Cohort, ...]) -> str:
    """" — A vs B · scope": cohort labels, then filters all cohorts share that no label names.

    Without the scope, "Pembrolizumab" and "Pembrolizumab in South Korea" got the same title.
    """
    labels = [c.label for c in cohorts if c.label]
    parts = [" vs ".join(labels)] if labels else []
    named = " ".join(labels).casefold()
    parts += [s for s in _shared_scope(cohorts) if s.casefold() not in named]
    return f" — {' · '.join(parts)}" if parts else ""


def _shared_scope(cohorts: tuple[Cohort, ...]) -> list[str]:
    first = cohorts[0].filter
    if any(c.filter != first for c in cohorts[1:]):
        shared = {
            name: value
            for name, value in vars(first).items()
            if all(getattr(c.filter, name) == value for c in cohorts[1:])
        }
    else:
        shared = vars(first)

    scope = [shared[name] for name in ("intervention", "condition", "sponsor", "country") if shared.get(name)]
    for name in ("phases", "statuses"):
        if shared.get(name):
            scope.append(", ".join(label(code) for code in sorted(shared[name], key=_code_order)))
    if shared.get("study_type"):
        scope.append(label(shared["study_type"]))
    start, end = shared.get("start_year_from"), shared.get("start_year_to")
    if start is not None and end is not None:
        scope.append(f"started {start}" if start == end else f"started {start}–{end}")
    elif start is not None:
        scope.append(f"started {start} or later")
    elif end is not None:
        scope.append(f"started {end} or earlier")
    return scope


def _code_order(code: str) -> tuple[int, str]:
    return (PHASE_ORDER.index(code), code) if code in PHASE_ORDER else (len(PHASE_ORDER), code)
