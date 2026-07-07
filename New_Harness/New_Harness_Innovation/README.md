# NEW_HARNESS_INNOVATION

선택된 arXiv 논문을 바탕으로, 결과물 중심의 향후 작업 초안을 작성하기 위한 Python-first MVP 하네스입니다.

## MVP 범위

현재 이 저장소는 다음 기능을 다룹니다.

* arXiv 전용 선택 논문 입력
* 선택적 사용자 초안 또는 메모 텍스트 입력
* `runs/<run_id>/` 아래에 결과물 중심 실행 기록 저장
* 후보 선택 단계까지의 결정론적 오프라인 스모크 실행
* 초안 작성 전 명시적 후보 선택
* 선택된 후보를 기반으로 초안 생성
* 제안만 제공하거나 초안을 직접 수정하는 revision 모드
* checker가 설정되지 않았을 때 degraded external-check 상태를 보존하는 verification-depth 플래그

## 비목표

이 MVP에는 다음 기능이 포함되지 않습니다.

* PDF 다운로드 또는 PDF 파싱
* Web UI 또는 Gradio UI
* 실험 실행
* 사용자 계정, 장기 권한, 데이터베이스 기반 제품 기능
* `AI-Researcher-main`의 직접적인 재작성

## 입력

선택 논문은 arXiv 식별자 또는 arXiv URL에서 가져와야 합니다. 하네스는 사용자가 작성한 선택적 초안 또는 메모 텍스트도 입력으로 받을 수 있습니다.

입력 JSON 예시:

```json
{
  "selected_papers": [
    {
      "source": "2401.14196",
      "title": "직접 ID 예시"
    },
    {
      "source": "https://arxiv.org/abs/2401.14196"
    },
    {
      "source": "cs/9901001",
      "title": "이전 형식의 arXiv ID 예시"
    }
  ],
  "user_draft": {
    "draft_text": "하네스 입력에 사용할 수 있는 선택적 초안 텍스트입니다.",
    "memo_text": "선택적 메모 텍스트입니다."
  }
}
```

참고:

* `user_draft`는 선택 사항입니다.
* 입력은 arXiv 전용이며, arXiv가 아닌 논문 소스는 지원하지 않습니다.
* parser는 arXiv 식별자를 표준 arXiv 메타데이터 필드로 정규화합니다.
* arXiv URL이 입력으로 사용되더라도 하네스는 PDF를 다운로드하지 않습니다.

## CLI 워크플로

Python 3.11 이상 환경에서 저장소 루트에서 명령어를 실행합니다.

기본 CLI 경로는 **오프라인/fake smoke 경로**입니다.

* `run`은 결정론적 `FakeLLMProvider`를 사용합니다.
* 누락된 제목/초록은 오프라인 스모크 실행을 위해 채워집니다.
* `select`, `draft`, `revise`는 동일한 `run_id`에 대해 이미 작성된 artifact에서만 동작합니다.

실제 LLM 실험을 위해 선택적으로 OpenRouter 기반 경로를 사용할 수 있습니다. 키는 소스 코드 밖에 보관하세요.

```bash
cp .env.example .env.local
# .env.local 파일을 수정하고 다음 값을 설정:
# OPENROUTER_API_KEY=...
```

그다음 실행:

```bash
python -m new_harness.cli run \
  --input tests/fixtures/selected_papers_arxiv.json \
  --run-id demo-openrouter \
  --run-root "$RUN_ROOT" \
  --provider openrouter
```

선택적 override:

* `.env.local` 안의 `OPENROUTER_MODEL=...`
* `--openrouter-model ...`
* `--env-file /path/to/key-file`

실제 API 키를 채팅, README, 소스 파일, 커밋된 fixture에 붙여넣지 마세요.

### 1) 임시 run root를 선택하고 후보 선택 단계까지 실행하기

```bash
RUN_ROOT="$(mktemp -d)"
python -m new_harness.cli run \
  --input tests/fixtures/selected_papers_arxiv.json \
  --run-id demo \
  --run-root "$RUN_ROOT" \
  --verification-depth selected_only
```

이 명령은 실행 artifact를 작성하고 후보 선택 단계에서 멈춥니다. 위 fixture의 경우, 오프라인 스모크 경로는 `cand-r1-1`과 같은 pass 후보를 결정론적으로 생성합니다.

### 2) 필수 선택 옵션 확인하기

```bash
cat "$RUN_ROOT/runs/demo/selection_options.md"
```

`run`은 후보를 자동 선택하지 않습니다. pass 후보가 존재하면 다음 두 파일을 모두 작성합니다.

* `runs/<run_id>/selection_options.json`
* `runs/<run_id>/selection_options.md`

이 파일들은 선택 가능한 `pass_candidate_ids`, 요약, critic 점수, 소스 경로를 나열합니다.

### 3) pass 후보 하나 선택하기

```bash
python -m new_harness.cli select \
  --run-id demo \
  --candidate-id cand-r1-1 \
  --run-root "$RUN_ROOT"
```

`pass_candidate_ids`에 나열된 candidate ID만 유효합니다. 이 명령은 `$RUN_ROOT/runs/demo/selected_candidate.json`을 작성합니다.

### 4) 초안 생성하기

```bash
python -m new_harness.cli draft \
  --run-id demo \
  --run-root "$RUN_ROOT"
```

이 명령은 다음 파일을 작성합니다.

* `$RUN_ROOT/runs/demo/draft.md`
* `$RUN_ROOT/runs/demo/draft.claim_map.json`

### 5) 초안을 수정하지 않고 revision 수행하기

```bash
python -m new_harness.cli revise \
  --run-id demo \
  --mode qa_suggest \
  --request "What should I change in the conclusion?" \
  --run-root "$RUN_ROOT"
```

`qa_suggest`는 `$RUN_ROOT/runs/demo/revisions/` 아래에 revision record를 작성하며, `draft.md`는 변경하지 않습니다.

### 6) 초안을 직접 수정하는 revision 수행하기

```bash
python -m new_harness.cli revise \
  --run-id demo \
  --mode auto_edit \
  --request "Add a revision update for the conclusion." \
  --run-root "$RUN_ROOT"
```

`auto_edit`는 `draft.md`를 업데이트하고, 이에 대응하는 revision record를 `$RUN_ROOT/runs/demo/revisions/` 아래에 작성합니다.

## Verification depth

`run`은 세 가지 verification-depth 모드를 지원합니다.

| Mode              | 의도된 정책                                                         | CLI 동작                                                                                                                                                                                                              |
| ----------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `selected_only`   | 선택된 논문 evidence만 사용하고, 외부 novelty check는 건너뜀                   | 외부 checker가 호출되지 않습니다. Critic report는 `verification_status="selected_only"`를 기록합니다.                                                                                                                                 |
| `light_external`  | pass 또는 near-pass 후보만 검사하며, `external_check_top_k` 기본값 `2`로 제한 | `--external-checker`가 설정되면 대상 후보만 검사합니다. 검사되지 않은 후보는 `light_external_skipped`로 표시됩니다. checker가 없거나 실패하면 degraded `external_checks/round_<n>/<candidate_id>.json` artifact를 작성합니다.                             |
| `strong_external` | 더 엄격한 외부 검증 기대치를 가지고 모든 후보를 검사                                 | `--external-checker`가 설정되면 모든 후보를 검사합니다. checker가 없거나 실패하면 모든 후보가 degraded external-check artifact를 작성하고 critic report는 `verification_status="degraded"`를 기록합니다.                                               |

오프라인 실행 예시:

```bash
RUN_ROOT="$(mktemp -d)"
python -m new_harness.cli run \
  --input tests/fixtures/selected_papers_arxiv.json \
  --run-id demo-light \
  --run-root "$RUN_ROOT" \
  --verification-depth light_external
```

```bash
RUN_ROOT="$(mktemp -d)"
python -m new_harness.cli run \
  --input tests/fixtures/selected_papers_arxiv.json \
  --run-id demo-strong \
  --run-root "$RUN_ROOT" \
  --verification-depth strong_external
```

### External checker 선택

`light_external` 또는 `strong_external`에서 실제 외부 검색을 수행하려면 `--external-checker`를 지정합니다.

| Checker | 용도 | 주요 옵션 |
| --- | --- | --- |
| `none` | 기본값. checker 미설정 상태를 degraded로 기록 | 없음 |
| `arxiv_api` | arXiv Atom API metadata-only 검색 | `--external-max-results`, `--external-timeout`, `--external-min-interval` |
| `web` | 범용 JSON 웹 검색 API/프록시 검색 | `--external-search-url`, `--external-search-query-param`, `--external-search-api-key-env` |
| `search_engine` | `D:/SearchEngine` FastAPI `/search` 서비스 연동 | `--external-search-url` 기본값 `http://127.0.0.1:8000/search` |

예: 범용 웹 검색 JSON endpoint 사용

```bash
python -m new_harness.cli run \
  --input tests/fixtures/selected_papers_arxiv.json \
  --run-id demo-web-strong \
  --run-root "$RUN_ROOT" \
  --verification-depth strong_external \
  --external-checker web \
  --external-search-url "https://example-search-proxy.local/search" \
  --external-search-query-param q \
  --external-max-results 5
```

API key가 필요한 웹 검색 프록시는 key 값을 명령줄에 직접 쓰지 말고 env var로 넘깁니다.

```bash
export WEB_SEARCH_API_KEY="..."
python -m new_harness.cli run \
  --input tests/fixtures/selected_papers_arxiv.json \
  --run-id demo-web-key \
  --run-root "$RUN_ROOT" \
  --verification-depth strong_external \
  --external-checker web \
  --external-search-url "https://api.search.example/web/search" \
  --external-search-api-key-env WEB_SEARCH_API_KEY \
  --external-search-api-key-header X-Subscription-Token
```

예: 로컬 `D:/SearchEngine` 서비스가 실행 중일 때 검색

```bash
python -m new_harness.cli run \
  --input tests/fixtures/selected_papers_arxiv.json \
  --run-id demo-search-engine \
  --run-root "$RUN_ROOT" \
  --verification-depth strong_external \
  --external-checker search_engine \
  --external-search-url "http://127.0.0.1:8000/search"
```

Degraded external-check 동작은 조용히 넘어가지 않고 명시적으로 기록됩니다.

* 시도된 check에 대해 external-check JSON artifact가 계속 작성됩니다.
* critic report는 `novelty_risk`를 `unknown`으로 유지합니다.
* critic의 weaknesses/required fixes는 novelty가 통과된 것으로 간주하기 전에, 작동하는 metadata-only checker로 다시 실행하라고 호출자에게 알려줍니다.

## Artifact-first 실행 레이아웃

현재의 일반적인 실행 레이아웃:

```text
runs/<run_id>/
  candidate_loop.json
  draft.claim_map.json            # `draft` 이후 생성
  draft.md                        # `draft` 이후 생성
  events.jsonl
  evidence_cards/
    <paper_id>.json
    index.json
  candidates/
    candidates_round_<n>.json
  critic_reports/
    critic_reports_round_<n>.json
  external_checks/                # light_external / strong_external에서만 생성
    round_<n>/
      <candidate_id>.json
  revisions/                      # `revise` 이후 생성
    qa_suggest-<hash>.json
    auto_edit-<hash>.json
  selected_candidate.json         # `select` 이후 생성
  selected_papers.normalized.json
  selection_options.json          # selection이 필요할 때 생성
  selection_options.md            # selection이 필요할 때 생성
  user_draft.json                 # 입력에 user_draft가 포함된 경우에만 생성
```

Schema/version 규칙:

* artifact store를 통해 작성된 JSON artifact에는 `"schema_version": 1`이 포함됩니다.
* `draft.md`, `selection_options.md`와 같은 Markdown/text artifact에는 `schema_version`이 포함되지 않습니다.
* `events.jsonl`은 이벤트 로그이며, schema-versioned artifact payload가 아닙니다.

## 후보 선택 요구사항

초안 작성 전 후보 선택은 필수입니다.

* 최소 하나의 후보가 pass하면, `run`은 `selection_required` 상태로 종료됩니다.
* 실행은 `selection_options.json`과 `selection_options.md`를 작성합니다.
* `select`는 `pass_candidate_ids`에 나열된 `candidate_id`만 허용합니다.
* `selected_candidate.json`은 선택된 후보를 동일한 `run_id`에 바인딩하고, 소스 artifact 경로를 기록합니다.
* 설정된 round limit 내에서 pass 후보가 없으면, `run`은 `blocked` 상태로 종료되며 `candidate_loop.json`은 `best_revise_candidate_ids`를 기록합니다.

## Revision 모드

두 가지 revision 모드를 지원합니다.

* `qa_suggest`: `draft.md`를 수정하지 않고 답변 또는 수정 제안만 제공
* `auto_edit`: `draft.md`를 수정하고 `RevisionRecord`를 저장

두 모드 모두 다음을 수행합니다.

* `--run-id`가 필요합니다.
* 해당 run의 `selected_candidate.json`과 `draft.claim_map.json`에서 context를 해석합니다.
* schema-versioned JSON revision record를 `runs/<run_id>/revisions/` 아래에 작성합니다.
* 이전의 동일한 요청을 덮어쓰지 않습니다. 반복 요청은 `-02.json`과 같은 suffix를 받습니다.

`auto_edit`는 실행될 때마다 새로운 `## Revision Update` 섹션을 추가하므로, 이전에 초안 안에 추가된 revision update도 계속 보입니다. 전체 append-only revision history 또한 `revisions/` 아래의 JSON record로 보존됩니다.

## 테스트 및 검증

전체 테스트 suite:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

CLI smoke test만 실행:

```bash
python -m unittest tests.test_cli_smoke
```
