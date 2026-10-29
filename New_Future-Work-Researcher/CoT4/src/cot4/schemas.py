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

RESOURCE_GUIDANCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "compute_resources",
        "data_resources",
        "tools_and_dependencies",
        "team_skills",
        "time_and_effort",
        "prerequisites",
        "unknowns_to_confirm",
        "required_performance_conditions",
        "proposed_performance_targets",
    ],
    "properties": {
        "compute_resources": {"type": "string"},
        "data_resources": {"type": "string"},
        "tools_and_dependencies": {"type": "array", "items": {"type": "string"}},
        "team_skills": {"type": "array", "items": {"type": "string"}},
        "time_and_effort": {"type": "string"},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "unknowns_to_confirm": {"type": "array", "items": {"type": "string"}},
        "required_performance_conditions": {"type": "array", "items": {"type": "string"}},
        "proposed_performance_targets": {"type": "array", "items": {"type": "string"}},
    },
}
