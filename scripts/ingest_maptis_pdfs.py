#!/usr/bin/env python3
"""
Module: Ingest MAPTIS PDFs
Purpose: Ingest MAPTIS PDF exports into PostgreSQL and regenerate FAISS index

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Usage:
    # Dry run (extract only, show results)
    python scripts/ingest_maptis_pdfs.py --materials floro.pdf --dry-run

    # Full ingest
    python scripts/ingest_maptis_pdfs.py --materials floro.pdf --flam flam.pdf --pneu pneu.pdf

    # With Bedrock
    python scripts/ingest_maptis_pdfs.py --materials floro.pdf --bedrock
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.maptis.pdf_extractor import MAPTISPDFExtractor, ExtractionResult


def insert_to_postgres(result: ExtractionResult, dry_run: bool = False):
    """
    Insert extracted data to PostgreSQL silver_report_rows.

    Schema: row_uid (uuid), contract_id (text), normalized_payload (jsonb), created_at (timestamp)
    The materialkey is stored INSIDE the normalized_payload jsonb field.
    """
    import psycopg2
    import uuid

    conn = psycopg2.connect(
        host='localhost',
        port=5432,
        database='mira',
        user='postgres',
        password='postgres'
    )
    cursor = conn.cursor()

    # Track what we insert
    inserted_materials = 0
    inserted_flam = 0
    inserted_pneu = 0

    try:
        # Insert materials as silver_report_rows with contract_id = 'materials_report'
        for mat in result.materials:
            # materialkey goes INSIDE the payload (matching existing schema)
            payload = {
                'materialkey': mat.material_key,
                'matl_designation': mat.matl_designation,
                'matl_materialcode': mat.matl_materialcode or mat.material_key,
                'matl_spec1': mat.matl_spec1,
                'matl_manufacturer': mat.matl_manufacturer,
                'matl_tradename': mat.matl_tradename,
            }

            if dry_run:
                print(f"  [DRY] Would insert material {mat.material_key}: {mat.matl_designation}")
            else:
                cursor.execute("""
                    INSERT INTO silver_report_rows
                    (row_uid, contract_id, normalized_payload)
                    VALUES (%s, %s, %s)
                """, (
                    str(uuid.uuid4()),
                    'materials_report',
                    json.dumps(payload),
                ))
            inserted_materials += 1

        # Insert flammability tests
        for test in result.flammability_tests:
            payload = {
                'materialkey': test.material_key,
                'flam_rating': test.flam_rating,
                'flam_gasname': test.flam_gasname,
                'flam_originalpercentoxygen': test.flam_originalpercentoxygen,
                'flam_testpressure': test.flam_testpressure,
                'flam_reportnumber': test.flam_reportnumber,
            }

            if dry_run:
                o2_pct = test.flam_originalpercentoxygen or 0
                print(f"  [DRY] Would insert flam test {test.material_key}: rating={test.flam_rating}, O2={o2_pct}%")
            else:
                cursor.execute("""
                    INSERT INTO silver_report_rows
                    (row_uid, contract_id, normalized_payload)
                    VALUES (%s, %s, %s)
                """, (
                    str(uuid.uuid4()),
                    'flammability_report',
                    json.dumps(payload),
                ))
            inserted_flam += 1

        # Insert pneumatic tests
        for test in result.pneumatic_tests:
            payload = {
                'materialkey': test.material_key,
                'pneu_rating': test.pneu_rating,
                'pneu_gasname': test.pneu_gasname,
                'pneu_testpressure': test.pneu_testpressure,
                'pneu_reportnumber': test.pneu_reportnumber,
            }

            if dry_run:
                print(f"  [DRY] Would insert pneu test {test.material_key}: rating={test.pneu_rating}")
            else:
                cursor.execute("""
                    INSERT INTO silver_report_rows
                    (row_uid, contract_id, normalized_payload)
                    VALUES (%s, %s, %s)
                """, (
                    str(uuid.uuid4()),
                    'pneumatic_impact_report',
                    json.dumps(payload),
                ))
            inserted_pneu += 1

        if not dry_run:
            conn.commit()

    finally:
        cursor.close()
        conn.close()

    return inserted_materials, inserted_flam, inserted_pneu


def main():
    parser = argparse.ArgumentParser(
        description="Ingest MAPTIS PDF exports into PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - extract and show what would be inserted
  python scripts/ingest_maptis_pdfs.py --materials floro.pdf --dry-run

  # Full ingest from all three PDFs
  python scripts/ingest_maptis_pdfs.py \\
      --materials "C:\\Users\\jwilde2\\Documents\\floro.pdf" \\
      --flam "C:\\Users\\jwilde2\\Documents\\flam.pdf" \\
      --pneu "C:\\Users\\jwilde2\\Documents\\pneu.pdf"

  # Use AWS Bedrock instead of direct API
  python scripts/ingest_maptis_pdfs.py --materials floro.pdf --bedrock
        """
    )
    parser.add_argument(
        "--materials",
        type=Path,
        help="Material family report PDF"
    )
    parser.add_argument(
        "--flam",
        type=Path,
        help="Flammability test report PDF"
    )
    parser.add_argument(
        "--pneu",
        type=Path,
        help="Pneumatic test report PDF"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract only, don't insert to database"
    )
    parser.add_argument(
        "--bedrock",
        action="store_true",
        help="Use AWS Bedrock instead of direct Anthropic API"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save extracted JSON to file"
    )

    args = parser.parse_args()

    if not any([args.materials, args.flam, args.pneu]):
        parser.error("At least one PDF must be specified (--materials, --flam, or --pneu)")

    # Initialize extractor
    print("=" * 60)
    print("MAPTIS PDF Ingest Pipeline")
    print("=" * 60)

    extractor = MAPTISPDFExtractor(use_bedrock=args.bedrock)

    # Extract from each PDF
    result = ExtractionResult()

    if args.materials:
        if not args.materials.exists():
            print(f"ERROR: Materials PDF not found: {args.materials}")
            sys.exit(1)
        print(f"\n[1/3] Extracting materials from {args.materials.name}...")
        result.materials = extractor.extract_materials(args.materials)
        print(f"      Found {len(result.materials)} materials")

    if args.flam:
        if not args.flam.exists():
            print(f"ERROR: Flammability PDF not found: {args.flam}")
            sys.exit(1)
        print(f"\n[2/3] Extracting flammability tests from {args.flam.name}...")
        result.flammability_tests = extractor.extract_flammability_tests(args.flam)
        print(f"      Found {len(result.flammability_tests)} tests")

    if args.pneu:
        if not args.pneu.exists():
            print(f"ERROR: Pneumatic PDF not found: {args.pneu}")
            sys.exit(1)
        print(f"\n[3/3] Extracting pneumatic tests from {args.pneu.name}...")
        result.pneumatic_tests = extractor.extract_pneumatic_tests(args.pneu)
        print(f"      Found {len(result.pneumatic_tests)} tests")

    # Show summary
    print("\n" + "=" * 60)
    print("Extraction Summary")
    print("=" * 60)
    print(f"  Materials:         {len(result.materials)}")
    print(f"  Flammability tests: {len(result.flammability_tests)}")
    print(f"  Pneumatic tests:    {len(result.pneumatic_tests)}")

    if result.errors:
        print(f"\n  Errors: {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err}")

    # Save JSON if requested
    if args.output:
        output_data = {
            'materials': [m.model_dump() for m in result.materials],
            'flammability_tests': [t.model_dump() for t in result.flammability_tests],
            'pneumatic_tests': [t.model_dump() for t in result.pneumatic_tests],
        }
        args.output.write_text(json.dumps(output_data, indent=2))
        print(f"\nSaved extracted data to: {args.output}")

    # Show sample data
    if result.materials:
        print("\n" + "-" * 60)
        print("Sample Materials (first 5):")
        print("-" * 60)
        for mat in result.materials[:5]:
            print(f"  {mat.material_key}: {mat.matl_designation[:50]}...")

    if result.flammability_tests:
        print("\n" + "-" * 60)
        print("Sample Flammability Tests (first 5):")
        print("-" * 60)
        for test in result.flammability_tests[:5]:
            o2 = test.flam_originalpercentoxygen or 0
            print(f"  {test.material_key}: rating={test.flam_rating}, gas={test.flam_gasname}, O2={o2}%")

    # Insert to database
    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN - No database changes made")
        print("=" * 60)
        print("\nWould insert:")
        insert_to_postgres(result, dry_run=True)
    else:
        print("\n" + "=" * 60)
        print("Inserting to PostgreSQL...")
        print("=" * 60)
        n_mat, n_flam, n_pneu = insert_to_postgres(result, dry_run=False)
        print(f"\nInserted:")
        print(f"  Materials:         {n_mat}")
        print(f"  Flammability tests: {n_flam}")
        print(f"  Pneumatic tests:    {n_pneu}")

        print("\n" + "=" * 60)
        print("NEXT STEPS")
        print("=" * 60)
        print("1. Regenerate FAISS index to include new materials:")
        print("   python scripts/rebuild_faiss_index.py")
        print("\n2. Restart the API server")
        print("\n3. Test search in Knowledge Twins")


if __name__ == "__main__":
    main()
