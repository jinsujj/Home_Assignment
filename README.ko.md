# Cheiron — ClinicalTrials.gov 질의-시각화 에이전트

[English](README.md) | 한국어

임상시험에 대해 자연어로 물으면, 실시간 [ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api)
데이터로 계산한 차트 명세를 돌려준다. 어떤 프론트엔드든 그대로 그릴 수 있고, 막대·점·노드·연결마다
그 뒤의 임상시험 기록을 인용한다.

- **하나의 문법, 여러 차트.** LLM이 질문을 다섯 가지 분석 계획 중 하나로 바꾸고, 결정적 코드가 데이터를
  가져와 차트를 만든다. 막대, 묶음 막대, 시계열, 히스토그램, 산포도, 네트워크, 단일 시험의 게시 결과를
  지원하며, 각각 대체 보기(지도, 도넛, 히트맵, 100% 누적, 누적 선, 포레스트 플롯)를 함께 준다.
- **LLM은 숫자를 쓰지 않는다.** 열거형으로 계획을 세우고 필터마다 질문의 단어를 인용한다. 인용이 없는
  필터는 고치거나 버리고, 답할 수 없는 질문은 거절한다.
- **심층 인용.** 데이터 항목마다 시험을 나열하고, 그 시험을 그 항목에 넣은 API 필드와 값, 그리고 필터한
  약물이나 질환을 언급하는 기록 원문을 함께 보여준다.
- **표본을 넘는 정확한 수.** 큰 코호트는 등록부가 직접 세거나 모든 기록을 집계한다(25,000건까지). 각 수에는
  그 수를 재현하는 API 요청 링크가 붙는다.
- **구조가 있는 네트워크.** 군집, 기준점, 연관 강도를 보여준다. 같은 군에서 병용된 약물과 다른 군에서
  비교된 약물을 나누고, 주관 스폰서와 협력 스폰서를 나눈다.
- **대화.** 숫자를 데이터와 대조한 짧은 답, 이전 계획을 다듬는 후속 질문, 미리 계획해 둔 다음 질문 추천.
- **데모.** React 화면이 명세만으로 모든 차트 유형을 그린다.

결정마다의 이유와 실측값은 [docs/design.ko.md](docs/design.ko.md)에, 실제 JSON을 포함한 실행 예시 다섯 개는
[아래](#실행-예시)에 있다.

## 사용자 입장에서 본 질문 하나

![질문하고, 답을 읽고, 근거를 열고, AI 확인을 거쳐 이어 묻는 과정](docs/images/cheiron-demo.gif)

<sub>2026-10-13 등록부 스냅샷으로 데모에서 녹화했다. 질문, 답변 문장과 근거, 막대의 인용, 그 인용에 대한 AI
확인, 추천 후속 질문 순서다.</sub>

데모(<http://localhost:8080>)는 연구자가 질문을 다루는 순서를 따른다. 묻고, 읽고, 확인하고, 다듬는다. 단계마다
페이지를 떠나지 않고도 믿을 수 있는 답을 주도록 설계했다.

1. **평범한 말로 묻는다.** "Compare phases for trials involving Keytruda vs Opdivo." 화면은 질문을 어떻게
   이해했는지("Understood as …"), 차트, 같은 숫자의 다른 보기 탭(100% 누적, 히트맵. 답이 국가면 세계 지도)을
   보여준다.
2. **차트만이 아니라 답을 읽는다.** 차트 위에 몇 문장의 답이 나온다. 예를 들어 두 약 모두 2상이 가장 많고,
   Keytruda 1,777건, Opdivo 1,164건이라는 식이다. 모든 숫자를 데이터와 대조했고, 문장마다 "sources"가 근거
   막대를 연다.
3. **막대, 점, 노드, 연결을 누르면 이유가 보인다.** 인용 패널이 그 뒤의 시험을 나열한다. 시험마다 그 항목에
   넣은 등록 필드와 값, 그리고 약물이나 질환을 언급하는 기록의 문장을 ClinicalTrials.gov 링크와 함께 보여준다.
   "List the other trials"로 처음 다섯 건 너머를 20건씩 본다.
4. **AI가 시험을 읽게 한다.** 등록부 검색은 약 이름을 언급만 한 시험도 돌려준다. "Ask AI what Keytruda is to
   these trials"는 각 기록을 읽고, 그 약이 연구 대상인지, 함께 투여하는지, 등록 조건인지, 배경일 뿐인지를
   기록을 인용해 알려준다. 기록에 없는 인용은 받아들이지 않는다.
5. **다시 쓰지 않고 이어 묻는다.** "Ask next"가 이미 계획해 둔 후속 질문("Only recruiting trials", "By country
   instead")을 보여주고, 직접 입력("only phase 3")해도 된다. 질문 상자 위의 칩이 지난 답을 다듬는 질문임을
   알리고, 이전 질문에서 유지한 필터는 안내로 나열된다.
6. **숫자를 믿을 수 있다.** 5,000건 표본을 넘는 수도 정확하고, 막대마다 그 수를 재현하는 API 요청 링크가 붙는다.
   데이터 스냅샷이 표시되고, Recent는 이전 답을 바로 다시 열며, 등록부가 새 데이터를 낸 경우에만 다시 묻는다.

같은 흐름이 추세, 지도, 네트워크(병용 또는 비교된 약물, 주관 또는 협력한 스폰서), 신뢰구간이 있는 단일 시험의
게시 결과에도 그대로 적용된다. 모든 단계 뒤에는 하나의 원칙이 있다. LLM은 해석하고 쓰며, 코드는 계산하고
확인한다([동작 방식](#동작-방식)).

## 빠른 시작

```bash
cp .env.example .env          # OPENAI_API_KEY 설정
docker compose up --build     # 화면 http://localhost:8080 · API http://localhost:8080/api · 문서 /api/docs
```

| 변수 | 기본값 | 용도 |
|---|---|---|
| `OPENAI_API_KEY` | — | `/api/visualize`, `/api/answers`, `/api/mentions`에 필요. `/api/plans`는 없어도 동작 |
| `OPENAI_MODEL` | `gpt-5.4-mini` | 모든 LLM 역할의 모델 |
| `OPENAI_REASONING_EFFORT` | `low` | 계획기와 답변 작성기. 추론 기능이 없는 모델이면 빈 값 |
| `OPENAI_MENTION_REASONING_EFFORT` | `high` | 언급 판정 |

로컬 개발에는 [uv](https://docs.astral.sh/uv/)(Python 3.14를 설치해 준다)와 Node 22가 필요하다.

```bash
cd backend && uv sync && uv run --env-file ../.env uvicorn cheiron.main:app --reload   # :8000
cd frontend && npm install && npm run dev                                           # :5173
cd backend && uv run pytest                                  # 오프라인 테스트 324개
uv run pytest -m live                                        # 실제 API 계약 확인
uv run --env-file ../.env pytest -m llm                      # LLM 평가(실제 모델)
cd ../frontend && npm run build && npm run lint              # 타입 검사, 빌드, 린트
```

## API

| 엔드포인트 | 용도 |
|---|---|
| `POST /api/visualize` | 질문(+ 선택 필터, 후속 질문이면 `context`) → 계획 → 시각화 |
| `POST /api/answers` | 같은 요청 + 그 질문에 답한 `plan` → 짧은 답과 미리 계획한 후속 질문 |
| `POST /api/plans` | LLM 없이 분석 계획을 바로 실행(어떤 답의 `meta.plan`이든 그대로 요청이 된다) |
| `POST /api/mentions` | 시험이 어떤 단어를 왜 언급하는지(연구 대상, 함께 투여, 등록 조건, 배경), LLM 판정과 검증된 인용 |
| `GET /api/options` | 필터 선택지: 시험 수가 붙은 등록부 국가, 흔한 용어, 단계와 상태 코드 |
| `GET /api/version` | 현재 제공 중인 등록부 데이터 스냅샷 |
| `GET /api/docs` | 스키마에서 생성한 OpenAPI 문서 |

### 요청: `POST /api/visualize`

```json
{ "query": "How has the number of trials for this drug changed over time?", "drug_name": "Pembrolizumab" }
```

| 필드 | 타입 | 규칙 |
|---|---|---|
| `query` | 문자열, 1–1,000자 | 필수 |
| `drug_name`, `condition`, `sponsor` | 문자열 ≤ 200 | 선택. 모든 코호트에 적용되고 계획기보다 우선 |
| `country` | 문자열 ≤ 100 | 선택. 그 나라에 사이트가 하나라도 있는 시험 |
| `phases`, `statuses` | 등록부 코드 목록(`PHASE3`, `RECRUITING`, …) | 선택. 그중 하나라도 |
| `start_year`, `end_year` | 정수 1900–2100 | 선택. start ≤ end |
| `nct_id` | `NCT` + 숫자 8자리 | 선택. 시험 결과 질문에서 이 시험을 쓴다 |
| `context` | `{"questions": [...], "plan": {...}}` | 선택. 후속 질문의 이전 질문들(5개 이하)과 마지막 답의 `meta.plan` |
| `max_trials_per_cohort` | 정수 1–10,000 | 기본값 5,000 |
| `all_citation_ids` | 불리언 | 기본값 `false`. 데이터 항목마다 기여한 모든 NCT ID를 나열 |

모르는 필드와 잘못된 값은 `422`로 거부한다. 오류: 어떤 분석으로도 답할 수 없는 질문(`unsupported_question`과
`reason`), 없는 시험(`trial_not_found`), 결과를 게시하지 않은 시험(`no_posted_results`), 한 번 수정한 뒤에도
유효하지 않은 계획(`plan_rejected`)은 `code`가 붙은 `422`. ClinicalTrials.gov 실패는 `502`, LLM 키가 없으면 `503`.

### 응답

```jsonc
{
  "visualization": {
    "type": "grouped_bar_chart",
    "title": "Trials by phase — Keytruda vs Opdivo",
    "encoding": {
      "x": { "field": "phase", "type": "ordinal", "title": "Phase", "order": ["Early Phase 1", "..."] },
      "y": { "field": "trial_count", "type": "quantitative", "title": "Number of trials", "unit": "trials" },
      "series": { "field": "cohort", "type": "nominal", "title": "Cohort", "order": ["Keytruda", "Opdivo"] }
    },
    "data": [ { "phase": "Phase 3", "cohort": "Keytruda", "trial_count": 369, "citations": { ... } }, "..." ]
  },
  "alternatives": [ { "type": "stacked_bar_chart", "...": "...", "notes": [ "..." ] }, { "type": "heatmap", "...": "..." } ],
  "meta": {
    "source": "clinicaltrials.gov",
    "query": "Compare phases for trials involving Keytruda vs Opdivo.",
    "interpretation": "I will compare the phase distribution of trials involving Keytruda versus trials involving Opdivo.",
    "plan": { "kind": "count_by", "cohorts": [ "..." ], "dimension": "phase" },     // 그대로 다시 실행 가능
    "cohorts": [ { "label": "Keytruda", "matched": 2974, "analyzed": 2974, "truncated": false,
                   "exact_counts": false, "names": ["Keytruda", "Pembrolizumab"] } ],
    "notes": [ "175 of 2974 trials in Keytruda have no registered phase and are not shown.", "..." ],
    "note_citations": [ { "note": "175 of 2974 trials ...", "citations": { ... } } ],
    "data_version": "2026-10-09T09:00:05"
  }
}
```

인코딩 채널은 모두 `{ field, type, title, order, unit, time_unit, scale }`이다. `type`은 Vega-Lite의
`nominal`, `ordinal`, `quantitative`, `temporal` 중 하나이고, `order`는 그릴 범주 순서, `scale`은 `null` 또는
`"symlog"`다.

| `type` | 채널 | `data` |
|---|---|---|
| `bar_chart` | `x`, `y` | 범주마다 한 행 |
| `grouped_bar_chart` | `x`, `y`, `series`(시험 결과면 `y_lower`, `y_upper` 추가) | 범주 × 계열마다 한 행, 0 포함 |
| `time_series` | `x`(`time_unit: "year"`), `y`, 선택적 `series` | 연도마다 한 행, 빈 해는 0 |
| `histogram` | `x`(`bin_start`), `x2`(`bin_end`), `y` | 구간 `[start, end)`마다 한 행 |
| `scatter_plot` | `x`, `y`, `tooltip` | 시험마다 한 행 |
| `network_graph` | `node_id`, `node_label`, `node_size`, `node_color`(군집), `node_shape`(종류), `edge_source`, `edge_target`, `edge_weight`(공유 시험), `edge_strength`(연관도), `edge_style`(병용/비교, 주관/협력) | `{ "nodes": [...], "edges": [...] }` |
| 대체 보기 | `stacked_bar_chart`, `heatmap`, `choropleth_map`(ISO 3166-1 숫자 `region`), `donut_chart`, `line_chart`, `forest_plot` | 기본 차트의 행에서 계산 |

### 인용

모든 행, 노드, 연결에 `citations`가 붙는다.

```json
{ "total": 369,
  "items": [ { "nct_id": "NCT04003636",
               "title": "Pembrolizumab (MK-3475) Plus Gemcitabine/Cisplatin ... (KEYNOTE-966)",
               "url": "https://clinicaltrials.gov/study/NCT04003636",
               "evidence": [ { "field": "protocolSection.designModule.phases", "value": "PHASE3" },
                             { "field": "protocolSection.armsInterventionsModule.interventions.name", "value": "Pembrolizumab" } ],
               "excerpt": "phases: PHASE3; interventions.name: Pembrolizumab",
               "mentioned_only": [] } ],
  "nct_ids": null,
  "registry_query": null }
```

- `evidence`는 API 연구 JSON 안의 필드 경로와 등록된 그대로의 값이고, `excerpt`는 이를 한 줄로 이은 것이다
  (과제 예시의 형태). 실행 예시의 근거 433건을 실제 기록과 대조하니 모두 일치했다. 341건은 필드 값과 같고,
  92건은 원문을 그대로 잘라낸 구절이다.
- `items`는 처음 다섯 시험을 자세히 보여주고, `total`은 전체 수다. `all_citation_ids`를 켜면 `nct_ids`가 모두를
  나열한다. `registry_query`는 등록부 수를 재현하는 API 요청이다.
- `mentioned_only`는 시험이 본문에서 언급만 하고 등록하지는 않은 필터 단어다(ClinicalTrials.gov 검색은
  둘 다 찾는다. `meta.notes`가 그 수를 알려준다).
- 대체 보기는 인용을 반복하지 않고 기본 차트의 인용을 참조한다: `{"$ref": "#/visualization/data/3/citations"}`.

## 동작 방식

```
질문 (+ 필터, + 대화)
  → 계획기 (LLM)      PlanDraft: 열거형으로 된 분석 계획, 필터마다 질문의 단어 인용
  → 근거 확인         인용을 질문(들)과 대조, 필터 적용, 도메인 규칙, 거부된 초안은 한 번 수정
  → 등록부            ClinicalTrials.gov API: 페이지 검색, 범주별 수, 전체 집계(스냅샷 단위로 캐시)
  → ACL               연구 JSON → 도메인 Trial(날짜, 군, 스폰서, 사이트, 게시 결과)
  → 차트              Trial[] → 시험과 근거를 유지한 묶음 → 시각화 + 인용
  → 답변 (LLM)        계산된 데이터만으로 쓴 문장, 모든 숫자를 인용한 데이터와 대조
```

환각 방지 장치와 실제 모델로 잰 결과(`pytest -m llm`):

| 단계 | 장치 | 평가 |
|---|---|---|
| 계획 | 열거형 JSON Schema(strict), 필터마다 원문 인용, 한 번의 수정, 이유 코드로 거절 | 정확한 필터까지 확인하는 26/26 사례(후속 질문 5개 포함) |
| 답변 | 문장이 인용한 항목에 있는 숫자만 허용, 행마다 순위 제공 | 답 15개 모두 문장 유지, 근거 없는 숫자로 4문장 제거 |
| 언급 판정 | 인용이 기록에 있어야 하고, 없으면 `unclear` | 직접 판정한 13건 중 실행마다 11–13건 일치 |
| 후속 질문 추천 | 보여주기 전에 계획해 보고, 계획되는 것만 표시 | 모든 답이 하나 이상 제시 |

## 주요 설계 결정과 트레이드오프

| 결정 | 이유 | 트레이드오프 |
|---|---|---|
| LLM은 계획하고, 코드가 계산한다 | 응답의 숫자는 모델에서 나오지 않는다. 결과가 재현되고 테스트할 수 있다 | 틀렸지만 유효한 계획은 가능하다. `meta.interpretation`이 보여주고, 계획을 고쳐 다시 실행할 수 있다 |
| 다섯 가지 계획 종류의 단일 문법 | 질문별 코드 없이 부록의 모든 질의 유형을 다룬다. 새 질문 유형은 열거형 값 하나와 그 값을 시험에서 읽는 방법이면 된다 | 문법 밖의 질문은 거절한다 |
| 가벼운 헥사고날 아키텍처 | 등록부와 LLM이 포트 뒤에 있어 네트워크 없이 핵심을 테스트한다. ACL이 API JSON을 매퍼 하나에 가둔다 | 스크립트보다 모듈이 많다. 저장할 것이 없어 애그리거트나 리포지토리는 두지 않았다 |
| 서비스에서 직접 집계, 상한 적용 | API에 필터를 건 통계 엔드포인트가 없다 | 큰 코호트는 표본(코호트당 5,000건)이 되므로, 범주별 수나 전체 기록 집계(25,000건까지, 처음 20–30초)로 수를 채운다 |
| DB 없이, 데이터 스냅샷에 맞춘 캐시 | API가 원천이고 영업일마다 한 번 갱신된다. `/version`이 바뀌면 캐시를 비운다 | 프로세스 안에만 있어 재시작하면 사라지고 복제본 사이에 공유되지 않는다 |
| 대체 보기는 기본 차트의 행에서 계산 | 모든 보기가 같은 숫자와 인용을 보여주고, LLM 호출이 더 들지 않는다 | 행이 뒷받침하는 보기만 만들 수 있다 |
| 필드 수준 인용과 JSON 참조 | 기록까지 추적된다. 참조로 약물 네트워크가 2,081 KB에서 804 KB로 줄었다 | 전체 ID 목록은 응답을 작게 두려고 선택 사항으로 했다 |
| 상태 없는 대화 | 클라이언트가 이전 질문과 계획을 보내고, 서버는 아무것도 저장하지 않는다 | 최근 질문 5개까지만 이어간다 |
| `/api/visualize` 옆의 `/api/plans` | LLM 없이 재현되는 실행, 해석을 손으로 고쳐 다시 실행 | 입구가 둘이지만 사용 사례는 하나를 공유한다 |

## 실행 예시

`POST /api/visualize`로 보낸 질문 다섯 개다(스냅샷 `2026-10-09T09:00:05`). 응답 전체는
[docs/examples](docs/examples/)에, 질문별 해설은 [docs/examples/README.ko.md](docs/examples/README.ko.md)에 있다.

| # | 질문 | 차트 | 결과 |
|---|---|---|---|
| 1 | How has the number of trials for pembrolizumab changed per year since 2015? | `time_series` | 2,909건, 2022년 299건이 최고, 예정 시작일 309건 표시 |
| 2 | Compare phases for trials involving Keytruda vs Opdivo. | `grouped_bar_chart` + 100% 누적, 히트맵 | 2상 1,777 대 1,164, 상표명을 약물로 인식 |
| 3 | Which countries have the most recruiting trials for cancer? | `bar_chart` + 지도, 도넛 | 18,769건 전체 집계: 미국 6,939(앞 5,000건만 보면 1,823) |
| 4 | Which drugs are combined with pembrolizumab? | `network_graph`(`link: same_arm`) | 카보플라틴 230, 시스플라틴 160, 파클리탁셀 144건, 군집 4개 |
| 5 | What were the results of the KEYNOTE-189 trial? | 구간이 있는 `grouped_bar_chart` + 포레스트 플롯 | 무진행 생존 중앙값 8.8 대 4.9개월, 위험비 0.52(95% CI 0.43–0.64) |

```bash
curl -s localhost:8080/api/visualize -H 'content-type: application/json' \
  -d '{"query": "Which countries have the most recruiting trials for cancer?"}'
```

## 한계와 향후 개선

- 네트워크, 히스토그램, 산포도, 분할 막대는 코호트의 앞 5,000건으로 계산한다. 시간이 더 있다면 한 차원
  집계처럼 전체 집계를 넓히겠다.
- ClinicalTrials.gov 검색은 단어를 언급만 한 시험도 찾는다(펨브롤리주맙의 11%). 등록부가 정의하는 코호트이므로
  세되 표시한다. 등록된 시험만 세는 옵션이 있으면 좋겠다.
- 개체 이름은 대소문자와 공백만 무시하고 맞춘다. 네트워크에서 "MK-3475"는 "Pembrolizumab"과 따로 남는다.
  등록된 다른 이름으로 합치는 것이 다음 단계다.
- 말로 하는 답은 숫자는 확인하지만 말은 확인하지 않는다. "가장 많다"는 순위가 붙은 항목을 모델이 읽은 결과다.
  답에는 LLM 호출이 하나 더 든다(처음에는 차트보다 7–15초 늦게).
- API의 요청 한도(처음 약 10건, 이후 초당 약 1건)는 문서에 없다. 요청은 재시도할 뿐 속도를 조절하지 않아,
  큰 코호트 둘에 대한 첫 질문은 약 30초 걸릴 수 있다.
- 캐시는 한 프로세스에만 있다. 같은 포트에 Redis 기반 데코레이터를 두면 공유할 수 있다.
- 평가는 영어 질문만 다룬다.

알려진 한계 전체: [docs/design.ko.md](docs/design.ko.md#21-알려진-한계-전체-all-known-limitations).

## AI 도구 사용과 검증

**도구.** Claude Code(Claude Opus 5.5)를 API 탐색, 코드·테스트·문서 작성의 페어 프로그래머로 썼다. 서비스
안에서는 OpenAI `gpt-5.4-mini`를 쓴다.

**역할 분담.** 작성자가 범위를 정하고 서비스의 모양을 결정했다. Claude Code는 설계를 제안하고 코드·테스트·문서
대부분을 작성하고 실측을 수행했다. 작성자는 변경마다 실제 등록부와 브라우저에서 결과를 확인하고, 고칠 것과 뺄
것을 정했다. 예를 들면 다음과 같다.

- 큰 코호트 차트가 표본이라는 점을 짚어 정확한 수를 요청했다.
- 말로 하는 답, 후속 질문, 다음 질문 추천을 요청했다.
- 언급 판정의 추론 강도를 정했다.
- 인용 아래에 시험 결과를 보여주는 기능은 차트의 숫자를 뒷받침하지 않아 뺐다.

**검증.**
- 코딩 전에 OpenAPI 명세를 읽고 실제 API에서 매개변수 동작을 확인했다. 오프라인 테스트는 녹화한 페이지를 쓰고,
  `pytest -m live`가 계약을 다시 확인한다.
- 집계는 등록부 자체의 수와 대조했다. 펨브롤리주맙 시험 2,974건의 모든 단계, 알츠하이머 시험 4,269건의
  38개 범주가 모두 같았다. 전체 집계한 연도와 국가도 등록부 검색과 일치한다.
- LLM 단계는 실제 모델로 평가한다(위 표). 그 출력을 읽다가 바꿔 말한 필터, 잘못 읽은 순위, 계획되지 않는
  추천 같은 문제를 찾아 고쳤다.
- 모든 차트 유형을 브라우저에서 처음부터 끝까지 실행했고, 이 과정에서 렌더러와 명세의 문제(히스토그램 구간,
  단위 중복, 페이지 번역 충돌)를 찾았다.

## 프로젝트 구조

```
backend/src/cheiron/
  domain/            Trial, TrialFilter, AnalysisPlan, facets, 차트 빌더, 인용(표준 라이브러리만)
  application/       사용 사례: run_plan, visualize(계획 + 근거 확인), answers, mentions; 포트
  adapters/inbound/  FastAPI 라우트와 Pydantic 스키마
  adapters/outbound/ ClinicalTrials.gov 클라이언트와 매퍼, OpenAI 계획기/답변 작성기/판정기, 캐시
  main.py            조립 지점
backend/tests/       단위·HTTP·캐시 테스트, 실제 API 확인(-m live), LLM 평가(-m llm)
frontend/src/        명세만으로 그리는 React + Vega-Lite + Cytoscape 렌더러
docs/                설계 노트, 실행 예시, API 명세
docker-compose.yml   api(FastAPI, 비root) + web(화면을 제공하고 /api를 프록시하는 nginx)
```
