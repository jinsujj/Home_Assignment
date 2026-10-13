# Cheiron — ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns a natural-language question about clinical trials into a
structured, frontend-renderable visualization specification, backed by the
[ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api).

> **Status:** questions are answered end to end (`POST /api/visualize`: LLM plan → grounding
> → ClinicalTrials.gov → visualization spec), structured plans run directly (`POST /api/plans`),
> and a React demo renders both. Example runs are still to be added. See [Progress](#progress).

## Contents

1. [How to run](#how-to-run)
2. [Request / response schema](#request--response-schema)
3. [Key design decisions and trade-offs](#key-design-decisions-and-trade-offs)
4. [Limitations and future improvements](#limitations-and-future-improvements)
5. [Example runs](#example-runs)
6. [AI tool usage and validation](#ai-tool-usage-and-validation)
7. [Progress](#progress)

## How to run

### Configure

```bash
cp .env.example .env   # then set OPENAI_API_KEY
```

| Variable | Required | Used for |
|---|---|---|
| `OPENAI_API_KEY` | for `/api/visualize` | the LLM planner; `/api/plans` works without it |
| `OPENAI_MODEL` | no | planner model, default `gpt-5.4-mini` |
| `OPENAI_REASONING_EFFORT` | no | default `low`; set empty for non-reasoning models such as `gpt-4.1-mini` |

`.env` is git-ignored; `.env.example` lists the variables and the allowed models.

### Start with Docker (recommended)

```bash
docker compose up --build
```

Open <http://localhost:8080> for the demo UI; the API is under <http://localhost:8080/api>
with interactive docs at <http://localhost:8080/api/docs>. Two containers run: `api`
(FastAPI, Python 3.14, non-root) and `web` (nginx serving the React build and proxying `/api`).

### Local development

Requires [uv](https://docs.astral.sh/uv/) (installs Python 3.14 if missing) and Node 22.

```bash
cd backend && uv sync && uv run --env-file ../.env uvicorn cheiron.main:app --reload   # API on :8000
cd frontend && npm install && npm run dev       # UI on :5173, proxies /api to :8000
```

### Test

```bash
cd backend
uv run pytest            # offline: unit tests, recorded API fixtures, HTTP tests with a fake source
uv run pytest -m live    # contract checks and cross-checks against the real ClinicalTrials.gov API
uv run --env-file ../.env pytest -m llm   # planner evaluation against the real model (17 cases)
cd ../frontend && npm run build && npm run lint   # type-check, build, lint
```

## Request / response schema

| Endpoint | Purpose |
|---|---|
| `POST /api/visualize` | Question (+ optional structured fields) → plan → visualization. |
| `POST /api/plans` | Run a structured analysis plan directly, without the LLM. |
| `GET /api/options` | Choices for building filters: every registry country (exact spelling, trial count), common conditions/interventions/sponsors as suggestions, phase and status codes. Cached 6 h. |
| `GET /api/health` | Liveness. |
| `GET /api/docs` | OpenAPI documentation generated from the Pydantic models. |

### `POST /api/visualize` request

```json
{ "query": "How has the number of trials for this drug changed over time?", "drug_name": "Pembrolizumab" }
```

| Field | Type | Rules |
|---|---|---|
| `query` | string, 1–1,000 chars | required |
| `drug_name`, `condition`, `sponsor` | string ≤ 200 | optional |
| `country` | string ≤ 100 | optional |
| `phases`, `statuses` | list of registry codes (`PHASE3`, `RECRUITING`, …) | optional; any of |
| `start_year`, `end_year` | integer 1900–2100 | optional; trials starting in `[start_year, end_year]`; start ≤ end |
| `nct_id` | `NCT` + 8 digits | optional; for a single trial's results, use this trial (e.g. an alternative listed in `meta.trial`) |
| `max_trials_per_cohort` | integer 1–10,000 | default 5,000 |

Structured fields apply to every cohort and take precedence over what the planner extracted;
the question can refer to them ("this drug"). `meta.notes` says when they were applied, and the
chart title names every filter shared by all cohorts that no cohort label already names, e.g.
"Trials started per year — Pembrolizumab · South Korea". A country filter keeps trials with at
least one site in that country (for pembrolizumab in South Korea, 335 of 389 are multinational);
`meta.notes` says so whenever one is used.

| Status | When | Body |
|---|---|---|
| `200` | answered | the response below, with `meta.query` and `meta.interpretation` |
| `422` | invalid request | FastAPI's validation errors |
| `422` | no analysis can answer it (medical advice, off-topic, data none of the analyses use) | `{"detail": {"code": "unsupported_question", "reason", "message"}}`, `reason` ∈ `medical_advice`, `not_about_trials`, `unavailable_data`, `other`; fixed wording per reason |
| `422` | a named trial is not in the registry | `{"detail": {"code": "trial_not_found", "message"}}` |
| `422` | the trial has not posted results | `{"detail": {"code": "no_posted_results", "message", "trial": {"nct_id", "url"}}}` |
| `422` | no valid plan after one correction round | `{"detail": {"code": "plan_rejected", "message", "problems": [...]}}` |
| `502` | ClinicalTrials.gov failed | `{"detail": "..."}` |
| `503` | no `OPENAI_API_KEY`, or the model is unreachable | `{"detail": "..."}` |

### `POST /api/plans` request

```json
{
  "plan": {
    "kind": "count_by",
    "cohorts": [
      { "label": "Pembrolizumab", "filter": { "intervention": "pembrolizumab" } },
      { "label": "Nivolumab", "filter": { "intervention": "nivolumab" } }
    ],
    "dimension": "phase"
  },
  "max_trials_per_cohort": 5000
}
```

| Field | Type | Rules |
|---|---|---|
| `plan.kind` | `count_by` \| `co_occurrence` \| `distribution` \| `correlation` | required; selects the other fields (see [AnalysisPlan](#one-grammar-for-every-question-analysisplan)) |
| `plan.cohorts` / `plan.cohort` | cohort(s): `{ label, filter }` | `count_by`: 1–5 cohorts with unique labels; others: one cohort |
| `filter.condition`, `.intervention`, `.sponsor` | string ≤ 200 | optional free text; synonyms resolved by ClinicalTrials.gov |
| `filter.country` | string ≤ 100 | optional; common variants resolved (`USA`, `UK`) |
| `filter.phases`, `.statuses` | list of registry codes (`PHASE3`, `RECRUITING`, …) | optional; any of |
| `filter.study_type` | `INTERVENTIONAL` \| `OBSERVATIONAL` \| `EXPANDED_ACCESS` | optional |
| `filter.start_year_from`, `.start_year_to` | integer 1900–2100 | optional; from ≤ to |
| `max_trials_per_cohort` | integer 1–10,000 | default 5,000; larger result sets are truncated and flagged |

Unknown fields, unknown enum values and invalid combinations (e.g. `split_by` with several
cohorts) are rejected with `422` and an explanation; ClinicalTrials.gov failures return `502`.

### Response

```jsonc
{
  "visualization": { "type": "grouped_bar_chart", "title": "Trials by phase — Pembrolizumab vs Nivolumab",
                     "encoding": { "x": { ... }, "y": { ... }, "series": { ... } }, "data": [ ... ] },
  "alternatives": [                        // the same data in other chart forms (see below)
    { "type": "stacked_bar_chart", "title": "Phase mix within each cohort — ...", "encoding": { ... },
      "data": [ ... ], "notes": [ "Each bar is 100% of one cohort's counts, ..." ] },
    { "type": "heatmap", ... }
  ],
  "meta": {
    "source": "clinicaltrials.gov",
    "query": "Compare phases for Keytruda vs Opdivo",            // /api/visualize only
    "interpretation": "Compare trial phases for Keytruda versus Opdivo.",   // /api/visualize only
    "plan": { ... },                       // the analysis that ran, with every filter applied
    "cohorts": [ { "label": "Pembrolizumab", "matched": 2974, "analyzed": 2974, "truncated": false }, ... ],
    "notes": [ "175 of 2974 trials in Pembrolizumab have no registered phase and are not shown.", ... ]
  }
}
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

Alternative views (`alternatives`) add these types; each item also carries its own `notes`:

| `type` | Channels | Data |
|---|---|---|
| `stacked_bar_chart` | `x` (group), `y` (`share`, %, stacks to 100), `color` (category) | one row per group × category |
| `heatmap` | `x`, `y` (categories), `color` (value) | one row per cell |
| `choropleth_map` | `region` (`iso_numeric`, ISO 3166-1 numeric), `label` (country), `color` (value) | one row per country; join to world shapes by `region` (e.g. world-atlas `id`) |
| `donut_chart` | `theta` (value), `color` (category), `tooltip` (`share`, %) | one row per category |
| `line_chart` | `x`, `y` (quantitative) | one row per point |
| `forest_plot` | `y` (outcome), `series` (group), `x` (value), `x_lower`, `x_upper` | one row per outcome × group |

A single trial's results are a `grouped_bar_chart` (x = outcome or adverse event, series = the
trial's groups) and may add `y_lower` / `y_upper` channels: the posted interval (e.g. 95% CI), to
draw as error bars; a value posted as "NA" (e.g. a median not reached) is `null`. `meta.trial`
names the trial (`nct_id`, `title`, `url`) and other trials the name matched (`alternatives`).

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
  → Planner (LLM)    PlanDraft: plan + a verbatim quote per filter, strict JSON Schema of enums
  → Grounding        quotes checked against the question; structured fields override;
                     domain invariants; rejected drafts get one correction round
  → TrialSource      cohort filters → ClinicalTrials.gov API, paginated, cached per data snapshot
  → ACL              raw study JSON → domain Trial
  → Charts           Trial[] → buckets with contributing NCT IDs → chart type + encoding   (pure)
```

No number in a response comes from the LLM. Its only output is a small plan whose categorical
fields are enums taken from the API spec, so hallucinations are limited to choosing a wrong
(but valid) plan, which `meta.interpretation` and `meta.plan` make visible and the demo lets
the user edit and rerun. Because the aggregator keeps contributing NCT IDs per bucket, deep
citations fall out of the design instead of being bolted on.

### AI design: grounding the planner in the question

Four layers keep the planner honest (`application/planning.py`, `application/visualize.py`):

1. **Constrained output.** The model answers with `PlanDraft` via structured outputs in strict
   mode: dimensions, entities, measures, phases, statuses and study types are enums.
2. **Quoted filters.** Each filter carries the exact words of the question that state it.
   A quote not found in the question (case-, spacing- and quote-mark-insensitive) means the
   filter was invented or paraphrased; text values must be taken from their quote, so search
   terms are the user's words and synonyms are left to ClinicalTrials.gov.
3. **One correction round.** Problems (unquoted filters, missing kind-specific fields, domain
   violations such as `split_by` with several cohorts) go back to the model with its previous
   draft. On the last attempt unquoted filters are dropped and reported in `meta.notes`, unless
   that leaves a compared cohort without a filter of its own, which is rejected instead.
4. **Refusal by reason code.** Questions no analysis can answer return
   `422 unsupported_question`; the model only picks a `refusal` enum and the message is fixed
   text per reason. It used to write its own reason: three runs of "What were the results of
   KEYNOTE-189?" gave three different reasons, two of them false ("registration data cannot
   describe results", while the trial's results are posted). That question is now answered
   (see `TrialResults` below).

Why the correction round exists: in the first evaluation `gpt-4.1-mini` quoted "trials involving
Opdivo" for "Keytruda vs Opdivo". Dropping that filter silently turned the comparison into
Keytruda vs the whole registry. With the round, the model fixes its quotes (both comparisons
then planned correctly), and a cohort left without filters is rejected rather than charted.

The planner sees today's date (for "in the last 5 years"), the structured fields (for "this
drug") and the grammar; it never sees trial data.

**Model choice** (`tests/llm/test_planner_eval.py`: every appendix question type,
structured-field references, relative periods, named-trial results and refusals; each case
asserts the exact filters, so an added filter fails it, and refusals assert their reason):

| Model | Result | Planner latency |
|---|---|---|
| `gpt-5.4-mini`, reasoning `low` (default) | 17/17 twice on the first suite; 19/19 on the current one | ~1.5–2.2 s |
| `gpt-4.1-mini` | 16/17 on the first suite (Keytruda vs Opdivo failed once, passed 3/3 on rerun) | ~1.8–4.8 s |

### One grammar for every question: `AnalysisPlan`

Rather than one code path per question type, every question is expressed in five analysis
kinds parameterised by enums (`cheiron/domain/analysis.py`): four over many trials, one over a
single trial's posted results. The chart type follows from the
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
| `TrialResults` | `trial` (NCT ID or name), `focus`, optional `outcome` | `grouped_bar_chart` with intervals | "What were the results of KEYNOTE-189?", "Side effects in CheckMate 227?" |

Dimensions: phase, status, study type, start year, country, condition, intervention,
intervention type, lead sponsor, lead sponsor class. Entities: drug, sponsor, condition,
country, investigator, site. Measures: enrollment, duration (months), start year. A cohort is a label plus a
`TrialFilter`, so "Drug A vs Drug B" is two cohorts of the same `CountBy`.

Adding a question class means adding an enum member and how to read it from a `Trial`
(`domain/facets.py`), not a new pipeline.

### One answer, several views

The design goal asks for many visualization types from one coherent approach. Every answer
therefore comes with **alternative views computed from the primary chart's rows**
(`domain/charts/views.py`), never from new data or another LLM call: all views of an answer
show the same numbers and carry the same citations, and which views exist depends only on the
primary's type and encoding.

| Primary | Alternatives | Why |
|---|---|---|
| `bar_chart` | `choropleth_map` (when categories are countries), `donut_chart` | geography reads best on a map; a donut shows each category's share |
| `grouped_bar_chart` (comparison) | `stacked_bar_chart` (100% per group), `heatmap` | groups of different size (Keytruda 2,974 vs Opdivo 2,030 trials) compare fairly as mixes: their phase mixes turn out nearly identical |
| `grouped_bar_chart` (a trial's outcomes) | `forest_plot` | point estimates with intervals, the usual form for posted results |
| `time_series` | cumulative `time_series` | growth and total in one view |
| `network_graph` | `heatmap` (adjacency matrix), `bar_chart` (strongest links) | dense networks are hard to read; the matrix and ranking give exact values |
| `histogram` | `line_chart` (cumulative distribution) | "what share of trials enroll fewer than N" reads directly |

Rates (adverse events in %) get a heatmap but no 100% stack, which would add up rates of
different events. The map joins countries by ISO 3166-1 numeric code from a table of the
registry's 226 country names (`domain/country_codes.json`): generated with pycountry, then
checked by hand, which caught a wrong fuzzy match ("Kosovo" → Serbia); 14 names needed manual
codes and four have no current code (Kosovo and three former states) and are listed in the
map's notes. Building the views in a browser found two bugs: Vega-Lite drops map shapes whose
colour value is null (countries without data vanished; the map now draws a grey base layer),
and channel titles that already contained the unit were suffixed again ("Median (Months)
(Months)"; units now travel only in `Channel.unit`).

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

The domain (`cheiron.domain`) depends on the standard library only. Pydantic is used for the HTTP
schemas and for the planner contract (`PlanDraft` in `application/planning.py`), which doubles as
the JSON Schema any LLM adapter must satisfy.

### No database

ClinicalTrials.gov is the required source of truth and the service stores no state. A local
mirror (e.g. DuckDB over the bulk download) would give exact, fast `GROUP BY`s, but adds a
multi-GB ingestion step for reviewers and a freshness problem. A cache sits behind the
`TrialSource` port instead (below); a database-backed source could replace it later without
touching the core.

### Caching keyed to the published data snapshot

Before caching, how often the data changes was measured rather than assumed:

- `/version` reports the snapshot timestamp (`dataTimestamp`). On Tuesday 2026-10-13 it still
  read Friday `2026-10-09T09:00:05`.
- Counting studies by `LastUpdatePostDate` over two weeks: ~800–1,200 updates are posted per
  US business day (≈0.17% of 606,601 studies), none on weekends, none on the 2026-10-12 federal
  holiday — updates arrive as one batch per business day.
- Per cohort, one week of postings touched 0.9% (breast cancer) to 4.3% (recruiting lung cancer)
  of trials.

So results stay valid until the next published snapshot. `CachingTrialSource` (a decorator
around the ClinicalTrials.gov adapter) keeps search results, trial-name lookups and posted
results in memory and drops them when
`dataTimestamp` changes, checking it at most every 10 minutes; a 24-hour maximum age bounds
staleness if the check fails. A fixed TTL was rejected: it would discard valid results over
weekends and serve stale ones for hours after a new snapshot. Capacity is counted in trials
(30,000; site-bearing results count triple, as measured), evicting least recently used.
Effect: a repeated or related question on the same cohort (phase, then start year) drops from
~4 s to ~10 ms. Redis was considered; with one API process it adds a container and
serialization code for no shared-state benefit, and it would implement the same port if the
API were scaled out.

### Aggregating on our side, with a cap

The API's `/stats/field/values` endpoint only reports statistics over *all* studies and accepts
no search filter (verified in the spec), so filtered aggregations must be computed by the
service. `CtGovTrialSource` fetches only the fields the analyses need (1,000 studies ≈ 1.9 MB,
≈ 1.3 s per page) up to a cap (default 5,000 per cohort, at most 10,000), and reports
`total_count` alongside the analyzed trials so responses say when a result is truncated. The
default was raised from 2,000 after a pembrolizumab chart (2,974 trials) showed Phase 1 at
699 instead of 1,046: flagged, but misleading in absolute terms.

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
| `/stats/field/values` returns all 226 location countries but only the top 250 of ~134,000 conditions, ~537,000 intervention names and ~52,000 sponsors; the intervention top list is led by "Placebo", "Control", "No intervention", "Usual Care". | `GET /api/options` offers the full country list as a dropdown and the top terms (without such non-search terms, case duplicates merged) as suggestions; free text still works. |
| Officials are often roles, departments or companies: in ~6,000 surveyed records, "Clinical Sciences & Operations" (239), "Teva Medical Expert, MD" (107), "Medical Director" (106), "Medical Monitor" (90), hotline texts, the sponsor's own name. | The ACL keeps only names that look like people (pattern list from that survey; the sponsor-name rule skips individual sponsors, who are often their own investigator). |
| One person, several spellings: "Benoit Girard, MD" / "Benoit Girard, M.D."; "James D. Carlson, Pharm.D." in four forms. | Investigator nodes are keyed without credentials after the first comma, so surnames like "Do" or "Ma" are kept. |
| Facilities are often generic: "Research Site" (5,880 locations in three conditions), "GSK Investigational Site" (2,264), "Local Institution", hotline texts. | Generic facilities are dropped; sites are keyed by facility + city + country, so "University Hospital, Basel" ≠ "University Hospital, Zurich". |
| Facility and city of every location double the payload (1.9 → 4.1 MB per 1,000 studies), and one trial can list 1,151 sites (~660,000 site pairs). | Site fields are fetched only for plans with site nodes; network links are counted only among the 4 × `max_nodes` most frequent nodes (pembrolizumab site network: 25.8 s → 6.4 s, same result). |
| `pageSize=0` means the default (10), not zero; subsequent pages must repeat the first page's parameters. | Encoded and tested in `client.py`. |
| Trial names are ambiguous. "KEYNOTE-189" is a secondary ID only of the 40-patient Japan extension; the 616-patient main trial has it only in its title; observational "emulations" mention it too. An ID-only lookup returns the wrong trial. | `find_trials` searches acronym, study IDs and titles; `choose_trial`: exact acronym first, IDs/titles only for distinctive names (digit or several words), trials with posted results only, largest enrollment chosen, the rest returned as `meta.trial.alternatives` with a note. |
| The registry indexes "KEYNOTE-189" as one term: "KEYNOTE 189" finds nothing. A common word ("RECOVERY") is in 5,682 titles. | Names are also searched hyphenated; acronyms get their own query; single common words only match acronyms. |
| Posted results: medians "not reached" are posted as "NA"; dispersion is limits or a spread; adverse-event groups include crossover groups with 2 participants at risk; two groups can share a title. | "NA" is kept as text and charted as null with a note; spreads become value ± spread; groups under 10 at risk are left out of adverse-event charts (noted); duplicate titles get their group ID. |
| `429` / `5xx` responses. | Retried with backoff (1 s, 2 s, 4 s); `4xx` fails fast with the API's message. |

### Naming: `Trial` rather than `Study`

ClinicalTrials.gov calls records "studies" and includes observational and expanded-access
studies, which are not trials in the strict sense. The domain keeps the users' word, `Trial`,
and `study_type` distinguishes the kinds; the ACL is where "study" becomes "trial".

### Two entry points: structured plans and natural language

`POST /api/visualize` lets the LLM write the plan; `POST /api/plans` runs a plan directly. Both
run the same `run_plan` use case and return the same response; `meta.plan` of a question's answer
is a valid `/api/plans` request, so an interpretation can be corrected by hand and rerun (the demo
does this). The LLM writes a separate `PlanDraft` rather than the public plan schema because the
draft carries the per-filter quotes used for grounding. The structured endpoint gives
reproducible results, exercises the core without an LLM, and serves clients that build plans
themselves.

### Frontend: a generic renderer, not a per-question UI

The React demo (`frontend/`) works like a chat assistant: the question box is pinned to the
bottom, the answer scrolls above it with how the question was understood, and the resulting
plan can be edited and rerun. Filters are chosen rather than typed where the registry has a
fixed list (country dropdown with trial counts, phase and status chips, year selects) and
suggested elsewhere (drug, condition, sponsor), from `GET /api/options`; active filters show as
removable chips. For a single trial it shows the trial used, with links, and lets the user
switch to another trial the name matched. Tabs above each chart switch between the answer's
views (e.g. Bars / Map / Donut). Refusals and "no posted results" appear as neutral notices, not
errors, and replace the previous chart.

Rendering knows nothing about questions: it maps `type` + `encoding` to Vega-Lite (bars with
optional error bars, stacked bars, heatmaps, maps, donuts, lines, forest plots, time series,
histograms, scatter) or Cytoscape (networks), and shows the
citations of whatever datum is clicked. That it renders every chart kind from the spec alone is
the evidence that the spec is renderable without guessing. Using it found two issues: one in
the renderer (pre-binned histograms need `bin: {binned: true}` in Vega-Lite) and one in the
spec (a country typed as "korea" filtered correctly, but the title did not show it, so the
chart looked unfiltered; titles now name shared filters).

### Monorepo and Docker

One repository, two folders (`backend/`, `frontend/`) and a `docker-compose.yml`; with a single
JS package, monorepo tooling (Nx, Turborepo) would add nothing. Docker makes the review a single
command and needs neither uv nor Node on the reviewer's machine.

### Python 3.14

The project targets Python ≥ 3.14 (lazy annotations by default; 3.12 is security-fix-only).
uv provisions the interpreter locally and the Docker image is `python:3.14-slim`.

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
- The cache lives in one process; it is lost on restart and not shared between API replicas.
  A Redis-backed `TrialSource` decorator would remove both limits.
- An uncached question over a large cohort takes a few seconds (pages of 1,000 studies are
  fetched sequentially, as the API's page tokens require).
- The demo bundle is 1.5 MB (Vega dominates); it is not code-split.
- Grounding proves a filter was stated, not that it was mapped correctly: a quoted "late-stage"
  mapped to `PHASE3` passes. `meta.interpretation` and the editable plan are the mitigation.
- Planning adds ~1.5–2 s per question; answers are not cached by question (data fetches are).
- One question at a time: no follow-up questions that refer to a previous answer.
- The evaluation covers English questions; other languages are untested.
- A trial name matching several trials with results is resolved to the largest; it is a rule,
  not knowledge of which is the "main" trial, so the alternatives are always shown.
- Alternative views repeat their rows' citations, so responses grow by about half to two
  thirds (grouped bars 59 KB, of which 39 KB alternatives; a melanoma sponsor–drug network
  428 KB, of which 205 KB). With more time: views would reference the primary's rows.
- The map shows the countries of the bar chart (the top 15 by default), not every country.
- Single-trial charts show one value scale (the first selected outcome's measure and unit; the
  rest is listed in notes) and the 15 most frequent adverse events; results are not compared
  across trials.

_To be completed as the remaining steps land._

## Example runs

_Planned (step 5):_ 3–5 queries with the actual JSON produced by the service.

## AI tool usage and validation

_To be completed by the author._ So far:

- **Tools:** Claude Code (Claude Opus 5.5) as a pair programmer for API exploration, code and tests.
- **Validation:** the OpenAPI spec (`docs/ctgov-openapi-v2.0.5.yaml`) was read and parameter
  behaviour probed against the live API before coding; offline tests use recorded API pages
  (`backend/tests/fixtures/ctgov/`); `pytest -m live` re-checks the contract (1,000 real studies map
  without errors; synonym and exact filters hold on returned trials).
- **Aggregation cross-check:** our phase counts for all 2,974 pembrolizumab trials equal, for
  every phase, the API's own `countTotal` for the same query filtered to that phase
  (`backend/tests/application/test_live_cross_check.py`).
- **Real-data smoke runs** of every plan kind (phase distribution, time series, drug A vs B,
  countries, phase × sponsor class, drug and sponsor–drug networks, histogram, scatter) were
  inspected before writing the unit tests; they surfaced the anticipated future start dates and
  the country-variant behaviour listed above.
- **End to end in a browser:** every example in the demo was run against the live API through
  the React UI, including clicking data to inspect citations; this is how the histogram
  rendering bug and the cramped network layout were found and fixed.
- **Planner evaluation:** `pytest -m llm` runs 17 cases against the real model and asserts the
  plan kind, its parameters and the exact filters (so an added filter fails), plus refusals;
  results per model are in [AI design](#ai-design-grounding-the-planner-in-the-question).
  Offline tests cover grounding rules, the correction round, the OpenAI adapter (request shape and
  parsing, via a mocked transport) and every `/api/visualize` status code.
- **Docker:** `docker compose up --build` was run; the API container reports healthy, runs as a
  non-root user, and serves plans through the nginx proxy.

## Progress

| Step | Scope | Status |
|---|---|---|
| 1 | Project setup, ClinicalTrials.gov adapter (ACL, query params, pagination, retries) | done |
| 2 | AnalysisPlan grammar, aggregation with citations, chart builders, `run_plan` use case | done |
| 2b | Monorepo, `POST /api/plans`, React renderer, cache, Docker Compose | done |
| 3 | LLM planner with grounding, `POST /api/visualize`, planner evaluation, question box in the UI | done |
| 4 | Example runs, README completion | next |

### Project structure

```
backend/
  src/cheiron/
    domain/                        standard library only
      trial.py, trial_filter.py      Trial, enums, TrialFilter
      analysis.py                    AnalysisPlan grammar: CountBy, CoOccurrence, Distribution, Correlation
      facets.py                      a Trial's values per dimension/entity/measure, with evidence
      charts/                        one builder per plan kind → Visualization
      visualization.py               output spec: chart types, channels, citations
      charts/views.py                alternative views derived from a primary chart's rows
      geography.py, country_codes.json   registry country names -> ISO 3166-1 numeric codes
      results.py                     a trial's posted outcome measures and adverse events
    application/
      ports.py                       TrialSource port, TrialSearchResult
      run_plan.py                    use case: fetch cohorts concurrently, build, report truncation
      planning.py                    PlanDraft (LLM contract), Question, grounding rules
      options.py                     filter choices from the registry vocabulary, cached
      trial_lookup.py                which trial a name refers to (rules and alternatives)
      visualize.py                   use case: plan with one correction round, then run_plan
    adapters/
      inbound/http/                  FastAPI routes and Pydantic schemas
      outbound/openai_planner.py     QueryPlanner on OpenAI structured outputs, planner instructions
      outbound/ctgov/                ClinicalTrials.gov client, query params, ACL mappers (studies, results)
      outbound/caching.py            TrialSource decorator keyed to the data snapshot
    main.py                        composition root
  tests/                           unit, HTTP, cache and planner tests; recorded fixtures;
                                   live API checks (-m live); planner evaluation (-m llm)
  Dockerfile
frontend/                          React + TypeScript (Vite): generic spec renderer
  src/charts/toVegaLite.ts         spec → Vega-Lite (map shapes from world-atlas, bundled)
  src/components/                  chart, network, citations, meta
  Dockerfile, nginx.conf           static build behind nginx, /api proxied to the API
docker-compose.yml
docs/                              API spec (v2.0.5), Korean domain glossary
```
