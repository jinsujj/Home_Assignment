"""TrialSource decorator that keeps search results in memory until the source publishes new data.

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

from cheiron.application.ports import TrialSearchResult, TrialSource, TrialSourceError
from cheiron.domain.trial_filter import TrialFilter

type _Key = tuple[TrialFilter, int, bool]

SITE_WEIGHT = 3  # site lists roughly triple a result's memory (measured)


class CachingTrialSource:
    def __init__(
        self,
        inner: TrialSource,
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
        self._entries: OrderedDict[_Key, tuple[float, TrialSearchResult]] = OrderedDict()
        self._version: str | None = None
        self._checked_at: float | None = None

    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        await self._drop_if_new_data()
        key = (criteria, max_trials, include_sites)
        cached = self._entries.get(key)
        if cached and self._clock() - cached[0] < self._max_age:
            self._entries.move_to_end(key)
            return cached[1]

        result = await self._inner.search(criteria, max_trials, include_sites=include_sites)
        self._entries[key] = (self._clock(), result)
        self._entries.move_to_end(key)
        self._evict()
        return result

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
        """Drop least recently used results until the cache fits its capacity."""
        while len(self._entries) > 1 and self._weight() > self._capacity:
            self._entries.popitem(last=False)

    def _weight(self) -> int:
        return sum(
            len(result.trials) * (SITE_WEIGHT if include_sites else 1)
            for (_, _, include_sites), (_, result) in self._entries.items()
        )
