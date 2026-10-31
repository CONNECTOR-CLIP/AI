# Reserch_Plen: 연구계획서 및 논문 틀 생성 기능

CoT5까지 통과한 아이디어를 입력받아 **연구계획서**와 **논문의 틀**을 만드는 기능이다.
실험 결과가 없는 상태이므로 논문 초안은 만들지 않는다(교수님 정의 기준).
단계별 설계는 `docs/implementation_plan.md`에 있다.

## 현재 상태: 데모

1~6단계(`run`)가 동작한다. 실제 LLM으로는 6번 아이디어에서 확인했다. 7단계 비교 평가는 시범 1회만 실행했고, 8단계는 시작 전이다. 앞으로 고칠 부분과 사람이 점검할 부분은 `docs/revision_guidebook.md`에 있다.

## 빠른 사용법

`.env.example`을 `.env`로 복사하고 `OPENROUTER_API_KEY`를 채운 뒤:

```powershell
$env:PYTHONPATH = "src"
python -m research_plan list --run-dir data/cot45_public_run_20261029_154552
python -m research_plan run  --run-dir data/cot45_public_run_20261029_154552 --idea 6
```

결과는 `out/<run_id>/idea06/`에 생긴다. 사람이 `plan.reviewed.json`을 고쳤다면 `--from write`를 붙여 다시 실행한다. 실행 기록은 `run_manifest.json`, 이전 결과는 `history/`에 있다. 확인 방법은 `docs/human_review.md`.

사람이 결과를 확인하고 고치는 방법은 `docs/human_review.md`에 있다.

| 산출물 | 경로 | 내용 |
|---|---|---|
| 출력 명세 | `docs/output_spec.md` | 입력·산출물 3종·연결 규칙·고정 제목·금지 규칙 |
| 필드 정의서 | `docs/field_definitions.md` | 15개 필수 요소 + 3개 추가 요소의 정의, 출처, 좋은 값의 기준 |
| JSON 스키마 | `schema/plan.schema.json` | 1차 출력(plan.json) 구조. `src/research_plan/schemas.py`에서 생성 |
| 문서 템플릿 | `templates/*.md.tmpl` | 연구계획서와 논문 틀의 고정 구조 + 절별 작성 지침 |
| 정답 예시 | `examples/golden/idea06_unsupported_token/` | 후보 6번("unsupported" 토큰)을 사람이 직접 채운 plan.json, research_plan.md, paper_skeleton.md |
| 검증기 | `src/research_plan/validate.py` | 필드 누락, 근거 경로, ID 연결, 인용 화이트리스트, 결과 단정 표현 검사 |
| 실행 데이터 | `data/cot45_public_run_20261029_154552/` | Category 브랜치 `3255acb`에서 복사한 FutureWork·CoT1~CoT5 결과와 manifest 2개 |
| 입력 어댑터 | `src/research_plan/inputs.py`, `evidence.py`, `cli.py` | 실행 폴더를 읽어 후보를 짝짓고, 고른 후보의 `evidence.json`을 만든다 |
| plan.json 생성 | `src/research_plan/extract.py`, `provider.py`, `prompts/` | OpenRouter LLM이 필드 묶음 3개를 차례로 쓰고, 검사에 걸린 묶음만 다시 쓴다 |
| 심사와 보완 | `src/research_plan/review.py`, `prompts/judge.md` | 판정 LLM이 필드별 점수와 지적 사항을 내고, 기준 미달 묶음만 1회 다시 쓴다 |
| 문서 작성 | `src/research_plan/write.py`, `prompts/write_*.md` | 표·목록은 코드가 plan에서 옮기고, 연결 문단과 논문의 틀만 LLM이 쓴다 |
| 인용·날조 검사 | `src/research_plan/verify.py` | arXiv 실재·제목 확인, plan에 없는 숫자·이름, 결과 단정 표현 (LLM 없음) |
| 한 줄 실행 | `src/research_plan/pipeline.py` | 1~5단계 연결, `--from` 재시작, 자동 백업, `run_manifest.json` |
| 평가 | `src/research_plan/evaluate.py`, `prompts/baseline_*.md`, `prompts/eval_judge.md` | free·template·pipeline을 같은 근거로 비교. 자동 지표, 눈가림 LLM 판정(여러 회사 모델), 사람 평가지 |
| 테스트 | `tests/` | 136개 (가짜 모델·가짜 arXiv, 네트워크 없음) |

외부 패키지가 필요 없다(Python 3.11 이상, 표준 라이브러리만 사용).

## 실행 방법

### 1단계: 후보 보기와 선택

```powershell
cd C:\Users\YJ\Desktop\Project_code\Reserch_Plen
$env:PYTHONPATH = "src"
python -m research_plan list   --run-dir data/cot45_public_run_20261029_154552
python -m research_plan select --run-dir data/cot45_public_run_20261029_154552 --idea 6
```

`select`는 `out/<run_id>/idea06/evidence.json`을 만든다. NOT_NOVEL 후보는 `--allow-not-novel`을 붙여야 고를 수 있다.
`--run-dir`에는 `examples_run_manifest.json`이 있는 폴더를 준다. Category 브랜치를 체크아웃한 `New_Future-Work-Researcher` 폴더를 그대로 줘도 된다.

### 2단계: plan.json 생성 (LLM)

`.env.example`을 `.env`로 복사하고 `OPENROUTER_API_KEY`를 채운 뒤 실행한다.

```powershell
python -m research_plan extract --evidence out/cot45_public_run_20261029_154552/idea06/evidence.json
```

같은 폴더에 `plan.json`(검사 통과) 또는 `plan.draft.json`(통과 못 함)과 `extract_log.json`이 생긴다. 모델은 기본 `openai/gpt-6-luna`이며 `--model`로 바꿀 수 있다.

### 3단계: 심사와 보완 (LLM)

```powershell
python -m research_plan review --plan out/cot45_public_run_20261029_154552/idea06/plan.json
```

같은 폴더에 `plan.reviewed.json`과 `review.json`이 생긴다. 원래 `plan.json`은 그대로 둔다. 판정 모델은 기본 `openai/gpt-6-luna-pro`이고, `--no-refine`을 붙이면 심사만 한다.

### 4단계: 문서 작성 (LLM)

```powershell
python -m research_plan write --plan out/cot45_public_run_20261029_154552/idea06/plan.reviewed.json
```

같은 폴더에 `research_plan.md`, `paper_skeleton.md`, `write_log.json`이 생긴다. 사람이 `plan.reviewed.json`을 고쳤다면 먼저 `check`(LLM 호출 없음)로 확인한다.

```powershell
python -m research_plan check --plan out/cot45_public_run_20261029_154552/idea06/plan.reviewed.json
```

### 5단계: 인용·날조 검사 (LLM 없음, 무료)

```powershell
python -m research_plan verify --plan out/cot45_public_run_20261029_154552/idea06/plan.reviewed.json
```

같은 폴더에 `verify_report.json`이 생긴다. arXiv 조회 결과는 `data/arxiv_cache.json`에 저장되고, `--offline`을 붙이면 캐시만 쓴다.

### 7단계: 평가 (LLM, 유료)

```powershell
python -m research_plan evaluate --run-dir data/cot45_public_run_20261029_154552 --ideas 6
```

`eval/eval_<시각>/summary.md`에 조건별 비교표가, `human/`에 눈가림 사람 평가지가 생긴다. `--ideas`를 빼면 NOVEL 후보 전부를 평가한다.

### 테스트

```powershell
python -m unittest discover -s tests -v
python -m research_plan.validate examples/golden/idea06_unsupported_token
```

### Docker

```powershell
docker build -t reserch-plen .
docker run --rm reserch-plen
```

이미지를 만들 때 인터넷에서 받는 것은 기본 이미지 `python:3.11-slim`뿐이다. 실행하면 테스트, 정답 예시 검증, 후보 목록 출력을 차례로 한다.
후보를 골라 결과 파일을 PC에 받으려면 다음과 같이 실행한다.

```powershell
docker run --rm -v ${PWD}/out:/app/out reserch-plen python -m research_plan select --run-dir data/cot45_public_run_20261029_154552 --idea 6
docker run --rm --env-file .env -v ${PWD}/out:/app/out reserch-plen python -m research_plan extract --evidence out/cot45_public_run_20261029_154552/idea06/evidence.json
```

`.env`는 `.dockerignore`로 이미지에서 빠진다. 키는 `--env-file`로 실행할 때만 넘긴다.

## 전체 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 명세, 스키마, 템플릿, 정답 예시, 검증기 | ✅ |
| 1 | 입력 어댑터: FutureWork + CoT3 + CoT4 + CoT5를 1부터 시작하는 번호로 짝짓고, 사용자가 후보 1개 선택 → `evidence.json` | ✅ |
| 2 | 1차 추출: LLM이 필드 묶음별로 plan.json 생성 → 검증기 통과할 때까지 재시도 | ✅ |
| 3 | 심사와 보완: 규칙 검사 + LLM 판정기 (field_definitions.md의 "좋은 값" 기준) → 기준 미달 묶음 1회 재작성 | ✅ |
| 4 | 문서 작성: plan.reviewed.json만 근거로 research_plan.md, paper_skeleton.md 작성 | ✅ |
| 5 | 인용·날조 검사: arXiv 실재·제목, plan에 없는 숫자·이름, 결과 단정 표현 | ✅ |
| 6 | 한 줄 실행(`run`), 중간 재시작, 자동 백업, 실행 기록 | ✅ |
| 7 | 평가: free·template·pipeline 비교 (정답 예시는 판정기 보정 기준) | 🔧 코드 완료, 시범 1회만 실행 |
| 8 | 기존 CoT4→CoT5 실행 흐름 뒤에 연결 | |

## 열린 결정 사항

1. **OpenRouter API 키**: `.env`에 넣어야 2단계를 실제로 돌릴 수 있다. 3단계 판정기에 작성 모델과 다른 모델을 쓸지도 정해야 한다.
2. **NOT_NOVEL 후보 처리**: 지금은 기본으로 막고 `--allow-not-novel`로만 허용한다. 실제 결과에서 NOT_NOVEL 2건(1번, 4번)은 CoT5 결과에 동등 논문이 남아 있지 않아, 어떤 논문과 겹치는지 확인할 수 없다.
3. **웹 검색 실패(8건 중 7건 확인불가)**: 재실행할지, 부록에 명시하고 진행할지. 지금은 `evidence.json`의 warnings와 `novelty.search_status`에 그대로 기록한다.
4. **출력 언어**: 계획서는 한국어, 논문 틀은 영어로 가정했다.
5. **정답 예시 갱신**: 정답 예시는 원문 없이 만들어 일부 필드가 `inferred: true`다. 이제 FutureWork·CoT3 원문이 있으니, 2단계 시작 전에 근거 경로를 실제 값으로 고친다.
