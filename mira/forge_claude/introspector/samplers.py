"""Column value sampling and profiling logic.

Enhanced for v4.1 with distribution shape detection, min/max/mean,
null rate computation, and value frequency analysis.
"""

from __future__ import annotations

import math
from collections import Counter

from sqlalchemy import text
from sqlalchemy.engine import Engine

from mira.forge_claude.config import DEFAULT_SAMPLE_COUNT, MAX_SAMPLE_SCAN
from mira.forge_claude.introspector.manifest import ColumnProfile
from mira.forge_claude.question_gen.patterns import is_numeric


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _render_table_ref(table_name: str | tuple[str | None, str]) -> str:
    if isinstance(table_name, tuple):
        schema, table = table_name
        if schema:
            return f"{_quote_ident(schema)}.{_quote_ident(table)}"
        return _quote_ident(table)
    if "." in table_name:
        schema, table = table_name.split(".", 1)
        return f"{_quote_ident(schema)}.{_quote_ident(table)}"
    return _quote_ident(table_name)


def sample_column_values(
    engine: Engine,
    table_name: str | tuple[str | None, str],
    column_name: str,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
) -> list[str]:
    """Sample distinct non-null values from a column."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT DISTINCT {_quote_ident(column_name)} FROM {table_ref} "
        f"WHERE {_quote_ident(column_name)} IS NOT NULL LIMIT :limit"
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": sample_count}).fetchall()
    return [str(row[0]) for row in rows]


def count_unique_values(
    engine: Engine,
    table_name: str | tuple[str | None, str],
    column_name: str,
) -> int:
    """Count distinct non-null values in a column."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT COUNT(DISTINCT {_quote_ident(column_name)}) FROM {table_ref} "
        f"WHERE {_quote_ident(column_name)} IS NOT NULL"
    )
    with engine.connect() as conn:
        result = conn.execute(query).scalar()
    return int(result) if result else 0


def count_rows(engine: Engine, table_name: str | tuple[str | None, str]) -> int:
    """Count total rows in a table."""
    query = text(f"SELECT COUNT(*) FROM {_render_table_ref(table_name)}")
    with engine.connect() as conn:
        result = conn.execute(query).scalar()
    return int(result) if result else 0


def count_nulls(
    engine: Engine,
    table_name: str | tuple[str | None, str],
    column_name: str,
) -> int:
    """Count null values in a column."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT COUNT(*) FROM {table_ref} WHERE {_quote_ident(column_name)} IS NULL"
    )
    with engine.connect() as conn:
        result = conn.execute(query).scalar()
    return int(result) if result else 0


def get_numeric_stats(
    engine: Engine,
    table_name: str | tuple[str | None, str],
    column_name: str,
) -> tuple[float | None, float | None, float | None]:
    """Get min, max, mean for a numeric column. Returns (min, max, mean)."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT MIN({_quote_ident(column_name)}), MAX({_quote_ident(column_name)}), AVG({_quote_ident(column_name)}) "
        f"FROM {table_ref} WHERE {_quote_ident(column_name)} IS NOT NULL"
    )
    with engine.connect() as conn:
        row = conn.execute(query).fetchone()
    if row is None:
        return None, None, None
    min_val = float(row[0]) if row[0] is not None else None
    max_val = float(row[1]) if row[1] is not None else None
    mean_val = float(row[2]) if row[2] is not None else None
    return min_val, max_val, mean_val


def get_value_frequencies(
    engine: Engine,
    table_name: str | tuple[str | None, str],
    column_name: str,
    limit: int = 20,
) -> dict[str, int]:
    """Get value frequency counts for low-cardinality columns."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT {_quote_ident(column_name)}, COUNT(*) as cnt FROM {table_ref} "
        f"WHERE {_quote_ident(column_name)} IS NOT NULL "
        f"GROUP BY {_quote_ident(column_name)} ORDER BY cnt DESC LIMIT :limit"
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": limit}).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def detect_distribution_shape(
    frequencies: dict[str, int],
    unique_count: int,
    row_count: int,
) -> str:
    """Detect distribution shape from value frequencies.

    Returns one of: categorical, sparse, uniform, skewed, normal.
    """
    if row_count == 0:
        return "empty"

    ratio = unique_count / row_count if row_count > 0 else 0

    # Categorical: low cardinality relative to row count
    if unique_count <= 20 or ratio < 0.05:
        return "categorical"

    # Sparse: very high cardinality (nearly unique per row)
    if ratio > 0.9:
        return "sparse"

    if not frequencies:
        return "unknown"

    counts = list(frequencies.values())
    if len(counts) < 2:
        return "sparse"

    # Check uniformity: are all counts roughly equal?
    mean_count = sum(counts) / len(counts)
    if mean_count > 0:
        cv = (sum((c - mean_count) ** 2 for c in counts) / len(counts)) ** 0.5 / mean_count
        if cv < 0.3:
            return "uniform"

    # Check skewness: is the top value much more frequent?
    max_count = max(counts)
    if max_count > 3 * mean_count:
        return "skewed"

    return "normal"


def profile_column(
    engine: Engine,
    table_name: str | tuple[str | None, str],
    column_name: str,
    column_type: str,
    row_count: int,
    unique_count: int,
) -> ColumnProfile:
    """Build a full ColumnProfile for a column."""
    null_count = count_nulls(engine, table_name, column_name)
    null_rate = null_count / row_count if row_count > 0 else 0.0

    min_val = None
    max_val = None
    mean_val = None
    if is_numeric(column_type) and row_count > 0:
        min_val, max_val, mean_val = get_numeric_stats(engine, table_name, column_name)

    # Value frequencies for categorical/low-cardinality columns
    frequencies: dict[str, int] = {}
    if unique_count is not None and unique_count <= 50 and row_count > 0:
        frequencies = get_value_frequencies(engine, table_name, column_name)

    shape = detect_distribution_shape(frequencies, unique_count or 0, row_count)

    return ColumnProfile(
        min_value=min_val,
        max_value=max_val,
        mean_value=mean_val,
        null_count=null_count,
        null_rate=round(null_rate, 4),
        distribution_shape=shape,
        value_frequencies=frequencies,
    )


def is_text_type(col_type: str) -> bool:
    """Check if a column type is text-like and should be sampled."""
    text_types = {"VARCHAR", "TEXT", "CHAR", "NVARCHAR", "NCHAR", "STRING", "CLOB"}
    upper = col_type.upper()
    return any(t in upper for t in text_types)
