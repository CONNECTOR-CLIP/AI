# Research Plan API

연구계획서와 논문의 틀을 만드는 HTTP API다. 전체 실행이 몇 분 걸리므로 작업을 만든 뒤 상태를 확인하는 방식이다.

```
후보 목록 조회 → 작업 시작 → 2~3초마다 상태 확인 → 결과 조회
```

## 서버 실행

```powershell
pip install fastapi uvicorn
$env:PYTHONPATH = "src"
python -m uvicorn research_plan.api:app --port 8002
```

자동 생성 문서는 http://localhost:8002/docs 에 있다.

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `RESEARCH_PLAN_API_MODE` | `mock` | `mock`: LLM 호출 없음, 비용 없음, 결과는 `examples/demo`. `live`: 실제 실행, **비용 발생**, 결과는 `out` |
| `RESEARCH_PLAN_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | 브라우저에서 호출을 허용할 주소. 쉼표로 구분 |

프론트 개발은 `mock`으로 하면 된다. 단계 진행을 약 1초씩 흉내 내고, 결과는 6번 아이디어만 있다. 다른 후보로 작업을 만들면 `failed`로 끝나므로 실패 화면 확인에 쓸 수 있다.

## 엔드포인트

경로 앞에 모두 `/api/research-plan`이 붙는다(`/health` 제외).

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/health` | 서버 상태와 실행 모드 |
| GET | `/runs` | 실행 목록 |
| GET | `/runs/{run_id}/candidates` | 아이디어 후보 목록 |
| POST | `/runs/{run_id}/candidates/{idea}/jobs` | 생성 작업 시작. live에서는 비용 발생 |
| GET | `/jobs/{job_id}` | 작업 상태 |
| GET | `/runs/{run_id}/candidates/{idea}/result` | 결과 문서 |

### 후보 목록

```json
{
  "run_id": "cot45_public_run_20261029_154552",
  "candidates": [
    {
      "idea": 6,
      "title": "…",
      "classification": "NOVEL",
      "cot3_candidate_id": "C6",
      "warnings": ["…"],
      "has_result": true
    }
  ]
}
```

`classification`이 `NOVEL`이 아닌 후보는 기본적으로 작업을 시작할 수 없다.

### 작업 시작

본문은 생략할 수 있다. 두 값의 기본은 `false`다.

```json
{ "force": false, "allow_not_novel": false }
```

- `force`: 결과가 이미 있어도 다시 생성한다. live에서는 비용이 다시 들고, 이전 결과는 서버의 `history/`로 백업된다.
- `allow_not_novel`: NOT_NOVEL 후보도 진행한다.

성공하면 202와 아래 작업 정보를 돌려준다.

### 작업 상태

```json
{
  "job_id": "3f2a…",
  "run_id": "cot45_public_run_20261029_154552",
  "idea": 6,
  "status": "running",
  "stages": ["select", "extract", "review", "write", "verify"],
  "current_stage": "review",
  "completed_stages": ["select", "extract"],
  "created_at": "2026-10-31T10:00:00+09:00",
  "started_at": "2026-10-31T10:00:00+09:00",
  "finished_at": null,
  "result_ready": false,
  "final_status": null,
  "total_cost_usd": null,
  "error": null
}
```

- `status`: `queued`(대기) → `running`(실행) → `done`(문서 생성됨) 또는 `failed`(실패). 작업은 서버에서 한 번에 하나씩 돈다.
- `final_status`: `done`일 때의 품질 상태. `pass`, `needs_review`(사람 확인 필요), `fail`(자동 검사 실패).
- `done`은 문서가 만들어졌다는 뜻이지 품질 통과가 아니다. 화면에는 `final_status`를 함께 보여 줘야 한다.
- 작업 기록은 서버 메모리에만 있다. 서버를 다시 켜면 `JOB_NOT_FOUND`가 나오며, 만들어진 결과는 결과 조회로 받을 수 있다.

### 결과

```json
{
  "run_id": "cot45_public_run_20261029_154552",
  "idea": 6,
  "source": "demo",
  "final_status": "needs_review",
  "finished_at": "2026-10-30T20:37:45+09:00",
  "total_cost_usd": 0.043201,
  "stages": [{ "stage": "select", "status": "pass", "seconds": 0.1, "cost_usd": 0 }],
  "verify": { "status": "pass", "errors": [], "warnings": [], "citation_count": 3 },
  "research_plan_md": "# 연구계획서 …",
  "paper_skeleton_md": "# 논문의 틀 …"
}
```

두 문서는 마크다운 문자열이므로 마크다운 렌더러로 표시한다. 표가 있어 표를 지원하는 설정이 필요하다(예: GFM). LLM이 쓴 문자열이므로 HTML을 그대로 삽입하지 말고 안전하게 처리한다.

`[TBD]`와 `[RESULT: …]`는 오류가 아니다. 아직 정해지지 않은 값과 실험 뒤 채울 자리다.

## 오류

오류는 HTTP 상태 코드와 아래 형식으로 돌려준다. 화면 분기는 `code`로 한다.

```json
{ "detail": { "code": "RESULT_EXISTS", "message": "결과가 이미 있음. 다시 생성하려면 force를 켤 것" } }
```

| 상태 | code | 뜻 | 화면 처리 예 |
|---|---|---|---|
| 404 | `RUN_NOT_FOUND`, `IDEA_NOT_FOUND`, `JOB_NOT_FOUND` | 대상 없음 | 안내 |
| 404 | `RESULT_NOT_FOUND` | 결과가 아직 없음 | 생성 버튼 표시 |
| 409 | `RESULT_EXISTS` | 결과가 이미 있음 | 결과 표시, "다시 생성"은 확인 후 `force` |
| 409 | `JOB_ALREADY_RUNNING`, `JOB_RUNNING` | 진행 중. `detail.job_id` 포함 | 그 작업의 상태 확인으로 이동 |
| 422 | `NOT_NOVEL` | 신규성 미통과 후보 | 경고 후 `allow_not_novel` |
| 500 | `RUN_INVALID` | 입력 파일끼리 맞지 않음 | 관리자 문의 |
| 503 | `NO_API_KEY` | 서버에 키 없음 | 관리자 문의 |

작업이 실패하면 `GET /jobs/{job_id}`의 `status`가 `failed`이고 `error`에 실패 단계가 들어 있다. 자세한 원인은 서버 로그에 있다.

## 호출 예

```js
const BASE = "http://localhost:8002/api/research-plan";
const RUN = "cot45_public_run_20261029_154552";

const start = await fetch(`${BASE}/runs/${RUN}/candidates/6/jobs`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ force: true }),
});
const { job_id } = await start.json();

let job;
do {
  await new Promise((resolve) => setTimeout(resolve, 2000));
  job = await (await fetch(`${BASE}/jobs/${job_id}`)).json();
} while (job.status === "queued" || job.status === "running");

if (job.status === "done") {
  const result = await (await fetch(`${BASE}/runs/${RUN}/candidates/6/result`)).json();
}
```

## 현재 한계

- **로그인과 권한 확인이 없다.** `live` 서버를 외부에 공개하면 누구나 비용을 쓸 수 있다. 공개 전에 인증과 사용량 제한을 먼저 넣어야 한다.
- `data/`에 저장된 실행만 읽는다. 새 CoT 실행 결과를 바로 받는 기능은 8단계 작업이다.
- 사람이 고친 plan을 웹에서 수정하거나 `--from write`로 다시 쓰는 기능은 없다. `force`는 처음부터 다시 만든다.
- 작업 기록이 메모리에 있어 서버 프로세스를 여러 개 띄우는 구성을 지원하지 않는다.
- `live` 전체 흐름은 API를 통해 실제 LLM으로 실행해 본 적이 없다. 가짜 실행기로만 테스트했다.
