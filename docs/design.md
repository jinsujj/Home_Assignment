# Design notes

[README](../README.md) · English | [한국어](design.ko.md)

The README summarises the design; this file keeps the reasoning behind each decision, the
measurements it rests on, and what testing on real data changed.

## Contents

1. [Citations in depth](#citations-in-depth)
2. [The LLM plans; deterministic code computes](#the-llm-plans-deterministic-code-computes)
3. [AI design: grounding the planner in the question](#ai-design-grounding-the-planner-in-the-question)
4. [AI design: why a trial mentions a term](#ai-design-why-a-trial-mentions-a-term)
5. [AI design: an answer in words, and what to ask next](#ai-design-an-answer-in-words-and-what-to-ask-next)
6. [One grammar for every question: `AnalysisPlan`](#one-grammar-for-every-question-analysisplan)
7. [Networks with structure, not just counts](#networks-with-structure-not-just-counts)
8. [One answer, several views](#one-answer-several-views)
9. [Lightweight hexagonal architecture, selective DDD](#lightweight-hexagonal-architecture-selective-ddd)
10. [No database](#no-database)
11. [Caching keyed to the published data snapshot](#caching-keyed-to-the-published-data-snapshot)
12. [Answering a repeated question without the LLM](#answering-a-repeated-question-without-the-llm)
13. [Aggregating on our side, with a cap](#aggregating-on-our-side-with-a-cap)
14. [Exact counts beyond the cap](#exact-counts-beyond-the-cap)
15. [Handling real API data](#handling-real-api-data)
16. [Naming: `Trial` rather than `Study`](#naming-trial-rather-than-study)
17. [Two entry points: structured plans and natural language](#two-entry-points-structured-plans-and-natural-language)
18. [Frontend: a generic renderer, not a per-question UI](#frontend-a-generic-renderer-not-a-per-question-ui)
19. [Monorepo and Docker](#monorepo-and-docker)
20. [Python 3.14](#python-314)
21. [All known limitations](#all-known-limitations)

## Citations in depth

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
915 KB (21, 37 and 99 KB gzipped). The demo therefore asks for them only when the user wants
the trials beyond the five cited in full: "List the other trials" in the citation panel runs the
answer's plan again with `all_citation_ids` (served from cache in 0.05–0.3 s) and finds the same
datum by its position in the response.

## The LLM plans; deterministic code computes

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

## AI design: grounding the planner in the question

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
| `gpt-5.4-mini`, reasoning `low` (default) | 17/17 twice on the first suite; 21/21 three times; 26/26 with the follow-up cases | ~1.5–2.2 s |
| `gpt-4.1-mini` | 16/17 on the first suite (Keytruda vs Opdivo failed once, passed 3/3 on rerun) | ~1.8–4.8 s |

## AI design: why a trial mentions a term

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

## AI design: an answer in words, and what to ask next

A chart still leaves the reading to the user, and changing one filter meant retyping the
question. Three additions, all on the same rule as the planner: the LLM decides, code checks.

**Follow-ups.** `/api/visualize` takes an optional `context`: the earlier questions and the plan
that answered the last one. The planner edits that plan ("only recruiting ones", "by country
instead", "compare with lung cancer"), and grounding accepts a quote from an earlier question,
checking each question on its own so a quote cannot span two; every filter kept that way is
reported ("Kept the condition filter 'breast cancer' on the cohort from an earlier question").
The server keeps no conversation state; the client sends it. Five eval cases cover narrowing,
regrouping, comparing and a new topic that must keep nothing; the first version failed "Only
recruiting trials in the United States", planned as a new topic without the condition, until the
instructions said that a question naming only what changes refines the plan.

**An answer in words.** After the chart arrives, the client sends the same request plus its
`meta.plan` to `/api/answers`, so the chart is never delayed by it. The server runs the plan again
(from cache), lists its data as items (`c0` a cohort, `r3` a row, `n2`/`e5` a node or link, `t1` a
note), and an LLM writes one to three sentences, citing the items each draws on. `check` then
keeps a sentence only if every number in it appears in the items it cites (or in the question or
chart title): rounding, sums, percentages and approximations are dropped. Kept sentences carry
JSON pointers to the data they cite (`#/visualization/data/3`), the same scheme as alternative
views' references, so the demo's "sources" open that bar's citations: question → sentence →
bar → trial → excerpt. Comparisons in words are the model's reading; numbers are not.

That gap showed in testing: "most in Phase 2 at 4,590, then Not applicable at 4,962" passed the
number check yet misread the ranking, because rows come in phase order. Each row now carries its
rank by trials within its cohort, and three reruns of that question ordered the phases correctly.
Over the last 15 answers (five questions of different chart types, three runs), every answer kept
at least one sentence and 4 sentences were dropped, each for a number not in its data (e.g.
"mid-200s"). The answer arrives 7–15 s after the chart on first ask and is stored with the
answer in Recent, so reopening it makes no LLM call.

**What to ask next.** The same LLM call suggests up to three follow-ups, each naming only what
changes. Each is planned as a follow-up before it is offered, in parallel, and only those that
plan to a different analysis are shown; the planner caches them, so choosing one skips planning
(3 s to the chart in the demo, the data fetch). For a single trial's results, cohort-style
suggestions ("by country instead") all failed to plan, so the writer is told to suggest the
trial's other results instead ("Its serious adverse events").

## One grammar for every question: `AnalysisPlan`

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

## Networks with structure, not just counts

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

## One answer, several views

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

## Lightweight hexagonal architecture, selective DDD

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

## No database

ClinicalTrials.gov is the required source of truth and the service stores no state. A local
mirror (e.g. DuckDB over the bulk download) would give exact, fast `GROUP BY`s, but adds a
multi-GB ingestion step for reviewers and a freshness problem. A cache sits behind the
`TrialSource` port instead (below); a database-backed source could replace it later without
touching the core.

## Caching keyed to the published data snapshot

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

## Answering a repeated question without the LLM

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

## Aggregating on our side, with a cap

The API's `/stats/field/values` endpoint only reports statistics over *all* studies and accepts
no search filter (verified in the spec), so filtered aggregations must be computed by the
service. `CtGovTrialSource` fetches only the fields the analyses need (1,000 studies ≈ 1.9 MB,
≈ 1.3 s per page) up to a cap (default 5,000 per cohort, at most 10,000), and reports
`total_count` alongside the analyzed trials so responses say when a result is truncated. The
default was raised from 2,000 after a pembrolizumab chart (2,974 trials) showed Phase 1 at
699 instead of 1,046: flagged, but misleading in absolute terms.

## Exact counts beyond the cap

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

## Handling real API data

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

## Naming: `Trial` rather than `Study`

ClinicalTrials.gov calls records "studies" and includes observational and expanded-access
studies, which are not trials in the strict sense. The domain keeps the users' word, `Trial`,
and `study_type` distinguishes the kinds; the ACL is where "study" becomes "trial".

## Two entry points: structured plans and natural language

`POST /api/visualize` lets the LLM write the plan; `POST /api/plans` runs a plan directly. Both
run the same `run_plan` use case and return the same response; `meta.plan` of a question's answer
is a valid `/api/plans` request, so an interpretation can be corrected by hand and rerun (the demo
does this). The LLM writes a separate `PlanDraft` rather than the public plan schema because the
draft carries the per-filter quotes used for grounding. The structured endpoint gives
reproducible results, exercises the core without an LLM, and serves clients that build plans
themselves.

## Frontend: a generic renderer, not a per-question UI

The React demo (`frontend/`) works like a chat assistant: the question box is pinned to the
bottom, the answer scrolls above it with how the question was understood, and the resulting
plan can be edited and rerun. Filters are chosen rather than typed where the registry has a
fixed list (country dropdown with trial counts, phase and status chips, year selects) and
suggested elsewhere (drug, condition, sponsor), from `GET /api/options`; active filters show as
removable chips. For a single trial it shows the trial used, with links, and lets the user
switch to another trial the name matched. Tabs above each chart switch between the answer's
views (e.g. Bars / Map / Donut). Notes that count trials have a "show trials" link that lists
them in the citation panel, and registry counts link to the API request that reproduces them.
Above the chart, the question is answered in a few sentences whose "sources" open the data they
cite, followed by planned follow-ups ("Ask next"); a chip over the question box shows when the
next question follows up on the shown answer, and removing it starts a new topic.
Beyond the five trials cited in full, "List the other trials" lists the rest by NCT ID, 20 at a
time, and the "Ask AI" check reads whichever listed trials it has not judged yet (in requests of
10, the endpoint's limit, sent together: 25 trials took 24 s). Refusals and "no posted results" appear as neutral notices, not
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

## Monorepo and Docker

One repository, two folders (`backend/`, `frontend/`) and a `docker-compose.yml`; with a single
JS package, monorepo tooling (Nx, Turborepo) would add nothing. Docker makes the review a single
command and needs neither uv nor Node on the reviewer's machine.

## Python 3.14

The project targets Python ≥ 3.14 (lazy annotations by default; 3.12 is security-fix-only).
uv provisions the interpreter locally and the Docker image is `python:3.14-slim`.

## All known limitations

- Written answers check numbers, not words: "most" or "more than" is the model's reading of items
  that state each row's rank. An answer costs one more LLM call (7–15 s after the chart, the
  first time), and a follow-up carries at most the last 5 questions, which the client sends.
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
