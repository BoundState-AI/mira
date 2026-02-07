#!/usr/bin/env python3
"""Query MAPTIS database for A-286 stainless steel codes and data."""

import psycopg2
from psycopg2.extras import RealDictCursor

CONN_PARAMS = {
    'host': 'localhost',
    'port': 5432,
    'database': 'mira',
    'user': 'postgres',
    'password': 'postgres',
}

def main():
    conn = psycopg2.connect(**CONN_PARAMS)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    print("=" * 80)
    print("MAPTIS A-286 STAINLESS STEEL - DATABASE QUERY")
    print("=" * 80)

    # Query 1: Search materials table for A-286
    print("\n--- MATERIALS TABLE (A-286 entries) ---\n")
    cursor.execute("""
        SELECT material_code, designation, composition, use_type
        FROM materials
        WHERE designation ILIKE '%A-286%' OR designation ILIKE '%A286%'
        ORDER BY material_code
    """)
    materials = cursor.fetchall()

    if materials:
        for m in materials:
            print(f"Code: {m['material_code']}")
            print(f"  Designation: {m['designation']}")
            print(f"  Composition: {m.get('composition', 'N/A')}")
            print(f"  Use Type: {m.get('use_type', 'N/A')}")
            print()
    else:
        print("No direct matches in materials table")

    # Query 2: Search silver_report_rows for A-286 by materialkey
    print("\n--- SILVER_REPORT_ROWS (distinct material codes for A-286) ---\n")
    cursor.execute("""
        SELECT DISTINCT
            normalized_payload->>'materialkey' as material_code,
            normalized_payload->>'materialdesig' as designation,
            contract_id
        FROM silver_report_rows
        WHERE normalized_payload->>'materialdesig' ILIKE '%A-286%'
           OR normalized_payload->>'materialdesig' ILIKE '%A286%'
           OR normalized_payload->>'composition' ILIKE '%A-286%'
           OR normalized_payload->>'composition' ILIKE '%A286%'
        ORDER BY material_code
    """)
    silver_rows = cursor.fetchall()

    codes_found = set()
    if silver_rows:
        for r in silver_rows:
            code = r['material_code']
            codes_found.add(code)
            print(f"Code: {code} | Designation: {r['designation'][:60] if r['designation'] else 'N/A'} | Report: {r['contract_id']}")
    else:
        print("No matches in silver_report_rows")

    # Query 3: For each distinct code found, get full details
    print(f"\n--- DETAILED DATA FOR {len(codes_found)} DISTINCT CODES ---\n")

    for code in sorted(codes_found):
        print(f"\n{'='*60}")
        print(f"MAPTIS CODE: {code}")
        print(f"{'='*60}")

        cursor.execute("""
            SELECT
                contract_id,
                normalized_payload->>'materialdesig' as designation,
                normalized_payload->>'composition' as composition,
                normalized_payload->>'flam_rating' as flam_rating,
                normalized_payload->>'stress_rating' as scc_rating,
                normalized_payload->>'cor_rating' as corr_rating,
                normalized_payload->>'tvs_rating' as tvs_rating,
                normalized_payload->>'tox_spacestationrating' as tox_rating,
                normalized_payload->>'fluc_rating' as fs_rating,
                normalized_payload->>'prom_rating' as prom_rating
            FROM silver_report_rows
            WHERE normalized_payload->>'materialkey' = %s
            LIMIT 10
        """, (code,))

        details = cursor.fetchall()
        for d in details:
            print(f"\n  Contract: {d['contract_id']}")
            print(f"  Designation: {d['designation']}")
            print(f"  Composition: {d.get('composition', 'N/A')}")
            ratings = []
            if d.get('flam_rating'): ratings.append(f"FLAM={d['flam_rating']}")
            if d.get('prom_rating'): ratings.append(f"PROM={d['prom_rating']}")
            if d.get('scc_rating'): ratings.append(f"SCC={d['scc_rating']}")
            if d.get('corr_rating'): ratings.append(f"CORR={d['corr_rating']}")
            if d.get('tvs_rating'): ratings.append(f"TVS={d['tvs_rating']}")
            if d.get('tox_rating'): ratings.append(f"TOX={d['tox_rating']}")
            if d.get('fs_rating'): ratings.append(f"FS={d['fs_rating']}")
            if ratings:
                print(f"  Ratings: {', '.join(ratings)}")

    # Query 4: Summary comparison
    print("\n\n" + "=" * 80)
    print("SUMMARY: CODE COMPARISON")
    print("=" * 80)

    for code in sorted(codes_found):
        cursor.execute("""
            SELECT
                COUNT(*) as report_count,
                COUNT(DISTINCT contract_id) as report_types,
                array_agg(DISTINCT contract_id) as contracts
            FROM silver_report_rows
            WHERE normalized_payload->>'materialkey' = %s
        """, (code,))
        summary = cursor.fetchone()
        print(f"\nCode {code}:")
        print(f"  Total reports: {summary['report_count']}")
        print(f"  Report types: {summary['report_types']}")
        print(f"  Contracts: {summary['contracts']}")

    cursor.close()
    conn.close()
    print("\n\nDone.")

if __name__ == "__main__":
    main()
