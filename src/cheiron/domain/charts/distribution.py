"""Distribution -> histogram."""

import math
from collections.abc import Sequence

from cheiron.domain.analysis import Distribution
from cheiron.domain.charts.common import MEASURE_TITLES, TRIAL_COUNT, Bucket, cohort_suffix
from cheiron.domain.facets import measure_value
from cheiron.domain.trial import Trial
from cheiron.domain.visualization import Channel, ChartType, FieldType, Visualization

CLIP_PERCENTILE = 0.95


def build_distribution(plan: Distribution, trials: Sequence[Trial], max_citations: int) -> Visualization:
    title, unit = MEASURE_TITLES[plan.measure]
    points = [(m[0], trial, m[1]) for trial in trials if (m := measure_value(trial, plan.measure)) is not None]
    notes = []
    if skipped := len(trials) - len(points):
        notes.append(f"{skipped} of {len(trials)} trials have no {title.lower()} and are not shown.")

    rows = []
    if points:
        # Enrollment and durations are heavily skewed; bins span the bulk of the data
        # and the long tail goes into one open-ended bin instead of stretching the axis.
        values = sorted(v for v, _, _ in points)
        low, high = values[0], values[math.ceil(CLIP_PERCENTILE * len(values)) - 1]
        step = _nice_step((high - low) / plan.bins)
        start = math.floor(low / step) * step
        regular = int((high - start) // step) + 1
        buckets = [Bucket() for _ in range(regular + 1)]
        for value, trial, evidence in points:
            buckets[min(int((value - start) // step), regular)].add(trial, evidence)
        overflow = buckets[-1]
        for i, bucket in enumerate(buckets if overflow.count else buckets[:-1]):
            rows.append(
                {
                    "bin_start": start + i * step,
                    "bin_end": None if i == regular else start + (i + 1) * step,
                    "trial_count": bucket.count,
                    "citations": bucket.citations(max_citations),
                }
            )
        if overflow.count:
            notes.append(
                f"{overflow.count} trials at or above {start + regular * step} {unit} (beyond the "
                f"{CLIP_PERCENTILE * 100:.0f}th percentile) are grouped in the last bin, whose bin_end is null."
            )
    notes.append("Each bin includes bin_start and excludes bin_end.")

    encoding = {
        "x": Channel("bin_start", FieldType.QUANTITATIVE, title, unit=unit),
        "x2": Channel("bin_end", FieldType.QUANTITATIVE, title, unit=unit),
        "y": TRIAL_COUNT,
    }
    return Visualization(
        ChartType.HISTOGRAM, f"Distribution of {title.lower()}" + cohort_suffix(plan.cohorts), encoding, rows, tuple(notes)
    )


def _nice_step(raw: float) -> int:
    """Smallest of 1, 2, 5 x 10^k that is at least `raw` (all measures are whole numbers)."""
    if raw <= 1:
        return 1
    magnitude = 10 ** math.floor(math.log10(raw))
    return next(int(m * magnitude) for m in (1, 2, 5, 10) if m * magnitude >= raw)
