#!/usr/bin/env python3
"""Add missing FC materials to materials table so all tests can be imported."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.core.db_config import get_db_connection_params


def add_missing_materials(dry_run: bool = True):
    """Add materials that are missing from materials table."""

    # Load extraction
    extraction_path = Path('C:/BoundState/temp/fc_vision_v2.json')
    with extraction_path.open('r', encoding='utf-8') as f:
        extracted = json.load(f)

    # Connect to database
    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    # Get existing test_report_no values
    cur.execute('SELECT test_report_no FROM fluid_compatibility_tests WHERE test_report_no IS NOT NULL')
    existing_tests = set(row[0] for row in cur.fetchall())

    # Get existing material codes
    cur.execute('SELECT material_code FROM materials')
    existing_materials = set(row[0] for row in cur.fetchall())

    # Find tests that failed to import (not in database)
    missing_materials = []
    seen_designations = set()

    for rec in extracted:
        report_no = rec.get('report_number')
        if report_no and report_no not in existing_tests:
            mat_code = rec.get('material_code')
            designation = rec.get('designation', '')

            # Strip trademark symbols
            clean_desig = designation
            for symbol in ['™', '®', '©', '℠', '�']:
                clean_desig = clean_desig.replace(symbol, '')
            clean_desig = ' '.join(clean_desig.split()).strip()

            if clean_desig and clean_desig not in seen_designations:
                seen_designations.add(clean_desig)
                missing_materials.append({
                    'material_code': mat_code,
                    'designation': clean_desig,
                    'original': designation
                })

    print(f"Found {len(missing_materials)} missing materials")

    # Insert missing materials
    inserted = 0
    skipped_existing = 0

    for mat in missing_materials:
        mat_code = mat['material_code']
        designation = mat['designation']

        if mat_code in existing_materials:
            # Material code exists, check if designation matches
            cur.execute("SELECT designation FROM materials WHERE material_code = %s", (mat_code,))
            existing_desig = cur.fetchone()[0]
            print(f"Material code {mat_code} exists: {existing_desig}")
            print(f"  PDF has: {designation}")
            skipped_existing += 1
            continue

        print(f"\nAdding material {mat_code}: {designation}")

        if not dry_run:
            cur.execute("""
                INSERT INTO materials (
                    material_code,
                    designation,
                    source
                ) VALUES (%s, %s, 'FC_MAPTIS_PDF')
            """, (mat_code, designation))
            inserted += 1
        else:
            inserted += 1

    if not dry_run:
        conn.commit()
        print(f"\nInserted {inserted} new materials")
    else:
        print(f"\nDRY RUN - Would insert {inserted} materials")

    print(f"Skipped {skipped_existing} (material_code already exists)")

    cur.close()
    conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Add missing FC materials')
    parser.add_argument('--execute', action='store_true',
                        help='Actually insert materials (default is dry-run)')

    args = parser.parse_args()

    add_missing_materials(dry_run=not args.execute)

    return 0


if __name__ == '__main__':
    sys.exit(main())
