"""TrialSource backed by the ClinicalTrials.gov Data API v2."""

import asyncio
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlencode

import httpx

from cheiron.adapters.outbound.ctgov.mapper import FIELDS, SITE_FIELDS, TALLY_FIELDS, TEXT_FIELDS, to_texts, to_trial
from cheiron.adapters.outbound.ctgov.params import (
    COUNTABLE_AREAS,
    category_params,
    essie_phrase,
    mentioned_only_params,
    tally_category_params,
    to_params,
)
from cheiron.adapters.outbound.ctgov.results_mapper import (
    CANDIDATE_FIELDS,
    NAME_AREAS,
    name_variants,
    to_candidate,
    to_results,
)
from cheiron.application.ports import TermCount, TrialCandidate, TrialSearchResult, TrialSourceError, Vocabulary
from cheiron.domain.analysis import Dimension
from cheiron.domain.charts import DEFAULT_MAX_CITATIONS
from cheiron.domain.charts.count_by import tally
from cheiron.domain.results import PostedResults
from cheiron.domain.visualization import RegistryCount
from cheiron.domain.trial_filter import TrialFilter

BASE_URL = "https://clinicaltrials.gov/api/v2"
MAX_PAGE_SIZE = 1000  # the API coerces larger values down to this
TEXTS_PER_REQUEST = 200  # NCT IDs in one filter.ids query string (~2.6 KB)
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

    async def count_by(
        self, criteria: TrialFilter, dimension: Dimension, keys: Sequence[str]
    ) -> dict[str, RegistryCount] | None:
        """One count-only request per key. They go one at a time: measured, the API answers a
        burst of about 10 requests and then about one per second, rejecting the rest with 429."""
        if dimension not in COUNTABLE_AREAS:
            return None
        counts = {}
        for key in keys:
            params = category_params(criteria, dimension, key)
            page = await self._get({**params, "countTotal": "true", "pageSize": "1", "fields": "NCTId"})
            counts[key] = RegistryCount(page["totalCount"], self._listing_url(params))
        return counts

    async def tally(
        self, criteria: TrialFilter, dimension: Dimension, limit: int
    ) -> dict[str | int, RegistryCount] | None:
        """Pages of 1,000 with only the fields the dimension needs; the trials are counted with
        the domain's own facets, so tallies and charts agree."""
        base = {
            **to_params(criteria),
            "fields": ",".join(("NCTId", "BriefTitle", *TALLY_FIELDS[dimension])),
            "pageSize": str(MAX_PAGE_SIZE),
        }
        page = await self._get({**base, "countTotal": "true"})
        if page["totalCount"] > limit:
            return None
        studies = list(page.get("studies", []))
        while token := page.get("nextPageToken"):
            page = await self._get({**base, "pageToken": token})
            studies += page.get("studies", [])
        counts: dict[str | int, RegistryCount] = {}
        for key, bucket in tally((to_trial(s) for s in studies), dimension).items():
            cited = bucket.citations(DEFAULT_MAX_CITATIONS)
            params = tally_category_params(criteria, dimension, key, bucket.label)
            counts[key] = RegistryCount(
                bucket.count, self._listing_url(params) if params else None, cited.nct_ids, bucket.label, cited.items
            )
        return counts

    def _listing_url(self, params: dict[str, str]) -> str:
        """An API request whose totalCount is the category's count and whose pages list its trials."""
        return f"{self._base_url}/studies?{urlencode({**params, 'countTotal': 'true', 'fields': 'NCTId,BriefTitle'})}"

    async def category_ids(
        self, criteria: TrialFilter, dimension: Dimension, key: str, limit: int
    ) -> tuple[str, ...] | None:
        return await self._ids(category_params(criteria, dimension, key), limit)

    async def mentioned_only(self, criteria: TrialFilter, criterion: str, limit: int) -> frozenset[str] | None:
        if not essie_phrase(getattr(criteria, criterion) or ""):
            return frozenset()  # no such criterion to check
        ids = await self._ids(mentioned_only_params(criteria, criterion), limit)
        return None if ids is None else frozenset(ids)

    async def _ids(self, params: dict[str, str], limit: int) -> tuple[str, ...] | None:
        """NCT IDs of every trial matching `params`, a page of 1,000 per request; None beyond `limit`."""
        base = {**params, "fields": "NCTId", "pageSize": str(MAX_PAGE_SIZE)}
        page = await self._get({**base, "countTotal": "true"})
        if page["totalCount"] > limit:
            return None
        ids = [s["protocolSection"]["identificationModule"]["nctId"] for s in page.get("studies", [])]
        while token := page.get("nextPageToken"):
            page = await self._get({**base, "pageToken": token})
            ids += [s["protocolSection"]["identificationModule"]["nctId"] for s in page.get("studies", [])]
        return tuple(ids)

    async def trial_texts(self, nct_ids: Sequence[str]) -> dict[str, dict[str, tuple[str, ...]]]:
        texts = {}
        for start in range(0, len(nct_ids), TEXTS_PER_REQUEST):
            chunk = nct_ids[start : start + TEXTS_PER_REQUEST]
            page = await self._get({"filter.ids": ",".join(chunk), "fields": ",".join(TEXT_FIELDS), "pageSize": str(len(chunk))})
            texts.update(to_texts(study) for study in page.get("studies", []))
        return texts

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

    async def find_trials(self, name: str) -> tuple[TrialCandidate, ...]:
        """Studies whose acronym, study IDs or titles contain `name` as a phrase.

        The registry indexes "KEYNOTE-189" as one term, so "KEYNOTE 189" is also searched
        hyphenated. Acronyms get their own query: common words ("RECOVERY") appear in
        thousands of titles and would crowd out the trial actually named so.
        """
        phrases = name_variants(name)
        if not phrases:
            return ()
        any_phrase = lambda areas: " OR ".join(f'AREA[{a}]"{p}"' for a in areas for p in phrases)  # noqa: E731
        by_acronym = await self._get({"filter.advanced": any_phrase(NAME_AREAS[:1]), "fields": CANDIDATE_FIELDS, "pageSize": "1000"})
        by_id_or_title = await self._get({"filter.advanced": any_phrase(NAME_AREAS[1:]), "fields": CANDIDATE_FIELDS, "pageSize": "100"})
        studies = {s["protocolSection"]["identificationModule"]["nctId"]: s for s in by_id_or_title.get("studies", [])}
        studies |= {s["protocolSection"]["identificationModule"]["nctId"]: s for s in by_acronym.get("studies", [])}
        return tuple(to_candidate(study, name) for study in studies.values())

    async def posted_results(self, nct_id: str) -> PostedResults | None:
        study = await self._get({}, path=f"/studies/{nct_id}", missing_ok=True)
        if not study or not study.get("hasResults") or "resultsSection" not in study:
            return None
        return to_results(study)

    async def _get(self, params: dict[str, str], path: str = "/studies", missing_ok: bool = False) -> Any:
        for attempt, delay in enumerate((*self._retry_delays, None)):
            try:
                response = await self._http.get(self._base_url + path, params=params)
            except httpx.TransportError as exc:
                if delay is None:
                    raise TrialSourceError(f"ClinicalTrials.gov unreachable: {exc}") from exc
            else:
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 404 and missing_ok:
                    return None
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
