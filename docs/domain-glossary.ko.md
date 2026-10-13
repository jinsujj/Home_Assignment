# 도메인 용어 정리

## 이 서비스가 하는 일

임상시험에 대한 질문을 받으면 ClinicalTrials.gov에서 데이터를 가져와 **세고**, 차트로 그릴 수 있는 **명세**를 돌려준다.

## 기본 개념

| 용어 | 뜻 |
|---|---|
| 임상시험 | 새 약·치료법이 사람에게 안전하고 효과 있는지 확인하는 연구 |
| ClinicalTrials.gov | 미국 NIH가 운영하는 세계 최대 임상시험 등록부 |
| NCT ID | 시험 등록번호 (예: `NCT03044730`) |

## 예시: `NCT03044730`

유방암 환자에게 Pembrolizumab과 Capecitabine을 함께 쓰는 시험.

| 변수 | 값 |
|---|---|
| phase | `PHASE2` |
| status | `UNKNOWN` |
| study_type | `INTERVENTIONAL` |
| start / completion | `2017-05-25` / `2021-05` |
| enrollment | 30명 |
| conditions | Triple-Negative Breast Carcinoma 외 9개 |
| interventions | Capecitabine (DRUG), Pembrolizumab (BIOLOGICAL), Laboratory Biomarker Analysis (OTHER) |
| lead_sponsor | Northwestern University (`OTHER`) |
| collaborators | Merck (`INDUSTRY`), National Cancer Institute (`NIH`) |
| countries | United States |

## 변수

### phase: 임상 단계

| 값 | 뜻 |
|---|---|
| `EARLY_PHASE1` | 극소량을 처음 써보는 탐색 단계 |
| `PHASE1` | 안전성·용량 확인 (수십 명) |
| `PHASE2` | 효과 확인 (수십~수백 명) |
| `PHASE3` | 기존 치료와 비교, 승인 근거 (수백~수천 명) |
| `PHASE4` | 시판 후 관찰 |
| `NA` | 해당 없음 (기기·운동 등 약이 아닌 연구) |

- 한 시험이 여러 단계를 가질 수 있다 (예: 1·2상 통합) → 단계별 합이 전체보다 클 수 있음
- 관찰 연구는 단계가 없다 → "단계 미등록"으로 따로 보고

### status: 진행 상태

| 값 | 뜻 |
|---|---|
| `NOT_YET_RECRUITING` | 모집 시작 전 |
| `RECRUITING` | 모집 중 |
| `ACTIVE_NOT_RECRUITING` | 진행 중, 모집 종료 |
| `COMPLETED` | 완료 |
| `TERMINATED` | 도중 중단 |
| `WITHDRAWN` | 시작 전 철회 |
| `UNKNOWN` | 오래 갱신되지 않아 상태 불명 |

### study_type: 연구 유형

| 값 | 뜻 |
|---|---|
| `INTERVENTIONAL` | 연구자가 치료를 투여 (엄밀한 의미의 "시험") |
| `OBSERVATIONAL` | 개입 없이 관찰만 |
| `EXPANDED_ACCESS` | 승인 전 약을 대안 없는 환자에게 예외적으로 제공 |

등록부는 이것들을 모두 "study"라 부르지만, 코드에서는 사용자 언어에 맞춰 `Trial`로 부른다.

### start_year: 시작 연도

시작일의 연도. 시작 전 시험은 **예정일**이라 미래 연도가 나올 수 있다.

### country: 국가

시험이 진행되는 병원(site)의 국가. 한 시험이 여러 국가에 걸칠 수 있고, 같은 국가는 한 번만 센다.

### condition: 질환

연구 대상 질환. 한 시험이 여러 개를 등록하기도 한다.

### intervention: 중재 (시험에서 하는 것)

| intervention_type | 뜻 | 예 |
|---|---|---|
| `DRUG` | 화학 합성 약 | Capecitabine |
| `BIOLOGICAL` | 항체·백신 등 생물학적 제제 | Pembrolizumab (키트루다) |
| `DEVICE` | 의료기기 | |
| `PROCEDURE` | 수술·시술 | |
| `RADIATION` | 방사선 치료 | |
| `BEHAVIORAL` | 운동·상담 등 | |
| `OTHER` | 기타 | Laboratory Biomarker Analysis (검사) |

**위약(placebo)**: 비교용 가짜 약. 보통 `DRUG`로 등록된다.

### sponsor: 스폰서

- **lead sponsor**: 시험을 책임지는 기관
- **collaborators**: 돈·약을 대며 돕는 기관

| sponsor class | 뜻 |
|---|---|
| `INDUSTRY` | 제약사·기업 |
| `NIH` | 미국 국립보건원 (NCI 포함) |
| `FED` | 그 밖의 미국 연방기관 |
| `OTHER_GOV` | 그 밖의 정부기관 |
| `OTHER` | 대학·병원 등 |
| `NETWORK` | 연구 네트워크·협력 그룹 |
| `INDIV` | 개인 |

분류 기준은 책임 기관(lead sponsor)이다. 그래서 차원 이름도 `LEAD_SPONSOR_CLASS`다.

### investigator: 연구자

시험의 책임자(overall official): 책임연구자(PI), 연구 의장, 연구 책임자.

- 이름 자리에 사람이 아닌 값이 많다: "Medical Director", "Medical Monitor", 부서명, 회사명, 콜센터 전화번호, 스폰서 이름 → **ACL에서 제거**
- 단, 개인 스폰서(`INDIV`)는 본인이 연구자인 경우가 많아 스폰서 이름과 같아도 남긴다
- "Benoit Girard, MD"와 "Benoit Girard, M.D."는 같은 사람 → 쉼표 뒤 학위 표기를 무시하고 묶는다

### site: 임상 사이트

시험이 진행되는 병원·기관.

- "Research Site", "GSK Investigational Site"처럼 어디인지 알 수 없는 일반 명칭이 많다 → **제거**
- 같은 이름이라도 도시가 다르면 다른 사이트다 (University Hospital, Basel ≠ Zurich)
- 사이트 정보는 응답 크기를 두 배로 늘리므로 **사이트 네트워크를 그릴 때만** API에 요청한다

### enrollment, duration: 숫자 값

- **enrollment**: 참여자 수 (등록값)
- **duration**: 시작일~완료일 개월 수 (**계산값**, 예시는 48개월)

## Dimension, Entity, Measure

같은 시험이 쓰이는 세 가지 방식이다. `src/cheiron/domain/analysis.py`에 정의돼 있다.

| enum | 고르는 것 | 차트 | 예시 시험이 기여하는 방식 |
|---|---|---|---|
| `Dimension` | 무엇으로 **나눠 셀까** | 막대, 시계열 | "Phase 2" 막대 +1, 2017년 +1 |
| `Entity` | 무엇을 **점으로 이을까** | 네트워크 | Pembrolizumab ── Capecitabine 연결 +1 |
| `Measure` | 어떤 **숫자**를 볼까 | 히스토그램, 산점도 | "0~100명" 구간 +1, (48개월, 30명) 점 |

- **약물 네트워크 (`Entity.DRUG`)**: DRUG·BIOLOGICAL만 쓰고 위약은 뺀다. 검사 같은 `OTHER`도 점이 되지 않는다.
- **스폰서 네트워크 (`Entity.SPONSOR`)**: 협력 기관도 포함한다. 반면 `Dimension.LEAD_SPONSOR`로 셀 때는 책임 기관만 센다.
- **연구자·사이트 네트워크 (`Entity.INVESTIGATOR`, `Entity.SITE`)**: 사람·장소를 특정할 수 없는 값은 빠진다 (위 변수 설명 참고).
- **네트워크 연결선 계산**: 사이트가 1,000곳 넘는 시험도 있어 모든 쌍을 세면 너무 느리다. 자주 나오는 노드(보여줄 수의 4배)끼리만 연결선을 센다.
- LLM은 질문을 보고 이 목록에서 **고르기만** 한다. 실제로 세는 일은 코드가 한다.

## 코드 위치

| 개념 | 파일 |
|---|---|
| 시험과 enum (Phase, Status 등) | `domain/trial.py` |
| 검색 조건 | `domain/trial_filter.py` |
| Dimension · Entity · Measure, 분석 계획 | `domain/analysis.py` |
| 시험에서 값과 근거(인용) 뽑기 | `domain/facets.py` |
| 계획 → 차트 명세 | `domain/charts/` |
| API 응답 → `Trial` 변환 | `adapters/outbound/ctgov/mapper.py` |
