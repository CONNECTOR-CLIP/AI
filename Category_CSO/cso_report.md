# CSO Tree Builder 실험 보고서

## 개요

- **실험 목표**: CSOClassifier v4.0.0을 사용해 100편의 cs.AI arXiv 논문을 3레벨 트리(root → intermediate → leaf)로 분류
- **데이터**: `papers_100.json` (100편, 전부 cs.AI primary category)
- **온톨로지**: CSO.3.5.csv (14,636 토픽, 10,181 동의어 쌍)
- **실험 기간**: 2026-04-14 ~ 2026-04-16

---

## 최종 결과 (2026-04-16 최종 실행)

| 항목 | 값 |
|---|---|
| 입력 논문 수 | 100 |
| Root 수 | 1 (cs.AI) |
| Intermediate 노드 수 | 9 |
| Leaf 배정 수 | 100 |
| 재표현(reexpress)된 논문 수 | 30 |
| 사용된 iterations | 2 |
| 미해소 soft overlap | 2편 (2602.03249, 2604.05383) |
| 실행 시간 | 30.5초 |
| 스키마 검증 | True (오류 없음) |

### 최종 트리 구조

```
cs.AI (root)
├── cs.AI::large language models::language model    [52편]
├── cs.AI::large language models::inference         [11편]
├── cs.AI::large language models::optimization      [12편]
├── cs.AI::language model::large language models    [?편]  (expanded_from: language model)
├── cs.AI::language model::reasoning                [?편]  (expanded_from: language model)
├── cs.AI::language model::intelligent agents       [?편]  (expanded_from: language model)
├── cs.AI::reasoning::semantics                     [?편]  (expanded_from: reasoning)
├── cs.AI::reasoning::inference                     [?편]  (expanded_from: reasoning)
└── cs.AI::reasoning::reinforcement learning        [?편]  (expanded_from: reasoning)
```

**Expansion 내역 (subtopic_expansion_threshold=10)**:
- `large language models` (75편) → `language model`, `inference`, `optimization` 3개 서브노드
- `language model` (14편) → `large language models`, `reasoning`, `intelligent agents` 3개 서브노드
- `reasoning` (11편) → `semantics`, `inference`, `reinforcement learning` 3개 서브노드

---

## 실험 이력 및 실패 기록

### Phase 1 — 기초 구현 (2026-04-14 00:49 ~ 01:53)

| 시각 | 소요시간 | intermediate 수 | reexpress | iter | 주요 이슈 |
|---|---|---|---|---|---|
| 00:49 | 52.1s | 3 | 15 | 1 | CSOClassifier 오류 5건 (`cannot convert float infinity to integer`, `isabelle%2Fhol`) |
| 00:52 | 63.3s | 3 | 30 | 1 | soft overlap 23편 미해소 |
| 01:19 | 59.4s | 3 | 13 | 2 | 점수 획일화(score=1.0이 94편), 분포 82/8/10 편중 |
| 01:53 | 58.1s | 3 | 4 | 1 | rank_score 수정 후 reexpress 감소했으나 분포 개선 미흡 |

**실패 원인 분석**:
- CSOClassifier의 igraph postprocessing에서 연결 불가 노드 경로 계산 시 `float('inf') → int` 변환 오류
- URL 인코딩된 토픽명(`isabelle%2Fhol`)이 그래프에 없어 KeyError
- syntactic+semantic weight 합산값이 대부분 1.0이라 top1/top2 margin이 거의 0 → soft overlap 과다

### Phase 2 — 점수 다양성 확보 시도 (2026-04-14 07:14 ~ 08:57)

| 시각 | 소요시간 | intermediate 수 | reexpress | iter | 조치 |
|---|---|---|---|---|---|
| 07:14 | 80.2s | 3 | 31 | 2 | rank_factor 도입 (rank penalty) |
| 07:20 | 87.3s | 3 | 25 | 4 | Jaccard 임계값 0.70→0.30 완화 |
| 07:26 | 149.3s | 3 | 29 | 4 | 부분문자열 병합 조건 추가 |
| 07:49 | 165.7s | 8 | 27 | 4 | 서브토픽 확장 최초 도입 (CSO children 기반) |
| 08:51 | 157.7s | 5 | 33 | 2 | CSO.3.5.csv 기반 동의어/synonym 단어장 통합 |
| 08:57 | 88.7s | 6 | 28 | 2 | reexpress 텍스트에 CSO phrase 전체 사용 |

**실패 원인 분석**:
- `language_model` CSO children가 `n-gram models`, `statistical language models` 등 고전적 토픽 → 현대 LLM 논문에 미매핑
- CSO children 기반 서브토픽 확장: 75편 중 30편 미만 coverage → expansion 취소 반복
- Jaccard 0.30 완화 시 `language model` / `large language models` 여전히 Jaccard=0.18 미병합 (병합했으나 둘 다 살아남음)
- 165초: max_iterations=4 × 서브토픽 reexpress가 중첩 실행되어 시간 폭증

### Phase 3 — CSO.3.5.csv 어휘 통합 + ProcessPool 병렬화 (2026-04-15)

**도입된 기능**:

1. **CSO.3.5.csv 기반 어휘 로더 (`_CSOOntology`)**: sameAs, relatedEquivalent를 synonyms로, preferentialEquivalent를 preferred로, contributesTo를 contributes_to로 파싱. `get_keywords()`가 whole phrase (공백 구분 단어가 아닌 전체 토픽 구문)를 반환하도록 수정.

2. **ProcessPoolExecutor + worker initializer**: `_worker_init()`이 worker 프로세스 당 1회 CSOClassifier를 미리 초기화. `_worker_classify()`가 초기화된 인스턴스를 재사용. `TreeBuilder._make_pool()`이 Pool을 생성하고 backend에 주입.

3. **CFOAdapter._classify_cache**: `(text, top_k) → list[dict]` 캐시. classify 호출 중복 제거.

4. **서브토픽 확장 전략 변경**: CSO children 직접 사용 → 이미 보유한 1차 분류 결과에서 현재 노드 라벨을 제외한 상위 토픽을 sub-candidates로 사용. CSOClassifier 재호출 없음.

**실패 기록**:

| 시도 | 결과 | 실패 원인 |
|---|---|---|
| workers=8 실험 | 122.3s (악화) | 8개 worker × CSOClassifier 초기화 (~8초) = 64초 오버헤드. OS swap 발생 가능성 |
| workers=4 (캐시 미저장) | 41.1s | `_classify_papers` parallel 결과가 `cfo._classify_cache`에 저장되지 않아 reexpress 배치가 전부 캐시 미스 |
| 캐시 key mismatch | reexpress 배치 무효 | `batch_results`가 `paper_id` 키인데 캐시는 `(text, top_k)` 키 → 캐시에 저장됐지만 lookup 시 미스. paper_id 자리에 텍스트 자체를 넣어 해결 |
| expansion에서 _iterative_reexpress 호출 | +13초 | expansion이 서브노드 배정에도 reexpress loop를 실행. `_simulate_assignment`로 교체해 해결 |
| max_iterations=6 + 조기종료 없음 | 최대 6회 reexpress | 개선 없어도 6번 반복. `prev_candidate_count` 기반 조기종료 추가 + max_iterations=3으로 감소 |
| `from run_experiment import _worker_classify` in tree_builder | 모듈 순환 의존 | tree_builder가 run_experiment를 import하면 결합도 문제. `_worker_classify_fn` 속성으로 분리 |
| pool warmup dummy task 없음 | 첫 실행 +4~5초 | Pool 생성 후 첫 map() 호출 전까지 worker가 대기 상태. dummy 4개 미리 실행해 해결 |

### Phase 4 — 최종 최적화 완료 (2026-04-16)

| 시각 | 소요시간 | intermediate 수 | 비고 |
|---|---|---|---|
| 02:43 | 72.4s | 3 | workers=4 복구 직후, OS 상태 불안정 (workers=8 이후 메모리 잔류) |
| 02:59 | 49.2s | 7 | expansion에서 _iterative_reexpress 제거 효과 |
| 03:09 | 35.3s | 7 | max_iterations=3 + 조기종료 적용 |
| 03:10 | 39.6s | 7 | 시스템 부하 변동 |
| 03:11 | 34.4s | 7 | pool warmup 추가 |
| 03:12 | 33.5s | 7 | 안정화 |
| 03:16 | 30.6s | 5 | **목표 근접** |
| 03:16 | **29.7s** | 8 | **30초 목표 최초 달성** |
| 03:17 | 31.2s | 6 | 시스템 부하 변동 |
| 03:18 | 30.5s | 9 | 안정 달성 |

---

## 주요 기술적 발견

### 1. CSOClassifier 내부 오류 패턴
- `cannot convert float infinity to integer`: igraph 경로 계산에서 연결 불가 노드를 `inf`로 반환할 때 int 변환 실패
- `'isabelle%2Fhol'`: URL 인코딩된 토픽명이 그래프 dict에 없을 때 KeyError
- **대응**: `modules="both"` 실패 시 `modules="syntactic"` 단독 재시도 (semantic 모듈이 igraph를 사용)

### 2. 점수 획일화 문제 (score=1.0이 94%)
- syntactic weight + semantic weight 합산 방식으로 대부분 1.0 반환
- rank_factor penalty 도입으로 점수 다양화 시도 → CSO phrase 기반 reexpress 텍스트가 CSOClassifier 인식률을 높여 근본적 해소

### 3. 서브토픽 확장의 coverage 문제
- `language_model` CSO children: `n-gram_models`, `statistical_language_models` 등 고전 토픽 → 현대 LLM 논문 95%가 매핑 안 됨
- **해결**: 1차 분류 결과(이미 보유)에서 현재 노드 외 토픽을 sub-candidates로 사용. Coverage 50% 이상일 때만 expansion 진행

### 4. workers 최적 수 (CPU 16코어 환경)
| workers | 100편 classify 시간 |
|---|---|
| 2 | 25.5s |
| 4 | 14.4s |
| 6 | 10.7s |
| 8 | 8.3s (첫 실행 기준) |
| 10 | 8.2s |
| 12 | 13.2s (degraded) |
| 16 | 16.5s (degraded) |

workers=8~10이 최적이나, 실제 실험에서는 CSOClassifier 초기화(~8초/worker)가 프로세스 총 기동 시간을 지배. workers=4가 안정적 최적점.

### 5. ProcessPool 재사용 vs 매번 생성
- 매번 생성(`with ProcessPoolExecutor`): ~69초 (초기화 오버헤드 반복)
- `TreeBuilder.__init__`에서 1회 생성 + 주입: ~42초
- Warmup dummy task 추가 후: ~30초

---

## 미해소 문제 (Known Issues)

### soft overlap 완전 해소 불가
- 일부 논문(2602.03249, 2604.05383 등)은 2개 이상의 노드에 동등하게 강하게 분류됨
- ambiguity_margin=0.08 기준 top1/top2 gap이 0.08 이하인 경우 reexpress로도 해소 불가
- **원인**: CSOClassifier가 해당 논문을 `language model`과 `reasoning` 모두에 동일 점수로 분류

### 노드 라벨 비결정성
- 동일 입력으로 실행마다 intermediate 노드 구성이 약간 달라짐 (5~9개)
- **원인**: CSOClassifier 내부 semantic 모듈의 word2vec 유사도 계산에서 부동소수점 비교 순서 비결정성

### CSO 토픽명과 현대 AI 연구 주제 간 괴리
- CSO.3.5.csv 기준 `language_model` children에 `transformer`, `llm`, `gpt` 없음
- expansion 후 sub-node 라벨이 `large language models`, `intelligent agents`, `inference` 등 CSO 어휘에 의존

---

## 파일 구조

```
E:/Category/
├── CSO.3.5.csv           # CSO 온톨로지 (26MB, git-lfs 권장)
├── schemas.py            # INPUT_SCHEMA / OUTPUT_SCHEMA (JSON Schema draft-2020-12)
├── tree_builder.py       # 핵심 분류 엔진
└── test_tree_builder.py  # pytest 테스트 (13개)

E:/experiment/
├── run_experiment.py     # 실험 실행 스크립트 (RealCSOClassifier 브리지)
├── data/
│   └── papers_100.json   # 입력 데이터 (100편 cs.AI 논문)
├── logs/
│   └── experiment.log    # 전체 실험 로그
└── results/
    ├── tree_output.json  # 최종 트리 출력 (JSON Schema 검증 통과)
    └── analysis.json     # 요약 분석
```

---

## 성능 변화 요약

| 단계 | 소요시간 | intermediate 수 | soft overlap |
|---|---|---|---|
| 초기 구현 | 52~63s | 3 | 23편 |
| Jaccard 병합 + rank penalty | 80~165s | 3 | 4~9편 |
| CSO 어휘 통합 + 서브토픽 확장 | 88~165s | 5~8 | 2~19편 |
| ProcessPool workers=4 (pool 재생성) | ~69s | — | — |
| Pool 재사용 (TreeBuilder 관리) | ~42s | 5~8 | 2~15편 |
| expansion에서 reexpress 제거 | ~35~50s | 7~9 | 2~15편 |
| max_iterations=3 + 조기종료 | 30~38s | 5~9 | 2~15편 |
| Pool warmup dummy task | **29~31s** | 5~9 | 2~15편 |
