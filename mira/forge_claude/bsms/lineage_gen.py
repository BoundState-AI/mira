"""Generate lineage.py for decision audit trails in FORGE-generated apps."""

from __future__ import annotations

from textwrap import dedent
from typing import Any


def generate_lineage_code() -> str:
    """Return the lineage module source code."""
    return dedent('''\
        from __future__ import annotations

        import json
        from datetime import datetime
        from pathlib import Path
        from typing import Any

        from config import LINEAGE_DIR

        LINEAGE_LOG = LINEAGE_DIR / "decision_lineage.jsonl"


        def record_lineage(payload: dict[str, Any]) -> dict[str, Any]:
            enriched = {
                **payload,
                "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat() + "Z",
            }
            LINEAGE_DIR.mkdir(parents=True, exist_ok=True)
            with LINEAGE_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(enriched) + "\\n")
            return enriched
    ''')


def generate_lineage_schema() -> dict[str, Any]:
    """Return the lineage schema definition."""
    return {
        "version": "1.0.0",
        "format": "jsonl",
        "fields": {
            "timestamp": {"type": "string", "format": "iso8601"},
            "pipeline": {"type": "string", "enum": ["B-S-M-S"]},
            "query": {"type": "string"},
            "bouncer_verdict": {"type": "string", "enum": ["PASS", "REJECT"]},
            "parsed_intent": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "question_type": {"type": "string"},
                    "table": {"type": "string"},
                    "filters": {"type": "object"},
                    "confidence": {"type": "number"},
                    "decision_source": {"type": "string"},
                },
            },
            "rules_verdict": {"type": "string", "enum": ["SUPPORTED", "HUMAN_REVIEW_REQUIRED"]},
            "rules_applied": {"type": "array", "items": {"type": "string"}},
            "evidence_sources": {"type": "array", "items": {"type": "string"}},
            "executed_query": {"type": "string"},
            "rendering_source": {"type": "string"},
            "confidence": {"type": "number"},
        },
    }
