#!/usr/bin/env python3
"""Upsert FC vision-v2 records into maptis.fluid_compatibility_tests.

Target input:
    C:/BoundState/temp/fc_vision_v2.json

Behavior:
1) Normalize designation strings (strip trademark symbols/mojibake).
2) Resolve a single material_code by designation match against materials table.
3) Upsert using unique key:
       (material_code, test_report_no, test_no_type)
4) Set source='FC_VISION_V2' for all inserted/updated rows.

This script is intentionally idempotent.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.core.db_config import get_db_connection_params


TEST_NO_TYPE = "Fluid Comp"
IMPORT_SOURCE = "FC_VISION_V2"


def normalize_designation(text: str) -> str:
    """Normalize designation text for reliable matching."""
    value = str(text or "")

    # Remove trademark symbols and common mojibake variants.
    for symbol in ["™", "®", "©", "℠", "â„¢", "Â®", "Â©", "â„ ", "ï¿½"]:
        value = value.replace(symbol, "")

    # Collapse whitespace and normalize casing for dictionary lookup.
    return " ".join(value.split()).strip().upper()


def normalize_optional_text(text: Any) -> str | None:
    """Normalize optional free-text fields to stripped text/None."""
    if text is None:
        return None
    value = str(text).strip()
    return value if value else None


def normalize_rating(value: Any) -> str | None:
    """Normalize rating to a single-character code or None."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text or text in {"-", "N/A", "NA"}:
        return None
    return text[0]


def load_material_maps(cur) -> tuple[dict[str, list[int]], dict[str, int]]:
    """Build designation->material_code candidate map and FC-history preference map."""
    cur.execute("SELECT material_code, designation FROM materials")
    rows = cur.fetchall()

    candidates_by_designation: dict[str, list[int]] = defaultdict(list)
    for material_code, designation in rows:
        candidates_by_designation[normalize_designation(designation)].append(material_code)

    # Keep candidate ordering stable.
    for key in list(candidates_by_designation.keys()):
        candidates_by_designation[key] = sorted(set(candidates_by_designation[key]))

    # FC history preference: if same designation already appears in FC tests,
    # reuse the most frequent material_code for that designation.
    cur.execute(
        """
        SELECT
            UPPER(TRIM(m.designation)) AS designation_norm,
            f.material_code,
            COUNT(*) AS row_count
        FROM fluid_compatibility_tests f
        JOIN materials m ON m.material_code = f.material_code
        GROUP BY 1, 2
        """
    )
    history_rows = cur.fetchall()

    history_by_designation: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for designation_norm, material_code, row_count in history_rows:
        history_by_designation[designation_norm].append((material_code, row_count))

    history_preferred_code: dict[str, int] = {}
    for designation_norm, entries in history_by_designation.items():
        # Highest FC row_count wins; tie-breaker smallest material_code.
        best_code, _ = sorted(entries, key=lambda x: (-x[1], x[0]))[0]
        history_preferred_code[designation_norm] = best_code

    return dict(candidates_by_designation), history_preferred_code


def resolve_material_code(
    record: dict[str, Any],
    designation_norm: str,
    candidates_by_designation: dict[str, list[int]],
    history_preferred_code: dict[str, int],
) -> tuple[int | None, str]:
    """Resolve material_code for an extracted record."""
    candidates = candidates_by_designation.get(designation_norm, [])
    if not candidates:
        return None, "no_designation_match"

    if len(candidates) == 1:
        return candidates[0], "exact_single"

    # Prefer extracted material_code when it is a valid candidate.
    extracted_code = record.get("material_code")
    if isinstance(extracted_code, int) and extracted_code in candidates:
        return extracted_code, "preferred_extracted_code"

    # Prefer whichever code has historical FC records for this designation.
    hist_code = history_preferred_code.get(designation_norm)
    if hist_code is not None and hist_code in candidates:
        return hist_code, "preferred_fc_history"

    # Deterministic fallback for ambiguous designations.
    return candidates[0], "ambiguous_lowest_code"


def classify_existing_state(
    cur,
    material_code: int,
    report_no: str,
    test_no_type: str,
    rating: str | None,
    media: str | None,
) -> str:
    """Return one of: will_insert, will_update, unchanged_conflict."""
    cur.execute(
        """
        SELECT rating, media, source
        FROM fluid_compatibility_tests
        WHERE material_code = %s
          AND test_report_no = %s
          AND test_no_type = %s
        """,
        (material_code, report_no, test_no_type),
    )
    row = cur.fetchone()
    if not row:
        return "will_insert"

    existing_rating, existing_media, existing_source = row
    normalized_existing_source = (existing_source or "").strip()
    target_media = media if media is not None else existing_media
    target_rating = rating if rating is not None else existing_rating

    if (
        existing_rating == target_rating
        and existing_media == target_media
        and normalized_existing_source == IMPORT_SOURCE
    ):
        return "unchanged_conflict"
    return "will_update"


def import_fc_records(
    json_path: Path,
    dry_run: bool = True,
    unmatched_out: Path | None = None,
) -> None:
    """Import/upsert FC records from extracted JSON."""
    print(f"Loading extraction: {json_path}")
    with json_path.open("r", encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        raise ValueError("Input JSON must be a list of records.")

    print(f"Loaded {len(records):,} records")

    config = get_db_connection_params(options="-c search_path=maptis,public")
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    stats = Counter()
    resolution_stats = Counter()
    unmatched_records: list[dict[str, Any]] = []

    cur.execute("SELECT COUNT(*) FROM fluid_compatibility_tests")
    before_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM fluid_compatibility_tests WHERE source = %s", (IMPORT_SOURCE,))
    before_source = cur.fetchone()[0]

    candidates_by_designation, history_preferred_code = load_material_maps(cur)
    print(f"Loaded material designation map: {len(candidates_by_designation):,} unique designations")

    upsert_sql = """
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
            %s, %s, %s, %s, %s, %s, 'N', 'N'
        )
        ON CONFLICT (material_code, test_report_no, test_no_type)
        DO UPDATE SET
            rating = COALESCE(EXCLUDED.rating, fluid_compatibility_tests.rating),
            media = COALESCE(EXCLUDED.media, fluid_compatibility_tests.media),
            source = EXCLUDED.source,
            material_change_flag = COALESCE(fluid_compatibility_tests.material_change_flag, 'N'),
            fluid_change_flag = COALESCE(fluid_compatibility_tests.fluid_change_flag, 'N')
    """

    try:
        for idx, record in enumerate(records, start=1):
            if idx % 250 == 0:
                print(f"  Processing {idx:,}/{len(records):,}...")

            designation_raw = str(record.get("designation") or "")
            designation_norm = normalize_designation(designation_raw)

            material_code, resolution = resolve_material_code(
                record=record,
                designation_norm=designation_norm,
                candidates_by_designation=candidates_by_designation,
                history_preferred_code=history_preferred_code,
            )
            resolution_stats[resolution] += 1

            if material_code is None:
                stats["unmatched_material"] += 1
                if len(unmatched_records) < 5000:
                    unmatched_records.append(
                        {
                            "record_num": idx,
                            "designation": designation_norm,
                            "original_designation": designation_raw,
                            "report_number": record.get("report_number"),
                            "media": record.get("media"),
                            "rating": record.get("rating"),
                            "reason": resolution,
                        }
                    )
                continue

            report_no = normalize_optional_text(record.get("report_number")) or "Report"
            media = normalize_optional_text(record.get("media"))
            rating = normalize_rating(record.get("rating"))

            outcome = classify_existing_state(
                cur=cur,
                material_code=material_code,
                report_no=report_no,
                test_no_type=TEST_NO_TYPE,
                rating=rating,
                media=media,
            )
            stats[outcome] += 1

            if dry_run:
                continue

            cur.execute(
                upsert_sql,
                (
                    material_code,
                    report_no,
                    TEST_NO_TYPE,
                    rating,
                    media,
                    IMPORT_SOURCE,
                ),
            )

        if dry_run:
            conn.rollback()
            print("\nDRY RUN complete (no changes committed).")
        else:
            conn.commit()
            print("\nImport committed.")

        cur.execute("SELECT COUNT(*) FROM fluid_compatibility_tests")
        after_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM fluid_compatibility_tests WHERE source = %s", (IMPORT_SOURCE,))
        after_source = cur.fetchone()[0]

        print("\n" + "=" * 72)
        print("FC VISION V2 UPSERT SUMMARY")
        print("=" * 72)
        print(f"Records processed:               {len(records):,}")
        print(f"Will insert / inserted:         {stats['will_insert']:,}")
        print(f"Will update / updated:          {stats['will_update']:,}")
        print(f"Unchanged conflicts:            {stats['unchanged_conflict']:,}")
        print(f"Unmatched material designation: {stats['unmatched_material']:,}")
        print("-" * 72)
        print(f"Rows before (all sources):      {before_total:,}")
        print(f"Rows after  (all sources):      {after_total:,}")
        print(f"Delta rows (all sources):       {after_total - before_total:+,}")
        print(f"{IMPORT_SOURCE} rows before:      {before_source:,}")
        print(f"{IMPORT_SOURCE} rows after:       {after_source:,}")
        print(f"{IMPORT_SOURCE} row delta:        {after_source - before_source:+,}")
        print("-" * 72)
        print("Material resolution modes:")
        for mode, count in sorted(resolution_stats.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {mode:24} {count:,}")

        if unmatched_out:
            unmatched_out.parent.mkdir(parents=True, exist_ok=True)
            with unmatched_out.open("w", encoding="utf-8") as f:
                json.dump(unmatched_records, f, indent=2)
            print(f"\nUnmatched record details written: {unmatched_out}")

    finally:
        cur.close()
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upsert FC Vision V2 extraction into MAPTIS table")
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("C:/BoundState/temp/fc_vision_v2.json"),
        help="Path to fc_vision_v2 JSON extraction",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute import (default is dry-run)",
    )
    parser.add_argument(
        "--unmatched-out",
        type=Path,
        default=Path("C:/BoundState/temp/fc_import_v2_unmatched.json"),
        help="Where to write unmatched material records",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.json.exists():
        print(f"ERROR: extraction file not found: {args.json}")
        return 1

    import_fc_records(
        json_path=args.json,
        dry_run=not args.execute,
        unmatched_out=args.unmatched_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
