"""Ports: what the application needs from the outside world."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from cheiron.application.planning import PlanDraft, Question
from cheiron.domain.analysis import Dimension
from cheiron.domain.membership import MentionRole
from cheiron.domain.results import PostedResults
from cheiron.domain.trial import Trial
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Evidence, RegistryCount


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

    async def count_by(
        self, criteria: TrialFilter, dimension: Dimension, keys: Sequence[str]
    ) -> dict[str, RegistryCount] | None:
        """How many of all trials matching `criteria` register each key under `dimension`.

        Unlike `search`, there is no cap. None when the source cannot count this dimension.
        """
        ...

    async def category_ids(
        self, criteria: TrialFilter, dimension: Dimension, key: str, limit: int
    ) -> tuple[str, ...] | None:
        """NCT IDs of every trial count_by counted for `key`; None when there are more than `limit`."""
        ...

    async def mentioned_only(self, criteria: TrialFilter, criterion: str, limit: int) -> frozenset[str] | None:
        """NCT IDs of trials matching `criteria` that do not register the free-text `criterion`
        ("intervention", "condition" or "sponsor"; synonyms count as registered) and match it only
        through other text, such as a description. None when there are more than `limit`."""
        ...

    async def trial_texts(self, nct_ids: Sequence[str]) -> dict[str, dict[str, tuple[str, ...]]]:
        """Free text of each trial (titles, summary, descriptions, keywords, eligibility criteria),
        by NCT ID and field path; trials not found are left out."""
        ...

    async def data_version(self) -> str | None:
        """Timestamp of the registry data snapshot being served; None when unknown."""
        ...


class PlannerError(Exception):
    """The planner could not be reached or returned no usable draft."""


class QueryPlanner(Protocol):
    async def draft(self, question: Question, feedback: Sequence[str] = ()) -> PlanDraft:
        """Draft a plan for `question`. `feedback` explains why a previous draft was rejected."""
        ...


@dataclass(frozen=True)
class MentionCase:
    """A trial and the passages of its text that name the entity whose role is judged."""

    nct_id: str
    names: tuple[str, ...]
    passages: tuple[Evidence, ...]
    title: str = ""
    """What the trial is about: passages alone often do not say what it tests."""


class MentionJudgeError(Exception):
    """The language model could not judge the mentions."""


class MentionJudge(Protocol):
    async def judge(self, cases: Sequence[MentionCase]) -> dict[str, tuple[MentionRole, str]]:
        """Per NCT ID: the entity's role in the trial and the words quoted from the case's passages."""
        ...


class Vocabulary(StrEnum):
    """Registry fields whose common values help users build filters."""

    COUNTRY = "country"
    CONDITION = "condition"
    INTERVENTION = "intervention"
    SPONSOR = "sponsor"


@dataclass(frozen=True)
class TermCount:
    term: str
    trials: int


class VocabularySource(Protocol):
    async def common_terms(self) -> dict[Vocabulary, tuple[TermCount, ...]]:
        """Registry-wide values by number of trials, most common first (a top list per vocabulary)."""
        ...


@dataclass(frozen=True)
class TrialCandidate:
    """A trial found by name, and how the name matched it."""

    nct_id: str
    title: str
    acronym: str | None
    has_results: bool
    enrollment: int | None
    matched_by: Literal["acronym", "study_id", "title"] | None
    """None when the registry's search matched loosely (e.g. one word of the name)."""


class TrialResultsSource(Protocol):
    async def find_trials(self, name: str) -> tuple[TrialCandidate, ...]:
        """Trials whose acronym, study IDs or titles mention `name`."""
        ...

    async def posted_results(self, nct_id: str) -> PostedResults | None:
        """The trial's posted results; None if it has none or does not exist."""
        ...


class Registry(TrialSource, TrialResultsSource, Protocol):
    """Everything the use cases read from the registry."""
