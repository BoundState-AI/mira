#!/usr/bin/env python3
"""
Deterministic adapter for H2 BoK evidence in BSMH.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _dedupe_bok_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = f"{row.get('doc_id') or ''}|{row.get('source') or ''}|{row.get('section') or ''}|{row.get('page') or ''}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _normalize_bok_row(row: Dict[str, Any]) -> Dict[str, Any]:
    text = str(row.get("text") or "").strip()
    excerpt = text[:320] + ("..." if len(text) > 320 else "")
    return {
        "doc_id": row.get("doc_id"),
        "source": row.get("source"),
        "section": row.get("section"),
        "title": row.get("title"),
        "page": row.get("page"),
        "relevance_score": round(_safe_float(row.get("relevance_score"), 0.0), 4),
        "excerpt": excerpt,
    }


def fetch_h2_bok_evidence(
    *,
    query: str,
    requested_materials: List[str],
    k_per_query: int = 3,
    max_total: int = 8,
) -> Tuple[List[Dict[str, Any]], str | None]:
    """
    Fetch H2 BoK evidence rows for a hydrogen-context query.

    Returns:
        (evidence_rows, error_message)
    """
    try:
        from mira.h2 import get_h2_engine
    except Exception as exc:
        return [], f"H2 engine import failed: {exc}"

    engine = get_h2_engine()
    if engine is None:
        return [], "H2 engine unavailable."
    if not hasattr(engine, "search_h2_bok"):
        return [], "H2 engine does not expose search_h2_bok."

    queries: List[str] = [query]
    for material in requested_materials:
        mat = str(material).strip()
        if not mat:
            continue
        queries.append(f"{mat} hydrogen compatibility")
        queries.append(f"{mat} hydrogen embrittlement cryogenic service")

    gathered: List[Dict[str, Any]] = []
    for q in queries:
        try:
            rows = engine.search_h2_bok(q, k=k_per_query)  # type: ignore[attr-defined]
        except Exception:
            rows = []
        for row in rows or []:
            gathered.append(_normalize_bok_row(row))

    ranked = sorted(
        _dedupe_bok_rows(gathered),
        key=lambda r: r.get("relevance_score", 0.0),
        reverse=True,
    )
    return ranked[:max_total], None

