from cheiron.adapters.outbound.ctgov.mapper import to_texts, to_trial
from cheiron.domain.trial import (
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
)
from tests.conftest import load_fixture


def _recorded_study(nct_id: str) -> dict:
    for page in ("pembrolizumab_page1.json", "pembrolizumab_page2.json"):
        for study in load_fixture(f"ctgov/{page}")["studies"]:
            if study["protocolSection"]["identificationModule"]["nctId"] == nct_id:
                return study
    raise KeyError(nct_id)


def test_maps_recorded_study() -> None:
    trial = to_trial(_recorded_study("NCT03044730"))

    assert trial.nct_id == "NCT03044730"
    assert trial.title.startswith("Pembrolizumab and Capecitabine")
    assert trial.status is Status.UNKNOWN
    assert trial.study_type is StudyType.INTERVENTIONAL
    assert trial.phases == (Phase.PHASE2,)
    assert trial.start_date == PartialDate(2017, 5, 25)
    assert trial.completion_date == PartialDate(2021, 5)
    assert trial.enrollment == 30
    assert "Triple-Negative Breast Carcinoma" in trial.conditions
    assert trial.interventions[2] == Intervention(
        name="Pembrolizumab",
        type=InterventionType.BIOLOGICAL,
        other_names=("Keytruda", "Lambrolizumab", "MK-3475", "SCH 900475"),
    )
    assert trial.lead_sponsor == Sponsor("Northwestern University", SponsorClass.OTHER)
    assert trial.collaborators == (
        Sponsor("Merck Sharp & Dohme LLC", SponsorClass.INDUSTRY),
        Sponsor("National Cancer Institute (NCI)", SponsorClass.NIH),
    )


def test_countries_are_distinct_in_registry_order() -> None:
    trial = to_trial(_recorded_study("NCT06558799"))

    assert trial.countries == ("Austria", "Czechia", "France", "Italy", "Netherlands", "Poland", "Spain")


def test_tolerates_study_with_only_an_id() -> None:
    trial = to_trial({"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}})

    assert trial.nct_id == "NCT00000001"
    assert trial.title == ""
    assert trial.status is None
    assert trial.phases == ()
    assert trial.start_date is None
    assert trial.enrollment is None
    assert trial.interventions == ()
    assert trial.lead_sponsor is None
    assert trial.countries == ()


def test_drops_values_outside_known_vocabulary() -> None:
    trial = to_trial(
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT00000002"},
                "statusModule": {"overallStatus": "SOME_NEW_STATUS", "startDateStruct": {"date": "TBD"}},
                "designModule": {"phases": ["PHASE2", "PHASE9"]},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Acme", "class": "ALIEN"}},
                "armsInterventionsModule": {"interventions": [{"type": "DRUG"}, {"name": "X", "type": "NEW"}]},
            }
        }
    )

    assert trial.status is None
    assert trial.start_date is None
    assert trial.phases == (Phase.PHASE2,)
    assert trial.lead_sponsor == Sponsor("Acme", None)
    assert trial.interventions == (Intervention("X", None),)


def _with_contacts(officials: list[dict], locations: list[dict], lead: str = "Boehringer Ingelheim") -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000003"},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": lead, "class": "INDUSTRY"}},
            "contactsLocationsModule": {"overallOfficials": officials, "locations": locations},
        }
    }


def test_investigators_keep_people_and_drop_placeholders() -> None:
    # Placeholder names below are taken from real records.
    officials = [
        {"name": "Tim Heise, MD", "role": "PRINCIPAL_INVESTIGATOR"},
        {"name": "王伟", "role": "PRINCIPAL_INVESTIGATOR"},
        {"name": "Medical Director", "role": "STUDY_DIRECTOR"},
        {"name": "Pfizer CT.gov Call Center", "role": "STUDY_DIRECTOR"},
        {"name": "GSK Clinical Trials", "role": "STUDY_DIRECTOR"},
        {"name": "Call 1-877-CTLILLY (1-877-285-4559)", "role": "STUDY_DIRECTOR"},
        {"name": "MD", "role": "PRINCIPAL_INVESTIGATOR"},
        {"name": "Boehringer Ingelheim", "role": "PRINCIPAL_INVESTIGATOR"},
        {"name": "Tim Heise, MD", "role": "STUDY_CHAIR"},
        {"name": "Teva Medical Expert, MD", "role": "STUDY_DIRECTOR"},
        {"name": "Sponsor's Medical Expert", "role": "STUDY_DIRECTOR"},
        {"name": "Medical Monitor", "role": "STUDY_DIRECTOR"},
        {"name": "Clinical Sciences & Operations", "role": "STUDY_DIRECTOR"},
        {"name": "Global Clinical Leader", "role": "STUDY_DIRECTOR"},
        {"name": "Duramed Protocol Chair", "role": "STUDY_CHAIR"},
        {"name": "ICD CSD", "role": "STUDY_DIRECTOR"},
        {"name": "ABBVIE INC.", "role": "STUDY_DIRECTOR"},
        {"name": "Boehringer Ingelheim Boehringer Ingelheim", "role": "STUDY_DIRECTOR"},
    ]

    assert to_trial(_with_contacts(officials, [])).investigators == ("Tim Heise, MD", "王伟")


def test_an_individual_sponsor_can_be_the_investigator() -> None:
    study = _with_contacts([{"name": "Yaron Ilan, MD", "role": "PRINCIPAL_INVESTIGATOR"}], [], lead="Yaron Ilan, MD")
    study["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"]["class"] = "INDIV"

    assert to_trial(study).investigators == ("Yaron Ilan, MD",)


def test_sites_are_distinct_by_facility_city_and_country_without_placeholders() -> None:
    locations = [
        {"facility": "Memorial Sloan Kettering Cancer Center", "city": "New York", "country": "United States"},
        {"facility": "memorial sloan kettering cancer center", "city": "New York", "country": "United States"},
        {"facility": "University Hospital", "city": "Basel", "country": "Switzerland"},
        {"facility": "University Hospital", "city": "Zurich", "country": "Switzerland"},
        {"facility": "Research Site", "city": "Seoul", "country": "South Korea"},
        {"facility": "GSK Investigational Site", "city": "Lyon", "country": "France"},
        {"facility": "Chiesi Clinical Trial Site", "city": "Parma", "country": "Italy"},
        {"facility": "Local Institution - 0123", "city": "Tokyo", "country": "Japan"},
        {
            "facility": "For additional information regarding investigative sites for this trial, "
            "contact 1-877-CTLILLY (1-877-285-4559)",
            "country": "United States",
        },
        {"city": "Paris", "country": "France"},
    ]

    trial = to_trial(_with_contacts([], locations))

    assert trial.sites == (
        Site("Memorial Sloan Kettering Cancer Center", "New York", "United States"),
        Site("University Hospital", "Basel", "Switzerland"),
        Site("University Hospital", "Zurich", "Switzerland"),
    )
    assert trial.countries[:3] == ("United States", "Switzerland", "South Korea")


def test_free_text_is_kept_by_field_path_without_empty_fields() -> None:
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT1", "briefTitle": "Short", "officialTitle": ""},
            "armsInterventionsModule": {"armGroups": [{"description": "Arm A gets pembrolizumab."}, {}]},
            "eligibilityModule": {"eligibilityCriteria": "* Adults"},
        }
    }

    assert to_texts(study) == (
        "NCT1",
        {
            "protocolSection.identificationModule.briefTitle": ("Short",),
            "protocolSection.armsInterventionsModule.armGroups.description": ("Arm A gets pembrolizumab.",),
            "protocolSection.eligibilityModule.eligibilityCriteria": ("* Adults",),
        },
    )


def test_date_types_say_whether_a_date_has_happened() -> None:
    status = {"startDateStruct": {"date": "2027-01", "type": "ESTIMATED"}, "completionDateStruct": {"date": "2030-12", "type": "SOON"}}

    mapped = to_trial({"protocolSection": {"identificationModule": {"nctId": "NCT1"}, "statusModule": status}})

    assert (mapped.start_date_type, mapped.completion_date_type) == (DateType.ESTIMATED, None)  # unknown types dropped
