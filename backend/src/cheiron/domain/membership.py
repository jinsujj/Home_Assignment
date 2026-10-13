"""Why a trial is in its cohort: the registered value matching each free-text filter.

ClinicalTrials.gov's searches for an intervention, condition or sponsor also match other text,
such as descriptions: 335 of the 2,974 trials found for pembrolizumab do not register it as an
intervention. The registry tells which trials only mention a term (its synonyms count as
registered); citations of the others name the registered value that matches. Cited trials also
get the passage of their own text that names the filtered entity, verbatim.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from cheiron.domain.facets import (
    ARM_GROUP_DESCRIPTION,
    BRIEF_SUMMARY,
    BRIEF_TITLE,
    COLLABORATOR_NAME,
    CONDITIONS,
    DETAILED_DESCRIPTION,
    ELIGIBILITY_CRITERIA,
    INTERVENTION_DESCRIPTION,
    INTERVENTION_NAME,
    INTERVENTION_OTHER_NAME,
    KEYWORDS,
    LEAD_SPONSOR_NAME,
    OFFICIAL_TITLE,
)
from cheiron.domain.trial import Trial
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Citation, Citations, Evidence, Visualization

FREE_TEXT_CRITERIA = ("intervention", "condition", "sponsor")
# Where a mention says most about the trial, first: titles and the summary describe it, while
# eligibility criteria often name other treatments ("prior therapy with pembrolizumab").
TEXT_ORDER = (
    BRIEF_TITLE,
    OFFICIAL_TITLE,
    BRIEF_SUMMARY,
    ARM_GROUP_DESCRIPTION,
    INTERVENTION_DESCRIPTION,
    DETAILED_DESCRIPTION,
    KEYWORDS,
    ELIGIBILITY_CRITERIA,
)
MAX_PASSAGE = 240
# A sentence ends at ., ! or ? followed by space and a capital (so "e.g. pembrolizumab",
# "etc.", "2.5 mg" do not end one), or at a line break (eligibility criteria are lists).
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'*•-])|\n")
MAX_PASSAGES = 6


class MentionRole(StrEnum):
    """What a named entity is to the trial whose text names it (judged by a language model)."""

    STUDIED = "studied"  # what the trial tests: an arm's treatment, or what it observes
    GIVEN_ALONGSIDE = "given_alongside"  # participants receive it, but the trial tests something else
    ELIGIBILITY = "eligibility"  # it decides who may enroll: prior, current or excluded use
    BACKGROUND = "background"  # named only for context
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class Membership:
    evidence: tuple[Evidence, ...] = ()
    """Registered values matching the cohort's free-text filters."""
    mentioned_only: tuple[str, ...] = ()
    """Filter terms the trial matches only through other text."""
    names: tuple[str, ...] = ()
    """What the filtered entities may be called in the trial's text: the filter terms, the
    registered values matching them, and the value matching most often in the cohort."""

    def with_passage(self, texts: Mapping[str, Sequence[str]]) -> Membership:
        """Adds the passage of `texts` that names a filtered entity, if any."""
        passage = mention_passage(texts, self.names)
        return replace(self, evidence=(*self.evidence, passage)) if passage else self


def memberships(
    trials: Sequence[Trial], criteria: TrialFilter, mentioned: Mapping[str, frozenset[str] | None]
) -> dict[str, Membership]:
    """By NCT ID. `mentioned` gives, per free-text criterion, the trials that only mention it;
    criteria missing from it or mapped to None (unknown) are left out."""
    checked = [
        (criterion, term, ids)
        for criterion in FREE_TEXT_CRITERIA
        if (term := getattr(criteria, criterion)) and (ids := mentioned.get(criterion)) is not None
    ]
    # How common each registered value is among trials that register the term: when a trial
    # registers only a synonym ("Pembrolizumab" for "Keytruda"), the cohort's own drug wins.
    frequency = {
        criterion: Counter(value for t in trials if t.nct_id not in ids for _, value in _registered(t, criterion))
        for criterion, _, ids in checked
    }
    evidence: dict[str, list[Evidence]] = {t.nct_id: [] for t in trials}
    only: dict[str, list[str]] = {t.nct_id: [] for t in trials}
    # A trial that only mentions the drug may call it by the name most trials register for it.
    common: list[str] = []
    for criterion, term, ids in checked:
        matched: Counter[str] = Counter()
        for trial in trials:
            if trial.nct_id in ids:
                only[trial.nct_id].append(term)
            elif match := _match(trial, criterion, term, frequency[criterion]):
                evidence[trial.nct_id].append(match)
                matched[match.value] += 1
        common += [value for value, _ in matched.most_common(1)]
    terms = [term for _, term, _ in checked]
    return {
        t.nct_id: Membership(
            tuple(evidence[t.nct_id]),
            tuple(only[t.nct_id]),
            tuple(dict.fromkeys(terms + [e.value for e in evidence[t.nct_id]] + common)),
        )
        for t in trials
    }


def mention_passage(texts: Mapping[str, Sequence[str]], names: Sequence[str]) -> Evidence | None:
    """The first passage, in TEXT_ORDER, that names one of `names`."""
    passages = mention_passages(texts, names, limit=1)
    return passages[0] if passages else None


def mention_passages(
    texts: Mapping[str, Sequence[str]], names: Sequence[str], limit: int = MAX_PASSAGES
) -> tuple[Evidence, ...]:
    """Passages naming one of `names`, in TEXT_ORDER: each the sentence or line around a name, cut
    to MAX_PASSAGE characters. Always exact substrings of the registered text."""
    if not names:
        return ()
    pattern = re.compile("|".join(rf"(?<!\w){re.escape(n)}(?!\w)" for n in names), re.IGNORECASE)
    found: dict[Evidence, None] = {}
    for field in TEXT_ORDER:
        for text in texts.get(field, ()):
            for match in pattern.finditer(text):
                found[Evidence(field, _passage(text, match.start(), match.end()))] = None
                if len(found) == limit:
                    return tuple(found)
    return tuple(found)


def cohort_names(found: Mapping[str, Membership]) -> tuple[str, ...]:
    """Names every trial of the cohort is searched for: the filter terms and the registered value
    matching them most often."""
    shared = [set(m.names) for m in found.values()]
    first = next(iter(found.values()), Membership())
    return tuple(n for n in first.names if all(n in names for names in shared))


def cited_trials(viz: Visualization) -> set[str]:
    """NCT IDs of every trial a citation spells out."""
    rows = [r for part in viz.data.values() for r in part] if isinstance(viz.data, dict) else viz.data
    return {c.nct_id for r in rows if isinstance(cited := r.get("citations"), Citations) for c in cited.items}


def cite_memberships(
    viz: Visualization, by_cohort: Mapping[str, Mapping[str, Membership]], default_cohort: str | None
) -> Visualization:
    """Adds each cited trial's membership to its citation. A row's cohort is its `cohort` field
    (compared cohorts) or `default_cohort`."""

    def row(r: dict[str, Any]) -> dict[str, Any]:
        cited = r.get("citations")
        found = by_cohort.get(r.get("cohort", default_cohort), {})
        if not isinstance(cited, Citations) or not found:
            return r
        items = tuple(_cite(c, found[c.nct_id]) if c.nct_id in found else c for c in cited.items)
        return r | {"citations": replace(cited, items=items)}

    if isinstance(viz.data, dict):
        return replace(viz, data={part: [row(r) for r in rows] for part, rows in viz.data.items()})
    return replace(viz, data=[row(r) for r in viz.data])


def _cite(citation: Citation, membership: Membership) -> Citation:
    evidence = tuple(dict.fromkeys(citation.evidence + membership.evidence))
    return Citation.of(citation.nct_id, citation.title, evidence, membership.mentioned_only)


def _registered(trial: Trial, criterion: str) -> list[tuple[str, str]]:
    match criterion:
        case "intervention":
            return [(INTERVENTION_NAME, i.name) for i in trial.interventions] + [
                (INTERVENTION_OTHER_NAME, other) for i in trial.interventions for other in i.other_names
            ]
        case "condition":
            return [(CONDITIONS, c) for c in trial.conditions]
        case _:
            lead = [(LEAD_SPONSOR_NAME, trial.lead_sponsor.name)] if trial.lead_sponsor else []
            return lead + [(COLLABORATOR_NAME, s.name) for s in trial.collaborators]


def _match(trial: Trial, criterion: str, term: str, frequency: Counter[str]) -> Evidence | None:
    """The registered value sharing most words with the term; ties go to the most common one."""
    words = _words(term)
    candidates = _registered(trial, criterion)
    if not candidates:
        return None
    field, value = max(candidates, key=lambda c: (len(words & _words(c[1])), frequency[c[1]]))
    return Evidence(field, value)


def _passage(text: str, start: int, end: int) -> str:
    """The sentence or line around text[start:end], at most MAX_PASSAGE characters."""
    left = max((b.end() for b in _SENTENCE_BREAK.finditer(text, 0, start + 1) if b.end() <= start), default=0)
    after = _SENTENCE_BREAK.search(text, end)
    right = after.start() if after else len(text)
    if right - left > MAX_PASSAGE:
        # Keep MAX_PASSAGE characters around the name; room one side does not use goes to the other.
        room = max(MAX_PASSAGE - (end - start), 0)
        before = min(start - left, max(room // 2, room - (right - end)))
        after = room - before
        if start - left > before:  # cut at a word boundary, never inside a word
            left = text.find(" ", start - before, start) + 1 or start
        if right - end > after:
            space = text.rfind(" ", end, end + after)
            right = space if space > end else end
    return text[left:right].strip()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))
