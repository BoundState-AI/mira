"""Human gate generation — 80/20 ceiling enforcement.

Identifies operations that require human approval and generates gate
definitions. The heuristics:

- Any operation that modifies data (not just reads) gets a gate
- Any decision involving thresholds at boundary conditions gets a gate
- Any cross-table join that could produce safety-critical correlations gets a gate

The 80/20 ceiling is built into the output, not bolted on later.
"""

from __future__ import annotations

from mira.forge_claude.introspector.manifest import SchemaManifest
from mira.forge_claude.question_gen.patterns import is_numeric
from mira.forge_claude.question_gen.question_map import QuestionMap


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


def generate_human_review_gates(
    manifest: SchemaManifest,
    question_map: QuestionMap,
) -> list[dict]:
    """Generate gates for operations requiring human review.

    Every mutation operation gets a gate. Read-only operations that involve
    threshold boundary decisions or safety-critical correlations also get gates.
    """
    gates = []
    gate_id = 0

    # Gate 1: Mutation gates — any write/update/delete on any table
    for table in manifest.tables:
        gate_id += 1
        gates.append({
            "id": f"gate_{gate_id:03d}",
            "type": "mutation",
            "table": table.name,
            "operations": ["create", "update", "delete"],
            "description": (
                f"Require human approval for any modification to "
                f"{_humanize(table.name)} records"
            ),
            "approval_required": True,
            "approver_role": "editor",
            "audit_log": True,
        })

    # Gate 2: Threshold boundary gates — numeric columns at extremes
    for table in manifest.tables:
        numeric_cols = [
            col for col in table.columns
            if not col.primary_key
            and not col.name.endswith("_id")
            and is_numeric(col.type)
        ]
        if numeric_cols:
            gate_id += 1
            gates.append({
                "id": f"gate_{gate_id:03d}",
                "type": "threshold_boundary",
                "table": table.name,
                "columns": [c.name for c in numeric_cols],
                "description": (
                    f"Escalate when {_humanize(table.name)} numeric values "
                    f"({', '.join(_humanize(c.name) for c in numeric_cols[:3])}) "
                    f"hit boundary conditions"
                ),
                "trigger": "value_at_boundary",
                "approval_required": True,
                "approver_role": "admin",
                "audit_log": True,
            })

    # Gate 3: Cross-table correlation gates — joins that could produce
    # safety-critical correlations
    tables_with_fks = [
        t for t in manifest.tables if len(t.foreign_keys) >= 2
    ]
    for table in tables_with_fks:
        referenced_tables = [fk.references_table for fk in table.foreign_keys]
        gate_id += 1
        gates.append({
            "id": f"gate_{gate_id:03d}",
            "type": "cross_table_correlation",
            "table": table.name,
            "referenced_tables": referenced_tables,
            "description": (
                f"Review cross-table correlations when {_humanize(table.name)} "
                f"joins {', '.join(_humanize(t) for t in referenced_tables)}"
            ),
            "trigger": "multi_table_join",
            "approval_required": False,
            "review_recommended": True,
            "approver_role": "admin",
            "audit_log": True,
        })

    return gates


def generate_escalation_rules(
    manifest: SchemaManifest,
    question_map: QuestionMap,
) -> list[dict]:
    """Generate escalation rules — when to bump from automated to human.

    Escalation triggers are derived from the question map:
    - Analysis questions with comparison or aggregation → escalate on anomalies
    - Detail views → escalate when linked records have conflicting data
    - v4.1: Caveated questions → escalate due to data quality concerns
    """
    # v4.1: Build caveated question lookup from capability map
    caveated_ids: set[str] = set()
    cap_lookup: dict[str, list[str]] = {}
    for cap in question_map.capability_map:
        if not cap.reliable:
            caveated_ids.add(cap.question_id)
            cap_lookup[cap.question_id] = cap.limiting_factors

    rules = []
    rule_id = 0

    for cat in question_map.question_categories:
        if cat.category == "Analysis":
            for q in cat.questions:
                if q.template_type in ("aggregation", "comparison"):
                    rule_id += 1
                    rules.append({
                        "id": f"esc_{rule_id:03d}",
                        "type": "anomaly_escalation",
                        "question_id": q.id,
                        "table": q.target_table,
                        "columns": q.target_columns,
                        "description": (
                            f"Escalate to human review when "
                            f"{q.natural_language} produces anomalous results"
                        ),
                        "trigger": "statistical_anomaly",
                        "escalation_target": "admin",
                    })

        elif cat.category == "Detail":
            for q in cat.questions:
                if q.join_tables:
                    rule_id += 1
                    rules.append({
                        "id": f"esc_{rule_id:03d}",
                        "type": "conflict_escalation",
                        "question_id": q.id,
                        "table": q.target_table,
                        "join_tables": q.join_tables,
                        "description": (
                            f"Escalate when detail view of "
                            f"{_humanize(q.target_table)} reveals "
                            f"conflicting data across "
                            f"{', '.join(_humanize(t) for t in q.join_tables)}"
                        ),
                        "trigger": "data_conflict",
                        "escalation_target": "editor",
                    })

    # v4.1: Add escalation rules for caveated questions
    for cat in question_map.question_categories:
        for q in cat.questions:
            if q.id in caveated_ids:
                rule_id += 1
                factors = cap_lookup.get(q.id, [])
                rules.append({
                    "id": f"esc_{rule_id:03d}",
                    "type": "quality_escalation",
                    "question_id": q.id,
                    "table": q.target_table,
                    "description": (
                        f"Require human review for '{q.natural_language}' "
                        f"due to data quality concerns"
                    ),
                    "trigger": "low_data_quality",
                    "limiting_factors": factors,
                    "escalation_target": "admin",
                })

    return rules


def build_gates_pack(
    manifest: SchemaManifest,
    question_map: QuestionMap,
) -> dict:
    """Build the complete gates structure for the authority pack.

    Returns a dict with human_review gates and escalation rules.
    """
    return {
        "human_review": generate_human_review_gates(manifest, question_map),
        "escalation": generate_escalation_rules(manifest, question_map),
    }
