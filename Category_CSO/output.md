# CSO Categorisation 실험 결과

## 1. 실험 개요

### 목적

OpenSearch(arXiv Atom API)로 LLM 관련 논문 100편을 수집하고, CSO.3.5 온톨로지 기반 TreeBuilder로 분류 트리를 생성한다.

### 실험 환경

| 항목          | 값                                              |
| ------------- | ----------------------------------------------- |
| 실험 일시     | 2026-04-26                                      |
| Python 버전   | 3.11.0                                          |
| 분류기        | `_CSOClassifier` (CSO.3.5.csv 기반 내장 분류기) |
| 온톨로지      | CSO v3.5 (`CSO.3.5.csv`, 26MB)                  |
| DB            | SQLite (`results/experiment.db`)                |
| 실행 스크립트 | `fetch_and_classify.py`                         |

---

## 2. 실험 절차

### Step 1 — 논문 수집 (OpenSearch via arXiv Atom API)

arXiv의 공개 검색 API를 사용해 LLM 관련 최신 논문을 수집했다. arXiv API는 Apache Lucene 기반 OpenSearch 엔진으로 동작하며, `search_query` 파라미터로 필드 프리픽스(`ti:`, `cat:`)와 Boolean 연산자(`AND`, `OR`)를 지원한다.

**검색 쿼리:**

```
cat:cs.AI AND (
  ti:"large language model" OR ti:LLM OR
  ti:"language model"       OR ti:"GPT" OR
  ti:"instruction tuning"   OR ti:"RLHF" OR
  ti:"chain of thought"     OR ti:"prompt"
)
```

**수집 설정:**

- 정렬 기준: `submittedDate` 내림차순 (재현성 확보)
- 페이지 크기: 50편 × 2회 배치
- 배치 간 대기: 3초 (arXiv API rate-limit 권고 준수)
- 중복 제거: `paper_id` 기준 deduplication 적용

**수집 결과 (100편):**

| arXiv primary category | 논문 수 |     비율 |
| ---------------------- | ------: | -------: |
| cs.AI                  |      31 |      31% |
| cs.CL                  |      25 |      25% |
| cs.CV                  |      10 |      10% |
| cs.CR                  |      10 |      10% |
| cs.LG                  |       7 |       7% |
| cs.SE                  |       5 |       5% |
| cs.MA                  |       3 |       3% |
| cs.CY                  |       2 |       2% |
| cond-mat.mtrl-sci      |       2 |       2% |
| cs.SD                  |       2 |       2% |
| cs.HC                  |       1 |       1% |
| cs.IR                  |       1 |       1% |
| cs.NI                  |       1 |       1% |
| **합계**               | **100** | **100%** |

> arXiv의 `cat:cs.AI` 쿼리는 cs.AI를 primary 또는 cross-list로 가진 논문을 모두 반환한다. 따라서 수집된 100편의 primary category 분포가 cs.AI 이외 카테고리에도 걸쳐 있는 것은 정상적인 현상이다(cs.AI → cs.CL cross-list 정책 등).

---

### Step 2 — CSO 분류 (TreeBuilder)

수집된 100편을 `TreeBuilder.build_tree()`에 입력해 3레벨 분류 트리를 생성했다.

**run_config 설정:**

| 파라미터                          | 값    | 설명                                        |
| --------------------------------- | ----- | ------------------------------------------- |
| `max_iterations`                  | 2     | 재표현 최대 반복 횟수                       |
| `top_k`                           | 5     | 논문당 상위 K개 CSO 토픽 후보               |
| `ambiguity_margin`                | 0.08  | soft overlap 판정 margin (top1-top2 점수차) |
| `max_intermediate_nodes_per_root` | 3     | root당 최대 중간 노드 수                    |
| `subtopic_expansion_threshold`    | 20    | 노드 자동 확장 기준 논문 수                 |
| `max_expansion_depth`             | 3     | 서브토픽 재귀 확장 최대 깊이                |
| `allow_arxiv_fetch`               | false | arXiv API 2차 호출 비활성화                 |
| `root_allowlist`                  | null  | 전체 primary category 처리                  |

**분류 알고리즘 흐름:**

```
[입력 100편]
    ↓
[primary category 기준 root 그룹화]  → 13개 root
    ↓ (root별 병렬 처리)
[CFO classify(title + abstract, top_k=5)]
    ↓
[라벨 빈도/점수 집계 → Jaccard 병합 → 1~3개 intermediate 라벨 선택]
    ↓
[결정적 배정: score desc → label_id asc → paper_id asc]
    ↓
[soft overlap 탐지 (margin=0.08) → 재표현 루프 (max 2회)]
    ↓
[불변식 검증: 누락 없음 / 중복 없음 / children≥2]
    ↓
[SQLite 저장 + JSON 출력]
```

**소요 시간:** 0.58초 (CSO.3.5.csv 온톨로지 로드 포함)

---

## 3. 분류 결과 요약

### 전체 통계

| 지표                             |       값 |
| -------------------------------- | -------: |
| 입력 논문 수                     |      100 |
| root 수 (arXiv primary category) |       13 |
| intermediate 노드 수             |       13 |
| 배정 완료 논문 수 (리프)         |      100 |
| 재표현(re-expression)된 논문 수  |       97 |
| 재표현 반복 횟수                 |        1 |
| 스키마 검증 통과 (`is_valid`)    | **True** |
| 오류                             |        0 |
| 경고                             |        5 |

### 경고 목록

| #   | 내용                                                                                                                   |
| --- | ---------------------------------------------------------------------------------------------------------------------- |
| 1~2 | `cond-mat.mtrl-sci` · `cs.AI` root의 `abstracting_and_indexing` 노드 확장 시도 → singleton sub-node 발생으로 확장 취소 |
| 3   | `cs.HC` root 논문 수 = 1 → children≥2 불가, children≥1 예외 허용                                                       |
| 4   | `cs.IR` root 논문 수 = 1 → 동일 예외                                                                                   |
| 5   | `cs.NI` root 논문 수 = 1 → 동일 예외                                                                                   |

---

## 4. 분류 트리 (root → intermediate node → papers)

> 모든 root에서 intermediate node가 1개(`abstracting_and_indexing`)로 수렴했다. CSO 내장 분류기가 LLM 도메인 키워드와 직접 매핑되는 토픽을 찾지 못해 재표현 후 공통 상위 토픽으로 수렴한 결과다(자세한 분석은 §5 참조).

---

### root: cs.AI (31편)

**intermediate node:** `cs.AI::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                                                          | score |   재표현   |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.19221v1 | UAF: A Unified Audio Front-end LLM for Full-Duplex Speech Interaction                                                                         |  0.80 | ✓ (iter 1) |
| 2604.19301v1 | Large Language Models Exhibit Normative Conformity                                                                                            |  0.80 | ✓ (iter 1) |
| 2604.19354v1 | Do Agents Dream of Root Shells? Partial-Credit Evaluation of LLM Agents in Capture The Flag Challenges                                        |  0.80 | ✓ (iter 1) |
| 2604.19398v1 | GRASPrune: Global Gating for Budgeted Structured Pruning of Large Language Models                                                             |  0.80 | ✓ (iter 1) |
| 2604.19459v1 | Do LLMs Game Formalization? Evaluating Faithfulness in Logical Reasoning                                                                      |  0.80 | ✓ (iter 1) |
| 2604.19561v1 | Detecting Data Contamination in Large Language Models                                                                                         |  0.80 | ✓ (iter 1) |
| 2604.19567v1 | Multi-modal Reasoning with LLMs for Visual Semantic Arithmetic                                                                                |  0.80 | ✓ (iter 1) |
| 2604.19638v1 | SafetyALFRED: Evaluating Safety-Conscious Planning of Multimodal Large Language Models                                                        |  0.80 | ✓ (iter 1) |
| 2604.20039v1 | Separable Pathways for Causal Reasoning: How Architectural Scaffolding Enables Hypothesis-Space Restructuring in LLM Agents                   |  0.80 | ✓ (iter 1) |
| 2604.20140v1 | HiPO: Hierarchical Preference Optimization for Adaptive Reasoning in LLMs                                                                     |  0.80 | ✓ (iter 1) |
| 2604.20261v1 | Memory-Augmented LLM-based Multi-Agent System for Automated Feature Generation on Tabular Data                                                |  0.80 | ✓ (iter 1) |
| 2604.20273v1 | ActuBench: A Multi-Agent LLM Pipeline for Generation and Evaluation of Actuarial Reasoning Tasks                                              |  0.80 | ✓ (iter 1) |
| 2604.20652v2 | Large Language Models Outperform Humans in Fraud Detection and Resistance to Motivated Investor Pressure                                      |  0.80 | ✓ (iter 1) |
| 2604.20795v1 | Automatic Ontology Construction Using LLMs as an External Layer of Memory, Verification, and Planning for Hybrid Intelligent Systems          |  0.80 | ✓ (iter 1) |
| 2604.20811v1 | Diagnosing CFG Interpretation in LLMs                                                                                                         |  0.80 | ✓ (iter 1) |
| 2604.20987v1 | Co-Evolving LLM Decision and Skill Bank Agents for Long-Horizon Tasks                                                                         |  0.80 | ✓ (iter 1) |
| 2604.20995v1 | Value-Conflict Diagnostics Reveal Widespread Alignment Faking in Language Models                                                              |  0.80 | ✓ (iter 1) |
| 2604.21036v1 | Who Defines Fairness? Target-Based Prompting for Demographic Representation in Generative Models                                              |  0.80 | ✓ (iter 1) |
| 2604.21092v1 | Mind the Prompt: Self-adaptive Generation of Task Plan Explanations via LLMs                                                                  |  0.80 | ✓ (iter 1) |
| 2604.21098v1 | Propensity Inference: Environmental Contributors to LLM Behaviour                                                                             |  0.80 | ✓ (iter 1) |
| 2604.21193v1 | Trust but Verify: Introducing DAVinCI — A Framework for Dual Attribution and Verification in Claim Inference for Language Models              |  0.80 | ✓ (iter 1) |
| 2604.21209v1 | Align Generative Artificial Intelligence with Human Preferences: A Novel Large Language Model Fine-Tuning Method for Online Review Management |  0.80 | ✓ (iter 1) |
| 2604.21264v1 | Enhancing Online Recruitment with Category-Aware MoE and LLM-based Data Augmentation                                                          |  0.80 | ✓ (iter 1) |
| 2604.21284v1 | Spatial Metaphors for LLM Memory: A Critical Analysis of the MemPalace Architecture                                                           |  0.80 | ✓ (iter 1) |
| 2604.21334v1 | Ideological Bias in LLMs' Economic Causal Reasoning                                                                                           |  0.80 | ✓ (iter 1) |
| 2604.21357v1 | ReaGeo: Reasoning-Enhanced End-to-End Geocoding with LLMs                                                                                     |  0.80 | ✓ (iter 1) |
| 2604.21549v1 | Unbiased Prevalence Estimation with Multicalibrated LLMs                                                                                      |  0.80 | ✓ (iter 1) |
| 2604.21571v1 | Separable Expert Architecture: Toward Privacy-Preserving LLM Personalization via Composable Adapters and Deletable User Proxies               |  0.80 | ✓ (iter 1) |
| 2604.21584v1 | CoFEE: Reasoning Control for LLM-Based Feature Discovery                                                                                      |  0.80 | ✓ (iter 1) |
| 2604.21769v1 | Who Defines "Best"? Towards Interactive, User-Defined Evaluation of LLM Leaderboards                                                          |  0.80 | ✓ (iter 1) |
| 2604.21896v1 | Nemobot Games: Crafting Strategic AI Gaming Agents for Interactive Learning with Large Language Models                                        |  0.80 | ✓ (iter 1) |

---

### root: cs.CL (25편)

**intermediate node:** `cs.CL::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                                                    | score |   재표현   |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.19245v2 | Talking to a Know-It-All GPT or a Second-Guesser Claude? How Repair reveals unreliable Multi-Turn Behavior in LLMs                      |  0.80 | ✓ (iter 1) |
| 2604.19262v1 | CulturALL: Benchmarking Multilingual and Multicultural Competence of LLMs on Grounded Tasks                                             |  0.80 | ✓ (iter 1) |
| 2604.19292v1 | Location Not Found: Exposing Implicit Local and Global Biases in Multilingual LLMs                                                      |  0.80 | ✓ (iter 1) |
| 2604.19298v1 | IndiaFinBench: An Evaluation Benchmark for Large Language Model Performance on Indian Financial Regulatory Text                         |  0.80 | ✓ (iter 1) |
| 2604.19299v1 | Rethinking Scale: Deployment Trade-offs of Small Language Models under Agent Paradigms                                                  |  0.80 | ✓ (iter 1) |
| 2604.19578v1 | Impact of large language models on peer review opinions from a fine-grained perspective: Evidence from top conference proceedings in AI |  0.80 | ✓ (iter 1) |
| 2604.19598v2 | Cross-Model Consistency of AI-Generated Exercise Prescriptions: A Repeated Generation Study Across Three Large Language Models          |  0.80 | ✓ (iter 1) |
| 2604.19884v1 | From Signal Degradation to Computation Collapse: Uncovering the Two Failure Modes of LLM Quantization                                   |  0.80 | ✓ (iter 1) |
| 2604.19887v1 | Depression Risk Assessment in Social Media via Large Language Models                                                                    |  0.80 | ✓ (iter 1) |
| 2604.20043v1 | TriEx: A Game-based Tri-View Framework for Explaining Internal Reasoning in Multi-Agent LLMs                                            |  0.80 | ✓ (iter 1) |
| 2604.20148v1 | Meta-Tool: Efficient Few-Shot Tool Adaptation for Small Language Models                                                                 |  0.80 | ✓ (iter 1) |
| 2604.20244v1 | Hybrid Policy Distillation for LLMs                                                                                                     |  0.80 | ✓ (iter 1) |
| 2604.20331v2 | Surrogate modeling for interpreting black-box LLMs in medical predictions                                                               |  0.80 | ✓ (iter 1) |
| 2604.20487v2 | Knowledge Capsules: Structured Nonparametric Memory Units for LLMs                                                                      |  0.80 | ✓ (iter 1) |
| 2604.20556v1 | LayerTracer: A Joint Task-Particle and Vulnerable-Layer Analysis framework for Arbitrary Large Language Model Architectures             |  0.80 | ✓ (iter 1) |
| 2604.20726v2 | Exploiting LLM-as-a-Judge Disposition on Free Text Legal QA via Prompt Optimization                                                     |  0.80 | ✓ (iter 1) |
| 2604.20791v1 | Can "AI" Be a Doctor? A Study of Empathy, Readability, and Alignment in Clinical LLMs                                                   |  0.80 | ✓ (iter 1) |
| 2604.20817v1 | Convergent Evolution: How Different Language Models Learn Similar Number Representations                                                |  0.80 | ✓ (iter 1) |
| 2604.21076v1 | Serialisation Strategy Matters: How FHIR Data Format Affects LLM Medication Reconciliation                                              |  0.80 | ✓ (iter 1) |
| 2604.21223v1 | Zero-Shot Detection of LLM-Generated Text via Implicit Reward Model                                                                     |  0.80 | ✓ (iter 1) |
| 2604.21276v1 | Do LLM Decoders Listen Fairly? Benchmarking How Language Model Priors Shape Bias in Speech Recognition                                  |  0.80 | ✓ (iter 1) |
| 2604.21454v1 | Reasoning Primitives in Hybrid and Non-Hybrid LLMs                                                                                      |  0.80 | ✓ (iter 1) |
| 2604.21611v1 | Process Supervision via Verbal Critique Improves Reasoning in Large Language Models                                                     |  0.80 | ✓ (iter 1) |
| 2604.21748v1 | StructMem: Structured Memory for Long-Horizon Behavior in LLMs                                                                          |  0.80 | ✓ (iter 1) |
| 2604.21751v1 | Why are all LLMs Obsessed with Japanese Culture? On the Hidden Cultural and Regional Biases of LLMs                                     |  0.80 | ✓ (iter 1) |

---

### root: cs.CR (10편)

**intermediate node:** `cs.CR::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                | score |   재표현   |
| ------------ | --------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.19533v3 | Cyber Defense Benchmark: Agentic Threat Hunting Evaluation for LLMs in SecOps                       |  0.80 | ✓ (iter 1) |
| 2604.20179v1 | Taint-Style Vulnerability Detection and Confirmation for Node.js Packages Using LLM Agent Reasoning |  0.80 | ✓ (iter 1) |
| 2604.20269v1 | Text Steganography with Dynamic Codebook and Multimodal Large Language Model                        |  0.80 | ✓ (iter 1) |
| 2604.20389v1 | CyberCertBench: Evaluating LLMs in Cybersecurity Certification Knowledge                            |  0.80 | ✓ (iter 1) |
| 2604.20911v1 | Omission Constraints Decay While Commission Constraints Persist in Long-Context LLM Agents          |  0.80 | ✓ (iter 1) |
| 2604.20930v1 | SafeRedirect: Defeating Internal Safety Collapse via Task-Completion Redirection in Frontier LLMs   |  0.80 | ✓ (iter 1) |
| 2604.21083v1 | Behavioral Consistency and Transparency Analysis on Large Language Model API Gateways               |  0.80 | ✓ (iter 1) |
| 2604.21159v1 | Adaptive Instruction Composition for Automated LLM Red-Teaming                                      |  0.80 | ✓ (iter 1) |
| 2604.21700v1 | Stealthy Backdoor Attacks against LLMs Based on Natural Style Triggers                              |  0.80 | ✓ (iter 1) |
| 2604.21860v1 | Transient Turn Injection: Exposing Stateless Multi-Turn Vulnerabilities in Large Language Models    |  0.80 | ✓ (iter 1) |

---

### root: cs.CV (10편)

**intermediate node:** `cs.CV::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                                             | score |   재표현   |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.19839v1 | Environmental Understanding Vision-Language Model for Embodied Agent                                                             |  0.80 | ✓ (iter 1) |
| 2604.19937v1 | Infection-Reasoner: A Compact Vision-Language Model for Wound Infection Classification with Evidence-Grounded Clinical Reasoning |  0.80 | ✓ (iter 1) |
| 2604.19966v1 | DistortBench: Benchmarking Vision Language Models on Image Distortion Identification                                             |  0.80 | ✓ (iter 1) |
| 2604.20012v1 | EmbodiedMidtrain: Bridging the Gap between Vision-Language Models and Vision-Language-Action Models via Mid-training             |  0.80 | ✓ (iter 1) |
| 2604.20544v1 | Evian: Towards Explainable Visual Instruction-tuning Data Auditing                                                               |  0.80 | ✓ (iter 1) |
| 2604.20806v1 | OMIBench: Benchmarking Olympiad-Level Multi-Image Reasoning in Large Vision-Language Model                                       |  0.80 | ✓ (iter 1) |
| 2604.20983v1 | Thinking Like a Botanist: Challenging Multimodal Language Models with Intent-Driven Chain-of-Inquiry                             |  0.80 | ✓ (iter 1) |
| 2604.21102v1 | Leveraging Multimodal LLMs for Built Environment and Housing Attribute Assessment from Street-View Imagery                       |  0.80 | ✓ (iter 1) |
| 2604.21396v1 | VG-CoT: Towards Trustworthy Visual Reasoning via Grounded Chain-of-Thought                                                       |  0.80 | ✓ (iter 1) |
| 2604.21911v1 | When Prompts Override Vision: Prompt-Induced Hallucinations in LVLMs                                                             |  0.80 | ✓ (iter 1) |

---

### root: cs.LG (7편)

**intermediate node:** `cs.LG::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                 | score |   재표현   |
| ------------ | ---------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.19321v1 | RDP LoRA: Geometry-Driven Identification for Parameter-Efficient Adaptation in Large Language Models |  0.80 | ✓ (iter 1) |
| 2604.19485v1 | EVPO: Explained Variance Policy Optimization for Adaptive Critic Utilization in LLM Post-Training    |  0.80 | ✓ (iter 1) |
| 2604.20904v1 | Reinforcing privacy reasoning in LLMs via normative simulacra from fiction                           |  0.80 | ✓ (iter 1) |
| 2604.20915v1 | Absorber LLM: Harnessing Causal Synchronization for Test-Time Training                               |  0.80 | ✓ (iter 1) |
| 2604.20933v1 | IRIS: Interpolative Rényi Iterative Self-play for Large Language Model Fine-Tuning                   |  0.80 | ✓ (iter 1) |
| 2604.21251v1 | CAP: Controllable Alignment Prompting for Unlearning in LLMs                                         |  0.80 | ✓ (iter 1) |
| 2604.21365v1 | mcdok at SemEval-2026 Task 13: Finetuning LLMs for Detection of Machine-Generated Code               |  0.80 | ✓ (iter 1) |

---

### root: cs.SE (5편)

**intermediate node:** `cs.SE::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                                          | score |   재표현   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.20211v1 | Towards Secure Logging: Characterizing and Benchmarking Logging Code Security Issues with LLMs                                |  0.80 | ✓ (iter 1) |
| 2604.20523v1 | Early-Stage Product Line Validation Using LLMs: A Study on Semi-Formal Blueprint Analysis                                     |  0.80 | ✓ (iter 1) |
| 2604.21090v1 | Structural Quality Gaps in Practitioner AI Governance Prompts: An Empirical Study Using a Five-Principle Evaluation Framework |  0.80 | ✓ (iter 1) |
| 2604.21579v1 | A Metamorphic Testing Approach to Diagnosing Memorization in LLM-Based Program Repair                                         |  0.80 | ✓ (iter 1) |
| 2604.21598v1 | DryRUN: On the Role of Public Tests in LLM-Driven Code Generation                                                             |  0.80 | ✓ (iter 1) |

---

### root: cs.MA (3편)

**intermediate node:** `cs.MA::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                          | score |   재표현   |
| ------------ | ------------------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.19540v1 | Mesh Memory Protocol: Semantic Infrastructure for Multi-Agent LLM Systems                                     |  0.80 | ✓ (iter 1) |
| 2604.20582v1 | Trust, Lies, and Long Memories: Emergent Social Dynamics and Reputation in Multi-Round Avalon with LLM Agents |  0.80 | ✓ (iter 1) |
| 2604.20732v1 | Anchor-and-Resume Concession Under Dynamic Pricing for LLM-Augmented Freight Negotiation                      |  0.80 | ✓ (iter 1) |

---

### root: cs.CY (2편)

**intermediate node:** `cs.CY::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                         | score |   재표현   |
| ------------ | ------------------------------------------------------------------------------------------------------------ | ----: | :--------: |
| 2604.19984v1 | Bias in the Tails: How Name-conditioned Evaluative Framing in Resume Summaries Destabilizes LLM-based Hiring |  0.80 | ✓ (iter 1) |
| 2604.21152v1 | Dialect vs Demographics: Quantifying LLM Bias from Implicit Linguistic Signals vs. Explicit User Profiles    |  0.80 | ✓ (iter 1) |

---

### root: cond-mat.mtrl-sci (2편)

**intermediate node:** `cond-mat.mtrl-sci::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                | score |   재표현   |
| ------------ | ----------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.20304v1 | LLM-guided phase diagram construction through high-throughput experimentation       |  0.80 | ✓ (iter 1) |
| 2604.20899v1 | Predicting Scale-Up of Metal-Organic Framework Syntheses with Large Language Models |  0.80 | ✓ (iter 1) |

---

### root: cs.SD (2편)

**intermediate node:** `cs.SD::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                                             | score |   재표현   |
| ------------ | ---------------------------------------------------------------------------------------------------------------- | ----: | :--------: |
| 2604.19300v1 | HalluAudio: A Comprehensive Benchmark for Hallucination Detection in Large Audio-Language Models                 |  0.80 | ✓ (iter 1) |
| 2604.19635v1 | Towards Streaming Target Speaker Extraction via Chunk-wise Interleaved Splicing of Autoregressive Language Model |  0.80 | ✓ (iter 1) |

---

### root: cs.HC (1편) ⚠ singleton 예외

**intermediate node:** `cs.HC::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                              | score | 재표현 |
| ------------ | ------------------------------------------------------------------------------------------------- | ----: | :----: |
| 2604.19971v1 | Semantic Prompting: Agentic Incremental Narrative Refinement through Spatial Semantic Interaction |  0.10 |   —    |

---

### root: cs.IR (1편) ⚠ singleton 예외

**intermediate node:** `cs.IR::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                                         | score | 재표현 |
| ------------ | -------------------------------------------------------------------------------------------- | ----: | :----: |
| 2604.21536v1 | Pre-trained LLMs Meet Sequential Recommenders: Efficient User-Centric Knowledge Distillation |  0.10 |   —    |

---

### root: cs.NI (1편) ⚠ singleton 예외

**intermediate node:** `cs.NI::abstracting_and_indexing` — Abstracting And Indexing

| paper_id     | 제목                                                                          | score | 재표현 |
| ------------ | ----------------------------------------------------------------------------- | ----: | :----: |
| 2604.21231v1 | SparKV: Overhead-Aware KV Cache Loading for Efficient On-Device LLM Inference |  0.10 |   —    |

---

## 5. 분석 및 한계

### 관찰된 현상

**모든 root에서 intermediate node가 `abstracting_and_indexing` 1개로 수렴**했다. 원인은 다음과 같다:

1. **CSO v3.5 온톨로지의 LLM 토픽 미포함**: CSO v3.5는 2023년 이전 컴퓨터 과학 분류 체계를 기반으로 한다. "large language model", "LLM", "instruction tuning", "RLHF", "chain of thought" 등 2022년 이후 급성장한 LLM 특유 키워드들이 CSO 토픽으로 등록되어 있지 않다.

2. **내장 `_CSOClassifier`의 동작**: 키워드 매칭으로 점수를 산출하는데, LLM 논문의 title/abstract에 CSO 토픽 키워드가 직접 등장하지 않아 모든 논문이 낮은 점수로 동일한 fallback 토픽(`abstracting_and_indexing`)으로 수렴했다.

3. **재표현(re-expression) 결과**: 97편이 재표현을 거쳤으나(iter=1), 재표현 텍스트도 CSO 내 해당 토픽이 없어 동일 노드로 재배정됐다.

4. **singleton root**: cs.HC, cs.IR, cs.NI 각 1편으로 children≥2 불가 → 예외 처리 후 경고 기록.

### 개선 방향

| 문제                     | 개선 방안                                                                                                                                                |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CSO 토픽 미등록          | CSO v3.5 대신 외부 LLM 분류기(`cso-classifier` v4.0.0) 주입 — semantic matching으로 "language model", "transformer" 등 연관 토픽 탐색 가능               |
| intermediate node 단일화 | `max_intermediate_nodes_per_root=3` + 외부 분류기로 "knowledge representation", "natural language processing", "machine learning" 등 상위 토픽 분리 기대 |
| singleton root           | 검색 쿼리를 `cat:cs.AI`로 제한하거나, `root_allowlist=["cs.AI","cs.CL","cs.LG"]`로 주요 카테고리만 선택                                                  |

---

## 6. 출력 파일

| 파일                                                 | 설명                                            |
| ---------------------------------------------------- | ----------------------------------------------- |
| [results/raw_papers.json](results/raw_papers.json)   | arXiv API 수집 원본 (100편 전체 메타데이터)     |
| [results/tree_output.json](results/tree_output.json) | TreeBuilder 출력 전체 (OUTPUT_SCHEMA 검증 통과) |
| [results/analysis.json](results/analysis.json)       | 노드별 논문 목록, 통계, 경고 요약               |
| [results/experiment.db](results/experiment.db)       | SQLite DB (cfo_runs, cfo_assignments 테이블)    |
| [fetch_and_classify.py](fetch_and_classify.py)       | 수집 + 분류 실험 스크립트                       |

---

## 7. 재현 방법

```bash
# 1. 의존성
pip install jsonschema

# 2. 실험 실행 (arXiv API → CSO 분류 → 결과 저장)
"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe" fetch_and_classify.py

# 출력:
#   results/raw_papers.json   — 수집된 논문 원본
#   results/tree_output.json  — 분류 트리 JSON
#   results/analysis.json     — 통계 요약
#   results/experiment.db     — SQLite 영속 저장
```

외부 CSO 분류기를 주입하려면 `fetch_and_classify.py`의 `TreeBuilder(cso_instance=None, ...)` 부분에 `RealCSOClassifier()` 인스턴스를 전달하면 된다.
