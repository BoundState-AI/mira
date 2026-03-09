"""Generate BSMS pipeline configuration from FORGE compile artifacts."""

from __future__ import annotations

from typing import Any


def generate_bsms_config(
    capabilities: dict[str, Any],
    question_map: dict[str, Any],
    semantic_map: dict[str, Any],
) -> dict[str, Any]:
    """Build the BSMS pipeline configuration dict.

    This is the runtime config that drives bouncer keywords,
    parser field mappings, rules engine operations, and formatter settings.
    """
    questions = question_map.get("questions", [])
    if not questions:
        # Handle categorized question maps
        for cat in question_map.get("question_categories", []):
            for q in cat.get("questions", []):
                questions.append({
                    "id": q.get("id", ""),
                    "question_type": q.get("type", cat.get("category", "")),
                    "table": q.get("table", ""),
                    **q,
                })

    allowed_intents = sorted({q.get("question_type", "") for q in questions if q.get("question_type")})

    tables = semantic_map.get("tables", {})
    if not tables:
        # Handle field-based semantic maps
        fields = semantic_map.get("fields", [])
        for field in fields:
            table = field.get("table", "")
            col = field.get("column", "")
            if table and col:
                tables.setdefault(table, {"columns": {}})
                tables[table]["columns"][col] = field.get("semantic_type", "unknown")

    vocabulary = sorted(
        {
            col_name
            for table in tables.values()
            for col_name in (table.get("columns", {}).keys() if isinstance(table, dict) else [])
        }
    )

    return {
        "architecture": "Bouncer -> LLM Parse -> Deterministic Rules -> LLM Format",
        "bouncer_config": {
            "allowed_intents": allowed_intents,
            "domain_keywords": vocabulary[:100],
            "mutation_terms_blocked": [
                "delete", "drop", "truncate", "update",
                "insert", "alter", "create", "grant", "revoke",
            ],
        },
        "parser_config": {
            "field_mappings": {
                table_name: list(table.get("columns", {}).keys()) if isinstance(table, dict) else []
                for table_name, table in tables.items()
            },
            "llm_selection_mode": "candidate_question_selection",
        },
        "rules_engine": {
            "mode": "deterministic_python",
            "supported_operations": capabilities.get("table_capabilities", {}),
            "status": "active_scaffold",
            "human_review_terms": [
                "approve", "certify", "guarantee", "sign off",
                "safety critical", "compliance decision",
            ],
        },
        "formatter_config": {
            "citation_style": "evidence_first",
            "include_executed_query": True,
            "include_rules_applied": True,
            "llm_summary_mode": "grounded_json_only",
        },
        "llm_runtime": {
            "provider": "anthropic",
            "enabled_env": "FORGE_BSMS_ENABLE_LLM",
            "api_key_env": "ANTHROPIC_API_KEY",
            "model_env": "FORGE_BSMS_MODEL",
            "default_model": "claude-sonnet-4-20250514",
        },
    }
