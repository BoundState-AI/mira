"""
Migration 017: Populate MUA Audit Tables

Reads mua_merged_clean.jsonl, runs normalizer + pattern extractor,
inserts into mua_records, mua_concerns, mua_patterns, mua_evidence.

Generates:
  - docs/mua_audit/mua_population_report.md
  - docs/mua_audit/mua_validation_10.md

Usage:
    python 017_populate_mua_audit.py             # Dry run (report only)
    python 017_populate_mua_audit.py --apply      # Write to PostgreSQL
    python 017_populate_mua_audit.py --apply --drop-existing  # Drop and recreate
"""

import json
import sys
import os
import random
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from mira.mua.mua_normalizer import (
    normalize_issues, extract_patterns, extract_evidence, classify_mua_type
)

random.seed(42)

# ─── Config ─────────────────────────────────────────────────────────────────
MERGED_DATA = Path(r"C:\BoundState\data\mua_merged_clean.jsonl")
OUTPUT_DIR = Path(r"C:\BoundState\docs\mua_audit")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CONCERN_DOMAIN_CODES = ['FLAMM', 'SCC', 'CORR', 'TOX', 'TVS', 'FC', 'FORBIDDEN', 'FUNGUS']


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def best_material(rec):
    v6 = (rec.get("material_designation") or "").strip()
    v5 = (rec.get("material_name_v5") or "").strip()
    if v6 and v6.lower() not in ("(no material)", "n/a", "see below",
                                   "see attached", "various", "several"):
        return v6
    if v5:
        return v5
    return None


def get_env_fields(rec):
    """Extract environment fields from record."""
    env_struct = rec.get("environment_structured") or {}
    env_raw = rec.get("environment") or ""
    if isinstance(env_raw, dict):
        env_raw = env_raw.get("raw_text", str(env_raw))

    env_type = None
    o2_pct = None
    pressure = None
    temp_f = None
    is_hab = False

    if isinstance(env_struct, dict):
        env_type = env_struct.get("type")
        o2_pct = env_struct.get("o2_percent")
        pressure = env_struct.get("pressure_psia")
        temp_f = env_struct.get("temperature_f")
        is_hab = env_struct.get("is_habitable", False)
    elif env_raw:
        raw_lower = str(env_raw).lower()
        if "vacuum" in raw_lower or "vac" in raw_lower:
            env_type = "vacuum"
        elif "air" in raw_lower:
            env_type = "cabin_air"
        elif "o2" in raw_lower or "oxygen" in raw_lower:
            env_type = "oxygen"
        elif "space" in raw_lower:
            env_type = "vacuum"

    # Use top-level fields as fallback for temp/pressure
    if temp_f is None:
        temp_f = rec.get("max_temperature_f")
    if pressure is None:
        pressure = rec.get("max_pressure")

    # Habitable from location field
    loc = (rec.get("location") or "").lower()
    if "habitable" in loc and "non" not in loc:
        is_hab = True

    return env_type, str(env_raw) if env_raw else None, o2_pct, pressure, temp_f, is_hab


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Populate MUA audit tables")
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL")
    parser.add_argument("--drop-existing", action="store_true", help="Drop existing data first")
    args = parser.parse_args()

    print("=" * 70)
    print("MUA Audit Population")
    print("=" * 70)

    # Load data
    records = load_jsonl(MERGED_DATA)
    print(f"Loaded {len(records):,} records from {MERGED_DATA}")

    # ─── Process all records ────────────────────────────────────────────────
    processed = []
    all_unmapped = []  # (record_index, source_file, raw_issue, unmapped_fragments)
    domain_counter = Counter()
    pattern_counter = Counter()
    domain_pattern_matrix = defaultdict(Counter)  # domain -> pattern -> count
    type_counter = Counter()
    evidence_counter = Counter()
    records_with_no_domain = 0
    records_with_no_pattern = 0

    for i, rec in enumerate(records):
        material = best_material(rec)
        rationale = rec.get("rationale") or ""
        application = rec.get("application") or ""
        raw_issue = rec.get("issue") or ""
        issues_cleaned = rec.get("issues_cleaned")

        # Step 1: Normalize issues -> concern domains
        domains, unmapped = normalize_issues(raw_issue, issues_cleaned)
        if unmapped:
            all_unmapped.append((i, rec.get("file", "?"), raw_issue, unmapped))
        if not domains:
            records_with_no_domain += 1
        for d in domains:
            domain_counter[d] += 1

        # Step 2: Extract rationale patterns
        patterns = extract_patterns(rationale, application)
        if not patterns:
            records_with_no_pattern += 1
        for p in patterns:
            pattern_counter[p['pattern_code']] += 1
            # Track domain x pattern co-occurrence
            for d in domains:
                domain_pattern_matrix[d][p['pattern_code']] += 1

        # Step 3: Extract evidence
        evidence = extract_evidence(rationale, application)
        for e in evidence:
            evidence_counter[e['evidence_type']] += 1

        # Step 4: Classify MUA type
        mua_type = classify_mua_type(application, raw_issue, material)
        type_counter[mua_type] += 1

        # Step 5: Environment
        env_type, env_raw, o2_pct, pressure, temp_f, is_hab = get_env_fields(rec)

        processed.append({
            'record': rec,
            'material': material,
            'domains': domains,
            'unmapped': unmapped,
            'patterns': patterns,
            'evidence': evidence,
            'mua_type': mua_type,
            'env_type': env_type,
            'env_raw': env_raw,
            'o2_percent': o2_pct,
            'pressure_psia': pressure,
            'temperature_f': temp_f,
            'is_habitable': is_hab,
        })

    print(f"Processed {len(processed):,} records")
    print(f"  Domains assigned: {sum(domain_counter.values()):,} total across {len(records) - records_with_no_domain:,} records")
    print(f"  Records with no domain: {records_with_no_domain:,}")
    print(f"  Patterns found: {sum(pattern_counter.values()):,} total across {len(records) - records_with_no_pattern:,} records")
    print(f"  Records with no pattern: {records_with_no_pattern:,}")
    print(f"  Unmapped issue fragments: {len(all_unmapped):,} records")
    print(f"  Evidence citations: {sum(evidence_counter.values()):,}")

    # ─── PostgreSQL population ──────────────────────────────────────────────
    if args.apply:
        print("\n" + "=" * 70)
        print("Writing to PostgreSQL...")
        print("=" * 70)
        try:
            import psycopg2
            from psycopg2.extras import execute_values
            try:
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

            if args.drop_existing:
                print("  Dropping existing data...")
                for tbl in ['mua_evidence', 'mua_patterns', 'mua_concerns', 'mua_records']:
                    cur.execute(f"DELETE FROM {tbl}")
                conn.commit()
                print("  [OK] Cleared all tables")

            # Load domain and pattern ID lookups
            cur.execute("SELECT id, code FROM concern_domains")
            domain_ids = {row[1]: row[0] for row in cur.fetchall()}
            cur.execute("SELECT id, pattern_code FROM rationale_patterns")
            pattern_ids = {row[1]: row[0] for row in cur.fetchall()}

            if not domain_ids:
                print("  ERROR: concern_domains table is empty. Run 017_mua_audit_schema.sql first.")
                return
            if not pattern_ids:
                print("  ERROR: rationale_patterns table is empty. Run 017_mua_audit_schema.sql first.")
                return

            print(f"  Domain IDs: {domain_ids}")
            print(f"  Pattern IDs: {len(pattern_ids)} patterns loaded")

            # Insert mua_records
            insert_count = 0
            skip_count = 0
            concern_rows = []
            pattern_rows = []
            evidence_rows = []

            for proc in processed:
                rec = proc['record']
                try:
                    cur.execute("SAVEPOINT record_sp")
                    cur.execute("""
                        INSERT INTO mua_records (
                            mua_number, source_file,
                            material_designation, material_designation_v6, material_name_v5,
                            material_family, specification, manufacturer, trade_name,
                            category, determination, confidence, extraction_mode,
                            environment_type, environment_raw, o2_percent, pressure_psia,
                            temperature_f, is_habitable,
                            application_text, rationale_text, raw_issue_text, mua_type
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (source_file) DO NOTHING
                        RETURNING id
                    """, (
                        rec.get("mua_number"),
                        rec.get("file", ""),
                        proc['material'],
                        rec.get("material_designation_v6"),
                        rec.get("material_name_v5"),
                        rec.get("material_family"),
                        rec.get("specification"),
                        rec.get("manufacturer"),
                        rec.get("trade_name"),
                        rec.get("category"),
                        rec.get("determination"),
                        rec.get("confidence"),
                        rec.get("extraction_mode"),
                        proc['env_type'],
                        proc['env_raw'],
                        proc['o2_percent'],
                        proc['pressure_psia'],
                        proc['temperature_f'],
                        proc['is_habitable'],
                        rec.get("application"),
                        rec.get("rationale"),
                        rec.get("issue"),
                        proc['mua_type'],
                    ))
                    result = cur.fetchone()
                    if result is None:
                        skip_count += 1
                        continue
                    record_id = result[0]
                    insert_count += 1

                    # Queue junction rows
                    for d in proc['domains']:
                        if d in domain_ids:
                            concern_rows.append((record_id, domain_ids[d], rec.get("issue")))
                    for p in proc['patterns']:
                        if p['pattern_code'] in pattern_ids:
                            pattern_rows.append((
                                record_id, pattern_ids[p['pattern_code']],
                                p['matched_text'], 1.0
                            ))
                    for e in proc['evidence']:
                        evidence_rows.append((
                            record_id, e['evidence_type'], e['reference_text'],
                            e.get('test_number'), e.get('standard_cited')
                        ))
                    cur.execute("RELEASE SAVEPOINT record_sp")
                except Exception as ex:
                    cur.execute("ROLLBACK TO SAVEPOINT record_sp")
                    skip_count += 1

            # Bulk insert junction tables
            if concern_rows:
                execute_values(cur, """
                    INSERT INTO mua_concerns (mua_record_id, concern_domain_id, raw_issue_text)
                    VALUES %s
                    ON CONFLICT (mua_record_id, concern_domain_id) DO NOTHING
                """, concern_rows, page_size=1000)

            if pattern_rows:
                execute_values(cur, """
                    INSERT INTO mua_patterns (mua_record_id, rationale_pattern_id, matched_text, match_confidence)
                    VALUES %s
                    ON CONFLICT (mua_record_id, rationale_pattern_id) DO NOTHING
                """, pattern_rows, page_size=1000)

            if evidence_rows:
                execute_values(cur, """
                    INSERT INTO mua_evidence (mua_record_id, evidence_type, reference_text, test_number, standard_cited)
                    VALUES %s
                """, evidence_rows, page_size=1000)

            # Update pattern usage counts
            for code, count in pattern_counter.items():
                if code in pattern_ids:
                    cur.execute(
                        "UPDATE rationale_patterns SET usage_count = %s WHERE pattern_code = %s",
                        (count, code)
                    )

            # Populate pattern_domain_applicability
            for domain, pattern_counts in domain_pattern_matrix.items():
                if domain not in domain_ids:
                    continue
                for pcode, freq in pattern_counts.items():
                    if pcode not in pattern_ids:
                        continue
                    cur.execute("""
                        INSERT INTO pattern_domain_applicability (pattern_id, concern_domain_id, frequency)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (pattern_id, concern_domain_id) DO UPDATE SET frequency = EXCLUDED.frequency
                    """, (pattern_ids[pcode], domain_ids[domain], freq))

            conn.commit()
            cur.close()
            conn.close()
            print(f"  [OK] Inserted {insert_count:,} records (skipped {skip_count:,} duplicates)")
            print(f"  [OK] {len(concern_rows):,} concern links")
            print(f"  [OK] {len(pattern_rows):,} pattern links")
            print(f"  [OK] {len(evidence_rows):,} evidence citations")

        except ImportError as e:
            print(f"  SKIP: psycopg2 not available ({e}). Reports still generated.")
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    # ─── Generate Reports ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("Generating reports")
    print("=" * 70)

    # ─── mua_population_report.md ───────────────────────────────────────────
    with open(OUTPUT_DIR / "mua_population_report.md", "w", encoding="utf-8") as f:
        f.write("# MUA Population Report\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Source**: `{MERGED_DATA}`  \n")
        f.write(f"**Records processed**: {len(records):,}\n\n")

        # Records per concern domain
        f.write("## Records Per Concern Domain\n\n")
        f.write("| Domain | Code | Records | % |\n")
        f.write("|--------|------|---------|---|\n")
        for code in CONCERN_DOMAIN_CODES:
            cnt = domain_counter.get(code, 0)
            f.write(f"| {code} | {code} | {cnt:,} | {100*cnt/len(records):.1f}% |\n")
        f.write(f"| **No domain** | - | {records_with_no_domain:,} | {100*records_with_no_domain/len(records):.1f}% |\n")
        f.write(f"\nTotal domain assignments: {sum(domain_counter.values()):,} "
                f"(records can have multiple)\n\n")

        # Records per mitigation pattern
        f.write("## Records Per Mitigation Pattern\n\n")
        f.write("| Pattern | Records | % |\n")
        f.write("|---------|---------|---|\n")
        for code, cnt in pattern_counter.most_common():
            f.write(f"| {code} | {cnt:,} | {100*cnt/len(records):.1f}% |\n")
        f.write(f"| **No pattern** | {records_with_no_pattern:,} | {100*records_with_no_pattern/len(records):.1f}% |\n")
        f.write(f"\nTotal pattern matches: {sum(pattern_counter.values()):,}\n\n")

        # Pattern x Domain heatmap
        f.write("## Pattern x Domain Heatmap\n\n")
        all_patterns = sorted(set(p for counts in domain_pattern_matrix.values() for p in counts))
        # Header
        f.write("| Pattern |")
        for code in CONCERN_DOMAIN_CODES:
            f.write(f" {code} |")
        f.write("\n|---------|")
        for _ in CONCERN_DOMAIN_CODES:
            f.write("------|")
        f.write("\n")
        # Rows
        for pcode in sorted(pattern_counter.keys(), key=lambda x: -pattern_counter[x]):
            f.write(f"| {pcode} |")
            for dcode in CONCERN_DOMAIN_CODES:
                val = domain_pattern_matrix.get(dcode, {}).get(pcode, 0)
                cell = str(val) if val > 0 else "-"
                f.write(f" {cell} |")
            f.write("\n")
        f.write("\n")

        # MUA type distribution
        f.write("## MUA Type Distribution\n\n")
        f.write("| Type | Count | % |\n")
        f.write("|------|-------|---|\n")
        for mtype, cnt in type_counter.most_common():
            f.write(f"| {mtype} | {cnt:,} | {100*cnt/len(records):.1f}% |\n")
        f.write("\n")

        # Evidence citations
        f.write("## Evidence Citations\n\n")
        f.write("| Type | Count |\n")
        f.write("|------|-------|\n")
        for etype, cnt in evidence_counter.most_common():
            f.write(f"| {etype} | {cnt:,} |\n")
        f.write("\n")

        # Unmapped issues
        f.write("## Unmapped Issue Fragments\n\n")
        f.write(f"**{len(all_unmapped):,} records** had issue fragments that didn't map to any domain.\n\n")
        f.write("These need manual review by Dude to determine if they represent:\n")
        f.write("- A new concern domain\n")
        f.write("- A keyword gap in an existing domain\n")
        f.write("- Noise/junk from OCR\n\n")

        # Group unmapped fragments by frequency
        fragment_counter = Counter()
        for _, _, _, fragments in all_unmapped:
            for frag in fragments:
                fragment_counter[frag.strip()[:100]] += 1

        f.write("### Top 50 Unmapped Fragments (by frequency)\n\n")
        f.write("| Fragment | Count | Suggested Action |\n")
        f.write("|----------|-------|------------------|\n")
        for frag, cnt in fragment_counter.most_common(50):
            f.write(f"| {frag.replace('|', '/')} | {cnt} | ___ |\n")
        f.write("\n")

        # Full unmapped list (first 100)
        if len(all_unmapped) > 50:
            f.write("### Sample Unmapped Records (first 100)\n\n")
            f.write("| # | Source File | Raw Issue | Unmapped Fragments |\n")
            f.write("|---|-----------|-----------|-------------------|\n")
            for idx, (rec_i, src, raw, frags) in enumerate(all_unmapped[:100]):
                raw_short = (raw or "")[:80].replace("|", "/").replace("\n", " ")
                frags_str = "; ".join(f[:50] for f in frags).replace("|", "/")
                f.write(f"| {idx+1} | {src} | {raw_short} | {frags_str} |\n")
            f.write("\n")

    print("  [OK] mua_population_report.md")

    # ─── mua_validation_10.md ───────────────────────────────────────────────
    # Pick 10 random records that have at least 1 domain AND 1 pattern
    rich_indices = [i for i, p in enumerate(processed)
                    if p['domains'] and p['patterns'] and p['material']]
    if len(rich_indices) < 10:
        rich_indices = list(range(len(processed)))
    validation_sample = random.sample(rich_indices, min(10, len(rich_indices)))

    with open(OUTPUT_DIR / "mua_validation_10.md", "w", encoding="utf-8") as f:
        f.write("# MUA Validation Sample -- 10 Records for Eyeball Check\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("Verify that the normalizer and pattern matcher got it right.\n\n")
        f.write("---\n\n")

        for sample_num, idx in enumerate(validation_sample, 1):
            proc = processed[idx]
            rec = proc['record']

            f.write(f"### Validation Record {sample_num} of 10\n\n")

            # Core fields
            f.write("| Field | Value |\n")
            f.write("|-------|-------|\n")
            f.write(f"| **Source** | `{rec.get('file', '?')}` |\n")
            f.write(f"| **MUA Number** | {rec.get('mua_number', '?')} |\n")
            f.write(f"| **Material** | {proc['material'] or '(none)'} |\n")
            f.write(f"| **Material Family** | {rec.get('material_family', '(none)')} |\n")
            f.write(f"| **Category** | {rec.get('category', '(none)')} |\n")
            f.write(f"| **Determination** | {rec.get('determination', '(none)')} |\n")
            f.write(f"| **Environment** | {proc['env_raw'] or '(none)'} |\n")
            f.write(f"| **MUA Type** | {proc['mua_type']} |\n")
            f.write(f"| **Confidence** | {rec.get('confidence', '?')} |\n")
            f.write("\n")

            # Raw issue -> normalized domains
            f.write("**Raw Issue**: ")
            f.write(f"`{(rec.get('issue') or '(none)')[:200]}`\n\n")
            f.write(f"**Normalized Domains**: {', '.join(proc['domains']) if proc['domains'] else 'NONE'}\n\n")
            if proc['unmapped']:
                f.write(f"**Unmapped fragments**: {', '.join(proc['unmapped'])}\n\n")

            # Rationale -> matched patterns
            f.write("**Rationale** (first 500 chars):\n")
            f.write(f"> {(rec.get('rationale') or '(none)')[:500]}\n\n")

            f.write("**Matched Patterns**:\n\n")
            if proc['patterns']:
                for p in proc['patterns']:
                    f.write(f"- `{p['pattern_code']}` -- \"...{p['matched_text']}...\"\n")
            else:
                f.write("- (none matched)\n")
            f.write("\n")

            # Evidence
            if proc['evidence']:
                f.write("**Evidence Citations**:\n\n")
                for e in proc['evidence']:
                    f.write(f"- [{e['evidence_type']}] {e['reference_text']}\n")
                f.write("\n")

            # Application
            f.write("**Application** (first 300 chars):\n")
            f.write(f"> {(rec.get('application') or '(none)')[:300]}\n\n")

            # Eyeball check fields
            f.write("**Eyeball Check**:\n")
            f.write("- Domains correct? ___\n")
            f.write("- Patterns correct? ___\n")
            f.write("- MUA type correct? ___\n")
            f.write("- Missing anything? ___\n\n")
            f.write("---\n\n")

    print("  [OK] mua_validation_10.md")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
