"""plan.json 스키마 정의 (docs/field_definitions.md와 동일한 순서)."""

SCHEMA_VERSION = "0.2"  # 0.2: expected_novelty에 existing_mechanism, difference_axis, tested_by 추가

# PDF의 15개 필수 요소 + Heilmeier/NIH 기준 3개(risks, milestones, search scope).
FIELD_KEYS = [
    "research_topic",
    "research_background",
    "research_problem",
    "limitations_of_existing_approaches",
    "research_objective",
    "proposed_method",
    "method_components",
    "component_relations",
    "data_and_subjects",
    "baselines",
    "validation_targets",
    "experimental_design",
    "target_claims",
    "expected_novelty",
    "expected_contribution",
    "risks_and_fallbacks",
    "success_criteria_milestones",
    "novelty_search_scope",
]

TEXT_FIELDS = {
    "research_topic",
    "research_background",
    "research_problem",
    "research_objective",
    "proposed_method",
}

# 목록형 필드 중 항목에 id가 있는 것과 그 접두어.
ID_PREFIXES = {
    "limitations_of_existing_approaches": "L",
    "method_components": "M",
    "baselines": "B",
    "validation_targets": "V",
    "experimental_design": "E",
    "target_claims": "C",
    "risks_and_fallbacks": "R",
    "success_criteria_milestones": "S",
}

SOURCE_PREFIXES = ("future_work.", "cot1.", "cot2.", "cot3.", "cot4.", "cot5.", "manifest.", "seed:")

_ID_LIST = {"type": "array", "items": {"type": "string"}}

# 신규성의 차이 축. 가장 가까운 선행연구와 무엇이 다른지 하나를 고른다.
DIFFERENCE_AXES = ["적용 단위", "적용 시점", "판단 대상", "판단 이후 동작", "학습 방식", "기타"]

_ITEM_SCHEMAS = {
    "limitations_of_existing_approaches": {
        "required": ["id", "text", "cites"],
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "cites": _ID_LIST},
    },
    "method_components": {
        "required": ["id", "name", "description", "addresses"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "addresses": _ID_LIST,
        },
    },
    "component_relations": {
        "required": ["from", "to", "relation"],
        "properties": {"from": {"type": "string"}, "to": {"type": "string"}, "relation": {"type": "string"}},
    },
    "data_and_subjects": {
        "required": ["name", "use", "status"],
        "properties": {
            "name": {"type": "string"},
            "use": {"type": "string"},
            "status": {"type": "string"},
            "source_hint": {"type": "string"},
        },
    },
    "baselines": {
        "required": ["id", "name", "why"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "arxiv_id": {"type": "string"},
            "why": {"type": "string"},
        },
    },
    "validation_targets": {
        "required": ["id", "question", "components"],
        "properties": {"id": {"type": "string"}, "question": {"type": "string"}, "components": _ID_LIST},
    },
    "experimental_design": {
        "required": [
            "id", "validates", "setup", "metrics", "baselines",
            "success_criterion", "failure_interpretation",
        ],
        "properties": {
            "id": {"type": "string"},
            "validates": _ID_LIST,
            "setup": {"type": "string"},
            "metrics": _ID_LIST,
            "baselines": _ID_LIST,
            "success_criterion": {"type": "string"},
            "failure_interpretation": {"type": "string"},
        },
    },
    "target_claims": {
        "required": ["id", "claim", "falsifiable_condition", "validated_by"],
        "properties": {
            "id": {"type": "string"},
            "claim": {"type": "string"},
            "falsifiable_condition": {"type": "string"},
            "validated_by": _ID_LIST,
        },
    },
    # 차이를 "무엇과(vs), 그 기존 장치가 무엇이고(existing_mechanism), 어느 축에서 다르며(difference_axis),
    # 어느 실험이 그 차이가 필요한지 가리는지(tested_by)"로 쓰게 해 신규성 주장을 반증 가능하게 만든다.
    "expected_novelty": {
        "required": ["text", "vs", "existing_mechanism", "difference_axis", "tested_by"],
        "properties": {
            "text": {"type": "string"},
            "vs": _ID_LIST,
            "existing_mechanism": {"type": "string"},
            "difference_axis": {"type": "string", "enum": DIFFERENCE_AXES},
            "tested_by": _ID_LIST,
        },
    },
    "expected_contribution": {
        "required": ["type", "text"],
        "properties": {
            "type": {"type": "string", "enum": ["method", "resource", "analysis", "other"]},
            "text": {"type": "string"},
        },
    },
    "risks_and_fallbacks": {
        "required": ["id", "risk", "fallback"],
        "properties": {
            "id": {"type": "string"},
            "risk": {"type": "string"},
            "fallback": {"type": "string"},
            "source": {"type": "string"},
        },
    },
    "success_criteria_milestones": {
        "required": ["id", "milestone", "criterion"],
        "properties": {"id": {"type": "string"}, "milestone": {"type": "string"}, "criterion": {"type": "string"}},
    },
}

_SEARCH_SOURCE = {
    "type": "object",
    "required": ["status", "checked_count", "error"],
    "properties": {
        "status": {"type": "string"},
        "checked_count": {"type": ["integer", "null"]},
        "error": {"type": ["string", "null"]},
    },
}


def _value_schema(key: str) -> dict:
    if key in TEXT_FIELDS:
        return {"type": "string", "minLength": 1}
    if key == "novelty_search_scope":
        return {
            "type": "object",
            "required": ["paper", "web", "patent", "statement"],
            "properties": {
                "paper": _SEARCH_SOURCE,
                "web": _SEARCH_SOURCE,
                "patent": _SEARCH_SOURCE,
                "statement": {"type": "string", "minLength": 1},
            },
        }
    item = _ITEM_SCHEMAS[key]
    return {
        "type": "array",
        "minItems": 1,
        "items": {"type": "object", "required": item["required"], "properties": item["properties"]},
    }


def _wrapper(key: str) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "source", "inferred"],
        "properties": {
            "value": _value_schema(key),
            "source": {"type": "array", "items": {"type": "string"}},
            "inferred": {"type": "boolean"},
        },
    }


# Stage 2에서 LLM이 한 번에 채우는 필드 묶음. 뒤 묶음은 앞 묶음의 ID(L, M)를 참조한다.
# novelty_search_scope는 CoT5 검색 상태를 그대로 옮기므로 LLM이 쓰지 않는다.
FIELD_GROUPS = {
    "problem": [
        "research_topic",
        "research_background",
        "research_problem",
        "limitations_of_existing_approaches",
    ],
    "method": [
        "research_objective",
        "proposed_method",
        "method_components",
        "component_relations",
        "data_and_subjects",
    ],
    "validation": [
        "baselines",
        "validation_targets",
        "experimental_design",
        "target_claims",
        "expected_novelty",
        "expected_contribution",
        "risks_and_fallbacks",
        "success_criteria_milestones",
    ],
}

_STRICT_DROP = {"minLength", "minItems", "$schema", "title"}


def _strict(schema: dict) -> dict:
    """OpenAI/OpenRouter strict 모드 조건: 모든 속성 required, additionalProperties false, 일부 키워드 제거.
    원래 선택 속성(arxiv_id, source_hint, source)은 빈 문자열로 받고 Stage 2에서 지운다."""
    out = {k: v for k, v in schema.items() if k not in _STRICT_DROP}
    if "properties" in out:
        out["properties"] = {k: _strict(v) for k, v in out["properties"].items()}
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    if "items" in out:
        out["items"] = _strict(out["items"])
    return out


def strict_group_schema(group: str) -> dict:
    keys = FIELD_GROUPS[group]
    return _strict({"type": "object", "properties": {key: _wrapper(key) for key in keys}})


PLAN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Research plan (Stage 1 output)",
    "type": "object",
    "required": ["schema_version", "meta", "citation_whitelist", "fields"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "meta": {
            "type": "object",
            "required": ["run_id", "candidate_index", "cot5_classification", "generated_by"],
        },
        "citation_whitelist": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["arxiv_id", "title", "role"],
                "properties": {
                    "arxiv_id": {"type": "string"},
                    "title": {"type": "string"},
                    "role": {"type": "string", "enum": ["seed", "cot5_candidate"]},
                },
            },
        },
        "fields": {
            "type": "object",
            "additionalProperties": False,
            "required": list(FIELD_KEYS),
            "properties": {key: _wrapper(key) for key in FIELD_KEYS},
        },
    },
}
