"""
MUA Precedents v7 - Category Backfill
=====================================

Backfills `category` (I/II/III) for rows where category is NULL using
deterministic rules aligned with v7 category routing semantics:

- Category I: Cat I trigger conditions (O2/H2/cryogenic style triggers).
- Category III: Approved + Appendix B code present + no Cat I trigger.
- Category II: Default otherwise.

Usage
-----
Dry-run:
    py -3 mira/mua/v7/migrations/010_backfill_category.py

Apply:
    py -3 mira/mua/v7/migrations/010_backfill_category.py --apply
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


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


_CAT1_ENV_TYPES = {"LOX_GOX", "ENRICHED_O2", "HYDROGEN", "CRYOGENIC"}
_CAT1_ISSUES = {"O2_COMPAT", "HEE", "FRACTURE_CONTROL"}


def _is_cat1_trigger(env_type: Optional[str], issues: list[str]) -> bool:
    env = (env_type or "UNKNOWN").upper()
    issue_set = {str(i).upper() for i in (issues or [])}
    if env in _CAT1_ENV_TYPES:
        return True
    if issue_set.intersection(_CAT1_ISSUES):
        return True
    return False


def _infer_category(
    *,
    env_type: Optional[str],
    issues: list[str],
    determination: str,
    appendix_b_code: Optional[str],
) -> tuple[str, str]:
    det = (determination or "").upper()
    code = (appendix_b_code or "").strip()

    if _is_cat1_trigger(env_type, issues):
        return "I", "cat1_trigger"

    if code and det in {"APPROVED", "APPROVED_WITH_LIMITS"}:
        return "III", "appendix_code_present"

    return "II", "default_cat2"


@dataclass
class Candidate:
    row_id: int
    mua_number: str
    old_category: Optional[str]
    new_category: str
    method: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill category for NULL rows.")
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
            SELECT
                id, mua_number, category, env_type, issues, determination, appendix_b_code
            FROM mua_precedents_v7
            WHERE category IS NULL
            ORDER BY id
            """
        )
        rows = cur.fetchall()
        cur.close()

        updates: list[tuple[str, int]] = []
        candidates: list[Candidate] = []
        method_counts: dict[str, int] = {}

        for row in rows:
            row_id, mua_number, old_category, env_type, issues, determination, appendix_b_code = row
            new_category, method = _infer_category(
                env_type=env_type,
                issues=issues or [],
                determination=str(determination or ""),
                appendix_b_code=appendix_b_code,
            )
            updates.append((new_category, int(row_id)))
            candidates.append(
                Candidate(
                    row_id=int(row_id),
                    mua_number=str(mua_number),
                    old_category=old_category,
                    new_category=new_category,
                    method=method,
                )
            )
            method_counts[method] = method_counts.get(method, 0) + 1

        if args.apply and updates:
            cur = conn.cursor()
            execute_values(
                cur,
                """
                UPDATE mua_precedents_v7 AS v
                SET category = d.category
                FROM (VALUES %s) AS d(category, row_id)
                WHERE v.id = d.row_id
                  AND v.category IS NULL
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
        print(f"CATEGORY BACKFILL ({mode})")
        print("=" * 72)
        print(f"Rows scanned:          {len(rows)}")
        print(f"Category updates:      {len(updates)}")
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
            "sample_updates": [c.__dict__ for c in candidates[:120]],
        }
        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"010_backfill_category_{stamp}.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
