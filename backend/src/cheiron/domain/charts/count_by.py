"""CountBy -> bar chart, grouped bar chart or time series."""

from collections import defaultdict
from collections.abc import Mapping, Sequence

from cheiron.domain.analysis import Cohort, CountBy, Dimension
from cheiron.domain.charts.common import DIMENSION_TITLES, TRIAL_COUNT, Bucket, cohort_suffix
from cheiron.domain.facets import MULTI_VALUED, PHASE_ORDER, dimension_facets
from cheiron.domain.trial import DateType, Trial
from cheiron.domain.visualization import Channel, ChartType, Citations, Evidence, FieldType, Visualization

DEFAULT_TOP_N = 15
HIGH_CARDINALITY = frozenset({Dimension.COUNTRY, Dimension.CONDITION, Dimension.INTERVENTION, Dimension.LEAD_SPONSOR})

type Key = str | int


def build_count_by(
    plan: CountBy,
    trials_by_cohort: Mapping[str, Sequence[Trial]],
    max_citations: int,
    totals: Mapping[str, Mapping[Key, int]] | None = None,
) -> Visualization:
    """`totals`: registry counts per category for truncated cohorts (without a split); bars
    show them, while citations still come from the cohort's analyzed trials."""
    dim, split = plan.dimension, plan.split_by
    totals = {} if split else totals or {}
    compare = len(plan.cohorts) > 1
    cells: defaultdict[tuple[Key, Key | None], Bucket] = defaultdict(Bucket)
    categories: defaultdict[Key, Bucket] = defaultdict(Bucket)
    series: defaultdict[Key | None, Bucket] = defaultdict(Bucket)
    notes: list[str] = []

    for cohort in plan.cohorts:
        trials = trials_by_cohort[cohort.label]
        skipped = 0
        for trial in trials:
            values = dimension_facets(trial, dim)
            groups: list[tuple[Key | None, str | None, tuple[Evidence, ...]]]
            if split:
                groups = [(f.key, f.label, f.evidences) for f in dimension_facets(trial, split)]
            else:
                groups = [(cohort.label if compare else None, cohort.label, ())]
            if not values or not groups:
                skipped += 1
                continue
            for value in values:
                categories[value.key].add(trial, value.evidences, value.label)
                for key, label, evidence in groups:
                    cells[value.key, key].add(trial, (*value.evidences, *evidence), value.label)
                    series[key].add(trial, evidence, label)
        if skipped:
            missing = DIMENSION_TITLES[dim].lower() + (f" or {DIMENSION_TITLES[split].lower()}" if split else "")
            where = f" in {cohort.label}" if compare else ""
            notes.append(f"{skipped} of {len(trials)} trials{where} have no registered {missing} and are not shown.")

    def count(category: Key, key: Key | None) -> int:
        """The registry's count for a truncated cohort, else the analyzed trials'."""
        cohort = key if compare else plan.cohorts[0].label
        if category in totals.get(cohort, {}):
            return totals[cohort][category]
        bucket = cells.get((category, key))
        return bucket.count if bucket else 0

    cohort_keys = [c.label for c in plan.cohorts] if compare else [None]
    ranking = {k: sum(count(k, c) for c in cohort_keys) for k in categories} if totals else None
    category_keys, dropped = _order(dim, categories, plan.top_n, ranking)
    if dropped:
        notes.append(
            f"Showing the {len(category_keys)} most frequent of {len(categories)} {DIMENSION_TITLES[dim].lower()} values."
        )
    if split:
        series_keys, dropped_series = _order(split, series, None)
        if dropped_series:
            notes.append(
                f"Showing the {len(series_keys)} most frequent of {len(series)} {DIMENSION_TITLES[split].lower()} values."
            )
    else:
        series_keys = cohort_keys

    temporal = dim is Dimension.START_YEAR
    x_field = dim.value
    series_field = "cohort" if compare else split.value if split else None

    def category_label(key: Key) -> str:
        return categories[key].label if key in categories else str(key)

    def series_label(key: Key | None) -> str:
        return series[key].label if split and key in series else str(key)

    rows = []
    for category in category_keys:
        for key in series_keys:
            bucket = cells.get((category, key))
            row: dict = {x_field: category if temporal else category_label(category)}
            if series_field:
                row[series_field] = series_label(key)
            row["trial_count"] = count(category, key)
            row["citations"] = bucket.citations(max_citations) if bucket else Citations(0, ())
            rows.append(row)

    encoding = {
        "x": Channel(
            x_field,
            FieldType.TEMPORAL if temporal else FieldType.ORDINAL if dim is Dimension.PHASE else FieldType.NOMINAL,
            DIMENSION_TITLES[dim],
            order=None if temporal else tuple(category_label(k) for k in category_keys),
            time_unit="year" if temporal else None,
        ),
        "y": TRIAL_COUNT,
    }
    if series_field:
        encoding["series"] = Channel(
            series_field,
            FieldType.NOMINAL,
            "Cohort" if compare else DIMENSION_TITLES[split],
            order=tuple(series_label(k) for k in series_keys),
        )

    if dim in MULTI_VALUED or split in MULTI_VALUED:
        notes.append("A trial registered with several values is counted once under each, so counts can add up to more than the number of trials.")
    if temporal and rows:
        notes.append("Years without any trial start are included with a count of 0.")
        counted = [t for c in plan.cohorts for t in trials_by_cohort[c.label] if t.start_date]
        if estimated := sum(t.start_date_type is DateType.ESTIMATED for t in counted):
            notes.append(
                f"{estimated:,} of {len(counted):,} counted trials have an estimated start date (not started yet, or "
                "not updated since; their citations show startDateStruct.type ESTIMATED), so the years they fall in "
                "are provisional."
            )
    if compare and (overlap := _overlap(plan.cohorts, trials_by_cohort)):
        notes.append(f"Trials that match more than one cohort are counted in each ({overlap} in total).")

    what = "Trials started per year" if temporal else f"Trials by {DIMENSION_TITLES[dim].lower()}"
    if split:
        what += f" and {DIMENSION_TITLES[split].lower()}"
    chart = ChartType.TIME_SERIES if temporal else ChartType.GROUPED_BAR if series_field else ChartType.BAR
    return Visualization(chart, what + cohort_suffix(plan.cohorts), encoding, rows, tuple(notes))


def _order(
    dim: Dimension, buckets: Mapping[Key, Bucket], top_n: int | None, counts: Mapping[Key, int] | None = None
) -> tuple[list[Key], int]:
    """Keys in display order, and how many were dropped by the top-N limit; `counts` overrides
    the buckets' counts for ranking."""
    if not buckets:
        return [], 0
    if dim is Dimension.START_YEAR:
        years = [int(k) for k in buckets]
        return list(range(min(years), max(years) + 1)), 0
    ranked = sorted(buckets, key=lambda k: (-(counts[k] if counts else buckets[k].count), buckets[k].label))
    limit = top_n or (DEFAULT_TOP_N if dim in HIGH_CARDINALITY else None)
    kept = ranked[:limit] if limit else ranked
    if dim is Dimension.PHASE:
        kept = [p for p in PHASE_ORDER if p in kept]
    return kept, len(ranked) - len(kept)


def _overlap(cohorts: tuple[Cohort, ...], trials_by_cohort: Mapping[str, Sequence[Trial]]) -> int:
    seen: dict[str, int] = defaultdict(int)
    for cohort in cohorts:
        for nct_id in {t.nct_id for t in trials_by_cohort[cohort.label]}:
            seen[nct_id] += 1
    return sum(1 for n in seen.values() if n > 1)
