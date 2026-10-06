REQUIREMENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "compute_requirements",
        "data_requirements",
        "implementation_steps",
        "external_dependencies",
        "vague_or_unspecified_steps",
    ],
    "properties": {
        "compute_requirements": {"type": "string"},
        "data_requirements": {"type": "string"},
        "implementation_steps": {"type": "array", "items": {"type": "string"}},
        "external_dependencies": {"type": "array", "items": {"type": "string"}},
        "vague_or_unspecified_steps": {"type": "array", "items": {"type": "string"}},
    },
}

_CONCERN = {
    "type": "object",
    "additionalProperties": False,
    "required": ["present", "explanation"],
    "properties": {
        "present": {"type": "boolean"},
        "explanation": {"type": "string"},
    },
}

FEASIBILITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "classification",
        "resource_concern",
        "data_concern",
        "implementation_concern",
        "methodological_concern",
        "missing_constraints",
        "rationale",
        "confidence",
    ],
    "properties": {
        "classification": {"type": "string", "enum": ["FEASIBLE", "QUESTIONABLE", "INFEASIBLE"]},
        "resource_concern": _CONCERN,
        "data_concern": _CONCERN,
        "implementation_concern": _CONCERN,
        "methodological_concern": _CONCERN,
        "missing_constraints": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}
