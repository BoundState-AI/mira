"""
MUA Precedents v7 - Unknowns Backfill
=====================================

Backfills high-confidence values for:
  - material_family (when NULL)
  - env_type (when UNKNOWN/NULL)

This script uses deterministic rules over existing structured text fields.
It does not re-extract PDFs.

Usage
-----
Dry-run (default):
    py -3 mira/mua/v7/migrations/005_backfill_unknowns.py

Apply updates:
    py -3 mira/mua/v7/migrations/005_backfill_unknowns.py --apply
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


_PLACEHOLDER_DESIGNATION = re.compile(
    r"\b(SEE|ATTACH|TBD|VARIOUS|SEVERAL|MISC|NOT SPECIFIED|UNKNOWN|NA|N/A)\b",
    re.IGNORECASE,
)


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def _upper(text: Optional[str]) -> str:
    return (text or "").upper()


def _infer_material_family(designation: str) -> tuple[Optional[str], str]:
    """
    Infer canonical material_family from designation text.

    Returns:
      (family, method)
    """
    text = _upper(designation).strip()
    if not text:
        return None, "empty_designation"
    if _PLACEHOLDER_DESIGNATION.search(text):
        # Keep unresolved placeholders unresolved.
        return None, "placeholder_designation"

    # High-signal classes first.
    if re.search(r"\b(LOCTITE|EPOXY|ADHESIVE|EA[-\s]?\d|ARALDITE)\b", text):
        return "ADHESIVE", "keyword_adhesive"
    if re.search(r"\b(SEALANT|RTV|PR[-\s]?\d{3,5})\b", text):
        return "SEALANT", "keyword_sealant"
    if re.search(r"\b(COAT|COATING|PAINT|PRIMER|ANODI[ZS]E|CHEM\.?\s*FILM)\b", text):
        return "COATING", "keyword_coating"
    if re.search(r"\b(GREASE|LUBRICANT|OIL|MOLYKOTE|KRYTOX)\b", text):
        return "LUBRICANT", "keyword_lubricant"
    if re.search(r"\b(COMPOSITE|CARBON FIBER|GRAPHITE|IM6/|IM7/|AS4/|T300/|KEVLAR)\b", text):
        return "COMPOSITE", "keyword_composite"
    if re.search(r"\b(PTFE|TEFLON|PEEK|KYNAR|POLYURETHANE|POLYOLEFIN|POLYESTER|NOMEX|Z Y T E L|ZYTEL|ETHYLENE PROPYLENE)\b", text):
        return "POLYMER", "keyword_polymer"
    if re.search(r"\b(VITON|BUNA[-\s]?N|NITRILE|ELASTOMER|SILICONE RUBBER)\b", text):
        return "ELASTOMER", "keyword_elastomer"
    if re.search(r"\b(CERAMIC|ALUMINA|SILICA|QUARTZ)\b", text):
        return "CERAMIC", "keyword_ceramic"

    # Metallic families.
    if re.search(r"\b(STAINLESS|CRES|NITRONIC|AISI\s*3\d{2}|AISI\s*4\d{2}|440C|17[- ]?4|17[- ]?7|A286)\b", text):
        return "STAINLESS_STEEL", "keyword_stainless"
    if re.search(r"\b(INCONEL|HASTELLOY|MONEL|WASPALOY|RENE|NICKEL|INVAR)\b", text):
        return "NICKEL_ALLOY", "keyword_nickel"
    if re.search(r"\b(TITANIUM|TI[-\s]*\d|6AL[-\s]*4V|CP[-\s]*TI)\b", text):
        return "TITANIUM", "keyword_titanium"
    if re.search(r"\b(COPPER|BRONZE|BRASS|BERYLLIUM\s*COPPER|BECU|OFHC)\b", text):
        return "COPPER_ALLOY", "keyword_copper"
    if re.search(r"\b(ALUMINUM|ALUMINIUM|AL[-\s]?(?:1\d{3}|2\d{3}|5\d{3}|6\d{3}|7\d{3})(?:[-\s]?T\d+)?)\b", text):
        return "ALUMINUM", "keyword_aluminum"
    if re.search(r"\b(STEEL|41[34]0|9310|10[0-9]{2})\b", text):
        return "CARBON_STEEL", "keyword_carbon_steel"

    return None, "no_rule_hit"


_O2_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*(?:O2|OXYGEN|OXY|02)\b", re.IGNORECASE)
_TEMP_PATTERN = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:TO|-)\s*(-?\d+(?:\.\d+)?)\s*(?:F|DEG\s*F|°F)?",
    re.IGNORECASE,
)
_PRESSURE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:PSIA|PSI)\b", re.IGNORECASE)


def _extract_temp_min_from_text(text: str) -> Optional[float]:
    mins: list[float] = []
    for m in _TEMP_PATTERN.finditer(text):
        try:
            v1 = float(m.group(1))
            v2 = float(m.group(2))
        except (ValueError, TypeError):
            continue
        mins.append(min(v1, v2))
    if not mins:
        return None
    return min(mins)


def _infer_env_type(env_raw_text: str, rationale: str, application: str) -> tuple[Optional[str], str]:
    """
    Infer canonical env_type from available free text.

    Canonical env_type values:
      LOX_GOX, ENRICHED_O2, CABIN_AIR, VACUUM, CRYOGENIC, WATER, PROPELLANT,
      HIGH_PRESSURE, HYDROGEN, UNKNOWN
    """
    env = _upper(env_raw_text)
    rat = _upper(rationale)
    app = _upper(application)
    full = " ".join([env, rat, app]).strip()
    if not full:
        return None, "no_text"

    # Parse numeric hints.
    o2_match = _O2_PATTERN.search(full)
    o2_pct = float(o2_match.group(1)) if o2_match else None
    tmin = _extract_temp_min_from_text(full)
    p_match = _PRESSURE_PATTERN.search(full)
    psi = float(p_match.group(1)) if p_match else None

    # Service first.
    if re.search(r"\b(GH2|LH2|HYDROGEN|H2 GAS)\b", full):
        return "HYDROGEN", "keyword_hydrogen"
    if re.search(r"\b(LOX|GOX)\b", full):
        return "LOX_GOX", "keyword_lox_gox"
    if o2_pct is not None and o2_pct >= 23.5:
        return "ENRICHED_O2", "o2_percent_enriched"
    if re.search(r"\b(OXYGEN|O2 SERVICE|ENRICHED O2|ENRICHED AIR)\b", full):
        return "ENRICHED_O2", "keyword_enriched_o2"

    # Physical environment.
    if re.search(r"\b(VACUUM|ON[- ]ORBIT|ON ORBIT|SPACE)\b", full):
        return "VACUUM", "keyword_vacuum"
    if tmin is not None and tmin <= -150.0:
        return "CRYOGENIC", "temperature_cryogenic"
    if re.search(r"\b(CRYOGENIC|CRYO)\b", full):
        return "CRYOGENIC", "keyword_cryogenic"
    if re.search(r"\b(WATER|SEAWATER|AQUEOUS)\b", full):
        return "WATER", "keyword_water"
    if re.search(r"\b(PROPELLANT|MMH|NTO|N2O4|HYDRAZINE)\b", full):
        return "PROPELLANT", "keyword_propellant"

    # Air-like regimes.
    if re.search(r"\b(CABIN|HABITABLE|NONHABITABLE|AMBIENT|AIR|CARGO BAY|SUBSYSTEM AMBIENT)\b", full):
        return "CABIN_AIR", "keyword_airlike"
    if re.search(r"\b(NITROGEN|GN2|N2)\b", full):
        return "CABIN_AIR", "keyword_nitrogen_proxy"
    if psi is not None and psi >= 1000:
        return "HIGH_PRESSURE", "pressure_high"

    return None, "no_rule_hit"


@dataclass
class Candidate:
    row_id: int
    mua_number: str
    old_family: Optional[str]
    new_family: Optional[str]
    family_method: str
    old_env_type: Optional[str]
    new_env_type: Optional[str]
    env_method: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill unknown material_family/env_type.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist updates. Default is dry-run.",
    )
    args = parser.parse_args()

    db_params = _load_db_params()
    conn = psycopg2.connect(**db_params)
    conn.autocommit = False

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, mua_number, material_designation, material_family,
                env_type, env_raw_text, rationale, application
            FROM mua_precedents_v7
            WHERE material_family IS NULL
               OR env_type IS NULL
               OR env_type = 'UNKNOWN'
            ORDER BY id
            """
        )
        rows = cur.fetchall()
        cur.close()

        candidates: list[Candidate] = []
        family_updates: list[tuple[str, int]] = []
        env_updates: list[tuple[str, int]] = []

        for row in rows:
            row_id, mua_number, designation, old_family, old_env, env_raw, rationale, application = row
            new_family = None
            family_method = "not_needed"
            if old_family is None:
                new_family, family_method = _infer_material_family(designation or "")
                if new_family:
                    family_updates.append((new_family, row_id))

            old_env_norm = (old_env or "").strip().upper()
            new_env = None
            env_method = "not_needed"
            if not old_env_norm or old_env_norm == "UNKNOWN":
                new_env, env_method = _infer_env_type(env_raw or "", rationale or "", application or "")
                if new_env and new_env != "UNKNOWN":
                    env_updates.append((new_env, row_id))

            if new_family or new_env:
                candidates.append(
                    Candidate(
                        row_id=row_id,
                        mua_number=mua_number,
                        old_family=old_family,
                        new_family=new_family,
                        family_method=family_method,
                        old_env_type=old_env,
                        new_env_type=new_env,
                        env_method=env_method,
                    )
                )

        if args.apply:
            if family_updates:
                cur = conn.cursor()
                execute_values(
                    cur,
                    """
                    UPDATE mua_precedents_v7 AS v
                    SET material_family = d.material_family
                    FROM (VALUES %s) AS d(material_family, row_id)
                    WHERE v.id = d.row_id
                    """,
                    family_updates,
                    page_size=500,
                )
                cur.close()

            if env_updates:
                cur = conn.cursor()
                execute_values(
                    cur,
                    """
                    UPDATE mua_precedents_v7 AS v
                    SET env_type = d.env_type
                    FROM (VALUES %s) AS d(env_type, row_id)
                    WHERE v.id = d.row_id
                    """,
                    env_updates,
                    page_size=500,
                )
                cur.close()

            conn.commit()
        else:
            conn.rollback()

        mode = "APPLY" if args.apply else "DRY_RUN"
        print("=" * 72)
        print(f"UNKNOWNS BACKFILL ({mode})")
        print("=" * 72)
        print(f"Rows scanned:                  {len(rows)}")
        print(f"material_family updates:       {len(family_updates)}")
        print(f"env_type updates:              {len(env_updates)}")
        print(f"rows touched (either field):   {len(candidates)}")

        # Method distribution
        fam_methods: dict[str, int] = {}
        env_methods: dict[str, int] = {}
        for c in candidates:
            if c.new_family:
                fam_methods[c.family_method] = fam_methods.get(c.family_method, 0) + 1
            if c.new_env_type:
                env_methods[c.env_method] = env_methods.get(c.env_method, 0) + 1
        if fam_methods:
            print("\nFamily methods:")
            for method, count in sorted(fam_methods.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {method:28s} {count:5d}")
        if env_methods:
            print("\nEnv methods:")
            for method, count in sorted(env_methods.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {method:28s} {count:5d}")

        report = {
            "mode": mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "rows_scanned": len(rows),
            "family_updates": len(family_updates),
            "env_updates": len(env_updates),
            "rows_touched": len(candidates),
            "family_method_counts": fam_methods,
            "env_method_counts": env_methods,
            "sample_updates": [c.__dict__ for c in candidates[:100]],
        }
        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"005_backfill_unknowns_{stamp}.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
