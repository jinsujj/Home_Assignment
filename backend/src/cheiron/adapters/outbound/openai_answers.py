"""AnswerWriter backed by an OpenAI model with structured outputs (AnswerDraft's JSON Schema).

Checking the sentences' numbers and planning the follow-ups are the application's job
(cheiron.application.answers), not this adapter's.
"""

from typing import Any

import openai
from openai import AsyncOpenAI

from cheiron.application.ports import AnswerWriterError
from cheiron.application.writing import AnswerContext, AnswerDraft

INSTRUCTIONS = """\
You answer a question about clinical trials in one to three sentences, using only the items
given, which a program computed from ClinicalTrials.gov records. Item ids: c = a cohort (the trials
a filter matched), r = a chart row, n = a network node, e = a network link, t = a note on the data.

- Copy every number exactly as it appears in the items a sentence cites: no rounding, sums,
  differences, ratios, percentages or approximations ("mid-200s", "over 1,000") of your own. Say
  the rest in words ("most", "fewer", "about twice", "roughly flat") when the cited items show it.
- Pick the figures that answer the question (the largest, the change, the extremes) rather than
  listing every row. Rows come in chart order (phases, years), not by size: `rank_by_trials`
  gives a row's rank within its cohort (1 = most trials), so read "most" and "second" from it.
- In `refs`, list for each sentence every item its numbers and claims come from. Cite the rows,
  nodes or links a number appears in, as they open the trials behind it; cite a note only for
  what no row shows.
- Lead with the direct answer, then the most telling comparison or pattern. When a note says the
  counts cover only some of the matching trials, or that many trials lack the value, say so.
- Describe what the registry records show. Never say whether a treatment works or what anyone
  should do.

Also suggest up to three follow-up questions about the same trials that one chart could answer,
each naming only what changes, as a user would type it: narrow them (a status, phase, country or
years, e.g. "Only recruiting trials"), view them by a dimension the chart does not already show
(phase, status, country, start year, sponsor class, intervention type, e.g. "By country
instead"), compare with a related
group the question does not already cover (a brand name and its generic name are the same drug),
or show a network of the drugs or sponsors involved. When the chart shows one trial's posted
results, suggest another of its results instead ("Its serious adverse events", a secondary
outcome the question did not ask about) or trials of its drug across the registry.
"""


class OpenAIAnswerWriter:
    def __init__(self, client: AsyncOpenAI, model: str, reasoning_effort: str | None = None) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort

    async def write(self, context: AnswerContext) -> AnswerDraft:
        options: dict[str, Any] = {}
        if self._reasoning_effort:
            options["reasoning"] = {"effort": self._reasoning_effort}
        try:
            response = await self._client.responses.parse(
                model=self._model, instructions=INSTRUCTIONS, input=render_input(context), text_format=AnswerDraft, **options
            )
        except openai.OpenAIError as error:
            raise AnswerWriterError(f"The language model is unavailable: {error}") from error
        if response.output_parsed is None:
            raise AnswerWriterError("The language model returned no answer.")
        return response.output_parsed


def render_input(context: AnswerContext) -> str:
    lines = [f"Question: {context.question}", f"Chart: {context.chart}", "Items:"]
    lines += [f"{item.id}: " + "; ".join(f"{k}={v}" for k, v in item.fields) for item in context.items]
    return "\n".join(lines)
