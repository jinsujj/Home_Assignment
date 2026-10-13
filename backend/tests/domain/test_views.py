from cheiron.domain.analysis import Cohort, CoOccurrence, CountBy, Dimension, Distribution, Entity, Measure, TrialResults
from cheiron.domain.charts import build_visualization
from cheiron.domain.charts.trial_results import build_trial_results
from cheiron.domain.charts.views import alternative_views
from cheiron.domain.geography import iso_numeric
from cheiron.domain.results import GroupValue, Outcome, OutcomeType, PostedResults
from cheiron.domain.trial import Phase
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import ChartType, Visualization
from tests.domain.factories import drug, sponsor, trial

PEM = Cohort("Pembrolizumab", TrialFilter(intervention="pembrolizumab"))
A, B = Cohort("A", TrialFilter(intervention="a")), Cohort("B", TrialFilter(intervention="b"))


def types(views: tuple[Visualization, ...]) -> list[ChartType]:
    return [v.type for v in views]


def test_comparisons_get_each_groups_mix_and_a_heatmap() -> None:
    trials = {
        "A": [trial("NCT1", phases=(Phase.PHASE1,)), trial("NCT2", phases=(Phase.PHASE2,)), trial("NCT3", phases=(Phase.PHASE2,))],
        "B": [trial("NCT4", phases=(Phase.PHASE2,))],
    }
    primary = build_visualization(CountBy((A, B), Dimension.PHASE), trials)

    stacked, heatmap = alternative_views(primary)

    assert (stacked.type, heatmap.type) == (ChartType.STACKED_BAR, ChartType.HEATMAP)
    assert stacked.title == "Phase mix within each cohort — A vs B"
    shares = {(r["cohort"], r["phase"]): r["share"] for r in stacked.data}
    assert shares == {("A", "Phase 1"): 33.3, ("A", "Phase 2"): 66.7, ("B", "Phase 1"): 0.0, ("B", "Phase 2"): 100.0}
    assert stacked.encoding["x"].field == "cohort" and stacked.encoding["color"].field == "phase"
    assert heatmap.encoding["color"].field == "trial_count"
    assert heatmap.data[0]["citations"] is primary.data[0]["citations"]


def test_country_bars_also_map_with_iso_codes() -> None:
    trials = [trial("NCT1", countries=("South Korea", "Kosovo")), trial("NCT2", countries=("South Korea",))]
    primary = build_visualization(CountBy((PEM,), Dimension.COUNTRY), {"Pembrolizumab": trials})

    choropleth, donut = alternative_views(primary)

    assert choropleth.type is ChartType.CHOROPLETH
    assert [(r["country"], r["iso_numeric"]) for r in choropleth.data] == [("South Korea", "410"), ("Kosovo", None)]
    assert "Not on the map (no current country code): Kosovo." in choropleth.notes
    assert donut.type is ChartType.DONUT
    assert [r["share"] for r in donut.data] == [66.7, 33.3]


def test_other_bars_get_a_donut_only() -> None:
    primary = build_visualization(CountBy((PEM,), Dimension.PHASE), {"Pembrolizumab": [trial("NCT1", phases=(Phase.PHASE2,))]})

    assert types(alternative_views(primary)) == [ChartType.DONUT]


def test_time_series_accumulate_per_series() -> None:
    trials = [trial("NCT1", start_date="2015"), trial("NCT2", start_date="2017"), trial("NCT3", start_date="2017")]
    primary = build_visualization(CountBy((PEM,), Dimension.START_YEAR), {"Pembrolizumab": trials})

    [cumulative] = alternative_views(primary)

    assert cumulative.title == "Cumulative trials started — Pembrolizumab"
    assert [(r["start_year"], r["cumulative_count"]) for r in cumulative.data] == [(2015, 1), (2016, 1), (2017, 3)]


def test_networks_get_a_matrix_and_their_strongest_links() -> None:
    trials = [
        trial("NCT1", lead_sponsor=sponsor("Merck"), interventions=(drug("X"), drug("Y"))),
        trial("NCT2", lead_sponsor=sponsor("Merck"), interventions=(drug("X"),)),
    ]
    primary = build_visualization(CoOccurrence(PEM, Entity.SPONSOR, Entity.DRUG), {"Pembrolizumab": trials})

    matrix, ranking = alternative_views(primary)

    assert matrix.type is ChartType.HEATMAP
    assert sorted((c["column"], c["row"], c["trial_count"]) for c in matrix.data) == [("Merck", "X", 2), ("Merck", "Y", 1)]
    assert (matrix.encoding["x"].title, matrix.encoding["y"].title) == ("Sponsor", "Drug")
    assert ranking.type is ChartType.BAR
    assert [(r["link"], r["trial_count"]) for r in ranking.data] == [("Merck + X", 2), ("Merck + Y", 1)]


def test_drug_drug_matrices_are_symmetric() -> None:
    trials = [trial("NCT1", interventions=(drug("X"), drug("Y")))]
    primary = build_visualization(CoOccurrence(PEM, Entity.DRUG, Entity.DRUG), {"Pembrolizumab": trials})

    matrix, _ = alternative_views(primary)

    assert sorted((c["column"], c["row"]) for c in matrix.data) == [("X", "Y"), ("Y", "X")]


def test_histograms_get_a_cumulative_distribution() -> None:
    trials = [trial(f"NCT{v}", enrollment=v) for v in range(20)] + [trial("NCT-BIG", enrollment=1000)]
    primary = build_visualization(Distribution(PEM, Measure.ENROLLMENT, bins=4), {"Pembrolizumab": trials})

    [cdf] = alternative_views(primary)

    assert cdf.type is ChartType.LINE
    assert [(p["value"], p["cumulative_share"]) for p in cdf.data] == [(5, 23.8), (10, 47.6), (15, 71.4), (20, 95.2)]
    assert "The remaining 4.8% are at or above 20 participants." in cdf.notes


def test_posted_outcomes_get_a_forest_plot() -> None:
    outcome = Outcome(OutcomeType.PRIMARY, "Overall Survival", None, "MEDIAN", "95% Confidence Interval", "Months", "", (GroupValue("Control", "11.3", "8.7", "15.1"),))
    primary = build_trial_results(TrialResults("NCT02578680"), PostedResults("NCT02578680", "Trial", None, (outcome,), ()))

    [forest] = alternative_views(primary)

    assert forest.type is ChartType.FOREST
    assert (forest.encoding["x"].field, forest.encoding["x_lower"].field, forest.encoding["y"].field) == ("value", "lower", "outcome")
    assert forest.notes == ("Lines show the posted 95% confidence interval.",)


def test_empty_answers_have_no_alternatives() -> None:
    assert alternative_views(build_visualization(CountBy((PEM,), Dimension.PHASE), {"Pembrolizumab": []})) == ()
    assert alternative_views(build_visualization(CoOccurrence(PEM, Entity.DRUG, Entity.DRUG), {"Pembrolizumab": []})) == ()


def test_registry_country_names_map_to_iso_codes() -> None:
    assert iso_numeric("South Korea") == "410"
    assert iso_numeric("Turkey (Türkiye)") == "792"
    assert iso_numeric("Burma") == "104"
    assert iso_numeric("Afghanistan") == "004"
    assert iso_numeric("Kosovo") is None
