from cheiron.domain.analysis import Cohort, CountBy, Dimension
from cheiron.domain.charts import build_visualization
from cheiron.domain.facets import (
    BRIEF_SUMMARY,
    CONDITIONS,
    ELIGIBILITY_CRITERIA,
    INTERVENTION_NAME,
    INTERVENTION_OTHER_NAME,
    LEAD_SPONSOR_NAME,
)
from cheiron.domain.membership import (
    MAX_PASSAGE,
    Membership,
    cite_memberships,
    memberships,
    mention_passage,
    mention_passages,
)
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

    assert found["NCT1"].evidence == (Evidence(INTERVENTION_OTHER_NAME, "Keytruda"),)
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

    assert (found["NCT1"].evidence, found["NCT1"].mentioned_only) == ((), ("pembrolizumab",))


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


def test_the_passage_naming_the_entity_is_quoted_verbatim_from_the_most_telling_text() -> None:
    summary = "Immunotherapy changed melanoma care. Anti-PD-1 drugs such as pembrolizumab remove the brakes. We test transplants."
    eligibility = "Inclusion Criteria:\n* Age 18 or older\n* Prior treatment with pembrolizumab.\n* ECOG 0-1"
    texts = {ELIGIBILITY_CRITERIA: (eligibility,), BRIEF_SUMMARY: (summary,)}

    assert mention_passage(texts, ["Pembrolizumab"]) == Evidence(BRIEF_SUMMARY, "Anti-PD-1 drugs such as pembrolizumab remove the brakes.")
    assert mention_passage({ELIGIBILITY_CRITERIA: (eligibility,)}, ["pembrolizumab"]) == Evidence(
        ELIGIBILITY_CRITERIA, "* Prior treatment with pembrolizumab."
    )
    assert mention_passage(texts, ["MK-3475"]) is None


def test_long_sentences_are_cut_around_the_name_and_stay_exact() -> None:
    text = "A" * 400 + " pembrolizumab " + "B" * 400

    passage = mention_passage({BRIEF_SUMMARY: (text,)}, ["pembrolizumab"])

    assert passage.value in text and "pembrolizumab" in passage.value and len(passage.value) <= MAX_PASSAGE


def test_a_mentioning_trial_is_searched_for_the_name_most_trials_register() -> None:
    trials = [trial("NCT1", interventions=(drug("Pembrolizumab"),)), trial("NCT2", interventions=(drug("Omega-3"),))]

    found = memberships(trials, TrialFilter(intervention="Keytruda"), {"intervention": frozenset({"NCT2"})})

    assert found["NCT2"].names == ("Keytruda", "Pembrolizumab")
    texts = {BRIEF_SUMMARY: ("Patients progressed on pembrolizumab.",)}
    assert found["NCT2"].with_passage(texts).evidence == (Evidence(BRIEF_SUMMARY, "Patients progressed on pembrolizumab."),)


def test_abbreviations_and_decimals_do_not_end_a_sentence() -> None:
    text = (
        "Patients receive immunotherapy [e.g., sintilimab, pembrolizumab, etc.\\] per protocol. Omega-3 is given daily. "
        "Some are on anti-PD-1 therapy (e.g. pembrolizumab) at 2.5 mg/kg. End."
    )

    passages = mention_passages({BRIEF_SUMMARY: (text,)}, ["pembrolizumab"])

    assert [p.value for p in passages] == [
        "Patients receive immunotherapy [e.g., sintilimab, pembrolizumab, etc.\\] per protocol.",
        "Some are on anti-PD-1 therapy (e.g. pembrolizumab) at 2.5 mg/kg.",
    ]


def test_a_short_sentence_is_kept_whole_wherever_the_name_is() -> None:
    title = "Ph3 Study of Exemestane With or Without Entinostat in Chinese Patients With Hormone Receptor-Positive, Locally Advanced or Metastatic Breast Cancer"

    assert mention_passage({BRIEF_SUMMARY: (title,)}, ["breast cancer"]).value == title
