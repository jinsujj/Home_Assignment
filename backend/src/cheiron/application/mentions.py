"""Use case: why does a trial mention the filtered drug, condition or sponsor?

ClinicalTrials.gov's searches also return trials that only mention the term, e.g. "prior
treatment with pembrolizumab" in eligibility criteria. A language model reads the passages
naming it and judges its role in the trial. Like plan filters, its answer must quote the
record: a quote not found in the passages is discarded and the role becomes unclear.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from cheiron.application.ports import MentionCase, MentionJudge, TrialSource
from cheiron.domain.facets import BRIEF_TITLE
from cheiron.domain.membership import MentionRole, mention_passages
from cheiron.domain.visualization import Evidence

MIN_QUOTE_WORDS = 3  # a bare name ("pembrolizumab") shows nothing about its role
_SECTION_LABEL = re.compile(r"^\s*\[[^\]]*\]\s*")


@dataclass(frozen=True)
class MentionVerdict:
    nct_id: str
    role: MentionRole
    quote: Evidence | None
    """The registered passage (or title) containing the model's quote, verbatim; None if it quoted
    nothing found there."""
    passages: int
    """How many passages naming the entity the model read."""


async def explain_mentions(
    nct_ids: Sequence[str], names: Sequence[str], source: TrialSource, judge: MentionJudge
) -> list[MentionVerdict]:
    """Raises MentionJudgeError or TrialSourceError."""
    texts = await source.trial_texts(list(nct_ids))
    cases = {
        n: MentionCase(n, tuple(names), passages, next(iter(texts[n].get(BRIEF_TITLE, ())), ""))
        for n in nct_ids
        if (passages := mention_passages(texts.get(n, {}), names))
    }
    answers = await judge.judge(list(cases.values())) if cases else {}
    verdicts = []
    for nct_id in nct_ids:
        case = cases.get(nct_id)
        role, quote = answers.get(nct_id, (MentionRole.UNCLEAR, ""))
        # The title is registered text too, and often what shows the role best.
        source_passage = _quoted(quote, (*case.passages, Evidence(BRIEF_TITLE, case.title))) if case else None
        verdicts.append(
            MentionVerdict(
                nct_id,
                role if source_passage else MentionRole.UNCLEAR,
                source_passage,
                len(case.passages) if case else 0,
            )
        )
    return verdicts


def _quoted(quote: str, passages: Sequence[Evidence]) -> Evidence | None:
    """The passage containing `quote` (ignoring spacing and case), if any. Models that reason
    longer tend to copy the section label shown before a passage; it is not part of the quote."""
    wanted = _flat(_SECTION_LABEL.sub("", quote))
    if len(wanted.split()) < MIN_QUOTE_WORDS:
        return None
    return next((p for p in passages if wanted in _flat(p.value)), None)


def _flat(text: str) -> str:
    """Spacing, case and markdown escapes ("etc.\\]") do not change what a quote says."""
    return " ".join(text.replace("\\", "").split()).casefold().strip(" .")
