#!/usr/bin/env python3
"""
Module: Validate Simple
Purpose: Quick validation script for the simplified H2 engine.

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

from __future__ import annotations

import sys
from pathlib import Path

# Add h2 directory to path for direct imports
h2_dir = Path(__file__).parent
sys.path.insert(0, str(h2_dir))

from engine_simple import H2Engine, Verdict


def main():
    """Run validation tests."""
    engine = H2Engine()

    print("=" * 70)
    print("H2 Knowledge Twin - Simplified Engine Validation")
    print("=" * 70)

    # Get stats first
    stats = engine.get_evidence_stats()
    print(f"\nEvidence Database:")
    print(f"  Total records: {stats['total_records']}")
    print(f"  Unique materials: {stats['unique_materials']}")
    print(f"  Band distribution: {stats['band_distribution']}")
    print()

    # Known failure cases that MUST work
    failure_cases = [
        ("718", "Inconel 718", "extreme"),
        ("SS316", "316 Stainless Steel", None),  # Any match is good
        ("316L", "316L", None),
        ("316", "316 Stainless Steel", None),
        ("440A", "440A Steel", None),
        ("K-Monel", "K-Monel", "extreme"),  # Worst case
        ("MA 754", "MA 754", "extreme"),
    ]

    print("Known Failure Cases (must all pass):")
    print("-" * 70)

    all_passed = True
    for query, expected_material, expected_band in failure_cases:
        result = engine.query(query)

        # Check if we found anything
        found = result.verdict != Verdict.UNKNOWN

        # Check if we found expected band (if specified)
        band_ok = expected_band is None or result.hee_band == expected_band

        passed = found and band_ok
        status = "PASS" if passed else "FAIL"

        if not passed:
            all_passed = False

        print(f"  Query: '{query}'")
        print(f"    Found: {found}, Band: {result.hee_band}, Verdict: {result.verdict.value}")
        print(f"    Match type: {result.match_type}, Canonical: {result.canonical_name}")
        print(f"    Evidence count: {result.evidence_count}")
        print(f"    Status: [{status}]")
        if not passed:
            print(f"    Expected band: {expected_band}, got: {result.hee_band}")
        print()

    print("-" * 70)

    # Test condition filtering for K-Monel
    print("\nCondition Filtering Test (K-Monel):")
    print("-" * 70)

    result_any = engine.query("K-Monel")
    result_annealed = engine.query("K-Monel", condition="annealed")
    result_aged = engine.query("K-Monel", condition="aged")

    print(f"  K-Monel (any condition):")
    print(f"    Band: {result_any.hee_band}, Distribution: {result_any.band_distribution}")

    print(f"  K-Monel (annealed):")
    print(f"    Band: {result_annealed.hee_band}, Distribution: {result_annealed.band_distribution}")

    print(f"  K-Monel (aged/STA):")
    print(f"    Band: {result_aged.hee_band}, Distribution: {result_aged.band_distribution}")

    # K-Monel should show extreme without filter, high with annealed filter
    kmonel_ok = (
        result_any.hee_band == "extreme" and
        result_annealed.hee_band == "high"
    )
    print(f"\n  K-Monel condition test: {'PASS' if kmonel_ok else 'FAIL'}")
    if not kmonel_ok:
        all_passed = False

    print()
    print("-" * 70)

    # Sample some authoritative materials
    print("\nSample Authoritative Materials:")
    print("-" * 70)

    sample_materials = [
        "Inconel 718",
        "Inconel 625",
        "304 Stainless Steel",
        "Ti-6Al-4V",
        "Copper (OFHC)",
        "6061-T6 Aluminum",
        "Hastelloy X",
        "4140 Steel",
        "250 Maraging Steel",
    ]

    for material in sample_materials:
        result = engine.query(material)
        print(f"  {material}:")
        print(f"    Verdict: {result.verdict.value}, Band: {result.hee_band}")
        print(f"    Evidence: {result.evidence_count} records")
        print()

    print("=" * 70)

    # Test MUA search integration (if available)
    print("\nMUA Search Integration Test:")
    print("-" * 70)

    if engine._mua_search:
        print("  MUA search is ENABLED")
        mua_stats = engine._mua_search.get_stats()
        print(f"  Index entries: {mua_stats.get('total_entries', 0)}")
        print(f"  Metadata entries: {mua_stats.get('metadata_entries', 0)}")

        # Test with a material that might have MUA history
        test_result = engine.query("Inconel 718")
        print(f"\n  MUA test for 'Inconel 718':")
        print(f"    MUA precedents found: {len(test_result.mua_precedents)}")
        print(f"    Has denial: {test_result.has_mua_denial}")
        if test_result.mua_precedents:
            for p in test_result.mua_precedents[:3]:
                print(f"      - {p.get('mua_id', 'N/A')}: {p.get('determination', 'N/A')} "
                      f"(score: {p.get('score', 0):.2f})")
    else:
        print("  MUA search is DISABLED (dependencies not available)")
        print("  To enable: pip install faiss-cpu sentence-transformers")

    print()
    print("=" * 70)
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED - Review output above")
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
