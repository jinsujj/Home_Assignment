# Example runs

[README](../../README.md) · English | [한국어](README.ko.md)

Five questions sent to `POST /api/visualize` on 2026-10-13 (registry snapshot
`2026-10-09T09:00:05`, planner `gpt-5.4-mini`). Every response is saved in full, minified, in
this folder (`01-…05-*.json`); below are each run's plan, its results and the part of its JSON
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

## 1. Time trend: pembrolizumab trials per year since 2015

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

## 2. Comparison: Keytruda vs Opdivo by phase

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

## 3. Geography: recruiting cancer trials by country

18,769 recruiting trials match, more than the 5,000 analyzed. Because the question counts by one
dimension, every matching trial was tallied from light pages (see
[Exact counts beyond the cap](../design.md#exact-counts-beyond-the-cap); about 28 s with an empty cache):

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

## 4. Network: drugs combined with pembrolizumab

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

## 5. A single trial: KEYNOTE-189 results

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
