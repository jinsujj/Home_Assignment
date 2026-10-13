"""Correlation -> scatter plot, one point per trial."""

from collections.abc import Sequence

from cheiron.domain.analysis import Correlation
from cheiron.domain.charts.common import MEASURE_TITLES, cohort_suffix
from cheiron.domain.facets import measure_value
from cheiron.domain.trial import Trial
from cheiron.domain.visualization import Channel, ChartType, Citation, Citations, FieldType, Visualization


def build_correlation(plan: Correlation, trials: Sequence[Trial]) -> Visualization:
    rows = []
    for trial in trials:
        x, y = measure_value(trial, plan.x), measure_value(trial, plan.y)
        if x is None or y is None:
            continue
        evidence = tuple(dict.fromkeys(x[1] + y[1]))
        rows.append(
            {
                "nct_id": trial.nct_id,
                "title": trial.title,
                plan.x.value: x[0],
                plan.y.value: y[0],
                "citations": Citations(1, (Citation.of(trial.nct_id, trial.title, evidence),)),
            }
        )

    (x_title, x_unit), (y_title, y_unit) = MEASURE_TITLES[plan.x], MEASURE_TITLES[plan.y]
    notes = ["Each point is one trial."]
    if skipped := len(trials) - len(rows):
        notes.append(f"{skipped} of {len(trials)} trials lack {x_title.lower()} or {y_title.lower()} and are not shown.")

    encoding = {
        "x": Channel(plan.x.value, FieldType.QUANTITATIVE, x_title, unit=x_unit),
        "y": Channel(plan.y.value, FieldType.QUANTITATIVE, y_title, unit=y_unit),
        "tooltip": Channel("title", FieldType.NOMINAL, "Trial"),
    }
    return Visualization(
        ChartType.SCATTER, f"{y_title} vs {x_title.lower()}" + cohort_suffix(plan.cohorts), encoding, rows, tuple(notes)
    )
