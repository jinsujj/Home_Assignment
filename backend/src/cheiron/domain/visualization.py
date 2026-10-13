"""The visualization specification a frontend renders, with citations per datum."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

STUDY_URL = "https://clinicaltrials.gov/study/{nct_id}"


class ChartType(StrEnum):
    BAR = "bar_chart"
    GROUPED_BAR = "grouped_bar_chart"
    TIME_SERIES = "time_series"
    HISTOGRAM = "histogram"
    SCATTER = "scatter_plot"
    NETWORK = "network_graph"
    # Alternative views of the same data (charts.views)
    STACKED_BAR = "stacked_bar_chart"
    HEATMAP = "heatmap"
    CHOROPLETH = "choropleth_map"
    DONUT = "donut_chart"
    LINE = "line_chart"
    FOREST = "forest_plot"


class FieldType(StrEnum):
    """How a channel's values are interpreted (Vega-Lite's measurement types)."""

    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    QUANTITATIVE = "quantitative"
    TEMPORAL = "temporal"


@dataclass(frozen=True)
class Channel:
    """Maps a data field to a visual channel (x, y, series, node_size, ...)."""

    field: str
    type: FieldType
    title: str
    order: tuple[str | int, ...] | None = None
    """Category order to render in; None means data order."""
    unit: str | None = None
    time_unit: str | None = None
    scale: str | None = None
    """None for a linear axis; "symlog" for a log-like axis that keeps zeros."""


@dataclass(frozen=True)
class Evidence:
    """A field of the study record and its value exactly as registered."""

    field: str
    value: str


@dataclass(frozen=True)
class Citation:
    nct_id: str
    title: str
    url: str
    evidence: tuple[Evidence, ...]
    excerpt: str
    """The evidence as one line of registered text, e.g. "phases: PHASE3"."""

    @classmethod
    def of(cls, nct_id: str, title: str, evidence: tuple[Evidence, ...]) -> Citation:
        excerpt = "; ".join(f"{_short_field(e.field)}: {e.value}" for e in evidence)
        return cls(nct_id, title, STUDY_URL.format(nct_id=nct_id), evidence, excerpt)


@dataclass(frozen=True)
class Citations:
    """The trials behind one datum: `total` of them, the first `items` spelled out."""

    total: int
    items: tuple[Citation, ...]
    nct_ids: tuple[str, ...] | None = None
    """Every contributing trial's NCT ID; responses include it on request."""


def _short_field(field: str) -> str:
    """"protocolSection.designModule.phases" -> "phases"; "...interventions.name" -> "interventions.name"."""
    parts = field.split(".")
    return parts[-1] if len(parts) < 2 or parts[-2].endswith("Module") else ".".join(parts[-2:])


@dataclass(frozen=True)
class Visualization:
    type: ChartType
    title: str
    encoding: dict[str, Channel]
    data: list[dict[str, Any]] | dict[str, list[dict[str, Any]]]
    """Rows; for network graphs {"nodes": [...], "edges": [...]}."""
    notes: tuple[str, ...] = ()
