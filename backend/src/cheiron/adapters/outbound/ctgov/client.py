"""TrialSource backed by the ClinicalTrials.gov Data API v2."""

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx

from cheiron.adapters.outbound.ctgov.mapper import FIELDS, SITE_FIELDS, to_trial
from cheiron.adapters.outbound.ctgov.params import to_params
from cheiron.application.ports import TermCount, TrialSearchResult, TrialSourceError, Vocabulary
from cheiron.domain.trial_filter import TrialFilter

BASE_URL = "https://clinicaltrials.gov/api/v2"
MAX_PAGE_SIZE = 1000  # the API coerces larger values down to this
_VOCABULARY_PIECES = {
    Vocabulary.COUNTRY: "LocationCountry",  # all 226 values are returned
    Vocabulary.CONDITION: "Condition",  # top 250 of ~134,000
    Vocabulary.INTERVENTION: "InterventionName",  # top 250 of ~537,000
    Vocabulary.SPONSOR: "LeadSponsorName",  # top 250 of ~52,000
}


class CtGovTrialSource:
    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str = BASE_URL,
        retry_delays: Sequence[float] = (1.0, 2.0, 4.0),
    ) -> None:
        self._http = http
        self._base_url = base_url
        self._retry_delays = retry_delays

    async def search(self, criteria: TrialFilter, max_trials: int, *, include_sites: bool = False) -> TrialSearchResult:
        if max_trials < 1:
            raise ValueError("max_trials must be at least 1")
        fields = FIELDS + SITE_FIELDS if include_sites else FIELDS
        base = {**to_params(criteria), "fields": ",".join(fields), "format": "json"}

        first = await self._get({**base, "countTotal": "true", "pageSize": str(min(max_trials, MAX_PAGE_SIZE))})
        total = first["totalCount"]
        studies: list[dict[str, Any]] = list(first.get("studies", []))
        token = first.get("nextPageToken")

        # Later pages must repeat the first page's parameters; only pageSize/pageToken change.
        while token and len(studies) < max_trials:
            page_size = min(max_trials - len(studies), MAX_PAGE_SIZE)
            page = await self._get({**base, "pageSize": str(page_size), "pageToken": token})
            studies.extend(page.get("studies", []))
            token = page.get("nextPageToken")

        trials = tuple(to_trial(s) for s in studies[:max_trials])
        return TrialSearchResult(trials=trials, total_count=total)

    async def data_version(self) -> str:
        """Timestamp of the data snapshot being served; it changes when new data is published
        (in practice once per US business day, in one batch)."""
        return (await self._get({}, path="/version"))["dataTimestamp"]

    async def common_terms(self) -> dict[Vocabulary, tuple[TermCount, ...]]:
        """Registry-wide value counts from /stats/field/values (not filterable by search)."""
        stats = await self._get({"fields": ",".join(_VOCABULARY_PIECES.values())}, path="/stats/field/values")
        by_piece = {field["piece"]: field.get("topValues", []) for field in stats}
        return {
            vocabulary: tuple(TermCount(v["value"], v["studiesCount"]) for v in by_piece.get(piece, []))
            for vocabulary, piece in _VOCABULARY_PIECES.items()
        }

    async def _get(self, params: dict[str, str], path: str = "/studies") -> Any:
        for attempt, delay in enumerate((*self._retry_delays, None)):
            try:
                response = await self._http.get(self._base_url + path, params=params)
            except httpx.TransportError as exc:
                if delay is None:
                    raise TrialSourceError(f"ClinicalTrials.gov unreachable: {exc}") from exc
            else:
                if response.status_code == 200:
                    return response.json()
                if response.status_code != 429 and response.status_code < 500:
                    raise TrialSourceError(
                        f"ClinicalTrials.gov rejected the query ({response.status_code}): {response.text.strip()}"
                    )
                if delay is None:
                    raise TrialSourceError(
                        f"ClinicalTrials.gov unavailable after {attempt + 1} attempts ({response.status_code})"
                    )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")
