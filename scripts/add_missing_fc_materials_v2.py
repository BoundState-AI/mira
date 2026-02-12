#!/usr/bin/env python3
"""Add missing FC materials with new material codes."""

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
    """Add materials that don't exist by designation with new material codes."""

    # Load extraction
    extraction_path = Path('C:/BoundState/temp/fc_vision_v2.json')
    with extraction_path.open('r', encoding='utf-8') as f:
        extracted = json.load(f)

    # Connect to database
    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    # Get max material_code to generate new codes
    cur.execute('SELECT MAX(material_code) FROM materials')
    max_code = cur.fetchone()[0] or 90000
    next_code = max_code + 1

    print(f"Max material_code in DB: {max_code}")
    print(f"Will start assigning from: {next_code}")
    print()

    # Get existing test_report_no values
    cur.execute('SELECT test_report_no FROM fluid_compatibility_tests WHERE test_report_no IS NOT NULL')
    existing_tests = set(row[0] for row in cur.fetchall())

    # Get existing designations
    cur.execute('SELECT designation FROM materials')
    existing_designations = set(row[0].strip().upper() for row in cur.fetchall())

    # Find materials that need to be added
    to_add = []
    seen = set()

    for rec in extracted:
        report_no = rec.get('report_number')
        if report_no and report_no not in existing_tests:
            designation = rec.get('designation', '')

            # Strip trademark symbols and clean
            clean_desig = designation
            for symbol in ['™', '®', '©', '℠', '�']:
                clean_desig = clean_desig.replace(symbol, '')
            clean_desig = ' '.join(clean_desig.split()).strip()

            if not clean_desig:
                continue

            # Check if this designation already exists
            if clean_desig.upper() in existing_designations:
                continue

            # Check if we've already queued this one
            if clean_desig in seen:
                continue

            seen.add(clean_desig)
            to_add.append({
                'designation': clean_desig,
                'pdf_code': rec.get('material_code'),
                'report_no': report_no
            })

    print(f"Found {len(to_add)} materials to add:")
    print()

    # Add them
    inserted = 0
    for mat in to_add:
        new_code = next_code
        designation = mat['designation']
        pdf_code = mat['pdf_code']

        print(f"{new_code}: {designation}")
        print(f"   (PDF had code {pdf_code}, report {mat['report_no']})")

        if not dry_run:
            cur.execute("""
                INSERT INTO materials (
                    material_code,
                    designation,
                    source
                ) VALUES (%s, %s, 'FC_MAPTIS_PDF')
            """, (new_code, designation))
            next_code += 1
            inserted += 1
        else:
            next_code += 1

    if not dry_run:
        conn.commit()
        print(f"\nInserted {inserted} new materials")
    else:
        print(f"\nDRY RUN - Would insert {len(to_add)} materials")

    cur.close()
    conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Add missing FC materials with new codes')
    parser.add_argument('--execute', action='store_true',
                        help='Actually insert materials (default is dry-run)')

    args = parser.parse_args()

    add_missing_materials(dry_run=not args.execute)

    return 0


if __name__ == '__main__':
    sys.exit(main())
