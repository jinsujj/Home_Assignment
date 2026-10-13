"""Use case: a short written answer from the computed data only, and follow-up questions
planned before they are offered.

The writer sees the chart's data as numbered items (writing.Item) and cites, per sentence, the
items it draws on. `check` keeps a sentence only if every number in it is found in those items
(or in the question or chart title), so an answer cannot state a figure the data does not show;
comparisons in words ("more than") are the writer's reading. Each follow-up question is planned
as a follow-up of this one, and only those that plan are offered, so choosing one always charts.
"""

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from cheiron.application.planning import Question, UnsupportedQuestion
from cheiron.application.ports import AnswerWriter, PlannerError, QueryPlanner, TrialSource
from cheiron.application.run_plan import DEFAULT_MAX_TRIALS, PlanResult, run_plan
from cheiron.application.visualize import PlanningFailed, plan_question
from cheiron.application.writing import AnswerContext, AnswerDraft, Item, Value
from cheiron.domain.analysis import AnalysisPlan, CountBy, TrialResults

MAX_SENTENCES = 3
MAX_FOLLOW_UPS = 3
MAX_ITEMS = 60
"""Rows, nodes or links shown to the writer, in chart order (a scatter has a row per trial)."""
MAX_EARLIER = 5
"""Questions a follow-up carries as its conversation, like the API's `context.questions`."""

# A number, not part of a word or code such as "NCT01234567"; "1,777" is one number.
_NUMBER = re.compile(r"(?<![A-Za-z\d.,])\d+(?:,\d{3})*(?:\.\d+)?")


@dataclass(frozen=True)
class Sentence:
    text: str
    refs: tuple[str, ...]
    """JSON pointers into the /api/visualize response: the data the sentence cites."""


@dataclass(frozen=True)
class FollowUp:
    query: str
    interpretation: str
    plan: AnalysisPlan


@dataclass(frozen=True)
class WrittenAnswer:
    sentences: tuple[Sentence, ...]
    dropped: int
    """Sentences left out because a number in them is not in the items they cite."""
    follow_ups: tuple[FollowUp, ...]


async def write_answer(
    question: Question,
    plan: AnalysisPlan,
    plan_json: str,
    writer: AnswerWriter,
    planner: QueryPlanner,
    source: TrialSource,
    max_trials_per_cohort: int = DEFAULT_MAX_TRIALS,
) -> WrittenAnswer:
    """`plan` answered `question` (its JSON, as the API shows it, is `plan_json`); running it
    again comes from cache. Raises AnswerWriterError."""
    result = await run_plan(plan, source, max_trials_per_cohort)
    context = answer_context(question.text, result)
    draft = await writer.write(context)
    sentences, dropped = check(draft, context)
    follow_ups = await _plan_follow_ups(draft.follow_ups, question, plan, plan_json, planner)
    return WrittenAnswer(sentences, dropped, follow_ups)


def answer_context(question: str, result: PlanResult) -> AnswerContext:
    viz = result.visualization
    items = [
        Item(f"c{i}", f"#/meta/cohorts/{i}", (("cohort", c.label), ("matched", c.matched), ("analyzed", c.analyzed)))
        for i, c in enumerate(result.cohorts)
    ]
    parts = viz.data.items() if isinstance(viz.data, dict) else [("data", viz.data)]
    series = viz.encoding["series"].field if "series" in viz.encoding else None
    for part, rows in parts:
        prefix, at = {"data": ("r", ""), "nodes": ("n", "/nodes"), "edges": ("e", "/edges")}[part]
        ranks = _ranks(rows, series)
        items += [
            Item(f"{prefix}{i}", f"#/visualization/data{at}/{i}", _scalars(row) + ranks.get(i, ()))
            for i, row in enumerate(rows[:MAX_ITEMS])
        ]
    # Notes appear in meta.note_citations (in this order) when they count trials.
    cited = [note for note, _ in (*viz.note_citations, *result.note_citations)]
    for i, note in enumerate((*viz.notes, *result.notes)):
        pointer = f"#/meta/note_citations/{cited.index(note)}/citations" if note in cited else None
        items.append(Item(f"t{i}", pointer, (("note", note),)))
    single = f" (posted results of one trial, {result.trial.nct_id})" if result.trial else ""
    return AnswerContext(question, f"{viz.type}: {viz.title}{single}", tuple(items))


def check(draft: AnswerDraft, context: AnswerContext) -> tuple[tuple[Sentence, ...], int]:
    """The sentences whose every number is in the items they cite, the question or the title,
    and how many were dropped (including those citing nothing or unknown items)."""
    items = {item.id: item for item in context.items}
    background = _numbers(context.question) | _numbers(context.chart)
    kept: list[Sentence] = []
    dropped = 0
    for sentence in draft.sentences[:MAX_SENTENCES]:
        cited = [items[ref] for ref in sentence.refs if ref in items]
        allowed = background | {n for item in cited for _, value in item.fields for n in _value_numbers(value)}
        if not cited or len(cited) < len(sentence.refs) or not _numbers(sentence.text) <= allowed:
            dropped += 1
            continue
        pointers = tuple(dict.fromkeys(item.pointer for item in cited if item.pointer))
        kept.append(Sentence(sentence.text.strip(), pointers))
    return tuple(kept), dropped


async def _plan_follow_ups(
    texts: Sequence[str], question: Question, plan: AnalysisPlan, plan_json: str, planner: QueryPlanner
) -> tuple[FollowUp, ...]:
    """Planned in parallel as follow-ups of `question`; the planner caches each, so asking one
    later is instant. Those that do not plan, or plan the same analysis again, are left out."""
    earlier = (*question.earlier, question.text)[-MAX_EARLIER:]

    async def planned(text: str) -> FollowUp | None:
        follow_up = Question(text, question.fields, earlier, plan_json)
        try:
            grounded = await plan_question(follow_up, planner)
        except (UnsupportedQuestion, PlanningFailed, PlannerError):
            return None
        return FollowUp(text, grounded.interpretation, grounded.plan)

    asked = [t.strip() for t in texts if t.strip()][:MAX_FOLLOW_UPS]
    distinct: dict[AnalysisPlan, FollowUp] = {}
    for found in await asyncio.gather(*(planned(t) for t in asked)):
        if found and _unlabeled(found.plan) != _unlabeled(plan):
            distinct.setdefault(_unlabeled(found.plan), found)
    return tuple(distinct.values())


def _unlabeled(plan: AnalysisPlan) -> AnalysisPlan:
    """The analysis with placeholder legend labels (which must stay distinct), as labels do not
    change what is counted."""
    if isinstance(plan, CountBy):
        return replace(plan, cohorts=tuple(replace(c, label=str(i)) for i, c in enumerate(plan.cohorts)))
    if isinstance(plan, TrialResults):
        return plan
    return replace(plan, cohort=replace(plan.cohort, label=""))


def _ranks(rows: Sequence[dict], series: str | None) -> dict[int, tuple[tuple[str, Value], ...]]:
    """Each row's rank by trial count within its series (1 = most trials). Rows come in chart
    order (phases, years); measured, the writer read "Phase 2 has the most" off that order when
    "Not applicable" had more, so the ranking is stated rather than left to it."""
    counted = [(i, row) for i, row in enumerate(rows) if isinstance(row.get("trial_count"), int)]
    ranks = {}
    for group in {row.get(series) if series else None for _, row in counted}:
        members = [(i, row["trial_count"]) for i, row in counted if (row.get(series) if series else None) == group]
        for i, count in members:
            ranks[i] = (("rank_by_trials", 1 + sum(other > count for _, other in members)),)
    return ranks


def _scalars(row: dict) -> tuple[tuple[str, Value], ...]:
    return tuple(
        (key, value)
        for key, value in row.items()
        if key != "citations" and (value is None or isinstance(value, (str, int, float, bool)))
    )


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(n.replace(",", "")) for n in _NUMBER.findall(text)}


def _value_numbers(value: Value) -> set[Decimal]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return {Decimal(str(value))}
    return _numbers(value)
