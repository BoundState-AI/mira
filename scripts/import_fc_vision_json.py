#!/usr/bin/env python3
"""Import vision-extracted FC data into PostgreSQL database."""

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


def import_fc_records(json_path: Path, dry_run: bool = False):
    """Import FC records from vision-extracted JSON into database."""

    # Load JSON
    print(f"Loading records from {json_path}")
    with json_path.open('r', encoding='utf-8') as f:
        records = json.load(f)

    print(f"Loaded {len(records)} records")

    # Connect to database
    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    stats = {
        'inserted': 0,
        'updated_media': 0,
        'skipped_duplicate': 0,
        'material_code_mismatch': 0,
        'skipped_material_not_found': 0,
    }

    try:
        for i, record in enumerate(records, 1):
            if i % 100 == 0:
                print(f"  Processing {i}/{len(records)}...")

            # Check if test exists by report number
            cur.execute("""
                SELECT id, material_code, media, rating
                FROM fluid_compatibility_tests
                WHERE test_report_no = %s
            """, (record['report_number'],))

            existing = cur.fetchone()

            if existing:
                existing_id, existing_mat_code, existing_media, existing_rating = existing

                # PDF uses old material codes, DB uses new ones
                if existing_mat_code != record['material_code']:
                    stats['material_code_mismatch'] += 1

                # Update media if NULL or different
                if record.get('media') and (existing_media is None or existing_media != record['media']):
                    if not dry_run:
                        cur.execute("""
                            UPDATE fluid_compatibility_tests
                            SET media = %s
                            WHERE id = %s
                        """, (record['media'], existing_id))
                    stats['updated_media'] += 1
                else:
                    stats['skipped_duplicate'] += 1

            else:
                # New test - look up correct material code by designation
                # Use progressive matching strategies
                designation = record['designation']

                # Strip trademark symbols and normalize
                clean_desig = designation
                for symbol in ['™', '®', '©', '℠']:
                    clean_desig = clean_desig.replace(symbol, '')
                clean_desig = ' '.join(clean_desig.split())

                mat_result = None

                # Strategy 1: Try exact match (with ILIKE for case insensitivity)
                cur.execute("""
                    SELECT material_code FROM materials
                    WHERE designation ILIKE %s LIMIT 1
                """, (clean_desig,))
                mat_result = cur.fetchone()

                # Strategy 2: Try without form suffixes (SHEET, BAR, ROD, STRIP, PLATE, etc.)
                if not mat_result:
                    base_desig = clean_desig
                    for form in [' SHEET ANNEALED', ' SHEET', ' BAR', ' ROD', ' STRIP', ' PLATE',
                                 ' TUBE', ' WIRE', ' FORGING', ' CASTING', ' ANNEALED', ' INGOT FOR CASTING SAND, MOLD, DIE']:
                        if base_desig.upper().endswith(form):
                            base_desig = base_desig[:-len(form)].strip()
                            break

                    if base_desig != clean_desig:
                        cur.execute("""
                            SELECT material_code FROM materials
                            WHERE designation ILIKE %s LIMIT 1
                        """, (base_desig,))
                        mat_result = cur.fetchone()

                # Strategy 3: Try just first 3-4 words (alloy name)
                if not mat_result:
                    words = clean_desig.split()
                    if len(words) >= 3:
                        short_desig = ' '.join(words[:3])
                        cur.execute("""
                            SELECT material_code FROM materials
                            WHERE designation ILIKE %s LIMIT 1
                        """, (f"{short_desig}%",))
                        mat_result = cur.fetchone()

                if mat_result:
                    correct_material_code = mat_result[0]

                    # Insert new test with correct material code
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
                        """, (
                            correct_material_code,
                            record['report_number'],
                            record['rating'],
                            record.get('media'),
                        ))
                    stats['inserted'] += 1
                else:
                    # Material not found in database
                    if i % 100 == 0:
                        print(f"  Warning: Material '{record['designation']}' not found in DB")
                    stats['skipped_material_not_found'] += 1

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
        print(f"  Updated media field: {stats['updated_media']}")
        print(f"  Skipped duplicates: {stats['skipped_duplicate']}")
        if stats['material_code_mismatch'] > 0:
            print(f"  Material code mismatches: {stats['material_code_mismatch']} (resolved by report number)")
        if stats['skipped_material_not_found'] > 0:
            print(f"  Skipped (material not in DB): {stats['skipped_material_not_found']}")

    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Import vision-extracted FC JSON into database')
    parser.add_argument('--json', type=Path,
                        default=Path('C:/BoundState/temp/fc_vision_v2.json'),
                        help='Path to vision-extracted JSON file')
    parser.add_argument('--dry-run', action='store_true',
                        help='Analyze without modifying database')

    args = parser.parse_args()

    if not args.json.exists():
        print(f"Error: JSON file not found at {args.json}")
        return 1

    import_fc_records(args.json, dry_run=args.dry_run)

    return 0


if __name__ == '__main__':
    sys.exit(main())
