"""Entropy-based join discovery using information theory.

Identifies hidden relationships that FK analysis and statistical matching
miss. Computes Shannon entropy H(X), conditional entropy H(A|B), and
mutual information I(A;B) = H(A) - H(A|B).

Gating controls (Section 3.4):
- Only compare columns within compatible semantic type families.
- Cheap prefilter: skip pairs where cardinality ratio exceeds 100:1.
- Use sampled values, not exhaustive scans.
- Computational budget cap.
- Composite scoring (MI + overlap_ratio + type compatibility).
- All latent joins require downstream join viability validation.
- FK conflicts: FK wins, conflict logged.

Spec reference: Section 3.4
"""

from __future__ import annotations

import math
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from mira.forge_claude.introspector.manifest import (
    ConfidenceScore,
    LatentJoin,
    LatentRelationships,
    SchemaManifest,
    SemanticMap,
)
from mira.forge_claude.introspector.samplers import _quote_ident, _render_table_ref
from mira.forge_claude.question_gen.patterns import is_date, is_numeric, is_text


# ---------------------------------------------------------------------------
# Semantic type compatibility
# ---------------------------------------------------------------------------

# Groups of compatible semantic types for comparison
_COMPATIBLE_FAMILIES = [
    {"identifier", "code", "category", "descriptor", "unknown"},
    {"metric", "measurement", "financial"},
    {"temporal"},
    {"geospatial"},
    {"text_content", "contact", "reference"},
]


def _are_types_compatible(sem_type_a: str, sem_type_b: str) -> bool:
    """Check if two semantic types belong to the same family."""
    for family in _COMPATIBLE_FAMILIES:
        if sem_type_a in family and sem_type_b in family:
            return True
    # If both are unknown, allow comparison
    if sem_type_a == "unknown" or sem_type_b == "unknown":
        return True
    return False


def _get_sql_type_family(col_type: str) -> str:
    """Broad SQL type family for compatibility check."""
    if is_numeric(col_type):
        return "numeric"
    if is_date(col_type):
        return "temporal"
    if is_text(col_type):
        return "text"
    return "other"


# ---------------------------------------------------------------------------
# Entropy computation
# ---------------------------------------------------------------------------

def _sample_column(
    engine: Engine,
    table_name: str,
    column_name: str,
    limit: int = 500,
) -> list[str]:
    """Sample non-null values from a column."""
    table_ref = _render_table_ref(table_name)
    query = text(
        f"SELECT {_quote_ident(column_name)} FROM {table_ref} "
        f"WHERE {_quote_ident(column_name)} IS NOT NULL LIMIT :limit"
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": limit}).fetchall()
    return [str(row[0]) for row in rows]


def shannon_entropy(values: list[str]) -> float:
    """Compute Shannon entropy H(X) of a value list."""
    if not values:
        return 0.0
    n = len(values)
    counts = Counter(values)
    entropy = 0.0
    for count in counts.values():
        p = count / n
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def conditional_entropy(values_a: list[str], values_b: list[str]) -> float:
    """Compute conditional entropy H(A|B).

    H(A|B) = sum_b P(b) * H(A | B=b)
    """
    if not values_a or not values_b or len(values_a) != len(values_b):
        return 0.0

    n = len(values_a)

    # Group A values by B value
    groups: dict[str, list[str]] = {}
    for a, b in zip(values_a, values_b):
        groups.setdefault(b, []).append(a)

    cond_h = 0.0
    for b_val, a_vals in groups.items():
        p_b = len(a_vals) / n
        h_a_given_b = shannon_entropy(a_vals)
        cond_h += p_b * h_a_given_b

    return cond_h


def mutual_information(values_a: list[str], values_b: list[str]) -> float:
    """Compute mutual information I(A;B) = H(A) - H(A|B)."""
    h_a = shannon_entropy(values_a)
    h_a_given_b = conditional_entropy(values_a, values_b)
    return max(0.0, h_a - h_a_given_b)


def _value_overlap(values_a: list[str], values_b: list[str]) -> float:
    """Compute overlap ratio between two value sets."""
    set_a = set(values_a)
    set_b = set(values_b)
    if not set_a or not set_b:
        return 0.0
    shared = set_a & set_b
    return len(shared) / min(len(set_a), len(set_b))


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def _composite_score(
    mi: float,
    overlap: float,
    type_compatible: bool,
    h_a: float,
) -> float:
    """Compute composite score from MI, overlap, and type compatibility.

    Normalized MI = MI / H(A) when H(A) > 0, capped at 1.0.
    Score = 0.5 * normalized_MI + 0.3 * overlap + 0.2 * type_compat
    """
    norm_mi = min(mi / h_a, 1.0) if h_a > 0 else 0.0
    type_bonus = 1.0 if type_compatible else 0.0
    return 0.5 * norm_mi + 0.3 * overlap + 0.2 * type_bonus


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def discover_latent_relationships(
    manifest: SchemaManifest,
    engine: Engine,
    semantic_map: SemanticMap | None = None,
    sample_size: int = 500,
    min_composite_score: float = 0.4,
    budget_max_pairs: int | None = None,
    progress_callback: Callable[[str, float], None] | None = None,
) -> LatentRelationships:
    """Discover latent joins via entropy analysis.

    Args:
        manifest: Schema manifest with table/column info.
        engine: SQLAlchemy engine for sampling.
        semantic_map: Optional semantic map for type compatibility filtering.
        sample_size: Max rows to sample per column.
        min_composite_score: Minimum composite score to include a join.
        budget_max_pairs: Max pairs to evaluate (None = no limit).

    Returns:
        LatentRelationships with discovered joins and evaluation stats.
    """
    # Build semantic type lookup
    sem_lookup: dict[tuple[str, str], str] = {}
    if semantic_map:
        for field in semantic_map.fields:
            sem_lookup[(field.table, field.column)] = field.semantic_type

    # Build set of known FK pairs to skip
    known_fk_pairs: set[tuple[str, str, str, str]] = set()
    for table in manifest.tables:
        for fk in table.foreign_keys:
            known_fk_pairs.add((table.name, fk.column, fk.references_table, fk.references_column))
            known_fk_pairs.add((fk.references_table, fk.references_column, table.name, fk.column))

    # Collect candidate columns (non-PK, non-FK source columns)
    candidates: list[tuple[str, str, str, int]] = []  # (table, col, type, unique_count)
    for table in manifest.tables:
        for col in table.columns:
            if col.primary_key:
                continue
            if col.unique_count and col.unique_count > 1:
                candidates.append((table.name, col.name, col.type, col.unique_count))

    max_workers = max(1, min(len(candidates), int(os.environ.get("FORGE_ENTROPY_WORKERS", "8"))))
    sampled_values: dict[tuple[str, str], list[str]] = {}
    if candidates:
        if max_workers == 1:
            for tbl, col, _, _ in candidates:
                sampled_values[(tbl, col)] = _sample_column(engine, tbl, col, sample_size)
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="forge-entropy") as executor:
                futures = {
                    executor.submit(_sample_column, engine, tbl, col, sample_size): (tbl, col)
                    for tbl, col, _, _ in candidates
                }
                completed = 0
                total = max(len(futures), 1)
                for future in as_completed(futures):
                    tbl, col = futures[future]
                    sampled_values[(tbl, col)] = future.result()
                    completed += 1
                    if progress_callback:
                        progress_callback(
                            f"Entropy sampling {completed}/{total}: {tbl}.{col}",
                            25.0 * (completed / total),
                        )

    joins: list[LatentJoin] = []
    pairs_evaluated = 0
    pairs_skipped = 0
    budget_exceeded = False
    total_pairs = max((len(candidates) * (len(candidates) - 1)) // 2, 1)

    for i, (tbl_a, col_a, type_a, uc_a) in enumerate(candidates):
        if budget_exceeded:
            break
        for j, (tbl_b, col_b, type_b, uc_b) in enumerate(candidates):
            if i >= j:
                continue
            if tbl_a == tbl_b:
                continue

            # Gating: cardinality ratio
            if uc_a and uc_b and max(uc_a, uc_b) / min(uc_a, uc_b) > 100:
                pairs_skipped += 1
                continue

            # Gating: SQL type family compatibility
            if _get_sql_type_family(type_a) != _get_sql_type_family(type_b):
                pairs_skipped += 1
                continue

            # Gating: semantic type compatibility
            sem_a = sem_lookup.get((tbl_a, col_a), "unknown")
            sem_b = sem_lookup.get((tbl_b, col_b), "unknown")
            type_compat = _are_types_compatible(sem_a, sem_b)
            if not type_compat and sem_a != "unknown" and sem_b != "unknown":
                pairs_skipped += 1
                continue

            # Budget check
            if budget_max_pairs and pairs_evaluated >= budget_max_pairs:
                budget_exceeded = True
                break

            pairs_evaluated += 1

            # Skip known FK pairs
            if (tbl_a, col_a, tbl_b, col_b) in known_fk_pairs:
                continue

            # Sample values
            vals_a = sampled_values.get((tbl_a, col_a), [])
            vals_b = sampled_values.get((tbl_b, col_b), [])

            if not vals_a or not vals_b:
                continue

            # Align samples to same length for conditional entropy
            min_len = min(len(vals_a), len(vals_b))
            aligned_a = vals_a[:min_len]
            aligned_b = vals_b[:min_len]

            # Compute entropy metrics
            h_a = shannon_entropy(aligned_a)
            h_b = shannon_entropy(aligned_b)
            h_a_given_b = conditional_entropy(aligned_a, aligned_b)
            mi = max(0.0, h_a - h_a_given_b)
            overlap = _value_overlap(vals_a, vals_b)

            score = _composite_score(mi, overlap, type_compat, h_a)

            if progress_callback and pairs_evaluated % 500 == 0:
                progress_callback(
                    f"Entropy comparison {pairs_evaluated}/{total_pairs}",
                    25.0 + (75.0 * min(pairs_evaluated / total_pairs, 1.0)),
                )

            if score < min_composite_score:
                continue

            # Check for FK conflict
            conflict = (tbl_a, col_a, tbl_b, col_b) in known_fk_pairs

            joins.append(LatentJoin(
                from_table=tbl_a,
                from_column=col_a,
                to_table=tbl_b,
                to_column=col_b,
                mutual_information=round(mi, 4),
                entropy_a=round(h_a, 4),
                entropy_b=round(h_b, 4),
                conditional_entropy=round(h_a_given_b, 4),
                overlap_ratio=round(overlap, 4),
                composite_score=round(score, 4),
                status="candidate",
                conflict_with_fk=conflict,
                confidence=ConfidenceScore(
                    score=round(score, 2),
                    source="entropy_discovery",
                    method="mutual_information_composite",
                    inputs=[f"{tbl_a}.{col_a}", f"{tbl_b}.{col_b}"],
                    threshold=0.6,
                    action_if_below="candidate_only_not_promoted",
                ),
            ))
    return LatentRelationships(
        database_name=manifest.database_name,
        joins=joins,
        pairs_evaluated=pairs_evaluated,
        pairs_skipped=pairs_skipped,
        budget_exceeded=budget_exceeded,
    )
