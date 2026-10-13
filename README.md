# Cheiron — ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns a natural-language question about clinical trials into a
structured, frontend-renderable visualization specification, backed by the
[ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api).

> **Status: work in progress.** Steps 1–2 of 5 are done (ClinicalTrials.gov adapter;
> analysis plan → visualization spec). Sections marked _planned_ describe the design that
> later steps implement. See [Progress](#progress).

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

_The HTTP layer is planned (step 4)._ The service will expose `POST /visualize` with OpenAPI
docs generated from the Pydantic models, following the assignment's examples:

```jsonc
// request
{ "query": "How has the number of trials for this drug changed over time?", // required
  "drug_name": "Pembrolizumab" }                                            // optional structured fields

// response
{ "visualization": { "type": "time_series", "title": "...", "encoding": { ... }, "data": [ ... ] },
  "meta": { "filters": { ... }, "source": "clinicaltrials.gov", "notes": [ ... ] } }
```

### Visualization spec (implemented)

`encoding` maps visual channels to data fields. Every channel is
`{ field, type, title, order, unit, time_unit }`, where `type` is one of `nominal`, `ordinal`,
`quantitative`, `temporal` (Vega-Lite's measurement types) and `order`, when present, is the
category order to render.

| `type` | Channels | Data |
|---|---|---|
| `bar_chart` | `x` (category), `y` | one row per category |
| `grouped_bar_chart` | `x`, `y`, `series` | one row per category × series, zeros included |
| `time_series` | `x` (temporal, `time_unit: "year"`), `y`, optional `series` | one row per year, gaps filled with 0 |
| `histogram` | `x` (`bin_start`), `x2` (`bin_end`), `y` | one row per bin; bins are `[bin_start, bin_end)`; the last bin may be open (`bin_end: null`) |
| `scatter_plot` | `x`, `y`, `tooltip` | one row per trial (`nct_id`, `title`, both measures) |
| `network_graph` | `node_id`, `node_label`, `node_size`, `node_color`, `edge_source`, `edge_target`, `edge_weight` | `{ "nodes": [...], "edges": [...] }` |

Every row, node and edge carries `citations`:

```json
"citations": {
  "total": 1777,
  "items": [
    { "nct_id": "NCT03044730",
      "title": "Pembrolizumab and Capecitabine in Treating Patients With ...",
      "url": "https://clinicaltrials.gov/study/NCT03044730",
      "evidence": [ { "field": "protocolSection.designModule.phases", "value": "PHASE2" } ] }
  ]
}
```

`total` is the number of trials behind the datum; `items` spells out the first few (default 5).
`evidence` names the field of the API's study JSON and the value exactly as registered that put
the trial into this datum (two entries for an edge, one per endpoint). `notes` lists assumptions
and caveats in plain sentences (multi-valued counting, missing values, top-N cut-offs, binning).

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

### One grammar for every question: `AnalysisPlan`

Rather than one code path per question type, every question is expressed in four analysis
kinds parameterised by enums (`cheiron/domain/analysis.py`). The chart type follows from the
plan's shape, deterministically:

| Plan | Parameters | Chart | Example question |
|---|---|---|---|
| `CountBy` | 1 cohort, `dimension` | `bar_chart` | "How are lung cancer trials distributed across phases?" |
| `CountBy` | `dimension = start_year` | `time_series` | "How many trials started each year for pembrolizumab?" |
| `CountBy` | 2–5 cohorts | `grouped_bar_chart` | "Compare phases for pembrolizumab vs nivolumab." |
| `CountBy` | 1 cohort + `split_by` | `grouped_bar_chart` | "Phases by sponsor class for pembrolizumab trials." |
| `CoOccurrence` | `source`, `target` entity | `network_graph` | "Network of sponsors ↔ drugs for breast cancer." |
| `Distribution` | `measure` | `histogram` | "How large are pembrolizumab trials?" |
| `Correlation` | `x`, `y` measures | `scatter_plot` | "Do longer trials enrol more patients?" |

Dimensions: phase, status, study type, start year, country, condition, intervention,
intervention type, lead sponsor, lead sponsor class. Entities: drug, sponsor, condition,
country, investigator, site. Measures: enrollment, duration (months), start year. A cohort is a label plus a
`TrialFilter`, so "Drug A vs Drug B" is two cohorts of the same `CountBy`.

Adding a question class means adding an enum member and how to read it from a `Trial`
(`domain/facets.py`), not a new pipeline.

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
| Country filters resolve variants (`USA`, `UK`, `Korea, Republic of` match `United States`, `United Kingdom`, `South Korea`); stored values use one spelling (226 distinct). | No country normalisation needed for filtering; charts show the stored spelling. |
| Not-yet-started trials carry anticipated start dates, including future years. | Time series note that recent and future years are provisional. |
| Officials are often roles, departments or companies: in ~6,000 surveyed records, "Clinical Sciences & Operations" (239), "Teva Medical Expert, MD" (107), "Medical Director" (106), "Medical Monitor" (90), hotline texts, the sponsor's own name. | The ACL keeps only names that look like people (pattern list from that survey; the sponsor-name rule skips individual sponsors, who are often their own investigator). |
| One person, several spellings: "Benoit Girard, MD" / "Benoit Girard, M.D."; "James D. Carlson, Pharm.D." in four forms. | Investigator nodes are keyed without credentials after the first comma, so surnames like "Do" or "Ma" are kept. |
| Facilities are often generic: "Research Site" (5,880 locations in three conditions), "GSK Investigational Site" (2,264), "Local Institution", hotline texts. | Generic facilities are dropped; sites are keyed by facility + city + country, so "University Hospital, Basel" ≠ "University Hospital, Zurich". |
| Facility and city of every location double the payload (1.9 → 4.1 MB per 1,000 studies), and one trial can list 1,151 sites (~660,000 site pairs). | Site fields are fetched only for plans with site nodes; network links are counted only among the 4 × `max_nodes` most frequent nodes (pembrolizumab site network: 25.8 s → 6.4 s, same result). |
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
- Entity names are matched ignoring case and spacing only. In a pembrolizumab drug network,
  "Pembrolizumab" is a hub, but registrations as "MK-3475" or "favezelimab/pembrolizumab" stay
  separate nodes. With more time: merge via the registered `otherNames` and a synonym source.
- Placeholder detection for investigators and sites is a pattern list drawn from a survey of
  real records, not a classifier; e.g. "Bristol-Myers Squibb" still passes as an investigator on
  trials where it is not a registered sponsor.
- Multi-valued attributes (phases, countries, conditions, interventions) count a trial once per
  value, so bars may add up to more than the number of trials; responses say so in `notes`.
- Scatter plots return one point per analyzed trial (up to the cap), which makes them the
  largest responses (measured: 2.1 MB for 2,969 pembrolizumab trials, vs 10 KB for a phase bar
  chart). With more time: drop the title duplicated between point and citation, or sample.

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
- **Aggregation cross-check:** our phase counts for all 2,974 pembrolizumab trials equal, for
  every phase, the API's own `countTotal` for the same query filtered to that phase
  (`tests/application/test_live_cross_check.py`).
- **Real-data smoke runs** of every plan kind (phase distribution, time series, drug A vs B,
  countries, phase × sponsor class, drug and sponsor–drug networks, histogram, scatter) were
  inspected before writing the unit tests; they surfaced the anticipated future start dates and
  the country-variant behaviour listed above.

## Progress

| Step | Scope | Status |
|---|---|---|
| 1 | Project setup, ClinicalTrials.gov adapter (ACL, query params, pagination, retries) | done |
| 2 | AnalysisPlan grammar, aggregation with citations, chart builders, `run_plan` use case | done |
| 3 | LLM planner + validator | next |
| 4 | Use case, HTTP API, schema docs, citations in responses | planned |
| 5 | Network graphs polish, example runs, README completion | planned |

### Project structure

```
src/cheiron/
  domain/                      standard library only
    trial.py, trial_filter.py    Trial, enums, TrialFilter
    analysis.py                  AnalysisPlan grammar: CountBy, CoOccurrence, Distribution, Correlation
    facets.py                    a Trial's values per dimension/entity/measure, with evidence
    charts/                      one builder per plan kind → Visualization
    visualization.py             output spec: chart types, channels, citations
  application/
    ports.py                     TrialSource port, TrialSearchResult
    run_plan.py                  use case: fetch cohorts concurrently, build, report truncation
  adapters/outbound/ctgov/     ClinicalTrials.gov client, query params, ACL mapper
tests/                         unit tests, recorded API fixtures, live contract and cross-checks
docs/ctgov-openapi-v2.0.5.yaml the API spec this code was written against
```
