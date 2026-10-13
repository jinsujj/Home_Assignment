"""Contract checks against the real API. Run with: uv run pytest -m live"""

import httpx
import pytest

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
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
