"""Semantic field inference — determine the likely meaning of each column.

Uses signals: column names, unit hints (mpa, psi, kelvin), value ranges,
data distributions, and text pattern analysis (emails, URLs, codes, dates).

Each field receives a semantic type, detected units, and a confidence score.
Low-confidence inferences are flagged for human review.

Spec reference: Section 3.2
"""

from __future__ import annotations

import re

from mira.forge_claude.introspector.manifest import (
    ColumnInfo,
    ConfidenceScore,
    SchemaManifest,
    SemanticField,
    SemanticMap,
    TableInfo,
)
from mira.forge_claude.question_gen.patterns import is_boolean, is_date, is_numeric, is_text


# ---------------------------------------------------------------------------
# Unit detection patterns
# ---------------------------------------------------------------------------

UNIT_PATTERNS: list[tuple[str, str, str]] = [
    # (regex on column name, detected_units, detected_property_prefix)
    (r"_mpa$|_megapascal", "MPa", "pressure"),
    (r"_psi$", "psi", "pressure"),
    (r"_gpa$|_gigapascal", "GPa", "pressure"),
    (r"_kpa$|_kilopascal", "kPa", "pressure"),
    (r"_kelvin$|_k$", "K", "temperature"),
    (r"_celsius$|_c$", "°C", "temperature"),
    (r"_fahrenheit$|_f$", "°F", "temperature"),
    (r"_kg$|_kilogram", "kg", "mass"),
    (r"_g$|_gram", "g", "mass"),
    (r"_lb$|_pound", "lb", "mass"),
    (r"_m$|_meter$|_metres?$", "m", "length"),
    (r"_cm$|_centimeter", "cm", "length"),
    (r"_mm$|_millimeter", "mm", "length"),
    (r"_km$|_kilometer", "km", "length"),
    (r"_pct$|_percent", "%", "percentage"),
    (r"_usd$|_dollar", "USD", "currency"),
    (r"_eur$|_euro", "EUR", "currency"),
    (r"_wt_?%|_wt_?pct", "wt%", "composition"),
    (r"_ppm$", "ppm", "concentration"),
    (r"_mg_?kg|_mg_?l", "mg/kg", "concentration"),
]

# Column name patterns that suggest semantic type
NAME_PATTERNS: list[tuple[str, str, str, float]] = [
    # (regex, semantic_type, property, confidence)
    (r"^id$|_id$", "identifier", "primary_key", 0.95),
    (r"email", "contact", "email", 0.95),
    (r"phone|tel", "contact", "phone", 0.90),
    (r"url|website|href|link", "reference", "url", 0.90),
    (r"lat(?:itude)?$", "geospatial", "latitude", 0.95),
    (r"lon(?:gitude)?$|lng$", "geospatial", "longitude", 0.95),
    (r"price|cost|amount|fee|rate(?!d)", "financial", "monetary_value", 0.85),
    (r"name$|_name$|title$", "descriptor", "name", 0.80),
    (r"description|desc$|note|comment|text$|body$", "text_content", "description", 0.80),
    (r"date$|_at$|_on$|timestamp|created|updated|modified", "temporal", "datetime", 0.90),
    (r"year$|month$|day$", "temporal", "date_part", 0.85),
    (r"count$|quantity|qty|num_|number_of", "metric", "count", 0.80),
    (r"score|rating|rank", "metric", "score", 0.85),
    (r"weight|mass", "measurement", "weight", 0.85),
    (r"height|width|length|depth|thickness|diameter|radius", "measurement", "dimension", 0.85),
    (r"temperature|temp$", "measurement", "temperature", 0.85),
    (r"pressure", "measurement", "pressure", 0.85),
    (r"density", "measurement", "density", 0.85),
    (r"strength|hardness|toughness|elasticity|modulus", "measurement", "mechanical_property", 0.85),
    (r"percentage|pct$|ratio", "metric", "percentage", 0.80),
    (r"color|colour", "category", "color", 0.80),
    (r"type$|_type$|category|class$|kind$|group$|family$", "category", "classification", 0.80),
    (r"status|state$", "category", "status", 0.85),
    (r"code$|_code$|sku$|part_number|serial", "identifier", "code", 0.85),
    (r"flag$|is_|has_|can_|enabled|active|visible", "flag", "boolean_flag", 0.90),
    (r"country|nation|region|city|state|province|zip|postal", "geospatial", "location", 0.80),
]

# Value patterns for text columns
VALUE_PATTERNS: list[tuple[str, str, str, float]] = [
    (r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", "contact", "email", 0.95),
    (r"^https?://", "reference", "url", 0.95),
    (r"^\d{3}[-.]?\d{3}[-.]?\d{4}$", "contact", "phone", 0.85),
    (r"^\d{4}-\d{2}-\d{2}", "temporal", "date_string", 0.90),
    (r"^[A-Z]{2,3}-\d+$", "identifier", "code", 0.80),
    (r"^#[0-9a-fA-F]{6}$", "category", "hex_color", 0.90),
]


def _infer_from_name(col_name: str) -> tuple[str, str, str, float]:
    """Infer semantic type from column name patterns.

    Returns (semantic_type, property, units, confidence).
    """
    lower = col_name.lower()

    # Check unit patterns first (most specific)
    for pattern, units, prop_prefix in UNIT_PATTERNS:
        if re.search(pattern, lower):
            return "measurement", f"{prop_prefix}_{col_name}", units, 0.90

    # Check name patterns
    for pattern, sem_type, prop, conf in NAME_PATTERNS:
        if re.search(pattern, lower):
            return sem_type, prop, "", conf

    return "", "", "", 0.0


def _infer_from_values(sample_values: list[str]) -> tuple[str, str, float]:
    """Infer semantic type from sample values.

    Returns (semantic_type, property, confidence).
    """
    if not sample_values:
        return "", "", 0.0

    for value in sample_values[:5]:
        for pattern, sem_type, prop, conf in VALUE_PATTERNS:
            if re.match(pattern, value):
                return sem_type, prop, conf

    return "", "", 0.0


def _infer_from_column_type(col_type: str) -> tuple[str, float]:
    """Infer broad semantic category from SQL type.

    Returns (semantic_type, confidence).
    """
    if is_boolean(col_type):
        return "flag", 0.70
    if is_date(col_type):
        return "temporal", 0.80
    if is_numeric(col_type):
        return "metric", 0.50  # Low confidence — could be anything numeric
    if is_text(col_type):
        return "text_content", 0.30  # Very generic
    return "unknown", 0.0


def infer_column_semantics(
    table: TableInfo,
    col: ColumnInfo,
) -> SemanticField:
    """Infer semantic meaning of a single column.

    Combines name-based, value-based, and type-based signals.
    Highest-confidence signal wins.
    """
    # Signal 1: column name
    name_type, name_prop, name_units, name_conf = _infer_from_name(col.name)

    # Signal 2: sample values
    val_type, val_prop, val_conf = _infer_from_values(col.sample_values)

    # Signal 3: SQL type
    type_type, type_conf = _infer_from_column_type(col.type)

    # Pick highest confidence signal
    best_type = ""
    best_prop = ""
    best_units = name_units  # Only name pattern detects units
    best_conf = 0.0
    best_method = "type_inference"

    if name_conf >= val_conf and name_conf >= type_conf:
        best_type = name_type
        best_prop = name_prop
        best_conf = name_conf
        best_method = "name_pattern"
    elif val_conf >= name_conf and val_conf >= type_conf:
        best_type = val_type
        best_prop = val_prop
        best_conf = val_conf
        best_method = "value_pattern"
    else:
        best_type = type_type
        best_prop = ""
        best_conf = type_conf
        best_method = "type_inference"

    # If no signal matched, mark unknown
    if not best_type:
        best_type = "unknown"
        best_conf = 0.0

    return SemanticField(
        table=table.name,
        column=col.name,
        column_type=col.type,
        semantic_type=best_type,
        detected_property=best_prop,
        detected_units=best_units,
        confidence=ConfidenceScore(
            score=round(best_conf, 2),
            source="semantic_inference",
            method=best_method,
            inputs=[f"{table.name}.{col.name}", col.type] + col.sample_values[:3],
            threshold=0.5,
            action_if_below="mark_unknown_flag_for_review",
        ),
    )


def build_semantic_map(manifest: SchemaManifest) -> SemanticMap:
    """Build a semantic map for all columns in the manifest.

    Returns a SemanticMap with inferences for every column.
    """
    fields = []
    for table in manifest.tables:
        for col in table.columns:
            field = infer_column_semantics(table, col)
            fields.append(field)

    return SemanticMap(
        database_name=manifest.database_name,
        fields=fields,
    )
