"""Authority Pack generator — orchestrates pack structure scaffolding.

Generates the authority_pack/ directory structure:

    authority_pack/
    ├── manifest.json          # Pack metadata, version, domain
    ├── rules/
    │   ├── categorical.json   # If column X = Y, then Z
    │   ├── threshold.json     # If value > N, flag as...
    │   └── relationship.json  # If A joins B where C, then...
    ├── evidence/
    │   ├── schema.json        # Required evidence fields per decision
    │   └── templates/         # Evidence packet templates
    ├── gates/
    │   ├── human_review.json  # What requires human approval
    │   └── escalation.json    # When to escalate
    └── extracts/              # [Empty] For customer document ingestion
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from mira.forge_claude.config import DEFAULT_OUTPUT_DIR
from mira.forge_claude.introspector.manifest import DataQualityReport, SchemaManifest, SemanticMap
from mira.forge_claude.question_gen.question_map import QuestionMap

from mira.forge_claude.authority.evidence_schema import build_evidence_pack_schema
from mira.forge_claude.authority.human_gate import build_gates_pack
from mira.forge_claude.authority.rule_templates import generate_all_rules


def _build_pack_manifest(
    manifest: SchemaManifest,
    question_map: QuestionMap,
    rules: dict,
    gates: dict,
) -> dict:
    """Build the top-level authority pack manifest."""
    total_rules = sum(len(v) for v in rules.values())
    total_gates = len(gates.get("human_review", []))
    total_escalations = len(gates.get("escalation", []))

    stats = {
        "tables_analyzed": manifest.statistics.total_tables,
        "total_rows": manifest.statistics.total_rows,
        "rules_generated": total_rules,
        "categorical_rules": len(rules.get("categorical", [])),
        "threshold_rules": len(rules.get("threshold", [])),
        "relationship_rules": len(rules.get("relationship", [])),
        "human_gates": total_gates,
        "escalation_rules": total_escalations,
    }

    # v4.1: Add quality/capability stats if available
    if question_map.capability_map:
        stats["total_questions"] = len(question_map.capability_map)
        stats["reliable_questions"] = question_map.total_reliable
        stats["caveated_questions"] = question_map.total_caveated

    return {
        "version": "1.0",
        "forge_version": "0.1.0",
        "database": manifest.database_name,
        "database_type": manifest.database_type,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "domain_summary": question_map.domain_summary,
        "statistics": stats,
        "principle": (
            "Deterministic rules handle safety-critical logic. "
            "LLMs translate between humans and structured data. "
            "Engineers remain validators, never replaced."
        ),
        "status": "generated",
        "reviewed_by": None,
        "reviewed_at": None,
    }


def _build_evidence_template() -> dict:
    """Build a blank evidence packet template for domain expert use."""
    return {
        "template_version": "1.0",
        "instructions": (
            "Fill in this template for each decision that requires evidence. "
            "Each evidence packet documents why a particular conclusion was reached."
        ),
        "packet": {
            "decision_id": "TODO: Auto-generated decision identifier",
            "decision_type": "TODO: Type of decision (search/filter/analysis/detail)",
            "timestamp": "TODO: ISO 8601 timestamp",
            "requestor": {
                "user_id": "TODO: User who initiated the query",
                "role": "TODO: User's role (admin/editor/viewer)",
            },
            "evidence_items": [
                {
                    "source_table": "TODO: Table name",
                    "source_column": "TODO: Column name",
                    "value": "TODO: The actual data value",
                    "retrieved_at": "TODO: When the value was read from the database",
                },
            ],
            "citations": [
                {
                    "reference_table": "TODO: Cited source table",
                    "reference_id": "TODO: Primary key of cited record",
                    "relationship": "TODO: How this citation supports the decision",
                },
            ],
            "confidence": "TODO: high/medium/low",
            "human_review": {
                "required": "TODO: true/false",
                "reviewer": "TODO: Reviewer user ID (if reviewed)",
                "review_timestamp": "TODO: When review was completed",
                "disposition": "TODO: approved/rejected/needs_revision",
                "notes": "TODO: Reviewer comments",
            },
        },
    }


def generate_authority_pack(
    manifest: SchemaManifest,
    question_map: QuestionMap,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    semantic_map: SemanticMap | None = None,
    data_quality_report: DataQualityReport | None = None,
) -> Path:
    """Generate a complete authority pack from schema and question map.

    Args:
        manifest: The schema manifest from Step 1.
        question_map: The question map from Step 2.
        output_dir: Base output directory.
        semantic_map: Optional v4.1 semantic map for enriched rules.
        data_quality_report: Optional v4.1 data quality report for quality-gated rules.

    Returns:
        Path to the generated authority_pack/ directory.
    """
    db_name = question_map.database_name
    pack_dir = output_dir / db_name / "authority_pack"

    # Create directory structure
    (pack_dir / "rules").mkdir(parents=True, exist_ok=True)
    (pack_dir / "evidence" / "templates").mkdir(parents=True, exist_ok=True)
    (pack_dir / "gates").mkdir(parents=True, exist_ok=True)
    (pack_dir / "extracts").mkdir(parents=True, exist_ok=True)

    # Generate rules (v4.1: semantic + quality enriched)
    rules = generate_all_rules(
        manifest,
        semantic_map=semantic_map,
        data_quality_report=data_quality_report,
    )
    _write_json(pack_dir / "rules" / "categorical.json", rules["categorical"])
    _write_json(pack_dir / "rules" / "threshold.json", rules["threshold"])
    _write_json(pack_dir / "rules" / "relationship.json", rules["relationship"])

    # Generate evidence schemas
    evidence_schema = build_evidence_pack_schema(manifest, question_map)
    _write_json(pack_dir / "evidence" / "schema.json", evidence_schema)

    # Generate evidence packet template
    evidence_template = _build_evidence_template()
    _write_json(
        pack_dir / "evidence" / "templates" / "evidence_packet.json",
        evidence_template,
    )

    # Generate gates
    gates = build_gates_pack(manifest, question_map)
    _write_json(pack_dir / "gates" / "human_review.json", gates["human_review"])
    _write_json(pack_dir / "gates" / "escalation.json", gates["escalation"])

    # Generate pack manifest (top-level)
    pack_manifest = _build_pack_manifest(manifest, question_map, rules, gates)
    _write_json(pack_dir / "manifest.json", pack_manifest)

    # Create .gitkeep in extracts/ so empty dir is tracked
    (pack_dir / "extracts" / ".gitkeep").write_text("")

    return pack_dir


def _write_json(path: Path, data) -> None:
    """Write data as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
