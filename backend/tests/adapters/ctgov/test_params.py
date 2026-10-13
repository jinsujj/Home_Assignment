from cheiron.adapters.outbound.ctgov.params import to_params
from cheiron.domain.trial import Phase, Status, StudyType
from cheiron.domain.trial_filter import TrialFilter


def test_empty_filter_has_no_params() -> None:
    assert to_params(TrialFilter()) == {}


def test_free_text_goes_to_query_areas() -> None:
    params = to_params(TrialFilter(condition="breast cancer", intervention="Keytruda", sponsor="Merck"))

    assert params == {"query.cond": "breast cancer", "query.intr": "Keytruda", "query.spons": "Merck"}


def test_enumerated_criteria_go_to_exact_filters() -> None:
    params = to_params(
        TrialFilter(
            country="Korea, Republic of",
            phases=frozenset({Phase.PHASE3, Phase.PHASE2}),
            statuses=frozenset({Status.RECRUITING, Status.NOT_YET_RECRUITING}),
            study_type=StudyType.INTERVENTIONAL,
            start_year_from=2015,
            start_year_to=2020,
        )
    )

    assert params == {
        "filter.overallStatus": "NOT_YET_RECRUITING|RECRUITING",
        "filter.advanced": 'AREA[LocationCountry]"Korea, Republic of"'
        " AND AREA[Phase](PHASE2 OR PHASE3)"
        " AND AREA[StudyType]INTERVENTIONAL"
        " AND AREA[StartDate]RANGE[2015-01-01,2020-12-31]",
    }


def test_open_ended_year_ranges() -> None:
    assert to_params(TrialFilter(start_year_from=2015))["filter.advanced"] == "AREA[StartDate]RANGE[2015-01-01,MAX]"
    assert to_params(TrialFilter(start_year_to=2015))["filter.advanced"] == "AREA[StartDate]RANGE[MIN,2015-12-31]"


def test_strips_essie_syntax_from_free_text() -> None:
    # A lone quote makes the API answer 400; brackets would allow AREA[...] injection.
    params = to_params(TrialFilter(condition='breast "cancer', intervention="AREA[Phase](PHASE3)", country='"US"'))

    assert params["query.cond"] == "breast cancer"
    assert params["query.intr"] == "AREA Phase PHASE3"
    assert params["filter.advanced"] == 'AREA[LocationCountry]"US"'


def test_skips_text_that_is_empty_after_cleaning() -> None:
    assert to_params(TrialFilter(condition='  ""  ', country="()")) == {}


def test_typographic_quotes_become_plain_ones() -> None:
    params = to_params(TrialFilter(condition="Alzheimer’s disease", sponsor="“Merck”"))

    assert (params["query.cond"], params["query.spons"]) == ("Alzheimer's disease", "Merck")
