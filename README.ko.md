# Cheiron — ClinicalTrials.gov 질의-시각화 에이전트

[English](README.md) | 한국어

임상시험에 대한 자연어 질문을 받아, 프론트엔드가 그대로 그릴 수 있는 구조화된 시각화 명세로
바꿔 주는 백엔드 서비스다. 데이터는 [ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api)에서
가져온다.

> **현재 상태:** 질문에 처음부터 끝까지 답한다(`POST /api/visualize`: LLM 계획 → 근거 확인
> → ClinicalTrials.gov → 시각화 명세). 구조화된 계획은 바로 실행할 수 있고(`POST /api/plans`),
> React 데모가 두 경로를 모두 그린다. 실행 예시는 아직 추가 전이다. [진행 상황](#진행-상황) 참고.

용어가 낯설다면 [도메인 용어 정리](docs/domain-glossary.ko.md)를 먼저 보면 좋다.

## 목차

1. [실행 방법](#실행-방법)
2. [요청 / 응답 스키마](#요청--응답-스키마)
3. [주요 설계 결정과 트레이드오프](#주요-설계-결정과-트레이드오프)
4. [한계와 향후 개선](#한계와-향후-개선)
5. [실행 예시](#실행-예시)
6. [AI 도구 사용과 검증](#ai-도구-사용과-검증)
7. [진행 상황](#진행-상황)

## 실행 방법

### 설정

```bash
cp .env.example .env   # 그다음 OPENAI_API_KEY 설정
```

| 변수 | 필수 여부 | 용도 |
|---|---|---|
| `OPENAI_API_KEY` | `/api/visualize`, `/api/mentions`에 필요 | LLM 플래너와 언급 판정. `/api/plans`는 없어도 동작한다 |
| `OPENAI_MODEL` | 아니오 | 플래너 모델, 기본값 `gpt-5.4-mini` |
| `OPENAI_REASONING_EFFORT` | 아니오 | 기본값 `low`. `gpt-4.1-mini`처럼 추론 기능이 없는 모델이면 빈 값으로 둔다 |
| `OPENAI_MENTION_REASONING_EFFORT` | 아니오 | 언급 판정용 같은 설정, 기본값 `high` |

`.env`는 git에서 제외된다. `.env.example`에 변수와 사용 가능한 모델이 정리되어 있다.

### Docker로 실행 (권장)

```bash
docker compose up --build
```

데모 화면은 <http://localhost:8080>, API는 <http://localhost:8080/api>,
대화형 문서는 <http://localhost:8080/api/docs>에서 볼 수 있다. 컨테이너는 두 개다.
`api`(FastAPI, Python 3.14, root가 아닌 사용자로 실행)와 `web`(React 빌드를 서빙하고 `/api`를
중계하는 nginx).

### 로컬 개발

[uv](https://docs.astral.sh/uv/)(Python 3.14가 없으면 설치해 준다)와 Node 22가 필요하다.

```bash
cd backend && uv sync && uv run --env-file ../.env uvicorn cheiron.main:app --reload   # API: :8000
cd frontend && npm install && npm run dev       # UI: :5173, /api는 :8000으로 중계
```

### 테스트

```bash
cd backend
uv run pytest            # 오프라인: 단위 테스트, 녹화한 API 응답, 가짜 소스를 쓴 HTTP 테스트
uv run pytest -m live    # 실제 ClinicalTrials.gov API에 대한 계약 확인과 교차 검증
uv run --env-file ../.env pytest -m llm   # 실제 모델로 플래너(19개 사례)와 언급 판정(13개) 평가
cd ../frontend && npm run build && npm run lint   # 타입 검사, 빌드, lint
```

## 요청 / 응답 스키마

| 엔드포인트 | 용도 |
|---|---|
| `POST /api/visualize` | 질문(+ 선택적 구조화 필드) → 계획 → 시각화. |
| `POST /api/plans` | 구조화된 분석 계획을 LLM 없이 바로 실행. |
| `GET /api/options` | 필터 선택지: 등록부의 모든 국가(정확한 표기, 시험 수), 자주 쓰이는 질환·중재·스폰서 추천어, 단계와 상태 코드. 6시간 캐시. |
| `GET /api/version` | `{"data_version": "2026-10-09T09:00:05"}`: 현재 제공 중인 등록부 데이터 스냅샷(ClinicalTrials.gov `/version`의 `dataTimestamp`, 최대 10분마다 확인). |
| `POST /api/mentions` | `{"nct_ids": [...], "names": [...]}` → 이름이 가리키는 대상이 각 시험에서 어떤 역할인지(연구 대상, 함께 투여, 등록 조건, 배경, 불분명), LLM이 원문을 인용해 판정. [시험이 그 단어를 언급하는 이유](#ai-설계-시험이-그-단어를-언급하는-이유) 참고. |
| `GET /api/health` | 생존 확인. |
| `GET /api/docs` | Pydantic 모델에서 생성한 OpenAPI 문서. |

### `POST /api/visualize` 요청

```json
{ "query": "How has the number of trials for this drug changed over time?", "drug_name": "Pembrolizumab" }
```

| 필드 | 타입 | 규칙 |
|---|---|---|
| `query` | 문자열, 1–1,000자 | 필수 |
| `drug_name`, `condition`, `sponsor` | 문자열 ≤ 200 | 선택 |
| `country` | 문자열 ≤ 100 | 선택 |
| `phases`, `statuses` | 등록부 코드 목록 (`PHASE3`, `RECRUITING`, …) | 선택. 하나라도 해당하면 포함 |
| `start_year`, `end_year` | 정수 1900–2100 | 선택. `[start_year, end_year]`에 시작한 시험. start ≤ end |
| `nct_id` | `NCT` + 숫자 8자리 | 선택. 단일 시험 결과 질문에서 이 시험을 쓴다(예: `meta.trial`에 나온 대안) |
| `max_trials_per_cohort` | 정수 1–10,000 | 기본값 5,000 |
| `all_citation_ids` | 불리언 | 기본값 `false`. 데이터 항목마다 기여한 모든 NCT ID를 `citations.nct_ids`에 담는다 |

구조화 필드는 모든 코호트에 적용되고, 플래너가 질문에서 뽑은 값보다 우선한다. 질문에서
이 필드를 가리킬 수 있다("this drug"). 필드가 적용되면 `meta.notes`에 남고, 차트 제목에는
모든 코호트가 공유하면서 코호트 이름에 드러나지 않은 필터가 붙는다. 예:
"Trials started per year — Pembrolizumab · South Korea". 국가 필터는 그 나라에 시험 기관이
하나라도 있는 시험을 남긴다(한국의 펨브롤리주맙 시험 389건 중 335건이 다국가 시험).
국가 필터를 쓰면 `meta.notes`가 이를 알린다.

| 상태 코드 | 경우 | 본문 |
|---|---|---|
| `200` | 답함 | 아래 응답, `meta.query`와 `meta.interpretation` 포함 |
| `422` | 잘못된 요청 | FastAPI 검증 오류 |
| `422` | 어떤 분석으로도 답할 수 없음 (의학적 조언, 주제 밖, 어떤 분석도 쓰지 않는 데이터) | `{"detail": {"code": "unsupported_question", "reason", "message"}}`, `reason` ∈ `medical_advice`, `not_about_trials`, `unavailable_data`, `other`. 사유별 고정 문구 |
| `422` | 이름으로 말한 시험이 등록부에 없음 | `{"detail": {"code": "trial_not_found", "message"}}` |
| `422` | 시험이 결과를 게시하지 않음 | `{"detail": {"code": "no_posted_results", "message", "trial": {"nct_id", "url"}}}` |
| `422` | 한 번의 수정 후에도 유효한 계획이 없음 | `{"detail": {"code": "plan_rejected", "message", "problems": [...]}}` |
| `502` | ClinicalTrials.gov 실패 | `{"detail": "..."}` |
| `503` | `OPENAI_API_KEY`가 없거나 모델에 연결할 수 없음 | `{"detail": "..."}` |

### `POST /api/plans` 요청

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

| 필드 | 타입 | 규칙 |
|---|---|---|
| `plan.kind` | `count_by` \| `co_occurrence` \| `distribution` \| `correlation` | 필수. 나머지 필드를 정한다([AnalysisPlan](#모든-질문을-하나의-문법으로-analysisplan) 참고) |
| `plan.cohorts` / `plan.cohort` | 코호트: `{ label, filter }` | `count_by`: 이름이 겹치지 않는 1–5개. 나머지: 1개 |
| `filter.condition`, `.intervention`, `.sponsor` | 문자열 ≤ 200 | 선택, 자유 텍스트. 동의어는 ClinicalTrials.gov가 처리한다 |
| `filter.country` | 문자열 ≤ 100 | 선택. 흔한 변형 표기(`USA`, `UK`)도 찾는다 |
| `filter.phases`, `.statuses` | 등록부 코드 목록 (`PHASE3`, `RECRUITING`, …) | 선택. 하나라도 해당하면 포함 |
| `filter.study_type` | `INTERVENTIONAL` \| `OBSERVATIONAL` \| `EXPANDED_ACCESS` | 선택 |
| `filter.start_year_from`, `.start_year_to` | 정수 1900–2100 | 선택. from ≤ to |
| `max_trials_per_cohort` | 정수 1–10,000 | 기본값 5,000. 더 큰 결과는 잘리고 그 사실이 표시된다 |
| `all_citation_ids` | 불리언 | 기본값 `false`. 데이터 항목마다 기여한 모든 NCT ID를 `citations.nct_ids`에 담는다 |

알 수 없는 필드, 알 수 없는 열거값, 잘못된 조합(예: 코호트가 여럿인데 `split_by`)은 설명과 함께
`422`로 거부한다. ClinicalTrials.gov 실패는 `502`를 돌려준다.

### 응답

```jsonc
{
  "visualization": { "type": "grouped_bar_chart", "title": "Trials by phase — Pembrolizumab vs Nivolumab",
                     "encoding": { "x": { ... }, "y": { ... }, "series": { ... } }, "data": [ ... ] },
  "alternatives": [                        // 같은 데이터를 다른 차트 형태로 (아래 참고)
    { "type": "stacked_bar_chart", "title": "Phase mix within each cohort — ...", "encoding": { ... },
      "data": [ ... ], "notes": [ "Each bar is 100% of one cohort's counts, ..." ] },
    { "type": "heatmap", ... }
  ],
  "meta": {
    "source": "clinicaltrials.gov",
    "query": "Compare phases for Keytruda vs Opdivo",            // /api/visualize만
    "interpretation": "Compare trial phases for Keytruda versus Opdivo.",   // /api/visualize만
    "plan": { ... },                       // 실제로 실행한 분석, 적용된 모든 필터 포함
    "cohorts": [ { "label": "Pembrolizumab", "matched": 2974, "analyzed": 2974, "truncated": false,
                   "exact_counts": false,   // "상한을 넘는 정확한 건수" 참고
                   "names": ["pembrolizumab", "Pembrolizumab"] }, ... ],   // 필터 단어와 등록된 이름
    "notes": [ "175 of 2974 trials in Pembrolizumab have no registered phase and are not shown.", ... ],
    "data_version": "2026-10-09T09:00:05"  // 답을 계산한 등록부 데이터 스냅샷
  }
}
```

### 시각화 명세 (구현됨)

`encoding`은 시각 채널을 데이터 필드에 연결한다. 모든 채널은
`{ field, type, title, order, unit, time_unit, scale }`이다. `type`은 `nominal`, `ordinal`,
`quantitative`, `temporal`(Vega-Lite의 측정 유형) 중 하나이고, `order`는 있을 때 범주를 그릴
순서이며, `scale`은 `null`(선형) 또는 `"symlog"`(0을 유지하는 로그형)다.

| `type` | 채널 | 데이터 |
|---|---|---|
| `bar_chart` | `x` (범주), `y` | 범주당 한 행 |
| `grouped_bar_chart` | `x`, `y`, `series` | 범주 × 시리즈당 한 행, 0도 포함 |
| `time_series` | `x` (temporal, `time_unit: "year"`), `y`, 선택적 `series` | 연도당 한 행, 빈 연도는 0으로 채움 |
| `histogram` | `x` (`bin_start`), `x2` (`bin_end`), `y` | 구간당 한 행. 구간은 `[bin_start, bin_end)`. 마지막 구간은 열려 있을 수 있다(`bin_end: null`) |
| `scatter_plot` | `x`, `y`, `tooltip` | 시험당 한 행(`nct_id`, `title`, 두 측정값). 최댓값이 중앙값의 10배 이상인 축은 `scale: "symlog"`. `notes`가 스피어먼 순위 상관계수를 문장으로 알려 준다 |
| `network_graph` | `node_id`, `node_label`, `node_size`, `node_color` (군집), `node_shape` (개체 종류), `edge_source`, `edge_target`, `edge_weight` (공유 시험 수), `edge_strength` (연관 강도) | `{ "nodes": [...], "edges": [...] }`. 노드에는 `community`(군집 이름 또는 null), `anchor`(불리언), `partners`(연결된 노드 수), 연결선에는 `association`(자카드 지수, 0–1) |

대체 보기(`alternatives`)는 아래 유형을 더한다. 각 항목에는 자체 `notes`가 있다.

| `type` | 채널 | 데이터 |
|---|---|---|
| `stacked_bar_chart` | `x` (그룹), `y` (`share`, %, 합계 100), `color` (범주) | 그룹 × 범주당 한 행 |
| `heatmap` | `x`, `y` (범주), `color` (값) | 칸당 한 행 |
| `choropleth_map` | `region` (`iso_numeric`, ISO 3166-1 숫자 코드), `label` (국가), `color` (값) | 국가당 한 행. `region`으로 세계 지도 도형과 연결(예: world-atlas의 `id`) |
| `donut_chart` | `theta` (값), `color` (범주), `tooltip` (`share`, %) | 범주당 한 행 |
| `line_chart` | `x`, `y` (quantitative) | 점당 한 행 |
| `forest_plot` | `y` (결과 지표), `series` (그룹), `x` (값), `x_lower`, `x_upper` | 결과 지표 × 그룹당 한 행 |

단일 시험의 결과는 `grouped_bar_chart`(x = 결과 지표 또는 이상반응, series = 시험의 그룹)로
나오고, `y_lower` / `y_upper` 채널이 더해질 수 있다. 게시된 구간(예: 95% 신뢰구간)으로, 오차
막대로 그린다. "NA"로 게시된 값(예: 도달하지 않은 중앙값)은 `null`이다. `meta.trial`은 사용한
시험(`nct_id`, `title`, `url`)과 그 이름에 함께 걸린 다른 시험(`alternatives`)을 알려 준다.

모든 행, 노드, 연결선에는 `citations`가 붙는다(아래는 펨브롤리주맙의 "Phase 3" 막대).

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
    "nct_ids": null } }
```

- `total`은 그 데이터 항목을 이루는, 집계한 시험의 수다. `items`는 앞의 몇 건(기본 5건)을 자세히 보여준다.
  건수를 등록부에서 받은 경우에는 `total`이 `trial_count`보다 작다("상한을 넘는 정확한 건수" 참고).
- `evidence`는 그 시험을 이 데이터 항목에 넣은, API 시험 JSON의 필드와 등록된 그대로의 값이다.
  연결선은 양 끝마다 하나씩 두 개, 게시된 결과는 값과 구간 한계를 담는다. 그 뒤에 시험이 코호트에
  속하는 근거가 붙는다. 코호트 필터와 일치하는 등록값, 그리고 시험 원문에서 그것을 언급하는 문장이다
  (아래 참고).
- `excerpt`는 같은 근거를 한 줄 텍스트로 쓴 것으로, 과제 예시의 형태(`citations[].{nct_id, excerpt}`)와 같다.
- `nct_ids`는 요청에 `all_citation_ids`를 켰을 때 기여한 모든 시험을 담고, 아니면 `null`이다.
- `notes`는 가정과 주의 사항을 평이한 문장으로 알려 준다(여러 값을 가진 항목의 집계, 누락된
  값, 상위 N개 제한, 구간 나누기).

**시험이 코호트에 속하는 근거.** ClinicalTrials.gov의 중재·질환·스폰서 검색은 설명문 같은 다른
텍스트도 찾는다. 펨브롤리주맙으로 찾은 2,974건 중 335건은 이 약을 중재로 등록하지 않았고(예: 대변
미생물 이식 연구), 폐암 시험 앞 5,000건 중 1,195건은 폐암을 질환으로 등록하지 않았다. 서비스는
자유 텍스트 필터마다 어떤 시험이 그 단어를 언급만 하는지 등록부에 묻는다(등록 필드에 대한
`NOT AREA[...]`. 등록부의 동의어는 등록으로 인정된다: "Keytruda", "MK-3475", "pembrolizumab" 모두 같은
2,639건). 나머지 시험에는 일치하는 등록값을 근거로 붙인다(단어가 가장 많이 겹치는 값, 없으면
코호트에서 가장 흔한 값. 그래서 "Keytruda"는 "Pembrolizumab"을 인용한다). 언급만 하는 시험은
`mentioned_only`에 그 단어가 담기고, 인용 순서에서 뒤로 가며, `meta.notes`가 그 수를 알려 준다.
실제 API 테스트가 3상 펨브롤리주맙 시험 전부에 대해 등록부의 판정과 등록된 약물명이 일치하는지
확인한다. 비용은 자유 텍스트 필터마다 요청 하나, 그런 시험 1,000건마다 하나씩 더 든다. 질환에서는
이 판정이 과하게 잡는다. 더 좁은 등록명("Lung Adenocarcinoma", "NSCLC Stage IV")은 "lung cancer"와
일치하지 않으므로, 표시된 시험 중 일부는 실제로 폐암을 연구한다. 아래의 LLM 판정이 이를 가려낸다.

**그것을 언급하는 원문.** 인용된 시험(전체 기여 시험이 아니라 자세히 보여주는 `items`)마다, 필터
단어나 등록된 이름이 나오는 시험 원문의 문장도 인용한다. 찾는 순서는 제목, 공식 제목, 요약, 군과
중재 설명, 상세 설명, 키워드, 선정 기준이다. 제목과 요약은 시험을 설명하는 반면 선정 기준은 다른
치료를 언급하는 경우가 많기 때문이다. 인용 문장은 이름 주변의 문장이나 줄로, 최대 240자이며 단어
경계에서 자르고, 언제나 원문의 정확한 부분 문자열이다. 문장은 대문자 앞의 ". "나 줄바꿈에서만 끝나므로
"e.g. pembrolizumab", "etc.", "2.5 mg"에서는 끝나지 않는다. 이 규칙 전에는 실제 기록에서 두 실수가
모두 나왔다("g pembrolizumab)"). 인용된 시험의 원문은 200건마다 요청 하나(`filter.ids`)로 받고,
받지 못하면 인용은 등록값 근거만 유지한다.

펨브롤리주맙 기준 실측으로 기본 단계 차트는 54 KB, Keytruda vs Opdivo는 123 KB, 약물 네트워크는
2,081 KB이고, 그중 약 3분의 2를 대체 보기가 반복한다. 압축을 받는 클라이언트(브라우저 포함)에는 gzip으로
보내 4 KB, 16 KB, 132 KB가 된다. 전체 NCT ID 목록은 선택 사항이다. `all_citation_ids`를 켜면 같은
답이 147 KB, 353 KB, 2,312 KB(gzip 36, 91, 186 KB)가 된다.

## 주요 설계 결정과 트레이드오프

### LLM은 계획하고, 결정적 코드가 계산한다

```
질문 + 구조화 필드
  → Planner (LLM)    PlanDraft: 계획 + 필터마다 질문 원문 인용, 열거형으로 된 엄격한 JSON Schema
  → Grounding        인용을 질문과 대조, 구조화 필드가 우선, 도메인 불변식 확인,
                     거부된 초안은 한 번 수정 기회
  → TrialSource      코호트 필터 → ClinicalTrials.gov API, 페이지 단위 조회, 데이터 스냅샷별 캐시
  → ACL              원본 시험 JSON → 도메인 Trial
  → Charts           Trial[] → 기여 NCT ID를 가진 버킷 → 차트 유형 + encoding   (순수 함수)
```

응답의 어떤 숫자도 LLM에서 나오지 않는다. LLM의 출력은 범주형 필드가 API 명세의 열거형으로
제한된 작은 계획뿐이라, 환각은 "틀렸지만 유효한 계획을 고르는 것"으로 좁혀진다. 이는
`meta.interpretation`과 `meta.plan`으로 드러나고, 데모에서 고쳐 다시 실행할 수 있다. 집계기가
버킷마다 기여한 NCT ID를 갖고 있으므로, 심층 인용은 나중에 덧붙인 기능이 아니라 설계에서
자연스럽게 나온다.

### AI 설계: 질문에 근거한 계획

플래너를 정직하게 만드는 장치는 네 겹이다(`application/planning.py`, `application/visualize.py`).

1. **제약된 출력.** 모델은 엄격 모드의 structured outputs로 `PlanDraft`를 돌려준다. 차원, 개체,
   측정값, 단계, 상태, 연구 유형은 모두 열거형이다.
2. **인용된 필터.** 필터마다 그것을 말한 질문의 정확한 문구가 붙는다. 인용이 질문에 없으면
   (대소문자, 공백, 따옴표 모양은 무시) 필터를 지어냈거나 바꿔 말한 것이다. 텍스트 값은
   인용에서 가져와야 하므로 검색어는 사용자의 말이고, 동의어 처리는 ClinicalTrials.gov에 맡긴다.
3. **한 번의 수정.** 문제(인용 없는 필터, 분석 종류에 필요한 필드 누락, 코호트가 여럿인데
   `split_by` 같은 도메인 위반)를 이전 초안과 함께 모델에 돌려보낸다. 마지막 시도에서도 인용이
   없는 필터는 빼고 `meta.notes`에 알린다. 단, 그 때문에 비교 대상 코호트에 자기 필터가 하나도
   남지 않으면 차트를 그리지 않고 거부한다.
4. **사유 코드로 거절.** 어떤 분석으로도 답할 수 없는 질문은 `422 unsupported_question`을
   돌려준다. 모델은 `refusal` 열거값만 고르고, 메시지는 사유별 고정 문구다. 예전에는 모델이 사유를
   직접 썼는데, "What were the results of KEYNOTE-189?"를 세 번 실행하자 사유가 세 번 다
   달랐고 그중 둘은 사실이 아니었다("등록 데이터로는 결과를 설명할 수 없다"고 했지만 이 시험은
   결과를 게시했다). 이 질문은 이제 답한다(아래 `TrialResults`).

수정 단계를 둔 이유: 첫 평가에서 `gpt-4.1-mini`가 "Keytruda vs Opdivo"에 대해 "trials involving
Opdivo"라고 인용했다(질문에 없는 문구). 이 필터를 조용히 빼 버리면 비교가 Keytruda 대 등록부
전체로 바뀐다. 수정 단계가 있으면 모델이 인용을 고치고(두 비교 모두 올바르게 계획됨), 필터 없이
남은 코호트는 차트로 그리지 않고 거부된다.

플래너가 보는 것은 오늘 날짜("최근 5년" 해석용), 구조화 필드("this drug" 해석용), 문법뿐이다.
시험 데이터는 전혀 보지 않는다.

**모델 선택** (`tests/llm/test_planner_eval.py`: 부록의 모든 질의 유형, 구조화 필드 참조,
상대 기간, 이름으로 말한 시험의 결과, 거절. 사례마다 필터를 정확히 비교하므로 필터가 하나만
더해져도 실패하고, 거절은 사유까지 확인한다.)

| 모델 | 결과 | 플래너 지연 시간 |
|---|---|---|
| `gpt-5.4-mini`, reasoning `low` (기본값) | 첫 평가 세트 17/17 두 번, 현재 세트 19/19 | 약 1.5–2.2초 |
| `gpt-4.1-mini` | 첫 평가 세트 16/17 (Keytruda vs Opdivo 1회 실패, 재실행 3/3 통과) | 약 1.8–4.8초 |

### AI 설계: 시험이 그 단어를 언급하는 이유

시험이 약을 언급만 한다는 사실만으로는 이유를 알 수 없다. 펨브롤리주맙 "언급" 335건에는 표준 치료인
펨브롤리주맙과 함께 진행하는 대변 이식 연구, 펨브롤리주맙 치료 경험을 요구하는 시험, 환자가 통상 치료로
받는 연구가 섞여 있다. 이를 가르려면 글을 읽어야 하므로, `POST /api/mentions`(데모 인용 패널의
"Ask AI" 버튼)는 시험마다 제목과 그 대상을 언급하는 모든 문장(최대 6개)을 LLM에 주고, 역할 하나를
고르게 한다. `studied`, `given_alongside`, `eligibility`, `background`, `unclear`이며 약물, 질환,
기관 각각에 맞게 정의했다.

플래너의 근거 확인 규칙이 그대로 적용된다. 판정마다 제목이나 문장을 인용해야 하고,
`application/mentions.py`는 그 인용(세 단어 이상, 공백·대소문자·마크다운 이스케이프 무시)이 그곳에
있을 때만 판정을 남긴다. 응답에는 그 원문 문장이 그대로 실리고, 찾지 못한 인용은 역할을 `unclear`로
바꾼다. 한 데이터 항목의 인용 시험(요청당 최대 10건)에 대해 요청할 때만 실행하며, 코호트 전체나 차트
숫자에는 쓰지 않는다. 판정은 시험과 문장 단위로 캐시한다(`CachingMentionJudge`).

평가(`tests/llm/test_mention_eval.py`, 직접 읽고 정답을 정한 기록 13건: 펨브롤리주맙 8건, 유방암·폐암
5건. "Lung Adenocarcinoma"로 등록되어 언급만으로 표시된 시험 포함). 평가를 만들며 모델이 아니라 우리
코드의 버그 셋을 찾았다. 문장 자르기가 "e.g."에서 멈췄고("g pembrolizumab)"), 대조 단계가 문장 앞의
섹션 표시를 복사한 인용이나 제목 인용을 거부했으며, 역할 정의가 약물에만 맞아 유방암 시험이 모두
`background`로 나왔다. 고친 뒤 `gpt-5.4-mini`로 각 3회 실행한 결과:

| 추론 강도 | 정답 | 13건 처리 시간 |
|---|---|---|
| `low` | 13, 12, 12 / 13 | 11–13초 |
| `high` (기본값, `OPENAI_MENTION_REASONING_EFFORT`) | 12, 11, 12 / 13 | 35–93초 |

추론 강도를 높여도 나아지지 않았다. 틀린 것은 해석이 갈리는 경우(관찰 연구에서 그 약을 "받을 예정인"
환자)였고, 제목과 섹션 표시를 더 자주 인용했다. `high`는 선택에 따른 기본값이며, 여기서는 `low`도
정확도가 같고 몇 배 빠르다.

### 모든 질문을 하나의 문법으로: `AnalysisPlan`

질문 유형마다 코드 경로를 따로 두지 않고, 모든 질문을 열거형으로 매개변수화된 다섯 가지 분석으로
표현한다(`cheiron/domain/analysis.py`). 넷은 여러 시험에 대한 분석이고, 하나는 단일 시험의
게시된 결과에 대한 분석이다. 차트 유형은 계획의 모양에서 결정적으로 정해진다.

| 계획 | 매개변수 | 차트 | 예시 질문 |
|---|---|---|---|
| `CountBy` | 코호트 1개, `dimension` | `bar_chart` | "How are lung cancer trials distributed across phases?" |
| `CountBy` | `dimension = start_year` | `time_series` | "How many trials started each year for pembrolizumab?" |
| `CountBy` | 코호트 2–5개 | `grouped_bar_chart` | "Compare phases for pembrolizumab vs nivolumab." |
| `CountBy` | 코호트 1개 + `split_by` | `grouped_bar_chart` | "Phases by sponsor class for pembrolizumab trials." |
| `CoOccurrence` | `source`, `target` 개체 | `network_graph` | "Network of sponsors ↔ drugs for breast cancer." |
| `Distribution` | `measure` | `histogram` | "How large are pembrolizumab trials?" |
| `Correlation` | `x`, `y` 측정값 | `scatter_plot` | "Do longer trials enrol more patients?" |
| `TrialResults` | `trial`(NCT ID 또는 이름), `focus`, 선택적 `outcome` | 구간이 있는 `grouped_bar_chart` | "What were the results of KEYNOTE-189?", "Side effects in CheckMate 227?" |

차원: 단계, 상태, 연구 유형, 시작 연도, 국가, 질환, 중재, 중재 유형, 주 스폰서, 주 스폰서 분류.
개체: 약물, 스폰서, 질환, 국가, 연구자, 시험 기관. 측정값: 모집 인원, 기간(개월), 시작 연도.
코호트는 이름과 `TrialFilter`의 쌍이라, "Drug A vs Drug B"는 같은 `CountBy` 안의 코호트 두 개다.

새 질문 유형을 더하려면 새 파이프라인이 아니라 열거값 하나와, 그 값을 `Trial`에서 읽는 방법
(`domain/facets.py`)만 더하면 된다.

### 개수만이 아니라 구조를 보여주는 네트워크

공동 출현 횟수를 그대로 그리면 대부분 빈도를 다시 말할 뿐이고, 특히 질문이 걸러 낸 개체가
두드러진다. 펨브롤리주맙은 펨브롤리주맙 시험의 67%에 등장하고 거의 모든 약물과 연결된다. 그래서
네트워크마다 세 가지를 명시한다(`domain/charts/co_occurrence.py`).

- **기준점(anchor)**: 필터로 쓴 개체, 또는 집계한 시험의 절반 넘게 등장하는 개체는 표시하고
  군집 계산에서 뺀다. 구조상 대부분의 노드와 연결되기 때문이다.
- **군집**: 나머지 표시 노드 사이의 공유 시험 수에 대해 탐욕적 모듈러리티 최대화
  (Clauset–Newman–Moore)를 쓴다. `domain/charts/communities.py`에 구현했다(순수 Python, 동점 처리가
  결정적, 최대 200노드). 군집 이름은 가장 빈도가 높은 구성원에서 딴다. 실제 데이터에서 군집은
  알아볼 수 있는 치료 패턴이다.
  - 펨브롤리주맙과 함께 쓰는 약물: 백금/탁산 계열 화학요법(carboplatin, pemetrexed,
    paclitaxel, …), 소화기암 요법(oxaliplatin, leucovorin, 5-FU, irinotecan, …), 다른 면역관문
    억제제(nivolumab, ipilimumab, atezolizumab, durvalumab), 세포치료 전처치(cyclophosphamide, fludarabine)
  - 유방암: HER2 표적 약물과 쓰는 화학요법, CDK4/6 억제제와 쓰는 내분비요법, 전이성/삼중음성 화학요법
  - 췌장암: gemcitabine/nab-paclitaxel과 FOLFIRINOX 구성 약물

  기준점 처리가 없을 때는 펨브롤리주맙이 화학요법 군집에 합쳐졌다.
- **연관 강도**: 연결선마다 자카드 지수(공유 시험 수 / 둘 중 하나라도 있는 시험 수)를 붙인다.
  단지 자주 함께 나오는 쌍보다 실제 병용 요법이 위로 온다. 펨브롤리주맙 네트워크에서 가장 잦은
  연결인 펨브롤리주맙 + carboplatin(256건)은 0.13인 반면, leucovorin + oxaliplatin(28건, 0.43)과
  carboplatin + paclitaxel(135건, 0.40)이 가장 높다.

데모는 노드를 군집별로 색칠하고, 개체 종류별로 모양을 다르게 하고, 기준점은 진하게 그린다.
연결선 두께는 공유 시험 수, 진하기는 연관 강도를 나타내고 범례도 붙는다. 그래프의 마우스 휠
확대는 껐다. 화면 너비를 채운 그래프가 페이지 스크롤을 가로채서 그 아래 범례와 인용에 닿을 수
없었기 때문이다.

### 하나의 답, 여러 보기

설계 목표는 하나의 일관된 방식으로 다양한 시각화를 만드는 것이다. 그래서 모든 답에는
**기본 차트의 행에서 계산한 대체 보기**가 함께 온다(`domain/charts/views.py`). 새 데이터나 LLM
호출은 쓰지 않는다. 한 답의 모든 보기는 같은 숫자와 같은 인용을 보여주고, 어떤 보기가 생기는지는
기본 차트의 유형과 encoding만으로 정해진다.

| 기본 차트 | 대체 보기 | 이유 |
|---|---|---|
| `bar_chart` | `choropleth_map`(범주가 국가일 때), `donut_chart` | 지리는 지도로 읽는 것이 가장 쉽고, 도넛은 범주별 비중을 보여준다 |
| `grouped_bar_chart` (비교) | `stacked_bar_chart` (그룹별 100%), `heatmap` | 크기가 다른 그룹(Keytruda 2,974건 vs Opdivo 2,030건)은 구성비로 공정하게 비교할 수 있다. 두 약의 단계 구성비는 거의 같았다 |
| `grouped_bar_chart` (한 시험의 결과) | `forest_plot` | 구간이 있는 점 추정치, 게시된 결과를 보여주는 일반적인 형태 |
| `time_series` | 누적 `time_series` | 증가와 누적 합계를 한눈에 |
| `network_graph` | `heatmap` (인접 행렬), `bar_chart` (강한 연결 순위) | 촘촘한 네트워크는 읽기 어렵다. 행렬과 순위가 정확한 값을 준다 |
| `histogram` | `line_chart` (누적 분포) | "모집 인원이 N명 미만인 시험의 비율"을 바로 읽을 수 있다 |
| `scatter_plot` | `bar_chart` (x 기준 5등분한 시험의 y 중앙값) | "x가 클수록 y도 큰가?"에 직접 답하고, 소수의 거대한 시험에 휘둘리지 않는다 |

비율(이상반응 %)에는 히트맵만 주고 100% 누적 막대는 주지 않는다. 서로 다른 이상반응의 비율을
더하게 되기 때문이다. 지도는 등록부의 국가명 226개를 ISO 3166-1 숫자 코드로 바꾼 표
(`domain/country_codes.json`)로 국가를 연결한다. pycountry로 만든 뒤 손으로 확인했고, 그 과정에서
잘못된 유사 일치("Kosovo" → 세르비아)를 잡았다. 14개는 코드를 직접 넣었고, 현재 코드가 없는
4개(코소보와 지금은 없는 세 나라)는 지도의 안내에 나열된다. 브라우저에서 보기를 만들며 버그 두
개를 찾았다. Vega-Lite는 색 값이 null인 지도 도형을 그리지 않아 데이터가 없는 나라가 사라졌고
(이제 회색 바탕 층을 먼저 그린다), 단위가 이미 들어간 채널 제목에 단위가 한 번 더 붙었다
("Median (Months) (Months)". 이제 단위는 `Channel.unit`으로만 전달한다).

### 가벼운 헥사고날 아키텍처, 선택적 DDD

문제 자체는 읽기 전용 분석 파이프라인이다. 저장도, 변하는 상태도, 여러 개체에 걸친 불변식도 없다.
대신 실제 외부 경계가 셋 있다(들어오는 HTTP, 나가는 ClinicalTrials.gov와 LLM). 그래서 포트와
어댑터는 값을 하지만, 전술적 DDD의 대부분은 형식에 그친다.

| 패턴 | 사용 | 이유 |
|---|---|---|
| 포트와 어댑터 | 예 | API와 LLM을 가짜로 바꿔, 네트워크 없이 핵심을 결정적으로 테스트한다. |
| 부패 방지 계층(ACL) | 예 | `adapters/outbound/ctgov/mapper.py`가 깊게 중첩되고 빈칸이 많은 API JSON을 평평한 `Trial`로 바꾼다. API가 바뀌면 파일 하나만 고친다. |
| 값 객체 / 열거형 | 예 | `Phase`, `Status`, `PartialDate`… 한 번 검증된다. 같은 열거형이 LLM 출력도 제한한다. |
| 보편 언어 | 예 | 사용자와 과제가 쓰는 말이라 도메인도 `Trial`이라 부른다(아래 참고). |
| 애그리거트, 리포지토리, 도메인 이벤트 | 아니오 | 바뀌거나 저장되는 것이 없다. 리포지토리는 이름만 바꾼 API 클라이언트가 될 것이다. |
| 여러 바운디드 컨텍스트, CQRS, DI 컨테이너 | 아니오 | 컨텍스트 하나, 조회만 한다. 생성자 주입으로 충분하다. |

도메인(`cheiron.domain`)은 표준 라이브러리에만 의존한다. Pydantic은 HTTP 스키마와 플래너 계약
(`application/planning.py`의 `PlanDraft`)에 쓰며, 이 계약은 어떤 LLM 어댑터든 만족해야 하는 JSON
Schema 역할도 한다.

### 데이터베이스 없음

ClinicalTrials.gov가 정해진 원천 데이터이고 서비스는 상태를 저장하지 않는다. 로컬 사본(예:
일괄 다운로드 위의 DuckDB)이 있으면 정확하고 빠른 `GROUP BY`가 가능하지만, 검토자에게 수 GB의
적재 단계와 최신성 문제를 떠안긴다. 대신 `TrialSource` 포트 뒤에 캐시를 둔다(아래). 나중에
데이터베이스 기반 소스로 바꿔도 핵심은 건드리지 않는다.

### 공개된 데이터 스냅샷에 맞춘 캐시

캐시하기 전에, 데이터가 얼마나 자주 바뀌는지 추측하지 않고 측정했다.

- `/version`은 스냅샷 시각(`dataTimestamp`)을 알려 준다. 2026-10-13(화)에도 금요일 값인
  `2026-10-09T09:00:05`였다.
- 2주간 `LastUpdatePostDate`로 시험을 세어 보니, 미국 영업일마다 약 800–1,200건(606,601건의
  약 0.17%)이 갱신되고 주말과 2026-10-12 연방 공휴일에는 없었다. 즉 갱신은 영업일마다 한 번에
  묶여 들어온다.
- 코호트별로 보면 일주일 동안 갱신된 시험은 0.9%(유방암)에서 4.3%(모집 중인 폐암)였다.

그래서 결과는 다음 스냅샷이 공개될 때까지 유효하다. `CachingTrialSource`(ClinicalTrials.gov
어댑터를 감싼 데코레이터)는 검색 결과, 시험 이름 조회, 게시된 결과를 메모리에 두고,
`dataTimestamp`가 바뀌면 비운다. 이 값은 최대 10분마다 확인하고, 확인이 실패해도 최대 24시간이
지나면 버린다. 고정 TTL은 택하지 않았다. 주말 동안 유효한 결과를 버리고, 새 스냅샷 뒤에도 몇 시간
동안 낡은 결과를 줄 것이기 때문이다. 용량은 시험 수(30,000)로 세고(실측에 따라 시험 기관 정보가
있는 결과는 3배로 계산), 가장 오래 쓰지 않은 것부터 버린다. 효과: 같은 코호트에 대한 반복 또는
관련 질문(단계, 그다음 시작 연도)이 약 4초에서 약 10 ms로 줄었다. Redis도 검토했지만, API 프로세스가
하나인 지금은 공유 상태 이점 없이 컨테이너와 직렬화 코드만 늘어난다. API를 여러 대로 늘리면 같은
포트를 구현하면 된다.

### 반복 질문은 LLM 없이 답하기

"Which drugs are combined with pembrolizumab?"로 측정하니 첫 답은 9.3초, 반복할 때마다 2.3초였다.
그중 1.4–3.2초가 플래너였고 데이터는 캐시에서 0.2초 만에 나왔다. 두 캐시로 이를 없앴다.

- `CachingPlanner`(`QueryPlanner` 데코레이터)는 모델이 보는 모든 것을 키로 초안을 보관한다.
  질문(대소문자, 공백, 끝의 "?" 무시), 구조화 필드, 수정 피드백, 오늘 날짜("최근 5년" 해석에 영향).
  반복 질문은 이제 0.22초이고, 같은 질문에는 항상 같은 계획이 나온다.
- 데모는 이번 세션의 답을 채팅 서비스처럼 보관한다. "Recent" 목록에서 다시 볼 수 있고, 이미 한
  질문을 다시 하면 저장된 답을 쓰며, 새로고침하면 마지막 답을 복원한다. 답은 `sessionStorage`에
  둔다. 답마다 계산에 쓴 스냅샷(`meta.data_version`, 차트 위에 표시)을 갖고 있어서, 저장된 답을
  보여주기 전에 `GET /api/version`을 확인하고(서비스가 캐시하므로 수 ms), 서비스가 더 새 데이터를
  제공하면 질문을 다시 보낸다.

표현만 바꾼 질문은 여전히 플래너 호출이 한 번 든다(약 2초).

### 상한을 두고 직접 집계하기

API의 `/stats/field/values`는 *전체* 시험에 대한 통계만 주고 검색 필터를 받지 않는다(명세에서
확인). 그래서 필터를 건 집계는 서비스가 직접 해야 한다. `CtGovTrialSource`는 분석에 필요한
필드만 가져오고(1,000건 ≈ 1.9 MB, 페이지당 약 1.3초) 상한(코호트당 기본 5,000건, 최대 10,000건)까지
조회한다. 집계한 시험과 함께 `total_count`를 알려 주므로, 결과가 잘렸는지 응답에 드러난다.
기본 상한은 원래 2,000이었는데, 펨브롤리주맙 차트(2,974건)에서 Phase 1이 1,046이 아니라 699로
나온 뒤 올렸다. 잘렸다는 표시는 있었지만 절대 수치로는 오해를 부르기 때문이다.

### 상한을 넘는 정확한 건수

잘린 코호트는 예전에는 앞의 5,000건으로만 그렸다. 유방암(16,899건)은 Phase 2가 4,590이 아니라
1,362로 나왔다. 이제 분할(split) 없이 단계, 상태, 연구 유형, 주 스폰서 분류, 중재 유형을 세는
`count_by`라면, `run_plan`이 집계한 시험에 나온 범주마다 *전체* 일치 시험 중 그 범주에 해당하는
수를 등록부에 묻는다(범주당 `countTotal` 요청 하나, 코호트 조건에 범주를 Essie `AREA[...]` 절로
덧붙임). 막대는 그 수를 보여주고, 인용은 여전히 집계한 시험에서 가져오며, `meta.cohorts[]`에
`exact_counts: true`가 표시된다. 이 방식을 쓰기 전에, 알츠하이머병 시험 4,269건 전체에 대해 다섯
차원의 모든 범주(38개)의 등록부 건수를 우리 집계와 비교해 모두 같음을 확인했다. 실제 API 테스트가
더 작은 코호트(한국의 흑색종 시험)로 같은 비교를 반복한다.

비용은 API의 요청 한도가 정하는데, 명세에는 나와 있지 않다. 실측: 처음 약 10건은 한꺼번에
처리되고, 그 뒤로는 초당 약 1건이다(10초 창마다 정확히 10건 성공). 61건을 동시에 보내면 53건이
`429`를 받았다. 그래서 건수 요청은 하나씩 보내고, 답 하나당 최대 20건(`MAX_COUNT_REQUESTS`)으로
제한하며, 검색처럼 캐시한다. 검색이 캐시된 상태에서 6건은 1.2초, 11건은 12초 걸렸다. 한도를
넘거나, 등록부가 셀 수 없는 차원이거나, 건수 조회가 실패하면 평소처럼 안내와 함께 집계한 시험으로
그린다. 시작 연도(연도마다 요청, 약 50건), 상위 N개 차원(국가, 질환, 스폰서), 네트워크, 분포,
산포도는 집계한 시험 기준으로 남는다.

### 실제 API 데이터 다루기

실제 API(v2.0.5)를 조사하며 관찰한 것과 각각의 처리 방법이다.

| 관찰 | 처리 |
|---|---|
| 상품명과 코드가 동의어다: `Keytruda`, `MK-3475`, `pembrolizumab` 모두 2,974건을 돌려준다. | 자유 텍스트는 `query.*`로 보내 API의 동의어 확장을 활용한다. |
| `"` 하나만 잘못 들어가도 API가 `400`을 돌려준다. | 자유 텍스트에서 Essie 문법 문자를 지운다(`AREA[...]` 주입도 막는다). |
| 정확한 조건(단계, 상태, 국가, 시작 연도)은 `filter.*` / `AREA[...]` 문법이 필요하다. | `params.py`가 만들고, 실제 건수로 테스트했다. |
| 필드가 자주 비어 있고, 날짜는 `2021-05` 또는 `2021-05-27` 형태로 온다. | `Trial`의 모든 속성은 선택적이다. `PartialDate`는 날짜를 지어내지 않고 등록된 정밀도를 유지한다. |
| 열거값이 명세보다 늘어날 수 있다. | 모르는 값은 필드 단위로 버리고 시험은 유지한다. |
| 시험은 기관마다 장소를 하나씩 나열한다(시험당 수백 개). | `Trial.countries`는 중복을 없앤다. 한 시험은 국가마다 한 번만 센다. |
| 약물이 아닌 항목도 중재로 등록된다(예: "Laboratory Biomarker Analysis", 유형 `OTHER`). | 약물 네트워크는 `DRUG` / `BIOLOGICAL` 중재만 쓴다. |
| 국가 필터는 변형 표기를 찾아 준다(`USA`, `UK`, `Korea, Republic of`가 `United States`, `United Kingdom`, `South Korea`와 일치). 저장된 값은 한 가지 표기다(226개). | 필터에는 국가명 정규화가 필요 없고, 차트는 저장된 표기를 보여준다. |
| 아직 시작하지 않은 시험은 예정 시작일을 갖고, 미래 연도도 있다. | 시계열은 최근과 미래 연도가 잠정치라고 안내한다. |
| `/stats/field/values`는 국가 226개는 모두 주지만, 질환 약 134,000개, 중재명 약 537,000개, 스폰서 약 52,000개는 상위 250개만 준다. 중재 상위 목록의 맨 앞은 "Placebo", "Control", "No intervention", "Usual Care"다. | `GET /api/options`는 전체 국가 목록을 드롭다운으로, 상위 용어(이런 비검색어는 빼고 대소문자 중복은 합침)를 추천어로 준다. 자유 입력도 된다. |
| 책임자 항목이 역할, 부서, 회사인 경우가 많다: 약 6,000건 조사에서 "Clinical Sciences & Operations"(239), "Teva Medical Expert, MD"(107), "Medical Director"(106), "Medical Monitor"(90), 상담 전화 문구, 스폰서 자신의 이름. | ACL은 사람 이름처럼 보이는 것만 남긴다(그 조사에서 뽑은 패턴 목록. 스폰서명 규칙은 개인 스폰서에는 적용하지 않는데, 이들은 흔히 직접 연구자이기 때문이다). |
| 한 사람이 여러 표기로 나온다: "Benoit Girard, MD" / "Benoit Girard, M.D.", "James D. Carlson, Pharm.D."는 네 가지. | 연구자 노드는 첫 쉼표 뒤의 학위를 떼고 키로 삼는다. 그래서 "Do", "Ma" 같은 성은 유지된다. |
| 기관명이 일반적인 경우가 많다: "Research Site"(질환 세 개에서 5,880곳), "GSK Investigational Site"(2,264), "Local Institution", 상담 전화 문구. | 일반적인 기관명은 버린다. 기관은 기관명 + 도시 + 국가로 구분하므로 "University Hospital, Basel" ≠ "University Hospital, Zurich". |
| 장소마다 기관명과 도시가 붙으면 응답이 두 배가 되고(1,000건당 1.9 → 4.1 MB), 한 시험이 1,151개 기관을 나열하기도 한다(약 660,000개 기관 쌍). | 기관 필드는 기관 노드가 있는 계획에서만 가져온다. 네트워크 연결은 가장 빈도 높은 4 × `max_nodes`개 노드 사이에서만 센다(펨브롤리주맙 기관 네트워크: 25.8초 → 6.4초, 결과 동일). |
| `pageSize=0`은 0이 아니라 기본값(10)이다. 이후 페이지는 첫 페이지의 매개변수를 반복해야 한다. | `client.py`에 반영하고 테스트했다. |
| 시험 이름이 모호하다. "KEYNOTE-189"는 40명 규모 일본 확장 연구에만 보조 ID로 있고, 616명 본 시험은 제목에만 있다. 관찰 연구 "에뮬레이션"도 이 이름을 언급한다. ID로만 찾으면 엉뚱한 시험이 나온다. | `find_trials`는 약칭, 연구 ID, 제목을 모두 찾는다. `choose_trial`: 약칭 정확 일치 우선, ID/제목은 특징 있는 이름(숫자나 여러 단어)일 때만, 결과를 게시한 시험만, 모집 인원이 가장 큰 시험 선택, 나머지는 안내와 함께 `meta.trial.alternatives`로. |
| 등록부는 "KEYNOTE-189"를 한 단어로 색인한다: "KEYNOTE 189"는 아무것도 못 찾는다. 흔한 단어("RECOVERY")는 제목 5,682개에 있다. | 이름을 하이픈으로 이어서도 찾는다. 약칭은 따로 질의하고, 흔한 단어 하나는 약칭에만 일치시킨다. |
| 게시된 결과: 도달하지 않은 중앙값은 "NA"로 게시된다. 산포는 한계값 또는 퍼짐 정도로 온다. 이상반응 그룹에 위험 노출 2명인 교차 그룹이 있다. 두 그룹의 제목이 같을 수 있다. | "NA"는 텍스트로 두고 null로 그리며 안내한다. 퍼짐 정도는 값 ± 퍼짐으로 바꾼다. 위험 노출 10명 미만 그룹은 이상반응 차트에서 빼고 안내한다. 제목이 같으면 그룹 ID를 붙인다. |
| `429` / `5xx` 응답. | 백오프(1초, 2초, 4초)로 재시도한다. `4xx`는 API 메시지와 함께 바로 실패한다. |

### 이름: `Study`가 아니라 `Trial`

ClinicalTrials.gov는 기록을 "study"라 부르고, 엄밀히는 임상시험이 아닌 관찰 연구와 확대 접근
프로그램도 포함한다. 도메인은 사용자의 말인 `Trial`을 쓰고 `study_type`으로 종류를 구분한다.
"study"가 "trial"이 되는 곳은 ACL이다.

### 두 개의 입구: 구조화된 계획과 자연어

`POST /api/visualize`는 LLM이 계획을 쓰게 하고, `POST /api/plans`는 계획을 바로 실행한다. 둘은
같은 `run_plan` 유스케이스를 실행하고 같은 응답을 돌려준다. 질문에 대한 답의 `meta.plan`은 그대로
유효한 `/api/plans` 요청이라, 해석을 손으로 고쳐 다시 실행할 수 있다(데모가 이렇게 한다). LLM이
공개 계획 스키마 대신 별도의 `PlanDraft`를 쓰는 이유는, 초안에 근거 확인용 필터별 인용이 붙기
때문이다. 구조화 엔드포인트는 재현 가능한 결과를 주고, LLM 없이 핵심을 검증하게 해 주며, 계획을
직접 만드는 클라이언트도 쓸 수 있다.

### 프론트엔드: 질문별 화면이 아닌 범용 렌더러

React 데모(`frontend/`)는 채팅 서비스처럼 동작한다. 질문 입력창은 화면 아래에 고정되어 있고, 답은
그 위로 질문을 어떻게 이해했는지와 함께 나오며, 그 결과 계획을 고쳐 다시 실행할 수 있다. 등록부에
정해진 목록이 있는 필터는 직접 입력하지 않고 고르게 했고(시험 수가 붙은 국가 드롭다운, 단계와
상태 칩, 연도 선택), 나머지(약물, 질환, 스폰서)는 `GET /api/options`의 추천어를 준다. 적용된 필터는
지울 수 있는 칩으로 보인다. 단일 시험이면 사용한 시험을 링크와 함께 보여주고, 같은 이름에 걸린 다른
시험으로 바꿀 수 있다. 각 차트 위의 탭으로 답의 여러 보기(예: Bars / Map / Donut)를 오간다. 거절과
"결과 미게시"는 오류가 아닌 중립적인 안내로 나오고, 이전 차트를 대신한다.

렌더링은 질문에 대해 아무것도 모른다. `type` + `encoding`을 Vega-Lite(오차 막대를 선택적으로 단
막대, 누적 막대, 히트맵, 지도, 도넛, 선, 포레스트 플롯, 시계열, 히스토그램, 산포도) 또는
Cytoscape(네트워크)로 옮기고, 클릭한 데이터의 인용을 보여줄 뿐이다. 명세만으로 모든 차트 종류를
그린다는 사실이, 명세를 추측 없이 그릴 수 있다는 증거다. 이렇게 쓰면서 문제 두 개를 찾았다.
하나는 렌더러 쪽으로, 미리 구간을 나눈 히스토그램은 Vega-Lite에 `bin: {binned: true}`가 필요했다.
다른 하나는 명세 쪽으로, "korea"로 입력한 국가는 제대로 걸러졌지만 제목에 나오지 않아 걸러지지 않은
차트처럼 보였다(이제 제목에 공유 필터를 적는다).

### 모노레포와 Docker

저장소 하나에 폴더 두 개(`backend/`, `frontend/`)와 `docker-compose.yml`이다. JS 패키지가 하나뿐이라
모노레포 도구(Nx, Turborepo)는 보탤 것이 없다. Docker 덕분에 검토는 명령 하나로 되고, 검토자 컴퓨터에
uv도 Node도 필요 없다.

### Python 3.14

Python 3.14 이상을 대상으로 한다(기본으로 지연 평가되는 어노테이션. 3.12는 보안 수정만 받는다).
로컬에서는 uv가 인터프리터를 준비하고, Docker 이미지는 `python:3.14-slim`이다.

## 한계와 향후 개선

- 조회 상한을 넘는 결과는 API가 돌려준 앞의 N건(정렬되지 않음)으로 분석하고, `meta`가 이를
  표시한다. 다섯 차원은 범주별 건수를 등록부에서 채운다(위 참고). 시계열, 상위 N개 차트,
  네트워크, 히스토그램, 산포도는 채우지 않는다. 시간이 더 있다면: 요청 한도에 맞춘 시계열의 연도별
  건수(50년에 약 1분).
- 자유 텍스트 조건은 ClinicalTrials.gov의 검색에 기대므로, 설명에서 언급만 한 시험도 걸린다
  (펨브롤리주맙 시험의 11%, 폐암 시험 앞 5,000건의 24%). 코호트는 등록부의 검색이 정하므로 이런
  시험도 세지만, 인용에 표시하고 `meta.notes`에 그 수를 알린다. 시간이 더 있다면: 등록된 시험만
  세는 옵션.
- 요청 한도가 API 명세에 없다(실측: 처음 약 10건, 그 뒤 초당 약 1건). 클라이언트는 `429`를
  백오프로 재시도하지만 미리 속도를 조절하지는 않는다. 그래서 큰 코호트 둘에 대한 첫 질문은 약
  30초 걸린다(10페이지와 건수 16건).
- 개체 이름은 대소문자와 공백만 무시하고 비교한다. 펨브롤리주맙 약물 네트워크에서
  "Pembrolizumab"은 중심 노드지만, "MK-3475"나 "favezelimab/pembrolizumab"로 등록된 것은 별도 노드로
  남는다. 시간이 더 있다면: 등록된 `otherNames`와 동의어 원천으로 합친다.
- 연구자와 기관의 자리표시자 판별은 실제 기록 조사에서 뽑은 패턴 목록이지 분류기가 아니다. 예를
  들어 "Bristol-Myers Squibb"는 등록된 스폰서가 아닌 시험에서는 여전히 연구자로 통과한다.
- 여러 값을 가진 속성(단계, 국가, 질환, 중재)은 값마다 시험을 한 번씩 세므로, 막대 합이 시험 수보다
  클 수 있다. 응답의 `notes`가 이를 알린다.
- 산포도는 집계한 시험마다(상한까지) 점 하나를 돌려주므로 응답이 가장 크다(실측: 펨브롤리주맙
  2,969건에 2.1 MB, 단계 막대 차트는 10 KB). 시간이 더 있다면: 점과 인용에 중복된 제목을 빼거나
  표본을 뽑는다.
- 캐시는 한 프로세스 안에 있어서 재시작하면 사라지고 API 복제본 사이에 공유되지 않는다. Redis 기반
  `TrialSource` 데코레이터가 두 한계를 없앨 것이다.
- 캐시되지 않은 큰 코호트 질문은 몇 초 걸린다(API의 페이지 토큰 때문에 1,000건 단위 페이지를
  순서대로 받아야 한다).
- 데모 번들은 1.5 MB다(대부분 Vega). 코드 분할은 하지 않았다.
- 근거 확인은 필터를 질문에서 말했다는 것만 증명하고, 올바르게 옮겼다는 것은 증명하지 못한다.
  인용된 "late-stage"를 `PHASE3`로 옮겨도 통과한다. `meta.interpretation`과 고칠 수 있는 계획이
  보완책이다.
- 처음 하는 질문에는 계획 수립에 약 1.5–2초가 더 든다. 같은 질문은 계획을 재사용하지만(위 참고),
  표현이 다른 질문은 다시 계획한다.
- 한 번에 한 질문: 이전 답을 가리키는 후속 질문은 지원하지 않는다.
- 평가는 영어 질문만 다룬다. 다른 언어는 시험하지 않았다.
- 결과가 있는 여러 시험에 걸리는 시험 이름은 가장 큰 시험으로 정한다. 어느 것이 "본" 시험인지 아는
  것이 아니라 규칙이므로, 대안을 항상 함께 보여준다.
- 대체 보기는 행의 인용을 반복해 응답의 약 3분의 2를 차지한다(펨브롤리주맙 약물 네트워크 2,081 KB 중
  1,351 KB, gzip으로는 전체 132 KB). 시간이 더 있다면: 보기가 기본 차트의 행을 참조하게 한다.
- 언급 역할은 최대 6개 문장과 제목에 대한 LLM의 해석이다. 해석이 갈리는 기록(관찰 연구에서 약을
  "받을 예정인" 환자)에서는 실행마다 달라질 수 있다. 역할과 함께 보여주는 인용으로 읽는 사람이 확인할 수 있다.
- 지도는 막대 차트의 국가(기본 상위 15개)만 보여주고, 모든 국가를 보여주지는 않는다.
- 군집은 표시된 부분 그래프(기본 상위 30개 노드)로 계산하고 모듈러리티도 높지 않다(예시에서
  Q ≈ 0.2). 군집은 경향이지 엄격한 분할이 아니다. 이름 변형("Fluorouracil", "5-fluorouracil")은 별도
  노드로 남고 한 군집에 들어갈 수 있다.
- 단일 시험 차트는 값 척도를 하나만 보여주고(처음 선택된 결과 지표의 측정 방식과 단위. 나머지는
  안내에 나열), 가장 잦은 이상반응 15개를 보여준다. 시험 사이의 결과 비교는 하지 않는다.

_남은 단계가 끝나면 보완한다._

## 실행 예시

_예정(5단계):_ 서비스가 실제로 만든 JSON과 함께 질의 3–5개.

## AI 도구 사용과 검증

_작성자가 마무리할 예정._ 지금까지:

- **도구:** Claude Code(Claude Opus 5.5)를 API 탐색, 코드, 테스트의 페어 프로그래머로 썼다.
- **검증:** 코딩 전에 OpenAPI 명세(`docs/ctgov-openapi-v2.0.5.yaml`)를 읽고 매개변수 동작을 실제
  API로 확인했다. 오프라인 테스트는 녹화한 API 페이지(`backend/tests/fixtures/ctgov/`)를 쓴다.
  `pytest -m live`가 계약을 다시 확인한다(실제 시험 1,000건이 오류 없이 변환되고, 동의어와 정확
  필터가 반환된 시험에서 성립하는지).
- **집계 교차 검증:** 펨브롤리주맙 시험 2,974건 전체의 단계별 건수가, 모든 단계에서 같은 질의를 그
  단계로 거른 API 자체의 `countTotal`과 같다(`backend/tests/application/test_live_cross_check.py`).
- **실제 데이터 시험 실행:** 단위 테스트를 쓰기 전에 모든 계획 종류(단계 분포, 시계열, 약물 A 대
  B, 국가, 단계 × 스폰서 분류, 약물 및 스폰서–약물 네트워크, 히스토그램, 산포도)를 실제 데이터로
  돌려 살폈다. 위에 적은 예정 시작일과 국가 변형 표기 동작이 이때 드러났다.
- **브라우저에서 처음부터 끝까지:** 데모의 모든 예시를 React 화면에서 실제 API로 실행하고, 데이터를
  클릭해 인용도 확인했다. 히스토그램 렌더링 버그와 비좁은 네트워크 배치를 이렇게 찾아 고쳤다.
- **플래너 평가:** `pytest -m llm`이 실제 모델로 19개 사례를 돌려 계획 종류, 매개변수, 정확한
  필터(필터가 하나만 더해져도 실패)와 거절을 확인한다. 모델별 결과는
  [AI 설계](#ai-설계-질문에-근거한-계획)에 있다. 오프라인 테스트는 근거 확인 규칙, 수정 단계,
  OpenAI 어댑터(가짜 전송으로 요청 형태와 파싱), `/api/visualize`의 모든 상태 코드를 다룬다.
- **Docker:** `docker compose up --build`를 실행했다. API 컨테이너는 healthy로 보고되고, root가
  아닌 사용자로 실행되며, nginx 프록시를 거쳐 계획을 처리한다.

## 진행 상황

| 단계 | 범위 | 상태 |
|---|---|---|
| 1 | 프로젝트 설정, ClinicalTrials.gov 어댑터(ACL, 질의 매개변수, 페이지 조회, 재시도) | 완료 |
| 2 | AnalysisPlan 문법, 인용이 붙는 집계, 차트 빌더, `run_plan` 유스케이스 | 완료 |
| 2b | 모노레포, `POST /api/plans`, React 렌더러, 캐시, Docker Compose | 완료 |
| 3 | 근거 확인을 갖춘 LLM 플래너, `POST /api/visualize`, 플래너 평가, 화면의 질문 입력창 | 완료 |
| 4 | 실행 예시, README 마무리 | 다음 |

### 프로젝트 구조

```
backend/
  src/cheiron/
    domain/                        표준 라이브러리만 사용
      trial.py, trial_filter.py      Trial, 열거형, TrialFilter
      analysis.py                    AnalysisPlan 문법: CountBy, CoOccurrence, Distribution, Correlation
      facets.py                      차원/개체/측정값별 Trial의 값과 근거
      charts/                        계획 종류마다 빌더 하나 → Visualization
      visualization.py               출력 명세: 차트 유형, 채널, 인용
      charts/views.py                기본 차트의 행에서 만드는 대체 보기
      charts/communities.py          네트워크용 탐욕적 모듈러리티 군집
      membership.py                  시험이 코호트에 속하는 근거: 등록값, 원문 문장
      geography.py, country_codes.json   등록부 국가명 -> ISO 3166-1 숫자 코드
      results.py                     시험의 게시된 결과 지표와 이상반응
    application/
      ports.py                       TrialSource 포트, TrialSearchResult
      run_plan.py                    유스케이스: 코호트 동시 조회, 차트 생성, 잘림 보고
      planning.py                    PlanDraft(LLM 계약), Question, 근거 확인 규칙
      options.py                     등록부 어휘에서 만든 필터 선택지, 캐시
      trial_lookup.py                이름이 가리키는 시험(규칙과 대안)
      visualize.py                   유스케이스: 수정 한 번을 포함한 계획, 그다음 run_plan
      mentions.py                    유스케이스: LLM이 언급 이유를 판정, 인용은 원문과 대조
    adapters/
      inbound/http/                  FastAPI 라우트와 Pydantic 스키마
      outbound/openai_planner.py     OpenAI structured outputs 기반 QueryPlanner, 플래너 지시문
      outbound/openai_mentions.py    OpenAI structured outputs 기반 MentionJudge
      outbound/ctgov/                ClinicalTrials.gov 클라이언트, 질의 매개변수, ACL 매퍼(시험, 결과)
      outbound/caching.py            데코레이터: 데이터 스냅샷 기준 등록부 데이터, 계획, 판정
    main.py                        조립 지점(composition root)
  tests/                           단위, HTTP, 캐시, 플래너 테스트, 녹화한 응답,
                                   실제 API 확인(-m live), 플래너 평가(-m llm)
  Dockerfile
frontend/                          React + TypeScript(Vite): 범용 명세 렌더러
  src/charts/toVegaLite.ts         명세 → Vega-Lite(지도 도형은 world-atlas, 번들에 포함)
  src/components/                  차트, 네트워크, 인용, 메타, 질문 입력창, 필터
  src/history.ts                   이번 세션의 답, 요청 없이 다시 보기
  Dockerfile, nginx.conf           nginx 뒤의 정적 빌드, /api는 API로 중계
docker-compose.yml
docs/                              API 명세(v2.0.5), 한국어 도메인 용어 정리
```
