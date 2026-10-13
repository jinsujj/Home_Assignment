import pytest

from cheiron.domain.analysis import Dimension, Entity, Measure
from cheiron.domain.facets import (
    COLLABORATOR_NAME,
    COMPLETION_DATE,
    INTERVENTION_NAME,
    LEAD_SPONSOR_NAME,
    PHASES,
    START_DATE,
    dimension_facets,
    entity_facets,
    label,
    measure_value,
    person_key,
)
from cheiron.domain.trial import InterventionType, Phase, Site, Sponsor, SponsorClass
from cheiron.domain.visualization import Evidence
from tests.domain.factories import drug, sponsor, trial


def test_multi_valued_dimension_yields_each_value_with_registry_evidence() -> None:
    facets = dimension_facets(trial("NCT1", phases=(Phase.PHASE1, Phase.PHASE2)), Dimension.PHASE)

    assert [(f.key, f.label, f.evidence) for f in facets] == [
        (Phase.PHASE1, "Phase 1", Evidence(PHASES, "PHASE1")),
        (Phase.PHASE2, "Phase 2", Evidence(PHASES, "PHASE2")),
    ]


def test_free_text_values_are_grouped_ignoring_case_and_spacing() -> None:
    t = trial("NCT1", interventions=(drug("Pembrolizumab"), drug(" pembrolizumab"), drug("Cis  platin")))

    facets = dimension_facets(t, Dimension.INTERVENTION)

    assert [(f.key, f.label) for f in facets] == [("pembrolizumab", "Pembrolizumab"), ("cis platin", "Cis  platin")]
    assert facets[0].evidence == Evidence(INTERVENTION_NAME, "Pembrolizumab")


def test_start_year_is_keyed_by_year_and_cites_the_registered_date() -> None:
    [facet] = dimension_facets(trial("NCT1", start_date="2019-03"), Dimension.START_YEAR)

    assert (facet.key, facet.label, facet.evidence) == (2019, "2019", Evidence(START_DATE, "2019-03"))


def test_missing_values_yield_no_facets() -> None:
    empty = trial("NCT1")
    for dimension in Dimension:
        assert dimension_facets(empty, dimension) == []


def test_drugs_exclude_placebos_and_non_drug_interventions() -> None:
    t = trial(
        "NCT1",
        interventions=(
            drug("Pembrolizumab", InterventionType.BIOLOGICAL),
            drug("Capecitabine"),
            drug("Matching Placebo"),
            drug("Laboratory Biomarker Analysis", InterventionType.OTHER),
            drug("Radiotherapy", InterventionType.RADIATION),
        ),
    )

    assert [f.label for f in entity_facets(t, Entity.DRUG)] == ["Pembrolizumab", "Capecitabine"]


def test_sponsors_include_collaborators_once() -> None:
    t = trial(
        "NCT1",
        lead_sponsor=sponsor("Northwestern University", SponsorClass.OTHER),
        collaborators=(sponsor("Merck Sharp & Dohme LLC"), sponsor("NORTHWESTERN UNIVERSITY")),
    )

    facets = entity_facets(t, Entity.SPONSOR)

    assert [(f.label, f.evidence.field) for f in facets] == [
        ("Northwestern University", LEAD_SPONSOR_NAME),
        ("Merck Sharp & Dohme LLC", COLLABORATOR_NAME),
    ]


def test_lead_sponsor_class_dimension_ignores_collaborators() -> None:
    t = trial("NCT1", lead_sponsor=Sponsor("NCI", SponsorClass.NIH), collaborators=(sponsor("Merck"),))

    assert [f.label for f in dimension_facets(t, Dimension.LEAD_SPONSOR_CLASS)] == ["NIH"]


def test_duration_is_months_between_registered_dates() -> None:
    value = measure_value(trial("NCT1", start_date="2019-03-27", completion_date="2021-05"), Measure.DURATION_MONTHS)

    assert value == (26, (Evidence(START_DATE, "2019-03-27"), Evidence(COMPLETION_DATE, "2021-05")))


@pytest.mark.parametrize(
    ("start", "end"),
    [(None, "2021-05"), ("2019", "2021-05"), ("2021-06", "2021-05")],
    ids=["missing start", "year-only precision", "completion before start"],
)
def test_duration_is_undefined_without_month_precision_or_with_inverted_dates(start, end) -> None:
    assert measure_value(trial("NCT1", start_date=start, completion_date=end), Measure.DURATION_MONTHS) is None


def test_enrollment_cites_the_registered_count() -> None:
    assert measure_value(trial("NCT1", enrollment=30), Measure.ENROLLMENT) == (
        30,
        (Evidence("protocolSection.designModule.enrollmentInfo.count", "30"),),
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("PHASE1", "Phase 1"),
        ("NA", "Not applicable"),
        ("ACTIVE_NOT_RECRUITING", "Active not recruiting"),
        ("OTHER_GOV", "Other government"),
        ("INDUSTRY", "Industry"),
        ("NIH", "NIH"),
    ],
)
def test_labels_for_registry_codes(code: str, expected: str) -> None:
    assert label(code) == expected


def test_investigators_are_network_nodes_cited_by_official_name() -> None:
    [facet] = entity_facets(trial("NCT1", investigators=("Tim Heise, MD",)), Entity.INVESTIGATOR)

    assert (facet.key, facet.label) == ("tim heise", "Tim Heise, MD")
    assert facet.evidence == Evidence("protocolSection.contactsLocationsModule.overallOfficials.name", "Tim Heise, MD")


def test_sites_with_the_same_facility_name_in_different_cities_are_different_nodes() -> None:
    t = trial("NCT1", sites=(Site("University Hospital", "Basel", "Switzerland"), Site("University Hospital", "Zurich", "Switzerland")))

    facets = entity_facets(t, Entity.SITE)

    assert [(f.key, f.label) for f in facets] == [
        ("university hospital|basel|switzerland", "University Hospital, Basel"),
        ("university hospital|zurich|switzerland", "University Hospital, Zurich"),
    ]
    assert facets[0].evidence == Evidence("protocolSection.contactsLocationsModule.locations.facility", "University Hospital")


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Benoit Girard, MD", "benoit girard"),
        ("Benoit Girard, M.D.", "benoit girard"),
        ("James D. Carlson, Pharm. D.", "james d carlson"),
        ("James D Carlson, Pharm.D.", "james d carlson"),
        ("David Price, Prof. MD", "david price"),
        ("Wei Ma", "wei ma"),
        ("Smith, John", "smith john"),
    ],
)
def test_person_key_ignores_credential_spellings(name: str, key: str) -> None:
    assert person_key(name) == key
