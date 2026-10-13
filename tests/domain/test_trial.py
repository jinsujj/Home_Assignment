import pytest

from cheiron.domain.trial import PartialDate
from cheiron.domain.trial_filter import TrialFilter


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2019", PartialDate(2019)),
        ("2019-03", PartialDate(2019, 3)),
        ("2019-03-27", PartialDate(2019, 3, 27)),
    ],
)
def test_partial_date_parses_registry_precisions(raw: str, expected: PartialDate) -> None:
    assert PartialDate.parse(raw) == expected


@pytest.mark.parametrize("raw", ["", "March 2019", "19-03", "2019/03"])
def test_partial_date_rejects_other_formats(raw: str) -> None:
    with pytest.raises(ValueError):
        PartialDate.parse(raw)


def test_filter_rejects_inverted_year_range() -> None:
    with pytest.raises(ValueError, match="after"):
        TrialFilter(start_year_from=2020, start_year_to=2015)


def test_filter_accepts_single_year_range() -> None:
    assert TrialFilter(start_year_from=2020, start_year_to=2020).start_year_to == 2020
