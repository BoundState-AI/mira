"""Deterministic rule generation from schema patterns.

Generates three categories of rules from the schema manifest:
- Categorical rules: If column X = Y, then Z
- Threshold rules: If numeric value > N, flag as...
- Relationship rules: If A joins B where C, then...

These are starter rules — domain experts refine them. The LLM never writes
the final rules; it suggests, and the rules engine executes deterministically.
"""

from __future__ import annotations

from mira.forge_claude.config import ENUM_LIKE_THRESHOLD
from mira.forge_claude.introspector.manifest import DataQualityReport, SchemaManifest, SemanticMap, TableInfo
from mira.forge_claude.question_gen.patterns import is_date, is_numeric, is_text


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


def _is_categorical(col, row_count: int) -> bool:
    """Column has low cardinality relative to row count."""
    if col.unique_count is None or row_count == 0:
        return False
    if col.unique_count <= 1:
        return False
    return col.unique_count / row_count <= ENUM_LIKE_THRESHOLD or col.unique_count <= 20


def generate_categorical_rules(manifest: SchemaManifest) -> list[dict]:
    """Generate conditional routing rules from low-cardinality columns.

    For each categorical column, produce a rule template:
    'When {table}.{column} equals {value}, route to {action}'
    """
    rules = []
    rule_id = 0

    for table in manifest.tables:
        for col in table.columns:
            if col.primary_key:
                continue
            if not is_text(col.type):
                continue
            if not _is_categorical(col, table.row_count):
                continue

            rule_id += 1
            values = col.sample_values or []
            rules.append({
                "id": f"cat_{rule_id:03d}",
                "type": "categorical",
                "table": table.name,
                "column": col.name,
                "description": (
                    f"When {_humanize(table.name)} "
                    f"{_humanize(col.name)} matches a known category, "
                    f"apply domain-specific routing"
                ),
                "known_values": values,
                "unique_count": col.unique_count,
                "action": "route_by_category",
                "requires_human_review": False,
                "confidence": "high",
            })

    return rules


def generate_threshold_rules(
    manifest: SchemaManifest,
    *,
    semantic_map: SemanticMap | None = None,
    data_quality_report: DataQualityReport | None = None,
) -> list[dict]:
    """Generate boundary detection rules from numeric columns.

    For each numeric column, produce a rule template:
    'When {table}.{column} exceeds threshold, flag for review'

    v4.1: Uses semantic map for unit-aware descriptions and data quality
    report for quality-gated confidence.
    """
    # Build lookups
    sem_lookup: dict[tuple[str, str], dict] = {}
    if semantic_map:
        for f in semantic_map.fields:
            sem_lookup[(f.table, f.column)] = {
                "units": f.detected_units,
                "property": f.detected_property,
                "semantic_type": f.semantic_type,
            }

    quality_lookup: dict[tuple[str, str], dict] = {}
    if data_quality_report:
        for tq in data_quality_report.tables:
            for cq in tq.columns:
                issues = []
                if cq.null_rate > 0.3:
                    issues.append("high_null_rate")
                if cq.outlier_count > 0:
                    issues.append("outlier_detected")
                if issues:
                    quality_lookup[(cq.table, cq.column)] = {"issues": issues}

    rules = []
    rule_id = 0

    for table in manifest.tables:
        numeric_cols = [
            col for col in table.columns
            if not col.primary_key and is_numeric(col.type)
        ]

        for col in numeric_cols:
            # Skip foreign key ID columns
            if col.name.endswith("_id"):
                continue

            rule_id += 1

            # v4.1: Enrich description with units
            sem = sem_lookup.get((table.name, col.name))
            units_str = ""
            if sem and sem["units"]:
                units_str = f" ({sem['units']})"

            # v4.1: Adjust confidence based on quality
            quality = quality_lookup.get((table.name, col.name))
            confidence = "medium"
            quality_caveats = []
            if quality:
                if "high_null_rate" in quality["issues"]:
                    confidence = "low"
                    quality_caveats.append("high null rate")
                if "outlier_detected" in quality["issues"]:
                    quality_caveats.append("outliers detected")

            rule = {
                "id": f"thr_{rule_id:03d}",
                "type": "threshold",
                "table": table.name,
                "column": col.name,
                "description": (
                    f"Flag {_humanize(_singularize(table.name))} when "
                    f"{_humanize(col.name)}{units_str} exceeds domain-defined threshold"
                ),
                "threshold_placeholder": {
                    "warning": "TODO: Set by domain expert",
                    "critical": "TODO: Set by domain expert",
                },
                "action": "flag_for_review",
                "requires_human_review": True,
                "confidence": confidence,
            }

            if quality_caveats:
                rule["quality_caveats"] = quality_caveats

            rules.append(rule)

    return rules


def generate_relationship_rules(manifest: SchemaManifest) -> list[dict]:
    """Generate dependency chain rules from foreign key relationships.

    For each FK relationship, produce a rule template:
    'When {child_table} references {parent_table}, enforce domain constraint'
    """
    rules = []
    rule_id = 0

    for rel in manifest.relationships:
        rule_id += 1
        rules.append({
            "id": f"rel_{rule_id:03d}",
            "type": "relationship",
            "from_table": rel.from_table,
            "from_column": rel.from_column,
            "to_table": rel.to_table,
            "to_column": rel.to_column,
            "relationship_type": rel.type,
            "description": (
                f"When {_humanize(rel.from_table)} references "
                f"{_humanize(rel.to_table)}, validate referential integrity "
                f"and enforce domain constraints"
            ),
            "action": "validate_reference",
            "requires_human_review": False,
            "confidence": "high",
        })

    return rules


def generate_all_rules(
    manifest: SchemaManifest,
    *,
    semantic_map: SemanticMap | None = None,
    data_quality_report: DataQualityReport | None = None,
) -> dict:
    """Generate all rule templates from schema manifest.

    Returns a dict with categorical, threshold, and relationship rule lists.
    """
    return {
        "categorical": generate_categorical_rules(manifest),
        "threshold": generate_threshold_rules(
            manifest,
            semantic_map=semantic_map,
            data_quality_report=data_quality_report,
        ),
        "relationship": generate_relationship_rules(manifest),
    }
