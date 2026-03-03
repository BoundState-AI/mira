"""
MUA Precedents v7 - Umbrella Flag Backfill
==========================================

Sets ``is_umbrella`` to TRUE for high-signal multi-material / list-driven MUAs.
This is a deterministic heuristic pass (no LLM).

Usage
-----
Dry-run:
    py -3 mira/mua/v7/migrations/007_backfill_umbrella.py

Apply:
    py -3 mira/mua/v7/migrations/007_backfill_umbrella.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


_UMB_PATTERNS = [
    re.compile(r"\bSEE\s+ATTACHED\b", re.IGNORECASE),
    re.compile(r"\bSEE\s+ATTACHED\s+LIST\b", re.IGNORECASE),
    re.compile(r"\bSEE\s+MIUL\b", re.IGNORECASE),
    re.compile(r"\bMIUL\s+ATTACHED\b", re.IGNORECASE),
    re.compile(r"\bVARIOUS\b", re.IGNORECASE),
    re.compile(r"\bSEVERAL\b", re.IGNORECASE),
    re.compile(r"\bMULTIPLE\b", re.IGNORECASE),
    re.compile(r"\bLIST\s+OF\s+MATERIALS?\b", re.IGNORECASE),
    re.compile(r"\bSEE\s+NEXT\s+PAGE\b", re.IGNORECASE),
    re.compile(r"\bSEE\s+SECOND\s+SHEET\b", re.IGNORECASE),
]


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def _is_multi_material_text(text: str, *, allow_separator_heuristic: bool) -> bool:
    text = (text or "").strip()
    if not text:
        return False

    # Strong keyword-driven umbrella indicators.
    for pat in _UMB_PATTERNS:
        if pat.search(text):
            return True

    if allow_separator_heuristic:
        # Heuristic: lots of separators usually indicates material lists.
        separators = text.count("/") + text.count(",") + text.count(";")
        if separators >= 3:
            return True
        if separators >= 2 and len(text) > 50:
            return True

    return False


@dataclass
class UmbrellaCandidate:
    row_id: int
    mua_number: str
    source_file: str
    material_designation: str
    reason: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill is_umbrella for v7 precedents.")
    parser.add_argument("--apply", action="store_true", help="Persist updates. Default is dry-run.")
    args = parser.parse_args()

    conn = psycopg2.connect(**_load_db_params())
    conn.autocommit = False

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, mua_number, source_file, material_designation, application
            FROM mua_precedents_v7
            WHERE COALESCE(is_umbrella, FALSE) = FALSE
            ORDER BY id
            """
        )
        rows = cur.fetchall()
        cur.close()

        candidates: list[UmbrellaCandidate] = []
        updates: list[tuple[bool, int]] = []

        for row_id, mua_number, source_file, material_designation, application in rows:
            reason = None
            if _is_multi_material_text(
                material_designation or "",
                allow_separator_heuristic=True,
            ):
                reason = "designation_pattern"
            elif _is_multi_material_text(
                application or "",
                allow_separator_heuristic=False,
            ):
                reason = "application_pattern"

            if not reason:
                continue

            candidates.append(
                UmbrellaCandidate(
                    row_id=int(row_id),
                    mua_number=mua_number,
                    source_file=source_file,
                    material_designation=material_designation or "",
                    reason=reason,
                )
            )
            updates.append((True, int(row_id)))

        if args.apply and updates:
            cur = conn.cursor()
            execute_values(
                cur,
                """
                UPDATE mua_precedents_v7 AS v
                SET is_umbrella = d.is_umbrella
                FROM (VALUES %s) AS d(is_umbrella, row_id)
                WHERE v.id = d.row_id
                  AND COALESCE(v.is_umbrella, FALSE) = FALSE
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

        mode = "APPLY" if args.apply else "DRY_RUN"
        print("=" * 72)
        print(f"UMBRELLA BACKFILL ({mode})")
        print("=" * 72)
        print(f"Rows scanned:            {len(rows)}")
        print(f"Rows flagged umbrella:   {len(candidates)}")

        reason_counts: dict[str, int] = {}
        for c in candidates:
            reason_counts[c.reason] = reason_counts.get(c.reason, 0) + 1
        if reason_counts:
            print("\nReason distribution:")
            for reason, count in sorted(reason_counts.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {reason:22s} {count:5d}")

        report = {
            "mode": mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "rows_scanned": len(rows),
            "rows_flagged": len(candidates),
            "reason_counts": reason_counts,
            "sample_rows": [c.__dict__ for c in candidates[:100]],
        }
        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"007_backfill_umbrella_{stamp}.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
