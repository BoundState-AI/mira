"""
MUA Precedents v7 - Appendix B / Closure Backfill
=================================================

Backfills:
  - appendix_b_code
  - closure_path

using deterministic text/rule signals aligned with v7 `category_router`
semantics (Appendix B is not assigned for Cat I trigger conditions).

Usage
-----
Dry-run:
    py -3 mira/mua/v7/migrations/009_backfill_appendix_b_and_closure.py

Apply:
    py -3 mira/mua/v7/migrations/009_backfill_appendix_b_and_closure.py --apply
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


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


_CODE_105 = re.compile(
    r"\b(minor quantity|very small amount|small quantity|negligible|less than\s*\.?\d+\s*(lb|lbs|g|grams)|<\s*45\s*g|<\s*13\s*cm2|2\s*in2)\b",
    re.IGNORECASE,
)
_CODE_104 = re.compile(
    r"\b(sandwich(?:ed)?|encapsulat(?:ed|ion)|laminat(?:ed|ion)|overcoat(?:ed)?|bonded to metal|between (?:two )?(?:metal|non[- ]flammable)|heat[- ]?sink(?:ed)?)\b",
    re.IGNORECASE,
)
_CODE_106 = re.compile(
    r"\b(hermetic(?:ally)? sealed|hermetic|sealed container|sealed volume|welded enclosure|brazed enclosure)\b",
    re.IGNORECASE,
)
_CODE_103 = re.compile(
    r"\b(tested in (?:actual )?(?:use )?configuration|configuration tested|full[- ]scale test|system[- ]level test|test report)\b",
    re.IGNORECASE,
)
_CODE_108 = re.compile(
    r"\b(off[- ]the[- ]shelf|off the shelf|\bcots\b|catalog item|commercial off[- ]the[- ]shelf|common off[- ]the[- ]shelf)\b",
    re.IGNORECASE,
)
_CODE_107 = re.compile(
    r"\b(no propagation path|prevents? (?:flame )?propagation|cannot contribute to fire propagation|no nearby ignition source|no ignition source)\b",
    re.IGNORECASE,
)


_CLOSURE_MAP = {
    "103": "CONFIG_ANALYSIS",
    "104": "HEAT_SINK",
    "105": "MINOR_QUANTITY",
    "106": "CONFIG_ANALYSIS",
    "107": "HEAT_SINK",
    "108": "CONFIG_ANALYSIS",
}

_CLOSURE_DIRECT_PATTERNS = [
    ("MINOR_QUANTITY", re.compile(r"\b(minor quantity|small quantity|very small amount|negligible)\b", re.IGNORECASE)),
    ("HEAT_SINK", re.compile(r"\b(heat[- ]?sink|sandwich(?:ed)?|encapsulat(?:ed|ion)|no propagation path)\b", re.IGNORECASE)),
    ("CONFIG_ANALYSIS", re.compile(r"\b(configuration analysis|tested in (?:actual )?(?:use )?configuration|hermetic(?:ally)? sealed|off[- ]the[- ]shelf|\bcots\b)\b", re.IGNORECASE)),
    ("SUBSTITUTION", re.compile(r"\b(substitut(?:e|ion|ed)|alternative material)\b", re.IGNORECASE)),
]


def _has_cat1_disqualifier(env_type: Optional[str], issues: list[str]) -> bool:
    env = (env_type or "UNKNOWN").upper()
    issue_set = {str(i).upper() for i in (issues or [])}

    if env in {"LOX_GOX", "ENRICHED_O2", "HYDROGEN", "CRYOGENIC"}:
        return True
    if issue_set.intersection({"O2_COMPAT", "HEE", "FRACTURE_CONTROL"}):
        return True
    return False


def _infer_appendix_b(
    *,
    determination: str,
    env_type: Optional[str],
    issues: list[str],
    text: str,
) -> tuple[Optional[str], str]:
    """
    Infer Appendix B code with conservative rules.

    Returns:
      (code, method)
    """
    det = (determination or "").upper()
    if det not in {"APPROVED", "APPROVED_WITH_LIMITS"}:
        return None, "determination_not_approved"

    if _has_cat1_disqualifier(env_type, issues):
        return None, "cat1_disqualifier"

    if _CODE_105.search(text):
        return "105", "pattern_code_105"
    if _CODE_104.search(text):
        return "104", "pattern_code_104"
    if _CODE_106.search(text):
        return "106", "pattern_code_106"
    if _CODE_103.search(text):
        return "103", "pattern_code_103"
    if _CODE_108.search(text):
        return "108", "pattern_code_108"
    if _CODE_107.search(text):
        return "107", "pattern_code_107"

    return None, "no_rule_hit"


def _infer_closure_from_text(text: str) -> tuple[Optional[str], str]:
    for closure, pattern in _CLOSURE_DIRECT_PATTERNS:
        if pattern.search(text):
            return closure, f"pattern_{closure.lower()}"
    return None, "no_rule_hit"


@dataclass
class Candidate:
    row_id: int
    mua_number: str
    old_appendix_b_code: Optional[str]
    new_appendix_b_code: Optional[str]
    appendix_method: str
    old_closure_path: Optional[str]
    new_closure_path: Optional[str]
    closure_method: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill appendix_b_code and closure_path.")
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
                id, mua_number, material_designation, env_type, issues, determination,
                rationale, application, appendix_b_code, closure_path
            FROM mua_precedents_v7
            WHERE appendix_b_code IS NULL
               OR closure_path IS NULL
            ORDER BY id
            """
        )
        rows = cur.fetchall()
        cur.close()

        appendix_updates: list[tuple[str, int]] = []
        closure_updates: list[tuple[str, int]] = []
        candidates: list[Candidate] = []

        append_methods: dict[str, int] = {}
        closure_methods: dict[str, int] = {}

        for row in rows:
            (
                row_id,
                mua_number,
                material_designation,
                env_type,
                issues,
                determination,
                rationale,
                application,
                old_appendix,
                old_closure,
            ) = row

            text = " ".join(
                [
                    str(material_designation or ""),
                    str(rationale or ""),
                    str(application or ""),
                ]
            )

            new_appendix = None
            appendix_method = "not_needed"
            if old_appendix is None:
                new_appendix, appendix_method = _infer_appendix_b(
                    determination=str(determination or ""),
                    env_type=env_type,
                    issues=issues or [],
                    text=text,
                )
                if new_appendix:
                    appendix_updates.append((new_appendix, int(row_id)))
                    append_methods[appendix_method] = append_methods.get(appendix_method, 0) + 1

            new_closure = None
            closure_method = "not_needed"
            if old_closure is None:
                closure_seed = new_appendix or old_appendix
                if closure_seed in _CLOSURE_MAP:
                    new_closure = _CLOSURE_MAP[closure_seed]
                    closure_method = "from_appendix_code"
                else:
                    new_closure, closure_method = _infer_closure_from_text(text)

                if new_closure:
                    closure_updates.append((new_closure, int(row_id)))
                    closure_methods[closure_method] = closure_methods.get(closure_method, 0) + 1

            if new_appendix or new_closure:
                candidates.append(
                    Candidate(
                        row_id=int(row_id),
                        mua_number=str(mua_number),
                        old_appendix_b_code=old_appendix,
                        new_appendix_b_code=new_appendix,
                        appendix_method=appendix_method,
                        old_closure_path=old_closure,
                        new_closure_path=new_closure,
                        closure_method=closure_method,
                    )
                )

        if args.apply:
            if appendix_updates:
                cur = conn.cursor()
                execute_values(
                    cur,
                    """
                    UPDATE mua_precedents_v7 AS v
                    SET appendix_b_code = d.appendix_b_code
                    FROM (VALUES %s) AS d(appendix_b_code, row_id)
                    WHERE v.id = d.row_id
                      AND v.appendix_b_code IS NULL
                    """,
                    appendix_updates,
                    page_size=500,
                )
                cur.close()

            if closure_updates:
                cur = conn.cursor()
                execute_values(
                    cur,
                    """
                    UPDATE mua_precedents_v7 AS v
                    SET closure_path = d.closure_path
                    FROM (VALUES %s) AS d(closure_path, row_id)
                    WHERE v.id = d.row_id
                      AND v.closure_path IS NULL
                    """,
                    closure_updates,
                    page_size=500,
                )
                cur.close()

            conn.commit()
        else:
            conn.rollback()

        mode = "APPLY" if args.apply else "DRY_RUN"
        print("=" * 72)
        print(f"APPENDIX/CLOSURE BACKFILL ({mode})")
        print("=" * 72)
        print(f"Rows scanned:                  {len(rows)}")
        print(f"appendix_b_code updates:       {len(appendix_updates)}")
        print(f"closure_path updates:          {len(closure_updates)}")
        print(f"rows touched (either field):   {len(candidates)}")

        if append_methods:
            print("\nAppendix methods:")
            for method, count in sorted(append_methods.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {method:26s} {count:5d}")
        if closure_methods:
            print("\nClosure methods:")
            for method, count in sorted(closure_methods.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {method:26s} {count:5d}")

        report = {
            "mode": mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "rows_scanned": len(rows),
            "appendix_updates": len(appendix_updates),
            "closure_updates": len(closure_updates),
            "rows_touched": len(candidates),
            "appendix_method_counts": append_methods,
            "closure_method_counts": closure_methods,
            "sample_updates": [c.__dict__ for c in candidates[:120]],
        }
        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"009_backfill_appendix_b_and_closure_{stamp}.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
