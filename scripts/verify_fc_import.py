#!/usr/bin/env python3
"""Verify FC MAPTIS import - check for duplicates and data quality."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.core.db_config import get_db_connection_params


def verify_fc_data():
    """Verify fluid compatibility data in database."""

    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    print("="*60)
    print("FC MAPTIS Data Verification")
    print("="*60)

    # 1. Total row count
    cur.execute("SELECT COUNT(*) FROM fluid_compatibility_tests")
    total_tests = cur.fetchone()[0]
    print(f"\n1. Total FC tests: {total_tests:,}")

    # 2. Check for duplicate test_report_no
    cur.execute("""
        SELECT test_report_no, COUNT(*) as count
        FROM fluid_compatibility_tests
        GROUP BY test_report_no
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 10
    """)
    dupes = cur.fetchall()

    if dupes:
        print(f"\n2. WARNING: Duplicate test_report_no found: {len(dupes)}")
        print("   Top duplicates:")
        for report_no, count in dupes[:5]:
            print(f"     {report_no}: {count} occurrences")
    else:
        print("\n2. OK: No duplicate test_report_no entries")

    # 3. Check media field population
    cur.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(media) as with_media,
            COUNT(*) - COUNT(media) as null_media
        FROM fluid_compatibility_tests
    """)
    total, with_media, null_media = cur.fetchone()
    media_pct = (with_media / total * 100) if total > 0 else 0

    print(f"\n3. Media field coverage:")
    print(f"   Total tests: {total:,}")
    print(f"   With media: {with_media:,} ({media_pct:.1f}%)")
    print(f"   NULL media: {null_media:,}")

    # 4. Source breakdown
    cur.execute("""
        SELECT source, COUNT(*) as count
        FROM fluid_compatibility_tests
        GROUP BY source
        ORDER BY count DESC
    """)
    sources = cur.fetchall()

    print(f"\n4. Data sources:")
    for source, count in sources:
        pct = (count / total * 100) if total > 0 else 0
        print(f"   {source or 'NULL'}: {count:,} ({pct:.1f}%)")

    # 5. Rating distribution
    cur.execute("""
        SELECT rating, COUNT(*) as count
        FROM fluid_compatibility_tests
        GROUP BY rating
        ORDER BY count DESC
    """)
    ratings = cur.fetchall()

    print(f"\n5. Rating distribution:")
    for rating, count in ratings:
        pct = (count / total * 100) if total > 0 else 0
        print(f"   {rating}: {count:,} ({pct:.1f}%)")

    # 6. Recent imports (FC_VISION_V2 source)
    cur.execute("""
        SELECT COUNT(*)
        FROM fluid_compatibility_tests
        WHERE source = 'FC_VISION_V2'
    """)
    vision_count = cur.fetchone()[0]

    print(f"\n6. Recent vision import:")
    print(f"   FC_VISION_V2 records: {vision_count:,}")

    # 7. Sample records with media
    cur.execute("""
        SELECT test_report_no, rating, media, source
        FROM fluid_compatibility_tests
        WHERE media IS NOT NULL
        ORDER BY id DESC
        LIMIT 5
    """)
    samples = cur.fetchall()

    print(f"\n7. Sample records with media (most recent):")
    for report_no, rating, media, source in samples:
        print(f"   {report_no} | {rating} | {media[:50] if media else 'NULL'} | {source}")

    # 8. Check for identical duplicates (same test_report_no AND media)
    cur.execute("""
        SELECT test_report_no, media, COUNT(*) as count
        FROM fluid_compatibility_tests
        WHERE media IS NOT NULL
        GROUP BY test_report_no, media
        HAVING COUNT(*) > 1
        LIMIT 5
    """)
    exact_dupes = cur.fetchall()

    if exact_dupes:
        print(f"\n8. WARNING: Exact duplicates (same report_no + media):")
        for report_no, media, count in exact_dupes:
            print(f"   {report_no} | {media[:40]} | {count} copies")
    else:
        print(f"\n8. OK: No exact duplicates found")

    print("\n" + "="*60)
    print("Verification Complete")
    print("="*60)

    cur.close()
    conn.close()


if __name__ == '__main__':
    verify_fc_data()
