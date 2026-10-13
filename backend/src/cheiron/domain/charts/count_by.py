"""CountBy -> bar chart, grouped bar chart or time series."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from cheiron.domain.analysis import Cohort, CountBy, Dimension
from cheiron.domain.charts.common import DIMENSION_TITLES, TRIAL_COUNT, Bucket, cohort_suffix
from cheiron.domain.facets import MULTI_VALUED, PHASE_ORDER, dimension_facets
from cheiron.domain.trial import DateType, Trial
from cheiron.domain.visualization import Channel, ChartType, Citations, Evidence, FieldType, RegistryCount, Visualization

DEFAULT_TOP_N = 15
HIGH_CARDINALITY = frozenset({Dimension.COUNTRY, Dimension.CONDITION, Dimension.INTERVENTION, Dimension.LEAD_SPONSOR})

type Key = str | int


def build_count_by(
    plan: CountBy,
    trials_by_cohort: Mapping[str, Sequence[Trial]],
    max_citations: int,
    totals: Mapping[str, Mapping[Key, RegistryCount]] | None = None,
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
    cited_notes: list[tuple[str, Citations]] = []

    def note(text: str, trials: Bucket) -> None:
        notes.append(text)
        cited_notes.append((text, trials.citations(max_citations)))

    for cohort in plan.cohorts:
        trials = trials_by_cohort[cohort.label]
        skipped = Bucket()
        for trial in trials:
            values = dimension_facets(trial, dim)
            groups: list[tuple[Key | None, str | None, tuple[Evidence, ...]]]
            if split:
                groups = [(f.key, f.label, f.evidences) for f in dimension_facets(trial, split)]
            else:
                groups = [(cohort.label if compare else None, cohort.label, ())]
            if not values or not groups:
                skipped.add(trial, ())
                continue
            for value in values:
                categories[value.key].add(trial, value.evidences, value.label)
                for key, label, evidence in groups:
                    cells[value.key, key].add(trial, (*value.evidences, *evidence), value.label)
                    series[key].add(trial, evidence, label)
        if skipped.count:
            missing = DIMENSION_TITLES[dim].lower() + (f" or {DIMENSION_TITLES[split].lower()}" if split else "")
            where = f" in {cohort.label}" if compare else ""
            note(f"{skipped.count} of {len(trials)} trials{where} have no registered {missing} and are not shown.", skipped)

    def registry(category: Key, key: Key | None) -> RegistryCount | None:
        return totals.get(key if compare else plan.cohorts[0].label, {}).get(category)

    def count(category: Key, key: Key | None) -> int:
        """The registry's count for a truncated cohort, else the analyzed trials'."""
        if counted := registry(category, key):
            return counted.trials
        bucket = cells.get((category, key))
        return bucket.count if bucket else 0

    # Registry counts may cover categories the analyzed trials do not show (a country, a year).
    registered = {k: c.label or str(k) for counts in totals.values() for k, c in counts.items()}
    labels = registered | {k: bucket.label for k, bucket in categories.items()}
    cohort_keys = [c.label for c in plan.cohorts] if compare else [None]
    ranking = {k: sum(count(k, c) for c in cohort_keys) for k in labels}
    category_keys, dropped = _order(dim, ranking, labels, plan.top_n)
    if dropped:
        notes.append(
            f"Showing the {len(category_keys)} most frequent of {len(labels)} {DIMENSION_TITLES[dim].lower()} values."
        )
    if split:
        series_counts = {k: bucket.count for k, bucket in series.items()}
        series_keys, dropped_series = _order(split, series_counts, {k: bucket.label for k, bucket in series.items()}, None)
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
        return labels.get(key, str(key))

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
            if counted := registry(category, key):
                cited = row["citations"] if bucket else Citations(len(counted.cited), counted.cited[:max_citations])
                listed = {"nct_ids": counted.nct_ids, "total": len(counted.nct_ids)} if counted.nct_ids else {}
                row["citations"] = replace(cited, registry_query=counted.query, **listed)
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
        estimated = Bucket()
        for t in counted:
            if t.start_date_type is DateType.ESTIMATED:
                estimated.add(t, dimension_facets(t, Dimension.START_YEAR)[0].evidences)
        if estimated.count:
            note(
                f"{estimated.count:,} of {len(counted):,} counted trials have an estimated start date (not started yet, "
                "or not updated since; their citations show startDateStruct.type ESTIMATED), so the years they fall "
                "in are provisional.",
                estimated,
            )
    if compare and (overlap := _overlap(plan.cohorts, trials_by_cohort)).count:
        note(f"Trials that match more than one cohort are counted in each ({overlap.count} in total).", overlap)

    what = "Trials started per year" if temporal else f"Trials by {DIMENSION_TITLES[dim].lower()}"
    if split:
        what += f" and {DIMENSION_TITLES[split].lower()}"
    chart = ChartType.TIME_SERIES if temporal else ChartType.GROUPED_BAR if series_field else ChartType.BAR
    return Visualization(chart, what + cohort_suffix(plan.cohorts), encoding, rows, tuple(notes), tuple(cited_notes))


def _order(
    dim: Dimension, counts: Mapping[Key, int], labels: Mapping[Key, str], top_n: int | None
) -> tuple[list[Key], int]:
    """Keys in display order, and how many were dropped by the top-N limit."""
    if not counts:
        return [], 0
    if dim is Dimension.START_YEAR:
        years = [int(k) for k in counts]
        return list(range(min(years), max(years) + 1)), 0
    ranked = sorted(counts, key=lambda k: (-counts[k], labels[k]))
    limit = top_n or (DEFAULT_TOP_N if dim in HIGH_CARDINALITY else None)
    kept = ranked[:limit] if limit else ranked
    if dim is Dimension.PHASE:
        kept = [p for p in PHASE_ORDER if p in kept]
    return kept, len(ranked) - len(kept)


def tally(trials: Iterable[Trial], dimension: Dimension) -> dict[Key, Bucket]:
    """The trials per value of `dimension`; a trial counts once per value."""
    buckets: defaultdict[Key, Bucket] = defaultdict(Bucket)
    for trial in trials:
        for value in dimension_facets(trial, dimension):
            buckets[value.key].add(trial, value.evidences, value.label)
    return dict(buckets)


def _overlap(cohorts: tuple[Cohort, ...], trials_by_cohort: Mapping[str, Sequence[Trial]]) -> Bucket:
    """The trials that match more than one cohort."""
    found: dict[str, list[Trial]] = defaultdict(list)
    for cohort in cohorts:
        for trial in {t.nct_id: t for t in trials_by_cohort[cohort.label]}.values():
            found[trial.nct_id].append(trial)
    overlap = Bucket()
    for matches in found.values():
        if len(matches) > 1:
            overlap.add(matches[0], ())
    return overlap
