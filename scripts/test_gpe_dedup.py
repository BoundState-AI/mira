#!/usr/bin/env python3
"""
Quick verification of GPE doubled-text dedup fix.

Tests the _is_doubled_text() detection and _dedupe_doubled_text() algorithm
with actual patterns from CU Boulder GPE PDFs.

Usage:
    py /c/BoundState/scripts/test_gpe_dedup.py
"""

import sys
sys.path.insert(0, "C:/BoundState")

from mira.miul.v3.text_extract import _is_doubled_text, _dedupe_doubled_text


def test_dedup():
    """Test doubled-text deduplication with GPE patterns."""

    test_cases = [
        # (input, expected_output, description)

        # Basic material designations
        ("66006611--TT66", "6061-T6", "Aluminum temper"),
        ("77007755--TT665511", "7075-T651", "Aluminum temper with digits"),
        ("55005522--HH3322", "5052-H32", "Aluminum H-temper"),
        ("AA228866", "A286", "A-series alloy"),
        ("1155--55  PPHH", "15-5 PH", "PH stainless with space"),

        # BOM header text
        ("IITTEEMM  NNOO..  QQTTYY  MMAATTEERRIIAALL", "ITEM NO. QTY MATERIAL", "BOM header"),
        ("MMAATTEERRIIAALL", "MATERIAL", "Single word"),

        # Process notes
        ("RREEMMOOVVEE  AALLLL  BBUURRRRSS", "REMOVE ALL BURRS", "Process note"),

        # Mixed content (doubled letters, single spaces)
        ("AALLUUMMIINNUUMM AALLLLOOYY", "ALUMINUM ALLOY", "Doubled with single space between"),

        # Edge cases
        ("", "", "Empty string"),
        ("A", "A", "Single char"),
        ("AB", "AB", "Two different chars - no dedup"),
    ]

    print("=" * 70)
    print("GPE Doubled-Text Dedup Verification")
    print("=" * 70)

    passed = 0
    failed = 0

    for input_str, expected, desc in test_cases:
        result = _dedupe_doubled_text(input_str)
        ok = result == expected

        if ok:
            passed += 1
            status = "PASS"
        else:
            failed += 1
            status = "FAIL"

        print(f"\n[{status}] {desc}")
        print(f"  Input:    {input_str!r}")
        print(f"  Expected: {expected!r}")
        print(f"  Got:      {result!r}")

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


def test_detection():
    """Test doubled-text detection heuristic."""

    test_cases = [
        # (input, expected_is_doubled, description)

        # GPE doubled text - should detect
        ("RREEMMOOVVEE  AALLLL  BBUURRRRSS  AANNDD  SSHHAARRPP  EEDDGGEESS", True, "GPE process note"),
        ("IITTEEMM  NNOO..  QQTTYY  MMAATTEERRIIAALL  LLOOTT--SS//NN", True, "GPE BOM header"),

        # NASA D-format normal text - should NOT detect
        ("REMOVE ALL BURRS AND SHARP EDGES", False, "NASA normal text"),
        ("MATERIAL: ALUMINUM ALLOY 7075-T651", False, "NASA material note"),
        ("STAINLESS STEEL 15-5PH CRES H900", False, "NASA material with doubled letters in words"),

        # Edge cases
        ("", False, "Empty string"),
        ("SHORT", False, "Too short to detect"),
    ]

    print("\n" + "=" * 70)
    print("Doubled-Text Detection Verification")
    print("=" * 70)

    passed = 0
    failed = 0

    for input_str, expected, desc in test_cases:
        result = _is_doubled_text(input_str)
        ok = result == expected

        if ok:
            passed += 1
            status = "PASS"
        else:
            failed += 1
            status = "FAIL"

        print(f"\n[{status}] {desc}")
        print(f"  Input:    {input_str[:50]!r}{'...' if len(input_str) > 50 else ''}")
        print(f"  Expected: {expected}")
        print(f"  Got:      {result}")

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    dedup_ok = test_dedup()
    detect_ok = test_detection()

    print("\n" + "=" * 70)
    if dedup_ok and detect_ok:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
