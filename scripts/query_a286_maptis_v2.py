#!/usr/bin/env python3
"""Query MAPTIS database for A-286 stainless steel codes and data - by material_code."""

import psycopg2
from psycopg2.extras import RealDictCursor

CONN_PARAMS = {
    'host': 'localhost',
    'port': 5432,
    'database': 'mira',
    'user': 'postgres',
    'password': 'postgres',
}

# A-286 codes found in materials table
A286_CODES = [
    '10011', '10124', '10125', '10230', '10267', '10392', '10456', '10518',
    '50069', '50084', '50140', '50706', '50708', '50709', '50717',
    '53418', '53419', '53420', '53421', '53422', '53423', '53424', '53425',
    '53426', '53427', '53428', '53429', '53430', '53516', '53571', '53649',
    '53935', '54197', '54198', '54199', '55340', '55660', '63972'
]

def main():
    conn = psycopg2.connect(**CONN_PARAMS)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    print("=" * 80)
    print("MAPTIS A-286 STAINLESS STEEL - DATABASE QUERY (by material_code)")
    print("=" * 80)

    # Query silver_report_rows for these specific codes
    print("\n--- SILVER_REPORT_ROWS DATA FOR A-286 CODES ---\n")

    codes_with_data = []
    codes_without_data = []

    for code in A286_CODES:
        cursor.execute("""
            SELECT
                COUNT(*) as report_count,
                array_agg(DISTINCT contract_id) as contracts
            FROM silver_report_rows
            WHERE normalized_payload->>'materialkey' = %s
        """, (code,))
        result = cursor.fetchone()

        if result['report_count'] > 0:
            codes_with_data.append((code, result['report_count'], result['contracts']))
        else:
            codes_without_data.append(code)

    print(f"Codes WITH test data: {len(codes_with_data)}")
    print(f"Codes WITHOUT test data: {len(codes_without_data)}")

    print("\n--- CODES WITH TEST DATA ---\n")
    for code, count, contracts in codes_with_data:
        # Get designation
        cursor.execute("SELECT designation FROM materials WHERE material_code::text = %s", (code,))
        mat = cursor.fetchone()
        designation = mat['designation'] if mat else 'N/A'
        print(f"Code {code}: {count} reports")
        print(f"  Designation: {designation}")
        print(f"  Report types: {contracts}")
        print()

    # For codes with data, get detailed ratings
    print("\n--- DETAILED RATINGS COMPARISON ---\n")
    print(f"{'Code':<8} {'Form':<20} {'FLAM':<6} {'PROM':<6} {'SCC':<6} {'CORR':<6} {'TVS':<6} {'TOX':<6} {'FS':<6}")
    print("-" * 90)

    for code, count, contracts in codes_with_data:
        cursor.execute("SELECT designation FROM materials WHERE material_code::text = %s", (code,))
        mat = cursor.fetchone()
        designation = mat['designation'] if mat else 'N/A'

        # Extract form (BAR, SHEET, FASTENER, etc.)
        form = 'UNKNOWN'
        for f in ['FASTENER', 'BOLTS', 'SCREWS', 'BAR', 'SHEET', 'FORGING', 'WIRE', 'TUBE', 'PLATE', 'STRIP', 'SHAPE', 'RINGS', 'STOCK', 'WELDING', 'WELDED']:
            if f in designation.upper():
                form = f
                break

        # Get ratings
        ratings = {'FLAM': '-', 'PROM': '-', 'SCC': '-', 'CORR': '-', 'TVS': '-', 'TOX': '-', 'FS': '-'}

        cursor.execute("""
            SELECT DISTINCT
                contract_id,
                normalized_payload->>'flam_rating' as flam,
                normalized_payload->>'prom_rating' as prom,
                normalized_payload->>'stress_rating' as scc,
                normalized_payload->>'cor_rating' as corr,
                normalized_payload->>'tvs_rating' as tvs,
                normalized_payload->>'tox_spacestationrating' as tox,
                normalized_payload->>'fluc_rating' as fs
            FROM silver_report_rows
            WHERE normalized_payload->>'materialkey' = %s
        """, (code,))

        for row in cursor.fetchall():
            if row['flam']: ratings['FLAM'] = row['flam']
            if row['prom']: ratings['PROM'] = row['prom']
            if row['scc']: ratings['SCC'] = row['scc']
            if row['corr']: ratings['CORR'] = row['corr']
            if row['tvs']: ratings['TVS'] = row['tvs']
            if row['tox']: ratings['TOX'] = row['tox']
            if row['fs']: ratings['FS'] = row['fs']

        print(f"{code:<8} {form:<20} {ratings['FLAM']:<6} {ratings['PROM']:<6} {ratings['SCC']:<6} {ratings['CORR']:<6} {ratings['TVS']:<6} {ratings['TOX']:<6} {ratings['FS']:<6}")

    # Summary
    print("\n\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"\nTotal A-286 MAPTIS codes in materials table: {len(A286_CODES)}")
    print(f"Codes with test data in silver_report_rows: {len(codes_with_data)}")
    print(f"Codes without test data: {len(codes_without_data)}")

    if codes_without_data:
        print(f"\nCodes without data: {', '.join(codes_without_data[:10])}{'...' if len(codes_without_data) > 10 else ''}")

    cursor.close()
    conn.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
