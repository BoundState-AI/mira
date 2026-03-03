"""
MUA Precedents v7 - Traceability Backfill
=========================================

Backfills ``mua_precedents_v7.source_hash`` from raw PDF files using SHA-256,
without rerunning OCR/extraction.

Why this exists
---------------
The v7 loader (`002_load_mua_precedents.py`) only hydrated `source_hash` from
the historic JSONL fallback when rationale text existed. That left legitimate
rows with NULL `source_hash` even though `source_file` is present.

This script enforces document traceability by computing hashes from source PDFs
and updating only rows with missing hashes by default.

Usage
-----
Dry-run (default):
    py -3 mira/mua/v7/migrations/004_backfill_traceability.py

Apply updates:
    py -3 mira/mua/v7/migrations/004_backfill_traceability.py --apply

Override roots:
    py -3 mira/mua/v7/migrations/004_backfill_traceability.py --apply \\
      --pdf-root C:\\maptis-nlp\\data --pdf-root C:\\BoundState\\mira\\data\\mua_pdfs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import psycopg2
from psycopg2.extras import execute_values


DEFAULT_PDF_ROOTS = [
    Path(r"C:\maptis-nlp\data"),
    Path(r"C:\BoundState\mira\data\mua_pdfs"),
]


@dataclass
class RowRef:
    row_id: int
    mua_number: str
    source_file: str
    source_hash: Optional[str]


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _build_pdf_index(roots: Iterable[Path]) -> tuple[dict[str, Path], dict[str, list[str]]]:
    """
    Build a filename -> absolute path lookup.

    Returns:
        (unique_index, duplicates)
        - unique_index: lowercase filename -> unique Path
        - duplicates: lowercase filename -> list[str] when multiple paths found
    """
    seen: dict[str, list[Path]] = {}
    for root in roots:
        if not root.exists():
            continue
        for pdf in root.rglob("*.pdf"):
            key = pdf.name.lower()
            seen.setdefault(key, []).append(pdf)

    unique: dict[str, Path] = {}
    dups: dict[str, list[str]] = {}
    for key, paths in seen.items():
        if len(paths) == 1:
            unique[key] = paths[0]
        else:
            # Deterministic ordering for repeatability
            sorted_paths = sorted(str(p) for p in paths)
            dups[key] = sorted_paths
    return unique, dups


def _fetch_rows(conn, missing_only: bool = True) -> list[RowRef]:
    cur = conn.cursor()
    if missing_only:
        cur.execute(
            """
            SELECT id, mua_number, source_file, source_hash
            FROM mua_precedents_v7
            WHERE source_file IS NOT NULL
              AND trim(source_file) <> ''
              AND (source_hash IS NULL OR trim(source_hash) = '')
            ORDER BY id
            """
        )
    else:
        cur.execute(
            """
            SELECT id, mua_number, source_file, source_hash
            FROM mua_precedents_v7
            WHERE source_file IS NOT NULL
              AND trim(source_file) <> ''
            ORDER BY id
            """
        )
    rows = [RowRef(*r) for r in cur.fetchall()]
    cur.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill source_hash from raw PDFs.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist updates. Default is dry-run.",
    )
    parser.add_argument(
        "--verify-all",
        action="store_true",
        help="Check all rows (not only NULL hashes). Does not overwrite non-NULL hashes unless --apply and --overwrite are both set.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing source_hash values when --verify-all is used.",
    )
    parser.add_argument(
        "--pdf-root",
        action="append",
        default=[],
        help="Additional PDF roots (can be repeated).",
    )
    args = parser.parse_args()

    roots = list(DEFAULT_PDF_ROOTS) + [Path(p) for p in args.pdf_root]
    unique_index, duplicate_index = _build_pdf_index(roots)

    db_params = _load_db_params()
    conn = psycopg2.connect(**db_params)
    conn.autocommit = False

    try:
        rows = _fetch_rows(conn, missing_only=not args.verify_all)
        total = len(rows)

        updates: list[tuple[str, int]] = []
        verified_match = 0
        verified_mismatch = 0
        missing_pdf = 0
        ambiguous_pdf = 0
        skipped_existing = 0

        missing_samples: list[str] = []
        ambiguous_samples: list[dict[str, object]] = []
        mismatch_samples: list[dict[str, str]] = []

        hash_cache: dict[Path, str] = {}

        for row in rows:
            filename = Path(row.source_file).name.lower()

            if filename in duplicate_index:
                ambiguous_pdf += 1
                if len(ambiguous_samples) < 25:
                    ambiguous_samples.append(
                        {
                            "row_id": row.row_id,
                            "mua_number": row.mua_number,
                            "source_file": row.source_file,
                            "candidates": duplicate_index[filename],
                        }
                    )
                continue

            pdf_path = unique_index.get(filename)
            if not pdf_path:
                missing_pdf += 1
                if len(missing_samples) < 25:
                    missing_samples.append(row.source_file)
                continue

            file_hash = hash_cache.get(pdf_path)
            if not file_hash:
                file_hash = _sha256_file(pdf_path)
                hash_cache[pdf_path] = file_hash

            existing = (row.source_hash or "").strip().lower()
            if existing:
                skipped_existing += 1
                if existing == file_hash:
                    verified_match += 1
                else:
                    verified_mismatch += 1
                    if len(mismatch_samples) < 25:
                        mismatch_samples.append(
                            {
                                "row_id": str(row.row_id),
                                "mua_number": row.mua_number,
                                "source_file": row.source_file,
                                "existing_hash": existing,
                                "computed_hash": file_hash,
                            }
                        )
                    if args.overwrite:
                        updates.append((file_hash, row.row_id))
                continue

            updates.append((file_hash, row.row_id))

        if args.verify_all and not args.overwrite:
            # In verify mode, preserve existing hashes unless explicitly told to overwrite.
            # updates already includes only NULL rows from this branch.
            pass

        if not args.apply:
            conn.rollback()
        else:
            if updates:
                cur = conn.cursor()
                execute_values(
                    cur,
                    """
                    UPDATE mua_precedents_v7 AS v
                    SET source_hash = d.source_hash
                    FROM (VALUES %s) AS d(source_hash, row_id)
                    WHERE v.id = d.row_id
                    """,
                    updates,
                    page_size=500,
                )
                cur.close()
            conn.commit()

        mode = "APPLY" if args.apply else "DRY_RUN"
        print("=" * 72)
        print(f"TRACEABILITY BACKFILL ({mode})")
        print("=" * 72)
        print(f"Rows considered:            {total}")
        print(f"PDF index unique filenames: {len(unique_index)}")
        print(f"PDF index duplicates:       {len(duplicate_index)}")
        print(f"Hashes to set/update:       {len(updates)}")
        print(f"Verified hash matches:      {verified_match}")
        print(f"Verified hash mismatches:   {verified_mismatch}")
        print(f"Missing source PDFs:        {missing_pdf}")
        print(f"Ambiguous source PDFs:      {ambiguous_pdf}")
        print(f"Skipped existing hashes:    {skipped_existing}")

        report = {
            "mode": mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "rows_considered": total,
            "pdf_index_unique": len(unique_index),
            "pdf_index_duplicates": len(duplicate_index),
            "updates_count": len(updates),
            "verified_match": verified_match,
            "verified_mismatch": verified_mismatch,
            "missing_pdf": missing_pdf,
            "ambiguous_pdf": ambiguous_pdf,
            "missing_samples": missing_samples,
            "ambiguous_samples": ambiguous_samples,
            "mismatch_samples": mismatch_samples,
        }
        out_dir = Path(__file__).resolve().parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"004_backfill_traceability_{stamp}.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {out_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
