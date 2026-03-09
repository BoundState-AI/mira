#!/usr/bin/env python3
"""
Schema diff helpers for FORGE.
"""

from __future__ import annotations

from typing import Any


def diff_schema_manifests(old_manifest: dict[str, Any], new_manifest: dict[str, Any]) -> dict[str, Any]:
    """Compare two schema manifests and return a deterministic change report."""

    old_tables = {table["qualified_name"]: table for table in old_manifest.get("tables", [])}
    new_tables = {table["qualified_name"]: table for table in new_manifest.get("tables", [])}
    changes: list[dict[str, Any]] = []

    for table_name in sorted(new_tables.keys() - old_tables.keys()):
        changes.append({"change_type": "table_added", "table": table_name})
    for table_name in sorted(old_tables.keys() - new_tables.keys()):
        changes.append({"change_type": "table_removed", "table": table_name})

    for table_name in sorted(old_tables.keys() & new_tables.keys()):
        old_columns = {column["name"]: column for column in old_tables[table_name].get("columns", [])}
        new_columns = {column["name"]: column for column in new_tables[table_name].get("columns", [])}

        for column_name in sorted(new_columns.keys() - old_columns.keys()):
            changes.append(
                {
                    "change_type": "column_added",
                    "table": table_name,
                    "column": column_name,
                }
            )
        for column_name in sorted(old_columns.keys() - new_columns.keys()):
            changes.append(
                {
                    "change_type": "column_removed",
                    "table": table_name,
                    "column": column_name,
                }
            )
        for column_name in sorted(old_columns.keys() & new_columns.keys()):
            old_column = old_columns[column_name]
            new_column = new_columns[column_name]
            if old_column.get("data_type") != new_column.get("data_type"):
                changes.append(
                    {
                        "change_type": "column_type_changed",
                        "table": table_name,
                        "column": column_name,
                        "old_type": old_column.get("data_type"),
                        "new_type": new_column.get("data_type"),
                    }
                )

    return {
        "changes": changes,
        "alembic_stub": build_alembic_stub(changes),
    }


def build_alembic_stub(changes: list[dict[str, Any]]) -> str:
    """Build a minimal Alembic migration stub from a change report."""

    lines = [
        "def upgrade():",
    ]
    if changes:
        lines.extend([f"    # {change['change_type']}: {change}" for change in changes])
    else:
        lines.append("    pass")
    lines.extend(
        [
            "",
            "def downgrade():",
            "    pass",
        ]
    )
    return "\n".join(lines)
