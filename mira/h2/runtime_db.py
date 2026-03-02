#!/usr/bin/env python3
"""
PostgreSQL runtime helpers for H2 temp-gated service.

This module is intentionally optional at runtime:
- If DB is unavailable, callers can fall back to JSON corpus behavior.
- If DB is available, callers can use it for material index, ratio stats,
  and coverage-gap persistence.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

try:
    import psycopg2
except Exception:  # pragma: no cover - optional dependency behavior
    psycopg2 = None  # type: ignore[assignment]

from mira.core.db_config import get_db_connection_params


_NO_DATA_MARKERS = (
    "no hydrogen compatibility data",
    "insufficient data",
    "data gap",
    "not listed",
    "not available",
    "treat compatibility as unknown",
)


def get_runtime_backend() -> str:
    """
    Runtime backend for H2 temp service.

    Values:
    - json  : file-based only
    - pg    : postgres-only (with JSON fallback if query returns nothing)
    - hybrid: postgres + JSON merge
    """
    return os.getenv("MIRA_H2_RUNTIME_BACKEND", "json").strip().lower()


def get_h2_schema() -> str:
    return os.getenv("MIRA_H2_SCHEMA", "h2_knowledge").strip()


def _env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_int(name: str) -> Optional[int]:
    value = _env(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _connect():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed for H2 PG runtime.")
    cfg = get_db_connection_params(
        host=_env("MIRA_H2_DB_HOST"),
        port=_env_int("MIRA_H2_DB_PORT"),
        database=_env("MIRA_H2_DB_NAME"),
        user=_env("MIRA_H2_DB_USER"),
        password=_env("MIRA_H2_DB_PASSWORD"),
    )
    return psycopg2.connect(**cfg)


@dataclass
class H2DbStats:
    schema: str
    materials: int
    property_records: int
    degradation_ratios: int
    training_pairs: int
    coverage_gaps: int
    citation_with_page: int
    citation_total: int

    @property
    def citation_ratio(self) -> float:
        if self.citation_total <= 0:
            return 0.0
        return float(self.citation_with_page) / float(self.citation_total)


def fetch_h2_db_stats(schema: Optional[str] = None) -> H2DbStats:
    schema = schema or get_h2_schema()
    sql = f"""
    SELECT
      (SELECT COUNT(*) FROM {schema}.materials) AS materials,
      (SELECT COUNT(*) FROM {schema}.property_records) AS property_records,
      (SELECT COUNT(*) FROM {schema}.degradation_ratios) AS degradation_ratios,
      (SELECT COUNT(*) FROM {schema}.training_pairs) AS training_pairs,
      (SELECT COUNT(*) FROM {schema}.coverage_gaps) AS coverage_gaps,
      (SELECT COALESCE(SUM(CASE WHEN citation_has_page THEN 1 ELSE 0 END), 0) FROM {schema}.training_pairs) AS citation_with_page,
      (SELECT COUNT(*) FROM {schema}.training_pairs) AS citation_total
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    finally:
        conn.close()

    return H2DbStats(
        schema=schema,
        materials=int(row[0] or 0),
        property_records=int(row[1] or 0),
        degradation_ratios=int(row[2] or 0),
        training_pairs=int(row[3] or 0),
        coverage_gaps=int(row[4] or 0),
        citation_with_page=int(row[5] or 0),
        citation_total=int(row[6] or 0),
    )


def evaluate_h2_db_readiness(
    stats: H2DbStats,
    min_materials: int = 3,
    min_training_pairs: int = 200,
    min_degradation_rows: int = 10,
    min_citation_ratio: float = 0.75,
) -> list[str]:
    issues: list[str] = []
    if stats.materials < min_materials:
        issues.append(f"materials<{min_materials} ({stats.materials})")
    if stats.training_pairs < min_training_pairs:
        issues.append(f"training_pairs<{min_training_pairs} ({stats.training_pairs})")
    if stats.degradation_ratios < min_degradation_rows:
        issues.append(f"degradation_ratios<{min_degradation_rows} ({stats.degradation_ratios})")
    if stats.citation_ratio < min_citation_ratio:
        issues.append(
            "citation_ratio<"
            f"{min_citation_ratio:.2f} ({stats.citation_with_page}/{stats.citation_total}={stats.citation_ratio:.3f})"
        )
    return issues


def fetch_material_names(schema: Optional[str] = None) -> list[str]:
    schema = schema or get_h2_schema()
    generic_values = ("", "general", "all", "unknown", "various", "multiple", "n/a", "na")

    sql = f"""
    WITH merged AS (
      SELECT TRIM(common_name) AS material
      FROM {schema}.materials
      WHERE common_name IS NOT NULL
      UNION
      SELECT TRIM(material) AS material
      FROM {schema}.degradation_ratios
      WHERE material IS NOT NULL
      UNION
      SELECT TRIM(material) AS material
      FROM {schema}.training_pairs
      WHERE material IS NOT NULL
        AND answer IS NOT NULL
        AND LOWER(answer) NOT LIKE ANY (%s)
    )
    SELECT DISTINCT material
    FROM merged
    WHERE material IS NOT NULL
      AND material <> ''
      AND LOWER(material) <> ALL (%s)
    ORDER BY material
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            like_markers = [f"%{marker}%" for marker in _NO_DATA_MARKERS]
            cur.execute(sql, (like_markers, list(generic_values)))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [str(r[0]).strip() for r in rows if r and str(r[0]).strip()]


def fetch_ratio_stats(schema: Optional[str] = None) -> dict[str, tuple[float, float, int]]:
    schema = schema or get_h2_schema()
    sql = f"""
    SELECT
      TRIM(material) AS material,
      MIN(ratio_h2_over_ref) AS min_ratio,
      MAX(ratio_h2_over_ref) AS max_ratio,
      COUNT(*) AS n
    FROM {schema}.degradation_ratios
    WHERE material IS NOT NULL
      AND TRIM(material) <> ''
      AND ratio_h2_over_ref IS NOT NULL
    GROUP BY TRIM(material)
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    out: dict[str, tuple[float, float, int]] = {}
    for material, min_ratio, max_ratio, n in rows:
        if material is None:
            continue
        out[str(material)] = (float(min_ratio), float(max_ratio), int(n))
    return out


def ensure_condition_alias_table(schema: Optional[str] = None) -> None:
    """Create condition-alias cache table if missing."""
    schema = schema or get_h2_schema()
    sql = f"""
    CREATE TABLE IF NOT EXISTS {schema}.condition_aliases (
      raw_key TEXT PRIMARY KEY,
      raw_text TEXT NOT NULL,
      canonical_condition TEXT NOT NULL,
      display_label TEXT NOT NULL,
      is_condition BOOLEAN NOT NULL DEFAULT TRUE,
      confidence NUMERIC,
      resolver_provider TEXT,
      resolver_model TEXT,
      source_document TEXT,
      material_name TEXT,
      details_jsonb JSONB DEFAULT '{{}}'::jsonb,
      human_verified BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


def fetch_condition_alias(raw_key: str, schema: Optional[str] = None) -> Optional[dict]:
    schema = schema or get_h2_schema()
    sql = f"""
    SELECT
      raw_key,
      raw_text,
      canonical_condition,
      display_label,
      is_condition,
      confidence,
      resolver_provider,
      resolver_model,
      source_document,
      material_name,
      details_jsonb,
      human_verified
    FROM {schema}.condition_aliases
    WHERE raw_key = %s
    LIMIT 1
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (raw_key,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "raw_key": row[0],
        "raw_text": row[1],
        "canonical_condition": row[2],
        "display_label": row[3],
        "is_condition": bool(row[4]),
        "confidence": float(row[5]) if row[5] is not None else None,
        "resolver_provider": row[6],
        "resolver_model": row[7],
        "source_document": row[8],
        "material_name": row[9],
        "details_jsonb": row[10] or {},
        "human_verified": bool(row[11]),
    }


def upsert_condition_alias(
    *,
    raw_key: str,
    raw_text: str,
    canonical_condition: str,
    display_label: str,
    is_condition: bool,
    confidence: Optional[float],
    resolver_provider: Optional[str],
    resolver_model: Optional[str],
    source_document: Optional[str],
    material_name: Optional[str],
    details_jsonb: Optional[dict] = None,
    schema: Optional[str] = None,
) -> None:
    schema = schema or get_h2_schema()
    sql = f"""
    INSERT INTO {schema}.condition_aliases(
      raw_key, raw_text, canonical_condition, display_label, is_condition,
      confidence, resolver_provider, resolver_model, source_document,
      material_name, details_jsonb, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
    ON CONFLICT (raw_key) DO UPDATE SET
      canonical_condition = EXCLUDED.canonical_condition,
      display_label = EXCLUDED.display_label,
      is_condition = EXCLUDED.is_condition,
      confidence = EXCLUDED.confidence,
      resolver_provider = EXCLUDED.resolver_provider,
      resolver_model = EXCLUDED.resolver_model,
      source_document = COALESCE(EXCLUDED.source_document, {schema}.condition_aliases.source_document),
      material_name = COALESCE(EXCLUDED.material_name, {schema}.condition_aliases.material_name),
      details_jsonb = EXCLUDED.details_jsonb,
      updated_at = NOW()
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    raw_key,
                    raw_text,
                    canonical_condition,
                    display_label,
                    bool(is_condition),
                    confidence,
                    resolver_provider,
                    resolver_model,
                    source_document,
                    material_name,
                    json.dumps(details_jsonb or {}),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def list_condition_aliases(
    *,
    material_name: Optional[str] = None,
    unresolved_only: bool = True,
    limit: int = 100,
    schema: Optional[str] = None,
) -> list[dict]:
    """List cached condition alias mappings for review/approval."""
    schema = schema or get_h2_schema()
    ensure_condition_alias_table(schema)

    where_clauses = ["1=1"]
    params: list[object] = []

    material = (material_name or "").strip()
    if material:
        where_clauses.append("COALESCE(material_name, '') ILIKE %s")
        params.append(f"%{material}%")

    if unresolved_only:
        where_clauses.append(
            "("
            "NOT human_verified OR "
            "display_label = 'Generic/Unknown' OR "
            "COALESCE(confidence, 0) < 0.75 OR "
            "COALESCE((details_jsonb->>'needs_review')::boolean, FALSE)"
            ")"
        )

    sql = f"""
    SELECT
      raw_key,
      raw_text,
      canonical_condition,
      display_label,
      is_condition,
      confidence,
      resolver_provider,
      resolver_model,
      source_document,
      material_name,
      details_jsonb,
      human_verified,
      created_at,
      updated_at
    FROM {schema}.condition_aliases
    WHERE {" AND ".join(where_clauses)}
    ORDER BY
      human_verified ASC,
      COALESCE(confidence, 0) ASC,
      updated_at DESC
    LIMIT %s
    """
    params.append(max(1, min(int(limit), 500)))

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "raw_key": row[0],
                "raw_text": row[1],
                "canonical_condition": row[2],
                "display_label": row[3],
                "is_condition": bool(row[4]),
                "confidence": float(row[5]) if row[5] is not None else None,
                "resolver_provider": row[6],
                "resolver_model": row[7],
                "source_document": row[8],
                "material_name": row[9],
                "details_jsonb": row[10] or {},
                "human_verified": bool(row[11]),
                "created_at": row[12].isoformat() if row[12] is not None else None,
                "updated_at": row[13].isoformat() if row[13] is not None else None,
            }
        )
    return out


def verify_condition_alias(
    *,
    raw_key: str,
    display_label: str,
    canonical_condition: Optional[str] = None,
    is_condition: bool = True,
    raw_text: Optional[str] = None,
    source_document: Optional[str] = None,
    material_name: Optional[str] = None,
    schema: Optional[str] = None,
) -> Optional[dict]:
    """Mark a condition alias row as human-verified (insert/update)."""
    schema = schema or get_h2_schema()
    ensure_condition_alias_table(schema)

    norm_key = (raw_key or "").strip()
    if not norm_key:
        raise ValueError("raw_key is required")
    label = (display_label or "").strip()
    if not label:
        raise ValueError("display_label is required")

    canonical = (canonical_condition or "").strip() or label
    raw_value = (raw_text or "").strip() or label
    details = {"needs_review": False, "human_verified_by": "api"}

    sql = f"""
    INSERT INTO {schema}.condition_aliases(
      raw_key,
      raw_text,
      canonical_condition,
      display_label,
      is_condition,
      confidence,
      resolver_provider,
      resolver_model,
      source_document,
      material_name,
      details_jsonb,
      human_verified,
      created_at,
      updated_at
    ) VALUES (
      %s, %s, %s, %s, %s, 1.0, 'human', 'human-verified',
      %s, %s, %s::jsonb, TRUE, NOW(), NOW()
    )
    ON CONFLICT (raw_key) DO UPDATE SET
      raw_text = EXCLUDED.raw_text,
      canonical_condition = EXCLUDED.canonical_condition,
      display_label = EXCLUDED.display_label,
      is_condition = EXCLUDED.is_condition,
      confidence = 1.0,
      resolver_provider = 'human',
      resolver_model = 'human-verified',
      source_document = COALESCE(EXCLUDED.source_document, {schema}.condition_aliases.source_document),
      material_name = COALESCE(EXCLUDED.material_name, {schema}.condition_aliases.material_name),
      details_jsonb = COALESCE({schema}.condition_aliases.details_jsonb, '{{}}'::jsonb) || EXCLUDED.details_jsonb,
      human_verified = TRUE,
      updated_at = NOW()
    """

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    norm_key,
                    raw_value,
                    canonical,
                    label,
                    bool(is_condition),
                    source_document,
                    material_name,
                    json.dumps(details),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return fetch_condition_alias(norm_key, schema=schema)


def insert_coverage_gap(
    material: str,
    question: str,
    model: str,
    event: str = "material_not_in_evidence_index",
    schema: Optional[str] = None,
    timestamp_utc: Optional[str] = None,
) -> None:
    schema = schema or get_h2_schema()
    ts = timestamp_utc or datetime.utcnow().isoformat()
    sql = f"""
    INSERT INTO {schema}.coverage_gaps(
      timestamp_utc, material, question, model, event, context_jsonb, source_file
    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
    ON CONFLICT (timestamp_utc, material, question, model, event) DO NOTHING
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ts,
                    material.strip(),
                    question.strip(),
                    model.strip(),
                    event.strip(),
                    "{}",
                    "runtime:h2_temp_gate",
                ),
            )
        conn.commit()
    finally:
        conn.close()
