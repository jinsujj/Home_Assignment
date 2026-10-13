"""Fixtures are real API responses for KEYNOTE-189; adverse event lists are cut to their first
entries (4 serious, 2 other) to keep the file small."""

import pytest

from cheiron.adapters.outbound.ctgov.results_mapper import name_variants, to_candidate, to_results
from cheiron.domain.results import Comparison, GroupValue, OutcomeType
from tests.conftest import load_fixture

PEMBRO_ARM = "Pembrolizumab+Pemetrexed+Platinum Chemotherapy Followed by Pembrolizumab+Pemetrexed"


def test_maps_posted_outcomes_with_intervals_and_analyses() -> None:
    results = to_results(load_fixture("ctgov/keynote189_results.json"))

    assert results.nct_id == "NCT02578680"
    pfs = results.outcomes[0]
    assert pfs.type is OutcomeType.PRIMARY
    assert pfs.title.startswith("Progression-Free Survival (PFS)")
    assert (pfs.measure, pfs.unit, pfs.dispersion) == ("MEDIAN", "Months", "95% Confidence Interval")
    assert pfs.values == (GroupValue(PEMBRO_ARM, "8.8", "7.6", "9.2"), GroupValue("Control", "4.9", "4.7", "5.5"))
    assert pfs.comparisons == (
        Comparison((PEMBRO_ARM, "Control"), "Hazard Ratio (HR)", "0.52", "95", "0.43", "0.64", "<0.00001"),
    )


def test_not_reached_medians_keep_the_posted_text() -> None:
    overall_survival = to_results(load_fixture("ctgov/keynote189_results.json")).outcomes[1]

    [pembro, control] = overall_survival.values
    assert (pembro.raw, pembro.value, pembro.interval) == ("NA", None, (None, None))
    assert (control.value, control.interval) == (11.3, (8.7, 15.1))


def test_maps_adverse_events_per_group_with_unique_group_titles() -> None:
    events = to_results(load_fixture("ctgov/keynote189_results.json")).adverse_events

    anaemia = [e for e in events if e.term == "Anaemia" and e.serious]
    assert (anaemia[0].group, anaemia[0].affected, anaemia[0].at_risk) == (PEMBRO_ARM, 13, 405)
    assert len({e.group for e in events}) == 5
    assert {e.serious for e in events} == {True, False}


def test_duplicate_group_titles_get_their_ids() -> None:
    study = {
        "protocolSection": {"identificationModule": {"nctId": "NCT1"}},
        "resultsSection": {
            "adverseEventsModule": {
                "eventGroups": [{"id": "EG000", "title": "Arm A"}, {"id": "EG001", "title": "Arm A"}],
                "seriousEvents": [
                    {"term": "Fever", "stats": [{"groupId": "EG000", "numAffected": 1, "numAtRisk": 10}, {"groupId": "EG001", "numAffected": 2, "numAtRisk": 12}]}
                ],
            }
        },
    }

    assert [e.group for e in to_results(study).adverse_events] == ["Arm A", "Arm A (EG001)"]


def test_split_measures_become_one_row_per_category() -> None:
    measure = {
        "type": "SECONDARY",
        "title": "Best Response",
        "paramType": "COUNT_OF_PARTICIPANTS",
        "unitOfMeasure": "Participants",
        "groups": [{"id": "OG000", "title": "Drug"}],
        "classes": [{"categories": [{"title": "Complete", "measurements": [{"groupId": "OG000", "value": "3"}]}, {"title": "Partial", "measurements": [{"groupId": "OG000", "value": "9"}]}]}],
    }
    study = {"protocolSection": {"identificationModule": {"nctId": "NCT1"}}, "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [measure]}}}

    outcomes = to_results(study).outcomes

    assert [o.label for o in outcomes] == ["Best Response — Complete", "Best Response — Partial"]


def test_spread_gives_a_symmetric_interval() -> None:
    assert GroupValue("Drug", "10.0", spread="2.5").interval == (7.5, 12.5)


def test_candidates_record_how_the_name_matched() -> None:
    pages = load_fixture("ctgov/keynote189_candidates.json")
    studies = pages["by_id_or_title"]["studies"]

    matched = {c.nct_id: (c.matched_by, c.has_results, c.enrollment) for c in (to_candidate(s, "keynote 189") for s in studies)}

    assert matched["NCT03950674"] == ("study_id", True, 40)  # Japan extension: "KEYNOTE-189" is its secondary ID
    assert matched["NCT02578680"] == ("title", True, 616)  # the main trial: only in its official title
    assert matched["NCT05908799"][1] is False


def test_acronyms_must_match_exactly() -> None:
    study = {"protocolSection": {"identificationModule": {"nctId": "NCT1", "acronym": "RECOVER-VITAL", "briefTitle": "Long COVID"}}}

    assert to_candidate(study, "RECOVER").matched_by is None
    assert to_candidate(study, "recover vital").matched_by == "acronym"


@pytest.mark.parametrize(
    ("name", "variants"),
    [("KEYNOTE-189", ("KEYNOTE-189",)), ("keynote 189", ("keynote 189", "keynote-189")), ('"RECOVERY"', ("RECOVERY",))],
)
def test_name_variants(name: str, variants: tuple[str, ...]) -> None:
    assert name_variants(name) == variants
