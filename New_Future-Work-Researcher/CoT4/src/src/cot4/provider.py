from __future__ import annotations

import json
import os
from typing import Any, Protocol


class LLMProvider(Protocol):
    model: str
    def evaluate(self, *, instructions: str, document: str, schema: dict[str, Any], schema_name: str) -> dict[str, Any]: ...


class OpenAIProvider:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        from openai import OpenAI
        self.model = model or os.getenv("COT5_MODEL", "gpt-5.6-terra")
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    def evaluate(self, *, instructions: str, document: str, schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=[{"role": "user", "content": [{"type": "input_text", "text": document}]}],
            text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
        )
        if not response.output_text:
            raise RuntimeError("모델이 결과를 반환하지 않았습니다.")
        return json.loads(response.output_text)
