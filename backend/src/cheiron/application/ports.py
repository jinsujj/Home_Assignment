"""Ports: what the application needs from the outside world."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from cheiron.application.planning import PlanDraft, Question
from cheiron.domain.trial import Trial
from cheiron.domain.trial_filter import TrialFilter


@dataclass(frozen=True)
class TrialSearchResult:
    trials: tuple[Trial, ...]
    total_count: int
    """Trials matching the filter in the source; may exceed len(trials)."""

    @property
    def truncated(self) -> bool:
        return len(self.trials) < self.total_count


class TrialSourceError(Exception):
    """The trial source could not answer, e.g. rejected query or upstream outage."""


class TrialSource(Protocol):
    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        """Return up to `max_trials` trials matching `criteria`.

        `Trial.sites` is only filled with `include_sites`, as sites make responses much larger.
        """
        ...


class PlannerError(Exception):
    """The planner could not be reached or returned no usable draft."""


class QueryPlanner(Protocol):
    async def draft(self, question: Question, feedback: Sequence[str] = ()) -> PlanDraft:
        """Draft a plan for `question`. `feedback` explains why a previous draft was rejected."""
        ...

