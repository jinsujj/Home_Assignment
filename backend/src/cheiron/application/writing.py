"""What the answer writer reads and writes.

The writer (an LLM) reads the chart's data as numbered items and writes a short answer whose
sentences cite the items they draw on, plus follow-up questions. AnswerDraft is a Pydantic model
because it doubles as the JSON Schema that constrains the LLM's output, like PlanDraft.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

type Value = str | int | float | bool | None


@dataclass(frozen=True)
class Item:
    """One thing the answer may cite: a cohort, a chart row, a network node or link, or a note."""

    id: str
    """What the writer cites it by: c0 (cohort), r3 (row), n2 (node), e5 (link), t1 (note)."""
    pointer: str | None
    """Where it sits in the /api/visualize response, as a JSON pointer; None for a note
    without citations, which can be cited but not opened."""
    fields: tuple[tuple[str, Value], ...]


@dataclass(frozen=True)
class AnswerContext:
    question: str
    chart: str
    """The chart's type and title."""
    items: tuple[Item, ...]


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SentenceDraft(_Draft):
    text: str = Field(description="One sentence of the answer. Every number is copied from the items it cites.")
    refs: list[str] = Field(description="Ids of the items the sentence's numbers and claims come from, e.g. ['r3', 'c0'].")


class AnswerDraft(_Draft):
    sentences: list[SentenceDraft] = Field(description="One to three sentences answering the question.")
    follow_ups: list[str] = Field(
        description="Up to three short follow-up questions, e.g. 'Only recruiting trials', 'By country instead'."
    )
