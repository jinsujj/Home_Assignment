from cheiron.adapters.outbound.ctgov.mapper import to_trial
from cheiron.domain.trial import (
    Intervention,
    InterventionType,
    PartialDate,
    Phase,
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
