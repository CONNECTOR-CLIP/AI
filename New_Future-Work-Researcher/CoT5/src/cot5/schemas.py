EQUIVALENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "equivalent",
        "purpose_overlap",
        "mechanism_overlap",
        "evaluation_overlap",
        "application_overlap",
        "critical_difference",
        "evidence_from_abstract",
        "confidence",
    ],
    "properties": {
        "equivalent": {"type": "boolean"},
        "purpose_overlap": {"type": "string"},
        "mechanism_overlap": {"type": "string"},
        "evaluation_overlap": {"type": "string"},
        "application_overlap": {"type": "string"},
        "critical_difference": {"type": "string"},
        "evidence_from_abstract": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}
