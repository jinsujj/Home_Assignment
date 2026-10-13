"""Which registered trial a name refers to.

Names are ambiguous in the registry: "KEYNOTE-189" is a secondary ID only of the trial's
40-patient Japan extension, while the 616-patient main trial carries it only in its title,
and observational "emulations" of it mention it too; a common word like "RECOVERY" is in
thousands of titles. The rule, stated in every answer that had alternatives:

1. An exact acronym match wins over IDs and titles.
2. IDs and whole-word title matches count only for distinctive names (with a digit or
   several words), not for single common words.
3. Of the matches with posted results, the largest enrollment is chosen; the others are
   returned as alternatives the user can switch to.
"""

import re
from dataclasses import dataclass

from cheiron.application.ports import TrialCandidate, TrialResultsSource


class TrialNotFound(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"No trial registered as '{name}' was found.")
        self.name = name


class NoPostedResults(Exception):
    def __init__(self, nct_id: str, title: str | None = None) -> None:
        super().__init__(f"{nct_id} has not posted results on ClinicalTrials.gov.")
        self.nct_id = nct_id
        self.title = title


@dataclass(frozen=True)
class TrialChoice:
    chosen: TrialCandidate
    alternatives: tuple[TrialCandidate, ...]

    def note(self, name: str) -> str | None:
        if not self.alternatives:
            return None
        others = "; ".join(f"{c.nct_id} ({c.enrollment or '?'} participants)" for c in self.alternatives)
        return (
            f"'{name}' matches {len(self.alternatives) + 1} trials with posted results; showing {self.chosen.nct_id}, "
            f"the largest ({self.chosen.enrollment} participants). Also matching: {others}."
        )


async def choose_trial(name: str, source: TrialResultsSource) -> TrialChoice:
    candidates = await source.find_trials(name)
    pool = [c for c in candidates if c.matched_by == "acronym"]
    if not pool and _distinctive(name):
        pool = [c for c in candidates if c.matched_by in ("study_id", "title")]
    if not pool:
        raise TrialNotFound(name)
    with_results = sorted((c for c in pool if c.has_results), key=lambda c: (-(c.enrollment or 0), c.nct_id))
    if not with_results:
        largest = max(pool, key=lambda c: c.enrollment or 0)
        raise NoPostedResults(largest.nct_id, largest.title)
    return TrialChoice(with_results[0], tuple(with_results[1:]))


def _distinctive(name: str) -> bool:
    return bool(re.search(r"\d", name)) or len(name.split()) > 1
