from cheiron.domain.analysis import Cohort, CountBy, Dimension
from cheiron.domain.charts import build_visualization
from cheiron.domain.facets import CONDITIONS, INTERVENTION_NAME, INTERVENTION_OTHER_NAME, LEAD_SPONSOR_NAME
from cheiron.domain.membership import Membership, cite_memberships, memberships
from cheiron.domain.trial import Intervention, InterventionType, Phase
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Evidence
from tests.domain.factories import drug, sponsor, trial


def test_registered_values_matching_the_filter_are_cited() -> None:
    trials = [
        trial("NCT1", interventions=(drug("Carboplatin"), Intervention("MK-3475", InterventionType.DRUG, ("Keytruda",)))),
        trial("NCT2", conditions=("Hypertension", "Cancer of the Breast"), lead_sponsor=sponsor("Merck Sharp & Dohme LLC")),
    ]
    criteria = TrialFilter(intervention="Keytruda", condition="breast cancer", sponsor="Merck")
    every = dict.fromkeys(("intervention", "condition", "sponsor"), frozenset())

    found = memberships(trials, criteria, every)

    assert found["NCT1"] == Membership((Evidence(INTERVENTION_OTHER_NAME, "Keytruda"),))
    assert found["NCT2"].evidence == (Evidence(CONDITIONS, "Cancer of the Breast"), Evidence(LEAD_SPONSOR_NAME, "Merck Sharp & Dohme LLC"))


def test_a_synonym_is_found_through_the_cohorts_most_common_value() -> None:
    # The registry counts "Pembrolizumab" as Keytruda; no word is shared, so the value most
    # common among trials registering the drug is cited, not the trial's other drug.
    trials = [
        trial("NCT1", interventions=(drug("Pembrolizumab"),)),
        trial("NCT2", interventions=(drug("Pembrolizumab"),)),
        trial("NCT3", interventions=(drug("Carboplatin"), drug("Pembrolizumab"))),
    ]

    found = memberships(trials, TrialFilter(intervention="Keytruda"), {"intervention": frozenset()})

    assert found["NCT3"].evidence == (Evidence(INTERVENTION_NAME, "Pembrolizumab"),)


def test_mentions_are_flagged_and_unknown_criteria_left_out() -> None:
    trials = [trial("NCT1", interventions=(drug("Omega-3"),), conditions=("Gastric Cancer",))]
    criteria = TrialFilter(intervention="pembrolizumab", condition="gastric cancer")

    found = memberships(trials, criteria, {"intervention": frozenset({"NCT1"}), "condition": None})

    assert found["NCT1"] == Membership((), ("pembrolizumab",))


def test_each_compared_cohort_cites_its_own_filter() -> None:
    a, b = Cohort("Keytruda", TrialFilter(intervention="Keytruda")), Cohort("Opdivo", TrialFilter(intervention="Opdivo"))
    both = trial("NCT1", phases=(Phase.PHASE3,), interventions=(drug("Pembrolizumab"), drug("Nivolumab")))
    viz = build_visualization(CountBy((a, b), Dimension.PHASE), {"Keytruda": [both], "Opdivo": [both]})
    by_cohort = {
        "Keytruda": {"NCT1": Membership((Evidence(INTERVENTION_NAME, "Pembrolizumab"),))},
        "Opdivo": {"NCT1": Membership((Evidence(INTERVENTION_NAME, "Nivolumab"),))},
    }

    cited = cite_memberships(viz, by_cohort, None)

    assert [r["citations"].items[0].excerpt for r in cited.data] == [
        "phases: PHASE3; interventions.name: Pembrolizumab",
        "phases: PHASE3; interventions.name: Nivolumab",
    ]
