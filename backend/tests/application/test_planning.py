import pytest

from cheiron.application.planning import (
    REFUSAL_MESSAGES,
    DraftRejected,
    Question,
    Refusal,
    StructuredFields,
    UnsupportedQuestion,
    ground,
)
from cheiron.domain.analysis import CoOccurrence, CountBy, Dimension, Entity, Link, ResultFocus, TrialResults
from cheiron.domain.trial import Phase, Status
from cheiron.domain.trial_filter import TrialFilter
from tests.application.planning_factories import cohort, draft, text


def test_grounded_filters_become_the_plan() -> None:
    question = Question("Which countries have the most recruiting trials for lung cancer since 2020?")
    proposal = draft(
        cohorts=[
            cohort(
                "Lung cancer",
                condition=text("lung cancer"),
                statuses={"values": ["RECRUITING"], "quote": "recruiting"},
                start_year_from={"value": 2020, "quote": "since 2020"},
            )
        ],
        dimension="country",
        top_n=10,
    )

    grounded = ground(proposal, question)

    assert grounded.plan == CountBy(
        (
            grounded.plan.cohorts[0].__class__(
                "Lung cancer",
                TrialFilter(condition="lung cancer", statuses=frozenset({Status.RECRUITING}), start_year_from=2020),
            ),
        ),
        Dimension.COUNTRY,
        top_n=10,
    )
    assert grounded.interpretation == "Trials by phase."
    assert grounded.notes == ()


def test_quotes_match_ignoring_case_spacing_and_quote_marks() -> None:
    question = Question('Compare  "Keytruda" vs Opdivo by phase')
    proposal = draft(cohorts=[cohort("K", intervention=text("keytruda")), cohort("O", intervention=text("OPDIVO"))])

    plan = ground(proposal, question).plan

    assert [c.filter.intervention for c in plan.cohorts] == ["keytruda", "OPDIVO"]


def test_unquoted_filter_is_a_problem_to_correct() -> None:
    question = Question("How are breast cancer trials distributed across phases?")
    proposal = draft(cohorts=[cohort(condition=text("breast cancer"), phases={"values": ["PHASE3"], "quote": "phase 3"})])

    with pytest.raises(DraftRejected) as rejected:
        ground(proposal, question)

    assert "the quote 'phase 3' for phases is not in the question" in rejected.value.problems[0]


def test_unquoted_filter_is_dropped_and_reported_on_the_last_attempt() -> None:
    question = Question("How are breast cancer trials distributed across phases?")
    proposal = draft(cohorts=[cohort(condition=text("breast cancer"), phases={"values": ["PHASE3"], "quote": "phase 3"})])

    grounded = ground(proposal, question, drop_unquoted=True)

    assert grounded.plan.cohorts[0].filter == TrialFilter(condition="breast cancer")
    assert grounded.notes == (
        "Ignored a phases filter on the cohort: its justification 'phase 3' does not appear in the question.",
    )


def test_text_values_must_come_from_their_quote() -> None:
    question = Question("Network of sponsors and drugs for Merck trials")
    proposal = draft(
        kind="co_occurrence",
        dimension=None,
        source="sponsor",
        target="drug",
        cohorts=[cohort(sponsor=text("Merck Sharp & Dohme LLC", "Merck"))],
    )

    with pytest.raises(DraftRejected, match="must be words taken from its quote"):
        ground(proposal, question)


def test_a_compared_cohort_left_without_filters_is_rejected() -> None:
    # gpt-4.1-mini quoted "trials involving Opdivo" for "Keytruda vs Opdivo"; dropping that
    # filter must not turn the comparison into Keytruda vs the whole registry.
    question = Question("Compare phases for trials involving Keytruda vs Opdivo.")
    proposal = draft(
        cohorts=[
            cohort("Keytruda", intervention=text("Keytruda")),
            cohort("Opdivo", intervention=text("Opdivo", "trials involving Opdivo")),
        ]
    )

    with pytest.raises(DraftRejected, match="'Opdivo' has no filter of its own"):
        ground(proposal, question, drop_unquoted=True)


def test_compared_cohorts_must_differ() -> None:
    question = Question("Compare phases for asthma trials vs asthma trials")
    proposal = draft(cohorts=[cohort("A", condition=text("asthma")), cohort("B", condition=text("asthma"))])

    with pytest.raises(DraftRejected, match="must differ"):
        ground(proposal, question)


def test_structured_fields_override_and_apply_to_every_cohort() -> None:
    question = Question(
        "How has the number of trials for this drug changed over time in phase 2 and phase 3?",
        StructuredFields(drug_name="Pembrolizumab", phases=frozenset({Phase.PHASE2})),
    )
    proposal = draft(
        dimension="start_year",
        cohorts=[cohort("", intervention=text("Keytruda", "unquoted"), phases={"values": ["PHASE2", "PHASE3"], "quote": "phase 2 and phase 3"})],
    )

    grounded = ground(proposal, question)

    assert grounded.plan.cohorts[0].label == "Pembrolizumab"
    assert grounded.plan.cohorts[0].filter == TrialFilter(intervention="Pembrolizumab", phases=frozenset({Phase.PHASE2}))
    assert grounded.notes == (
        "Applied the request's structured fields to every cohort: drug_name=Pembrolizumab, phases=['PHASE2'].",
    )


def test_structured_years_map_to_start_year_range() -> None:
    question = Question("Trials per phase", StructuredFields(condition="asthma", start_year=2015, end_year=2020))

    plan = ground(draft(), question).plan

    assert plan.cohorts[0].filter == TrialFilter(condition="asthma", start_year_from=2015, start_year_to=2020)


def test_refusals_use_fixed_wording_for_the_chosen_reason() -> None:
    # The planner only picks a reason; free-text reasons were inaccurate and varied per call.
    proposal = draft(answerable=False, refusal="medical_advice", kind=None, interpretation="I would advise...")

    with pytest.raises(UnsupportedQuestion) as refused:
        ground(proposal, Question("Should I take metformin for weight loss?"))

    assert refused.value.reason is Refusal.MEDICAL_ADVICE
    assert refused.value.message == REFUSAL_MESSAGES[Refusal.MEDICAL_ADVICE]


def test_refusals_without_a_reason_fall_back_to_other() -> None:
    with pytest.raises(UnsupportedQuestion) as refused:
        ground(draft(answerable=False, kind=None), Question("?"))

    assert refused.value.reason is Refusal.OTHER


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"kind": None}, "kind is required"),
        ({"dimension": None}, "count_by requires dimension"),
        ({"kind": "co_occurrence", "source": "drug"}, "co_occurrence requires target"),
        ({"kind": "distribution"}, "distribution requires measure"),
        ({"kind": "correlation", "x": "enrollment", "y": "enrollment"}, "different measures"),
        ({"dimension": "start_year", "top_n": 5}, "top_n does not apply"),
        ({"split_by": "phase"}, "split_by must differ"),
    ],
)
def test_incomplete_or_invalid_plans_are_rejected(overrides: dict, problem: str) -> None:
    with pytest.raises(DraftRejected, match=problem):
        ground(draft(**overrides), Question("anything"))


def test_single_cohort_kinds_reject_several_cohorts() -> None:
    proposal = draft(
        kind="co_occurrence",
        source="drug",
        target="drug",
        cohorts=[cohort("A", condition=text("asthma")), cohort("B", condition=text("COPD"))],
    )

    with pytest.raises(DraftRejected, match="exactly one cohort"):
        ground(proposal, Question("drug networks for asthma and COPD"))


def test_inverted_year_range_is_rejected() -> None:
    proposal = draft(
        cohorts=[cohort(start_year_from={"value": 2020, "quote": "2020"}, start_year_to={"value": 2015, "quote": "2015"})]
    )

    with pytest.raises(DraftRejected, match="after"):
        ground(proposal, Question("trials from 2020 to 2015"))


def test_labels_default_to_the_main_filter() -> None:
    proposal = draft(kind="co_occurrence", source="drug", target="drug", cohorts=[cohort("", condition=text("melanoma"))])

    plan = ground(proposal, Question("drugs combined in melanoma trials")).plan

    assert plan == CoOccurrence(plan.cohort.__class__("melanoma", TrialFilter(condition="melanoma")), Entity.DRUG, Entity.DRUG)


def test_a_combination_question_links_drugs_given_together() -> None:
    proposal = draft(
        kind="co_occurrence", dimension=None, source="drug", target="drug", link="same_arm",
        cohorts=[cohort("melanoma", condition=text("melanoma"))],
    )

    assert ground(proposal, Question("drugs combined in melanoma trials")).plan.link is Link.SAME_ARM


def test_arm_links_on_other_networks_are_problems_to_correct() -> None:
    proposal = draft(
        kind="co_occurrence", dimension=None, source="sponsor", target="drug", link="same_arm",
        cohorts=[cohort("melanoma", condition=text("melanoma"))],
    )

    with pytest.raises(DraftRejected, match="drug-drug"):
        ground(proposal, Question("sponsors and drugs in melanoma trials"))


# --- trial_results -------------------------------------------------------------------------


def results_draft(**overrides):
    base = {"kind": "trial_results", "cohorts": [], "dimension": None, "trial": text("KEYNOTE-189"), "result_focus": "outcomes"}
    return draft(**(base | overrides))


def test_a_named_trial_becomes_a_results_plan() -> None:
    proposal = results_draft(outcome=text("overall survival"))

    grounded = ground(proposal, Question("What was the overall survival in KEYNOTE-189?"))

    assert grounded.plan == TrialResults("KEYNOTE-189", ResultFocus.OUTCOMES, "overall survival")


def test_the_trial_must_be_named_in_the_question() -> None:
    proposal = results_draft(trial=text("KEYNOTE-189", "the Merck lung trial"))

    with pytest.raises(DraftRejected, match="must be named in the question"):
        ground(proposal, Question("What were the results of the big pembrolizumab lung trial?"), drop_unquoted=True)


def test_a_requested_nct_id_overrides_the_named_trial() -> None:
    question = Question("What were the results of KEYNOTE-189?", StructuredFields(nct_id="NCT03950674"))

    grounded = ground(results_draft(), question)

    assert grounded.plan.trial == "NCT03950674"
    assert grounded.notes == ("Using the requested trial NCT03950674.",)


def test_cohort_filters_do_not_apply_to_one_trial() -> None:
    question = Question("Adverse events in KEYNOTE-189", StructuredFields(country="South Korea"))

    grounded = ground(results_draft(result_focus="adverse_events"), question)

    assert grounded.plan.focus is ResultFocus.ADVERSE_EVENTS
    assert grounded.notes == ("The request's filters (country) do not apply to one trial's posted results and were ignored.",)


def test_an_unquoted_outcome_is_dropped_on_the_last_attempt() -> None:
    proposal = results_draft(outcome=text("progression-free survival"))

    with pytest.raises(DraftRejected):
        ground(proposal, Question("Results of KEYNOTE-189?"))
    grounded = ground(proposal, Question("Results of KEYNOTE-189?"), drop_unquoted=True)

    assert grounded.plan.outcome is None
