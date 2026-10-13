"""The domain's view of a clinical trial.

Holds only the attributes analyses need. Enum values and free-text values keep
ClinicalTrials.gov's own vocabulary so citations can quote them verbatim.
Enum members mirror the ClinicalTrials.gov API v2.0.5 spec (docs/ctgov-openapi-v2.0.5.yaml).
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class Phase(StrEnum):
    NA = "NA"
    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"


class Status(StrEnum):
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    COMPLETED = "COMPLETED"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"
    AVAILABLE = "AVAILABLE"
    NO_LONGER_AVAILABLE = "NO_LONGER_AVAILABLE"
    TEMPORARILY_NOT_AVAILABLE = "TEMPORARILY_NOT_AVAILABLE"
    APPROVED_FOR_MARKETING = "APPROVED_FOR_MARKETING"
    WITHHELD = "WITHHELD"
    UNKNOWN = "UNKNOWN"


class StudyType(StrEnum):
    EXPANDED_ACCESS = "EXPANDED_ACCESS"
    INTERVENTIONAL = "INTERVENTIONAL"
    OBSERVATIONAL = "OBSERVATIONAL"


class InterventionType(StrEnum):
    BEHAVIORAL = "BEHAVIORAL"
    BIOLOGICAL = "BIOLOGICAL"
    COMBINATION_PRODUCT = "COMBINATION_PRODUCT"
    DEVICE = "DEVICE"
    DIAGNOSTIC_TEST = "DIAGNOSTIC_TEST"
    DIETARY_SUPPLEMENT = "DIETARY_SUPPLEMENT"
    DRUG = "DRUG"
    GENETIC = "GENETIC"
    PROCEDURE = "PROCEDURE"
    RADIATION = "RADIATION"
    OTHER = "OTHER"


class SponsorClass(StrEnum):
    """ClinicalTrials.gov `AgencyClass`."""

    NIH = "NIH"
    FED = "FED"
    OTHER_GOV = "OTHER_GOV"
    INDIV = "INDIV"
    INDUSTRY = "INDUSTRY"
    NETWORK = "NETWORK"
    AMBIG = "AMBIG"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


_PARTIAL_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


@dataclass(frozen=True)
class PartialDate:
    """A date as registered: "2019", "2019-03" or "2019-03-27"."""

    year: int
    month: int | None = None
    day: int | None = None

    @classmethod
    def parse(cls, raw: str) -> PartialDate:
        match = _PARTIAL_DATE.match(raw.strip())
        if not match:
            raise ValueError(f"not a partial date: {raw!r}")
        year, month, day = match.groups()
        return cls(int(year), int(month) if month else None, int(day) if day else None)

    def __str__(self) -> str:
        """The registered form, e.g. "2021-05"."""
        parts = [f"{self.year:04d}"]
        if self.month is not None:
            parts.append(f"{self.month:02d}")
            if self.day is not None:
                parts.append(f"{self.day:02d}")
        return "-".join(parts)


@dataclass(frozen=True)
class Intervention:
    name: str
    type: InterventionType | None
    other_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sponsor:
    name: str
    sponsor_class: SponsorClass | None


@dataclass(frozen=True)
class Site:
    """A trial location, identified by facility name, city and country."""

    facility: str
    city: str | None
    country: str | None


@dataclass(frozen=True)
class Trial:
    """A registered study, named after the user's vocabulary ("trials").

    ClinicalTrials.gov calls these "studies" and also registers observational and
    expanded-access studies, which are not trials in the strict sense; `study_type`
    tells them apart.
    """

    nct_id: str
    title: str
    status: Status | None
    study_type: StudyType | None
    phases: tuple[Phase, ...]
    start_date: PartialDate | None
    completion_date: PartialDate | None
    enrollment: int | None
    conditions: tuple[str, ...]
    interventions: tuple[Intervention, ...]
    lead_sponsor: Sponsor | None
    collaborators: tuple[Sponsor, ...]
    countries: tuple[str, ...]
    """Distinct location countries, in registry order."""
    investigators: tuple[str, ...]
    """Names of the trial's overall officials who are identifiable people."""
    sites: tuple[Site, ...]
    """Distinct identifiable locations; empty unless the source was asked for sites."""
