"""Three-mechanism relationship discovery.

Mechanism 1: Explicit foreign keys (confidence 1.0).
Mechanism 2: Statistical key matching — overlapping value sets.
Mechanism 3: Join viability testing — sample query coverage.

Spec reference: Section 3.3
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from mira.forge_claude.introspector.manifest import (
    ConfidenceScore,
    DiscoveredRelationship,
    RelationshipGraph,
    SchemaManifest,
    TableInfo,
)
from mira.forge_claude.introspector.samplers import _quote_ident, _render_table_ref


# ---------------------------------------------------------------------------
# Mechanism 1: Explicit FK extraction
# ---------------------------------------------------------------------------

def discover_explicit_fks(manifest: SchemaManifest) -> list[DiscoveredRelationship]:
    """Extract relationships from declared foreign keys. Confidence 1.0."""
    rels = []
    for table in manifest.tables:
        for fk in table.foreign_keys:
            rels.append(DiscoveredRelationship(
                from_table=table.name,
                from_column=fk.column,
                to_table=fk.references_table,
                to_column=fk.references_column,
                mechanism="explicit_fk",
                confidence=ConfidenceScore(
                    score=1.0,
                    source="relationship_discovery",
                    method="explicit_foreign_key",
                    inputs=[f"{table.name}.{fk.column}"],
                    threshold=0.7,
                    action_if_below="n/a",
                ),
            ))
    return rels


# ---------------------------------------------------------------------------
# Mechanism 2: Statistical key matching
# ---------------------------------------------------------------------------

def _get_distinct_values(
    engine: Engine,
    table_name: str,
    column_name: str,
    limit: int = 500,
) -> set[str]:
    """Get a set of distinct non-null values from a column."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT DISTINCT {_quote_ident(column_name)} FROM {table_ref} "
        f"WHERE {_quote_ident(column_name)} IS NOT NULL LIMIT :limit"
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": limit}).fetchall()
    return {str(row[0]) for row in rows}


def discover_statistical_matches(
    manifest: SchemaManifest,
    engine: Engine,
    overlap_threshold: float = 0.8,
    progress_callback: Callable[[str, float], None] | None = None,
) -> list[DiscoveredRelationship]:
    """Find columns across tables with overlapping value sets.

    overlap_ratio = shared_values / min(unique_a, unique_b).
    If ratio exceeds threshold, candidate relationship generated.
    """
    # Build set of known FK pairs to skip
    known_fk_pairs = set()
    for table in manifest.tables:
        for fk in table.foreign_keys:
            known_fk_pairs.add((table.name, fk.column, fk.references_table, fk.references_column))
            known_fk_pairs.add((fk.references_table, fk.references_column, table.name, fk.column))

    # Collect candidate columns: integer or text columns that could be join keys
    candidates: list[tuple[str, str, int | None]] = []
    for table in manifest.tables:
        for col in table.columns:
            if col.unique_count and col.unique_count > 1:
                candidates.append((table.name, col.name, col.unique_count))

    max_workers = max(1, min(len(candidates), int(os.environ.get("FORGE_RELATIONSHIP_WORKERS", "8"))))
    distinct_values: dict[tuple[str, str], set[str]] = {}
    if candidates:
        if max_workers == 1:
            for tbl, col, _ in candidates:
                distinct_values[(tbl, col)] = _get_distinct_values(engine, tbl, col, limit=200)
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="forge-relvals") as executor:
                futures = {
                    executor.submit(_get_distinct_values, engine, tbl, col, 200): (tbl, col)
                    for tbl, col, _ in candidates
                }
                completed = 0
                total = max(len(futures), 1)
                for future in as_completed(futures):
                    tbl, col = futures[future]
                    distinct_values[(tbl, col)] = future.result()
                    completed += 1
                    if progress_callback:
                        progress_callback(
                            f"Relationship sampling {completed}/{total}: {tbl}.{col}",
                            35.0 * (completed / total),
                        )

    rels = []
    seen = set()
    pair_count = 0
    total_pairs = max((len(candidates) * (len(candidates) - 1)) // 2, 1)

    for i, (tbl_a, col_a, uc_a) in enumerate(candidates):
        for j, (tbl_b, col_b, uc_b) in enumerate(candidates):
            if i >= j:
                continue
            if tbl_a == tbl_b:
                continue

            # Skip known FK pairs
            if (tbl_a, col_a, tbl_b, col_b) in known_fk_pairs:
                continue

            # Skip if cardinality ratio exceeds 100:1 (gating control)
            if uc_a and uc_b:
                ratio = max(uc_a, uc_b) / min(uc_a, uc_b)
                if ratio > 100:
                    continue

            pair_key = tuple(sorted([(tbl_a, col_a), (tbl_b, col_b)]))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            pair_count += 1

            # Compare value sets
            vals_a = distinct_values.get((tbl_a, col_a), set())
            vals_b = distinct_values.get((tbl_b, col_b), set())

            if not vals_a or not vals_b:
                continue

            shared = vals_a & vals_b
            overlap = len(shared) / min(len(vals_a), len(vals_b))

            if overlap >= overlap_threshold:
                rels.append(DiscoveredRelationship(
                    from_table=tbl_a,
                    from_column=col_a,
                    to_table=tbl_b,
                    to_column=col_b,
                    mechanism="statistical_match",
                    overlap_ratio=round(overlap, 4),
                    confidence=ConfidenceScore(
                        score=round(min(overlap, 0.95), 2),
                        source="relationship_discovery",
                        method="statistical_value_overlap",
                        inputs=[f"{tbl_a}.{col_a}", f"{tbl_b}.{col_b}"],
                        threshold=0.7,
                        action_if_below="require_join_viability_test",
                    ),
                ))
            if progress_callback and pair_count % 500 == 0:
                progress_callback(
                    f"Relationship comparison {pair_count}/{total_pairs}",
                    35.0 + (45.0 * min(pair_count / total_pairs, 1.0)),
                )

    return rels


# ---------------------------------------------------------------------------
# Mechanism 3: Join viability testing
# ---------------------------------------------------------------------------

def test_join_viability(
    engine: Engine,
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    coverage_threshold: float = 0.7,
) -> tuple[float, bool]:
    """Test if a candidate join actually produces meaningful results.

    coverage = joined_rows / from_table_rows
    Returns (coverage, passes_threshold).
    """
    from_table_ref = _render_table_ref(from_table)
    to_table_ref = _render_table_ref(to_table)

    # Count rows in from_table
    count_query = text(f"SELECT COUNT(*) FROM {from_table_ref}")
    with engine.connect() as conn:
        total = conn.execute(count_query).scalar() or 0

    if total == 0:
        return 0.0, False

    # Count rows that would join (cast both sides to text to handle type mismatches)
    join_query = text(
        f"SELECT COUNT(*) FROM {from_table_ref} a "
        f"INNER JOIN {to_table_ref} b ON CAST(a.{_quote_ident(from_column)} AS TEXT) = CAST(b.{_quote_ident(to_column)} AS TEXT)"
    )
    try:
        with engine.connect() as conn:
            joined = conn.execute(join_query).scalar() or 0
    except Exception:
        return 0.0, False

    coverage = joined / total
    return round(coverage, 4), coverage >= coverage_threshold


def discover_via_join_viability(
    engine: Engine,
    candidates: list[DiscoveredRelationship],
    coverage_threshold: float = 0.7,
    progress_callback: Callable[[str, float], None] | None = None,
) -> list[DiscoveredRelationship]:
    """Validate candidate relationships with actual join queries."""
    validated = []
    max_workers = max(1, min(len(candidates), int(os.environ.get("FORGE_RELATIONSHIP_WORKERS", "8"))))

    def validate(rel: DiscoveredRelationship) -> DiscoveredRelationship | None:
        coverage, passes = test_join_viability(
            engine, rel.from_table, rel.from_column,
            rel.to_table, rel.to_column, coverage_threshold,
        )
        if not passes:
            return None
        return DiscoveredRelationship(
            from_table=rel.from_table,
            from_column=rel.from_column,
            to_table=rel.to_table,
            to_column=rel.to_column,
            mechanism="join_viability",
            overlap_ratio=rel.overlap_ratio,
            join_coverage=coverage,
            confidence=ConfidenceScore(
                score=round(min(coverage, 0.95), 2),
                source="relationship_discovery",
                method="join_viability_test",
                inputs=[f"{rel.from_table}.{rel.from_column}",
                        f"{rel.to_table}.{rel.to_column}"],
                threshold=0.7,
                action_if_below="demote_to_candidate",
            ),
        )

    if max_workers == 1:
        for rel in candidates:
            maybe = validate(rel)
            if maybe is not None:
                validated.append(maybe)
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="forge-joinval") as executor:
            futures = {executor.submit(validate, rel): rel for rel in candidates}
            completed = 0
            total = max(len(futures), 1)
            for future in as_completed(futures):
                maybe = future.result()
                if maybe is not None:
                    validated.append(maybe)
                completed += 1
                if progress_callback and completed % 50 == 0:
                    progress_callback(
                        f"Join viability {completed}/{total}",
                        80.0 + (20.0 * (completed / total)),
                    )
    return validated


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_relationship_graph(
    manifest: SchemaManifest,
    engine: Engine,
    overlap_threshold: float = 0.8,
    coverage_threshold: float = 0.7,
    progress_callback: Callable[[str, float], None] | None = None,
) -> RelationshipGraph:
    """Run all three relationship discovery mechanisms.

    1. Explicit FKs (confidence 1.0)
    2. Statistical matching (overlap ratio)
    3. Join viability testing (validates statistical candidates)
    """
    explicit = discover_explicit_fks(manifest)
    if progress_callback:
        progress_callback("Extracted explicit foreign keys.", 10.0)
    statistical = discover_statistical_matches(
        manifest,
        engine,
        overlap_threshold,
        progress_callback=progress_callback,
    )
    if progress_callback:
        progress_callback("Running join viability tests.", 80.0)
    join_validated = discover_via_join_viability(
        engine,
        statistical,
        coverage_threshold,
        progress_callback=progress_callback,
    )

    return RelationshipGraph(
        database_name=manifest.database_name,
        explicit=explicit,
        statistical=statistical,
        join_viability=join_validated,
    )
