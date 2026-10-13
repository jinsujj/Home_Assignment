import pytest

from cheiron.domain.analysis import (
    Cohort,
    CoOccurrence,
    Correlation,
    CountBy,
    Dimension,
    Distribution,
    Entity,
    Measure,
    needs_sites,
)
from cheiron.domain.trial_filter import TrialFilter

A = Cohort("A", TrialFilter(intervention="a"))
B = Cohort("B", TrialFilter(intervention="b"))


def test_count_by_accepts_comparison_of_cohorts() -> None:
    assert CountBy((A, B), Dimension.PHASE).cohorts == (A, B)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (dict(cohorts=()), "between 1 and 5"),
        (dict(cohorts=(A,) * 6), "between 1 and 5"),
        (dict(cohorts=(A, A)), "unique"),
        (dict(cohorts=(A, B), split_by=Dimension.STATUS), "single cohort"),
        (dict(cohorts=(A,), split_by=Dimension.PHASE), "differ"),
        (dict(cohorts=(A,), top_n=0), "at least 1"),
    ],
)
def test_count_by_rejects_invalid_plans(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CountBy(dimension=kwargs.pop("dimension", Dimension.PHASE), **kwargs)


def test_top_n_does_not_apply_to_years() -> None:
    with pytest.raises(ValueError, match="start_year"):
        CountBy((A,), Dimension.START_YEAR, top_n=5)


def test_single_cohort_plans_expose_cohorts() -> None:
    assert CoOccurrence(A, Entity.DRUG, Entity.DRUG).cohorts == (A,)
    assert Distribution(A, Measure.ENROLLMENT).cohorts == (A,)
    assert Correlation(A, Measure.ENROLLMENT, Measure.DURATION_MONTHS).cohorts == (A,)


@pytest.mark.parametrize(
    "build",
    [
        lambda: CoOccurrence(A, Entity.DRUG, Entity.DRUG, max_nodes=1),
        lambda: CoOccurrence(A, Entity.DRUG, Entity.DRUG, min_shared_trials=0),
        lambda: Distribution(A, Measure.ENROLLMENT, bins=0),
        lambda: Correlation(A, Measure.ENROLLMENT, Measure.ENROLLMENT),
    ],
)
def test_single_cohort_plans_reject_invalid_parameters(build) -> None:
    with pytest.raises(ValueError):
        build()


def test_only_site_networks_need_sites() -> None:
    assert needs_sites(CoOccurrence(A, Entity.SITE, Entity.DRUG))
    assert needs_sites(CoOccurrence(A, Entity.DRUG, Entity.SITE))
    assert not needs_sites(CoOccurrence(A, Entity.INVESTIGATOR, Entity.DRUG))
    assert not needs_sites(CountBy((A,), Dimension.COUNTRY))
