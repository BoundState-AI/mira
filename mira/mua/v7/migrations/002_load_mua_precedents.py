"""
MUA Precedents v7 — Data Migration
===================================

Loads v6_cleaned.jsonl (5,650 records, best structured data) into mua_precedents_v7.
Falls back to v5 historic_mua.jsonl for full-length rationale when v6 truncated at 500 chars.

Run:
    python mira/mua/v7/migrations/002_load_mua_precedents.py

Prerequisites:
    1. Run 001_create_mua_precedents_v7.sql first
    2. PostgreSQL running with mira database
"""

import json
import hashlib
import sys
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values

# ============================================================
# Paths
# ============================================================

BASE = Path(__file__).resolve().parents[4]  # c:\BoundState
V6_CLEANED = BASE / "data" / "MUA" / "mua_v6_cleaned.jsonl"
V5_HISTORIC = BASE / "mira" / "databases" / "mua_faiss_db" / "historic_mua.jsonl"

# ============================================================
# Canonical enum mappings — resolves the chaos
# ============================================================

# env_type: v6 lowercase → canonical uppercase
ENV_TYPE_MAP = {
    "lox_gox": "LOX_GOX",
    "pure_o2": "LOX_GOX",       # pure O2 is LOX/GOX service
    "enriched_o2": "ENRICHED_O2",
    "cabin_air": "CABIN_AIR",
    "ambient": "CABIN_AIR",     # ambient air = cabin air for search purposes
    "vacuum": "VACUUM",
    "cryogenic": "CRYOGENIC",
    "water": "WATER",
    "co2": "PROPELLANT",        # CO2 systems are propellant-adjacent
    "high_pressure": "HIGH_PRESSURE",
    "unknown": "UNKNOWN",
}

# issues: v6 lowercase → canonical uppercase
ISSUE_MAP = {
    "flammability": "FLAM",
    "toxicity": "TOX",
    "scc": "SCC",
    "corrosion": "CORR",
    "tvs": "TVS",
    "offgassing": "OFFGAS",
    "o2_compat": "O2_COMPAT",
    "dissimilar_metals": "DISSIMILAR_METALS",
    "fluid_compat": "FLUID_COMPAT",
    "fracture_control": "FRACTURE_CONTROL",
    "process_spec": "PROCESS_SPEC",
    "workmanship": "WORKMANSHIP",
    "other": "OTHER",
}

# material_family: v6 lowercase → canonical uppercase
FAMILY_MAP = {
    "aluminum": "ALUMINUM",
    "stainless_steel": "STAINLESS_STEEL",
    "nickel_alloy": "NICKEL_ALLOY",
    "titanium": "TITANIUM",
    "copper_alloy": "COPPER_ALLOY",
    "carbon_steel": "CARBON_STEEL",
    "polymer": "POLYMER",
    "elastomer": "ELASTOMER",
    "adhesive": "ADHESIVE",
    "composite": "COMPOSITE",
    "ceramic": "CERAMIC",
    "coating": "COATING",
    "lubricant": "LUBRICANT",
    "sealant": "SEALANT",
    "other_metal": "OTHER_METAL",
    "other_nonmetal": "OTHER_NONMETAL",
    "unknown": None,  # NULL in DB, not "UNKNOWN" string
}

# determination: normalize edge cases
DETERMINATION_MAP = {
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
    "CANCELLED": "CANCELLED",
    "DEFERRED": "DEFERRED",
    "UNKNOWN": "UNKNOWN",
    # Edge cases from other sources
    "CONDITIONAL": "APPROVED_WITH_LIMITS",
    "APPROVED_WITH_LIMITS": "APPROVED_WITH_LIMITS",
    "TESTING_REQUIRED": "TESTING_REQUIRED",
}


def normalize_env_type(raw: str) -> str:
    return ENV_TYPE_MAP.get(raw, "UNKNOWN")


def normalize_issues(raw_list: list) -> list:
    return sorted(set(ISSUE_MAP.get(i, "OTHER") for i in raw_list))


def normalize_family(raw: str) -> Optional[str]:
    return FAMILY_MAP.get(raw)


def normalize_determination(raw: str) -> str:
    return DETERMINATION_MAP.get(raw, "UNKNOWN")


# ============================================================
# Load v5 rationale index (for full-text fallback)
# ============================================================

def load_v5_rationale_index() -> dict:
    """Build filename → full rationale from v5 historic data.

    v6_cleaned truncates rationale at 500 chars.
    v5 has the full text (avg 277 chars in v6, but some were longer before truncation).
    """
    index = {}
    if not V5_HISTORIC.exists():
        print(f"  WARNING: v5 historic file not found at {V5_HISTORIC}")
        return index

    print(f"  Loading v5 rationale index from {V5_HISTORIC}...")
    with open(V5_HISTORIC, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                fname = rec.get("file_name", "")
                data = rec.get("data", {})
                rationale = data.get("rationale", "")
                application = data.get("application", "")
                if fname:
                    existing = index.get(fname) or {
                        "rationale": "",
                        "application": "",
                        "file_hash": "",
                    }
                    # Preserve the longest non-empty rationale/application text seen
                    # for this file and keep the file hash even if rationale is blank.
                    if rationale and len(rationale) > len(existing.get("rationale", "")):
                        existing["rationale"] = rationale
                    if application and len(application) > len(existing.get("application", "")):
                        existing["application"] = application
                    if not existing.get("file_hash") and rec.get("file_hash"):
                        existing["file_hash"] = rec.get("file_hash", "")
                    index[fname] = existing
            except json.JSONDecodeError:
                continue

    print(f"  Loaded {len(index)} v5 rationale entries")
    return index


# ============================================================
# Transform one v6_cleaned record → insert row
# ============================================================

def transform_record(rec: dict, v5_index: dict) -> Optional[tuple]:
    """Transform a v6_cleaned JSON record into a PostgreSQL row tuple."""

    mua_number = rec.get("mua_number", "").strip()
    source_file = rec.get("source_file", "").strip()
    material_designation = rec.get("material_designation", "").strip()

    if not mua_number or not material_designation:
        return None

    # Environment decomposition
    env = rec.get("environment", {})
    if isinstance(env, str):
        # Shouldn't happen in v6_cleaned but be safe
        env = {"type": "unknown", "raw_text": env}

    env_type = normalize_env_type(env.get("type", "unknown"))
    o2_percent = env.get("o2_percent")
    pressure_psia = env.get("pressure_psia")
    temp_f = env.get("temperature_f")  # v6 only has one temp field
    is_habitable = env.get("is_habitable", False)
    env_raw_text = env.get("raw_text", "")

    # Classification
    category = rec.get("category")  # None is fine
    issues = normalize_issues(rec.get("issues", []))
    determination = normalize_determination(rec.get("determination", "UNKNOWN"))

    # Material
    material_family = normalize_family(rec.get("material_family", "unknown"))
    specification = rec.get("specification")
    manufacturer = rec.get("manufacturer")
    trade_name = rec.get("trade_name")

    # Content — use v5 full-length rationale if v6 was truncated
    rationale = rec.get("rationale", "")
    application = rec.get("application", "")

    # Detect truncation: v6 caps at 500 chars
    fname = Path(source_file).name if source_file else ""
    v5_data = v5_index.get(fname, {})
    source_hash = v5_data.get("file_hash", "")

    if rationale and len(rationale) >= 498 and v5_data.get("rationale"):
        v5_rat = v5_data["rationale"]
        if len(v5_rat) > len(rationale):
            rationale = v5_rat

    if application and len(application) >= 498 and v5_data.get("application"):
        v5_app = v5_data["application"]
        if len(v5_app) > len(application):
            application = v5_app

    # Metadata
    confidence = rec.get("confidence", 1.0)
    extraction_mode = rec.get("extraction_mode", "vision")

    return (
        mua_number,
        source_file,
        source_hash or None,
        material_designation,
        material_family,
        specification,
        manufacturer,
        trade_name,
        env_type,
        o2_percent,
        pressure_psia,
        temp_f,         # temp_max_f (v6 only has one temp field)
        None,           # temp_min_f (not in v6_cleaned — backfill later)
        is_habitable,
        env_raw_text,
        category,
        issues,
        determination,
        rationale,
        application,
        None,           # appendix_b_code (backfill later)
        None,           # closure_path (backfill later)
        confidence,
        extraction_mode,
        False,          # is_umbrella (backfill from BOK v2 later)
    )


# ============================================================
# Main migration
# ============================================================

def main():
    if not V6_CLEANED.exists():
        print(f"ERROR: v6_cleaned not found at {V6_CLEANED}")
        sys.exit(1)

    print("=" * 60)
    print("MUA Precedents v7 — Data Migration")
    print("=" * 60)

    # Step 1: Load v5 rationale index for full-text fallback
    v5_index = load_v5_rationale_index()

    # Step 2: Transform all v6_cleaned records
    print(f"\n  Transforming records from {V6_CLEANED}...")
    rows = []
    skipped = 0
    truncation_recovered = 0

    with open(V6_CLEANED, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue

            row = transform_record(rec, v5_index)
            if row is None:
                skipped += 1
                continue

            rows.append(row)

    print(f"  Transformed: {len(rows)} records")
    print(f"  Skipped: {skipped} records")

    # Step 3: Load into PostgreSQL
    print(f"\n  Connecting to PostgreSQL...")

    # Use centralized config if available, fall back to defaults
    try:
        sys.path.insert(0, str(BASE))
        from mira.core.db_config import get_db_connection_params
        conn_params = get_db_connection_params()
    except ImportError:
        conn_params = {
            "host": "localhost",
            "port": 5432,
            "dbname": "mira",
            "user": "postgres",
            "password": "postgres",
        }

    conn = psycopg2.connect(**conn_params)
    cur = conn.cursor()

    # Verify table exists and is empty
    cur.execute("SELECT count(*) FROM mua_precedents_v7")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"  WARNING: mua_precedents_v7 already has {existing} rows.")
        print(f"  Truncating before load...")
        cur.execute("TRUNCATE mua_precedents_v7 RESTART IDENTITY")

    # Bulk insert
    print(f"  Inserting {len(rows)} rows...")

    insert_sql = """
        INSERT INTO mua_precedents_v7 (
            mua_number, source_file, source_hash,
            material_designation, material_family, specification, manufacturer, trade_name,
            env_type, o2_percent, pressure_psia, temp_max_f, temp_min_f,
            is_habitable, env_raw_text,
            category, issues, determination,
            rationale, application,
            appendix_b_code, closure_path,
            confidence, extraction_mode, is_umbrella
        ) VALUES %s
    """

    execute_values(cur, insert_sql, rows, page_size=500)
    conn.commit()

    # Step 4: Verify
    cur.execute("SELECT count(*) FROM mua_precedents_v7")
    loaded = cur.fetchone()[0]

    cur.execute("""
        SELECT
            determination, count(*) as cnt
        FROM mua_precedents_v7
        GROUP BY determination
        ORDER BY cnt DESC
    """)
    det_dist = cur.fetchall()

    cur.execute("""
        SELECT
            env_type, count(*) as cnt
        FROM mua_precedents_v7
        GROUP BY env_type
        ORDER BY cnt DESC
    """)
    env_dist = cur.fetchall()

    cur.execute("""
        SELECT
            count(CASE WHEN material_family IS NOT NULL THEN 1 END) as has_family,
            count(CASE WHEN category IS NOT NULL THEN 1 END) as has_category,
            count(CASE WHEN o2_percent IS NOT NULL THEN 1 END) as has_o2,
            count(CASE WHEN pressure_psia IS NOT NULL THEN 1 END) as has_pressure,
            count(CASE WHEN temp_max_f IS NOT NULL THEN 1 END) as has_temp,
            count(CASE WHEN rationale IS NOT NULL AND length(rationale) > 0 THEN 1 END) as has_rationale,
            avg(length(rationale))::int as avg_rationale_len
        FROM mua_precedents_v7
    """)
    fill = cur.fetchone()

    cur.close()
    conn.close()

    # Report
    print(f"\n{'=' * 60}")
    print(f"  MIGRATION COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Loaded: {loaded} rows")
    print(f"\n  Determination distribution:")
    for det, cnt in det_dist:
        print(f"    {det:30s} {cnt:5d}")
    print(f"\n  Environment type distribution:")
    for env, cnt in env_dist:
        print(f"    {env:30s} {cnt:5d}")
    print(f"\n  Field fill rates:")
    print(f"    material_family:  {fill[0]:5d} / {loaded} ({100*fill[0]/loaded:.1f}%)")
    print(f"    category:         {fill[1]:5d} / {loaded} ({100*fill[1]/loaded:.1f}%)")
    print(f"    o2_percent:       {fill[2]:5d} / {loaded} ({100*fill[2]/loaded:.1f}%)")
    print(f"    pressure_psia:    {fill[3]:5d} / {loaded} ({100*fill[3]/loaded:.1f}%)")
    print(f"    temp_max_f:       {fill[4]:5d} / {loaded} ({100*fill[4]/loaded:.1f}%)")
    print(f"    rationale:        {fill[5]:5d} / {loaded} ({100*fill[5]/loaded:.1f}%)")
    print(f"    avg rationale:    {fill[6]} chars")

    print(f"\n  Next steps:")
    print(f"    1. Run 003_rename_table_to_v7.sql if table name has not been aligned yet")
    print(f"    2. Run 004_backfill_traceability.py to hydrate source_hash from raw PDFs")
    print(f"    3. Run 005_backfill_unknowns.py to classify unknown material_family/env_type")
    print(f"    4. Run 006_extract_temp_min.py to fill temp_min_f")
    print(f"    5. Run 007_backfill_umbrella.py to tag umbrella/list-driven MUAs")
    print(f"    6. Run 008_enforce_traceability_constraints.sql after source_hash backfill")
    print(f"    7. Run 009_backfill_appendix_b_and_closure.py to infer Appendix B codes")
    print(f"    8. Run 010_backfill_category.py to fill remaining category values")
    print(f"    9. Run 011_audit_consistency.py to quantify residual review items")
    print(f"   10. Run 012_backfill_determination_strict.py to close deterministic UNKNOWN determinations")
    print(f"   11. Run 013_generate_pdf_audit_sample.py for statistically valid PDF QA sampling")
    print(f"   12. Run 014_evaluate_pdf_audit_confidence.py on completed audit sheets")
    print(f"   13. Archive FAISS indexes: mua_faiss_db/, mua_bok_v2/, mua_v6_faiss/, MIRA_V2/faiss_indexes/")


if __name__ == "__main__":
    main()
