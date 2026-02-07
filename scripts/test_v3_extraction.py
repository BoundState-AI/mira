#!/usr/bin/env python3
"""
Test v3 extraction on problematic drawings.

Usage:
    python scripts/test_v3_extraction.py C:\\Users\\jwilde2\\Desktop\\DMLLV
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.miul.v3.extract import extract_drawing_page, VisionClient
from mira.miul.v3.ocr_correction import (
    correct_ocr_errors,
    parse_material_note,
    is_valid_material_spec,
    clean_material_spec,
    clean_designation,
    correct_part_number,
)


def test_ocr_correction():
    """Test OCR correction on known problematic strings."""
    print("=" * 60)
    print("Testing OCR Correction")
    print("=" * 60)

    test_cases = [
        ("3x2 OR 304 SST", "302/304 CRES"),
        ("3X2 OR 304 SST", "302/304 CRES"),
        ("PD A-286", "A-286"),
        ("A2B6 CRES", "A286 CRES"),
        ("7O75 ALUMINUM", "7075 ALUMINUM"),
        ("INCONE1 625", "INCONEL 625"),
    ]

    for input_text, expected in test_cases:
        result = correct_ocr_errors(input_text)
        status = "PASS" if expected in result else "FAIL"
        print(f"  {status} '{input_text}' -> '{result}' (expected: '{expected}')")

    print()


def test_note_parsing():
    """Test material note parsing."""
    print("=" * 60)
    print("Testing Note Parsing")
    print("=" * 60)

    test_notes = [
        "3. MATERIAL: A286 CRES, UNS S66286, PER SAE AMS 5737",
        "MATERIAL: INCONEL 718, UNS N07718, PER SAE AMS 5664",
        "2. MATERIAL 7075-T6 ALUMINUM PER ASTM B211",
    ]

    for note in test_notes:
        result = parse_material_note(note)
        print(f"  Input: {note}")
        print(f"  Result: {json.dumps(result, indent=4)}")
        print()


def test_material_spec_validation():
    """Test Material Specification validation (rejects OCR garbage)."""
    print("=" * 60)
    print("Testing Material Spec Validation")
    print("=" * 60)

    test_cases = [
        # (input, should_be_valid)
        ("SAE AMS 5737", True),
        ("ASTM B211", True),
        ("MIL-S-5000", True),
        ("AMS5525, AMS5731, AMS5732", True),
        ("SAE AMS-QQ-A-200/6", True),
        ("ASTM D1710, TYPE III", True),
        ("PER AMS 5737", True),
        ("", True),  # Empty is valid

        # OCR garbage - should be rejected
        ("33982", False),
        ("33062", False),
        ("33@B2", False),
        ("51914", False),
        ("56968", False),
        ("51588", False),
    ]

    for input_text, expected_valid in test_cases:
        result = is_valid_material_spec(input_text)
        status = "PASS" if result == expected_valid else "FAIL"
        cleaned = clean_material_spec(input_text)
        print(f"  {status} '{input_text}' valid={result} (expected={expected_valid}) -> cleaned='{cleaned}'")

    print()


def test_part_number_correction():
    """Test part number OCR correction."""
    print("=" * 60)
    print("Testing Part Number Correction")
    print("=" * 60)

    test_cases = [
        # (input, expected)
        ("MER70570-001", "MER07570-001"),
        ("MER70575-001", "MER07575-001"),
        ("MFR07585-001", "MER07585-001"),
        ("MER07540-001", "MER07540-001"),  # Should not change
        ("NAS1352N5-12", "NAS1352N5-12"),  # Should not change
        ("5...", "5."),  # Extra dots
    ]

    for input_text, expected in test_cases:
        result = correct_part_number(input_text)
        status = "PASS" if result == expected else "FAIL"
        print(f"  {status} '{input_text}' -> '{result}' (expected: '{expected}')")

    print()


def test_designation_cleanup():
    """Test designation cleanup (removes vendor pollution)."""
    print("=" * 60)
    print("Testing Designation Cleanup")
    print("=" * 60)

    test_cases = [
        (
            "A286 SST. RECOMMENDED SOURCE: SMALLEY STEEL RING CO WWW.SMALLEY.COM PHONE: 847-719-5900 ALTERNATE: ROTOR CLIP WWW.ROTORCLIP.COM PHONE: 732-469-7333",
            "A286 SST",
        ),
        (
            "A286. RECOMMENDED SOURCE: SMALLEY STEEL RING CO WWW.SMALLEY.COM ALTERNATE: ROTOR CLIP WWW.ROTORCLIP.COM",
            "A286",
        ),
        ("INCONEL 625", "INCONEL 625"),  # Should not change
        ("A286 CRES", "A286 CRES"),  # Should not change
    ]

    for input_text, expected in test_cases:
        result = clean_designation(input_text)
        status = "PASS" if result == expected else "FAIL"
        print(f"  {status}")
        if status == "FAIL":
            print(f"    Input:    '{input_text}'")
            print(f"    Got:      '{result}'")
            print(f"    Expected: '{expected}'")
        else:
            print(f"    '{input_text[:50]}...' -> '{result}'")

    print()


def test_drawing_extraction(pdf_path: Path):
    """Test extraction on a single drawing."""
    print("=" * 60)
    print(f"Testing: {pdf_path.name}")
    print("=" * 60)

    try:
        client = VisionClient()
        result = extract_drawing_page(pdf_path, 0, client)

        if not result:
            print("  No result returned")
            return

        tb = result.get("title_block", {})
        print(f"  Drawing Number: {tb.get('drawing_number', 'N/A')}")
        print(f"  Title: {tb.get('title', 'N/A')}")
        print(f"  Material Designation: {tb.get('material_designation', 'N/A')}")
        print(f"  Material Spec: {tb.get('material_spec', 'N/A')}")
        print(f"  UNS Number: {tb.get('uns_number', 'N/A')}")
        print(f"  Material Source: {tb.get('material_source', 'N/A')}")

        # Show notes if they exist
        notes = result.get("notes", [])
        if notes:
            print(f"  Notes ({len(notes)}):")
            for note in notes[:5]:
                print(f"    - {note[:80]}...")

        # Show material notes
        mat_notes = result.get("material_notes_found", [])
        if mat_notes:
            print(f"  Material Notes Found ({len(mat_notes)}):")
            for mn in mat_notes:
                print(f"    - Note {mn.get('note_number')}: {mn.get('parsed_designation', 'N/A')}")

        # Show parts list summary
        parts = result.get("parts_list", [])
        if parts:
            print(f"  Parts List ({len(parts)}):")
            for p in parts[:5]:
                mat = p.get("material_callout", "N/A")
                print(f"    - {p.get('part_number', '?')}: {mat}")

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

    print()


def main():
    # Run all unit tests
    test_ocr_correction()
    test_note_parsing()
    test_material_spec_validation()
    test_part_number_correction()
    test_designation_cleanup()

    # If a directory is provided, test extraction
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
        if not directory.exists():
            print(f"Directory not found: {directory}")
            sys.exit(1)

        # Test on specific problematic files if they exist, else test first 5 PDFs
        problem_files = [
            "MER07567-001.DRW_-.11_RELEASED.pdf",
            "MER07576.DRW_-.6_RELEASED.pdf",
            "MER07587-001.DRW_-.6_RELEASED.pdf",
        ]

        found_any = False
        for filename in problem_files:
            pdf_path = directory / filename
            if pdf_path.exists():
                test_drawing_extraction(pdf_path)
                found_any = True
            else:
                # Try to find with different suffix
                matches = list(directory.glob(f"{filename.split('.')[0]}*.pdf"))
                if matches:
                    test_drawing_extraction(matches[0])
                    found_any = True

        # If no specific files found, test first 5 PDFs in directory
        if not found_any:
            print("No specific test files found. Testing first 5 PDFs in directory...")
            pdf_files = sorted(directory.glob("*.pdf"))[:5]
            for pdf_path in pdf_files:
                test_drawing_extraction(pdf_path)

    print("=" * 60)
    print("Testing Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
