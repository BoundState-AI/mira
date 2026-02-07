#!/usr/bin/env python3
"""
Human Review CLI for Vision Extraction Learning.

Interactive tool for reviewing and correcting Vision extractions.
Corrections are recorded in the database for future learning.

Claude Vision extracts part numbers from rendered drawing images.
This tool helps correct Vision's character recognition errors
(e.g., 0/O confusion, similar-looking digits) and trains the
system to auto-correct similar errors in the future.

Usage:
    python -m mira.miul.v3.ocr_review review <needs_review.json>
    python -m mira.miul.v3.ocr_review stats
    python -m mira.miul.v3.ocr_review export-corrections <output.json>

BoundState AI 2025
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ocr_learning import OCRLearningDB, fuzzy_match_list

logging.basicConfig(level=logging.INFO, format="%(message)s")
LOGGER = logging.getLogger(__name__)


def print_header(text: str):
    """Print a formatted header for Vision review output."""
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)


def print_item(item: Dict[str, Any], idx: int, total: int):
    """Print a single review item."""
    print(f"\n--- Item {idx + 1}/{total} ---")
    print(f"Find No:     {item.get('find_no', '?')}")
    print(f"Raw:         {item.get('raw', '?')}")
    print(f"Expected:    {item.get('expected', '?')}")
    print(f"Description: {item.get('description', '')[:60]}")


def get_user_choice(prompt: str, options: List[str]) -> str:
    """Get user input with validation."""
    while True:
        choice = input(prompt).strip().lower()
        if choice in options:
            return choice
        print(f"Invalid choice. Options: {', '.join(options)}")


def interactive_review(review_file: Path, db: OCRLearningDB = None):
    """
    Interactive review of items needing human correction.

    For each item:
    - Show raw extraction and expected value
    - Ask user to confirm expected is correct
    - Record correction in database for learning

    Args:
        review_file: Path to JSON file with items needing review
        db: Optional database connection (created if not provided)
    """
    # Load review items
    with open(review_file, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not items:
        print("No items to review!")
        return

    print_header(f"Vision Extraction Review: {len(items)} items to review")

    # Connect to DB if not provided
    close_db = False
    if db is None:
        db = OCRLearningDB()
        close_db = True

    # Get all known parts for suggestions
    with db.conn.cursor() as cur:
        cur.execute("SELECT part_number FROM known_parts")
        all_known = [row[0] for row in cur.fetchall()]

    corrections_made = 0
    skipped = 0
    remaining = []

    for idx, item in enumerate(items):
        print_item(item, idx, len(items))

        raw = item.get("raw", "").strip().upper()
        expected = item.get("expected", "").strip().upper()
        description = item.get("description", "")

        # Show fuzzy suggestions
        suggestions = fuzzy_match_list(raw, all_known, min_similarity=0.4, limit=5)
        if suggestions:
            print("\nSuggestions (similarity):")
            for i, (pn, sim) in enumerate(suggestions, 1):
                marker = " <-- expected" if pn.upper() == expected else ""
                print(f"  {i}. {pn} ({sim:.2f}){marker}")

        print(f"\nOptions:")
        print(f"  [a] Accept expected: {expected}")
        print(f"  [1-5] Select suggestion")
        print(f"  [c] Enter custom correction")
        print(f"  [s] Skip this item")
        print(f"  [q] Quit review")

        choice = input("\nChoice: ").strip().lower()

        if choice == "q":
            # Save remaining items
            remaining = items[idx:]
            break

        elif choice == "s":
            skipped += 1
            remaining.append(item)
            continue

        elif choice == "a":
            # Accept expected value
            corrected = expected

        elif choice in "12345" and suggestions:
            # Select suggestion
            try:
                selected_idx = int(choice) - 1
                if 0 <= selected_idx < len(suggestions):
                    corrected = suggestions[selected_idx][0].upper()
                else:
                    print("Invalid selection, skipping")
                    remaining.append(item)
                    continue
            except (ValueError, IndexError):
                print("Invalid selection, skipping")
                remaining.append(item)
                continue

        elif choice == "c":
            # Custom correction
            corrected = input("Enter correct part number: ").strip().upper()
            if not corrected:
                print("Empty input, skipping")
                remaining.append(item)
                continue

            # Add to known parts if new
            if not db.is_known_part(corrected):
                add_new = input(f"'{corrected}' not in known parts. Add it? [y/n]: ").strip().lower()
                if add_new == "y":
                    desc_input = input(f"Description [{description[:50]}]: ").strip()
                    db.add_known_part(
                        corrected,
                        description=desc_input or description,
                        source="MANUAL",
                        verified_by="human_review"
                    )
                    print(f"Added {corrected} to known parts")

        else:
            print("Invalid choice, skipping")
            remaining.append(item)
            continue

        # Record the correction
        if db.record_correction(
            raw,
            corrected,
            drawing_source=item.get("drawing_source", ""),
            find_no=item.get("find_no", ""),
            description_context=description,
            confidence=0.95  # High confidence for human-verified
        ):
            corrections_made += 1
            print(f"✓ Recorded: {raw} -> {corrected}")
        else:
            print(f"✗ Failed to record correction (is {corrected} in known_parts?)")
            remaining.append(item)

    # Summary
    print_header("Review Complete")
    print(f"Corrections made: {corrections_made}")
    print(f"Skipped: {skipped}")
    print(f"Remaining: {len(remaining)}")

    # Save remaining items
    if remaining:
        remaining_file = review_file.with_suffix(".remaining.json")
        with open(remaining_file, "w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2)
        print(f"Saved {len(remaining)} remaining items to {remaining_file}")

    if close_db:
        db.close()


def show_stats(db: OCRLearningDB = None):
    """Show Vision extraction learning database statistics."""
    close_db = False
    if db is None:
        db = OCRLearningDB()
        close_db = True

    print_header("Vision Extraction Learning Statistics")

    with db.conn.cursor() as cur:
        # Known parts
        cur.execute("SELECT COUNT(*) FROM known_parts")
        known_count = cur.fetchone()[0]
        print(f"Known parts: {known_count}")

        # By source
        cur.execute("""
            SELECT source, COUNT(*) as cnt
            FROM known_parts
            GROUP BY source
            ORDER BY cnt DESC
        """)
        print("\n  By source:")
        for row in cur.fetchall():
            print(f"    {row[0]}: {row[1]}")

        # Corrections
        cur.execute("SELECT COUNT(*) FROM ocr_corrections")
        corrections_count = cur.fetchone()[0]
        print(f"\nLearned corrections: {corrections_count}")

        # Auto-correct enabled
        cur.execute("SELECT COUNT(*) FROM ocr_corrections WHERE auto_correct = TRUE")
        auto_count = cur.fetchone()[0]
        print(f"  Auto-correct enabled: {auto_count}")

        # Most common corrections
        cur.execute("""
            SELECT raw_extraction, corrected_to, correction_count, confidence
            FROM ocr_corrections
            ORDER BY correction_count DESC
            LIMIT 10
        """)
        rows = cur.fetchall()
        if rows:
            print("\n  Top corrections:")
            for raw, corrected, count, conf in rows:
                print(f"    {raw} -> {corrected} (count={count}, conf={conf:.2f})")

        # Audit log
        cur.execute("SELECT COUNT(*) FROM extraction_audit")
        audit_count = cur.fetchone()[0]
        print(f"\nExtraction audits: {audit_count}")

        cur.execute("SELECT COUNT(*) FROM extraction_audit WHERE correction_applied = TRUE")
        corrected_count = cur.fetchone()[0]
        print(f"  Corrections applied: {corrected_count}")

        cur.execute("SELECT COUNT(*) FROM extraction_audit WHERE human_verified = TRUE")
        verified_count = cur.fetchone()[0]
        print(f"  Human verified: {verified_count}")

    if close_db:
        db.close()


def export_corrections(output_file: Path, db: OCRLearningDB = None):
    """Export all learned corrections to JSON."""
    close_db = False
    if db is None:
        db = OCRLearningDB()
        close_db = True

    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT raw_extraction, corrected_to, confidence, correction_count, auto_correct
            FROM ocr_corrections
            ORDER BY correction_count DESC
        """)
        rows = cur.fetchall()

    corrections = [
        {
            "raw": row[0],
            "corrected": row[1],
            "confidence": row[2],
            "count": row[3],
            "auto_correct": row[4],
        }
        for row in rows
    ]

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(corrections, f, indent=2)

    print(f"Exported {len(corrections)} corrections to {output_file}")

    if close_db:
        db.close()


def batch_add_corrections(corrections_file: Path, db: OCRLearningDB = None):
    """
    Batch add corrections from a JSON file.

    File format:
    [
        {"raw": "01-625-08N", "corrected": "01-885-06K"},
        ...
    ]
    """
    close_db = False
    if db is None:
        db = OCRLearningDB()
        close_db = True

    with open(corrections_file, "r", encoding="utf-8") as f:
        corrections = json.load(f)

    added = 0
    for corr in corrections:
        raw = corr.get("raw", "").strip().upper()
        corrected = corr.get("corrected", "").strip().upper()

        if not raw or not corrected:
            continue

        # Ensure corrected is in known_parts
        if not db.is_known_part(corrected):
            db.add_known_part(corrected, source="BATCH_IMPORT")

        if db.record_correction(raw, corrected, confidence=0.9):
            added += 1

    print(f"Added {added} corrections from {corrections_file}")

    if close_db:
        db.close()


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m mira.miul.v3.ocr_review <command> [args]")
        print("\nCommands:")
        print("  review <needs_review.json>  - Interactive review of extractions")
        print("  stats                       - Show database statistics")
        print("  export <output.json>        - Export learned corrections")
        print("  batch <corrections.json>    - Batch import corrections")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "review":
        if len(sys.argv) < 3:
            print("Usage: review <needs_review.json>")
            sys.exit(1)
        review_file = Path(sys.argv[2])
        if not review_file.exists():
            print(f"File not found: {review_file}")
            sys.exit(1)
        interactive_review(review_file)

    elif cmd == "stats":
        show_stats()

    elif cmd == "export":
        if len(sys.argv) < 3:
            print("Usage: export <output.json>")
            sys.exit(1)
        export_corrections(Path(sys.argv[2]))

    elif cmd == "batch":
        if len(sys.argv) < 3:
            print("Usage: batch <corrections.json>")
            sys.exit(1)
        batch_add_corrections(Path(sys.argv[2]))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
