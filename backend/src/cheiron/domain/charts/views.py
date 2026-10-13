"""Alternative views: the same answer drawn in other chart forms.

Every view is computed from the primary visualization's rows, never from new data, so all
views of an answer show the same numbers and keep the same citations. Which views exist
depends only on the primary's type and encoding, not on the question:

    bar_chart          -> donut_chart; choropleth_map when the categories are countries
    grouped_bar_chart  -> stacked_bar_chart (each group's mix, 100%) and heatmap;
                          forest_plot when values carry intervals (a trial's outcomes)
    time_series        -> cumulative time_series
    network_graph      -> heatmap (adjacency matrix) and bar_chart (strongest links)
    histogram          -> line_chart (cumulative distribution)
    scatter_plot       -> bar_chart (median y per fifth of the trials by x)
"""

import statistics
from bisect import bisect_right
from collections import defaultdict
from typing import Any

from cheiron.domain.geography import iso_numeric
from cheiron.domain.visualization import Channel, ChartType, Citations, FieldType, Visualization

TOP_LINKS = 15
MEDIAN_GROUPS = 5
CITED_PER_GROUP = 5
_MULTI_VALUED_NOTE = "counted once under each"


def alternative_views(primary: Visualization) -> tuple[Visualization, ...]:
    # Network data is {"nodes": [...], "edges": [...]}, which is truthy even when empty.
    empty = not primary.data["edges"] if primary.type is ChartType.NETWORK else not primary.data
    if empty:
        return ()
    match primary.type:
        case ChartType.BAR:
            return _bar_views(primary)
        case ChartType.GROUPED_BAR:
            return _grouped_views(primary)
        case ChartType.TIME_SERIES:
            return (_cumulative(primary),)
        case ChartType.NETWORK:
            return _network_views(primary)
        case ChartType.HISTOGRAM:
            return (_cumulative_distribution(primary),)
        case ChartType.SCATTER:
            return _medians_by_range(primary)
    return ()


def _bar_views(primary: Visualization) -> tuple[Visualization, ...]:
    x, y = primary.encoding["x"], primary.encoding["y"]
    rows = primary.data
    total = sum(r[y.field] for r in rows) or 1
    donut = Visualization(
        ChartType.DONUT,
        _title(primary, f"{x.title} mix"),
        {
            "theta": y,
            "color": Channel(x.field, x.type, x.title, order=x.order),
            "tooltip": Channel("share", FieldType.QUANTITATIVE, "Share", unit="%"),
        },
        [r | {"share": round(100 * r[y.field] / total, 1)} for r in rows],
        ("Each slice is its share of the counts in the bar chart.", *_caveats(primary)),
    )
    if x.field != "country":
        return (donut,)

    mapped = [r | {"iso_numeric": iso_numeric(r["country"])} for r in rows]
    unmapped = [r["country"] for r in mapped if r["iso_numeric"] is None]
    notes = [
        "Countries are matched to map shapes by ISO 3166-1 numeric code; the map shows the same countries as the bar chart.",
        "Small territories may be too small to see at world scale.",
    ]
    if unmapped:
        notes.append(f"Not on the map (no current country code): {', '.join(unmapped)}.")
    choropleth = Visualization(
        ChartType.CHOROPLETH,
        _title(primary, "Trials by country, mapped"),
        {
            "region": Channel("iso_numeric", FieldType.NOMINAL, "ISO 3166-1 numeric code"),
            "label": Channel("country", FieldType.NOMINAL, "Country"),
            "color": y,
        },
        mapped,
        (*notes, *_caveats(primary)),
    )
    return (choropleth, donut)


def _grouped_views(primary: Visualization) -> tuple[Visualization, ...]:
    enc = primary.encoding
    x, y, series = enc["x"], enc["y"], enc["series"]
    if "y_lower" in enc:
        return (_forest(primary),)

    heatmap = Visualization(
        ChartType.HEATMAP,
        _title(primary, f"{y.title} by {x.title.lower()} and {series.title.lower()}"),
        {"x": x, "y": Channel(series.field, series.type, series.title, order=series.order), "color": y},
        primary.data,
        ("Each cell is one bar of the grouped bar chart.", *_caveats(primary)),
    )
    if y.unit == "%":  # already a rate: stacking rates of different categories means nothing
        return (heatmap,)

    totals: dict[Any, float] = defaultdict(float)
    for row in primary.data:
        totals[row[series.field]] += row[y.field]
    shares = [r | {"share": round(100 * r[y.field] / totals[r[series.field]], 1) if totals[r[series.field]] else 0.0} for r in primary.data]
    stacked = Visualization(
        ChartType.STACKED_BAR,
        _title(primary, f"{x.title} mix within each {series.title.lower()}"),
        {
            "x": Channel(series.field, series.type, series.title, order=series.order),
            "y": Channel("share", FieldType.QUANTITATIVE, f"Share of {series.title.lower()}'s counts", unit="%"),
            "color": x,
        },
        shares,
        (
            f"Each bar is 100% of one {series.title.lower()}'s counts, so mixes compare regardless of group size.",
            *_caveats(primary),
        ),
    )
    return (stacked, heatmap)


def _forest(primary: Visualization) -> Visualization:
    enc = primary.encoding
    interval_notes = tuple(n for n in primary.notes if n.startswith("Error bars"))
    return Visualization(
        ChartType.FOREST,
        _title(primary, "Estimates with intervals"),
        {
            "y": Channel(enc["x"].field, FieldType.NOMINAL, enc["x"].title, order=enc["x"].order),
            "series": enc["series"],
            "x": enc["y"],
            "x_lower": enc["y_lower"],
            "x_upper": enc["y_upper"],
        },
        primary.data,
        tuple(n.replace("Error bars", "Lines") for n in interval_notes),
    )


def _cumulative(primary: Visualization) -> Visualization:
    enc = primary.encoding
    x, y, series = enc["x"], enc["y"], enc.get("series")
    running: dict[Any, float] = defaultdict(float)
    rows = []
    for row in sorted(primary.data, key=lambda r: r[x.field]):
        key = row[series.field] if series else None
        running[key] += row[y.field]
        rows.append(row | {"cumulative_count": running[key]})
    encoding = {"x": x, "y": Channel("cumulative_count", FieldType.QUANTITATIVE, "Trials started so far", unit="trials")}
    if series:
        encoding["series"] = series
    return Visualization(
        ChartType.TIME_SERIES,
        _title(primary, "Cumulative trials started"),
        encoding,
        rows,
        ("Each point adds that year's starts to all earlier ones; its citations are that year's trials.",),
    )


def _network_views(primary: Visualization) -> tuple[Visualization, ...]:
    nodes = {n["id"]: n for n in primary.data["nodes"]}
    edges = primary.data["edges"]
    kinds = list(dict.fromkeys(n["kind"] for n in nodes.values()))
    same_kind = len(kinds) == 1
    order = [n["label"] for n in primary.data["nodes"]]

    cells = []
    for e in edges:
        a, b = nodes[e["source"]], nodes[e["target"]]
        if not same_kind and a["kind"] != kinds[0]:
            a, b = b, a
        cells.append({"row": b["label"], "column": a["label"], "trial_count": e["trial_count"], "citations": e["citations"]})
        if same_kind:
            cells.append({"row": a["label"], "column": b["label"], "trial_count": e["trial_count"], "citations": e["citations"]})
    column_title = kinds[0].title()
    row_title = kinds[-1].title()
    matrix = Visualization(
        ChartType.HEATMAP,
        _title(primary, "Shared trials matrix"),
        {
            "x": Channel("column", FieldType.NOMINAL, column_title, order=tuple(l for l in order if any(c["column"] == l for c in cells))),
            "y": Channel("row", FieldType.NOMINAL, row_title, order=tuple(l for l in order if any(c["row"] == l for c in cells))),
            "color": Channel("trial_count", FieldType.QUANTITATIVE, "Shared trials", unit="trials"),
        },
        cells,
        ("Each cell is one link of the network: the trials registering both." + (" The matrix is symmetric." if same_kind else ""),),
    )

    strongest = sorted(edges, key=lambda e: -e["trial_count"])[:TOP_LINKS]
    links = [
        {"link": f"{nodes[e['source']]['label']} + {nodes[e['target']]['label']}", "trial_count": e["trial_count"], "citations": e["citations"]}
        for e in strongest
    ]
    ranking = Visualization(
        ChartType.BAR,
        _title(primary, "Strongest links"),
        {
            "x": Channel("link", FieldType.NOMINAL, "Link", order=tuple(l["link"] for l in links)),
            "y": Channel("trial_count", FieldType.QUANTITATIVE, "Shared trials", unit="trials"),
        },
        links,
        (f"The {len(links)} links with the most shared trials, out of {len(edges)} shown in the network.",),
    )
    return (matrix, ranking)


def _cumulative_distribution(primary: Visualization) -> Visualization:
    x = primary.encoding["x"]
    rows = primary.data
    total = sum(r["trial_count"] for r in rows) or 1
    below = 0
    points = []
    for row in rows:
        below += row["trial_count"]
        if row["bin_end"] is not None:
            points.append(
                {"value": row["bin_end"], "cumulative_share": round(100 * below / total, 1), "trial_count": row["trial_count"], "citations": row["citations"]}
            )
    notes = ["Each point is the share of trials below a bin's upper edge; its citations are that bin's trials."]
    if rows[-1]["bin_end"] is None:
        notes.append(f"The remaining {round(100 * rows[-1]['trial_count'] / total, 1)}% are at or above {rows[-1]['bin_start']} {x.unit}.")
    return Visualization(
        ChartType.LINE,
        _title(primary, f"Cumulative distribution of {x.title.lower()}"),
        {
            "x": Channel("value", FieldType.QUANTITATIVE, x.title, unit=x.unit),
            "y": Channel("cumulative_share", FieldType.QUANTITATIVE, "Trials below this value", unit="%"),
        },
        points,
        tuple(notes),
    )


def _medians_by_range(primary: Visualization) -> tuple[Visualization, ...]:
    """Answers "does y rise with x?" directly: trials split into fifths by x, median y of each."""
    x, y = primary.encoding["x"], primary.encoding["y"]
    rows = sorted(primary.data, key=lambda r: r[x.field])
    if len(rows) < 2 * MEDIAN_GROUPS:
        return ()
    values = [r[x.field] for r in rows]
    # Cut at the quintiles; equal values stay in one group, so groups can differ in size.
    cuts = sorted({values[k * len(rows) // MEDIAN_GROUPS] for k in range(1, MEDIAN_GROUPS)})
    groups: list[list[dict[str, Any]]] = [[] for _ in range(len(cuts) + 1)]
    for row in rows:
        groups[bisect_right(cuts, row[x.field])].append(row)

    bars = []
    for group in filter(None, groups):
        low, high = group[0][x.field], group[-1][x.field]
        cited = [c for r in group for c in r["citations"].items]
        bars.append(
            {
                "range": f"{low:,}" if low == high else f"{low:,}–{high:,}",
                "median": statistics.median(r[y.field] for r in group),
                "trial_count": len(group),
                "citations": Citations(len(group), tuple(cited[:CITED_PER_GROUP]), tuple(r["nct_id"] for r in group)),
            }
        )
    association = tuple(n for n in primary.notes if n.startswith("Spearman"))
    return (
        Visualization(
            ChartType.BAR,
            _title(primary, f"Median {y.title.lower()} by {x.title.lower()}"),
            {
                "x": Channel("range", FieldType.ORDINAL, x.title, order=tuple(b["range"] for b in bars), unit=x.unit),
                "y": Channel("median", FieldType.QUANTITATIVE, f"Median {y.title.lower()}", unit=y.unit),
                "tooltip": Channel("trial_count", FieldType.QUANTITATIVE, "Trials", unit="trials"),
            },
            bars,
            (
                f"The scatter's trials split into {len(bars)} groups of about equal size by {x.title.lower()}; "
                f"each bar is a group's median {y.title.lower()}.",
                *association,
            ),
        ),
    )


def _title(primary: Visualization, what: str) -> str:
    """Reuse the primary title's scope ("— Keytruda vs Opdivo · South Korea")."""
    _, dash, scope = primary.title.partition(" — ")
    return f"{what} — {scope}" if dash else what


def _caveats(primary: Visualization) -> tuple[str, ...]:
    return tuple(n for n in primary.notes if _MULTI_VALUED_NOTE in n)

