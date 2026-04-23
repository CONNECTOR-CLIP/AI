# schemas.py
"""
JSON Schema (draft-2020-12) definitions for the CFO/CSO-based arXiv tree builder.
Provides INPUT_SCHEMA and OUTPUT_SCHEMA as dict constants.
"""

INPUT_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.local/schemas/input-papers.schema.json",
    "title": "InputPapers",
    "type": "object",
    "additionalProperties": False,
    "required": ["input_papers"],
    "properties": {
        "run_config": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_iterations": {"type": "integer", "minimum": 1, "default": 6},
                "top_k": {"type": "integer", "minimum": 1, "default": 5},
                "ambiguity_margin": {"type": "number", "minimum": 0, "default": 0.08},
                "max_intermediate_nodes_per_root": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                    "default": 3,
                },
                "subtopic_expansion_threshold": {
                    "type": "integer",
                    "minimum": 2,
                    "default": 20,
                },
                "max_expansion_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 3,
                },
                "allow_arxiv_fetch": {"type": "boolean", "default": False},
                "root_allowlist": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": ["cs.AI"],
                },
            },
        },
        "input_papers": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/paper"},
        },
    },
    "$defs": {
        "paper": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "paper_id",
                "title",
                "abstract",
                "arxiv_id",
                "arxiv_primary_category",
                "arxiv_categories",
                "authors",
                "year",
                "source",
            ],
            "properties": {
                "paper_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "abstract": {"type": "string"},
                "arxiv_id": {"type": ["string", "null"], "default": None},
                "arxiv_primary_category": {"type": ["string", "null"], "default": None},
                "arxiv_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "authors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "year": {"type": ["integer", "null"], "default": None},
                "source": {
                    "type": "string",
                    "enum": ["arxiv_api", "arxiv_oai", "user_search", "other"],
                },
            },
        }
    },
}

OUTPUT_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.local/schemas/cfo-tree-output.schema.json",
    "title": "CFOTreeOutput",
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "generated_at", "roots", "validation", "provenance"],
    "properties": {
        "version": {"type": "string", "minLength": 1},
        "generated_at": {"type": "string", "minLength": 1},
        "roots": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/root"},
        },
        "validation": {"$ref": "#/$defs/validation"},
        "provenance": {
            "type": "object",
            "additionalProperties": False,
            "required": ["cfo_classifier_info", "assumptions", "adapter_fallbacks"],
            "properties": {
                "cfo_classifier_info": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "name": {"type": ["string", "null"]},
                        "version": {"type": ["string", "null"]},
                        "citations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                    },
                },
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "adapter_fallbacks": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "$defs": {
        "root": {
            "type": "object",
            "additionalProperties": False,
            "required": ["arxiv_primary_category", "intermediate_nodes"],
            "properties": {
                "arxiv_primary_category": {"type": "string", "minLength": 1},
                "intermediate_nodes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/intermediate"},
                },
            },
        },
        "intermediate": {
            "type": "object",
            "additionalProperties": False,
            "required": ["node_id", "label", "cfo", "children"],
            "properties": {
                "node_id": {"type": "string", "minLength": 1},
                "label": {"type": "string", "minLength": 1},
                "expanded_from": {"type": ["string", "null"]},
                "cfo": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["label_id", "initial_keywords"],
                    "properties": {
                        "label_id": {"type": ["string", "null"]},
                        "initial_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "children": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/leaf"},
                },
            },
        },
        "leaf": {
            "type": "object",
            "additionalProperties": False,
            "required": ["paper_id", "assignment"],
            "properties": {
                "paper_id": {"type": "string", "minLength": 1},
                "title": {"type": "string"},
                "assignment": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "cfo_label_id",
                        "score",
                        "was_reexpressed",
                        "reexpress_iteration",
                    ],
                    "properties": {
                        "cfo_label_id": {"type": ["string", "null"]},
                        "score": {"type": ["number", "null"]},
                        "was_reexpressed": {"type": "boolean"},
                        "reexpress_iteration": {"type": ["integer", "null"]},
                    },
                },
            },
        },
        "validation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["is_valid", "errors", "warnings", "stats"],
            "properties": {
                "is_valid": {"type": "boolean"},
                "errors": {"type": "array", "items": {"type": "string"}},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "stats": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "num_input_papers",
                        "num_roots",
                        "num_intermediate_nodes",
                        "num_assigned_leaves",
                        "num_reexpressed",
                        "iterations_used",
                    ],
                    "properties": {
                        "num_input_papers": {"type": "integer", "minimum": 0},
                        "num_roots": {"type": "integer", "minimum": 0},
                        "num_intermediate_nodes": {"type": "integer", "minimum": 0},
                        "num_assigned_leaves": {"type": "integer", "minimum": 0},
                        "num_reexpressed": {"type": "integer", "minimum": 0},
                        "iterations_used": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
    },
}
