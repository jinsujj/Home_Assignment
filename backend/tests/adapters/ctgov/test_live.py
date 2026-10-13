"""Contract checks against the real API. Run with: uv run pytest -m live"""

from collections import Counter

import httpx
import pytest

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.adapters.outbound.ctgov.params import COUNTABLE_AREAS
from cheiron.domain.facets import dimension_facets
from cheiron.domain.trial import Phase
from cheiron.domain.trial_filter import TrialFilter

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_maps_a_full_page_of_real_studies() -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        result = await CtGovTrialSource(http).search(TrialFilter(condition="breast cancer"), max_trials=1000)

    assert result.total_count > 10_000
    assert len(result.trials) == 1000
    assert len({t.nct_id for t in result.trials}) == 1000


async def test_synonyms_and_exact_filters_are_honoured() -> None:
    criteria = TrialFilter(intervention="Keytruda", phases=frozenset({Phase.PHASE3}), start_year_from=2020)
    async with httpx.AsyncClient(timeout=30) as http:
        result = await CtGovTrialSource(http).search(criteria, max_trials=200)

    assert result.trials
    for trial in result.trials:
        assert Phase.PHASE3 in trial.phases
        assert trial.start_date is not None and trial.start_date.year >= 2020


async def test_registry_category_counts_equal_our_own_aggregation() -> None:
    # A cohort small enough to fetch whole, so both ways count the same trials.
    criteria = TrialFilter(condition="melanoma", country="South Korea")
    async with httpx.AsyncClient(timeout=30) as http:
        source = CtGovTrialSource(http)
        result = await source.search(criteria, max_trials=1000)
        assert not result.truncated
        for dimension in COUNTABLE_AREAS:
            ours = Counter(f.key for t in result.trials for f in dimension_facets(t, dimension))
            assert await source.count_by(criteria, dimension, list(ours)) == dict(ours), dimension
