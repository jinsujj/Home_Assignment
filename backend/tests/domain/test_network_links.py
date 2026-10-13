import pytest

from cheiron.domain.analysis import Cohort, CoOccurrence, Entity, Link
from cheiron.domain.charts import build_visualization
from cheiron.domain.facets import ARM_GROUP_INTERVENTION, ARM_GROUP_LABEL, COLLABORATOR_NAME, LEAD_SPONSOR_NAME
from cheiron.domain.trial import Arm, SponsorClass
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Evidence
from tests.domain.factories import drug, sponsor, trial

LUNG = Cohort("Lung cancer", TrialFilter(condition="lung cancer"))


def _trials():
    """Pembrolizumab + carboplatin in one arm, versus docetaxel in another; one trial without arms."""
    arms = (
        Arm("Experimental: Pembrolizumab + Carboplatin", ("Drug: Pembrolizumab", "Drug: Carboplatin")),
        Arm("Active Comparator: Docetaxel", ("Drug: Docetaxel",)),
    )
    return [
        trial("NCT1", interventions=(drug("Pembrolizumab"), drug("Carboplatin"), drug("Docetaxel")), arms=arms),
        trial("NCT2", interventions=(drug("Pembrolizumab"), drug("Carboplatin")), arms=arms[:1]),
        trial("NCT3", interventions=(drug("Pembrolizumab"), drug("Docetaxel"))),
    ]


def _edges(viz) -> dict[tuple[str, str], dict]:
    labels = {n["id"]: n["label"] for n in viz.data["nodes"]}
    return {tuple(sorted((labels[e["source"]], labels[e["target"]]))): e for e in viz.data["edges"]}


def test_drug_links_say_whether_drugs_are_combined_or_compared() -> None:
    viz = build_visualization(CoOccurrence(LUNG, Entity.DRUG, Entity.DRUG), {"Lung cancer": _trials()})

    edges = _edges(viz)
    combined, compared = edges["Carboplatin", "Pembrolizumab"], edges["Docetaxel", "Pembrolizumab"]
    assert (combined["trial_count"], combined["combined_trials"], combined["compared_trials"], combined["relation"]) == (2, 2, 0, "combined")
    assert (compared["trial_count"], compared["combined_trials"], compared["compared_trials"], compared["relation"]) == (2, 0, 1, "compared")
    # The citation quotes the arm that gives both drugs, as registered.
    assert combined["citations"].items[0].evidence == (
        Evidence(ARM_GROUP_LABEL, "Experimental: Pembrolizumab + Carboplatin"),
        Evidence(ARM_GROUP_INTERVENTION, "Drug: Carboplatin"),
        Evidence(ARM_GROUP_INTERVENTION, "Drug: Pembrolizumab"),
    )
    assert compared["citations"].items[0].evidence[0] == Evidence(ARM_GROUP_LABEL, "Active Comparator: Docetaxel")
    assert "1 of 3 trials list no drugs per arm, so their pairs are neither combined nor compared." in viz.notes
    assert viz.encoding["edge_style"].order == ("combined", "compared")  # no link left unclassified


def test_a_combination_network_keeps_only_drugs_given_together() -> None:
    combination = build_visualization(CoOccurrence(LUNG, Entity.DRUG, Entity.DRUG, link=Link.SAME_ARM), {"Lung cancer": _trials()})
    comparison = build_visualization(CoOccurrence(LUNG, Entity.DRUG, Entity.DRUG, link=Link.DIFFERENT_ARMS), {"Lung cancer": _trials()})

    assert combination.title == "Drug combination network — Lung cancer"
    assert combination.encoding["edge_style"].order == ("combined",)
    assert {pair: e["trial_count"] for pair, e in _edges(combination).items()} == {("Carboplatin", "Pembrolizumab"): 2}
    assert comparison.title == "Drugs compared in different arms — Lung cancer"
    assert set(_edges(comparison)) == {("Docetaxel", "Pembrolizumab"), ("Carboplatin", "Docetaxel")}


def test_sponsor_links_say_whether_the_sponsor_leads_or_collaborates() -> None:
    trials = [
        trial("NCT1", lead_sponsor=sponsor("Merck"), interventions=(drug("Pembrolizumab"),)),
        trial("NCT2", lead_sponsor=sponsor("NCI", SponsorClass.NIH), collaborators=(sponsor("Merck"),), interventions=(drug("Pembrolizumab"),)),
        trial("NCT3", lead_sponsor=sponsor("NCI", SponsorClass.NIH), collaborators=(sponsor("Merck"),), interventions=(drug("Pembrolizumab"),)),
    ]

    viz = build_visualization(CoOccurrence(LUNG, Entity.SPONSOR, Entity.DRUG), {"Lung cancer": trials})

    merck = _edges(viz)["Merck", "Pembrolizumab"]
    assert (merck["trial_count"], merck["lead_trials"], merck["collaborator_trials"], merck["relation"]) == (3, 1, 2, "collaborator")
    assert {e.field for c in merck["citations"].items for e in c.evidence} >= {LEAD_SPONSOR_NAME, COLLABORATOR_NAME}
    assert {n["label"]: n.get("sponsor_class") for n in viz.data["nodes"]} == {"Merck": "INDUSTRY", "NCI": "NIH", "Pembrolizumab": None}
    assert viz.encoding["node_category"].order == ("INDUSTRY", "NIH")


def test_arm_links_need_a_drug_network() -> None:
    with pytest.raises(ValueError, match="drug-drug"):
        CoOccurrence(LUNG, Entity.SPONSOR, Entity.DRUG, link=Link.SAME_ARM)
