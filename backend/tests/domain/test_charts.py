from cheiron.domain.analysis import Cohort, CoOccurrence, Correlation, CountBy, Dimension, Distribution, Entity, Measure
from cheiron.domain.charts import build_visualization
from cheiron.domain.facets import (
    COMPLETION_DATE,
    INTERVENTION_NAME,
    LEAD_SPONSOR_CLASS,
    PHASES,
    START_DATE,
    START_DATE_TYPE,
)
from cheiron.domain.trial import DateType, InterventionType, Phase, SponsorClass, Status
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import (
    Channel,
    ChartType,
    Citation,
    Citations,
    Evidence,
    FieldType,
    Visualization,
)
from tests.domain.factories import drug, sponsor, trial

PEM = Cohort("Pembrolizumab", TrialFilter(intervention="pembrolizumab"))


def plain(viz: Visualization) -> list[dict]:
    return [{k: v for k, v in row.items() if k != "citations"} for row in viz.data]


def cited_ids(citations: Citations) -> list[str]:
    return [c.nct_id for c in citations.items]


# --- CountBy ------------------------------------------------------------------------------


def test_counts_by_phase_in_clinical_order_with_citations() -> None:
    trials = [
        trial("NCT1", phases=(Phase.PHASE2,)),
        trial("NCT2", phases=(Phase.PHASE1, Phase.PHASE2)),
        trial("NCT3", phases=(Phase.PHASE3,)),
        trial("NCT4"),
        trial("NCT5", phases=(Phase.NA,)),
    ]

    viz = build_visualization(CountBy((PEM,), Dimension.PHASE), {"Pembrolizumab": trials})

    assert viz.type is ChartType.BAR
    assert viz.title == "Trials by phase — Pembrolizumab"
    assert plain(viz) == [
        {"phase": "Phase 1", "trial_count": 1},
        {"phase": "Phase 2", "trial_count": 2},
        {"phase": "Phase 3", "trial_count": 1},
        {"phase": "Not applicable", "trial_count": 1},
    ]
    assert viz.encoding["x"] == Channel(
        "phase", FieldType.ORDINAL, "Phase", order=("Phase 1", "Phase 2", "Phase 3", "Not applicable")
    )
    assert viz.encoding["y"].field == "trial_count"
    assert viz.data[1]["citations"] == Citations(
        2,
        (
            Citation("NCT1", "Title of NCT1", "https://clinicaltrials.gov/study/NCT1", (Evidence(PHASES, "PHASE2"),), "phases: PHASE2"),
            Citation("NCT2", "Title of NCT2", "https://clinicaltrials.gov/study/NCT2", (Evidence(PHASES, "PHASE2"),), "phases: PHASE2"),
        ),
        ("NCT1", "NCT2"),
    )
    assert "1 of 5 trials have no registered phase and are not shown." in viz.notes
    assert any("counted once under each" in n for n in viz.notes)


def test_citations_are_capped_but_keep_the_total() -> None:
    trials = [trial(f"NCT{i}", phases=(Phase.PHASE2,)) for i in range(4)]

    viz = build_visualization(CountBy((PEM,), Dimension.PHASE), {"Pembrolizumab": trials}, max_citations=2)

    assert viz.data[0]["citations"].total == 4
    assert viz.data[0]["citations"].nct_ids == ("NCT0", "NCT1", "NCT2", "NCT3")
    assert cited_ids(viz.data[0]["citations"]) == ["NCT0", "NCT1"]


def _country_trials() -> list:
    return [
        trial("NCT-A1", countries=("Atlantis", "Brazil")),
        trial("NCT-A2", countries=("Atlantis", "Brazil")),
        trial("NCT-A3", countries=("Atlantis",)),
        *(trial(f"NCT-{i}", countries=(f"Country {i:02d}",)) for i in range(1, 16)),
    ]


def test_high_cardinality_dimensions_keep_the_15_most_frequent_by_default() -> None:
    viz = build_visualization(CountBy((PEM,), Dimension.COUNTRY), {"Pembrolizumab": _country_trials()})

    countries = [row["country"] for row in viz.data]
    assert countries == ["Atlantis", "Brazil", *(f"Country {i:02d}" for i in range(1, 14))]
    assert "Showing the 15 most frequent of 17 country values." in viz.notes


def test_explicit_top_n() -> None:
    viz = build_visualization(CountBy((PEM,), Dimension.COUNTRY, top_n=2), {"Pembrolizumab": _country_trials()})

    assert plain(viz) == [{"country": "Atlantis", "trial_count": 3}, {"country": "Brazil", "trial_count": 2}]


def test_time_series_fills_years_without_trials() -> None:
    trials = [
        trial("NCT1", start_date="2015-01"),
        trial("NCT2", start_date="2015-06-30"),
        trial("NCT3", start_date="2018"),
        trial("NCT4"),
    ]

    viz = build_visualization(CountBy((PEM,), Dimension.START_YEAR), {"Pembrolizumab": trials})

    assert viz.type is ChartType.TIME_SERIES
    assert viz.title == "Trials started per year — Pembrolizumab"
    assert plain(viz) == [
        {"start_year": 2015, "trial_count": 2},
        {"start_year": 2016, "trial_count": 0},
        {"start_year": 2017, "trial_count": 0},
        {"start_year": 2018, "trial_count": 1},
    ]
    assert viz.encoding["x"] == Channel("start_year", FieldType.TEMPORAL, "Start year", time_unit="year")
    assert viz.data[3]["citations"].items[0].evidence == (Evidence(START_DATE, "2018"),)
    assert viz.data[1]["citations"] == Citations(0, ())


def test_comparing_cohorts_gives_a_grouped_bar_with_every_combination() -> None:
    a, b = Cohort("A", TrialFilter(intervention="a")), Cohort("B", TrialFilter(intervention="b"))
    shared = trial("NCT2", phases=(Phase.PHASE2,))
    trials = {
        "A": [trial("NCT1", phases=(Phase.PHASE1,)), shared],
        "B": [shared, trial("NCT3", phases=(Phase.PHASE3,))],
    }

    viz = build_visualization(CountBy((a, b), Dimension.PHASE), trials)

    assert viz.type is ChartType.GROUPED_BAR
    assert viz.title == "Trials by phase — A vs B"
    assert plain(viz) == [
        {"phase": "Phase 1", "cohort": "A", "trial_count": 1},
        {"phase": "Phase 1", "cohort": "B", "trial_count": 0},
        {"phase": "Phase 2", "cohort": "A", "trial_count": 1},
        {"phase": "Phase 2", "cohort": "B", "trial_count": 1},
        {"phase": "Phase 3", "cohort": "A", "trial_count": 0},
        {"phase": "Phase 3", "cohort": "B", "trial_count": 1},
    ]
    assert viz.encoding["series"] == Channel("cohort", FieldType.NOMINAL, "Cohort", order=("A", "B"))
    assert "Trials that match more than one cohort are counted in each (1 in total)." in viz.notes


def test_split_by_a_second_dimension() -> None:
    trials = [
        trial("NCT1", phases=(Phase.PHASE1,), lead_sponsor=sponsor("Merck", SponsorClass.INDUSTRY)),
        trial("NCT2", phases=(Phase.PHASE1,), lead_sponsor=sponsor("MD Anderson", SponsorClass.OTHER)),
        trial("NCT3", phases=(Phase.PHASE2,), lead_sponsor=sponsor("Pfizer", SponsorClass.INDUSTRY)),
    ]

    viz = build_visualization(
        CountBy((PEM,), Dimension.PHASE, split_by=Dimension.LEAD_SPONSOR_CLASS), {"Pembrolizumab": trials}
    )

    assert viz.type is ChartType.GROUPED_BAR
    assert viz.title == "Trials by phase and lead sponsor class — Pembrolizumab"
    assert plain(viz) == [
        {"phase": "Phase 1", "lead_sponsor_class": "Industry", "trial_count": 1},
        {"phase": "Phase 1", "lead_sponsor_class": "Other", "trial_count": 1},
        {"phase": "Phase 2", "lead_sponsor_class": "Industry", "trial_count": 1},
        {"phase": "Phase 2", "lead_sponsor_class": "Other", "trial_count": 0},
    ]
    assert viz.encoding["series"].order == ("Industry", "Other")
    assert viz.data[0]["citations"].items[0].evidence == (
        Evidence(PHASES, "PHASE1"),
        Evidence(LEAD_SPONSOR_CLASS, "INDUSTRY"),
    )


def test_no_trials_gives_an_empty_chart() -> None:
    for dimension in (Dimension.PHASE, Dimension.START_YEAR, Dimension.COUNTRY):
        viz = build_visualization(CountBy((PEM,), dimension), {"Pembrolizumab": []})
        assert viz.data == []


# --- CoOccurrence ---------------------------------------------------------------------------


def _drug_trials() -> list:
    return [
        trial("NCT1", interventions=(drug("A"), drug("B"), drug("C"))),
        trial("NCT2", interventions=(drug("b"), drug("A"))),
        trial("NCT3", interventions=(drug("A"),)),
        trial("NCT4", interventions=(drug("D"), drug("E"))),
    ]


def test_drug_network_weights_edges_by_shared_trials() -> None:
    viz = build_visualization(CoOccurrence(PEM, Entity.DRUG, Entity.DRUG), {"Pembrolizumab": _drug_trials()})

    assert viz.type is ChartType.NETWORK
    assert viz.title == "Drug co-occurrence network — Pembrolizumab"
    nodes = [(n["id"], n["label"], n["kind"], n["trial_count"]) for n in viz.data["nodes"]]
    assert nodes == [
        ("drug:a", "A", "drug", 3),
        ("drug:b", "B", "drug", 2),
        ("drug:c", "C", "drug", 1),
        ("drug:d", "D", "drug", 1),
        ("drug:e", "E", "drug", 1),
    ]
    edges = [(e["source"], e["target"], e["trial_count"]) for e in viz.data["edges"]]
    assert edges == [
        ("drug:a", "drug:b", 2),
        ("drug:a", "drug:c", 1),
        ("drug:b", "drug:c", 1),
        ("drug:d", "drug:e", 1),
    ]
    assert viz.data["edges"][0]["citations"].items[1].evidence == (
        Evidence(INTERVENTION_NAME, "A"),
        Evidence(INTERVENTION_NAME, "b"),
    )
    assert viz.data["edges"][0]["citations"].items[1].excerpt == "interventions.name: A; interventions.name: b"
    assert set(viz.encoding) == {
        "node_id", "node_label", "node_size", "node_color", "node_shape",
        "edge_source", "edge_target", "edge_weight", "edge_strength",
    }


def test_network_drops_weak_links_and_unlinked_entities() -> None:
    viz = build_visualization(
        CoOccurrence(PEM, Entity.DRUG, Entity.DRUG, min_shared_trials=2), {"Pembrolizumab": _drug_trials()}
    )

    assert [n["id"] for n in viz.data["nodes"]] == ["drug:a", "drug:b"]
    assert [(e["source"], e["target"]) for e in viz.data["edges"]] == [("drug:a", "drug:b")]
    assert "Only links shared by at least 2 trials are shown." in viz.notes


def test_network_keeps_the_most_frequent_nodes() -> None:
    viz = build_visualization(
        CoOccurrence(PEM, Entity.DRUG, Entity.DRUG, max_nodes=2), {"Pembrolizumab": _drug_trials()}
    )

    assert [n["id"] for n in viz.data["nodes"]] == ["drug:a", "drug:b"]
    assert "Showing 2 of 5 entities, favouring the most frequent, and the strongest links between them (1)." in viz.notes


def test_bipartite_network_shares_the_node_budget_between_kinds() -> None:
    trials = [
        trial("NCT1", lead_sponsor=sponsor("Merck"), interventions=(drug("X"),)),
        trial("NCT2", lead_sponsor=sponsor("Merck"), interventions=(drug("X"),)),
        trial("NCT3", lead_sponsor=sponsor("Merck"), interventions=(drug("Y"),)),
        trial("NCT4", lead_sponsor=sponsor("Roche"), interventions=(drug("Z"),)),
    ]

    viz = build_visualization(
        CoOccurrence(PEM, Entity.SPONSOR, Entity.DRUG, max_nodes=2), {"Pembrolizumab": trials}
    )

    assert viz.title == "Sponsor–drug network — Pembrolizumab"
    assert [(n["id"], n["trial_count"]) for n in viz.data["nodes"]] == [("sponsor:merck", 3), ("drug:x", 2)]
    assert [(e["source"], e["target"], e["trial_count"]) for e in viz.data["edges"]] == [
        ("sponsor:merck", "drug:x", 2)
    ]


def test_network_without_links() -> None:
    viz = build_visualization(
        CoOccurrence(PEM, Entity.DRUG, Entity.DRUG), {"Pembrolizumab": [trial("NCT1", interventions=(drug("A"),))]}
    )

    assert viz.data == {"nodes": [], "edges": []}
    assert "No two entities are registered on the same trial." in viz.notes


# --- Distribution ---------------------------------------------------------------------------


def test_histogram_groups_the_long_tail_into_an_open_ended_bin() -> None:
    trials = [trial(f"NCT{v}", enrollment=v) for v in range(20)] + [trial("NCT-BIG", enrollment=1000), trial("NCT-NONE")]

    viz = build_visualization(Distribution(PEM, Measure.ENROLLMENT, bins=4), {"Pembrolizumab": trials})

    assert viz.type is ChartType.HISTOGRAM
    assert viz.title == "Distribution of enrollment — Pembrolizumab"
    assert plain(viz) == [
        {"bin_start": 0, "bin_end": 5, "trial_count": 5},
        {"bin_start": 5, "bin_end": 10, "trial_count": 5},
        {"bin_start": 10, "bin_end": 15, "trial_count": 5},
        {"bin_start": 15, "bin_end": 20, "trial_count": 5},
        {"bin_start": 20, "bin_end": None, "trial_count": 1},
    ]
    assert cited_ids(viz.data[-1]["citations"]) == ["NCT-BIG"]
    assert "1 of 22 trials have no enrollment and are not shown." in viz.notes
    assert any("beyond the 95th percentile" in n for n in viz.notes)


def test_histogram_without_outliers_has_no_open_bin() -> None:
    trials = [trial(f"NCT{v}", enrollment=v) for v in range(1, 11)]

    viz = build_visualization(Distribution(PEM, Measure.ENROLLMENT, bins=5), {"Pembrolizumab": trials})

    assert [(r["bin_start"], r["bin_end"], r["trial_count"]) for r in viz.data] == [
        (0, 2, 1),
        (2, 4, 2),
        (4, 6, 2),
        (6, 8, 2),
        (8, 10, 2),
        (10, 12, 1),
    ]


def test_histogram_of_identical_values() -> None:
    trials = [trial(f"NCT{i}", enrollment=50) for i in range(3)]

    viz = build_visualization(Distribution(PEM, Measure.ENROLLMENT), {"Pembrolizumab": trials})

    assert plain(viz) == [{"bin_start": 50, "bin_end": 51, "trial_count": 3}]


# --- Correlation ----------------------------------------------------------------------------


def test_scatter_has_one_cited_point_per_trial() -> None:
    trials = [
        trial("NCT1", start_date="2019-03", completion_date="2021-05"),
        trial("NCT2", start_date="2020-01"),
    ]

    viz = build_visualization(
        Correlation(PEM, Measure.START_YEAR, Measure.DURATION_MONTHS), {"Pembrolizumab": trials}
    )

    assert viz.type is ChartType.SCATTER
    assert viz.title == "Duration from start to completion vs start year — Pembrolizumab"
    assert plain(viz) == [{"nct_id": "NCT1", "title": "Title of NCT1", "start_year": 2019, "duration_months": 26}]
    assert viz.data[0]["citations"].items[0].evidence == (
        Evidence(START_DATE, "2019-03"),
        Evidence(COMPLETION_DATE, "2021-05"),
    )
    assert viz.encoding["x"] == Channel("start_year", FieldType.QUANTITATIVE, "Start year", unit="year")
    assert "1 of 2 trials lack start year or duration from start to completion and are not shown." in viz.notes


def _sized(enrollments: list[int], months: list[int]):
    return [
        trial(f"NCT{i}", enrollment=e, start_date="2015-01", completion_date=f"{2015 + m // 12}-{m % 12 + 1:02d}")
        for i, (e, m) in enumerate(zip(enrollments, months, strict=True))
    ]


def test_scatter_states_its_rank_correlation_in_words() -> None:
    plan = Correlation(PEM, Measure.DURATION_MONTHS, Measure.ENROLLMENT)

    rising = build_visualization(plan, {"Pembrolizumab": _sized([10, 20, 15, 40], [6, 12, 18, 24])})
    flat = build_visualization(plan, {"Pembrolizumab": _sized([30, 10, 10, 30], [6, 12, 18, 24])})

    assert (
        "Spearman rank correlation ρ = 0.80 over 4 trials: a strong positive association; "
        "enrollment tends to rise as duration from start to completion rises." in rising.notes
    )
    assert "Spearman rank correlation ρ = 0.00 over 4 trials: no clear association between" in flat.notes[-1]


def test_skewed_axes_are_drawn_log_like() -> None:
    plan = Correlation(PEM, Measure.DURATION_MONTHS, Measure.ENROLLMENT)

    viz = build_visualization(plan, {"Pembrolizumab": _sized([0, 50, 100, 2000], [6, 12, 18, 24])})

    assert (viz.encoding["x"].scale, viz.encoding["y"].scale) == (None, "symlog")  # 2000 is 27 times the median 75
    assert "Enrollment is drawn on a log-like (symlog) axis, as its largest value is 27 times its median; zeros stay on the axis." in viz.notes


# --- Titles -------------------------------------------------------------------------------


def test_titles_name_shared_filters_that_labels_do_not() -> None:
    # "Pembrolizumab" and "Pembrolizumab in South Korea" used to get the same title.
    korea = Cohort("Pembrolizumab", TrialFilter(intervention="pembrolizumab", country="South Korea"))

    viz = build_visualization(CountBy((korea,), Dimension.START_YEAR), {"Pembrolizumab": []})

    assert viz.title == "Trials started per year — Pembrolizumab · South Korea"


def test_titles_list_shared_phases_statuses_and_years_once() -> None:
    a = Cohort("Keytruda", TrialFilter(intervention="Keytruda", phases=frozenset({Phase.PHASE3, Phase.PHASE2}), start_year_from=2015))
    b = Cohort("Opdivo", TrialFilter(intervention="Opdivo", phases=frozenset({Phase.PHASE2, Phase.PHASE3}), start_year_from=2015))

    viz = build_visualization(CountBy((a, b), Dimension.LEAD_SPONSOR_CLASS), {"Keytruda": [], "Opdivo": []})

    assert viz.title == "Trials by lead sponsor class — Keytruda vs Opdivo · Phase 2, Phase 3 · started 2015 or later"


def test_titles_skip_filters_already_in_the_label() -> None:
    cohort = Cohort("Lung cancer, recruiting", TrialFilter(condition="lung cancer", statuses=frozenset({Status.RECRUITING})))

    viz = build_visualization(CountBy((cohort,), Dimension.COUNTRY), {"Lung cancer, recruiting": []})

    assert viz.title == "Trials by country — Lung cancer, recruiting"


# --- Network structure ------------------------------------------------------------------------


def _regimen_trials() -> list:
    """Every trial has the anchor drug P; A+B and X+Y are regimens that rarely mix."""
    regimen = lambda i, *names: trial(f"NCT{i}", interventions=tuple(drug(n) for n in ("P", *names)))  # noqa: E731
    return [
        regimen(1, "A", "B"), regimen(2, "A", "B"), regimen(3, "A", "B"),
        regimen(4, "X", "Y"), regimen(5, "X", "Y"), regimen(6, "X", "Y"),
        regimen(7, "B", "X"), regimen(8),
    ]


def test_the_filtered_entity_is_an_anchor_outside_the_clusters() -> None:
    cohort = Cohort("P", TrialFilter(intervention="p"))

    viz = build_visualization(CoOccurrence(cohort, Entity.DRUG, Entity.DRUG), {"P": _regimen_trials()})

    nodes = {n["label"]: n for n in viz.data["nodes"]}
    assert nodes["P"]["anchor"] is True and nodes["P"]["community"] is None
    assert {nodes[l]["community"] for l in ("A", "B")} == {"B"}  # named after its most frequent member
    assert {nodes[l]["community"] for l in ("X", "Y")} == {"X"}
    assert viz.encoding["node_color"].order == ("B", "X")
    assert any(n.startswith("P is in 100% of the trials (the question's own filter)") for n in viz.notes)
    assert any(n.startswith("Colours mark 2 clusters") for n in viz.notes)


def test_entities_in_most_trials_are_anchors_too() -> None:
    viz = build_visualization(CoOccurrence(PEM, Entity.DRUG, Entity.DRUG), {"Pembrolizumab": _regimen_trials()})

    assert [n["label"] for n in viz.data["nodes"] if n["anchor"]] == ["P"]
    assert any("(more than half of them)" in n for n in viz.notes)


def test_links_carry_their_association_and_nodes_their_partners() -> None:
    viz = build_visualization(CoOccurrence(PEM, Entity.DRUG, Entity.DRUG), {"Pembrolizumab": _regimen_trials()})

    labels = {n["id"]: n["label"] for n in viz.data["nodes"]}
    association = {tuple(sorted((labels[e["source"]], labels[e["target"]]))): e["association"] for e in viz.data["edges"]}
    assert association["A", "B"] == 0.75  # 3 shared / (3 + 4 - 3)
    assert association["B", "X"] == 0.143  # 1 / (4 + 4 - 1)
    assert {n["label"]: n["partners"] for n in viz.data["nodes"]}["P"] == 4


def test_registry_totals_set_bar_heights_and_ranking_but_not_citations() -> None:
    biological = drug("b", InterventionType.BIOLOGICAL)
    trials = [trial("NCT1", interventions=(drug("a"),)), trial("NCT2", interventions=(biological,)), trial("NCT3", interventions=(biological,))]
    plan = CountBy((PEM,), Dimension.INTERVENTION_TYPE, top_n=1)

    viz = build_visualization(plan, {"Pembrolizumab": trials}, totals={"Pembrolizumab": {"DRUG": 900, "BIOLOGICAL": 50}})

    # Biological leads among the analyzed trials (2 to 1), Drug in the registry.
    assert [(r["intervention_type"], r["trial_count"], r["citations"].total) for r in viz.data] == [("Drug", 900, 1)]


def test_estimated_start_dates_are_cited_and_counted() -> None:
    trials = [
        trial("NCT1", start_date="2025-03", start_date_type=DateType.ACTUAL),
        trial("NCT2", start_date="2027-01", start_date_type=DateType.ESTIMATED),
    ]

    viz = build_visualization(CountBy((PEM,), Dimension.START_YEAR), {"Pembrolizumab": trials})

    cited = {r["start_year"]: r["citations"].items[0].evidence for r in viz.data if r["trial_count"]}
    assert cited[2027] == (Evidence(START_DATE, "2027-01"), Evidence(START_DATE_TYPE, "ESTIMATED"))
    assert cited[2025][1] == Evidence(START_DATE_TYPE, "ACTUAL")
    assert (
        "1 of 2 counted trials have an estimated start date (not started yet, or not updated since; their "
        "citations show startDateStruct.type ESTIMATED), so the years they fall in are provisional." in viz.notes
    )
