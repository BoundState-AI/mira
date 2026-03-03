"""
MUA Precedents v7 - Strict Determination Backfill
=================================================

Backfills `mua_precedents_v7.determination` for UNKNOWN rows using ONLY
deterministic joins to `bok.mua_normalized` by filename.

Strict rule:
  - Join on lower(source_file) == lower(filename)
  - Candidate determination must be a SINGLE distinct non-UNKNOWN value
    within bok.mua_normalized for that filename.
  - No LLM, no heuristic inference.

Usage
-----
Dry-run:
    py -3 mira/mua/v7/migrations/012_backfill_determination_strict.py

Apply:
    py -3 mira/mua/v7/migrations/012_backfill_determination_strict.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values


CANONICAL_MAP = {
    "APPROVED": "APPROVED",
    "CONDITIONAL": "APPROVED_WITH_LIMITS",
    "APPROVED_WITH_LIMITS": "APPROVED_WITH_LIMITS",
    "REJECTED": "REJECTED",
    "DEFERRED": "DEFERRED",
    "CANCELLED": "CANCELLED",
}


@dataclass
class Candidate:
    row_id: int
    mua_number: str
    source_file: str
    old_determination: str
    bok_determination_raw: str
    new_determination: str
    method: str = "strict_filename_join_single_non_unknown"


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def main() -> None:
    parser = argparse.ArgumentParser(description="Strictly backfill UNKNOWN determinations.")
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
        cur.execute("SELECT COUNT(*) FROM mua_precedents_v7 WHERE determination='UNKNOWN'")
        unknown_before = cur.fetchone()[0]

        cur.execute(
            """
            WITH bok_det AS (
              SELECT
                lower(filename) AS filename_key,
                COUNT(DISTINCT upper(determination))
                  FILTER (WHERE upper(determination) <> 'UNKNOWN') AS non_unknown_distinct_count,
                MAX(upper(determination))
                  FILTER (WHERE upper(determination) <> 'UNKNOWN') AS chosen_non_unknown
              FROM bok.mua_normalized
              GROUP BY lower(filename)
            )
            SELECT
              v.id,
              v.mua_number,
              v.source_file,
              v.determination,
              b.chosen_non_unknown
            FROM mua_precedents_v7 v
            JOIN bok_det b
              ON lower(v.source_file) = b.filename_key
            WHERE v.determination = 'UNKNOWN'
              AND b.non_unknown_distinct_count = 1
              AND b.chosen_non_unknown IS NOT NULL
            ORDER BY v.id
            """
        )
        rows = cur.fetchall()
        cur.close()

        candidates: list[Candidate] = []
        updates: list[tuple[str, int]] = []
        skipped_unmapped = 0

        for row_id, mua_number, source_file, old_det, bok_det in rows:
            canonical = CANONICAL_MAP.get(str(bok_det).upper())
            if not canonical:
                skipped_unmapped += 1
                continue
            updates.append((canonical, int(row_id)))
            candidates.append(
                Candidate(
                    row_id=int(row_id),
                    mua_number=str(mua_number),
                    source_file=str(source_file),
                    old_determination=str(old_det),
                    bok_determination_raw=str(bok_det),
                    new_determination=canonical,
                )
            )

        if args.apply and updates:
            cur = conn.cursor()
            execute_values(
                cur,
                """
                UPDATE mua_precedents_v7 AS v
                SET determination = d.determination
                FROM (VALUES %s) AS d(determination, row_id)
                WHERE v.id = d.row_id
                  AND v.determination = 'UNKNOWN'
                """,
                updates,
                page_size=500,
            )
            cur.close()
            conn.commit()
        elif args.apply:
            conn.commit()
        else:
            conn.rollback()

        # Re-query for reporting.
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM mua_precedents_v7 WHERE determination='UNKNOWN'")
        unknown_after = cur.fetchone()[0]
        cur.close()

        mode = "APPLY" if args.apply else "DRY_RUN"
        print("=" * 72)
        print(f"DETERMINATION BACKFILL ({mode})")
        print("=" * 72)
        print(f"UNKNOWN before:                {unknown_before}")
        print(f"Deterministic candidates:      {len(rows)}")
        print(f"Updates prepared:              {len(updates)}")
        print(f"Skipped (unmapped det value):  {skipped_unmapped}")
        print(f"UNKNOWN after:                 {unknown_after}")

        mapping_counts: dict[str, int] = {}
        for c in candidates:
            key = f"{c.bok_determination_raw}->{c.new_determination}"
            mapping_counts[key] = mapping_counts.get(key, 0) + 1
        if mapping_counts:
            print("\nMapping distribution:")
            for k, v in sorted(mapping_counts.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {k:30s} {v:5d}")

        report = {
            "mode": mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "unknown_before": unknown_before,
            "deterministic_candidates": len(rows),
            "updates_prepared": len(updates),
            "skipped_unmapped": skipped_unmapped,
            "unknown_after": unknown_after,
            "mapping_counts": mapping_counts,
            "sample_updates": [c.__dict__ for c in candidates[:120]],
        }
        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"012_backfill_determination_strict_{stamp}.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
