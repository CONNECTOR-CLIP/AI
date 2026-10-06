# Future-Work-Researcher

논문에서 연구 목표와 한계를 분석하고, 후속 연구 아이디어의 실현가능성과 신규성을 검토하는 연구용 실험 코드입니다.

**CoT1~CoT5의 실행 코드를 공개하지만, CoT5 검색에 사용하는 실제 문헌 DB는 제공하지 않습니다.** DB 원본·부분 추출본·임베딩·검색 인덱스도 공개 범위에 포함하지 않습니다. 따라서 저장소를 내려받는 것만으로 CoT5의 DB 연동 실험까지 실행할 수는 없습니다.

## 1. 실험 구성

| 단계 | 목적 | 실행 파일 |
|---|---|---|
| CoT1 | 논문별 목표 분해 및 검증 | `CoT1.py` |
| CoT2 | 원문에서 한계 후보 추출 및 정적 검증 | `CoT2.py` |
| CoT3 | 논문 간 목표·한계 교차 비교 및 후보 판정 | `CoT3.py` |
| Future Work | 논문을 스캔하고 후속 연구 제안 생성 | `run_future_work.py` |
| CoT4 | 제안의 기술적 실현가능성 검사 | `CoT4.py` |
| CoT5 | 로컬 문헌 검색에 근거한 신규성 검사 | `CoT5.py` |

개념적인 실험 순서는 다음과 같습니다.

```text
CoT1 → CoT2 → CoT3 → Future Work → CoT4 → CoT5
```

**현재 구현의 연결 범위**

- CoT1~CoT3는 각각 실행할 수 있는 실험 진입점입니다. CoT3는 내부에서 목표·한계 분석에 필요한 처리를 수행하며, CoT1/CoT2 출력 파일을 CLI 인자로 받는 방식은 아닙니다.
- `run_future_work.py`는 논문 제목을 받아 자체 스캔·제안 생성을 수행합니다. CoT3 출력 파일을 자동으로 입력받는 연결은 구현되어 있지 않습니다.
- Future Work 형식의 JSON은 CoT4와 CoT5의 입력으로 사용할 수 있습니다.
- `run_cot4_then_cot5.py`는 **모든 제안이 CoT4에서 `FEASIBLE` 판정을 받은 경우에만** CoT5를 실행합니다. 하나라도 미통과하거나 오류가 발생하면 해당 배치의 CoT5 전체를 건너뜁니다.

## 2. 디렉토리 구조

```text
Future-Work-Researcher/
├── CoT1.py / CoT2.py / CoT3.py       # 상위 단계별 실험
├── run_future_work.py               # 후속 연구 제안 생성
├── CoT4.py / CoT5.py                 # 하위 검사 단계
├── run_cot4_then_cot5.py             # 실현가능성 게이트를 포함한 연결 실행
├── global_state.py
├── research_agent/                  # 공통 에이전트·도구·워크플로
├── CoT4/                            # 패키지 소스·예시·테스트
├── CoT5/                            # 패키지 소스·예시·테스트
├── external/idea_novelty_checker/    # CoT5 외부 구현 및 필수 정적 리소스
├── requirements-cot4.txt
├── requirements-cot5.txt
├── config.cot5.yml.example
├── test_cot4_then_cot5.py
└── GITHUB_UPLOAD_GUIDE.md            # 공개/비공개 파일 기준
```

## 3. 환경 준비

### 3.1 Python 및 의존성

CoT4/CoT5 패키지는 **Python 3.11 이상**을 요구합니다. 아래 명령은 저장소 루트에서 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-cot4.txt -r requirements-cot5.txt
```

Linux/macOS에서는 활성화 명령을 `source .venv/bin/activate`로 바꿉니다.

> 위 두 의존성 파일은 CoT4/CoT5용입니다. 현재 루트에는 CoT1~CoT3 및 Future Work 전체를 포괄하는 `requirements.txt`가 없습니다. 따라서 위 설치만으로 상위 단계의 모든 의존성이 준비된다고 보장하지 않습니다. 공개 배포 전 통합 의존성 목록 작성과 깨끗한 환경에서의 설치 검증이 필요합니다.

CoT1~CoT3 및 Future Work는 `research_agent`의 추가 패키지에 의존합니다. `ModuleNotFoundError`가 발생하면 해당 단계의 의존성이 아직 준비되지 않은 것입니다. 본 문서는 전체 파이프라인의 설치·재현 검증 완료를 의미하지 않습니다.

### 3.2 모델과 인증정보

실제 모델 호출에는 해당 제공자의 API 키와 사용 권한이 필요하며 비용이 발생할 수 있습니다. 논문 다운로드·문헌 검색·모델 다운로드에는 네트워크가 필요합니다. CoT2의 한계 추출 자체는 정규식 기반이며 LLM을 호출하지 않습니다.

PowerShell 설정 예시입니다. 자리표시자는 본인 환경에 맞게 바꿉니다.

```powershell
$env:OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
$env:COMPLETION_MODEL = "YOUR_COMPLETION_MODEL"
$env:CHEEP_MODEL = "YOUR_SCAN_AND_KEYWORD_MODEL"
$env:JUDGE_MODEL = "YOUR_JUDGE_MODEL"
$env:COT5_MODEL = "YOUR_OPENAI_FEASIBILITY_MODEL"
```

- `COMPLETION_MODEL`: 상위 단계 기본 모델. 지원되는 스크립트에서는 `--model`로 지정할 수 있습니다.
- `CHEEP_MODEL`: 현재 코드의 환경변수 이름입니다. Future Work 스캔·키워드 추출 등에 사용합니다.
- `JUDGE_MODEL`: CoT3 판정 모델. `--judge_model`로 지정할 수도 있습니다.
- `COT5_MODEL`: **이름과 달리 현재 `CoT4.py`의 실현가능성 모델 설정**입니다. 연결 실행에서는 `--cot4-model`로 명시할 수 있습니다.
- OpenRouter 경유 모델을 사용한다면 해당 제공자의 `OPENROUTER_API_KEY`도 설정합니다.
- `GITHUB_AI_TOKEN`: Future Work의 GitHub 검색용 토큰입니다. 토큰이 없으면 현재 흐름에서는 해당 검색을 건너뜁니다.

키는 로컬 환경변수나 비공개 설정으로만 관리합니다. 모든 스크립트가 `.env`를 동일하게 읽는다고 가정하지 말고, 특히 CoT4와 연결 실행에 필요한 키는 실행 전에 환경변수로 설정합니다. 코드에 지정된 기본 모델이 본인 계정에서 사용 가능하다는 보장은 없습니다.

### 3.3 CoT5 외부 코드와 설정

루트의 `external/idea_novelty_checker/noveltychecker/`와 코드가 읽는 프롬프트·`incontext_examples` 리소스가 필요합니다. Python 파일만 복사하고 필수 JSON 리소스를 제외하면 실행할 수 없습니다.

외부 구현이 submodule로 배포된 경우에만 다음 명령을 실행합니다.

```powershell
git submodule update --init --recursive
```

직접 포함 방식이면 이 명령은 필요하지 않습니다. **로컬 DB 검색용 수정사항까지 포함된 외부 구현**이 필요하며, 임의의 upstream 최신 버전으로 교체하면 동일 동작을 보장할 수 없습니다.

```powershell
Copy-Item config.cot5.yml.example config.yml
```

생성한 `config.yml`에서 다음 값을 본인 환경에 맞게 수정합니다.

- `OPENAI_API_KEY` 및 사용 모델에 필요한 제공자 키
- `ARXIV_DB_PATH`: 사용자가 직접 준비한 호환 SQLite DB 경로
- `NOVELTY_CHECK_MODEL`, `RANKGPT_MODEL`, `DEFAULT_MODEL` 등 모델 설정
- `SPECTER2_DEVICE`, `SPECTER2_BATCH_SIZE` 등 임베딩 설정

현재 설정 로더는 YAML 값을 환경변수에 덮어씁니다. 예시 키가 실제 환경변수 값을 덮어쓰지 않도록 자리표시자를 수정하거나 불필요한 키 항목을 제거하세요. `config.yml`과 실제 API 키는 커밋하지 않습니다.

## 4. 단계별 실행

아래 제목·모델 자리표시자는 실제 사용할 값으로 바꿉니다. arXiv에서 찾을 수 있고 원문 소스를 내려받을 수 있는 논문을 사용하세요.

### CoT1: 목표 분해

```powershell
python CoT1.py --paper "논문 제목" --model "YOUR_COMPLETION_MODEL" --cache_path cache_cot1
```

검증 결과와 목표 분해 JSON이 콘솔에 출력됩니다.

### CoT2: 한계 추출

```powershell
python CoT2.py --paper "논문 제목" --cache_path cache_cot2
```

원문에서 한계 후보를 추출하고 정적 검증한 결과를 출력합니다.

### CoT3: 교차 비교

```powershell
python CoT3.py --papers "논문 제목 A" "논문 제목 B" --model "YOUR_COMPLETION_MODEL" --judge_model "YOUR_JUDGE_MODEL" --cache_path cache_cot3
```

`--paper_ids`를 사용하면 `--papers`와 동일한 순서로 arXiv ID를 지정합니다. 진단 로그와 최종 후보 JSON이 함께 출력되므로 콘솔 출력 전체를 순수 JSON으로 취급하지 않습니다.

### Future Work: 후속 연구 제안 생성

```powershell
python run_future_work.py --papers "논문 제목 A" "논문 제목 B" --model "YOUR_COMPLETION_MODEL" --cache_path cache_future_work
```

CLI 도움말은 10~15편 입력을 안내합니다. 위 명령은 인자 형식 예시이며, 실제 실험에서는 연구 목적에 맞게 논문 수를 정합니다. `--paper_ids`를 지정한다면 제목과 ID 개수가 같아야 합니다.

결과는 콘솔에 출력됩니다. 현재 CLI에는 결과 JSON 저장용 `--output` 옵션이 없습니다. 출력에서 최종 제안 JSON 객체만 분리해 UTF-8 파일로 저장하고, 다음 입력 형식에 맞는지 확인합니다. 로그·마크다운 코드 펜스가 포함된 전체 출력을 그대로 CoT4/CoT5에 넘기지 않습니다.

### CoT4: 실현가능성 검사

```powershell
python CoT4.py CoT4/examples/idea.json
```

제공된 예시는 입력 형식 확인용입니다. 실제 실험에서는 문제·방법·검증 계획과 계산 자원·데이터·일정·팀 역량 등의 제약을 작성합니다. CoT4는 로컬 문헌 DB 없이 실행할 수 있지만 모델 API 환경은 필요합니다.

### CoT5: 신규성 검사 — 별도 DB 필요

```powershell
python CoT5.py CoT5/examples/idea.json --config config.yml
```

**이 명령은 실제 호환 DB, 외부 구현, 모델/API 환경을 준비한 경우에만 실행할 수 있습니다.** DB가 없거나 비어 있으면 검색 어댑터에서 오류가 발생합니다. Semantic Scholar 온라인 검색으로 자동 대체되지 않습니다.

SPECTER2는 최초 실행 시 모델·어댑터 다운로드와 로컬 추론 환경이 필요할 수 있습니다. 장치와 배치 크기는 사용 환경에 맞춰 설정합니다.

## 5. Future Work JSON으로 CoT4 → CoT5 실행

`future_work.json`을 다음 구조로 준비합니다. 아래 내용은 실제 연구 결과가 아닌 형식 예시입니다.

```json
{
  "future_work_proposals": [
    {
      "id": 1,
      "background_and_gap": "기존 방법이 제한된 데이터 조건에서 충분히 검증되지 않았다.",
      "proposed_direction": "데이터 규모별 비교 실험으로 방법의 적용 범위를 검증한다.",
      "expected_contribution": "적용 가능한 조건과 한계를 정리한다.",
      "reference_papers": []
    }
  ]
}
```

각 제안에는 비어 있지 않은 `background_and_gap`, `proposed_direction`이 필요합니다. 상위 모델 출력이 다른 필드명을 사용하면 이 형식으로 정리해야 합니다. CoT3의 최종 후보 목록을 그대로 대체 입력으로 사용하지 않습니다.

DB 없이 CoT4만 실행하려면:

```powershell
python CoT4.py future_work.json
```

DB까지 준비한 뒤 연결 실행하려면:

```powershell
python run_cot4_then_cot5.py future_work.json --cot5-config config.yml --cot4-model "YOUR_OPENAI_FEASIBILITY_MODEL" --output report.json
```

- 모든 제안이 `FEASIBLE`이면 CoT5를 시작합니다.
- 하나라도 미통과하거나 CoT4 검사 중 오류가 발생하면 `gate.passed`는 `false`, CoT5 상태는 `skipped`가 됩니다.
- `--cot5-model`은 CoT5의 동등성 검사 제공자 모델을 지정합니다. 외부 신규성 검사·랭킹 모델 설정 전체를 대체하는 옵션은 아닙니다.
- `--output`의 상위 디렉토리는 미리 존재해야 합니다.
- CoT5 단독 실행은 CoT4 게이트를 거치지 않습니다. 순서를 강제하려면 연결 실행기를 사용합니다.

## 6. CoT5 DB 요구사항 및 비공개 정책

검색 어댑터는 `external/idea_novelty_checker/noveltychecker/utils/s2_api.py`에 있습니다. 파일명과 일부 함수명은 기존 구현의 이름을 유지하지만, 실제 검색 대상은 `ARXIV_DB_PATH`의 로컬 SQLite DB입니다.

현재 검색 코드에서 참조하는 테이블·컬럼은 다음과 같습니다.

| 테이블 | 참조 컬럼 |
|---|---|
| `papers` | `arxiv_id`, `title`, `abstract`, `created_date`, `categories`, `is_deleted` |
| `authors` | `arxiv_id`, `keyname`, `forenames`, `position` |
| `cso_keywords` | `arxiv_id`, `keyword`, `score` |

테이블 간 `arxiv_id`가 대응해야 하며, `papers.is_deleted=0`인 레코드를 검색합니다. 날짜·키워드 등 데이터 형식도 어댑터의 기대값과 맞아야 합니다. 빈 테이블만 만드는 것은 문헌 기반 실험을 재현하는 것과 다릅니다.

공개하지 않는 항목:

- 실제 문헌 DB 전체·일부 추출본·덤프·백업
- 실제 논문 메타데이터 코퍼스, 임베딩 벡터, 검색·벡터 인덱스
- 작성자의 기존 실험 입력·결과·캐시·로그
- API 키, 토큰, 개인 설정

사용자는 적법하게 확보한 자신의 데이터를 호환 구조로 준비해야 합니다. 본 저장소는 비공개 DB 다운로드나 원래 실험 데이터의 복원을 제공하지 않습니다. DB·모델·입력·검색 기준이 달라지면 결과도 달라질 수 있습니다.

## 7. 테스트와 검증 범위

CoT4 → CoT5 게이트의 기본 회귀 테스트:

```powershell
python -m unittest test_cot4_then_cot5 -v
```

이 테스트는 대체 검사 객체를 사용하며 실제 모델 API나 DB 검색을 실행하지 않습니다. CoT4 오류, 일부 제안 미통과, 전체 제안 통과 시 동작을 확인합니다.

추가 테스트는 `CoT4/tests/`, `CoT5/tests/`에 있습니다. 패키지 설치·테스트 도구와 각 테스트의 DB/API/모델 의존성을 먼저 확인하세요. 단위 테스트 통과가 실제 API·문헌 DB 연동 실험의 성공을 의미하지는 않습니다.

## 8. 결과 관리 및 문제 해결

| 증상 | 확인 사항 |
|---|---|
| `ModuleNotFoundError` | 해당 단계 의존성, 가상환경, 외부 구현 경로 확인. 상위 단계 통합 의존성 목록은 아직 없음 |
| 논문 다운로드 실패 | 제목·arXiv ID, 네트워크, 원문 소스 제공 여부 확인 |
| 모델/API 오류 | 제공자 키, 모델 접근 권한, 설정 파일의 환경변수 덮어쓰기 확인 |
| DB 누락 또는 빈 DB 오류 | 직접 준비한 DB와 `ARXIV_DB_PATH` 확인. 저장소에는 DB가 없음 |
| 테이블·컬럼 오류 | 사용 DB와 검색 어댑터의 스키마 비교 |
| JSON 파싱·필드 오류 | 로그·코드 펜스 제거, UTF-8 JSON 및 필수 필드 확인 |
| CoT5가 `skipped` | 연결 실행 결과의 `gate.failed_ideas`와 CoT4 판정 확인 |

실행하면 `cache_*/`, `workplace_future_work/` 등 로컬 작업 파일이 생성될 수 있습니다. 결과·로그에는 논문 내용과 개인 경로 등이 포함될 수 있으므로 공개 전에 확인합니다.

상세 업로드 기준은 [GITHUB_UPLOAD_GUIDE.md](GITHUB_UPLOAD_GUIDE.md)를 따릅니다. `.gitignore`만으로 이미 커밋된 데이터가 제거되지는 않으므로 공개할 Git 이력과 submodule 참조도 점검해야 합니다. 외부 구현의 라이선스·재배포 조건을 별도로 확인하세요.

이 도구의 판정은 연구 검토를 돕는 모델 기반 결과이며, 기술적 실현가능성이나 신규성을 확정적으로 보장하지 않습니다.
