"""Building blocks shared by the chart builders."""

from collections import Counter

from cheiron.domain.analysis import Cohort, Dimension, Entity, Measure
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
        return Citations(total=self.count, items=tuple(self._citations[:max_items]))


def cohort_suffix(cohorts: tuple[Cohort, ...]) -> str:
    labels = [c.label for c in cohorts if c.label]
    return f" — {' vs '.join(labels)}" if labels else ""
