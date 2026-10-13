"""Anti-corruption layer: ClinicalTrials.gov study JSON -> domain Trial.

Real records are sparse and occasionally hold values newer than our enums, so every
field is optional here and unknown enum values are dropped instead of failing the study.
Officials and facilities registered under placeholders ("Medical Director", "Research
Site", hotline texts) are dropped too: they name nobody and nowhere in particular.
"""

import re
from enum import StrEnum
from typing import Any

from cheiron.domain.facets import (
    ARM_GROUP_DESCRIPTION,
    BRIEF_SUMMARY,
    BRIEF_TITLE,
    CREDENTIALS,
    DETAILED_DESCRIPTION,
    ELIGIBILITY_CRITERIA,
    INTERVENTION_DESCRIPTION,
    KEYWORDS,
    OFFICIAL_TITLE,
)
from cheiron.domain.trial import (
    Arm,
    DateType,
    Intervention,
    InterventionType,
    PartialDate,
    Phase,
    Site,
    Sponsor,
    SponsorClass,
    Status,
    StudyType,
    Trial,
)

# Free text for citing mentions (to_texts); a few KB per trial, so fetched only for cited trials.
TEXT_FIELDS = (
    "NCTId",
    "BriefTitle",
    "OfficialTitle",
    "BriefSummary",
    "DetailedDescription",
    "ArmGroupDescription",
    "InterventionDescription",
    "Keyword",
    "EligibilityCriteria",
)

# Piece names requested via the `fields` parameter; keep in sync with to_trial().
FIELDS = (
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "StudyType",
    "Phase",
    "StartDate",
    "StartDateType",
    "CompletionDate",
    "CompletionDateType",
    "EnrollmentCount",
    "Condition",
    "InterventionType",
    "InterventionName",
    "InterventionOtherName",
    "ArmGroupLabel",
    "ArmGroupInterventionName",
    "LeadSponsorName",
    "LeadSponsorClass",
    "CollaboratorName",
    "CollaboratorClass",
    "LocationCountry",
    "OverallOfficialName",
)
# Facility and city of every location roughly double the payload, so they are opt-in.
SITE_FIELDS = ("LocationFacility", "LocationCity")

# Official names that are roles, departments or companies, all seen repeatedly in real records:
# "Medical Director", "Teva Medical Expert, MD", "Sponsor's Medical Expert", "Medical Monitor",
# "Clinical Sciences & Operations", "Global Clinical Leader", "Duramed Protocol Chair", "ICD CSD",
# "Pfizer CT.gov Call Center", "GSK Clinical Trials", "ABBVIE INC.", "Call 1-877-CTLILLY ...".
_PLACEHOLDER_PERSON = re.compile(
    r"director|medical (?:expert|monitor)|sponsor|call cent(?:er|re)|clinical (?:trials?|sciences|project)\b"
    r"|leader\b|protocol chair|operations|ct\.gov|\bicd\b|\b(?:inc|llc|ltd|gmbh|corp|plc)\b|\d{3}",
    re.IGNORECASE,
)
# Seen in real records: "Research Site", "GSK Investigational Site", "Novartis Investigative Site",
# "Chiesi Clinical Trial Site", "Local Institution", "For additional information regarding
# investigative sites for this trial, contact 1-877-CTLILLY ...".
_PLACEHOLDER_SITE = re.compile(
    r"\b(?:investigational|investigative|investigator|clinical(?: trial| study)?|study|research)\s+sites?\b"
    r"|^local institution\b|^for additional information|\d{3}\)?[-\s]\d{3}",
    re.IGNORECASE,
)


def to_texts(study: dict[str, Any]) -> tuple[str, dict[str, tuple[str, ...]]]:
    """NCT ID and the study's free text by field path (see TEXT_FIELDS); empty fields left out."""
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    description = protocol.get("descriptionModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    texts = {
        BRIEF_TITLE: (identification.get("briefTitle"),),
        OFFICIAL_TITLE: (identification.get("officialTitle"),),
        BRIEF_SUMMARY: (description.get("briefSummary"),),
        DETAILED_DESCRIPTION: (description.get("detailedDescription"),),
        ARM_GROUP_DESCRIPTION: tuple(a.get("description") for a in arms.get("armGroups", [])),
        INTERVENTION_DESCRIPTION: tuple(i.get("description") for i in arms.get("interventions", [])),
        KEYWORDS: tuple(protocol.get("conditionsModule", {}).get("keywords", [])),
        ELIGIBILITY_CRITERIA: (protocol.get("eligibilityModule", {}).get("eligibilityCriteria"),),
    }
    present = {field: tuple(t for t in values if t) for field, values in texts.items()}
    return identification.get("nctId", ""), {field: values for field, values in present.items() if values}


def to_trial(study: dict[str, Any]) -> Trial:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    sponsors = protocol.get("sponsorCollaboratorsModule", {})
    contacts = protocol.get("contactsLocationsModule", {})
    locations = contacts.get("locations", [])

    lead_sponsor = _sponsor(sponsors.get("leadSponsor"))
    collaborators = tuple(s for s in (_sponsor(raw) for raw in sponsors.get("collaborators", [])) if s)

    return Trial(
        nct_id=identification["nctId"],
        title=identification.get("briefTitle", ""),
        status=_enum(Status, status.get("overallStatus")),
        study_type=_enum(StudyType, design.get("studyType")),
        phases=tuple(p for p in (_enum(Phase, raw) for raw in design.get("phases", [])) if p),
        start_date=_date(status.get("startDateStruct")),
        completion_date=_date(status.get("completionDateStruct")),
        start_date_type=_enum(DateType, (status.get("startDateStruct") or {}).get("type")),
        completion_date_type=_enum(DateType, (status.get("completionDateStruct") or {}).get("type")),
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
        lead_sponsor=lead_sponsor,
        collaborators=collaborators,
        arms=tuple(
            Arm(label=arm["label"], intervention_names=tuple(arm.get("interventionNames", [])))
            for arm in protocol.get("armsInterventionsModule", {}).get("armGroups", [])
            if arm.get("label")
        ),
        countries=tuple(dict.fromkeys(loc["country"] for loc in locations if loc.get("country"))),
        investigators=_investigators(
            contacts.get("overallOfficials", []),
            # An individual sponsor is often also the investigator, so only organisations count.
            [s.name for s in (lead_sponsor, *collaborators) if s and s.sponsor_class is not SponsorClass.INDIV],
        ),
        sites=_sites(locations),
    )


def _investigators(officials: list[dict[str, Any]], organisations: list[str]) -> tuple[str, ...]:
    """Names of officials who are identifiable people, e.g. not "Medical Director" or the sponsor."""
    sponsors = [_fold(name) for name in organisations if len(name) >= 4]
    names = (o["name"].strip() for o in officials if o.get("name"))
    return tuple(
        dict.fromkeys(
            name
            for name in names
            if not _PLACEHOLDER_PERSON.search(name)
            and not any(sponsor in _fold(name) for sponsor in sponsors)  # also "AstraZeneca AstraZeneca"
            and not {w.casefold() for w in re.findall(r"[^\W\d_]+", name)} <= CREDENTIALS  # e.g. "MD"
        )
    )


def _sites(locations: list[dict[str, Any]]) -> tuple[Site, ...]:
    sites: dict[tuple[str, str, str], Site] = {}
    for loc in locations:
        facility = (loc.get("facility") or "").strip()
        if not facility or _PLACEHOLDER_SITE.search(facility):
            continue
        site = Site(facility, loc.get("city"), loc.get("country"))
        sites.setdefault((_fold(facility), _fold(site.city or ""), _fold(site.country or "")), site)
    return tuple(sites.values())


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


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
