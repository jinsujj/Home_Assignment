"""Registry decorator that keeps searches, name lookups and posted results until new data is published.

ClinicalTrials.gov publishes data in one batch per US business day (measured: ~800–1,200
updated studies per posting day, none on weekends and holidays), and `/version` reports
the snapshot timestamp. Results are therefore kept until that timestamp changes, checked
at most every few minutes, instead of expiring on a fixed timer. A maximum age still
bounds staleness if the version check keeps failing.

One process, one cache: with several API instances a shared store such as Redis would
implement the same port.
"""

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from cheiron.application.ports import Registry, TrialCandidate, TrialSearchResult, TrialSourceError
from cheiron.domain.results import PostedResults
from cheiron.domain.trial_filter import TrialFilter

SITE_WEIGHT = 3  # site lists roughly triple a result's memory (measured)
RESULTS_WEIGHT = 500  # one trial's posted results (~220 KB of JSON) weigh about as much as 500 trials
NAME_LOOKUP_WEIGHT = 1


class CachingTrialSource:
    """Caches searches, name lookups and posted results; capacity is counted in trial-equivalents."""

    def __init__(
        self,
        inner: Registry,
        data_version: Callable[[], Awaitable[str]],
        version_check_seconds: float = 600,
        max_age_seconds: float = 24 * 3600,
        max_cached_trials: int = 30_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._data_version = data_version
        self._check_interval = version_check_seconds
        self._max_age = max_age_seconds
        self._capacity = max_cached_trials
        self._clock = clock
        self._entries: OrderedDict[tuple, tuple[float, int, Any]] = OrderedDict()
        self._version: str | None = None
        self._checked_at: float | None = None

    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        return await self._cached(
            ("search", criteria, max_trials, include_sites),
            lambda: self._inner.search(criteria, max_trials, include_sites=include_sites),
            lambda result: len(result.trials) * (SITE_WEIGHT if include_sites else 1),
        )

    async def find_trials(self, name: str) -> tuple[TrialCandidate, ...]:
        return await self._cached(
            ("find", " ".join(name.casefold().split())), lambda: self._inner.find_trials(name), lambda _: NAME_LOOKUP_WEIGHT
        )

    async def posted_results(self, nct_id: str) -> PostedResults | None:
        return await self._cached(
            ("results", nct_id.upper()), lambda: self._inner.posted_results(nct_id), lambda _: RESULTS_WEIGHT
        )

    async def _cached(self, key: tuple, fetch: Callable[[], Awaitable[Any]], weight: Callable[[Any], int]) -> Any:
        await self._drop_if_new_data()
        cached = self._entries.get(key)
        if cached and self._clock() - cached[0] < self._max_age:
            self._entries.move_to_end(key)
            return cached[2]

        value = await fetch()
        self._entries[key] = (self._clock(), weight(value), value)
        self._entries.move_to_end(key)
        self._evict()
        return value

    async def _drop_if_new_data(self) -> None:
        now = self._clock()
        if self._checked_at is not None and now - self._checked_at < self._check_interval:
            return
        self._checked_at = now
        try:
            version = await self._data_version()
        except TrialSourceError:
            return  # keep serving; entries still expire at max age
        if version != self._version:
            self._entries.clear()
            self._version = version

    def _evict(self) -> None:
        """Drop least recently used entries until the cache fits its capacity."""
        while len(self._entries) > 1 and sum(weight for _, weight, _ in self._entries.values()) > self._capacity:
            self._entries.popitem(last=False)
