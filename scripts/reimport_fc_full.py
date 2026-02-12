#!/usr/bin/env python3
"""Re-import ALL FC tests - (material_code, media) is the unique key."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.core.db_config import get_db_connection_params


def reimport_all_fc_tests(json_path: Path, dry_run: bool = False):
    """Import ALL FC records - unique key is (material_code, media)."""

    # Load JSON
    print(f"Loading records from {json_path}")
    with json_path.open('r', encoding='utf-8') as f:
        records = json.load(f)

    print(f"Loaded {len(records)} records")

    # Connect to database
    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    # FIRST: Delete all FC_VISION_V2 records
    if not dry_run:
        print("\nDeleting existing FC_VISION_V2 records...")
        cur.execute("DELETE FROM fluid_compatibility_tests WHERE source = 'FC_VISION_V2'")
        deleted = cur.rowcount
        print(f"Deleted {deleted} existing FC_VISION_V2 records")

    stats = {
        'inserted': 0,
        'skipped_duplicate': 0,
        'material_not_found': 0,
    }

    for i, record in enumerate(records, 1):
        if i % 500 == 0:
            print(f"  Processing {i}/{len(records)}...")

        report_no = record.get('report_number')
        designation = record.get('designation', '')
        media = record.get('media')
        rating = record.get('rating')

        if not media:
            continue

        # Strip trademark symbols
        clean_desig = designation
        for symbol in ['™', '®', '©', '℠', '�']:
            clean_desig = clean_desig.replace(symbol, '')
        clean_desig = ' '.join(clean_desig.split()).strip()

        # Match material by designation
        mat_result = None

        # Strategy 1: Exact match
        cur.execute("SELECT material_code FROM materials WHERE designation ILIKE %s LIMIT 1", (clean_desig,))
        mat_result = cur.fetchone()

        # Strategy 2: Without form suffixes
        if not mat_result:
            base_desig = clean_desig
            for form in [' SHEET ANNEALED', ' SHEET SOLUTION TREATED', ' SHEET', ' BAR', ' ROD', ' STRIP', ' PLATE',
                         ' TUBE', ' WIRE', ' FORGING', ' CASTING', ' ANNEALED', ' FOIL', ' EXTRUDED', ' EXTRUSION',
                         ' H1150M', ' H1150', ' H1025']:
                if base_desig.upper().endswith(form.upper()):
                    base_desig = base_desig[:-len(form)].strip()
                    break

            if base_desig != clean_desig:
                cur.execute("SELECT material_code FROM materials WHERE designation ILIKE %s LIMIT 1", (base_desig,))
                mat_result = cur.fetchone()

        # Strategy 3: First 3 words
        if not mat_result:
            words = clean_desig.split()
            if len(words) >= 3:
                short_desig = ' '.join(words[:3])
                cur.execute("SELECT material_code FROM materials WHERE designation ILIKE %s LIMIT 1", (f"{short_desig}%",))
                mat_result = cur.fetchone()

        if not mat_result:
            stats['material_not_found'] += 1
            continue

        material_code = mat_result[0]

        # Check if (material_code, media) already exists - that's the unique key
        # test_report_no is just metadata (many are "Report")
        cur.execute("""
            SELECT id FROM fluid_compatibility_tests
            WHERE material_code = %s AND media = %s
        """, (material_code, media))

        existing = cur.fetchone()

        if existing:
            stats['skipped_duplicate'] += 1
        else:
            # Insert new test
            if not dry_run:
                cur.execute("""
                    INSERT INTO fluid_compatibility_tests (
                        material_code,
                        test_report_no,
                        test_no_type,
                        rating,
                        media,
                        source,
                        material_change_flag,
                        fluid_change_flag
                    ) VALUES (
                        %s, %s, 'Fluid Comp', %s, %s, 'FC_VISION_V2',
                        'N', 'N'
                    )
                """, (material_code, report_no, rating, media))
            stats['inserted'] += 1

    if not dry_run:
        conn.commit()
        print("\nCommitted changes to database")
    else:
        print("\nDRY RUN - No changes committed")

    # Print statistics
    print(f"\n{'='*60}")
    print("Import Statistics")
    print(f"{'='*60}")
    print(f"Total records processed: {len(records)}")
    print(f"  Inserted new tests: {stats['inserted']}")
    print(f"  Skipped duplicates: {stats['skipped_duplicate']}")
    print(f"  Material not found: {stats['material_not_found']}")

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='Re-import ALL FC vision data')
    parser.add_argument('--json', type=Path,
                        default=Path('C:/BoundState/temp/fc_vision_v2.json'),
                        help='Path to vision-extracted JSON file')
    parser.add_argument('--execute', action='store_true',
                        help='Actually import (default is dry-run)')

    args = parser.parse_args()

    if not args.json.exists():
        print(f"Error: JSON file not found at {args.json}")
        return 1

    reimport_all_fc_tests(args.json, dry_run=not args.execute)

    return 0


if __name__ == '__main__':
    sys.exit(main())
