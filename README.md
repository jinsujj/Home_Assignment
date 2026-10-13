# Cheiron — ClinicalTrials.gov Query-to-Visualization Agent

English | [한국어](README.ko.md)

A backend service that turns a natural-language question about clinical trials into a
structured, frontend-renderable visualization specification, backed by the
[ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api).

> **Status:** questions are answered end to end (`POST /api/visualize`: LLM plan → grounding
> → ClinicalTrials.gov → visualization spec), structured plans run directly (`POST /api/plans`),
> and a React demo renders both. [Example runs](#example-runs) show five questions with the
> service's actual responses.

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
| `OPENAI_API_KEY` | for `/api/visualize`, `/api/mentions` | the LLM planner and mention judge; `/api/plans` works without it |
| `OPENAI_MODEL` | no | planner model, default `gpt-5.4-mini` |
| `OPENAI_REASONING_EFFORT` | no | default `low`; set empty for non-reasoning models such as `gpt-4.1-mini` |
| `OPENAI_MENTION_REASONING_EFFORT` | no | the same for the mention judge, default `high` |

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
uv run --env-file ../.env pytest -m llm   # planner (21 cases) and mention judge (13) against the real model
cd ../frontend && npm run build && npm run lint   # type-check, build, lint
```

## Request / response schema

| Endpoint | Purpose |
|---|---|
| `POST /api/visualize` | Question (+ optional structured fields) → plan → visualization. |
| `POST /api/plans` | Run a structured analysis plan directly, without the LLM. |
| `GET /api/options` | Choices for building filters: every registry country (exact spelling, trial count), common conditions/interventions/sponsors as suggestions, phase and status codes. Cached 6 h. |
| `GET /api/version` | `{"data_version": "2026-10-09T09:00:05"}`: the registry data snapshot being served (ClinicalTrials.gov's `/version` `dataTimestamp`, checked at most every 10 minutes). |
| `POST /api/mentions` | `{"nct_ids": [...], "names": [...]}` → what the named entity is to each trial (studied, given alongside, eligibility, background, unclear), judged by the LLM and quoting the record. See [Why a trial mentions a term](#ai-design-why-a-trial-mentions-a-term). |
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
| `all_citation_ids` | boolean | default `false`; list every contributing NCT ID per datum in `citations.nct_ids` |

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
| `plan.link` | `same_trial` \| `same_arm` \| `different_arms` | `co_occurrence` drug ↔ drug only, default `same_trial`; `same_arm` = combinations, `different_arms` = comparisons |
| `filter.condition`, `.intervention`, `.sponsor` | string ≤ 200 | optional free text; synonyms resolved by ClinicalTrials.gov |
| `filter.country` | string ≤ 100 | optional; common variants resolved (`USA`, `UK`) |
| `filter.phases`, `.statuses` | list of registry codes (`PHASE3`, `RECRUITING`, …) | optional; any of |
| `filter.study_type` | `INTERVENTIONAL` \| `OBSERVATIONAL` \| `EXPANDED_ACCESS` | optional |
| `filter.start_year_from`, `.start_year_to` | integer 1900–2100 | optional; from ≤ to |
| `max_trials_per_cohort` | integer 1–10,000 | default 5,000; larger result sets are truncated and flagged |
| `all_citation_ids` | boolean | default `false`; list every contributing NCT ID per datum in `citations.nct_ids` |

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
    "cohorts": [ { "label": "Pembrolizumab", "matched": 2974, "analyzed": 2974, "truncated": false,
                   "exact_counts": false,   // see "Exact counts beyond the cap"
                   "names": ["pembrolizumab", "Pembrolizumab"] }, ... ],   // filter terms as registered
    "notes": [ "175 of 2974 trials in Pembrolizumab have no registered phase and are not shown.", ... ],
    "data_version": "2026-10-09T09:00:05",  // the registry snapshot the answer was computed from
    "note_citations": [ { "note": "175 of 2974 trials ... have no registered phase ...",   // notes that count
                          "citations": { "total": 175, "items": [ ... ] } } ]           // trials, with them
  }
}
```

### Visualization spec (implemented)

`encoding` maps visual channels to data fields. Every channel is
`{ field, type, title, order, unit, time_unit, scale }`, where `type` is one of `nominal`, `ordinal`,
`quantitative`, `temporal` (Vega-Lite's measurement types), `order`, when present, is the
category order to render, and `scale` is `null` (linear) or `"symlog"` (log-like, keeping zeros).

| `type` | Channels | Data |
|---|---|---|
| `bar_chart` | `x` (category), `y` | one row per category |
| `grouped_bar_chart` | `x`, `y`, `series` | one row per category × series, zeros included |
| `time_series` | `x` (temporal, `time_unit: "year"`), `y`, optional `series` | one row per year, gaps filled with 0 |
| `histogram` | `x` (`bin_start`), `x2` (`bin_end`), `y` | one row per bin; bins are `[bin_start, bin_end)`; the last bin may be open (`bin_end: null`) |
| `scatter_plot` | `x`, `y`, `tooltip` | one row per trial (`nct_id`, `title`, both measures); an axis whose largest value is at least 10 times its median gets `scale: "symlog"`; `notes` state Spearman's rank correlation in words |
| `network_graph` | `node_id`, `node_label`, `node_size`, `node_color` (cluster), `node_shape` (entity kind), `node_category` (sponsor class, sponsor networks), `edge_source`, `edge_target`, `edge_weight` (shared trials), `edge_strength` (association), `edge_style` (how they meet) | `{ "nodes": [...], "edges": [...] }`; nodes carry `community` (cluster name or null), `anchor` (bool), `partners` (linked nodes) and, for sponsors, `sponsor_class`; edges carry `association` (Jaccard, 0–1), and `relation` with its counts: drug ↔ drug `combined_trials` / `compared_trials` (`combined`, `compared`, `unknown`), sponsor ↔ X `lead_trials` / `collaborator_trials` (`lead`, `collaborator`) |

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

Every row, node and edge carries `citations` (here the "Phase 3" bar for pembrolizumab):

```json
{ "phase": "Phase 3", "trial_count": 369,
  "citations": {
    "total": 369,
    "items": [
      { "nct_id": "NCT04003636",
        "title": "Pembrolizumab (MK-3475) Plus Gemcitabine/Cisplatin ... (KEYNOTE-966)",
        "url": "https://clinicaltrials.gov/study/NCT04003636",
        "evidence": [ { "field": "protocolSection.designModule.phases", "value": "PHASE3" },
                      { "field": "protocolSection.armsInterventionsModule.interventions.name",
                        "value": "Pembrolizumab" },
                      { "field": "protocolSection.identificationModule.briefTitle",
                        "value": "Pembrolizumab (MK-3475) Plus Gemcitabine/Cisplatin Versus Placebo ..." } ],
        "excerpt": "phases: PHASE3; interventions.name: Pembrolizumab; briefTitle: Pembrolizumab (MK-3475) ...",
        "mentioned_only": [] }
    ],
    "nct_ids": null,
    "registry_query": null } }
```

`total` is the number of trials behind the datum that the citations cover; `items` spells out the
first few (default 5). For a count made by the registry (see "Exact counts beyond the cap"),
`total` covers the analyzed trials and `registry_query` is a ClinicalTrials.gov API request whose
`totalCount` is the bar's `trial_count` and whose pages list those trials; with
`all_citation_ids`, `nct_ids` lists them all and `total` equals `trial_count`.
`evidence` names the field of the API's study JSON and the value exactly as registered that put
the trial into this datum (two entries for an edge, one per endpoint; value and interval limits
for a posted result), followed by why the trial is in the cohort: the registered value matching
the cohort's filter and the passage of the trial's own text that names it (see below); `excerpt`
is the same evidence as one line of text, the shape the assignment's example uses
(`citations[].{nct_id, excerpt}`). `nct_ids` lists every
contributing trial when the request sets `all_citation_ids`, and is `null` otherwise.
`notes` lists assumptions and caveats in plain sentences (multi-valued counting, missing
values, top-N cut-offs, binning); a note that counts trials ("1069 of 5000 trials have no
registered phase", "309 … have an estimated start date", "335 … mention 'pembrolizumab'", trials
in two compared cohorts, trials without a measure) also appears in `meta.note_citations` with
those trials, cited like a datum. Alternative views cite the same trials as the rows they redraw,
so they refer to the primary chart's citations with a JSON reference instead of repeating them:
`"citations": {"$ref": "#/visualization/data/3/citations"}` (or `.../data/edges/12/citations`).

**Why a trial is in its cohort.** ClinicalTrials.gov's searches for an intervention, condition or
sponsor also match other text, such as descriptions: 335 of the 2,974 trials found for
pembrolizumab do not register it as an intervention (e.g. a fecal-transplant study), and 1,195 of
the first 5,000 lung cancer trials do not register lung cancer as a condition. For each free-text
filter the service asks the registry which trials only mention the term (`NOT AREA[...]` over
the registered fields; the registry's synonyms count as registered: "Keytruda", "MK-3475" and
"pembrolizumab" give the same 2,639). Other trials get the matching registered value as evidence
(the one sharing most words with the term, else the cohort's most common one, so "Keytruda"
cites "Pembrolizumab"); trials that only mention it list the term in `mentioned_only`, are cited
last, and `meta.notes` says how many there are. A live test checks, for every phase 3
pembrolizumab trial, that the registry's verdict agrees with the registered drug names. This
costs one request per free-text filter, plus one per 1,000 such trials. For conditions the
verdict over-flags: a narrower registered name ("Lung Adenocarcinoma", "NSCLC Stage IV") does not
match "lung cancer", so some flagged trials do study it; the LLM check below tells them apart.

**The text that names it.** Each cited trial (the spelled-out `items`, not all contributing
trials) also quotes the passage of its own text that names the filtered entity, by its filter
term or registered name: from the title, official title, summary, arm and intervention
descriptions, detailed description, keywords or eligibility criteria, in that order, as titles
and summaries describe the trial while eligibility criteria often name other treatments. A
passage is the sentence or line around the name, at most 240 characters, cut at word
boundaries, and always an exact substring of the record. Sentences end at ". " before a capital
or at a line break, so "e.g. pembrolizumab", "etc." and "2.5 mg" do not end one; both mistakes
showed up on real records ("g pembrolizumab)") before that rule. The texts of all cited trials
come in one request per 200 (`filter.ids`); without them, citations keep the registered values.

Measured for pembrolizumab, a default phase chart is 32 KB, Keytruda vs Opdivo 53 KB and the drug
network 804 KB; before alternative views referred to the primary's citations, they were 54, 123
and 2,081 KB. Responses are gzipped for clients that accept it (browsers do): 5 KB, 7 KB and
65 KB. Full NCT ID lists are opt-in: with `all_citation_ids` the same answers are 85, 148 and
915 KB (21, 37 and 99 KB gzipped).

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
| `gpt-5.4-mini`, reasoning `low` (default) | 17/17 twice on the first suite; 21/21 three times on the current one | ~1.5–2.2 s |
| `gpt-4.1-mini` | 16/17 on the first suite (Keytruda vs Opdivo failed once, passed 3/3 on rerun) | ~1.8–4.8 s |

### AI design: why a trial mentions a term

That a trial only mentions a drug does not say why: the 335 pembrolizumab "mentions" include a
fecal-transplant study given alongside standard pembrolizumab, trials requiring prior
pembrolizumab, and studies whose patients receive it as usual care. Telling these apart needs
reading, so `POST /api/mentions` (the "Ask AI" button of the demo's citation panel) gives the
LLM, per trial, its title and every passage naming the entity (at most 6), and asks for one
role: `studied`, `given_alongside`, `eligibility`, `background` or `unclear`, defined for drugs,
conditions and organisations.

The grounding rule of the planner applies: each verdict must quote the title or a passage, and
`application/mentions.py` keeps it only if the quote (at least three words, ignoring spacing,
case and markdown escapes) is found there; the response carries that passage verbatim, and an
unfound quote turns the role into `unclear`. It runs on demand for the cited trials of one datum
(at most 10 per request), never for whole cohorts or chart numbers, and verdicts are cached per
trial and passages (`CachingMentionJudge`).

Evaluation (`tests/llm/test_mention_eval.py`, 13 records read by hand: 8 for pembrolizumab,
5 for breast or lung cancer, including trials that register "Lung Adenocarcinoma" and are
flagged as mention-only). Building it found three bugs in our own code, not the model's: the
sentence cutter stopped at "e.g." ("g pembrolizumab)"), the verifier rejected quotes that copied
the section label shown before a passage or quoted the title, and the role definitions only
fitted drugs, so every breast cancer trial came back `background`. After fixing them, with
`gpt-5.4-mini`, three runs each:

| Reasoning effort | Right | 13 trials in |
|---|---|---|
| `low` | 13, 12, 12 of 13 | 11–13 s |
| `high` (default, `OPENAI_MENTION_REASONING_EFFORT`) | 12, 11, 12 of 13 | 35–93 s |

Higher effort did not help: the misses are borderline readings (an observational study of
patients "scheduled to receive" the drug), and it quoted titles and labels more often. `high`
is the configured default by choice; `low` is as accurate here and several times faster.

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
| `CoOccurrence` | `source`, `target` entity, `link` | `network_graph` | "Network of sponsors ↔ drugs for breast cancer.", "Which drugs are combined with pembrolizumab?" (`link = same_arm`) |
| `Distribution` | `measure` | `histogram` | "How large are pembrolizumab trials?" |
| `Correlation` | `x`, `y` measures | `scatter_plot` | "Do longer trials enrol more patients?" |
| `TrialResults` | `trial` (NCT ID or name), `focus`, optional `outcome` | `grouped_bar_chart` with intervals | "What were the results of KEYNOTE-189?", "Side effects in CheckMate 227?" |

Dimensions: phase, status, study type, start year, country, condition, intervention,
intervention type, lead sponsor, lead sponsor class. Entities: drug, sponsor, condition,
country, investigator, site. Measures: enrollment, duration (months), start year. A cohort is a label plus a
`TrialFilter`, so "Drug A vs Drug B" is two cohorts of the same `CountBy`.

Adding a question class means adding an enum member and how to read it from a `Trial`
(`domain/facets.py`), not a new pipeline.

### Networks with structure, not just counts

Raw co-occurrence counts mostly restate frequency, and above all the entity the question
filtered on: pembrolizumab is in 67% of pembrolizumab trials and links to almost every drug.
Each network therefore makes three things explicit (`domain/charts/co_occurrence.py`):

- **Anchors**: the filtered entity, or any entity in more than half of the analyzed trials, is
  marked and left out of clustering, since it links to most nodes by construction.
- **Clusters**: greedy modularity maximisation (Clauset–Newman–Moore) on shared-trial counts
  among the other displayed nodes, implemented in `domain/charts/communities.py` (pure Python,
  deterministic tie-breaking; at most 200 nodes). Each cluster is named after its most frequent
  member. On real data the clusters are recognisable treatment patterns:
  - pembrolizumab's partners: platinum/taxane chemotherapy (carboplatin, pemetrexed,
    paclitaxel, …), GI regimens (oxaliplatin, leucovorin, 5-FU, irinotecan, …), other
    checkpoint inhibitors (nivolumab, ipilimumab, atezolizumab, durvalumab) and
    lymphodepletion for cell therapy (cyclophosphamide, fludarabine);
  - breast cancer: chemotherapy with HER2 agents, endocrine therapy with CDK4/6 inhibitors,
    and metastatic/triple-negative chemotherapy;
  - pancreatic cancer: gemcitabine/nab-paclitaxel and FOLFIRINOX components.
  Without anchors, pembrolizumab was merged into the chemotherapy cluster.
- **Association**: each link's Jaccard index (shared trials / trials with either). It ranks
  regimens above merely frequent pairs: in pembrolizumab's network the most frequent link,
  pembrolizumab + carboplatin (256 trials), scores 0.13, while leucovorin + oxaliplatin
  (28 trials, 0.43) and carboplatin + paclitaxel (135 trials, 0.40) score highest.

- **How they meet**: two drugs on the same trial may be given together or compared against
  each other, and a sponsor may run a trial or only support it. Arms say which: 2,821 of the 2,974
  pembrolizumab trials list the drugs of each arm (`ArmGroupInterventionName`, "Drug: Name").
  Carboplatin + pemetrexed share an arm in 117 of their 118 trials, while docetaxel +
  pembrolizumab are only in different arms in 35 of 75 (pembrolizumab vs docetaxel) and
  nivolumab + pembrolizumab in 41 of 104. Drug links therefore carry `combined_trials` and
  `compared_trials`, their citations quote the arms ("Experimental: Pembrolizumab + Carboplatin",
  "Drug: Carboplatin"), clusters follow combinations, and `link` makes a network of combinations
  only (`same_arm`, "Drug combination network") or comparisons only (`different_arms`); the
  planner picks it from the wording ("combined with", "versus"). Of pembrolizumab's 120 shown
  links, 105 are mostly combined and 15 mostly compared. Sponsors are counted per role: in
  melanoma, Merck ↔ pembrolizumab is 86 trials, Merck leading 26 and collaborating on 60 (others
  run them, Merck supports); BMS ↔ nivolumab 27 and 51; sponsor nodes carry their class
  (industry, NIH, other). Arm fields add 17% to a page of studies (1.92 → 2.25 MB per 1,000).

The demo colours nodes by cluster, shapes them by entity kind, draws anchors dark, scales link
width by shared trials and opacity by association, and adds a legend. Links are solid where drugs
are combined or the sponsor leads, dashed where they are compared or the sponsor collaborates,
dotted where the arms do not say; sponsor nodes get a border in their class's colour. It also disables wheel
zoom on the graph: a full-width graph captured page scrolling, so the legend and citations below
it could not be reached.

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
| `scatter_plot` | `bar_chart` (median y per fifth of the trials by x) | answers "does y rise with x?" directly, unmoved by a few huge trials |

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

### Answering a repeated question without the LLM

Measured on "Which drugs are combined with pembrolizumab?": the first answer took 9.3 s, and
each repeat 2.3 s, of which 1.4–3.2 s was the planner while the data came from cache in 0.2 s.
Two caches remove that:

- `CachingPlanner` (a `QueryPlanner` decorator) keeps drafts keyed by everything the model
  sees: the question (ignoring case, spacing and a trailing "?"), the structured fields, the
  correction feedback, and today's date (which resolves "in the last 5 years"). A repeat now
  takes 0.22 s, and identical questions get identical plans.
- The demo keeps this session's answers (like a chat assistant): a "Recent" list shows them,
  asking a known question again reuses its answer, and a reload restores the last one. They
  live in `sessionStorage`. Each answer carries the snapshot it was computed from
  (`meta.data_version`, shown above the chart); before a stored answer is shown, the demo asks
  `GET /api/version` (a few milliseconds, as the service caches it) and asks the question
  again if the service now serves newer data.

A reworded question still costs one planner call (~2 s).

### Aggregating on our side, with a cap

The API's `/stats/field/values` endpoint only reports statistics over *all* studies and accepts
no search filter (verified in the spec), so filtered aggregations must be computed by the
service. `CtGovTrialSource` fetches only the fields the analyses need (1,000 studies ≈ 1.9 MB,
≈ 1.3 s per page) up to a cap (default 5,000 per cohort, at most 10,000), and reports
`total_count` alongside the analyzed trials so responses say when a result is truncated. The
default was raised from 2,000 after a pembrolizumab chart (2,974 trials) showed Phase 1 at
699 instead of 1,046: flagged, but misleading in absolute terms.

### Exact counts beyond the cap

A truncated cohort used to be charted from its first 5,000 trials: breast cancer (16,899 trials)
showed Phase 2 at 1,362 instead of 4,590. For a `count_by` without a split over phase, status,
study type, lead sponsor class or intervention type, `run_plan` now asks the registry how many
of *all* matching trials register each category the analyzed trials show (one `countTotal`
request each, the category added to the cohort's own criteria as an Essie `AREA[...]` clause).
Bars show those counts, citations still spell out analyzed trials, `meta.cohorts[]` says
`exact_counts: true`, and each bar's `citations.registry_query` reproduces its count: for breast
cancer, requesting it returns `totalCount` 4,590 for Phase 2, the bar's value. With
`all_citation_ids`, every trial behind each count is listed (one request per 1,000; breast
cancer's six phases list 14,200 trials in about 30 s; above 20,000 a note says so and
`registry_query` remains the way to them). Before relying on it, the registry's count of every category (38
over five dimensions) was compared with our own aggregation for all 4,269 Alzheimer's disease
trials: all equal. A live test repeats the comparison on a smaller cohort (melanoma trials in
South Korea).

The cost is set by the API's rate limit, which the spec does not state. Measured: a burst of
about 10 requests is served at once, then about one per second (exactly 10 successes per 10 s
window); 61 parallel requests got 53 `429`s. Counts are therefore requested one at a time,
at most 20 per answer (`MAX_COUNT_REQUESTS`), and cached like searches. Measured with the
searches cached: 6 counts take 1.2 s, 11 take 12 s.

Start years (about 50 categories), countries and other many-valued dimensions would need too
many such requests, yet they are what the appendix's time trends and geography ask about, and
the sample was badly off in absolute terms. Measured against the registry's own year and
country searches: the first 5,000 breast cancer trials hold a steady 28–31% of each year's starts
(2025: 317 shown, 1,090 real), and the first 5,000 of 18,769 recruiting cancer trials 26–28% of
each country's (United States: 1,823 shown, 6,939 real; South Korea ranked 8th instead of 10th).
The shape survived, the numbers did not. So when per-category counting is not possible
(a dimension the registry cannot count, or more than 20 categories), every matching trial is
tallied instead: pages of 1,000 with only the fields the dimension needs (~250 KB per page for
start dates, ~470 KB for countries, against ~2.2 MB for full records), counted with the same
domain facets as the chart, up to 25,000 trials per answer (`MAX_TALLY_TRIALS`). A tally also
finds categories the analyzed trials missed and lists every trial behind each bar; years and
countries carry a `registry_query`, which a live test checks against the registry's
`AREA[StartDate]RANGE[...]` search. Breast cancer's years and recruiting cancer's countries now
equal the registry's numbers exactly (2025: 1,090; United States: 6,939, South Korea 10th), in
24 s and 28 s the first time and 0.1 s from cache. Beyond 25,000 trials, or when counting fails,
the analyzed trials are charted with the usual note; networks, distributions, scatters and
split bars stay on the analyzed trials.

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
| Non-drug items are registered as interventions (e.g. "Laboratory Biomarker Analysis", type `OTHER`). | Drug networks use `DRUG` / `BIOLOGICAL` interventions only. |
| Country filters resolve variants (`USA`, `UK`, `Korea, Republic of` match `United States`, `United Kingdom`, `South Korea`); stored values use one spelling (226 distinct). | No country normalisation needed for filtering; charts show the stored spelling. |
| Not-yet-started trials carry anticipated start dates, including future years (`startDateStruct.type: ESTIMATED`; 309 of 2,969 dated pembrolizumab trials). | Start and completion dates are cited with their registered type; time series say how many counted trials have an estimated start, in a note that cites them. |
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
views (e.g. Bars / Map / Donut). Notes that count trials have a "show trials" link that lists
them in the citation panel, and registry counts link to the API request that reproduces them. Refusals and "no posted results" appear as neutral notices, not
errors, and replace the previous chart.

Rendering knows nothing about questions: it maps `type` + `encoding` to Vega-Lite (bars with
optional error bars, stacked bars, heatmaps, maps, donuts, lines, forest plots, time series,
histograms, scatter) or Cytoscape (networks), and shows the
citations of whatever datum is clicked. That it renders every chart kind from the spec alone is
the evidence that the spec is renderable without guessing. Using it found two issues: one in
the renderer (pre-binned histograms need `bin: {binned: true}` in Vega-Lite) and one in the
spec (a country typed as "korea" filtered correctly, but the title did not show it, so the
chart looked unfiltered; titles now name shared filters).

Browser page translation replaces text nodes with its own elements, so React then fails to
insert or remove next to them ("Failed to execute 'insertBefore' on 'Node'") and drops the whole
page. A script that mimics it (every text node wrapped in `<font>`, new text translated as it
appears) crashed the demo on the first question. Text that changes or sits beside conditional
content is now its own element holding a single string, which React replaces whole; the same
script then ran 13 interactions (asking, switching views, selecting data, filters, Recent, the
AI check) without an error, and changed text such as the interpretation updates.

### Monorepo and Docker

One repository, two folders (`backend/`, `frontend/`) and a `docker-compose.yml`; with a single
JS package, monorepo tooling (Nx, Turborepo) would add nothing. Docker makes the review a single
command and needs neither uv nor Node on the reviewer's machine.

### Python 3.14

The project targets Python ≥ 3.14 (lazy annotations by default; 3.12 is security-fix-only).
uv provisions the interpreter locally and the Docker image is `python:3.14-slim`.

## Limitations and future improvements

- Results above the fetch cap are analyzed on the first N studies the API returns (unsorted);
  `meta` flags this. Counts by one dimension are completed from the registry up to 25,000
  matching trials (see above); networks, histograms, scatters and split bars are not, and a
  first question over a large cohort takes 20–30 s while it is tallied.
- Free-text criteria rely on ClinicalTrials.gov's search, which also matches mentions in
  descriptions (11% of pembrolizumab trials, 24% of the first 5,000 lung cancer trials). Such
  trials are counted, as the registry defines the cohort, but flagged in their citations and
  counted in `meta.notes`. With more time: an option to count registered trials only.
- Rate limits are not documented in the API spec (measured: a burst of ~10, then ~1 request
  per second). The client retries `429` with backoff but does not throttle proactively, so a
  first question over two large cohorts takes ~30 s (10 pages plus 16 counts).
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
- Planning adds ~1.5–2 s to a question asked for the first time; identical questions reuse their
  plan (see above), reworded ones are planned again.
- One question at a time: no follow-up questions that refer to a previous answer.
- The evaluation covers English questions; other languages are untested.
- A trial name matching several trials with results is resolved to the largest; it is a rule,
  not knowledge of which is the "main" trial, so the alternatives are always shown.
- Large networks remain the largest answers (804 KB for pembrolizumab's drug network, 65 KB
  gzipped), mostly per-link citations with their passages.
- Mention roles are an LLM's reading of up to six passages and the title; on borderline records
  (patients "scheduled to receive" a drug in an observational study) runs disagree. The quote
  shown with each role lets the reader check it.
- The map shows the countries of the bar chart (the top 15 by default), not every country.
- Clusters are computed on the displayed subgraph (top 30 nodes by default) and modularity is
  modest (Q ≈ 0.2 on the examples): clusters are tendencies, not hard partitions. Name variants
  ("Fluorouracil", "5-fluorouracil") remain separate nodes and may land in one cluster.
- Arms are read structurally: an arm offering alternatives ("pembrolizumab or nivolumab") counts
  as a combination, which is likely part of nivolumab + pembrolizumab's 63 "combined" trials.
  Sponsor roles are split for sponsor ↔ other networks, not between two sponsors.
- Single-trial charts show one value scale (the first selected outcome's measure and unit; the
  rest is listed in notes) and the 15 most frequent adverse events; results are not compared
  across trials.

_To be completed as the remaining steps land._

## Example runs

Five questions sent to `POST /api/visualize` on 2026-10-13 (registry snapshot
`2026-10-09T09:00:05`, planner `gpt-5.4-mini`). Every response is saved in full, minified, in
[`docs/examples/`](docs/examples/); below are each run's plan, its results and the part of its JSON
that shows what the run is about. Filters left empty are omitted from plans, and long lists and
titles are cut (`...`). With Docker running, each can be repeated:

```bash
curl -s localhost:8080/api/visualize -H 'content-type: application/json' \
  -d '{"query": "Which countries have the most recruiting trials for cancer?"}'
```

| # | Question | Appendix type | Chart | What it shows |
|---|---|---|---|---|
| 1 | How has the number of trials for pembrolizumab changed per year since 2015? | Time trends | `time_series` | A year filter; provisional start dates |
| 2 | Compare phases for trials involving Keytruda vs Opdivo. | Comparisons, distributions | `grouped_bar_chart` | Brand names; two cohorts; views that cite by reference |
| 3 | Which countries have the most recruiting trials for cancer? | Geographic | `bar_chart` | Exact counts for 18,769 trials, each reproducible |
| 4 | Which drugs are combined with pembrolizumab? | Networks | `network_graph` | Combinations read from trial arms |
| 5 | What were the results of the KEYNOTE-189 trial? | (a single trial) | `grouped_bar_chart` with error bars | Posted results; choosing among trials of that name |

### 1. Time trend: pembrolizumab trials per year since 2015

"Since 2015" became a filter rather than a cut of the chart, so the cohort is the 2,909 trials
that started in 2015 or later, all of them analyzed:

```json
{ "kind": "count_by", "dimension": "start_year",
  "cohorts": [ { "label": "Pembrolizumab",
                 "filter": { "intervention": "pembrolizumab", "start_year_from": 2015 } } ] }
```

Trials per year, 2015 to 2027: 120, 195, 260, 255, 248, 263, 265, **299** (2022), 259, 256, 259,
223, 7. The last two years are partly plans, and the response says so: "309 of 2,909 counted
trials have an estimated start date (...), so the years they fall in are provisional", with those
309 trials in `meta.note_citations`. Each year cites its trials with the registered start date and
its type, then why the trial is in the cohort:

```json
{ "start_year": 2026, "trial_count": 223,
  "citations": { "total": 223, "items": [
    { "nct_id": "NCT07465276",
      "title": "Neoadjuvant Ficerafusp Alfa With Pembrolizumab in Resectable SCC",
      "url": "https://clinicaltrials.gov/study/NCT07465276",
      "evidence": [
        { "field": "protocolSection.statusModule.startDateStruct.date", "value": "2026-03-26" },
        { "field": "protocolSection.statusModule.startDateStruct.type", "value": "ACTUAL" },
        { "field": "protocolSection.armsInterventionsModule.interventions.name", "value": "Pembrolizumab" },
        { "field": "protocolSection.identificationModule.briefTitle", "value": "Neoadjuvant Ficerafusp Alfa With ..." } ],
      "excerpt": "startDateStruct.date: 2026-03-26; startDateStruct.type: ACTUAL; interventions.name: Pembrolizumab; ...",
      "mentioned_only": [] },
    "..." ],
    "nct_ids": null, "registry_query": null } }
```

Another note counts the 329 trials that only mention pembrolizumab in their text without
registering it as an intervention; their citations list it under `mentioned_only`.

### 2. Comparison: Keytruda vs Opdivo by phase

The brand names went into the filters as typed. The registry's search matches them to the
drugs, and `meta.cohorts[].names` reports what the trials call them: `["Keytruda",
"Pembrolizumab"]` and `["Opdivo", "Nivolumab"]`, for 2,974 and 2,030 trials.

```json
{ "kind": "count_by", "dimension": "phase",
  "cohorts": [ { "label": "Keytruda", "filter": { "intervention": "Keytruda" } },
               { "label": "Opdivo", "filter": { "intervention": "Opdivo" } } ] }
```

| Phase | Early 1 | 1 | 2 | 3 | 4 | Not applicable |
|---|---|---|---|---|---|---|
| Keytruda | 51 | 1,046 | 1,777 | 369 | 19 | 54 |
| Opdivo | 34 | 714 | 1,164 | 186 | 17 | 50 |

The notes say that 175 and 215 trials register no phase and are not shown, that a trial with
two phases (e.g. Phase 1/2) counts under each, and that 296 trials match both cohorts and count in
each. The two `alternatives`, a stacked bar of each cohort's phase mix and a heatmap,
cite the primary chart's rows by reference instead of repeating them:

```json
{ "phase": "Early Phase 1", "cohort": "Keytruda", "trial_count": 51, "share": 1.5,
  "citations": { "$ref": "#/visualization/data/0/citations" } }
```

### 3. Geography: recruiting cancer trials by country

18,769 recruiting trials match, more than the 5,000 analyzed. Because the question counts by one
dimension, every matching trial was tallied from light pages (see
[Exact counts beyond the cap](#exact-counts-beyond-the-cap); about 28 s with an empty cache):

```json
{ "kind": "count_by", "dimension": "country", "top_n": 10,
  "cohorts": [ { "label": "cancer", "filter": { "condition": "cancer", "statuses": ["RECRUITING"] } } ] }
```

United States 6,939, China 5,769, France 1,628, Italy 1,430, Spain 1,104, Canada 1,020,
Germany 934, United Kingdom 878, Australia 851, South Korea 832: the top 10 of 133 countries.
From the first 5,000 trials alone, the United States would have shown 1,823. The note reads
"Counts cover all 18,769 matching trials for cancer, tallied from all their records; citations
and other notes cover the first 5,000 analyzed." Each bar carries the API request that
reproduces it; requesting the United States one returned `totalCount` 6,939:

```json
{ "country": "United States", "trial_count": 6939,
  "citations": { "total": 6939, "items": [
    { "nct_id": "NCT07698314", "title": "A Pilot Study Assessing Myokines During an EXErcise Regimen ...",
      "url": "https://clinicaltrials.gov/study/NCT07698314",
      "evidence": [ { "field": "protocolSection.contactsLocationsModule.locations.country", "value": "United States" } ],
      "excerpt": "locations.country: United States", "mentioned_only": [] },
    "..." ],
    "nct_ids": null,
    "registry_query": "https://clinicaltrials.gov/api/v2/studies?query.cond=cancer&filter.overallStatus=RECRUITING&filter.advanced=AREA%5BLocationCountry%5D%22United+States%22&countTotal=true&fields=NCTId%2CBriefTitle" } }
```

One limit shows here too: a note says trials that only mention "cancer" could not be told apart,
because more than 5,000 do. The alternatives are a world map and a donut of the country mix.

### 4. Network: drugs combined with pembrolizumab

"Combined with" became `link: "same_arm"`: two drugs are linked only when one arm of a trial gives
both, so a chemotherapy in the comparator arm does not count as a combination.

```json
{ "kind": "co_occurrence", "source": "drug", "target": "drug", "link": "same_arm",
  "max_nodes": 30, "min_shared_trials": 1,
  "cohort": { "label": "Pembrolizumab", "filter": { "intervention": "pembrolizumab" } } }
```

The graph keeps 29 of 2,487 drugs and the 120 strongest links. The strongest are pembrolizumab
with carboplatin (230 trials), cisplatin (160) and paclitaxel (144), then carboplatin with
paclitaxel (131) and with pemetrexed (117): the platinum doublets given alongside it. Pembrolizumab
is in 67% of the trials, so it is marked as the anchor and left out of clustering, and four
clusters remain, the largest (10 drugs) named after carboplatin. Each link cites the arm that gives both drugs:

```json
{ "source": "drug:carboplatin", "target": "drug:pembrolizumab", "trial_count": 230,
  "association": 0.113, "combined_trials": 230, "compared_trials": 0, "relation": "combined",
  "citations": { "total": 230, "items": [
    { "nct_id": "NCT06966700",
      "title": "A Clinical Study of Sacituzumab Tirumotecan (Sac-TMT, MK-2870) in People With Breast Cancer (MK-2870-032)",
      "evidence": [
        { "field": "protocolSection.armsInterventionsModule.armGroups.label", "value": "sac-TMT" },
        { "field": "protocolSection.armsInterventionsModule.armGroups.interventionNames", "value": "Drug: Carboplatin" },
        { "field": "protocolSection.armsInterventionsModule.armGroups.interventionNames", "value": "Biological: Pembrolizumab" },
        "..." ],
      "...": "..." },
    "..." ] } }
```

This is the largest response: 970 KB minified, 80 KB as sent with gzip. Every node and link
cites up to five trials with their evidence.

### 5. A single trial: KEYNOTE-189 results

The question names a trial rather than a cohort, so the plan is `{"kind": "trial_results",
"trial": "KEYNOTE-189", "focus": "outcomes"}`. Two trials with posted results carry that name.
The service charts the larger one, NCT02578680 (616 participants), and names the other
(NCT03950674, 40 participants) in a note and in `meta.trial.alternatives`.

| Primary outcome (median, months) | Pembrolizumab + pemetrexed + platinum | Control |
|---|---|---|
| Progression-free survival | 8.8 (95% CI 7.6–9.2) | 4.9 (4.7–5.5) |
| Overall survival | not estimable (posted as "NA"; no bar) | 11.3 (8.7–15.1) |

The posted analyses are notes: hazard ratio 0.52 (95% CI 0.43 to 0.64) for progression-free
survival and 0.49 (0.38 to 0.64) for overall survival, both p < 0.00001. Error bars use
`y_lower` and `y_upper`, and each value cites the posted fields it came from:

```json
"evidence": [
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.title", "value": "Progression-Free Survival (PFS) ..." },
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements.value", "value": "8.8" },
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements.lowerLimit", "value": "7.6" },
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements.upperLimit", "value": "9.2" } ]
```

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
- **Planner evaluation:** `pytest -m llm` runs 21 planner cases against the real model and asserts the
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
| 4 | Example runs | done |
| 5 | README completion (AI tool usage, by the author) | next |

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
      charts/communities.py          greedy modularity clustering for networks
      membership.py                  why a trial is in its cohort: registered values, quoted passages
      geography.py, country_codes.json   registry country names -> ISO 3166-1 numeric codes
      results.py                     a trial's posted outcome measures and adverse events
    application/
      ports.py                       TrialSource port, TrialSearchResult
      run_plan.py                    use case: fetch cohorts concurrently, build, report truncation
      planning.py                    PlanDraft (LLM contract), Question, grounding rules
      options.py                     filter choices from the registry vocabulary, cached
      trial_lookup.py                which trial a name refers to (rules and alternatives)
      visualize.py                   use case: plan with one correction round, then run_plan
      mentions.py                    use case: an LLM judges why trials mention a term, quotes verified
    adapters/
      inbound/http/                  FastAPI routes and Pydantic schemas
      outbound/openai_planner.py     QueryPlanner on OpenAI structured outputs, planner instructions
      outbound/openai_mentions.py    MentionJudge on OpenAI structured outputs
      outbound/ctgov/                ClinicalTrials.gov client, query params, ACL mappers (studies, results)
      outbound/caching.py            decorators: registry data keyed to the data snapshot; plans; verdicts
    main.py                        composition root
  tests/                           unit, HTTP, cache and planner tests; recorded fixtures;
                                   live API checks (-m live); planner evaluation (-m llm)
  Dockerfile
frontend/                          React + TypeScript (Vite): generic spec renderer
  src/charts/toVegaLite.ts         spec → Vega-Lite (map shapes from world-atlas, bundled)
  src/components/                  chart, network, citations, meta, composer, filters
  src/history.ts                   this session's answers, replayed without requests
  Dockerfile, nginx.conf           static build behind nginx, /api proxied to the API
docker-compose.yml
docs/                              API spec (v2.0.5), Korean domain glossary
```
