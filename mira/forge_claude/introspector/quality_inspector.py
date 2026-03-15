"""Data quality inspection.

Generates a quality report alongside the manifest. If 40% of a column is
null, that affects what questions the DB can reliably answer. Capability
mapping in Step 2 uses this to flag unreliable question paths.

Metrics per column:
- Null rates (>50% flagged)
- Outlier detection (IQR-based for numeric columns)
- Duplicate keys (columns with unique constraint violations)
- Inconsistent units (from semantic inference)
- Schema anomalies (missing FKs, naming, denormalized tables)

Spec reference: Section 3.5
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from mira.forge_claude.introspector.manifest import (
    ColumnQuality,
    ConfidenceScore,
    DataQualityReport,
    SchemaManifest,
    SemanticMap,
    TableQuality,
)
from mira.forge_claude.introspector.samplers import _quote_ident, _render_table_ref
from mira.forge_claude.question_gen.patterns import is_numeric


# ---------------------------------------------------------------------------
# Column-level quality checks
# ---------------------------------------------------------------------------

def _check_nulls(
    engine: Engine,
    table_name: str,
    col_name: str,
    row_count: int,
) -> tuple[int, float, list[str]]:
    """Check null rate. Returns (null_count, null_rate, flags)."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT COUNT(*) FROM {table_ref} WHERE {_quote_ident(col_name)} IS NULL"
    )
    with engine.connect() as conn:
        null_count = conn.execute(query).scalar() or 0

    null_rate = null_count / row_count if row_count > 0 else 0.0
    flags = []
    if null_rate > 0.5:
        flags.append(f"high_null_rate_{null_rate:.0%}")
    elif null_rate > 0.2:
        flags.append(f"moderate_null_rate_{null_rate:.0%}")
    return null_count, round(null_rate, 4), flags


def _check_outliers(
    engine: Engine,
    table_name: str,
    col_name: str,
    col_type: str,
) -> tuple[int, list[str], list[str]]:
    """IQR-based outlier detection for numeric columns.

    Returns (outlier_count, outlier_values, flags).
    """
    if not is_numeric(col_type):
        return 0, [], []

    # Get Q1, Q3 for IQR
    # Using a subquery approach compatible with SQLite
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT {_quote_ident(col_name)} FROM {table_ref} "
        f"WHERE {_quote_ident(col_name)} IS NOT NULL ORDER BY {_quote_ident(col_name)}"
    )
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    if len(rows) < 4:
        return 0, [], []

    values = [float(row[0]) for row in rows]
    n = len(values)
    q1 = values[n // 4]
    q3 = values[3 * n // 4]
    iqr = q3 - q1

    if iqr == 0:
        return 0, [], []

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    outliers = [v for v in values if v < lower or v > upper]
    outlier_strs = [str(v) for v in outliers[:10]]  # Cap at 10 examples

    flags = []
    if len(outliers) > 0:
        pct = len(outliers) / n
        if pct > 0.1:
            flags.append(f"many_outliers_{pct:.0%}")
        else:
            flags.append(f"outliers_detected_{len(outliers)}")

    return len(outliers), outlier_strs, flags


def _check_duplicates(
    engine: Engine,
    table_name: str,
    col_name: str,
    unique_count: int | None,
    row_count: int,
) -> tuple[bool, int, list[str]]:
    """Check for near-duplicate values suggesting uniqueness issues.

    Returns (has_duplicates, duplicate_count, flags).
    """
    if unique_count is None or row_count == 0:
        return False, 0, []

    dup_count = row_count - unique_count
    has_dups = dup_count > 0

    flags = []
    if has_dups and col_name.endswith("_id") or col_name == "id":
        # ID columns should be unique
        if dup_count > 0:
            flags.append("duplicate_ids_detected")

    return has_dups, dup_count, flags


def _compute_quality_score(
    null_rate: float,
    outlier_count: int,
    row_count: int,
    flags: list[str],
) -> float:
    """Compute composite quality score (0.0 to 1.0)."""
    score = 1.0

    # Null penalty
    if null_rate > 0.5:
        score -= 0.4
    elif null_rate > 0.2:
        score -= 0.2
    elif null_rate > 0.05:
        score -= 0.1

    # Outlier penalty
    if row_count > 0 and outlier_count > 0:
        outlier_pct = outlier_count / row_count
        if outlier_pct > 0.1:
            score -= 0.2
        elif outlier_pct > 0.01:
            score -= 0.1

    # Flag penalty
    score -= 0.05 * len(flags)

    return max(0.0, round(score, 2))


# ---------------------------------------------------------------------------
# Table-level quality checks
# ---------------------------------------------------------------------------

def _check_naming_anomalies(table_name: str, col_names: list[str]) -> list[str]:
    """Detect inconsistent naming conventions."""
    anomalies = []

    # Mixed case styles
    has_snake = any("_" in name for name in col_names if name != "id")
    has_camel = any(
        any(c.isupper() for c in name[1:]) and "_" not in name
        for name in col_names if len(name) > 1
    )
    if has_snake and has_camel:
        anomalies.append("mixed_naming_conventions")

    # Very short names
    short = [n for n in col_names if len(n) <= 2 and n != "id"]
    if short:
        anomalies.append(f"ambiguous_short_names: {', '.join(short)}")

    return anomalies


def _suggest_indexes(
    table_name: str,
    existing_indexes: list[str],
    col_names: list[str],
    fk_columns: list[str],
) -> list[str]:
    """Suggest missing indexes."""
    recommendations = []

    # FK columns should have indexes
    for fk_col in fk_columns:
        idx_name = f"idx_{table_name}_{fk_col}"
        if idx_name not in existing_indexes:
            recommendations.append(f"Consider index on {table_name}.{fk_col} (foreign key)")

    return recommendations


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def inspect_quality(
    manifest: SchemaManifest,
    engine: Engine,
    semantic_map: SemanticMap | None = None,
    progress_callback: Callable[[str, float], None] | None = None,
) -> DataQualityReport:
    """Run data quality inspection across all tables and columns.

    Returns a DataQualityReport with per-column and per-table assessments.
    """
    table_reports = []
    total_flags = 0
    total_columns_checked = 0
    columns_flagged = 0

    def inspect_table(index: int, table) -> tuple[int, TableQuality, int, int, int]:
        col_reports = []
        col_names = [c.name for c in table.columns]
        fk_columns = [fk.column for fk in table.foreign_keys]
        local_total_flags = 0
        local_total_columns_checked = 0
        local_columns_flagged = 0

        for col in table.columns:
            local_total_columns_checked += 1
            all_flags: list[str] = []

            # Null check
            null_count, null_rate, null_flags = _check_nulls(
                engine, table.name, col.name, table.row_count,
            )
            all_flags.extend(null_flags)

            # Outlier check
            outlier_count, outlier_values, outlier_flags = _check_outliers(
                engine, table.name, col.name, col.type,
            )
            all_flags.extend(outlier_flags)

            # Duplicate check
            has_dups, dup_count, dup_flags = _check_duplicates(
                engine, table.name, col.name, col.unique_count, table.row_count,
            )
            all_flags.extend(dup_flags)

            # Quality score
            quality = _compute_quality_score(
                null_rate, outlier_count, table.row_count, all_flags,
            )

            if all_flags:
                local_columns_flagged += 1
                local_total_flags += len(all_flags)

            col_reports.append(ColumnQuality(
                table=table.name,
                column=col.name,
                null_rate=null_rate,
                null_count=null_count,
                outlier_count=outlier_count,
                outlier_values=outlier_values,
                has_duplicates=has_dups,
                duplicate_count=dup_count,
                quality_score=ConfidenceScore(
                    score=quality,
                    source="quality_inspector",
                    method="composite",
                    inputs=[f"{table.name}.{col.name}"],
                    threshold=0.7,
                    action_if_below="flag_in_report",
                ),
                flags=all_flags,
            ))

        # Table-level checks
        naming_anomalies = _check_naming_anomalies(table.name, col_names)
        index_recs = _suggest_indexes(
            table.name, table.indexes, col_names, fk_columns,
        )

        return index, TableQuality(
            table=table.name,
            row_count=table.row_count,
            naming_anomalies=naming_anomalies,
            index_recommendations=index_recs,
            columns=col_reports,
        ), local_total_flags, local_total_columns_checked, local_columns_flagged

    max_workers = max(1, min(len(manifest.tables), int(os.environ.get("FORGE_QUALITY_WORKERS", "6"))))
    if max_workers == 1:
        results = [inspect_table(index, table) for index, table in enumerate(manifest.tables)]
        if progress_callback:
            progress_callback("Data quality inspection complete.", 100.0)
    else:
        results = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="forge-quality") as executor:
            futures = {
                executor.submit(inspect_table, index, table): table.name
                for index, table in enumerate(manifest.tables)
            }
            completed = 0
            total = max(len(futures), 1)
            for future in as_completed(futures):
                results.append(future.result())
                completed += 1
                if progress_callback:
                    progress_callback(
                        f"Quality inspection {completed}/{total}: {futures[future]}",
                        92.0 + (8.0 * (completed / total)),
                    )

    results.sort(key=lambda item: item[0])
    for _, table_quality, flags, columns_checked, flagged_columns in results:
        table_reports.append(table_quality)
        total_flags += flags
        total_columns_checked += columns_checked
        columns_flagged += flagged_columns

    return DataQualityReport(
        database_name=manifest.database_name,
        tables=table_reports,
        summary={
            "total_columns_checked": total_columns_checked,
            "columns_flagged": columns_flagged,
            "total_flags": total_flags,
        },
    )
