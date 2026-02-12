#!/usr/bin/env python3
"""Deduplicate fluid_compatibility_tests table - remove exact duplicates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.core.db_config import get_db_connection_params


def deduplicate_fc_tests(dry_run: bool = True):
    """Remove exact duplicate FC test records.

    Strategy:
    - Find all (test_report_no, media) pairs with multiple rows
    - Keep the record with the lowest ID (oldest)
    - Delete the duplicates
    """

    config = get_db_connection_params(options='-c search_path=maptis,public')
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    print("="*60)
    print("FC Tests Deduplication")
    print("="*60)

    # 1. Find duplicate groups
    cur.execute("""
        SELECT test_report_no, media, COUNT(*) as count
        FROM fluid_compatibility_tests
        WHERE test_report_no IS NOT NULL
        GROUP BY test_report_no, media
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    """)
    duplicate_groups = cur.fetchall()

    if not duplicate_groups:
        print("\nNo duplicates found!")
        cur.close()
        conn.close()
        return

    total_dupes = sum(count - 1 for _, _, count in duplicate_groups)
    print(f"\nFound {len(duplicate_groups)} duplicate groups")
    print(f"Total duplicate records to delete: {total_dupes}")

    # Show top duplicates
    print(f"\nTop 10 duplicate groups:")
    for report_no, media, count in duplicate_groups[:10]:
        media_str = media[:40] if media else "NULL"
        print(f"  {report_no} | {media_str} | {count} copies")

    # 2. Identify records to delete
    delete_ids = []

    for report_no, media in [(rn, m) for rn, m, _ in duplicate_groups]:
        # Get all IDs for this duplicate group
        if media is None:
            cur.execute("""
                SELECT id
                FROM fluid_compatibility_tests
                WHERE test_report_no = %s AND media IS NULL
                ORDER BY id
            """, (report_no,))
        else:
            cur.execute("""
                SELECT id
                FROM fluid_compatibility_tests
                WHERE test_report_no = %s AND media = %s
                ORDER BY id
            """, (report_no, media))

        ids = [row[0] for row in cur.fetchall()]

        # Keep first ID (oldest), delete the rest
        if len(ids) > 1:
            delete_ids.extend(ids[1:])

    print(f"\nRecords to delete: {len(delete_ids)}")

    # 3. Delete duplicates
    if delete_ids:
        if dry_run:
            print("\nDRY RUN - No changes will be made")
            print(f"Would delete {len(delete_ids)} duplicate records")

            # Show some example IDs that would be deleted
            print(f"\nExample IDs to delete (first 20):")
            for del_id in delete_ids[:20]:
                cur.execute("""
                    SELECT test_report_no, media, source
                    FROM fluid_compatibility_tests
                    WHERE id = %s
                """, (del_id,))
                report_no, media, source = cur.fetchone()
                media_str = media[:40] if media else "NULL"
                print(f"  ID {del_id}: {report_no} | {media_str} | {source}")
        else:
            print(f"\nDeleting {len(delete_ids)} duplicate records...")

            # Delete in batches of 100
            batch_size = 100
            for i in range(0, len(delete_ids), batch_size):
                batch = delete_ids[i:i+batch_size]
                cur.execute("""
                    DELETE FROM fluid_compatibility_tests
                    WHERE id = ANY(%s)
                """, (batch,))
                print(f"  Deleted batch {i//batch_size + 1}/{(len(delete_ids)-1)//batch_size + 1}")

            conn.commit()
            print(f"\nSuccessfully deleted {len(delete_ids)} duplicate records")

    # 4. Verify results
    cur.execute("SELECT COUNT(*) FROM fluid_compatibility_tests")
    final_count = cur.fetchone()[0]

    cur.execute("""
        SELECT test_report_no, media, COUNT(*) as count
        FROM fluid_compatibility_tests
        WHERE test_report_no IS NOT NULL
        GROUP BY test_report_no, media
        HAVING COUNT(*) > 1
    """)
    remaining_dupes = cur.fetchall()

    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"Total records after deduplication: {final_count:,}")
    print(f"Remaining duplicates: {len(remaining_dupes)}")

    if remaining_dupes and not dry_run:
        print("\nWARNING: Some duplicates still remain!")
        for report_no, media, count in remaining_dupes[:5]:
            media_str = media[:40] if media else "NULL"
            print(f"  {report_no} | {media_str} | {count} copies")

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='Deduplicate FC tests')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Preview changes without deleting (default)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually delete duplicates (use with caution)')

    args = parser.parse_args()

    # Default to dry-run unless --execute is specified
    dry_run = not args.execute

    if not dry_run:
        print("WARNING: This will DELETE duplicate records!")
        response = input("Are you sure? Type 'yes' to continue: ")
        if response.lower() != 'yes':
            print("Aborted.")
            return 1

    deduplicate_fc_tests(dry_run=dry_run)

    return 0


if __name__ == '__main__':
    sys.exit(main())
