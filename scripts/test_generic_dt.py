#!/usr/bin/env python3
"""
Test Generic DT Extraction - Works with any project prefix.

This tests that the MIUL builder works generically for:
- DMLLV (MER prefix) - e.g., MER07540-001
- GPE (GPE- prefix) - e.g., GPE-A000-1
- Any other project without hardcoding

The test verifies:
1. DT file detection (handles -DT, "Drawing Tree", etc.)
2. Project prefix auto-detection
3. NHA assignment for project parts vs standard hardware
"""

import sys
from pathlib import Path

sys.path.insert(0, r"C:\BoundState")

from mira.miul.v3.builder import _is_dt_file, MIULBuilderV3


def test_dt_file_detection():
    """Test that DT files are detected regardless of naming convention."""
    print("\n" + "=" * 60)
    print("TEST 1: DT File Detection")
    print("=" * 60)

    test_cases = [
        # (filename, expected_is_dt)
        ("MER07540-DT.DRW_-.6.pdf", True),        # DMLLV style
        ("GPE-DOC-004-D (GPE Drawing Tree).pdf", True),  # GPE style
        ("DrawingTree.pdf", True),                 # Simple name
        ("Something_DT.pdf", True),                # Underscore style
        ("Project DT.pdf", True),                  # Space style
        ("MER07540-001.DRW_-.11.pdf", False),     # Regular drawing
        ("GPE-A100-A (Faceplate Assembly).pdf", False),  # Regular drawing
        ("random_file.pdf", False),                # Not a DT
    ]

    passed = 0
    for filename, expected in test_cases:
        result = _is_dt_file(filename)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  {status}: {filename[:45]:<45} -> {result} (expected: {expected})")

    print(f"\nResults: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_prefix_extraction():
    """Test that project prefixes are correctly extracted."""
    print("\n" + "=" * 60)
    print("TEST 2: Prefix Extraction")
    print("=" * 60)

    builder = MIULBuilderV3()

    test_cases = [
        # (part_number, expected_prefix)
        ("MER07540-001", "MER"),
        ("GPE-A000-1", "GPE"),
        ("GPE-101-1", "GPE"),
        ("ABC12345-001", "ABC"),
        ("XYZ-001-A", "XYZ"),
        ("MS21043-6", "MS"),      # Standard hardware
        ("NAS1352N4-12", "NAS"),  # Standard hardware
        ("AN960-10", "AN"),       # Standard hardware
        ("12345-001", ""),        # No prefix
    ]

    passed = 0
    for pn, expected in test_cases:
        result = builder._extract_alpha_prefix(pn)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  {status}: {pn:<20} -> '{result}' (expected: '{expected}')")

    print(f"\nResults: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_project_part_detection():
    """Test that project parts are distinguished from standard hardware."""
    print("\n" + "=" * 60)
    print("TEST 3: Project Part Detection")
    print("=" * 60)

    builder = MIULBuilderV3()

    # Test with MER prefix (DMLLV)
    print("\n  --- With project prefix 'MER' (DMLLV) ---")
    mer_tests = [
        ("MER07540-001", True),   # Project part
        ("MER07546-001", True),   # Project part
        ("MS21043-6", False),     # Standard hardware
        ("NAS1352N4-12", False),  # Standard hardware
        ("16007", False),         # Catalog number
    ]

    passed_mer = 0
    for pn, expected in mer_tests:
        result = builder._is_project_part(pn, "MER")
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed_mer += 1
        print(f"    {status}: {pn:<18} is_project_part('MER')={result} (expected: {expected})")

    # Test with GPE prefix
    print("\n  --- With project prefix 'GPE' ---")
    gpe_tests = [
        ("GPE-A000-1", True),     # Project part
        ("GPE-101-1", True),      # Project part
        ("MS21043-6", False),     # Standard hardware
        ("NAS1352N4-12", False),  # Standard hardware
        ("MER07540-001", False),  # Different project!
    ]

    passed_gpe = 0
    for pn, expected in gpe_tests:
        result = builder._is_project_part(pn, "GPE")
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed_gpe += 1
        print(f"    {status}: {pn:<18} is_project_part('GPE')={result} (expected: {expected})")

    total = len(mer_tests) + len(gpe_tests)
    passed = passed_mer + passed_gpe
    print(f"\nResults: {passed}/{total} passed")
    return passed == total


def test_prefix_detection_from_dt():
    """Test that project prefix is auto-detected from DT tree."""
    print("\n" + "=" * 60)
    print("TEST 4: Prefix Detection from DT Tree")
    print("=" * 60)

    builder = MIULBuilderV3()

    # Simulate DMLLV DT tree
    builder.dt_tree = {
        "top_level": "MER07540-001",
        "tree": [
            {"drawing_number": "MER07540-001", "parent": None},
            {"drawing_number": "MER07543-001", "parent": "MER07540-001"},
        ]
    }
    prefix = builder._detect_project_prefix()
    status1 = "PASS" if prefix == "MER" else "FAIL"
    print(f"  {status1}: DMLLV DT -> '{prefix}' (expected: 'MER')")

    # Simulate GPE DT tree
    builder.dt_tree = {
        "top_level": "GPE-A000-1",
        "tree": [
            {"drawing_number": "GPE-A000-1", "parent": None},
            {"drawing_number": "GPE-A100-1", "parent": "GPE-A000-1"},
        ]
    }
    prefix = builder._detect_project_prefix()
    status2 = "PASS" if prefix == "GPE" else "FAIL"
    print(f"  {status2}: GPE DT -> '{prefix}' (expected: 'GPE')")

    # Simulate ABC project
    builder.dt_tree = {
        "top_level": "ABC12345-001",
        "tree": []
    }
    prefix = builder._detect_project_prefix()
    status3 = "PASS" if prefix == "ABC" else "FAIL"
    print(f"  {status3}: ABC DT -> '{prefix}' (expected: 'ABC')")

    passed = sum([status1 == "PASS", status2 == "PASS", status3 == "PASS"])
    print(f"\nResults: {passed}/3 passed")
    return passed == 3


def test_nested_to_flat_conversion():
    """Test conversion of nested tree to flat format."""
    print("\n" + "=" * 60)
    print("TEST 5: Nested to Flat Conversion")
    print("=" * 60)

    from mira.miul.v3.extract import _convert_nested_to_flat

    # GPE-style nested tree
    nested = {
        "root": {
            "part_number": "GPE-A000-1",
            "name": "GPE ASSEMBLY",
            "children": [
                {
                    "part_number": "GPE-A100-1",
                    "name": "FACEPLATE ASSEMBLY",
                    "children": [
                        {"part_number": "GPE-101-1", "name": "FACEPLATE", "children": []},
                        {"part_number": "GPE-102-1", "name": "DOOR", "children": []},
                    ]
                },
                {"part_number": "GPE-014-1", "name": "BOTTOM PLATE", "children": []},
            ]
        }
    }

    flat = _convert_nested_to_flat(nested)

    print(f"  Top level: {flat.get('top_level')}")
    print(f"  Tree entries: {len(flat.get('tree', []))}")

    # Verify hierarchy
    tree = flat.get("tree", [])
    nha_map = {e["drawing_number"]: e["parent"] for e in tree}

    expected = {
        "GPE-A000-1": None,           # Root
        "GPE-A100-1": "GPE-A000-1",   # Child of root
        "GPE-101-1": "GPE-A100-1",    # Child of A100
        "GPE-102-1": "GPE-A100-1",    # Child of A100
        "GPE-014-1": "GPE-A000-1",    # Child of root
    }

    passed = 0
    for pn, exp_parent in expected.items():
        actual = nha_map.get(pn, "(missing)")
        status = "PASS" if actual == exp_parent else "FAIL"
        if status == "PASS":
            passed += 1
        exp_str = exp_parent if exp_parent else "(root)"
        act_str = actual if actual else "(root)"
        print(f"  {status}: {pn} -> {act_str} (expected: {exp_str})")

    print(f"\nResults: {passed}/{len(expected)} passed")
    return passed == len(expected)


def main():
    print("=" * 60)
    print("GENERIC DT EXTRACTION TEST SUITE")
    print("=" * 60)
    print("\nThis verifies the MIUL builder works for ANY project")
    print("without hardcoding MER, GPE, or any specific prefix.\n")

    all_passed = True

    all_passed &= test_dt_file_detection()
    all_passed &= test_prefix_extraction()
    all_passed &= test_project_part_detection()
    all_passed &= test_prefix_detection_from_dt()
    all_passed &= test_nested_to_flat_conversion()

    print("\n" + "=" * 60)
    print("FINAL RESULT")
    print("=" * 60)

    if all_passed:
        print("\nALL TESTS PASSED - Code is generic and project-agnostic!")
    else:
        print("\nSOME TESTS FAILED - Review issues above")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
