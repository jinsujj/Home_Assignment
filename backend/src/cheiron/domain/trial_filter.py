"""Criteria that select which trials an analysis looks at."""

from dataclasses import dataclass

from cheiron.domain.trial import Phase, Status, StudyType


@dataclass(frozen=True)
class TrialFilter:
    """All set criteria must hold (AND). Multi-valued criteria match any value (OR)."""

    condition: str | None = None
    intervention: str | None = None
    sponsor: str | None = None
    country: str | None = None
    """Country name; the API resolves common variants ("USA", "UK", "Korea, Republic of")."""
    phases: frozenset[Phase] = frozenset()
    statuses: frozenset[Status] = frozenset()
    study_type: StudyType | None = None
    start_year_from: int | None = None
    start_year_to: int | None = None

    def __post_init__(self) -> None:
        if (
            self.start_year_from is not None
            and self.start_year_to is not None
            and self.start_year_from > self.start_year_to
        ):
            raise ValueError(
                f"start_year_from ({self.start_year_from}) is after start_year_to ({self.start_year_to})"
            )
