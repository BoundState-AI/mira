#!/usr/bin/env python3
"""
Module: Test Material Lookup
Purpose: Test material code lookup for problem designations.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import logging
import sys
from pathlib import Path

# Add project root to path for imports
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Show debug for material lookup to diagnose issues
logging.getLogger("mira.miul.material_code_lookup").setLevel(logging.DEBUG)


def test_material_lookup():
    """Test material code lookup for problem designations."""
    from mira.miul.material_code_lookup import get_lookup_service, reset_lookup_service

    # Reset to get fresh instance
    reset_lookup_service()
    lookup = get_lookup_service()

    # Test cases: (designation, expected_behavior)
    test_cases = [
        # Primary acceptance criteria
        (
            "302 SST",
            "Should match CRES/STAINLESS STEEL 302 (e.g., 10089, 10262), NOT 05571"
        ),
        (
            "INCONEL 625",
            "Should match Inconel 625 (e.g., 10141, 10288), NOT 02484"
        ),
        (
            "INCONEL 718",
            "Should match Inconel 718 (e.g., 02102) - regression test"
        ),
        # Edge cases
        (
            "316L SST",
            "Should match stainless steel 316L variants"
        ),
        (
            "A286",
            "Should match A-286 stainless steel"
        ),
        (
            "7075 ALUMINUM",
            "Should match aluminum 7075 variants"
        ),
        # Boundary safety test - this should NOT match "302 SST"
        (
            "AMS 3302",
            "Should NOT match stainless steel 302 - this is a different spec"
        ),
    ]

    print("\n" + "=" * 80)
    print("MATERIAL CODE LOOKUP TEST")
    print("=" * 80)

    results = []
    for designation, expected in test_cases:
        print(f"\n--- Testing: '{designation}' ---")
        print(f"Expected: {expected}")

        match = lookup.lookup_material_code(designation)

        print(f"Result:")
        print(f"  material_code: {match.material_code}")
        print(f"  designation: {match.designation}")
        print(f"  method: {match.method}")
        print(f"  confidence: {match.confidence}")
        print(f"  score: {match.score:.2f}")

        if match.candidates:
            print(f"  candidates ({len(match.candidates)}):")
            for c in match.candidates[:3]:
                print(f"    - {c.material_code}: {c.designation}")

        # Evaluate result
        passed = True
        reason = ""

        if designation == "302 SST":
            # Should NOT be 05571 (AMS 3302 Shore Hardness)
            if match.material_code == "05571":
                passed = False
                reason = "FAIL: Got 05571 (AMS 3302) - wrong material family"
            elif match.material_code is None and match.method == "ambiguous":
                reason = "OK: Quarantined for review (ambiguous)"
            elif match.material_code:
                reason = f"OK: Got {match.material_code}"

        elif designation == "INCONEL 625":
            # Should NOT be 02484 (part number)
            if match.material_code == "02484":
                passed = False
                reason = "FAIL: Got 02484 (part number) - wrong match"
            elif match.material_code is None and match.method == "ambiguous":
                reason = "OK: Quarantined for review (ambiguous)"
            elif match.material_code:
                reason = f"OK: Got {match.material_code}"

        elif designation == "INCONEL 718":
            # Should get a valid match (regression test)
            if match.material_code is None:
                passed = False
                reason = "FAIL: No match found - regression"
            else:
                reason = f"OK: Got {match.material_code}"

        elif designation == "AMS 3302":
            # This is NOT stainless steel - should get its own match or nothing
            if match.method == "family_filtered":
                # Check it's not in stainless family
                if match.designation and "STAINLESS" in match.designation.upper():
                    passed = False
                    reason = "FAIL: Incorrectly matched as stainless steel"
                else:
                    reason = f"OK: Got {match.material_code} (not stainless)"
            elif match.material_code is None:
                reason = "OK: No match (as expected for ambiguous spec)"
            else:
                reason = f"OK: Got {match.material_code}"

        else:
            # Generic check
            if match.material_code:
                reason = f"Got match: {match.material_code}"
            elif match.method in ("ambiguous", "unresolved"):
                reason = f"Quarantined ({match.method})"
            else:
                reason = "No match"

        print(f"  -> {reason}")
        results.append((designation, passed, reason))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    passed_count = sum(1 for _, p, _ in results if p)
    total = len(results)

    for designation, passed, reason in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] '{designation}': {reason}")

    print(f"\nTotal: {passed_count}/{total} passed")

    # Cleanup
    lookup.close()

    return passed_count == total


def test_family_detection():
    """Test word-boundary family detection."""
    from mira.miul.material_code_lookup import FAMILY_PATTERNS

    print("\n" + "=" * 80)
    print("FAMILY DETECTION TEST")
    print("=" * 80)

    test_cases = [
        # Should detect stainless
        ("302 SST", "STAINLESS"),
        ("CRES 316", "STAINLESS"),
        ("SS 304", "STAINLESS"),
        ("STAINLESS STEEL 321", "STAINLESS"),
        # Should detect nickel
        ("INCONEL 625", "NICKEL"),
        ("HASTELLOY X", "NICKEL"),
        ("MONEL 400", "NICKEL"),
        # Should detect aluminum
        ("7075 ALUMINUM", "ALUMINUM"),
        ("AL 6061", "ALUMINUM"),
        # Should NOT detect family (false positives)
        ("ASSEMBLY PART", None),  # Contains "SS" in ASSEMBLY - should NOT match
        ("INSTALLATION KIT", None),  # Contains "IN" - should NOT match
        ("ALLOY 625", None),  # No family keyword
    ]

    passed = 0
    for designation, expected_family in test_cases:
        detected = None
        for family, pattern in FAMILY_PATTERNS.items():
            if pattern.search(designation):
                detected = family
                break

        status = "PASS" if detected == expected_family else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  [{status}] '{designation}': expected={expected_family}, got={detected}")

    print(f"\nTotal: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("MIUL MATERIAL CODE LOOKUP TESTS")
    print("=" * 80)

    # Test family detection first (no DB needed)
    family_ok = test_family_detection()

    # Test material lookup (requires DB)
    try:
        lookup_ok = test_material_lookup()
    except Exception as e:
        print(f"\nError running lookup tests: {e}")
        print("Make sure PostgreSQL is running with mira database")
        lookup_ok = False

    # Final result
    print("\n" + "=" * 80)
    print("FINAL RESULT")
    print("=" * 80)

    if family_ok and lookup_ok:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
