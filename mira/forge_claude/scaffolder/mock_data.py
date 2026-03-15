"""Mock data generation from schema manifest."""

from __future__ import annotations

import json
import random
import string

from mira.forge_claude.introspector.manifest import SchemaManifest, TableInfo
from mira.forge_claude.question_gen.patterns import is_date, is_numeric, is_text


def _generate_mock_value(col_type: str, col_name: str, sample_values: list[str]) -> str:
    """Generate a plausible mock value for a column."""
    if sample_values:
        return json.dumps(random.choice(sample_values))

    if is_numeric(col_type):
        if "id" in col_name.lower():
            return str(random.randint(1, 100))
        return str(round(random.uniform(1, 1000), 2))

    if is_date(col_type):
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        return json.dumps(f"2025-{month:02d}-{day:02d}")

    if is_text(col_type):
        return json.dumps(f"Sample {col_name}")

    return json.dumps("mock_value")


def generate_mock_rows(table: TableInfo, count: int = 5) -> list[dict]:
    """Generate mock rows for a table."""
    rows = []
    for i in range(count):
        row = {}
        for col in table.columns:
            if col.primary_key:
                row[col.name] = i + 1
            else:
                val = _generate_mock_value(col.type, col.name, col.sample_values)
                # Try to parse JSON, fallback to raw
                try:
                    row[col.name] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    row[col.name] = val
        rows.append(row)
    return rows


def generate_mock_data_module(manifest: SchemaManifest) -> str:
    """Generate a JavaScript module with mock data for all tables."""
    lines = ["// Auto-generated mock data from schema manifest", ""]

    for table in manifest.tables:
        rows = generate_mock_rows(table, count=5)
        var_name = f"mock{_pascal(table.name)}"
        lines.append(f"export const {var_name} = {json.dumps(rows, indent=2)};")
        lines.append("")

    return "\n".join(lines)


def _pascal(name: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in name.split("_"))
