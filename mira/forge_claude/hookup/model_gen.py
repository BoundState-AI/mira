"""Pydantic model generation from schema manifest."""

from __future__ import annotations

import re

from mira.forge_claude.introspector.manifest import SchemaManifest, SemanticMap, TableInfo
from mira.forge_claude.question_gen.patterns import is_date, is_numeric, is_text, is_boolean


def _python_type(col_type: str, nullable: bool) -> str:
    """Map SQL type to Python type annotation."""
    if is_numeric(col_type):
        if any(t in col_type.upper() for t in ("FLOAT", "REAL", "DOUBLE", "NUMERIC", "DECIMAL")):
            base = "float"
        else:
            base = "int"
    elif is_date(col_type):
        base = "str"  # Keep as string for simplicity
    elif is_boolean(col_type):
        base = "bool"
    elif is_text(col_type):
        base = "str"
    else:
        base = "str"

    if nullable:
        return f"{base} | None = None"
    return base


def _safe_py(name: str) -> str:
    """Convert a schema-qualified name to a valid Python identifier."""
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name and name[0].isdigit():
        name = f"t_{name}"
    return name or "unknown"


def _pascal(name: str) -> str:
    safe = _safe_py(name)
    return "".join(word.capitalize() for word in safe.split("_"))


def _build_semantic_lookup(
    semantic_map: SemanticMap | None,
) -> dict[tuple[str, str], dict]:
    """Build a (table, column) -> semantic info lookup."""
    if not semantic_map:
        return {}
    lookup: dict[tuple[str, str], dict] = {}
    for field in semantic_map.fields:
        desc_parts = []
        if field.detected_property:
            desc_parts.append(field.detected_property.replace("_", " "))
        if field.semantic_type and field.semantic_type != "unknown":
            desc_parts.append(f"({field.semantic_type})")
        if field.detected_units:
            desc_parts.append(f"in {field.detected_units}")
        if desc_parts:
            lookup[(field.table, field.column)] = {
                "description": " ".join(desc_parts),
            }
    return lookup


def generate_pydantic_models(
    manifest: SchemaManifest,
    *,
    semantic_map: SemanticMap | None = None,
) -> str:
    """Generate Pydantic model code from schema manifest.

    Args:
        manifest: The schema manifest from Step 1.
        semantic_map: Optional v4.1 semantic map for field descriptions.
    """
    sem_lookup = _build_semantic_lookup(semantic_map)

    lines = [
        '"""Auto-generated Pydantic models from schema manifest."""',
        "",
        "from __future__ import annotations",
        "",
        "from pydantic import BaseModel, Field",
        "",
    ]

    for table in manifest.tables:
        class_name = _pascal(table.name)
        lines.append(f"class {class_name}(BaseModel):")
        lines.append(f'    """Model for {table.name} table."""')
        lines.append("")

        for col in table.columns:
            type_str = _python_type(col.type, col.nullable)
            sem_info = sem_lookup.get((table.name, col.name))
            if sem_info:
                desc = sem_info["description"]
                if col.nullable:
                    # Type already has "| None = None", need Field with description
                    base = type_str.split(" |")[0]
                    lines.append(
                        f'    {col.name}: {base} | None = Field(None, description="{desc}")'
                    )
                else:
                    lines.append(
                        f'    {col.name}: {type_str} = Field(description="{desc}")'
                    )
            else:
                lines.append(f"    {col.name}: {type_str}")

        lines.append("")
        lines.append(f"    class Config:")
        lines.append(f"        from_attributes = True")
        lines.append("")
        lines.append("")

    return "\n".join(lines)
