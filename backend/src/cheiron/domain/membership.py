"""Why a trial is in its cohort: the registered value matching each free-text filter.

ClinicalTrials.gov's searches for an intervention, condition or sponsor also match other text,
such as descriptions: 335 of the 2,974 trials found for pembrolizumab do not register it as an
intervention. The registry tells which trials only mention a term (its synonyms count as
registered); citations of the others name the registered value that matches.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from cheiron.domain.facets import (
    COLLABORATOR_NAME,
    CONDITIONS,
    INTERVENTION_NAME,
    INTERVENTION_OTHER_NAME,
    LEAD_SPONSOR_NAME,
)
from cheiron.domain.trial import Trial
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Citation, Citations, Evidence, Visualization

FREE_TEXT_CRITERIA = ("intervention", "condition", "sponsor")


@dataclass(frozen=True)
class Membership:
    evidence: tuple[Evidence, ...] = ()
    """Registered values matching the cohort's free-text filters."""
    mentioned_only: tuple[str, ...] = ()
    """Filter terms the trial matches only through other text."""


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
    result = {}
    for trial in trials:
        evidence, only = [], []
        for criterion, term, ids in checked:
            if trial.nct_id in ids:
                only.append(term)
            elif match := _match(trial, criterion, term, frequency[criterion]):
                evidence.append(match)
        result[trial.nct_id] = Membership(tuple(evidence), tuple(only))
    return result


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


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))
