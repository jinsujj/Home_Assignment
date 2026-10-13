"""Anti-corruption layer: ClinicalTrials.gov study JSON -> domain Trial.

Real records are sparse and occasionally hold values newer than our enums, so every
field is optional here and unknown enum values are dropped instead of failing the study.
"""

from enum import StrEnum
from typing import Any

from cheiron.domain.trial import (
    Intervention,
    InterventionType,
    PartialDate,
    Phase,
    Sponsor,
    SponsorClass,
    Status,
    StudyType,
    Trial,
)

# Piece names requested via the `fields` parameter; keep in sync with to_trial().
FIELDS = (
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "StudyType",
    "Phase",
    "StartDate",
    "CompletionDate",
    "EnrollmentCount",
    "Condition",
    "InterventionType",
    "InterventionName",
    "InterventionOtherName",
    "LeadSponsorName",
    "LeadSponsorClass",
    "CollaboratorName",
    "CollaboratorClass",
    "LocationCountry",
)


def to_trial(study: dict[str, Any]) -> Trial:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    sponsors = protocol.get("sponsorCollaboratorsModule", {})

    return Trial(
        nct_id=identification["nctId"],
        title=identification.get("briefTitle", ""),
        status=_enum(Status, status.get("overallStatus")),
        study_type=_enum(StudyType, design.get("studyType")),
        phases=tuple(p for p in (_enum(Phase, raw) for raw in design.get("phases", [])) if p),
        start_date=_date(status.get("startDateStruct")),
        completion_date=_date(status.get("completionDateStruct")),
        enrollment=design.get("enrollmentInfo", {}).get("count"),
        conditions=tuple(protocol.get("conditionsModule", {}).get("conditions", [])),
        interventions=tuple(
            Intervention(
                name=item["name"],
                type=_enum(InterventionType, item.get("type")),
                other_names=tuple(item.get("otherNames", [])),
            )
            for item in protocol.get("armsInterventionsModule", {}).get("interventions", [])
            if item.get("name")
        ),
        lead_sponsor=_sponsor(sponsors.get("leadSponsor")),
        collaborators=tuple(
            s for s in (_sponsor(raw) for raw in sponsors.get("collaborators", [])) if s
        ),
        countries=tuple(
            dict.fromkeys(
                loc["country"]
                for loc in protocol.get("contactsLocationsModule", {}).get("locations", [])
                if loc.get("country")
            )
        ),
    )


def _enum[E: StrEnum](enum: type[E], raw: str | None) -> E | None:
    try:
        return enum(raw) if raw else None
    except ValueError:
        return None


def _date(struct: dict[str, Any] | None) -> PartialDate | None:
    try:
        return PartialDate.parse(struct["date"]) if struct and struct.get("date") else None
    except ValueError:
        return None


def _sponsor(raw: dict[str, Any] | None) -> Sponsor | None:
    if not raw or not raw.get("name"):
        return None
    return Sponsor(name=raw["name"], sponsor_class=_enum(SponsorClass, raw.get("class")))
