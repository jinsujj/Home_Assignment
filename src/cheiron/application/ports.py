"""Ports: what the application needs from the outside world."""

from dataclasses import dataclass
from typing import Protocol

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
    async def search(self, criteria: TrialFilter, max_trials: int) -> TrialSearchResult:
        """Return up to `max_trials` trials matching `criteria`."""
        ...
