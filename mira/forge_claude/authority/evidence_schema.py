"""Evidence schema generation for authority packs.

For every decision the generated application can make, generates an evidence
schema defining:
- What data points support the decision
- What citations are required
- What confidence level applies
- What the human reviewer needs to see

This is the "never recommend without citation" principle automated.
"""

from __future__ import annotations

from mira.forge_claude.introspector.manifest import SchemaManifest
from mira.forge_claude.question_gen.patterns import is_date, is_numeric, is_text
from mira.forge_claude.question_gen.question_map import CapabilityEntry, QuestionMap


def _humanize(name: str) -> str:
    return name.replace("_", " ")


def _singularize(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def generate_evidence_schemas(
    manifest: SchemaManifest,
    question_map: QuestionMap,
) -> list[dict]:
    """Generate evidence schemas from the question map.

    Each question type implies a decision the application can surface.
    We generate a schema for each distinct decision pattern.

    v4.1: Uses capability map for per-question reliability scoring.
    """
    # Build capability lookup for v4.1 enrichment
    cap_lookup: dict[str, CapabilityEntry] = {}
    for cap in question_map.capability_map:
        cap_lookup[cap.question_id] = cap

    schemas = []
    schema_id = 0

    for cat in question_map.question_categories:
        for q in cat.questions:
            schema_id += 1
            schema = _build_evidence_for_question(schema_id, q, manifest)
            if schema:
                # v4.1: Overlay capability reliability
                cap = cap_lookup.get(q.id)
                if cap:
                    schema["reliability_score"] = cap.reliability_score
                    schema["reliable"] = cap.reliable
                    if cap.limiting_factors:
                        schema["limiting_factors"] = cap.limiting_factors

                # v4.1: Use question-level confidence if available
                if hasattr(q, "confidence") and q.confidence.score < 1.0:
                    schema["confidence_level"] = (
                        "low" if q.confidence.score < 0.5
                        else "medium" if q.confidence.score < 0.8
                        else schema["confidence_level"]
                    )
                    if q.data_caveats:
                        schema["data_caveats"] = q.data_caveats

                schemas.append(schema)

    return schemas


def _build_evidence_for_question(
    schema_id: int,
    question,
    manifest: SchemaManifest,
) -> dict | None:
    """Build evidence schema for a single question."""

    # Find the target table in manifest for column info
    target_table = None
    for t in manifest.tables:
        if t.name == question.target_table:
            target_table = t
            break

    if target_table is None:
        return None

    # Build required data points from target columns
    data_points = []
    for col in target_table.columns:
        if question.target_columns == ["*"] or col.name in question.target_columns:
            data_points.append({
                "column": col.name,
                "table": target_table.name,
                "type": col.type,
                "role": _classify_data_point_role(col.name, col.type),
            })

    # Add join table references as supporting evidence
    citations = []
    for join_table in question.join_tables:
        citations.append({
            "source_table": join_table,
            "relationship": f"{question.target_table} -> {join_table}",
            "required": True,
        })

    # Determine confidence level based on question type
    confidence = _confidence_for_template(question.template_type)

    # Determine what the reviewer needs to see
    reviewer_fields = _reviewer_fields_for_template(
        question.template_type, target_table, question.target_columns
    )

    return {
        "id": f"ev_{schema_id:03d}",
        "question_id": question.id,
        "decision_type": question.template_type,
        "description": question.natural_language,
        "target_table": question.target_table,
        "data_points": data_points,
        "citations": citations,
        "confidence_level": confidence,
        "reviewer_checklist": reviewer_fields,
    }


def _classify_data_point_role(col_name: str, col_type: str) -> str:
    """Classify a data point's role in evidence."""
    if col_name.endswith("_id") or col_name == "id":
        return "identifier"
    if is_date(col_type):
        return "temporal"
    if is_numeric(col_type):
        return "metric"
    if is_text(col_type):
        return "descriptor"
    return "attribute"


def _confidence_for_template(template_type: str) -> str:
    """Determine confidence level for a question template type."""
    high_confidence = {"text_search", "categorical_filter", "detail_view"}
    medium_confidence = {"aggregation", "time_series"}
    low_confidence = {"comparison", "cross_reference"}

    if template_type in high_confidence:
        return "high"
    if template_type in medium_confidence:
        return "medium"
    return "low"


def _reviewer_fields_for_template(
    template_type: str,
    table,
    target_columns: list[str],
) -> list[dict]:
    """Determine what a human reviewer needs to see for this decision type."""
    fields = []

    if template_type == "aggregation":
        fields.append({
            "field": "statistical_method",
            "check": "Verify aggregation method is appropriate for data distribution",
        })
        fields.append({
            "field": "outlier_impact",
            "check": "Review whether outliers skew the aggregate result",
        })

    elif template_type == "comparison":
        fields.append({
            "field": "comparison_basis",
            "check": "Verify compared values share the same unit and scale",
        })
        fields.append({
            "field": "sample_size",
            "check": "Confirm sufficient data points for meaningful comparison",
        })

    elif template_type == "time_series":
        fields.append({
            "field": "time_range",
            "check": "Verify time range covers representative period",
        })
        fields.append({
            "field": "seasonality",
            "check": "Check for seasonal patterns that may distort trends",
        })

    elif template_type in ("text_search", "categorical_filter"):
        fields.append({
            "field": "result_completeness",
            "check": "Verify search/filter returns all relevant records",
        })

    elif template_type == "detail_view":
        fields.append({
            "field": "data_currency",
            "check": "Confirm displayed data reflects latest available information",
        })

    # Universal: every decision needs a data provenance check
    fields.append({
        "field": "data_provenance",
        "check": f"Confirm data from {table.name} is authoritative and current",
    })

    return fields


def build_evidence_pack_schema(
    manifest: SchemaManifest,
    question_map: QuestionMap,
) -> dict:
    """Build the complete evidence pack schema structure.

    Returns a dict suitable for writing to evidence/schema.json.
    """
    schemas = generate_evidence_schemas(manifest, question_map)

    return {
        "version": "1.0",
        "database": manifest.database_name,
        "principle": "Never recommend without citation",
        "evidence_schemas": schemas,
        "template_fields": {
            "decision_id": "Unique identifier for the decision",
            "timestamp": "When the decision was made",
            "user_id": "Who requested the decision",
            "evidence_items": "List of data points that support the decision",
            "citations": "References to source data tables and records",
            "confidence": "Confidence level (high/medium/low)",
            "reviewer": "Human reviewer who validated the decision (if required)",
            "review_timestamp": "When the human review was completed",
        },
    }
