"""
MUA Precedents v7 - Consistency Audit
=====================================

Read-only audit of key semantic consistency checks after backfills.

Usage:
    py -3 mira/mua/v7/migrations/011_audit_consistency.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def main() -> None:
    conn = psycopg2.connect(**_load_db_params())
    try:
        cur = conn.cursor()
        checks = {
            "cat3_without_appendix": """
                SELECT COUNT(*)
                FROM mua_precedents_v7
                WHERE category = 'III'
                  AND appendix_b_code IS NULL
            """,
            "cat3_with_cat1_triggers": """
                SELECT COUNT(*)
                FROM mua_precedents_v7
                WHERE category = 'III'
                  AND (
                    env_type IN ('LOX_GOX','ENRICHED_O2','HYDROGEN','CRYOGENIC')
                    OR issues && ARRAY['O2_COMPAT','HEE','FRACTURE_CONTROL']::text[]
                  )
            """,
            "appendix_with_cat1_triggers": """
                SELECT COUNT(*)
                FROM mua_precedents_v7
                WHERE appendix_b_code IS NOT NULL
                  AND (
                    env_type IN ('LOX_GOX','ENRICHED_O2','HYDROGEN','CRYOGENIC')
                    OR issues && ARRAY['O2_COMPAT','HEE','FRACTURE_CONTROL']::text[]
                  )
            """,
            "closure_without_appendix": """
                SELECT COUNT(*)
                FROM mua_precedents_v7
                WHERE closure_path IS NOT NULL
                  AND appendix_b_code IS NULL
            """,
            "appendix_without_closure": """
                SELECT COUNT(*)
                FROM mua_precedents_v7
                WHERE appendix_b_code IS NOT NULL
                  AND closure_path IS NULL
            """,
            "category_null": """
                SELECT COUNT(*) FROM mua_precedents_v7 WHERE category IS NULL
            """,
            "traceability_missing_hash": """
                SELECT COUNT(*)
                FROM mua_precedents_v7
                WHERE source_hash IS NULL OR trim(source_hash) = ''
            """,
        }
        out: dict[str, object] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        for name, sql in checks.items():
            cur.execute(sql)
            out[name] = cur.fetchone()[0]

        cur.execute("SELECT category, COUNT(*) FROM mua_precedents_v7 GROUP BY category ORDER BY COUNT(*) DESC")
        out["category_distribution"] = cur.fetchall()

        cur.execute(
            """
            SELECT appendix_b_code, COUNT(*)
            FROM mua_precedents_v7
            WHERE appendix_b_code IS NOT NULL
            GROUP BY appendix_b_code
            ORDER BY COUNT(*) DESC
            """
        )
        out["appendix_distribution"] = cur.fetchall()

        cur.execute(
            """
            SELECT closure_path, COUNT(*)
            FROM mua_precedents_v7
            WHERE closure_path IS NOT NULL
            GROUP BY closure_path
            ORDER BY COUNT(*) DESC
            """
        )
        out["closure_distribution"] = cur.fetchall()

        print("=" * 72)
        print("MUA V7 CONSISTENCY AUDIT")
        print("=" * 72)
        for k, v in out.items():
            if isinstance(v, (list, tuple)):
                continue
            print(f"{k:30s} {v}")

        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"011_audit_consistency_{stamp}.json"
        out_file.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"\nReport: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
