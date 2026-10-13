"""What a trial contributes to an analysis: its values along a dimension, entity or measure.

Every value comes with the Evidence that justifies it: the ClinicalTrials.gov field it
was read from and the value as registered. Field paths below are part of the citation
contract, so they name the API's JSON paths rather than our attribute names.
"""

from dataclasses import dataclass

from cheiron.domain.analysis import Dimension, Entity, Measure
from cheiron.domain.trial import InterventionType, Phase, Trial
from cheiron.domain.visualization import Evidence

PHASES = "protocolSection.designModule.phases"
OVERALL_STATUS = "protocolSection.statusModule.overallStatus"
STUDY_TYPE = "protocolSection.designModule.studyType"
START_DATE = "protocolSection.statusModule.startDateStruct.date"
START_DATE_TYPE = "protocolSection.statusModule.startDateStruct.type"
COMPLETION_DATE = "protocolSection.statusModule.completionDateStruct.date"
COMPLETION_DATE_TYPE = "protocolSection.statusModule.completionDateStruct.type"
ENROLLMENT = "protocolSection.designModule.enrollmentInfo.count"
CONDITIONS = "protocolSection.conditionsModule.conditions"
INTERVENTION_NAME = "protocolSection.armsInterventionsModule.interventions.name"
INTERVENTION_OTHER_NAME = "protocolSection.armsInterventionsModule.interventions.otherNames"
INTERVENTION_TYPE = "protocolSection.armsInterventionsModule.interventions.type"
LEAD_SPONSOR_NAME = "protocolSection.sponsorCollaboratorsModule.leadSponsor.name"
LEAD_SPONSOR_CLASS = "protocolSection.sponsorCollaboratorsModule.leadSponsor.class"
COLLABORATOR_NAME = "protocolSection.sponsorCollaboratorsModule.collaborators.name"
LOCATION_COUNTRY = "protocolSection.contactsLocationsModule.locations.country"
LOCATION_FACILITY = "protocolSection.contactsLocationsModule.locations.facility"
OVERALL_OFFICIAL_NAME = "protocolSection.contactsLocationsModule.overallOfficials.name"
# Free text, fetched only for cited trials (domain.membership)
BRIEF_TITLE = "protocolSection.identificationModule.briefTitle"
OFFICIAL_TITLE = "protocolSection.identificationModule.officialTitle"
BRIEF_SUMMARY = "protocolSection.descriptionModule.briefSummary"
DETAILED_DESCRIPTION = "protocolSection.descriptionModule.detailedDescription"
ARM_GROUP_DESCRIPTION = "protocolSection.armsInterventionsModule.armGroups.description"
INTERVENTION_DESCRIPTION = "protocolSection.armsInterventionsModule.interventions.description"
KEYWORDS = "protocolSection.conditionsModule.keywords"
ELIGIBILITY_CRITERIA = "protocolSection.eligibilityModule.eligibilityCriteria"

DRUG_TYPES = frozenset({InterventionType.DRUG, InterventionType.BIOLOGICAL})

PHASE_ORDER = (Phase.EARLY_PHASE1, Phase.PHASE1, Phase.PHASE2, Phase.PHASE3, Phase.PHASE4, Phase.NA)
_LABELS = {
    Phase.EARLY_PHASE1: "Early Phase 1",
    Phase.PHASE1: "Phase 1",
    Phase.PHASE2: "Phase 2",
    Phase.PHASE3: "Phase 3",
    Phase.PHASE4: "Phase 4",
    Phase.NA: "Not applicable",
    "NIH": "NIH",
    "FED": "Federal",
    "OTHER_GOV": "Other government",
    "INDIV": "Individual",
    "AMBIG": "Ambiguous",
}

CREDENTIALS = frozenset(
    {"md", "phd", "mph", "msc", "ms", "bsc", "rn", "pharmd", "pharm", "d", "mba", "mbbs", "frcp", "facp", "prof", "dr"}
)

MULTI_VALUED = frozenset(
    {Dimension.PHASE, Dimension.COUNTRY, Dimension.CONDITION, Dimension.INTERVENTION, Dimension.INTERVENTION_TYPE}
)


@dataclass(frozen=True)
class Facet:
    key: str | int
    """Grouping key: case- and whitespace-insensitive for free text."""
    label: str
    evidence: Evidence
    context: tuple[Evidence, ...] = ()
    """More of the record that qualifies the value, e.g. whether a start date is ESTIMATED."""

    @property
    def evidences(self) -> tuple[Evidence, ...]:
        return (self.evidence, *self.context)


def dimension_facets(trial: Trial, dimension: Dimension) -> list[Facet]:
    """Distinct values of `dimension` for this trial (a trial counts once per value)."""
    match dimension:
        case Dimension.PHASE:
            facets = [_coded(p, PHASES) for p in trial.phases]
        case Dimension.STATUS:
            facets = [_coded(trial.status, OVERALL_STATUS)] if trial.status else []
        case Dimension.STUDY_TYPE:
            facets = [_coded(trial.study_type, STUDY_TYPE)] if trial.study_type else []
        case Dimension.START_YEAR:
            start = trial.start_date
            facets = []
            if start:
                facets = [Facet(start.year, str(start.year), Evidence(START_DATE, str(start)), _start_type(trial))]
        case Dimension.COUNTRY:
            facets = entity_facets(trial, Entity.COUNTRY)
        case Dimension.CONDITION:
            facets = entity_facets(trial, Entity.CONDITION)
        case Dimension.INTERVENTION:
            facets = [_text(i.name, INTERVENTION_NAME) for i in trial.interventions]
        case Dimension.INTERVENTION_TYPE:
            facets = [_coded(i.type, INTERVENTION_TYPE) for i in trial.interventions if i.type]
        case Dimension.LEAD_SPONSOR:
            lead = trial.lead_sponsor
            facets = [_text(lead.name, LEAD_SPONSOR_NAME)] if lead else []
        case Dimension.LEAD_SPONSOR_CLASS:
            lead = trial.lead_sponsor
            facets = [_coded(lead.sponsor_class, LEAD_SPONSOR_CLASS)] if lead and lead.sponsor_class else []
    return _distinct(facets)


def entity_facets(trial: Trial, entity: Entity) -> list[Facet]:
    """Distinct network nodes of kind `entity` registered on this trial."""
    match entity:
        case Entity.DRUG:
            facets = [
                _text(i.name, INTERVENTION_NAME)
                for i in trial.interventions
                if i.type in DRUG_TYPES and not is_placebo(i.name)
            ]
        case Entity.SPONSOR:
            sponsors = [trial.lead_sponsor] if trial.lead_sponsor else []
            facets = [_text(s.name, LEAD_SPONSOR_NAME) for s in sponsors]
            facets += [_text(s.name, COLLABORATOR_NAME) for s in trial.collaborators]
        case Entity.CONDITION:
            facets = [_text(c, CONDITIONS) for c in trial.conditions]
        case Entity.COUNTRY:
            facets = [_text(c, LOCATION_COUNTRY) for c in trial.countries]
        case Entity.INVESTIGATOR:
            facets = [
                Facet(person_key(name), name.strip(), Evidence(OVERALL_OFFICIAL_NAME, name))
                for name in trial.investigators
            ]
        case Entity.SITE:
            # The same facility name in another city is another site.
            facets = [
                Facet(
                    "|".join(normalize(part or "") for part in (s.facility, s.city, s.country)),
                    ", ".join(part for part in (s.facility.strip(), s.city) if part),
                    Evidence(LOCATION_FACILITY, s.facility),
                )
                for s in trial.sites
            ]
    return _distinct(facets)


def measure_value(trial: Trial, measure: Measure) -> tuple[float, tuple[Evidence, ...]] | None:
    """The trial's value for `measure`, or None when it is not registered or not computable."""
    match measure:
        case Measure.ENROLLMENT:
            if trial.enrollment is None:
                return None
            return trial.enrollment, (Evidence(ENROLLMENT, str(trial.enrollment)),)
        case Measure.START_YEAR:
            if trial.start_date is None:
                return None
            return trial.start_date.year, (Evidence(START_DATE, str(trial.start_date)), *_start_type(trial))
        case Measure.DURATION_MONTHS:
            start, end = trial.start_date, trial.completion_date
            if start is None or end is None or start.month is None or end.month is None:
                return None
            months = (end.year - start.year) * 12 + (end.month - start.month)
            if months < 0:
                return None
            completion = (Evidence(COMPLETION_DATE, str(end)),)
            if trial.completion_date_type:
                completion += (Evidence(COMPLETION_DATE_TYPE, trial.completion_date_type),)
            return months, (Evidence(START_DATE, str(start)), *_start_type(trial), *completion)


def _start_type(trial: Trial) -> tuple[Evidence, ...]:
    return (Evidence(START_DATE_TYPE, trial.start_date_type),) if trial.start_date_type else ()


def label(code: str) -> str:
    """Display text for a registry enum value, e.g. ACTIVE_NOT_RECRUITING -> "Active not recruiting"."""
    return _LABELS.get(code) or code.replace("_", " ").capitalize()


def is_placebo(name: str) -> bool:
    return "placebo" in name.casefold()


def normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def person_key(name: str) -> str:
    """One key per person across credential spellings: "Benoit Girard, M.D." -> "benoit girard".

    Only words after the first comma are treated as credentials, so surnames such as
    "Do" or "Ma" survive.
    """
    head, *tail = name.replace(".", "").split(",")
    rest = [w for w in " ".join(tail).split() if w.casefold() not in CREDENTIALS]
    return normalize(" ".join([head, *rest]))


def _coded(code: str, field: str) -> Facet:
    return Facet(code, label(code), Evidence(field, code))


def _text(text: str, field: str) -> Facet:
    return Facet(normalize(text), text.strip(), Evidence(field, text))


def _distinct(facets: list[Facet]) -> list[Facet]:
    """First facet per key, in registry order."""
    first: dict[str | int, Facet] = {}
    for facet in facets:
        first.setdefault(facet.key, facet)
    return list(first.values())
