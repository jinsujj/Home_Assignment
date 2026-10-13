from cheiron.application.planning import FilterDraft, PlanDraft

_NO_FILTERS = {name: None for name in FilterDraft.model_fields}


def cohort(label: str = "", **filters: dict) -> dict:
    return {"label": label, "filter": _NO_FILTERS | filters}


def text(value: str, quote: str | None = None) -> dict:
    return {"value": value, "quote": quote if quote is not None else value}


def draft(**overrides) -> PlanDraft:
    base = {
        "interpretation": "Trials by phase.",
        "answerable": True,
        "refusal": None,
        "kind": "count_by",
        "cohorts": [cohort()],
        "dimension": "phase",
        "split_by": None,
        "top_n": None,
        "source": None,
        "target": None,
        "measure": None,
        "x": None,
        "y": None,
        "trial": None,
        "result_focus": None,
        "outcome": None,
    }
    return PlanDraft.model_validate(base | overrides)
