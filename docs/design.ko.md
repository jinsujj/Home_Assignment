# 설계 노트 (Design Notes)

[README](../README.ko.md) · [English](design.md) | 한국어

README가 설계를 간략히 요약한다면, 이 문서는 각 설계 결정의 이유, 근거가 된 실측값, 그리고 실제 데이터로
테스트하면서 바뀐 점을 기록합니다.

## 목차

1. [심층 인용 상세 (Citations in depth)](#1-심층-인용-상세-citations-in-depth)
2. [LLM은 계획하고, 결정적 코드가 계산한다 (The LLM plans; deterministic code computes)](#2-llm은-계획하고-결정적-코드가-계산한다-the-llm-plans-deterministic-code-computes)
3. [AI 설계: 질문에 근거한 계획 (AI design: grounding the planner in the question)](#3-ai-설계-질문에-근거한-계획-ai-design-grounding-the-planner-in-the-question)
4. [AI 설계: 시험이 어떤 단어를 언급하는 이유 (AI design: why a trial mentions a term)](#4-ai-설계-시험이-어떤-단어를-언급하는-이유-ai-design-why-a-trial-mentions-a-term)
5. [AI 설계: 말로 하는 답과 다음 질문 (AI design: an answer in words, and what to ask next)](#5-ai-설계-말로-하는-답과-다음-질문-ai-design-an-answer-in-words-and-what-to-ask-next)
6. [모든 질문을 위한 단일 문법: AnalysisPlan (One grammar for every question)](#6-모든-질문을-위한-단일-문법-analysisplan-one-grammar-for-every-question)
7. [빈도가 아닌 구조를 보여주는 네트워크 (Networks with structure, not just counts)](#7-빈도가-아닌-구조를-보여주는-네트워크-networks-with-structure-not-just-counts)
8. [하나의 답, 여러 보기 (One answer, several views)](#8-하나의-답-여러-보기-one-answer-several-views)
9. [가벼운 헥사고날 아키텍처와 선택적 DDD (Lightweight hexagonal architecture, selective DDD)](#9-가벼운-헥사고날-아키텍처와-선택적-ddd-lightweight-hexagonal-architecture-selective-ddd)
10. [데이터베이스 없음 (No database)](#10-데이터베이스-없음-no-database)
11. [공개된 데이터 스냅샷에 맞춘 캐시 (Caching keyed to the published data snapshot)](#11-공개된-데이터-스냅샷에-맞춘-캐시-caching-keyed-to-the-published-data-snapshot)
12. [반복 질문은 LLM 없이 답하기 (Answering a repeated question without the LLM)](#12-반복-질문은-llm-없이-답하기-answering-a-repeated-question-without-the-llm)
13. [상한을 둔 자체 집계 (Aggregating on our side, with a cap)](#13-상한을-둔-자체-집계-aggregating-on-our-side-with-a-cap)
14. [상한을 넘는 정확한 건수 (Exact counts beyond the cap)](#14-상한을-넘는-정확한-건수-exact-counts-beyond-the-cap)
15. [실제 API 데이터 다루기 (Handling real API data)](#15-실제-api-데이터-다루기-handling-real-api-data)
16. [이름: Study가 아니라 Trial (Naming: Trial rather than Study)](#16-이름-study가-아니라-trial-naming-trial-rather-than-study)
17. [두 개의 입구: 구조화된 계획과 자연어 (Two entry points)](#17-두-개의-입구-구조화된-계획과-자연어-two-entry-points)
18. [프론트엔드: 질문별 화면이 아닌 범용 렌더러 (Frontend: a generic renderer)](#18-프론트엔드-질문별-화면이-아닌-범용-렌더러-frontend-a-generic-renderer)
19. [모노레포와 Docker (Monorepo and Docker)](#19-모노레포와-docker-monorepo-and-docker)
20. [Python 3.14](#20-python-314)
21. [알려진 한계 전체 (All known limitations)](#21-알려진-한계-전체-all-known-limitations)

## 1. 심층 인용 상세 (Citations in depth)

### 시험이 코호트에 속하는 근거

ClinicalTrials.gov에서 중재(intervention), 질환(condition), 스폰서를 검색하면 상세 설명 같은 다른 본문까지
함께 매칭됩니다.

- 펨브롤리주맙(pembrolizumab)으로 찾은 2,974건 중 335건은 펨브롤리주맙을 중재로 등록하지 않았습니다
  (예: 대변 미생물군 이식 연구).
- 폐암(lung cancer)으로 찾은 앞 5,000건 중 1,195건은 폐암을 질환으로 등록하지 않았습니다.

그래서 서비스는 자유 텍스트 필터마다 "그 단어를 언급만 한 시험"이 무엇인지 등록부에 따로 묻습니다(등록
필드에 대한 `NOT AREA[...]` 구문).

- **동의어는 등록된 것으로 봅니다.** "Keytruda", "MK-3475", "pembrolizumab"은 모두 같은 2,639건을 돌려줍니다.
- **등록한 시험**은 매칭된 등록값을 근거로 씁니다. 필터 단어와 겹치는 단어가 가장 많은 값, 없으면 코호트에서
  가장 흔한 값을 고르므로 "Keytruda"로 찾은 시험은 "Pembrolizumab"을 인용합니다.
- **언급만 한 시험**은 `mentioned_only`에 그 단어를 적고, 인용 목록 맨 뒤에 두며, `meta.notes`에 건수를 밝힙니다.
- **검증**: 실제 API 테스트가 3상 펨브롤리주맙 시험 전부에 대해 등록부의 판정과 등록된 약물명이 일치하는지
  확인합니다.
- **비용**: 자유 텍스트 필터마다 요청 1회, 그리고 그런 시험 1,000건마다 1회가 더 듭니다.
- **질환은 과하게 표시될 수 있습니다.** 더 좁은 등록명("Lung Adenocarcinoma", "NSCLC Stage IV")은 "lung
  cancer"와 일치하지 않아, 실제로 폐암을 연구하는 시험도 표시됩니다. 이를 가르는 것이
  [4절](#4-ai-설계-시험이-어떤-단어를-언급하는-이유-ai-design-why-a-trial-mentions-a-term)의 LLM 판정입니다.

### 그 단어를 언급하는 원문

인용된 시험(기여한 전체 시험이 아니라 자세히 보여주는 `items`)마다, 필터한 대상을 필터 단어나 등록된 이름으로
언급하는 원문 구절을 함께 인용합니다.

- **찾는 순서**: 제목, 공식 제목, 요약, 군(arm)과 중재 설명, 상세 설명, 키워드, 선정 기준. 제목과 요약은 시험
  자체를 설명하지만, 선정 기준은 이전 치료 같은 다른 약을 자주 언급하기 때문입니다.
- **구절**: 이름 주변의 문장이나 줄로, 최대 240자이며 단어 경계에서 자르고, 언제나 원문의 정확한 부분
  문자열입니다.
- **문장 경계**: 대문자 앞의 ". "나 줄바꿈에서만 문장이 끝납니다. 그래서 "e.g. pembrolizumab", "etc.",
  "2.5 mg"에서 끊기지 않습니다. 이 규칙 전에는 실제 기록에서 "g pembrolizumab)"처럼 잘리는 문제가 나왔습니다.
- **요청**: 인용된 시험의 원문은 200건마다 요청 1회(`filter.ids`)로 받습니다. 받지 못하면 인용은 등록값 근거만
  유지합니다.

### 응답 크기

펨브롤리주맙 기준 실측값입니다.

| 답 | 응답 크기 | gzip | 대체 보기가 인용을 참조하기 전 | `all_citation_ids` 사용 시 (gzip) |
|---|---|---|---|---|
| 기본 단계 차트 | 32 KB | 5 KB | 54 KB | 85 KB (21 KB) |
| Keytruda vs Opdivo | 53 KB | 7 KB | 123 KB | 148 KB (37 KB) |
| 약물 네트워크 | 804 KB | 65 KB | 2,081 KB | 915 KB (99 KB) |

전체 NCT ID 목록은 선택 사항입니다. 그래서 데모는 사용자가 자세히 인용한 다섯 건 밖의 시험을 원할 때만 이를
요청합니다. 인용 패널의 "List the other trials"는 같은 계획을 `all_citation_ids`로 다시 실행하고(캐시에서
0.05–0.3초), 응답 안의 같은 위치에서 그 데이터 항목을 찾습니다.

## 2. LLM은 계획하고, 결정적 코드가 계산한다 (The LLM plans; deterministic code computes)

```
질문 + 구조화 필드
  → 계획기 (LLM)     PlanDraft: 계획 + 필터마다 원문 인용, 열거형으로 된 strict JSON Schema
  → 근거 확인        인용을 질문과 대조, 구조화 필드 우선 적용, 도메인 불변식 확인,
                     거부된 초안은 한 번 수정
  → TrialSource      코호트 필터 → ClinicalTrials.gov API, 페이지 처리, 데이터 스냅샷 단위 캐시
  → ACL              원본 연구 JSON → 도메인 Trial
  → 차트             Trial[] → 기여한 NCT ID를 유지한 묶음 → 차트 유형 + 인코딩 (순수 함수)
```

- **응답의 어떤 숫자도 LLM에서 나오지 않습니다.** LLM의 출력은 API 명세의 열거형으로 된 작은 계획뿐입니다.
- 따라서 환각은 "틀렸지만 유효한 계획을 고르는 것"으로 좁혀집니다. 이는 `meta.interpretation`과 `meta.plan`에
  드러나고, 데모에서 계획을 고쳐 다시 실행할 수 있습니다.
- 집계가 묶음마다 기여한 NCT ID를 유지하므로, 심층 인용은 나중에 덧붙인 기능이 아니라 설계에서 자연스럽게
  나옵니다.

## 3. AI 설계: 질문에 근거한 계획 (AI design: grounding the planner in the question)

네 겹의 장치가 계획기를 정직하게 만듭니다(`application/planning.py`, `application/visualize.py`).

1. **제약된 출력 (Constrained output)**: 모델은 strict 모드의 구조화된 출력으로 `PlanDraft`만 답합니다. 차원,
   개체, 측정값, 단계, 상태, 연구 유형은 모두 열거형입니다.
2. **필터 원문 인용 (Quoted filters)**: 필터마다 그 필터를 말한 질문의 단어를 그대로 인용합니다. 인용이
   질문에 없으면(대소문자, 공백, 따옴표 무시) 필터를 지어냈거나 바꿔 말한 것입니다. 텍스트 값은 인용에서
   가져와야 하므로 검색어는 사용자의 단어 그대로이고, 동의어 처리는 ClinicalTrials.gov에 맡깁니다.
3. **한 번의 수정 (One correction round)**: 문제(인용 없는 필터, 계획 종류별 필수 필드 누락, 여러 코호트에
   `split_by` 같은 도메인 규칙 위반)는 이전 초안과 함께 모델에 돌려보냅니다. 마지막 시도에서도 인용이 없는
   필터는 버리고 `meta.notes`에 알립니다. 단, 그 때문에 비교 코호트에 고유한 필터가 하나도 남지 않으면
   거부합니다.
4. **이유 코드로 거절 (Refusal by reason code)**: 어떤 분석으로도 답할 수 없는 질문은
   `422 unsupported_question`을 돌려줍니다. 모델은 `refusal` 열거형만 고르고, 메시지는 이유별로 고정된
   문장입니다.
   - 모델이 이유를 직접 쓰게 했을 때는 "What were the results of KEYNOTE-189?"를 세 번 돌려 세 가지 다른
     이유가 나왔고, 그중 둘은 거짓이었습니다("등록 데이터로는 결과를 알 수 없다". 실제로는 결과가 게시돼
     있습니다).
   - 이 질문은 이제 답합니다(6절의 `TrialResults`).

**수정 단계가 필요한 이유**: 첫 평가에서 `gpt-4.1-mini`가 "Keytruda vs Opdivo"에 대해 "trials involving Opdivo"를
인용했습니다. 이 필터를 조용히 버리면 비교가 "Keytruda 대 등록부 전체"로 바뀝니다. 수정 단계를 둔 뒤 모델이
인용을 고쳐 두 비교 모두 바르게 계획했고, 필터가 없는 코호트는 차트를 그리는 대신 거부됩니다.

계획기는 오늘 날짜("최근 5년"), 구조화 필드("this drug"), 그리고 문법만 봅니다. 시험 데이터는 보지 않습니다.

**모델 선택** (`tests/llm/test_planner_eval.py`): 부록의 모든 질의 유형, 구조화 필드 참조, 상대 기간, 이름으로
지정한 시험 결과, 거절을 다룹니다. 사례마다 정확한 필터를 확인하므로 필터가 하나만 더해져도 실패하고, 거절은
이유까지 확인합니다.

| 모델 | 결과 | 계획 지연 |
|---|---|---|
| `gpt-5.4-mini`, reasoning `low` (기본값) | 첫 평가 세트 17/17 두 번, 21/21 세 번, 후속 질문 사례를 더해 26/26 | 약 1.5–2.2초 |
| `gpt-4.1-mini` | 첫 평가 세트 16/17 (Keytruda vs Opdivo 한 번 실패, 재실행 시 3/3) | 약 1.8–4.8초 |

## 4. AI 설계: 시험이 어떤 단어를 언급하는 이유 (AI design: why a trial mentions a term)

시험이 약 이름을 언급만 했다는 사실로는 그 이유를 알 수 없습니다. 펨브롤리주맙을 언급만 한 335건에는 표준
치료인 펨브롤리주맙과 함께 진행하는 대변 미생물군 이식 연구, 펨브롤리주맙 투여 이력을 요구하는 시험, 환자가
일반 치료로 그 약을 받는 연구가 섞여 있습니다.

이를 가르려면 글을 읽어야 하므로, `POST /api/mentions`(데모 인용 패널의 "Ask AI" 버튼)는 시험마다 제목과
그 대상을 언급하는 구절(최대 6개)을 LLM에 주고 역할 하나를 고르게 합니다. 역할 정의는 약물, 질환, 기관에
맞게 따로 되어 있습니다.

| 역할 | 의미 |
|---|---|
| `studied` | 시험이 연구하는 대상 |
| `given_alongside` | 시험이 시험하는 것과 함께 투여 |
| `eligibility` | 선정·제외 조건 |
| `background` | 배경 설명일 뿐 |
| `unclear` | 판단 불가 |

계획기와 같은 근거 원칙을 적용합니다.

- 판정마다 제목이나 구절을 인용해야 합니다. `application/mentions.py`는 그 인용(3단어 이상, 공백·대소문자·
  마크다운 이스케이프 무시)이 실제로 있을 때만 받아들입니다.
- 응답에는 그 구절이 원문 그대로 담기고, 인용을 찾지 못하면 역할은 `unclear`가 됩니다.
- 한 데이터 항목의 인용 시험에 대해서만 요청 시 실행하며(요청당 최대 10건), 코호트 전체나 차트 숫자에는 쓰지
  않습니다. 판정은 시험과 구절 단위로 캐시합니다(`CachingMentionJudge`).

**평가** (`tests/llm/test_mention_eval.py`): 직접 읽고 판정한 기록 13건입니다. 펨브롤리주맙 8건, 유방암·폐암
5건이고, "Lung Adenocarcinoma"를 등록해 언급만 한 것으로 표시된 시험도 포함합니다. 평가를 만들면서 모델이
아니라 우리 코드의 버그 세 개를 찾았습니다.

- 문장 자르기가 "e.g."에서 멈췄습니다("g pembrolizumab)").
- 검증기가 구절 앞에 붙은 섹션 표시를 함께 복사한 인용이나 제목을 인용한 경우를 거부했습니다.
- 역할 정의가 약물에만 맞아서 유방암 시험이 모두 `background`로 나왔습니다.

고친 뒤 `gpt-5.4-mini`로 세 번씩 실행한 결과입니다.

| 추론 강도 | 정답 (13건 중) | 13건 처리 시간 |
|---|---|---|
| `low` | 13, 12, 12 | 11–13초 |
| `high` (기본값, `OPENAI_MENTION_REASONING_EFFORT`) | 12, 11, 12 | 35–93초 |

추론 강도를 높여도 나아지지 않았습니다. 틀린 경우는 해석이 갈리는 기록(관찰 연구에서 그 약을 "받을 예정인"
환자)이었고, 높은 강도에서는 제목과 섹션 표시를 더 자주 인용했습니다. 기본값 `high`는 선택에 따른 것이며,
이 평가에서는 `low`도 정확도가 같고 몇 배 빠릅니다.

## 5. AI 설계: 말로 하는 답과 다음 질문 (AI design: an answer in words, and what to ask next)

차트만으로는 해석이 사용자에게 남고, 필터 하나를 바꾸려 해도 질문을 다시 써야 했습니다. 세 가지를 더했고,
모두 계획기와 같은 원칙(LLM이 정하고, 코드가 확인한다)을 따릅니다.

### 후속 질문 (Follow-ups)

- `/api/visualize`가 선택적으로 `context`를 받습니다. 이전 질문들과 마지막 질문에 답한 계획입니다.
- 계획기는 그 계획을 고칩니다("only recruiting ones", "by country instead", "compare with lung cancer").
- 근거 확인은 이전 질문의 인용도 받아들이되, 질문마다 따로 대조하므로 두 질문에 걸친 인용은 통하지 않습니다.
- 이렇게 유지한 필터는 모두 안내로 알립니다("Kept the condition filter 'breast cancer' on the cohort from an
  earlier question").
- 서버는 대화 상태를 저장하지 않고, 클라이언트가 보냅니다.
- 평가 사례 5개가 좁히기, 다시 묶기, 비교, 국가 지정, 그리고 아무것도 가져오면 안 되는 새 주제를 다룹니다.
  첫 판은 "Only recruiting trials in the United States"를 새 주제로 보고 질환을 빠뜨렸는데, "바뀌는 것만 말하는
  질문은 계획을 다듬는 것"이라고 지시한 뒤 통과했습니다.

### 말로 하는 답 (An answer in words)

- 차트가 온 뒤 클라이언트가 같은 요청에 `meta.plan`을 더해 `/api/answers`로 보냅니다. 그래서 차트가 이 때문에
  늦어지지 않습니다.
- 서버는 계획을 다시 실행하고(캐시), 데이터를 항목으로 나열합니다. `c0` 코호트, `r3` 행, `n2`/`e5` 노드나
  연결, `t1` 안내입니다.
- LLM은 1–3문장을 쓰며 문장마다 근거 항목을 인용합니다.
- `check`는 문장의 모든 숫자가 그 문장이 인용한 항목(또는 질문, 차트 제목)에 있을 때만 문장을 남깁니다.
  반올림, 합, 백분율, 어림수는 버려집니다.
- 남은 문장은 인용한 데이터의 JSON 포인터(`#/visualization/data/3`)를 갖습니다. 대체 보기의 참조와 같은
  방식이라 데모의 "sources"가 그 막대의 인용을 엽니다. 질문 → 문장 → 막대 → 시험 → 발췌로 이어집니다.
- **말로 한 비교는 모델의 해석이고, 숫자는 그렇지 않습니다.**

그 틈이 시험 중에 드러났습니다.

- "most in Phase 2 at 4,590, then Not applicable at 4,962"는 숫자 검증을 통과했지만 순위를 잘못 읽었습니다.
  행이 단계 순서로 오기 때문입니다.
- 이제 각 행이 코호트 안에서의 시험 수 순위(`rank_by_trials`)를 함께 갖고, 같은 질문을 세 번 다시 돌리자 세 번
  모두 순서를 바르게 썼습니다.
- 마지막 답 15개(차트 유형이 다른 질문 5개 × 3회) 모두 문장을 하나 이상 남겼고, 4문장이 버려졌습니다. 모두
  데이터에 없는 숫자 때문이었습니다(예: "mid-200s").
- 처음 물을 때 답은 차트보다 7–15초 늦게 오고, Recent에 함께 저장돼 다시 열 때는 LLM을 부르지 않습니다.

### 다음 질문 추천 (What to ask next)

- 같은 LLM 호출이 바뀌는 것만 말하는 후속 질문을 최대 3개 제안합니다.
- 각각을 보여주기 전에 후속 질문으로 병렬 계획해 보고, 다른 분석으로 계획되는 것만 보여줍니다.
- 계획기가 이를 캐시하므로 하나를 고르면 계획 단계를 건너뜁니다. 데모에서는 차트까지 3초였고, 그 시간은
  데이터 조회입니다.
- 단일 시험 결과에는 코호트용 제안("by country instead")이 모두 계획에 실패해서, 그 시험의 다른 결과를
  제안하도록 했습니다("Its serious adverse events").

## 6. 모든 질문을 위한 단일 문법: AnalysisPlan (One grammar for every question)

질문 유형마다 코드 경로를 두는 대신, 모든 질문을 열거형으로 매개변수화된 다섯 가지 분석 종류로 표현합니다
(`cheiron/domain/analysis.py`). 넷은 여러 시험을, 하나는 한 시험의 게시 결과를 다룹니다. 차트 유형은 계획의
모양에서 결정적으로 정해집니다.

| 계획 | 매개변수 | 차트 | 질문 예 |
|---|---|---|---|
| `CountBy` | 코호트 1개, `dimension` | `bar_chart` | "How are lung cancer trials distributed across phases?" |
| `CountBy` | `dimension = start_year` | `time_series` | "How many trials started each year for pembrolizumab?" |
| `CountBy` | 코호트 2–5개 | `grouped_bar_chart` | "Compare phases for pembrolizumab vs nivolumab." |
| `CountBy` | 코호트 1개 + `split_by` | `grouped_bar_chart` | "Phases by sponsor class for pembrolizumab trials." |
| `CoOccurrence` | `source`, `target` 개체, `link` | `network_graph` | "Network of sponsors ↔ drugs for breast cancer.", "Which drugs are combined with pembrolizumab?"(`link = same_arm`) |
| `Distribution` | `measure` | `histogram` | "How large are pembrolizumab trials?" |
| `Correlation` | 측정값 `x`, `y` | `scatter_plot` | "Do longer trials enrol more patients?" |
| `TrialResults` | `trial`(NCT ID 또는 이름), `focus`, 선택적 `outcome` | 구간이 있는 `grouped_bar_chart` | "What were the results of KEYNOTE-189?", "Side effects in CheckMate 227?" |

- **차원 (Dimensions)**: phase, status, study type, start year, country, condition, intervention,
  intervention type, lead sponsor, lead sponsor class
- **개체 (Entities)**: drug, sponsor, condition, country, investigator, site
- **측정값 (Measures)**: enrollment, duration(개월), start year
- 코호트는 이름표와 `TrialFilter`이므로, "Drug A vs Drug B"는 같은 `CountBy`의 코호트 두 개입니다.
- 새 질문 유형을 더하려면 새 파이프라인이 아니라, 열거형 값 하나와 그 값을 `Trial`에서 읽는 방법
  (`domain/facets.py`)을 더하면 됩니다.

## 7. 빈도가 아닌 구조를 보여주는 네트워크 (Networks with structure, not just counts)

단순 동시 출현 수는 대부분 빈도를 되풀이할 뿐이고, 특히 질문이 필터한 대상을 되풀이합니다. 펨브롤리주맙은
펨브롤리주맙 시험의 67%에 있어 거의 모든 약물과 연결됩니다. 그래서 네트워크마다 다음을 명시합니다
(`domain/charts/co_occurrence.py`).

### 기준점 (Anchors)

필터한 대상, 또는 집계한 시험의 절반 넘게 나오는 대상은 기준점으로 표시하고 군집 계산에서 뺍니다. 구조상
대부분의 노드와 연결되기 때문입니다.

### 군집 (Clusters)

- 나머지 표시 노드들의 공유 시험 수에 탐욕적 모듈성 최대화(Clauset–Newman–Moore)를 적용합니다
  (`domain/charts/communities.py`, 순수 파이썬, 결정적인 동점 처리, 최대 200 노드).
- 군집은 가장 흔한 구성원의 이름으로 부릅니다.
- 실제 데이터에서 알아볼 수 있는 치료 패턴이 나옵니다.
  - **펨브롤리주맙의 상대 약물**: 백금·탁산계 항암화학요법(carboplatin, pemetrexed, paclitaxel 등), 소화기
    요법(oxaliplatin, leucovorin, 5-FU, irinotecan 등), 다른 면역관문억제제(nivolumab, ipilimumab,
    atezolizumab, durvalumab), 세포 치료 전 림프구 제거(cyclophosphamide, fludarabine)
  - **유방암**: HER2 표적제를 쓰는 항암화학요법, CDK4/6 억제제를 쓰는 내분비요법, 전이성·삼중음성 항암화학요법
  - **췌장암**: gemcitabine/nab-paclitaxel, FOLFIRINOX 구성 약물
- 기준점이 없을 때는 펨브롤리주맙이 항암화학요법 군집에 합쳐졌습니다.

### 연관도 (Association)

연결마다 자카드 지수(공유 시험 수 / 둘 중 하나라도 있는 시험 수)를 계산합니다. 단순히 잦은 쌍보다 요법을
위에 둡니다.

| 연결 | 공유 시험 | 연관도 |
|---|---|---|
| pembrolizumab + carboplatin (가장 잦은 연결) | 256 | 0.13 |
| leucovorin + oxaliplatin | 28 | 0.43 (최고) |
| carboplatin + paclitaxel | 135 | 0.40 |

### 만나는 방식 (How they meet)

같은 시험의 두 약물은 함께 투여될 수도 있고 서로 비교될 수도 있습니다. 스폰서는 시험을 주관할 수도, 지원만 할
수도 있습니다. 군(arm) 정보가 이를 알려줍니다.

- 펨브롤리주맙 시험 2,974건 중 2,821건이 군마다 약물을 적습니다(`ArmGroupInterventionName`, "Drug: Name").
- carboplatin + pemetrexed는 118건 중 117건에서 같은 군에 있고, docetaxel + pembrolizumab은 75건 중 35건에서
  서로 다른 군에만 있으며(펨브롤리주맙 대 도세탁셀), nivolumab + pembrolizumab은 104건 중 41건이 그렇습니다.
- 그래서 약물 연결은 `combined_trials`(같은 군)와 `compared_trials`(다른 군에만)를 갖고, 인용은 군을 인용하며
  ("Experimental: Pembrolizumab + Carboplatin", "Drug: Carboplatin"), 군집은 병용을 따릅니다.
- `link`로 병용만(`same_arm`, "Drug combination network") 또는 비교만(`different_arms`) 그리는 네트워크를 만들
  수 있고, 계획기는 질문의 표현("combined with", "versus")으로 고릅니다.
- 펨브롤리주맙 네트워크에 보이는 연결 120개 중 105개는 주로 병용, 15개는 주로 비교입니다.
- 스폰서는 역할별로 셉니다. 흑색종에서 Merck ↔ pembrolizumab은 86건으로, Merck가 주관 26건, 협력 60건입니다
  (다른 기관이 진행하고 Merck가 지원). BMS ↔ nivolumab은 27건과 51건입니다. 스폰서 노드는 분류(산업, NIH,
  기타)를 갖습니다.
- 군 필드로 시험 페이지 크기가 17% 늘었습니다(1,000건당 1.92 → 2.25 MB).

### 데모 화면

- 노드는 군집별 색, 개체 종류별 모양, 기준점은 진한 색으로 그립니다. 연결 굵기는 공유 시험 수, 투명도는
  연관도이며, 범례가 붙습니다.
- 병용이거나 스폰서가 주관하면 실선, 비교이거나 협력이면 파선, 군 정보가 없으면 점선입니다. 스폰서 노드는
  분류 색의 테두리를 갖습니다.
- 그래프의 휠 확대는 껐습니다. 전체 폭 그래프가 페이지 스크롤을 가로채서 아래의 범례와 인용에 닿을 수
  없었습니다.

## 8. 하나의 답, 여러 보기 (One answer, several views)

설계 목표는 일관된 하나의 방식으로 여러 시각화 유형을 지원하는 것입니다. 그래서 모든 답은 **기본 차트의
행에서 계산한 대체 보기**를 함께 줍니다(`domain/charts/views.py`). 새 데이터나 추가 LLM 호출은 없습니다. 한 답의
모든 보기는 같은 숫자와 같은 인용을 갖고, 어떤 보기가 생기는지는 기본 차트의 유형과 인코딩만으로 정해집니다.

| 기본 차트 | 대체 보기 | 이유 |
|---|---|---|
| `bar_chart` | `choropleth_map`(범주가 국가일 때), `donut_chart` | 지리는 지도에서 가장 잘 읽히고, 도넛은 범주별 비중을 보여줍니다 |
| `grouped_bar_chart` (비교) | `stacked_bar_chart`(그룹별 100%), `heatmap` | 크기가 다른 그룹(Keytruda 2,974건 vs Opdivo 2,030건)은 구성비로 비교해야 공정합니다. 두 약의 단계 구성은 거의 같았습니다 |
| `grouped_bar_chart` (시험 결과) | `forest_plot` | 구간이 있는 점추정치를 보여주는 결과 보고의 표준 형식입니다 |
| `time_series` | 누적 `time_series` | 증가와 누적 총량을 한 번에 봅니다 |
| `network_graph` | `heatmap`(인접 행렬), `bar_chart`(가장 강한 연결) | 빽빽한 네트워크는 읽기 어렵고, 행렬과 순위는 정확한 값을 줍니다 |
| `histogram` | `line_chart`(누적 분포) | "N명 미만을 모집하는 시험의 비율"을 바로 읽습니다 |
| `scatter_plot` | `bar_chart`(x 기준 5분위마다 y 중앙값) | 소수의 큰 시험에 흔들리지 않고 "x가 늘면 y도 느는가"에 답합니다 |

- 비율(이상반응 %)은 히트맵만 주고 100% 누적은 주지 않습니다. 서로 다른 사건의 비율을 더하게 되기 때문입니다.
- 지도는 등록부의 국가명 226개를 ISO 3166-1 숫자 코드로 바꾼 표(`domain/country_codes.json`)로 연결합니다.
  pycountry로 만든 뒤 직접 확인했고, 잘못된 퍼지 매칭("Kosovo" → 세르비아)을 잡았습니다. 14개는 수동으로 코드를
  넣었고, 넷(코소보와 옛 국가 셋)은 현재 코드가 없어 지도 안내에 적습니다.
- 브라우저에서 보기를 만들며 버그 두 개를 찾았습니다.
  - Vega-Lite는 색 값이 null인 지도 도형을 그리지 않아 데이터 없는 나라가 사라졌습니다. 이제 회색 바탕
    레이어를 먼저 그립니다.
  - 단위가 이미 들어 있는 채널 제목에 단위가 또 붙었습니다("Median (Months) (Months)"). 이제 단위는
    `Channel.unit`에만 담습니다.

## 9. 가벼운 헥사고날 아키텍처와 선택적 DDD (Lightweight hexagonal architecture, selective DDD)

이 문제는 읽기 전용 분석 파이프라인입니다. 영속성도, 변하는 상태도, 여러 엔티티에 걸친 불변식도 없습니다.
다만 실제 외부 경계가 셋(HTTP 입력, ClinicalTrials.gov와 LLM 출력) 있어서 포트와 어댑터는 값어치가 있고, 전술적
DDD 대부분은 형식에 그칩니다.

| 패턴 | 사용 | 이유 |
|---|---|---|
| 포트와 어댑터 (Ports and adapters) | 예 | API와 LLM을 가짜로 바꿔, 네트워크 없이 핵심을 결정적으로 테스트합니다 |
| 부패 방지 계층 (ACL) | 예 | `adapters/outbound/ctgov/mapper.py`가 깊고 희소한 API JSON을 평평한 `Trial`로 바꿉니다. API가 바뀌어도 파일 하나만 고칩니다 |
| 값 객체·열거형 (Value objects / enums) | 예 | `Phase`, `Status`, `PartialDate` 등을 한 번만 검증하고, 같은 열거형이 LLM 출력을 제약합니다 |
| 보편 언어 (Ubiquitous language) | 예 | 사용자와 과제가 쓰는 말대로 도메인은 `Trial`이라고 부릅니다(16절) |
| 애그리거트, 리포지토리, 도메인 이벤트 | 아니오 | 바뀌거나 저장되는 것이 없어, 리포지토리는 이름만 바꾼 API 클라이언트가 됩니다 |
| 여러 경계 컨텍스트, CQRS, DI 컨테이너 | 아니오 | 컨텍스트는 하나이고 조회뿐이라 생성자 주입으로 충분합니다 |

도메인(`cheiron.domain`)은 표준 라이브러리에만 의존합니다. Pydantic은 HTTP 스키마와 LLM 계약(`PlanDraft`,
`AnswerDraft`)에만 쓰며, 이 계약은 LLM 어댑터가 따라야 하는 JSON Schema를 겸합니다.

## 10. 데이터베이스 없음 (No database)

- ClinicalTrials.gov가 정해진 원천이고, 서비스는 상태를 저장하지 않습니다.
- 로컬 미러(예: 대량 다운로드 위의 DuckDB)는 정확하고 빠른 `GROUP BY`를 주지만, 검토자에게 수 GB의 적재 단계와
  최신성 문제를 떠넘깁니다.
- 대신 `TrialSource` 포트 뒤에 캐시를 둡니다(11절). 나중에 DB 기반 소스로 바꿔도 핵심은 그대로입니다.

## 11. 공개된 데이터 스냅샷에 맞춘 캐시 (Caching keyed to the published data snapshot)

캐시하기 전에 데이터가 얼마나 자주 바뀌는지 가정하지 않고 쟀습니다.

- `/version`은 스냅샷 시각(`dataTimestamp`)을 알려줍니다. 2026-10-13(화)에도 금요일 값
  `2026-10-09T09:00:05`였습니다.
- 2주 동안 `LastUpdatePostDate`로 세어 보니, 미국 영업일마다 약 800–1,200건(606,601건의 약 0.17%)이
  게시되고 주말과 2026-10-12 연방 공휴일에는 없었습니다. 영업일마다 한 번에 갱신됩니다.
- 코호트별로는 1주 동안 시험의 0.9%(유방암)에서 4.3%(모집 중 폐암)가 바뀌었습니다.

그래서 결과는 다음 스냅샷이 나올 때까지 유효합니다.

- `CachingTrialSource`(ClinicalTrials.gov 어댑터를 감싼 데코레이터)는 검색 결과, 시험 이름 조회, 게시 결과를
  메모리에 두고 `dataTimestamp`가 바뀌면 비웁니다.
- 확인은 최대 10분마다 하고, 확인이 실패해도 최대 24시간이 지나면 비웁니다.
- 고정 TTL은 쓰지 않았습니다. 주말 내내 유효한 결과를 버리고, 새 스냅샷 뒤에도 몇 시간 동안 낡은 결과를
  주기 때문입니다.
- 용량은 시험 수로 셉니다(30,000건, 사이트 정보가 있는 결과는 실측대로 3배로 계산). 가장 오래 쓰지 않은
  것부터 비웁니다.
- 효과: 같은 코호트에 대한 반복·관련 질문(단계 다음에 시작 연도)이 약 4초에서 약 10 ms로 줄었습니다.
- Redis도 검토했습니다. API 프로세스가 하나뿐이라 공유 상태의 이점 없이 컨테이너와 직렬화 코드만 늘어납니다.
  API를 여러 대로 늘리면 같은 포트를 구현하면 됩니다.

## 12. 반복 질문은 LLM 없이 답하기 (Answering a repeated question without the LLM)

"Which drugs are combined with pembrolizumab?"로 잰 결과, 첫 답은 9.3초, 반복할 때마다 2.3초였습니다. 그중
1.4–3.2초가 계획기였고, 데이터는 캐시에서 0.2초였습니다. 두 가지 캐시가 이를 없앱니다.

- **`CachingPlanner`** (`QueryPlanner` 데코레이터): 모델이 보는 모든 것을 키로 초안을 캐시합니다. 질문(대소문자,
  공백, 끝의 "?" 무시), 구조화 필드, 후속 질문의 이전 질문과 계획, 수정 피드백, 오늘 날짜("최근 5년")입니다.
  반복은 0.22초가 되고, 같은 질문은 같은 계획을 받습니다.
- **데모의 Recent**: 이 세션의 답을 채팅 도우미처럼 보관합니다(`sessionStorage`). 아는 질문을 다시 물으면
  저장된 답을 쓰고, 새로 고침하면 마지막 답을 복원합니다. 답마다 계산된 스냅샷(`meta.data_version`, 차트 위에
  표시)을 갖고, 저장된 답을 보여주기 전에 `GET /api/version`(서비스가 캐시하므로 수 ms)을 확인해 더 새 데이터가
  있으면 다시 묻습니다.

표현을 바꾼 질문은 여전히 계획기 호출이 한 번(약 2초) 듭니다.

## 13. 상한을 둔 자체 집계 (Aggregating on our side, with a cap)

- API의 `/stats/field/values`는 *전체* 연구에 대한 통계만 주고 검색 필터를 받지 않습니다(명세에서 확인). 그래서
  필터를 건 집계는 서비스가 직접 계산해야 합니다.
- `CtGovTrialSource`는 분석에 필요한 필드만 받습니다(1,000건 ≈ 1.9 MB, 페이지당 ≈ 1.3초).
- 코호트당 상한(기본 5,000건, 최대 10,000건)까지 받고, 분석한 시험과 함께 `total_count`를 알려 잘렸는지
  밝힙니다.
- 기본값은 2,000에서 올렸습니다. 펨브롤리주맙 차트(2,974건)가 Phase 1을 1,046 대신 699로 보여줬기 때문입니다.
  표시는 됐지만 절대 수치로는 오해를 낳았습니다.

## 14. 상한을 넘는 정확한 건수 (Exact counts beyond the cap)

잘린 코호트는 앞 5,000건으로 그렸습니다. 유방암(16,899건)은 Phase 2를 4,590 대신 1,362로 보여줬습니다.

### 범주별 등록부 집계 (countTotal)

- 분할(split) 없는 `count_by` 중 등록부가 셀 수 있는 차원(단계, 상태, 연구 유형, 주관 스폰서 분류, 중재
  유형)은, 집계한 시험에 나온 범주마다 *전체* 일치 시험 수를 등록부에 묻습니다. 범주는 코호트 조건에 Essie
  `AREA[...]` 절로 더하고, 범주마다 `countTotal` 요청 하나입니다.
- 막대는 그 수를 보여주고, 인용은 여전히 집계한 시험을 자세히 보여주며, `meta.cohorts[]`는
  `exact_counts: true`입니다.
- 막대마다 `citations.registry_query`가 그 수를 재현합니다. 유방암 Phase 2 요청은 막대 값과 같은 `totalCount`
  4,590을 돌려줍니다.
- `all_citation_ids`를 켜면 막대마다 모든 시험을 나열합니다(1,000건마다 요청 1회. 유방암 여섯 단계 14,200건에
  약 30초. 20,000건을 넘으면 안내를 붙이고, `registry_query`로 볼 수 있습니다).
- 쓰기 전에 알츠하이머 시험 4,269건 전체에 대해 다섯 차원 38개 범주의 등록부 수와 우리 집계를 비교했고, 모두
  같았습니다. 실제 API 테스트가 더 작은 코호트(한국의 흑색종 시험)로 이 비교를 반복합니다.

### 요청 한도

- 명세에 없는 API 요청 한도가 비용을 정합니다. 실측: 처음 약 10건은 한꺼번에, 이후 초당 약 1건(10초 창마다
  정확히 10건 성공). 61건을 동시에 보내면 53건이 `429`를 받았습니다.
- 그래서 건수 요청은 하나씩, 답 하나당 최대 20건(`MAX_COUNT_REQUESTS`)으로 제한하고 검색처럼 캐시합니다.
  검색이 캐시된 상태에서 6건은 1.2초, 11건은 12초 걸렸습니다.

### 전체 기록 집계 (Tally)

시작 연도(범주 약 50개), 국가처럼 값이 많은 차원은 범주별 요청이 너무 많이 듭니다. 그런데 부록의 시간 추세와
지리 질문이 바로 이 차원을 묻고, 표본은 절대 수치에서 크게 틀렸습니다.

| 코호트 | 표본(앞 5,000건)이 담은 비율 | 예 |
|---|---|---|
| 유방암, 연도별 | 해마다 28–31% | 2025년: 표시 317, 실제 1,090 |
| 모집 중 암 시험 18,769건, 국가별 | 국가마다 26–28% | 미국: 표시 1,823, 실제 6,939. 한국은 10위가 아니라 8위로 나옴 |

모양은 맞았지만 수치는 틀렸습니다. 그래서 범주별로 셀 수 없을 때(등록부가 셀 수 없는 차원이거나 범주가 20개를
넘을 때)는 일치하는 시험 전부를 셉니다.

- 그 차원에 필요한 필드만 담은 1,000건 단위 페이지를 받습니다(시작일 약 250 KB, 국가 약 470 KB. 전체 기록은
  약 2.2 MB).
- 차트와 같은 도메인 규칙(facets)으로 세고, 답 하나당 25,000건까지입니다(`MAX_TALLY_TRIALS`).
- 집계한 시험에 없던 범주도 찾고, 막대마다 시험 전부를 나열합니다.
- 연도와 국가는 `registry_query`를 갖고, 실제 API 테스트가 이를 등록부의 `AREA[StartDate]RANGE[...]` 검색과
  대조합니다.
- 이제 유방암의 연도별 수와 모집 중 암 시험의 국가별 수가 등록부 값과 정확히 같습니다(2025년 1,090건, 미국
  6,939건, 한국 10위). 첫 질문은 24초와 28초, 캐시에서는 0.1초입니다.
- 25,000건을 넘거나 세기가 실패하면 평소처럼 안내와 함께 집계한 시험으로 그립니다. 네트워크, 분포, 산포도,
  분할 막대는 항상 집계한 시험(앞 5,000건) 기준입니다.

## 15. 실제 API 데이터 다루기 (Handling real API data)

실제 API(v2.0.5)를 살펴보며 관찰한 것과 그 처리입니다.

| 관찰 | 처리 |
|---|---|
| 상표명과 코드가 동의어입니다. `Keytruda`, `MK-3475`, `pembrolizumab` 모두 2,974건을 돌려줍니다. | 자유 텍스트는 `query.*`로 보내 API의 동의어 확장을 활용합니다. |
| 따옴표(`"`) 하나만 잘못 들어가도 `400`이 납니다. | 자유 텍스트에서 Essie 문법 문자를 제거합니다(`AREA[...]` 주입도 막습니다). |
| 정확한 조건(단계, 상태, 국가, 시작 연도)은 `filter.*` / `AREA[...]` 문법이 필요합니다. | `params.py`가 만들고, 실제 건수로 테스트합니다. |
| 필드가 자주 비어 있고, 날짜가 `2021-05` 또는 `2021-05-27`로 옵니다. | `Trial`의 모든 속성은 선택 사항이고, `PartialDate`는 날짜를 지어내지 않고 등록된 정밀도를 유지합니다. |
| 열거형 값이 명세보다 늘어날 수 있습니다. | 모르는 값은 필드 단위로 버리고 연구는 유지합니다. |
| 한 연구가 사이트마다 위치를 하나씩(수백 개) 적습니다. | `Trial.countries`는 중복을 없애, 시험은 국가마다 한 번만 셉니다. |
| 약물이 아닌 항목도 중재로 등록됩니다(예: "Laboratory Biomarker Analysis", 유형 `OTHER`). | 약물 네트워크는 `DRUG` / `BIOLOGICAL` 중재만 씁니다. |
| 국가 필터는 변형을 해석합니다(`USA`, `UK`, `Korea, Republic of` → `United States`, `United Kingdom`, `South Korea`). 저장 값은 한 가지 표기(226개)입니다. | 필터에는 국가 정규화가 필요 없고, 차트는 저장된 표기를 보여줍니다. |
| 시작 전 시험은 미래 연도를 포함한 예정 시작일을 갖습니다(`startDateStruct.type: ESTIMATED`. 날짜가 있는 펨브롤리주맙 시험 2,969건 중 309건). | 시작일과 완료일은 등록된 유형과 함께 인용하고, 시계열은 예정 시작일인 시험 수를 그 시험을 인용하는 안내로 밝힙니다. |
| `/stats/field/values`는 국가 226개는 모두 주지만, 질환 약 134,000개, 중재명 약 537,000개, 스폰서 약 52,000개는 상위 250개만 주고, 중재 상위는 "Placebo", "Control", "No intervention", "Usual Care"가 차지합니다. | `GET /api/options`는 전체 국가를 드롭다운으로, 상위 용어는 (검색어가 아닌 것을 빼고 대소문자 중복을 합쳐) 추천어로 줍니다. 자유 입력도 됩니다. |
| 책임자 필드에 역할, 부서, 회사가 자주 들어 있습니다. 약 6,000건을 조사하니 "Clinical Sciences & Operations"(239), "Teva Medical Expert, MD"(107), "Medical Director"(106), "Medical Monitor"(90), 콜센터 문구, 스폰서 이름이 있었습니다. | ACL은 사람 이름처럼 보이는 것만 남깁니다(조사에서 만든 패턴 목록. 스폰서 이름 규칙은 개인 스폰서를 건너뜁니다. 개인 스폰서는 대개 본인이 책임자입니다). |
| 한 사람이 여러 표기로 나옵니다: "Benoit Girard, MD" / "Benoit Girard, M.D.", "James D. Carlson, Pharm.D."는 네 가지. | 연구자 노드는 첫 쉼표 뒤의 학위를 빼고 키를 만들어, "Do", "Ma" 같은 성은 유지합니다. |
| 기관명이 흔히 일반적입니다: "Research Site"(세 질환에서 5,880곳), "GSK Investigational Site"(2,264), "Local Institution", 콜센터 문구. | 일반 기관명은 버리고, 사이트는 기관 + 도시 + 국가로 키를 만들어 "University Hospital, Basel" ≠ "University Hospital, Zurich"입니다. |
| 모든 위치의 기관과 도시를 받으면 응답이 두 배가 되고(1,000건당 1.9 → 4.1 MB), 한 시험이 사이트 1,151곳(약 660,000쌍)을 적기도 합니다. | 사이트 필드는 사이트 노드가 있는 계획에서만 받고, 연결은 가장 잦은 4 × `max_nodes` 노드 사이에서만 셉니다(펨브롤리주맙 사이트 네트워크 25.8초 → 6.4초, 결과 동일). |
| `pageSize=0`은 0이 아니라 기본값(10)이고, 다음 페이지는 첫 페이지의 매개변수를 반복해야 합니다. | `client.py`에 반영하고 테스트합니다. |
| 시험 이름이 모호합니다. "KEYNOTE-189"는 40명 일본 연장 연구의 보조 ID일 뿐이고, 616명 본 시험은 제목에만 있으며, 관찰 "emulation" 연구도 언급합니다. ID로만 찾으면 엉뚱한 시험이 나옵니다. | `find_trials`는 약칭, 연구 ID, 제목을 찾고, `choose_trial`은 정확한 약칭을 먼저 보고, ID·제목은 고유한 이름(숫자나 여러 단어)일 때만 쓰며, 게시 결과가 있는 시험만, 등록 인원이 가장 큰 것을 고르고 나머지는 안내와 함께 `meta.trial.alternatives`로 돌려줍니다. |
| 등록부는 "KEYNOTE-189"를 한 단어로 색인해 "KEYNOTE 189"로는 찾지 못합니다. 흔한 단어("RECOVERY")는 제목 5,682개에 나옵니다. | 이름은 하이픈 표기로도 찾고, 약칭은 따로 질의하며, 흔한 한 단어는 약칭에만 매칭합니다. |
| 게시 결과: 도달하지 않은 중앙값은 "NA"로, 산포는 한계값 또는 퍼짐으로 게시되고, 이상반응 그룹에 위험 인원 2명인 교차 그룹이 있으며, 두 그룹이 같은 제목을 갖기도 합니다. | "NA"는 텍스트로 유지하고 차트에서는 null과 안내로 처리하며, 퍼짐은 값 ± 퍼짐으로 바꾸고, 위험 인원 10명 미만 그룹은 이상반응 차트에서 빼며(안내), 중복 제목에는 그룹 ID를 붙입니다. |
| `429` / `5xx` 응답 | 백오프(1초, 2초, 4초)로 재시도하고, `4xx`는 API 메시지와 함께 바로 실패합니다. |

## 16. 이름: Study가 아니라 Trial (Naming: Trial rather than Study)

ClinicalTrials.gov는 기록을 "study"라 부르고, 엄밀히는 임상시험이 아닌 관찰 연구와 확대 접근 연구도 포함합니다.
도메인은 사용자의 말인 `Trial`을 쓰고 `study_type`으로 종류를 구분하며, "study"가 "trial"로 바뀌는 곳은 ACL입니다.

## 17. 두 개의 입구: 구조화된 계획과 자연어 (Two entry points)

- `POST /api/visualize`는 LLM이 계획을 쓰고, `POST /api/plans`는 계획을 바로 실행합니다.
- 둘 다 같은 `run_plan` 사용 사례를 실행해 같은 응답을 돌려줍니다. 질문에 대한 답의 `meta.plan`은 그대로 유효한
  `/api/plans` 요청이라, 해석을 손으로 고쳐 다시 실행할 수 있습니다(데모가 이렇게 합니다).
- LLM은 공개 계획 스키마가 아니라 별도의 `PlanDraft`를 씁니다. 초안에는 근거 확인에 쓰는 필터별 인용이 들어
  있기 때문입니다.
- 구조화된 입구는 재현 가능한 결과를 주고, LLM 없이 핵심을 실행하며, 계획을 직접 만드는 클라이언트도 지원합니다.

## 18. 프론트엔드: 질문별 화면이 아닌 범용 렌더러 (Frontend: a generic renderer)

React 데모(`frontend/`)는 채팅 도우미처럼 동작합니다.

- 질문 상자는 아래에 고정되고, 답은 질문을 어떻게 이해했는지와 함께 그 위에 쌓이며, 계획을 고쳐 다시 실행할
  수 있습니다.
- 등록부에 정해진 목록이 있는 필터는 고르게 하고(시험 수가 붙은 국가 드롭다운, 단계·상태 칩, 연도 선택),
  나머지(약물, 질환, 스폰서)는 `GET /api/options`의 추천어를 줍니다. 적용된 필터는 지울 수 있는 칩입니다.
- 단일 시험이면 사용한 시험을 링크와 함께 보여주고, 같은 이름에 걸린 다른 시험으로 바꿀 수 있습니다.
- 차트 위의 탭으로 답의 여러 보기(예: Bars / Map / Donut)를 오갑니다.
- 시험 수를 말하는 안내에는 그 시험들을 인용 패널에 보여주는 "show trials" 링크가 있고, 등록부가 센 건수에는
  그 수를 재현하는 API 요청 링크가 붙습니다.
- 차트 위에는 몇 문장의 답이 나오고, 문장마다 "sources"가 인용한 데이터를 엽니다. 그 아래에 미리 계획한 후속
  질문("Ask next")이 있고, 질문 상자 위의 칩은 다음 질문이 지금 답의 후속 질문임을 알립니다. 칩을 지우면 새
  주제로 시작합니다.
- 자세히 인용한 다섯 건 밖의 시험은 "List the other trials"로 NCT ID를 20건씩 보고, "Ask AI" 확인은 목록에
  보이는 시험 중 아직 판정하지 않은 것만 읽습니다(엔드포인트 한도인 10건씩 나눠 동시에 보냅니다. 25건에 24초).
- 거절과 "결과 미게시"는 오류가 아닌 중립적인 안내로 나오고, 이전 차트를 대신합니다.

렌더링은 질문을 전혀 모릅니다.

- `type` + `encoding`을 Vega-Lite(오차 막대가 있는 막대, 누적 막대, 히트맵, 지도, 도넛, 선, 포레스트 플롯,
  시계열, 히스토그램, 산포도) 또는 Cytoscape(네트워크)로 옮기고, 클릭한 데이터의 인용을 보여줍니다.
- 명세만으로 모든 차트를 그린다는 것 자체가, 명세를 추측 없이 그릴 수 있다는 증거입니다.
- 렌더러를 쓰다가 문제 두 개를 찾았습니다. 렌더러 쪽(미리 구간을 나눈 히스토그램은 Vega-Lite에
  `bin: {binned: true}`가 필요)과 명세 쪽(국가를 "korea"로 입력하면 필터는 됐지만 제목에 드러나지 않아 차트가
  필터되지 않은 것처럼 보임. 이제 제목에 공통 필터를 적습니다)입니다.

**브라우저 페이지 번역 문제**: 번역 기능은 텍스트 노드를 자기 요소로 바꿔치기해서, React가 그 옆에 넣거나 빼다가
실패하고("Failed to execute 'insertBefore' on 'Node'") 페이지 전체를 잃습니다.
- 이를 흉내 내는 스크립트(모든 텍스트 노드를 `<font>`로 감싸고, 새 텍스트도 나타나는 대로 번역)로 첫 질문에서
  데모가 멈추는 것을 재현했습니다.
- 바뀌는 텍스트나 조건부 내용 옆의 텍스트는 이제 문자열 하나만 담은 자기 요소라서, React가 통째로 바꿉니다.
- 같은 스크립트로 13가지 동작(질문, 보기 전환, 데이터 선택, 필터, Recent, AI 확인)을 오류 없이 실행했고, 해석
  같은 바뀌는 텍스트도 갱신됩니다.

## 19. 모노레포와 Docker (Monorepo and Docker)

저장소 하나에 폴더 둘(`backend/`, `frontend/`)과 `docker-compose.yml`을 둡니다. JS 패키지가 하나라 모노레포 도구
(Nx, Turborepo)는 보탬이 없습니다. Docker 덕분에 검토는 명령 하나로 끝나고, 검토자의 컴퓨터에 uv나 Node가 필요
없습니다.

## 20. Python 3.14

Python ≥ 3.14를 대상으로 합니다(기본 지연 어노테이션. 3.12는 보안 수정만 받습니다). uv가 로컬 인터프리터를
준비하고, Docker 이미지는 `python:3.14-slim`입니다.

## 21. 알려진 한계 전체 (All known limitations)

**답과 AI**
- 말로 하는 답은 숫자는 확인하지만 말은 확인하지 않습니다. "most", "more than"은 각 행의 순위가 적힌 항목을
  모델이 읽은 결과입니다. 답에는 LLM 호출이 하나 더 들고(처음에는 차트보다 7–15초 늦게), 후속 질문은
  클라이언트가 보내는 최근 질문 5개까지만 이어갑니다.
- 근거 확인은 필터를 말했다는 것을 증명할 뿐, 바르게 옮겼다는 것은 증명하지 않습니다. "late-stage"를 인용해
  `PHASE3`으로 옮겨도 통과합니다. `meta.interpretation`과 고칠 수 있는 계획이 대책입니다.
- 처음 묻는 질문은 계획에 약 1.5–2초가 더 듭니다. 같은 질문은 계획을 재사용하고, 표현을 바꾼 질문은 다시
  계획합니다.
- 평가는 영어 질문만 다룹니다. 다른 언어는 시험하지 않았습니다.
- 언급 역할은 최대 6개 구절과 제목을 LLM이 읽은 결과입니다. 해석이 갈리는 기록(관찰 연구에서 약을 "받을
  예정인" 환자)에서는 실행마다 달라질 수 있고, 함께 보이는 인용으로 확인할 수 있습니다.

**데이터와 집계**
- 조회 상한을 넘는 결과는 API가 돌려준 앞의 N건(정렬되지 않음)으로 분석하고, `meta`가 이를 표시합니다. 한
  차원으로 세는 차트는 일치하는 시험 25,000건까지 등록부 기준으로 채웁니다(14절). 네트워크, 히스토그램, 산포도,
  분할 막대는 채우지 않고, 큰 코호트의 첫 질문은 세는 동안 20–30초 걸립니다.
- 자유 텍스트 조건은 ClinicalTrials.gov 검색에 기대므로, 설명에서 언급만 한 시험도 걸립니다(펨브롤리주맙
  시험의 11%, 폐암 앞 5,000건의 24%). 등록부가 정의하는 코호트이므로 세되, 인용에 표시하고 `meta.notes`에서
  셉니다. 시간이 더 있다면 등록된 시험만 세는 옵션을 두겠습니다.
- 요청 한도는 API 명세에 없습니다(실측: 처음 약 10건, 이후 초당 약 1건). 클라이언트는 `429`를 백오프로
  재시도할 뿐 미리 속도를 조절하지 않아, 큰 코호트 둘에 대한 첫 질문은 약 30초 걸립니다(페이지 10개 + 건수
  16개).
- 캐시되지 않은 큰 코호트 질문은 몇 초가 걸립니다(API의 페이지 토큰 때문에 1,000건 페이지를 차례로 받습니다).
- 여러 값을 갖는 속성(단계, 국가, 질환, 중재)은 값마다 한 번씩 세므로, 막대 합이 시험 수보다 클 수 있습니다.
  응답이 `notes`에서 이를 밝힙니다.
- 시험 이름이 결과가 있는 여러 시험에 걸리면 가장 큰 시험으로 정합니다. 어느 것이 "본" 시험인지 아는 것이 아니라
  규칙이므로, 대안을 항상 보여줍니다.
- 단일 시험 차트는 값 척도를 하나만 보여주고(처음 선택된 결과 지표의 측정 방식과 단위. 나머지는 안내에 나열),
  가장 잦은 이상반응 15개를 보여줍니다. 시험 사이의 결과 비교는 하지 않습니다.

**네트워크와 이름**
- 개체 이름은 대소문자와 공백만 무시하고 맞춥니다. 펨브롤리주맙 약물 네트워크에서 "Pembrolizumab"은 허브지만,
  "MK-3475"나 "favezelimab/pembrolizumab"으로 등록된 것은 따로 남습니다. 시간이 더 있다면 등록된 `otherNames`와
  동의어 출처로 합치겠습니다.
- 연구자와 사이트의 자리표시자 판별은 실제 기록 조사에서 만든 패턴 목록이지 분류기가 아닙니다. 예를 들어
  "Bristol-Myers Squibb"는 등록된 스폰서가 아닌 시험에서 연구자로 통과합니다.
- 군집은 표시된 부분 그래프(기본 상위 30 노드)에서 계산하고, 모듈성은 높지 않습니다(예시에서 Q ≈ 0.2). 군집은
  경향이지 확실한 분할이 아닙니다. 이름 변형("Fluorouracil", "5-fluorouracil")은 따로 남고 한 군집에 함께 들어갈
  수 있습니다.
- 군은 구조로만 읽습니다. 대안을 주는 군("pembrolizumab or nivolumab")은 병용으로 세므로, nivolumab +
  pembrolizumab의 "병용" 63건 일부가 이런 경우로 보입니다. 스폰서 역할은 스폰서 ↔ 다른 개체 네트워크에서만
  나누고, 스폰서끼리는 나누지 않습니다.
- 지도는 막대 차트의 국가(기본 상위 15개)만 보여주고, 모든 국가를 보여주지는 않습니다.

**응답 크기와 운영**
- 산포도는 집계한 시험마다 점을 하나씩 돌려줘 가장 큰 응답이 됩니다(실측: 펨브롤리주맙 시험 2,969건에 2.1 MB,
  단계 막대는 10 KB). 시간이 더 있다면 점과 인용에 중복된 제목을 빼거나 표본을 쓰겠습니다.
- 큰 네트워크도 큰 응답입니다(펨브롤리주맙 약물 네트워크 804 KB, gzip 65 KB). 대부분 연결별 인용과 구절입니다.
- 캐시는 한 프로세스에만 있어, 재시작하면 사라지고 API 복제본 사이에 공유되지 않습니다. Redis 기반 `TrialSource`
  데코레이터가 두 한계를 모두 없앨 것입니다.
- 데모 번들은 1.5 MB이고(대부분 Vega), 코드 분할을 하지 않았습니다.
