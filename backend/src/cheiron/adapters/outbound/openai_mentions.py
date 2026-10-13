"""MentionJudge backed by an OpenAI model with structured outputs.

The model reads only the passages that name the entity and returns, per trial, one role from a
fixed list and the words it relied on. The application checks those words against the record.
"""

from collections.abc import Sequence
from typing import Any

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from cheiron.application.ports import MentionCase, MentionJudgeError
from cheiron.domain.membership import MentionRole

INSTRUCTIONS = """\
You read passages from ClinicalTrials.gov records. Each trial comes with its title and the
passages of its record that name an entity (a drug, condition or sponsor). Decide, from these
alone, what that entity is to the trial:

- studied: the trial is about it. For a drug: the treatment one of its arms tests (experimental
  or comparator), or, in an observational study, the exposure whose effects, response or side
  effects it observes. For a condition: the disease of the participants that the trial treats or
  studies (also a subtype or stage of it); a diagnosis required to enroll means the participants
  have it, so it is studied. For an organisation: it runs or funds the trial.
- given_alongside: participants receive it during the trial as usual care, while the trial's
  question is about something else (a supplement, device, follow-up method, test or biomarker),
  even when the eligibility criteria require it, and even when it is one example of the care they
  receive ("immunotherapy, e.g. pembrolizumab").
- eligibility: only past or excluded use of a drug, or a condition participants must not have
  (or may have only as history) while the trial is about something else.
- background: it is named only for context and participants are not given it in the trial, e.g.
  "drugs such as ... have changed treatment".
- unclear: the title and passages do not say.

`quote`: copy the words of the title or of one passage that show the role, exactly as written (a
sentence or less), without the section name shown before a passage. Never paraphrase and never combine passages.
Answer for every trial.
"""


class _Verdict(BaseModel):
    nct_id: str
    role: MentionRole
    quote: str


class _Verdicts(BaseModel):
    verdicts: list[_Verdict]


class OpenAIMentionJudge:
    def __init__(self, client: AsyncOpenAI, model: str, reasoning_effort: str | None = None) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort

    async def judge(self, cases: Sequence[MentionCase]) -> dict[str, tuple[MentionRole, str]]:
        options: dict[str, Any] = {}
        if self._reasoning_effort:
            options["reasoning"] = {"effort": self._reasoning_effort}
        try:
            response = await self._client.responses.parse(
                model=self._model, instructions=INSTRUCTIONS, input=render_input(cases), text_format=_Verdicts, **options
            )
        except openai.OpenAIError as error:
            raise MentionJudgeError(f"The language model is unavailable: {error}") from error
        if response.output_parsed is None:
            raise MentionJudgeError("The language model returned no verdicts.")
        asked = {c.nct_id for c in cases}
        return {v.nct_id: (v.role, v.quote) for v in response.output_parsed.verdicts if v.nct_id in asked}


def render_input(cases: Sequence[MentionCase]) -> str:
    blocks = []
    for case in cases:
        lines = [f"Trial {case.nct_id}: {case.title}", f"The entity is named: {', '.join(case.names)}"]
        lines += [f"[{_section(p.field)}] {p.value}" for p in case.passages]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _section(field: str) -> str:
    """"...eligibilityModule.eligibilityCriteria" -> "eligibility criteria";
    "...armGroups.description" -> "arm groups description"."""
    *_, parent, last = field.split(".")
    return _spaced(f"{parent}.{last}" if last == "description" else last).replace(".", " ")


def _spaced(camel: str) -> str:
    return "".join(f" {c.lower()}" if c.isupper() else c for c in camel).strip()
