"""Cross-checks our aggregation against the API's own counts. Run with: uv run pytest -m live"""

import httpx
import pytest

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.application.run_plan import run_plan
from cheiron.domain.analysis import Cohort, CountBy, Dimension
from cheiron.domain.facets import label
from cheiron.domain.trial import Phase
from cheiron.domain.trial_filter import TrialFilter

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_phase_counts_match_the_apis_filtered_counts() -> None:
    cohort = Cohort("Pembrolizumab", TrialFilter(intervention="pembrolizumab"))
    async with httpx.AsyncClient(timeout=60) as http:
        source = CtGovTrialSource(http)
        result = await run_plan(CountBy((cohort,), Dimension.PHASE), source, max_trials_per_cohort=5000)
        assert not result.cohorts[0].truncated, "cross-check needs the complete result set"

        ours = {row["phase"]: row["trial_count"] for row in result.visualization.data}
        for phase in Phase:
            per_phase = await source.search(TrialFilter(intervention="pembrolizumab", phases=frozenset({phase})), 1)
            assert ours.get(label(phase), 0) == per_phase.total_count, phase
