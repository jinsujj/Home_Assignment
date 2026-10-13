"""Correlation -> scatter plot, one point per trial, with its rank correlation."""

import statistics
from collections.abc import Sequence

from cheiron.domain.analysis import Correlation
from cheiron.domain.charts.common import MEASURE_TITLES, Bucket, cohort_suffix
from cheiron.domain.facets import measure_value
from cheiron.domain.trial import Trial
from cheiron.domain.visualization import Channel, ChartType, Citation, Citations, FieldType, Visualization

SKEW_RATIO = 10
"""An axis whose largest value is at least this many times its median is drawn log-like."""


def build_correlation(plan: Correlation, trials: Sequence[Trial], max_citations: int) -> Visualization:
    rows = []
    skipped = Bucket()
    for trial in trials:
        x, y = measure_value(trial, plan.x), measure_value(trial, plan.y)
        if x is None or y is None:
            skipped.add(trial, ())
            continue
        evidence = tuple(dict.fromkeys(x[1] + y[1]))
        rows.append(
            {
                "nct_id": trial.nct_id,
                "title": trial.title,
                plan.x.value: x[0],
                plan.y.value: y[0],
                "citations": Citations(1, (Citation.of(trial.nct_id, trial.title, evidence),), (trial.nct_id,)),
            }
        )

    (x_title, x_unit), (y_title, y_unit) = MEASURE_TITLES[plan.x], MEASURE_TITLES[plan.y]
    xs, ys = [r[plan.x.value] for r in rows], [r[plan.y.value] for r in rows]
    notes = ["Each point is one trial."]
    cited_notes = []
    if skipped.count:
        missing = f"{skipped.count} of {len(trials)} trials lack {x_title.lower()} or {y_title.lower()} and are not shown."
        notes.append(missing)
        cited_notes.append((missing, skipped.citations(max_citations)))
    if association := _association(xs, ys, x_title.lower(), y_title.lower()):
        notes.append(association)
    scales = {}
    for axis, title, values in (("x", x_title, xs), ("y", y_title, ys)):
        if ratio := _skew(values):
            scales[axis] = "symlog"
            notes.append(
                f"{title} is drawn on a log-like (symlog) axis, as its largest value is {ratio:.0f} times "
                "its median; zeros stay on the axis."
            )

    encoding = {
        "x": Channel(plan.x.value, FieldType.QUANTITATIVE, x_title, unit=x_unit, scale=scales.get("x")),
        "y": Channel(plan.y.value, FieldType.QUANTITATIVE, y_title, unit=y_unit, scale=scales.get("y")),
        "tooltip": Channel("title", FieldType.NOMINAL, "Trial"),
    }
    title = f"{y_title} vs {x_title.lower()}" + cohort_suffix(plan.cohorts)
    return Visualization(ChartType.SCATTER, title, encoding, rows, tuple(notes), tuple(cited_notes))


def _association(xs: list[float], ys: list[float], x: str, y: str) -> str | None:
    """Spearman's rank correlation in words; ranks keep a few huge trials from dominating."""
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rho = statistics.correlation(xs, ys, method="ranked")
    measured = f"Spearman rank correlation ρ = {rho:.2f} over {len(xs)} trials"
    if abs(rho) < 0.1:
        return f"{measured}: no clear association between {x} and {y}."
    strength = "strong" if abs(rho) >= 0.5 else "moderate" if abs(rho) >= 0.3 else "weak"
    direction, trend = ("positive", "rise") if rho > 0 else ("negative", "fall")
    return f"{measured}: a {strength} {direction} association; {y} tends to {trend} as {x} rises."


def _skew(values: list[float]) -> float | None:
    """How many times the median the largest value is, when that is at least SKEW_RATIO."""
    if not values or (median := statistics.median(values)) <= 0:
        return None
    ratio = max(values) / median
    return ratio if ratio >= SKEW_RATIO else None
