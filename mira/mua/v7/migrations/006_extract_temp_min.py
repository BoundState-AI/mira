"""
MUA Precedents v7 - temp_min_f Backfill
=======================================

Backfills ``temp_min_f`` for v7 precedents without re-extraction.

Strategy (in order):
1. Join by filename to ``bok.mua_normalized.temp_f_min`` (deterministic).
2. Regex extraction from existing text fields (rationale/env_raw_text/application).

Usage
-----
Dry-run (default):
    py -3 mira/mua/v7/migrations/006_extract_temp_min.py

Apply:
    py -3 mira/mua/v7/migrations/006_extract_temp_min.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values


_TEMP_RANGE_F = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:TO|THRU|THROUGH|-|–)\s*(-?\d+(?:\.\d+)?)\s*(?:DEG(?:REES?)?\s*)?(?:F|°F)\b",
    re.IGNORECASE,
)

_TEMP_RANGE_GENERIC = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:TO|THRU|THROUGH|-|–)\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

_TEMP_SINGLE_F = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:DEG(?:REES?)?\s*)?(?:F|°F)\b",
    re.IGNORECASE,
)


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def _valid_temp_f(value: float) -> bool:
    # Conservative physical range for parsed legacy MUA text.
    return -500.0 <= value <= 1200.0


def _parse_temp_min_from_text(text: str) -> Optional[float]:
    if not text:
        return None
    candidates: list[float] = []

    for m in _TEMP_RANGE_F.finditer(text):
        try:
            v1 = float(m.group(1))
            v2 = float(m.group(2))
        except (ValueError, TypeError):
            continue
        lo = min(v1, v2)
        if _valid_temp_f(lo):
            candidates.append(lo)

    # Fallback: ranges without explicit trailing "F"
    if not candidates:
        for m in _TEMP_RANGE_GENERIC.finditer(text):
            try:
                v1 = float(m.group(1))
                v2 = float(m.group(2))
            except (ValueError, TypeError):
                continue
            lo = min(v1, v2)
            hi = max(v1, v2)
            # Filter obvious non-temperature pairs (e.g., years/pages) by requiring
            # plausible temperature span and at least one negative or low value.
            if not (_valid_temp_f(lo) and _valid_temp_f(hi)):
                continue
            if lo <= 60.0 and (hi - lo) <= 1500.0:
                candidates.append(lo)

    if not candidates:
        # Last resort: single explicit F values; prefer negatives.
        singles: list[float] = []
        for m in _TEMP_SINGLE_F.finditer(text):
            try:
                v = float(m.group(1))
            except (ValueError, TypeError):
                continue
            if _valid_temp_f(v):
                singles.append(v)
        negatives = [v for v in singles if v < 0]
        if negatives:
            return min(negatives)
        if singles:
            return min(singles)
        return None

    return min(candidates)


@dataclass
class ParsedUpdate:
    row_id: int
    source_file: str
    temp_min_f: float
    method: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill temp_min_f for v7 precedents.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist updates. Default is dry-run.",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(**_load_db_params())
    conn.autocommit = False

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, source_file, rationale, env_raw_text, application
            FROM mua_precedents_v7
            WHERE temp_min_f IS NULL
            ORDER BY id
            """
        )
        rows = cur.fetchall()
        cur.close()

        # 1) Deterministic join to bok.mua_normalized by filename.
        cur = conn.cursor()
        cur.execute(
            """
            SELECT lower(filename) AS filename_key, MIN(temp_f_min)::float AS temp_min_f
            FROM bok.mua_normalized
            WHERE temp_f_min IS NOT NULL
            GROUP BY lower(filename)
            """
        )
        norm_map = {r[0]: float(r[1]) for r in cur.fetchall() if r[0] and r[1] is not None}
        cur.close()

        updates: list[ParsedUpdate] = []
        method_counts: dict[str, int] = {}

        for row_id, source_file, rationale, env_raw_text, application in rows:
            filename_key = Path(source_file or "").name.lower()
            temp_min = None
            method = None

            from_norm = norm_map.get(filename_key)
            if from_norm is not None and _valid_temp_f(from_norm):
                temp_min = float(from_norm)
                method = "join_bok_normalized"
            else:
                text = " ".join([
                    rationale or "",
                    env_raw_text or "",
                    application or "",
                ])
                parsed = _parse_temp_min_from_text(text)
                if parsed is not None and _valid_temp_f(parsed):
                    temp_min = float(parsed)
                    method = "regex_text_parse"

            if temp_min is None or method is None:
                continue

            updates.append(
                ParsedUpdate(
                    row_id=int(row_id),
                    source_file=source_file,
                    temp_min_f=temp_min,
                    method=method,
                )
            )
            method_counts[method] = method_counts.get(method, 0) + 1

        if args.apply and updates:
            values = [(u.temp_min_f, u.row_id) for u in updates]
            cur = conn.cursor()
            execute_values(
                cur,
                """
                UPDATE mua_precedents_v7 AS v
                SET temp_min_f = d.temp_min_f
                FROM (VALUES %s) AS d(temp_min_f, row_id)
                WHERE v.id = d.row_id
                  AND v.temp_min_f IS NULL
                """,
                values,
                page_size=500,
            )
            cur.close()
            conn.commit()
        elif args.apply:
            conn.commit()
        else:
            conn.rollback()

        mode = "APPLY" if args.apply else "DRY_RUN"
        print("=" * 72)
        print(f"TEMP_MIN BACKFILL ({mode})")
        print("=" * 72)
        print(f"Rows scanned (temp_min NULL):  {len(rows)}")
        print(f"Rows with updates:             {len(updates)}")
        if method_counts:
            print("\nMethod distribution:")
            for method, count in sorted(method_counts.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {method:24s} {count:5d}")

        report = {
            "mode": mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "rows_scanned": len(rows),
            "updates_count": len(updates),
            "method_counts": method_counts,
            "sample_updates": [u.__dict__ for u in updates[:100]],
        }
        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"006_extract_temp_min_{stamp}.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
