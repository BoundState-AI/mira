#!/usr/bin/env python3
"""
Test OCR corrections for MIUL extraction.

Verifies that the corrections identified from DMLLV comparison work correctly.
"""

import sys
sys.path.insert(0, r"C:\BoundState")

from mira.miul.v3.ocr_correction import (
    correct_part_number,
    is_invalid_part_number,
    get_invalid_reason,
)


def test_ocr_corrections():
    """Test part number OCR corrections from DMLLV analysis."""
    print("\n" + "=" * 60)
    print("TEST: Part Number OCR Corrections")
    print("=" * 60)

    # Corrections identified from James's reference comparison
    test_cases = [
        # (extracted, expected_corrected)
        ("WHM-137-C86", "WSM-137-C86"),  # H→S in retaining ring
        ("MS14128R8", "MS14198N6"),       # 2→9, R→N in lock
        ("NAS1352N4-6", "NAS1352N5-12"),  # 4→5, 6→12 in SHCS
        ("M71133/2-255", "M12133/2-255"), # 7→1 in belleville
        ("NAS1351N4R6", "NAS1351N4H16"),  # R→H, 6→16 in SHCS
        ("AR933K04", "AS4307K04"),        # R→S, digit reorder in fitting
        # Existing corrections (regression test)
        ("MER70540-001", "MER07540-001"), # Digit transposition
        ("WFM-137-C86", "WSM-137-C86"),   # F→S in retaining ring
    ]

    passed = 0
    for extracted, expected in test_cases:
        result = correct_part_number(extracted)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  {status}: {extracted:<20} -> {result:<20} (expected: {expected})")

    print(f"\nResults: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_invalid_filtering():
    """Test that invalid/hallucinated parts are filtered."""
    print("\n" + "=" * 60)
    print("TEST: Invalid Part Number Filtering")
    print("=" * 60)

    test_cases = [
        # (part_number, should_be_invalid)
        ("5.", True),              # Note reference
        ("6.", True),              # Note reference
        ("EH-FITTED", True),       # Description text
        ("MER07643-001", True),    # Hallucinated
        ("MER07567C1A10", True),   # Hallucinated
        ("MER07600C4-10", True),   # Hallucinated
        # Valid parts (should NOT be filtered)
        ("MER07540-001", False),
        ("NAS509-6C", False),
        ("NAS509L6C", False),      # Valid LH thread variant
        ("MS21043-6", False),
        ("16007", False),          # Catalog number
        ("6824", False),           # Catalog number
        ("51109", False),          # Catalog number
    ]

    passed = 0
    for pn, expected_invalid in test_cases:
        result = is_invalid_part_number(pn)
        status = "PASS" if result == expected_invalid else "FAIL"
        if status == "PASS":
            passed += 1
        reason = get_invalid_reason(pn) or "(valid)"
        marker = "INVALID" if result else "VALID"
        print(f"  {status}: {pn:<20} -> {marker:<10} {reason}")

    print(f"\nResults: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_nas509l6c_not_corrected():
    """Ensure NAS509L6C is NOT incorrectly corrected to NAS509-6C."""
    print("\n" + "=" * 60)
    print("TEST: NAS509L6C Preservation")
    print("=" * 60)

    # NAS509L6C is the LEFT-HAND thread variant - it's valid!
    result = correct_part_number("NAS509L6C")

    if result == "NAS509L6C":
        print("  PASS: NAS509L6C remains NAS509L6C (LH thread preserved)")
        return True
    else:
        print(f"  FAIL: NAS509L6C incorrectly changed to {result}")
        return False


def main():
    print("=" * 60)
    print("OCR CORRECTIONS TEST SUITE")
    print("=" * 60)
    print("\nVerifying corrections identified from DMLLV/James comparison")

    all_passed = True
    all_passed &= test_ocr_corrections()
    all_passed &= test_invalid_filtering()
    all_passed &= test_nas509l6c_not_corrected()

    print("\n" + "=" * 60)
    print("FINAL RESULT")
    print("=" * 60)

    if all_passed:
        print("\nALL TESTS PASSED")
    else:
        print("\nSOME TESTS FAILED - Review above")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
