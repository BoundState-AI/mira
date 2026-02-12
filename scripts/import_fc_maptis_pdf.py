#!/usr/bin/env python3
"""Extract Fluid Compatibility data from FC MAPTIS PDF and populate database.

Extracts data from "C:\\BoundState\\docs\\FC maptis.pdf" (151 pages, 3987 tests)
and populates fluid_compatibility_tests table with deduplication.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
import re

import psycopg2
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.core.db_config import get_db_connection_params


def extract_fc_data_from_pdf(pdf_path: Path) -> list[dict]:
    """Extract all FC test data from PDF tables.

    Returns list of dicts with keys:
        - material_code: int
        - designation: str
        - report_number: str
        - rating: str (A, B, X, I)
        - media: str
    """
    records = []

    with pdfplumber.open(pdf_path) as pdf:
        print(f"Processing {len(pdf.pages)} pages...")

        for page_num, page in enumerate(pdf.pages, 1):
            if page_num % 10 == 0:
                print(f"  Page {page_num}/{len(pdf.pages)}...")

            # Extract tables from page
            tables = page.extract_tables()

            for table in tables:
                if not table or len(table) < 2:
                    continue

                # First row is header, skip it
                for row in table[1:]:
                    if not row or len(row) < 5:
                        continue

                    # Parse row: [Mtrl. Code, Material Designation, Report Number, Rating, Media]
                    mtrl_code_str = (row[0] or "").strip()
                    designation = (row[1] or "").strip()
                    report_number = (row[2] or "").strip()
                    rating = (row[3] or "").strip()
                    media = (row[4] or "").strip()

                    # Skip empty rows or header rows
                    if not mtrl_code_str or mtrl_code_str == "Mtrl. Code":
                        continue

                    # Parse material code
                    try:
                        material_code = int(mtrl_code_str)
                    except ValueError:
                        print(f"  Warning: Invalid material code '{mtrl_code_str}' on page {page_num}, skipping")
                        continue

                    # Skip rows without required data
                    if not report_number or not rating:
                        continue

                    records.append({
                        'material_code': material_code,
                        'designation': designation,
                        'report_number': report_number,
                        'rating': rating,
                        'media': media or None,
                    })

    print(f"\nExtracted {len(records)} FC test records")
    return records


def populate_database(records: list[dict], dry_run: bool = False):
    """Populate fluid_compatibility_tests table with deduplication.

    Strategy:
        1. For each record, check if test_report_no exists
        2. If exists and media is NULL, update media field
        3. If exists and media is NOT NULL, check for duplicates and skip
        4. If not exists, insert new test
    """
    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    stats = {
        'inserted': 0,
        'updated_media': 0,
        'skipped_duplicate': 0,
        'material_code_mismatch': 0,
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

                # Note: PDF uses old material codes, DB uses new ones
                # We match by test_report_no only, which is the unique identifier
                if existing_mat_code != record['material_code']:
                    stats['material_code_mismatch'] += 1
                    # Continue anyway - trust the database's material code

                # If media is NULL or different, update it
                if record['media'] and (existing_media is None or existing_media != record['media']):
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
                # New test - need to look up correct material code by designation
                # PDF has old codes, we need to find the new code in the materials table
                cur.execute("""
                    SELECT material_code
                    FROM materials
                    WHERE designation ILIKE %s
                    LIMIT 1
                """, (f"%{record['designation']}%",))

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
                                %s, %s, 'Fluid Comp', %s, %s, 'FC_MAPTIS_PDF',
                                'N', 'N'
                            )
                        """, (
                            correct_material_code,
                            record['report_number'],
                            record['rating'],
                            record['media'],
                        ))
                    stats['inserted'] += 1
                else:
                    # Material not found in database - skip this test
                    if i % 100 == 0:  # Only print occasionally to avoid spam
                        print(f"  Warning: Material '{record['designation']}' not found in DB, skipping {record['report_number']}")
                    if 'skipped_material_not_found' not in stats:
                        stats['skipped_material_not_found'] = 0
                    stats['skipped_material_not_found'] += 1

        if not dry_run:
            conn.commit()
            print("\nCommitted changes to database")
        else:
            print("\nDRY RUN - No changes committed")

        print("\nStatistics:")
        print(f"  Inserted new tests: {stats['inserted']}")
        print(f"  Updated media field: {stats['updated_media']}")
        print(f"  Skipped duplicates: {stats['skipped_duplicate']}")
        if stats['material_code_mismatch'] > 0:
            print(f"  Material code mismatches: {stats['material_code_mismatch']} (resolved by report number)")
        if stats.get('skipped_material_not_found', 0) > 0:
            print(f"  Skipped (material not in DB): {stats['skipped_material_not_found']}")

    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Import FC MAPTIS PDF data')
    parser.add_argument('--pdf', type=Path,
                        default=Path('C:/BoundState/docs/FC maptis.pdf'),
                        help='Path to FC MAPTIS PDF')
    parser.add_argument('--dry-run', action='store_true',
                        help='Extract and analyze without modifying database')

    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Error: PDF not found at {args.pdf}")
        return 1

    print(f"Extracting FC data from: {args.pdf}")
    records = extract_fc_data_from_pdf(args.pdf)

    if not records:
        print("No records extracted!")
        return 1

    # Show sample
    print("\nSample records:")
    for record in records[:5]:
        print(f"  {record}")

    print(f"\nPopulating database...")
    populate_database(records, dry_run=args.dry_run)

    print("\nDone!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
