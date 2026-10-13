from cheiron.domain.analysis import ResultFocus, TrialResults
from cheiron.domain.charts.trial_results import MIN_AT_RISK, build_trial_results
from cheiron.domain.results import AdverseEvent, Comparison, GroupValue, Outcome, OutcomeType, PostedResults
from cheiron.domain.visualization import ChartType, Evidence


def outcome(title: str, values, type=OutcomeType.PRIMARY, measure="MEDIAN", unit="Months", comparisons=()) -> Outcome:
    return Outcome(type, title, None, measure, "95% Confidence Interval", unit, "Up to 21 months", tuple(values), comparisons)


PFS = outcome(
    "Progression-Free Survival",
    [GroupValue("Pembrolizumab", "8.8", "7.6", "9.2"), GroupValue("Control", "4.9", "4.7", "5.5")],
    comparisons=(Comparison(("Pembrolizumab", "Control"), "Hazard Ratio (HR)", "0.52", "95", "0.43", "0.64", "<0.00001"),),
)
OS = outcome("Overall Survival", [GroupValue("Pembrolizumab", "NA", "NA", "NA"), GroupValue("Control", "11.3", "8.7", "15.1")])
ORR = outcome("Overall Response Rate", [GroupValue("Pembrolizumab", "47.6"), GroupValue("Control", "18.9")], OutcomeType.SECONDARY, "NUMBER", "Percentage of Participants")
RESULTS = PostedResults("NCT02578680", "Pembrolizumab plus chemotherapy", None, (PFS, OS, ORR), ())


def plain(viz) -> list[dict]:
    return [{k: v for k, v in row.items() if k != "citations"} for row in viz.data]


def test_primary_outcomes_by_group_with_intervals() -> None:
    viz = build_trial_results(TrialResults("KEYNOTE-189"), RESULTS)

    assert viz.type is ChartType.GROUPED_BAR
    assert viz.title == "Primary outcomes — KEYNOTE-189 (NCT02578680)"
    assert plain(viz) == [
        {"outcome": "Progression-Free Survival", "group": "Pembrolizumab", "value": 8.8, "lower": 7.6, "upper": 9.2},
        {"outcome": "Progression-Free Survival", "group": "Control", "value": 4.9, "lower": 4.7, "upper": 5.5},
        {"outcome": "Overall Survival", "group": "Pembrolizumab", "value": None, "lower": None, "upper": None},
        {"outcome": "Overall Survival", "group": "Control", "value": 11.3, "lower": 8.7, "upper": 15.1},
    ]
    assert (viz.encoding["y"].title, viz.encoding["y"].unit) == ("Median", "Months")
    assert {"y_lower", "y_upper", "series"} <= set(viz.encoding)


def test_values_are_cited_as_posted() -> None:
    viz = build_trial_results(TrialResults("NCT02578680"), RESULTS)

    [citation] = viz.data[0]["citations"].items
    assert citation.nct_id == "NCT02578680"
    measurement = "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements"
    assert citation.evidence == (
        Evidence("resultsSection.outcomeMeasuresModule.outcomeMeasures.title", "Progression-Free Survival"),
        Evidence(f"{measurement}.value", "8.8"),
        Evidence(f"{measurement}.lowerLimit", "7.6"),
        Evidence(f"{measurement}.upperLimit", "9.2"),
    )


def test_notes_carry_posted_analyses_and_unestimable_values() -> None:
    viz = build_trial_results(TrialResults("NCT02578680"), RESULTS)

    assert viz.title == "Primary outcomes — NCT02578680"
    assert "Pembrolizumab: 'Overall Survival' was posted as 'NA' (not estimable); no bar is drawn." in viz.notes
    assert (
        "Progression-Free Survival: Hazard Ratio (HR) 0.52 (95% CI 0.43 to 0.64), p <0.00001; Pembrolizumab vs Control."
        in viz.notes
    )
    assert "Error bars show the posted 95% confidence interval." in viz.notes


def test_a_named_outcome_is_selected_by_title_words() -> None:
    viz = build_trial_results(TrialResults("NCT02578680", outcome="response rate"), RESULTS)

    assert viz.title == "Outcomes matching 'response rate' — NCT02578680"
    assert [r["value"] for r in viz.data] == [47.6, 18.9]
    assert (viz.encoding["y"].title, viz.encoding["y"].unit) == ("Number", "Percentage of Participants")
    assert "y_lower" not in viz.encoding


def test_one_chart_keeps_one_unit() -> None:
    viz = build_trial_results(TrialResults("NCT02578680", outcome="o"), RESULTS)  # matches PFS, OS and ORR

    assert {r["outcome"] for r in viz.data} == {"Progression-Free Survival", "Overall Survival"}
    assert "Also matching, in other units and not shown: Overall Response Rate." in viz.notes


def test_no_matching_outcome_lists_what_was_posted() -> None:
    viz = build_trial_results(TrialResults("NCT02578680", outcome="quality of life"), RESULTS)

    assert viz.data == []
    assert any("Posted measures: Progression-Free Survival; Overall Survival; Overall Response Rate." in n for n in viz.notes)


def _events(term: str, rates: dict[str, tuple[int, int]], serious: bool = True) -> list[AdverseEvent]:
    return [AdverseEvent(term, "Blood", serious, group, affected, at_risk) for group, (affected, at_risk) in rates.items()]


def test_adverse_events_as_percent_of_participants_at_risk() -> None:
    events = (
        _events("Anaemia", {"Pembrolizumab": (13, 405), "Control": (11, 202), "Crossover (second course)": (1, 2)})
        + _events("Febrile neutropenia", {"Pembrolizumab": (24, 405), "Control": (12, 202), "Crossover (second course)": (0, 2)})
        + _events("Nausea", {"Pembrolizumab": (200, 405), "Control": (90, 202)}, serious=False)
    )
    results = PostedResults("NCT02578680", "Trial", "KEYNOTE-189", (), tuple(events))

    viz = build_trial_results(TrialResults("NCT02578680", ResultFocus.ADVERSE_EVENTS), results)

    assert viz.title == "Serious adverse events — KEYNOTE-189 (NCT02578680)"
    assert [(r["event"], r["group"], r["percent"]) for r in viz.data] == [
        ("Febrile neutropenia", "Pembrolizumab", 5.9),
        ("Febrile neutropenia", "Control", 5.9),
        ("Anaemia", "Pembrolizumab", 3.2),
        ("Anaemia", "Control", 5.4),
    ]
    assert f"Groups with fewer than {MIN_AT_RISK} participants at risk are not shown: Crossover (second course) (2 at risk)." in viz.notes
    assert viz.data[0]["citations"].items[0].evidence[1:] == (
        Evidence("resultsSection.adverseEventsModule.seriousEvents.stats.numAffected", "24"),
        Evidence("resultsSection.adverseEventsModule.seriousEvents.stats.numAtRisk", "405"),
    )
