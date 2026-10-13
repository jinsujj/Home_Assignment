# 실행 예시

[README](../../README.ko.md) · [English](README.md) | 한국어

2026-10-13에 `POST /api/visualize`로 보낸 질문 다섯 개다(등록부 스냅샷 `2026-10-09T09:00:05`, 계획기
`gpt-5.4-mini`). 응답 전체는 공백 없이 이 폴더(`01-…05-*.json`)에 저장했다. 아래에는 실행마다
계획, 결과, 그리고 그 실행의 요점을 보여주는 JSON 부분을 싣는다. 계획에서 비어 있는 필터는 뺐고, 긴 목록과
제목은 잘랐다(`...`). Docker를 띄우면 다음처럼 다시 실행할 수 있다.

```bash
curl -s localhost:8080/api/visualize -H 'content-type: application/json' \
  -d '{"query": "Which countries have the most recruiting trials for cancer?"}'
```

| # | 질문 | 부록 유형 | 차트 | 보여주는 것 |
|---|---|---|---|---|
| 1 | How has the number of trials for pembrolizumab changed per year since 2015? | 시간 추세 | `time_series` | 연도 필터, 잠정 시작일 |
| 2 | Compare phases for trials involving Keytruda vs Opdivo. | 비교, 분포 | `grouped_bar_chart` | 상표명, 두 코호트, 참조로 인용하는 대체 보기 |
| 3 | Which countries have the most recruiting trials for cancer? | 지리 | `bar_chart` | 18,769건의 정확한 수, 막대마다 재현 가능 |
| 4 | Which drugs are combined with pembrolizumab? | 네트워크 | `network_graph` | 시험 군(arm)에서 읽은 병용 |
| 5 | What were the results of the KEYNOTE-189 trial? | (단일 시험) | 오차 막대가 있는 `grouped_bar_chart` | 게시된 결과, 같은 이름의 시험 중 고르기 |

## 1. 시간 추세: 2015년 이후 연도별 펨브롤리주맙 시험

"since 2015"는 차트를 자르는 대신 필터가 됐다. 그래서 코호트는 2015년 이후 시작한 시험 2,909건이고,
모두 집계했다.

```json
{ "kind": "count_by", "dimension": "start_year",
  "cohorts": [ { "label": "Pembrolizumab",
                 "filter": { "intervention": "pembrolizumab", "start_year_from": 2015 } } ] }
```

2015년부터 2027년까지 연도별 시험 수는 120, 195, 260, 255, 248, 263, 265, **299**(2022년), 259, 256,
259, 223, 7이다. 마지막 두 해는 일부가 계획이며, 응답이 이를 밝힌다. "309 of 2,909 counted trials have an
estimated start date (...), so the years they fall in are provisional"라는 안내가 붙고, 그 309건은
`meta.note_citations`에 담긴다. 연도마다 시험을 인용하며, 등록된 시작일과 그 유형, 이어서 시험이
코호트에 든 이유를 적는다.

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

다른 안내는 펨브롤리주맙을 중재로 등록하지 않고 본문에서 언급만 한 시험 329건을 센다. 이 시험들의
인용은 `mentioned_only`에 그 이름을 적는다.

## 2. 비교: Keytruda와 Opdivo의 단계

상표명은 입력한 그대로 필터에 들어갔다. 등록부 검색이 이를 약물에 대응시키고, `meta.cohorts[].names`가
시험에서 쓰는 이름을 알려준다. `["Keytruda", "Pembrolizumab"]`와 `["Opdivo", "Nivolumab"]`이고,
시험은 각각 2,974건과 2,030건이다.

```json
{ "kind": "count_by", "dimension": "phase",
  "cohorts": [ { "label": "Keytruda", "filter": { "intervention": "Keytruda" } },
               { "label": "Opdivo", "filter": { "intervention": "Opdivo" } } ] }
```

| 단계 | Early 1 | 1 | 2 | 3 | 4 | 해당 없음 |
|---|---|---|---|---|---|---|
| Keytruda | 51 | 1,046 | 1,777 | 369 | 19 | 54 |
| Opdivo | 34 | 714 | 1,164 | 186 | 17 | 50 |

안내는 세 가지를 밝힌다. 단계를 등록하지 않은 175건과 215건은 표시하지 않는다. 단계가 둘인 시험(예:
Phase 1/2)은 각 단계에 한 번씩 센다. 두 코호트에 모두 걸린 296건은 양쪽에 센다. 두 `alternatives`(코호트별
단계 구성을 보여주는 누적 막대와 히트맵)는 인용을 반복하지 않고 주 차트의 행을 참조한다.

```json
{ "phase": "Early Phase 1", "cohort": "Keytruda", "trial_count": 51, "share": 1.5,
  "citations": { "$ref": "#/visualization/data/0/citations" } }
```

## 3. 지리: 국가별 모집 중인 암 시험

모집 중인 시험 18,769건이 일치해, 집계하는 5,000건을 넘는다. 질문이 한 차원으로 세므로, 가벼운
페이지로 일치하는 시험 전부를 셌다([상한을 넘는 정확한 건수](../design.ko.md#14-상한을-넘는-정확한-건수-exact-counts-beyond-the-cap) 참고. 캐시가
비었을 때 약 28초).

```json
{ "kind": "count_by", "dimension": "country", "top_n": 10,
  "cohorts": [ { "label": "cancer", "filter": { "condition": "cancer", "statuses": ["RECRUITING"] } } ] }
```

미국 6,939, 중국 5,769, 프랑스 1,628, 이탈리아 1,430, 스페인 1,104, 캐나다 1,020, 독일 934, 영국 878,
호주 851, 한국 832로, 133개국 중 상위 10개다. 앞 5,000건만 셌다면 미국은 1,823이었을 것이다. 안내는
"Counts cover all 18,769 matching trials for cancer, tallied from all their records; citations and other
notes cover the first 5,000 analyzed."이다. 막대마다 그 수를 재현하는 API 요청이 붙어 있고, 미국 막대의
요청을 보내면 `totalCount` 6,939가 돌아왔다.

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

한계도 하나 드러난다. "cancer"를 언급만 한 시험이 5,000건을 넘어, 이들을 구분하지 못했다는 안내가
붙는다. 대체 보기는 세계 지도와 국가 구성 도넛이다.

## 4. 네트워크: 펨브롤리주맙과 병용되는 약물

"combined with"는 `link: "same_arm"`이 됐다. 시험의 한 군이 두 약을 함께 줄 때만 연결하므로, 대조군에
있는 항암제는 병용으로 세지 않는다.

```json
{ "kind": "co_occurrence", "source": "drug", "target": "drug", "link": "same_arm",
  "max_nodes": 30, "min_shared_trials": 1,
  "cohort": { "label": "Pembrolizumab", "filter": { "intervention": "pembrolizumab" } } }
```

그래프는 약물 2,487개 중 29개와 가장 강한 연결 120개를 남긴다. 가장 강한 연결은 펨브롤리주맙과
카보플라틴(230건), 시스플라틴(160건), 파클리탁셀(144건)이고, 그다음은 카보플라틴과 파클리탁셀(131건),
카보플라틴과 페메트렉시드(117건)다. 펨브롤리주맙과 함께 쓰는 백금 기반 2제 요법이다. 펨브롤리주맙은
시험의 67%에 있어 기준점(anchor)으로 표시하고 군집에서 뺐다. 남은 군집은 네 개이고, 가장 큰 군집(약물
10개)은 카보플라틴의 이름을 딴다. 연결마다 두 약을 함께 주는 군을 인용한다.

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

가장 큰 응답으로, 공백 없이 970 KB, gzip으로 보내면 80 KB다. 노드와 연결마다 근거와 함께 시험을 최대
다섯 건 인용한다.

## 5. 단일 시험: KEYNOTE-189 결과

질문이 코호트가 아니라 시험 하나를 가리키므로 계획은 `{"kind": "trial_results", "trial": "KEYNOTE-189",
"focus": "outcomes"}`다. 그 이름으로 결과를 게시한 시험은 두 건이다. 서비스는 큰 쪽인 NCT02578680(참가자
616명)을 그리고, 다른 한 건(NCT03950674, 40명)은 안내와 `meta.trial.alternatives`에 적는다.

| 주요 결과변수(중앙값, 개월) | 펨브롤리주맙 + 페메트렉시드 + 백금 | 대조군 |
|---|---|---|
| 무진행 생존 | 8.8 (95% CI 7.6–9.2) | 4.9 (4.7–5.5) |
| 전체 생존 | 추정 불가("NA"로 게시, 막대 없음) | 11.3 (8.7–15.1) |

게시된 분석은 안내로 붙는다. 위험비는 무진행 생존 0.52(95% CI 0.43–0.64), 전체 생존 0.49(0.38–0.64)이고,
둘 다 p < 0.00001이다. 오차 막대는 `y_lower`와 `y_upper`를 쓰고, 값마다 그 값이 나온 게시 필드를 인용한다.

```json
"evidence": [
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.title", "value": "Progression-Free Survival (PFS) ..." },
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements.value", "value": "8.8" },
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements.lowerLimit", "value": "7.6" },
  { "field": "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements.upperLimit", "value": "9.2" } ]
```
