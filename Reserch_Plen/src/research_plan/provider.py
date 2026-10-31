"""LLM 호출. OpenRouter chat completions + JSON Schema 강제 출력 (표준 라이브러리만 사용).

CoT4/CoT5의 LLMProvider와 같은 형태(evaluate)를 따른다.
API 키는 환경변수 OPENROUTER_API_KEY 또는 작업 폴더의 .env에서 읽는다. 키를 코드나 이미지에 넣지 않는다.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MODEL = "openai/gpt-6-luna"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMProvider(Protocol):
    model: str

    def evaluate(self, *, instructions: str, document: str, schema: dict[str, Any], schema_name: str) -> dict[str, Any]: ...


class ProviderError(RuntimeError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """KEY=VALUE 형식의 .env를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ProviderError("모델 출력이 JSON 객체가 아님")
    return data


class OpenRouterProvider:
    def __init__(self, model: str | None = None, api_key: str | None = None, *, timeout: float = 600, retries: int = 3):
        load_dotenv()
        self.model = model or os.getenv("RESEARCH_PLAN_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY가 없음 (.env 또는 환경변수에 설정)")
        self.timeout = timeout
        self.retries = retries
        self.calls: list[dict[str, Any]] = []  # 호출별 사용량과 소요 시간

    def evaluate(self, *, instructions: str, document: str, schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": document},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        started = time.monotonic()
        response = self._post(body)
        choices = response.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        if not content:
            raise ProviderError(f"모델이 내용을 반환하지 않음: {json.dumps(response)[:300]}")
        self.calls.append({
            "schema_name": schema_name,
            "model": response.get("model", self.model),
            "usage": response.get("usage", {}),
            "seconds": round(time.monotonic() - started, 2),
        })
        return parse_json_text(content)

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Reserch_Plen",
        }
        for attempt in range(1, self.retries + 1):
            request = urllib.request.Request(OPENROUTER_URL, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                if exc.code not in RETRY_STATUS or attempt == self.retries:
                    raise ProviderError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self.retries:
                    raise ProviderError(f"OpenRouter 연결 실패: {exc}") from exc
            time.sleep(2 ** attempt)
        raise ProviderError("unreachable")
