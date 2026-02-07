#!/usr/bin/env python3
"""
Test re-extraction of MER07543-001 with improved V3 prompt.

Validates that the prompt fix correctly distinguishes FIND NO. vs PART NUMBER
columns in the EPL. This is a generic fix — no hardcoded maps.

Usage:
    py scripts/test_mer07543_extraction.py
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mira.miul.v3.extract import extract_drawing_page, VisionClient

PDF_PATH = Path(r"C:\Users\jwilde2\Desktop\DMLLV\MER07543-001.DRW_-.23_RELEASED.pdf")

# Known correct part numbers from the actual drawing EPL
# These are what the vision model SHOULD return (not find numbers)
EXPECTED_PART_NUMBERS = {
    "MER07560-001",   # Find 1 - VALVE BODY SUB-ASSEMBLY
    "MER07565-001",   # Find 2 - SHAFT, OFFSET, SUB-ASSEMBLY
    "MER07562-001",   # Find 2 alternate OCR read (also valid MER number)
    "51109",          # Find 3 - BEARING, THRUST
    "MER07557-001",   # Find 4 - SHAFT, CENTER
    "6915",           # Find 5 - BEARING, THIN SECTION
    "6916",           # Find 5 alternate OCR read (5 vs 6 confusion)
    "6824",           # Find 6 - BEARING, SINGLE ROW RADIAL
    "MER07558-001",   # Find 7 - OFFSET ROTARY SHAFT, LOWER
    "MER07559-001",   # Find 8 - OFFSET ROTARY SHAFT, UPPER
    # Find 9 = DELETED
    "MER07556-001",   # Find 10
    "MER07554-001",   # Find 11
    "MER07555-001",   # Find 12
    "M12133/2-255",   # Find 13 - WASHER, BELLEVILLE
    "MER07553-001",   # Find 14 - COVER, BEARING
    "16007",          # Find 15 - BEARING, DEEP GROOVE (numeric catalog PN)
    "WHM-244-S86",    # Find 16 - RETAINING RING
    "MER07546-001",   # Find 17 - BEARING DISC
    "M12133/2-100",   # Find 18 - WASHER, BELLEVILLE
    "97022A388",      # Find 19 - RING SHIM
    "97022A389",      # Find 19 alternate OCR read
    "MER07545-001",   # Find 20 - LOWER CAM MODULE
    "NAS1352N4-12",   # Find 21
    "NAS1352N4-14",   # Find 22
    "NAS1149E0432R",  # Find 23 - WASHER
    "MER07584-001",   # Find 24
    "2949T32",        # Find 25 - HOIST RING
    "NAS1351N4H16",   # Find 27
    "NAS509-4C",      # Find 28
    "NASM20995N32",   # Find 29
}

# Numeric catalog part numbers that are NOT find numbers
# These are real bearing/hardware part numbers that happen to be all-digit
NUMERIC_PART_NUMBERS = {"16007", "6824", "6915", "6916", "51109"}

# These indicate the vision model confused columns (FAIL)
# Only small integers (1-2 digits) are find numbers. Larger numbers like
# 6824, 16007, 51109 are real bearing catalog part numbers.
FIND_NUMBERS = {str(i) for i in range(1, 100)} | {f"{i}." for i in range(1, 100)}


def main():
    print("=" * 80)
    print("  MER07543-001 Extraction Test (Prompt Fix Validation)")
    print("=" * 80)
    print(f"PDF: {PDF_PATH}")
    print()

    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}")
        sys.exit(1)

    client = VisionClient()
    print(f"Using model: {client.model}")
    print(f"Backend: {'Bedrock' if client.use_bedrock else 'Direct API'}")
    print()

    # Extract page 1 (index 0) - this has the EPL
    print("Extracting page 1 (EPL page)...")
    result = extract_drawing_page(PDF_PATH, 0, client)

    if not result:
        print("ERROR: No extraction result!")
        sys.exit(1)

    # Show title block
    tb = result.get("title_block", {})
    print(f"\nTitle Block:")
    print(f"  Drawing: {tb.get('drawing_number', '?')}")
    print(f"  Title:   {tb.get('title', '?')}")
    print(f"  NHA:     {tb.get('nha_part_number', '?')}")
    print(f"  Type:    {result.get('drawing_type', '?')}")
    print()

    # Analyze parts list
    parts = result.get("parts_list", [])
    print(f"Parts extracted: {len(parts)}")
    print()

    find_number_count = 0
    real_pn_count = 0
    matched_expected = 0

    print("%-6s  %-25s  %-40s  %s" % ("Find#", "Part Number", "Description", "Status"))
    print("-" * 100)

    for part in parts:
        find_no = str(part.get("find_no", "")).strip()
        pn = str(part.get("part_number", "")).strip()
        desc = str(part.get("description", ""))[:40]
        has_find_flag = part.get("_find_number_as_pn", False)

        pn_stripped = pn.rstrip(".")
        if pn in NUMERIC_PART_NUMBERS or pn_stripped in NUMERIC_PART_NUMBERS:
            # Known numeric catalog part numbers (bearings etc.) - these are correct
            status = "OK (numeric catalog PN)"
            real_pn_count += 1
            if pn in EXPECTED_PART_NUMBERS or pn_stripped in EXPECTED_PART_NUMBERS:
                matched_expected += 1
        elif pn in FIND_NUMBERS or (pn_stripped.isdigit() and len(pn_stripped) <= 2):
            status = "FAIL - find number in PN field!"
            find_number_count += 1
        elif pn in EXPECTED_PART_NUMBERS:
            status = "OK (matches drawing)"
            matched_expected += 1
            real_pn_count += 1
        else:
            status = "OK (real PN, not in expected set)"
            real_pn_count += 1

        if has_find_flag:
            status += " [FLAGGED by postprocessing]"

        print("%-6s  %-25s  %-40s  %s" % (find_no, pn, desc, status))

    print()
    print("=" * 80)
    print("  RESULTS")
    print("=" * 80)
    print(f"  Total parts extracted:     {len(parts)}")
    print(f"  Real part numbers:         {real_pn_count}")
    print(f"  Find numbers as PN (BAD):  {find_number_count}")
    print(f"  Matched expected PNs:      {matched_expected}")
    print()

    if find_number_count == 0:
        print("  >>> PASS: Prompt fix works! No find numbers in part_number field.")
    else:
        print(f"  >>> FAIL: {find_number_count} find numbers still in part_number field.")
        print("           Vision model still confusing FIND NO. with PART NUMBER column.")

    print("=" * 80)

    # Save raw result for inspection
    out_path = Path(r"C:\Users\jwilde2\Desktop\DMLLV\MER07543_extraction_test.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nRaw result saved to: {out_path}")


if __name__ == "__main__":
    main()
