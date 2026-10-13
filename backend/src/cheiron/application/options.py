"""Choices for building filters: what clients can offer instead of free typing.

Countries are the registry's complete list, so a chosen value always matches its spelling.
Conditions, interventions and sponsors are the registry's most common values, offered as
suggestions; any other text still works because the API resolves synonyms.
"""

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cheiron.application.ports import TermCount, Vocabulary, VocabularySource
from cheiron.domain.facets import PHASE_ORDER, label
from cheiron.domain.trial import Status

STATUS_ORDER = (
    Status.RECRUITING,
    Status.NOT_YET_RECRUITING,
    Status.ENROLLING_BY_INVITATION,
    Status.ACTIVE_NOT_RECRUITING,
    Status.COMPLETED,
    Status.SUSPENDED,
    Status.TERMINATED,
    Status.WITHDRAWN,
    Status.UNKNOWN,
)

# Among the most common intervention names, but not useful as search terms (seen in the registry's
# top list: "Placebo", "Control", "No intervention", "Usual Care", "Saline", "Questionnaire", ...).
_NOT_A_SEARCH_TERM = re.compile(
    r"placebo|control|no intervention|usual care|standard of care|saline|questionnaire"
    r"|biospecimen|biomarker analysis|quality-of-life|assessment",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    trials: int | None = None
    """Registry-wide number of trials, where known."""


@dataclass(frozen=True)
class SearchOptions:
    countries: tuple[Choice, ...]
    conditions: tuple[Choice, ...]
    interventions: tuple[Choice, ...]
    sponsors: tuple[Choice, ...]
    phases: tuple[Choice, ...]
    statuses: tuple[Choice, ...]


class SearchOptionsProvider:
    """Builds SearchOptions from the registry and keeps them for `ttl_seconds`."""

    def __init__(
        self, source: VocabularySource, ttl_seconds: float = 6 * 3600, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._source = source
        self._ttl = ttl_seconds
        self._clock = clock
        self._cached: tuple[float, SearchOptions] | None = None

    async def get(self) -> SearchOptions:
        if self._cached and self._clock() - self._cached[0] < self._ttl:
            return self._cached[1]
        terms = await self._source.common_terms()
        options = SearchOptions(
            countries=tuple(sorted(_choices(terms[Vocabulary.COUNTRY]), key=lambda c: c.label)),
            conditions=_choices(terms[Vocabulary.CONDITION]),
            interventions=_choices(t for t in terms[Vocabulary.INTERVENTION] if not _NOT_A_SEARCH_TERM.search(t.term)),
            sponsors=_choices(terms[Vocabulary.SPONSOR]),
            phases=tuple(Choice(p, label(p)) for p in PHASE_ORDER),
            statuses=tuple(Choice(s, label(s)) for s in STATUS_ORDER),
        )
        self._cached = (self._clock(), options)
        return options


def _choices(terms: Iterable[TermCount]) -> tuple[Choice, ...]:
    """One choice per term ignoring case and spacing, under its most common spelling."""
    first: dict[str, Choice] = {}
    for term in terms:
        first.setdefault(" ".join(term.term.split()).casefold(), Choice(term.term, term.term, term.trials))
    return tuple(first.values())
