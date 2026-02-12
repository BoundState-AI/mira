#!/usr/bin/env python3
"""Add ALL missing FC materials from extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.core.db_config import get_db_connection_params


def add_all_missing_materials(dry_run: bool = True):
    """Add all materials from fc_missing_materials.json."""

    # Load missing materials report
    report_path = Path('C:/BoundState/temp/fc_missing_materials.json')
    with report_path.open('r', encoding='utf-8') as f:
        missing_records = json.load(f)

    # Get unique designations
    unique_materials = {}
    for rec in missing_records:
        designation = rec['designation']
        if designation not in unique_materials:
            unique_materials[designation] = rec

    print(f"Found {len(unique_materials)} unique materials to add")

    # Connect to database
    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    # Get max material_code
    cur.execute('SELECT MAX(material_code) FROM materials')
    max_code = cur.fetchone()[0] or 90000
    next_code = max_code + 1

    print(f"Starting from material_code {next_code}")
    print()

    # Get existing designations
    cur.execute('SELECT designation FROM materials')
    existing_designations = set(row[0].strip().upper() for row in cur.fetchall())

    # Add materials
    inserted = 0
    skipped = 0

    for designation in sorted(unique_materials.keys()):
        # Check if already exists
        if designation.upper() in existing_designations:
            skipped += 1
            continue

        print(f"{next_code}: {designation[:70]}")

        if not dry_run:
            cur.execute("""
                INSERT INTO materials (
                    material_code,
                    designation,
                    source
                ) VALUES (%s, %s, 'FC_MAPTIS_PDF')
            """, (next_code, designation))

        next_code += 1
        inserted += 1

    if not dry_run:
        conn.commit()
        print(f"\nInserted {inserted} new materials")
    else:
        print(f"\nDRY RUN - Would insert {inserted} materials")

    print(f"Skipped {skipped} (already exist)")

    cur.close()
    conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Add all missing FC materials')
    parser.add_argument('--execute', action='store_true',
                        help='Actually insert materials (default is dry-run)')

    args = parser.parse_args()

    add_all_missing_materials(dry_run=not args.execute)

    return 0


if __name__ == '__main__':
    sys.exit(main())
