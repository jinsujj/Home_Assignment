# Cheiron — ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns a natural-language question about clinical trials into a
structured, frontend-renderable visualization specification, backed by the
[ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api).

> **Status: work in progress.** Step 1 of 5 is done (ClinicalTrials.gov adapter).
> Sections marked _planned_ describe the design that later steps implement. See [Progress](#progress).

## Contents

1. [How to run](#how-to-run)
2. [Request / response schema](#request--response-schema)
3. [Key design decisions and trade-offs](#key-design-decisions-and-trade-offs)
4. [Limitations and future improvements](#limitations-and-future-improvements)
5. [Example runs](#example-runs)
6. [AI tool usage and validation](#ai-tool-usage-and-validation)
7. [Progress](#progress)

## How to run

### Install

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.14 if it is missing.

```bash
uv sync
```

### Configure

```bash
cp .env.example .env   # then set OPENAI_API_KEY
```

| Variable | Required | Used for |
|---|---|---|
| `OPENAI_API_KEY` | from step 3 | the LLM query planner |

`.env` is git-ignored; `.env.example` lists the variables and the allowed models.

### Start

_Planned (step 4):_ `uv run uvicorn cheiron.main:app`. There is no HTTP entry point yet.

### Test

```bash
uv run pytest            # offline: recorded API fixtures, no network
uv run pytest -m live    # contract checks against the real ClinicalTrials.gov API
```

## Request / response schema

_Planned (step 4)._ The service will expose `POST /visualize` with OpenAPI docs generated
from the Pydantic models. Planned shapes, following the assignment's examples:

```jsonc
// request
{ "query": "How has the number of trials for this drug changed over time?", // required
  "drug_name": "Pembrolizumab" }                                            // optional structured fields

// response
{ "visualization": { "type": "time_series", "title": "...", "encoding": { ... }, "data": [ ... ] },
  "meta": { "filters": { ... }, "source": "clinicaltrials.gov", "notes": [ ... ] } }
```

Each datum will carry citations (`nct_id` + the exact field value that placed the trial in that datum).

## Key design decisions and trade-offs

### The LLM plans; deterministic code computes

```
query + structured fields
  → Planner (LLM)    natural language → AnalysisPlan, constrained by a strict JSON Schema of enums
  → Validator        reject invalid combinations; explicit structured fields override LLM guesses
  → TrialSource      AnalysisPlan filters → ClinicalTrials.gov API, paginated
  → ACL              raw study JSON → domain Trial
  → Aggregator       Trial[] → buckets, each remembering its contributing NCT IDs   (pure)
  → SpecBuilder      plan shape → chart type + encoding                             (pure)
```

No number in a response comes from the LLM. Its only output is a small plan whose fields are
enums taken from the API spec, so hallucinations are limited to choosing a wrong (but valid)
plan, which the response's `meta` makes visible. Because the aggregator keeps contributing NCT
IDs per bucket, deep citations fall out of the design instead of being bolted on.

### Lightweight hexagonal architecture, selective DDD

The problem is a read-only analytics pipeline: no persistence, no mutable state, no invariants
spanning entities. It does have three real external boundaries (HTTP in; ClinicalTrials.gov
and the LLM out), so ports and adapters pay off, while most tactical DDD would be ceremony.

| Pattern | Used | Why |
|---|---|---|
| Ports and adapters | yes | Swap the API and the LLM for fakes, so the core is tested deterministically without network. |
| Anti-corruption layer | yes | `adapters/outbound/ctgov/mapper.py` turns deeply nested, sparse API JSON into a flat `Trial`. An API change touches one file. |
| Value objects / enums | yes | `Phase`, `Status`, `PartialDate`… validated once; the same enums constrain the LLM. |
| Ubiquitous language | yes | The domain says `Trial` because users and the assignment do (see below). |
| Aggregates, repositories, domain events | no | Nothing is mutated or stored; a repository would be a renamed API client. |
| Multiple bounded contexts, CQRS, DI container | no | One context, queries only; constructor injection suffices. |

The domain (`cheiron.domain`) depends on the standard library only. Pydantic is used at the edges
(HTTP schemas, LLM output schema).

### No database

ClinicalTrials.gov is the required source of truth and the service stores no state. A local
mirror (e.g. DuckDB over the bulk download) would give exact, fast `GROUP BY`s, but adds a
multi-GB ingestion step for reviewers and a freshness problem. An in-memory cache will sit
behind the `TrialSource` port instead; a database-backed source could replace it later
without touching the core.

### Aggregating on our side, with a cap

The API's `/stats/field/values` endpoint only reports statistics over *all* studies and accepts
no search filter (verified in the spec), so filtered aggregations must be computed by the
service. `CtGovTrialSource` fetches only the fields the analyses need (1,000 studies ≈ 1.9 MB,
≈ 1.5 s per page) up to a configurable cap, and reports `total_count` alongside the analyzed
trials so responses can say when a result is truncated.

Alternative considered: one `countTotal` request per bucket gives exact counts for very large
result sets but cannot produce citations and multiplies requests. It remains an option for
time series when truncation matters.

### Handling real API data

Observed while probing the live API (v2.0.5); each is handled or noted:

| Observation | Handling |
|---|---|
| Brand names and codes are synonyms: `Keytruda`, `MK-3475`, `pembrolizumab` all return 2,974 studies. | Free text goes to `query.*` to benefit from the API's synonym expansion. |
| One stray `"` makes the API answer `400`. | Essie syntax characters are stripped from free text (also blocks `AREA[...]` injection). |
| Exact criteria (phase, status, country, start year) need `filter.*` / `AREA[...]` syntax. | `params.py` builds them; tested against live counts. |
| Fields are often missing; dates come as `2021-05` or `2021-05-27`. | Every `Trial` attribute is optional; `PartialDate` keeps the registered precision instead of inventing a day. |
| Enum values may outgrow the spec. | Unknown values are dropped per field; the study is kept. |
| A study lists one location per site (hundreds per study). | `Trial.countries` is de-duplicated: a trial counts once per country. |
| Non-drug items are registered as interventions (e.g. "Laboratory Biomarker Analysis", type `OTHER`). | Drug networks will use `DRUG` / `BIOLOGICAL` interventions only. |
| Countries use registry spelling, e.g. `Korea, Republic of`. | The planner will be constrained to registry spellings. |
| `pageSize=0` means the default (10), not zero; subsequent pages must repeat the first page's parameters. | Encoded and tested in `client.py`. |
| `429` / `5xx` responses. | Retried with backoff (1 s, 2 s, 4 s); `4xx` fails fast with the API's message. |

### Naming: `Trial` rather than `Study`

ClinicalTrials.gov calls records "studies" and includes observational and expanded-access
studies, which are not trials in the strict sense. The domain keeps the users' word, `Trial`,
and `study_type` distinguishes the kinds; the ACL is where "study" becomes "trial".

### Python 3.14

The project targets Python ≥ 3.14 (lazy annotations by default; 3.12 is security-fix-only).
uv provisions the interpreter, so reviewers do not need it preinstalled.

## Limitations and future improvements

- Results above the fetch cap are analyzed on the first N studies the API returns (unsorted);
  `meta` will flag this. With more time: exact per-bucket counts for large time series.
- Free-text criteria rely on ClinicalTrials.gov's relevance search, which also matches mentions
  in descriptions (e.g. a fecal-transplant study that mentions pembrolizumab).
- Rate limits are not documented in the API spec; the client retries `429` but does not
  throttle proactively.

_To be completed as the remaining steps land._

## Example runs

_Planned (step 5):_ 3–5 queries with the actual JSON produced by the service.

## AI tool usage and validation

_To be completed by the author._ So far:

- **Tools:** Claude Code (Claude Opus 5.5) as a pair programmer for API exploration, code and tests.
- **Validation:** the OpenAPI spec (`docs/ctgov-openapi-v2.0.5.yaml`) was read and parameter
  behaviour probed against the live API before coding; offline tests use recorded API pages
  (`tests/fixtures/ctgov/`); `pytest -m live` re-checks the contract (1,000 real studies map
  without errors; synonym and exact filters hold on returned trials).

## Progress

| Step | Scope | Status |
|---|---|---|
| 1 | Project setup, ClinicalTrials.gov adapter (ACL, query params, pagination, retries) | done |
| 2 | Aggregator + SpecBuilder: hand-written plan → visualization spec | next |
| 3 | LLM planner + validator | planned |
| 4 | Use case, HTTP API, schema docs, citations in responses | planned |
| 5 | Network graphs polish, example runs, README completion | planned |

### Project structure

```
src/cheiron/
  domain/                      Trial, enums, TrialFilter (standard library only)
  application/ports.py         TrialSource port, TrialSearchResult
  adapters/outbound/ctgov/     ClinicalTrials.gov client, query params, ACL mapper
tests/                         unit tests, recorded API fixtures, live contract tests
docs/ctgov-openapi-v2.0.5.yaml the API spec this code was written against
```
