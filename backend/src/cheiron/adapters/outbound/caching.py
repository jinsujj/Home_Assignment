"""In-memory caches as port decorators: registry data until new data is published, and plans.

CachingTrialSource keeps searches, category counts, mention checks, name lookups and posted
results until new data is published.

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
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from typing import Any

from cheiron.application.planning import PlanDraft, Question
from cheiron.application.ports import QueryPlanner, Registry, TrialCandidate, TrialSearchResult, TrialSourceError
from cheiron.domain.analysis import Dimension
from cheiron.domain.results import PostedResults
from cheiron.domain.trial_filter import TrialFilter

SITE_WEIGHT = 3  # site lists roughly triple a result's memory (measured)
RESULTS_WEIGHT = 500  # one trial's posted results (~220 KB of JSON) weigh about as much as 500 trials
NAME_LOOKUP_WEIGHT = 1
COUNTS_WEIGHT = 1


class CachingTrialSource:
    """Caches searches, category counts, name lookups and posted results; capacity is counted in trial-equivalents."""

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

    async def count_by(self, criteria: TrialFilter, dimension: Dimension, keys: Sequence[str]) -> dict[str, int] | None:
        return await self._cached(
            ("count_by", criteria, dimension, tuple(keys)),
            lambda: self._inner.count_by(criteria, dimension, keys),
            lambda _: COUNTS_WEIGHT,
        )

    async def mentioned_only(self, criteria: TrialFilter, criterion: str, limit: int) -> frozenset[str] | None:
        return await self._cached(
            ("mentioned_only", criteria, criterion, limit),
            lambda: self._inner.mentioned_only(criteria, criterion, limit),
            lambda _: COUNTS_WEIGHT,
        )

    async def find_trials(self, name: str) -> tuple[TrialCandidate, ...]:
        return await self._cached(
            ("find", " ".join(name.casefold().split())), lambda: self._inner.find_trials(name), lambda _: NAME_LOOKUP_WEIGHT
        )

    async def posted_results(self, nct_id: str) -> PostedResults | None:
        return await self._cached(
            ("results", nct_id.upper()), lambda: self._inner.posted_results(nct_id), lambda _: RESULTS_WEIGHT
        )

    async def data_version(self) -> str | None:
        """The snapshot the cached data belongs to, checked at most every `version_check_seconds`."""
        await self._drop_if_new_data()
        return self._version

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


class CachingPlanner:
    """QueryPlanner decorator: the same question gets the same draft without another LLM call.

    Measured: a repeated question spent ~90% of its 2.3 s in the planner while the data came
    from cache in 0.2 s. The key is everything the planner sees: the question (ignoring case,
    spacing and a trailing "?"), the structured fields, the correction feedback, and today's
    date, which resolves "in the last 5 years". A correction round is cached too, under its
    own feedback, so a question that needed one is also instant the next time.
    """

    def __init__(self, inner: QueryPlanner, max_plans: int = 256, today: Callable[[], date] = date.today) -> None:
        self._inner = inner
        self._max = max_plans
        self._today = today
        self._drafts: OrderedDict[tuple, PlanDraft] = OrderedDict()

    async def draft(self, question: Question, feedback: Sequence[str] = ()) -> PlanDraft:
        text = " ".join(question.text.casefold().split()).rstrip(" ?")
        key = (text, question.fields, tuple(feedback), self._today())
        if key in self._drafts:
            self._drafts.move_to_end(key)
            return self._drafts[key]
        draft = await self._inner.draft(question, feedback)
        self._drafts[key] = draft
        if len(self._drafts) > self._max:
            self._drafts.popitem(last=False)
        return draft
