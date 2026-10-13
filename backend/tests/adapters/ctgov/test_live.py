"""Contract checks against the real API. Run with: uv run pytest -m live"""

from collections import Counter

import httpx
import pytest

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.adapters.outbound.ctgov.params import COUNTABLE_AREAS
from cheiron.domain.analysis import Dimension
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
            counts = await source.count_by(criteria, dimension, list(ours))
            assert {key: c.trials for key, c in counts.items()} == dict(ours), dimension
        # The trials behind a count can be listed: as many as it counts.
        key, count = next(iter(counts.items()))
        assert len(await source.category_ids(criteria, dimension, key, limit=1000)) == count.trials


async def test_trials_that_only_mention_a_drug_do_not_register_it() -> None:
    criteria = TrialFilter(intervention="pembrolizumab", phases=frozenset({Phase.PHASE3}))
    async with httpx.AsyncClient(timeout=30) as http:
        source = CtGovTrialSource(http)
        mentioned = await source.mentioned_only(criteria, "intervention", limit=1000)
        result = await source.search(criteria, max_trials=1000)

    assert mentioned and not result.truncated
    for trial in result.trials:
        names = " ".join(n for i in trial.interventions for n in (i.name, *i.other_names)).casefold()
        assert ("pembrolizumab" in names or "keytruda" in names or "mk-3475" in names) is (trial.nct_id not in mentioned)


async def test_tallied_years_equal_the_registrys_year_searches() -> None:
    criteria = TrialFilter(condition="melanoma", country="South Korea")
    async with httpx.AsyncClient(timeout=30) as http:
        source = CtGovTrialSource(http)
        counts = await source.tally(criteria, Dimension.START_YEAR, limit=1000)
        for year in sorted(counts, key=lambda y: -counts[y].trials)[:2]:
            reproduced = (await http.get(counts[year].query)).json()["totalCount"]
            assert reproduced == counts[year].trials, year
