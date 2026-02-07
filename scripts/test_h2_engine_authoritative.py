#!/usr/bin/env python3
"""
Test H2 Engine directly against authoritative NASA/TM-2016-218602 Table 2 data.

Complete 135-material test suite (excluding duplicates).

Usage:
    python scripts/test_h2_engine_authoritative.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.knowledge_twins.h2.engine_simple import H2Engine, Verdict


@dataclass
class MaterialTest:
    """Test case from NASA authoritative data."""
    material: str
    hee_index: float
    expected_band: str


def get_band(hee_index: float) -> str:
    """Get HEE band from index value."""
    if hee_index < 0.50:
        return "extreme"
    elif hee_index < 0.70:
        return "severe"
    elif hee_index < 0.90:
        return "high"
    elif hee_index < 0.97:
        return "small"
    else:
        return "negligible"


# NASA/TM-2016-218602 Table 2 - Complete Material Authoritative HEE Data
AUTHORITATIVE_MATERIALS = [
    # EXTREME HEE (< 0.50)
    MaterialTest("CM SX-2 (single crystal)", 0.14, "extreme"),
    MaterialTest("AerMet 100 (peak aged)", 0.15, "extreme"),
    MaterialTest("Ti-11.5Mo-6Zr-4.5Sn (STA)", 0.18, "extreme"),
    MaterialTest("MA 754 (Longitudinal)", 0.19, "extreme"),
    MaterialTest("440A Steel", 0.21, "extreme"),
    MaterialTest("MAR-M200 (DS)", 0.23, "extreme"),
    MaterialTest("MAR-M246 (Hf) (single crystal)", 0.24, "extreme"),
    MaterialTest("Fe-9Ni-4Co-0.20C", 0.24, "extreme"),
    MaterialTest("Maraging Steel 300", 0.24, "extreme"),
    MaterialTest("MA 754 (Transverse)", 0.27, "extreme"),
    MaterialTest("Maraging Steel 250", 0.28, "extreme"),
    MaterialTest("D6AC Steel (300C tempered)", 0.30, "extreme"),
    MaterialTest("IN 100", 0.30, "extreme"),
    MaterialTest("Nickel (electroformed)", 0.31, "extreme"),
    MaterialTest("PH 13-8 Mo", 0.31, "extreme"),
    MaterialTest("CG-27 (precipitated)", 0.34, "extreme"),
    MaterialTest("4340 Steel", 0.35, "extreme"),
    MaterialTest("Incoloy 909 (ST + Aged)", 0.36, "extreme"),
    MaterialTest("CM SX-4C (single crystal)", 0.36, "extreme"),
    MaterialTest("CM-SX5", 0.36, "extreme"),
    MaterialTest("CM SX-3 (std)", 0.38, "extreme"),
    MaterialTest("PH 15-7 Mo", 0.38, "extreme"),
    MaterialTest("Gamma-TiAl Alloy", 0.39, "extreme"),
    MaterialTest("410 Stainless Steel", 0.39, "extreme"),
    MaterialTest("AM-350", 0.40, "extreme"),
    MaterialTest("Maraging Steel 200", 0.40, "extreme"),
    MaterialTest("AM-355", 0.42, "extreme"),
    MaterialTest("Inconel 713LC", 0.42, "extreme"),
    MaterialTest("4140 Steel", 0.43, "extreme"),
    MaterialTest("Inconel 718 (STA)", 0.43, "extreme"),
    MaterialTest("17-7 PH", 0.43, "extreme"),
    MaterialTest("CM SX-4D", 0.43, "extreme"),
    MaterialTest("A372 (grade J)", 0.45, "extreme"),
    MaterialTest("Inconel 700", 0.45, "extreme"),
    MaterialTest("K-Monel (aged)", 0.45, "extreme"),
    MaterialTest("Rene N-4 (single crystal)", 0.46, "extreme"),
    MaterialTest("Inconel 706", 0.46, "extreme"),
    MaterialTest("17-4 PH", 0.46, "extreme"),
    MaterialTest("4130 Steel", 0.47, "extreme"),
    MaterialTest("PWA 1480 (single crystal)", 0.49, "extreme"),
    MaterialTest("Rene 41", 0.49, "extreme"),

    # SEVERE HEE (0.50-0.69)
    MaterialTest("440C", 0.50, "severe"),
    MaterialTest("A286 (ST + Aged)", 0.51, "severe"),
    MaterialTest("9310 Steel", 0.51, "severe"),
    MaterialTest("Inconel 718 (ST 1750F)", 0.53, "severe"),
    MaterialTest("Udimet 720", 0.53, "severe"),
    MaterialTest("Alpha-2 TiAl Alloy", 0.54, "severe"),
    MaterialTest("RR 2000", 0.54, "severe"),
    MaterialTest("Incoloy 903 (ST + Aged)", 0.55, "severe"),
    MaterialTest("Ti-6Al-4V", 0.55, "severe"),
    MaterialTest("Udimet 700", 0.57, "severe"),
    MaterialTest("MA 956 (Longitudinal)", 0.58, "severe"),
    MaterialTest("Incoloy 901", 0.60, "severe"),
    MaterialTest("1080 Steel", 0.62, "severe"),
    MaterialTest("Rene 95 (PM)", 0.62, "severe"),
    MaterialTest("Nitronic 50", 0.62, "severe"),
    MaterialTest("Astroloy", 0.62, "severe"),
    MaterialTest("X100 Pipeline Steel", 0.63, "severe"),
    MaterialTest("MP159", 0.63, "severe"),
    MaterialTest("Inco 4005 (experimental)", 0.64, "severe"),
    MaterialTest("18-2-12 (Nitronic 32)", 0.64, "severe"),
    MaterialTest("MP35N (24 MPa)", 0.66, "severe"),
    MaterialTest("304N Stainless Steel", 0.66, "severe"),
    MaterialTest("21-6-9 Stainless", 0.66, "severe"),
    MaterialTest("1042 Steel", 0.67, "severe"),
    MaterialTest("18-18 Plus", 0.67, "severe"),
    MaterialTest("A212-61T (normalized)", 0.68, "severe"),
    MaterialTest("430F Steel", 0.68, "severe"),
    MaterialTest("Nitronic 40", 0.68, "severe"),
    MaterialTest("Waspaloy", 0.68, "severe"),
    MaterialTest("Ti-6Al-4V (STA 48 MPa)", 0.69, "severe"),

    # HIGH HEE (0.70-0.89)
    MaterialTest("IN-100", 0.70, "high"),
    MaterialTest("MP35N (34 MPa)", 0.70, "high"),
    MaterialTest("Nickel 270", 0.71, "high"),
    MaterialTest("321 Stainless Steel", 0.71, "high"),
    MaterialTest("Inconel 718 (ST)", 0.72, "high"),
    MaterialTest("K-Monel (annealed)", 0.73, "high"),
    MaterialTest("A515-Gr. 70", 0.73, "high"),
    MaterialTest("A372 (class 4)", 0.74, "high"),
    MaterialTest("1080 Steel (Transverse)", 0.74, "high"),
    MaterialTest("1042 Steel (Normalized)", 0.75, "high"),
    MaterialTest("JBK-75 (ST + Aged)", 0.75, "high"),
    MaterialTest("C1025 Steel", 0.76, "high"),
    MaterialTest("Haynes 230", 0.76, "high"),
    MaterialTest("Inconel 625", 0.76, "high"),
    MaterialTest("347 Stainless Steel", 0.76, "high"),
    MaterialTest("A-286", 0.77, "high"),
    MaterialTest("304L Stainless Steel", 0.77, "high"),
    MaterialTest("Haynes 242", 0.77, "high"),
    MaterialTest("A106-Gr. B", 0.78, "high"),
    MaterialTest("X52 Pipeline Steel", 0.78, "high"),
    MaterialTest("A517-F (T-1)", 0.78, "high"),
    MaterialTest("Hastelloy X", 0.78, "high"),
    MaterialTest("Ti-5Al-2.5Sn", 0.78, "high"),
    MaterialTest("A302B", 0.79, "high"),
    MaterialTest("AF-115 (PM)", 0.80, "high"),
    MaterialTest("Inconel 600", 0.80, "high"),
    MaterialTest("304 Stainless Steel", 0.80, "high"),
    MaterialTest("309S Stainless Steel", 0.80, "high"),
    MaterialTest("22-13-5 Stainless", 0.81, "high"),
    MaterialTest("1020 Steel", 0.82, "high"),
    MaterialTest("Inconel 706 (48 MPa)", 0.82, "high"),
    MaterialTest("MAR-M-246", 0.82, "high"),
    MaterialTest("A516", 0.83, "high"),
    MaterialTest("AF-56 (single crystal)", 0.84, "high"),
    MaterialTest("Tenelon", 0.85, "high"),
    MaterialTest("4140 Steel (normalized)", 0.85, "high"),
    MaterialTest("MERL 76", 0.85, "high"),
    MaterialTest("MP98T", 0.85, "high"),
    MaterialTest("310 Stainless Steel", 0.85, "high"),
    MaterialTest("MA 6000 (Longitudinal)", 0.86, "high"),
    MaterialTest("X-45 (superalloy)", 0.87, "high"),
    MaterialTest("305 Stainless Steel", 0.87, "high"),
    MaterialTest("PWA 1480E (111 plane)", 0.88, "high"),
    MaterialTest("Monel K-500", 0.89, "high"),

    # SMALL HEE (0.90-0.96)
    MaterialTest("X70 Pipeline Steel", 0.90, "small"),
    MaterialTest("Haynes 188", 0.90, "small"),
    MaterialTest("X60 Pipeline Steel", 0.92, "small"),
    MaterialTest("18-3-Mn", 0.92, "small"),
    MaterialTest("MA 6000 (Transverse)", 0.92, "small"),
    MaterialTest("Inconel 718 (ST 1900F)", 0.92, "small"),
    MaterialTest("Nickel 200", 0.92, "small"),
    MaterialTest("K-Monel (as-received)", 0.92, "small"),
    MaterialTest("309S Steel", 0.93, "small"),
    MaterialTest("Ni-SPAN-C (alloy 902)", 0.93, "small"),
    MaterialTest("316L Stainless Steel", 0.94, "small"),
    MaterialTest("X42 Pipeline Steel", 0.95, "small"),
    MaterialTest("MERL 76 (PM)", 0.96, "small"),
    MaterialTest("Incoloy 907", 0.96, "small"),

    # NEGLIGIBLE HEE (0.97-1.00+)
    MaterialTest("Beryllium Copper", 0.97, "negligible"),
    MaterialTest("NASA-HR1", 0.98, "negligible"),
    MaterialTest("70-30 Brass", 0.98, "negligible"),
    MaterialTest("Incoloy 903 (ST only)", 0.98, "negligible"),
    MaterialTest("D6AC Steel (600C tempered)", 0.98, "negligible"),
    MaterialTest("Monel 400", 0.98, "negligible"),
    MaterialTest("316 Stainless Steel", 0.98, "negligible"),
    MaterialTest("216 Steel", 0.99, "negligible"),
    MaterialTest("2024 Aluminum", 0.99, "negligible"),
    MaterialTest("7075 Aluminum", 0.99, "negligible"),
    MaterialTest("70/30 Cupronickel", 0.99, "negligible"),
    MaterialTest("22-13-5 (Nitronic 50)", 1.00, "negligible"),
    MaterialTest("OFHC Copper", 1.00, "negligible"),
    MaterialTest("6061 Aluminum", 1.00, "negligible"),
    MaterialTest("2011 Aluminum", 1.01, "negligible"),
    MaterialTest("5086 Aluminum", 1.05, "negligible"),
]


def check_result(result, expected_index: float) -> tuple[bool, str]:
    """Check if engine result matches expected.

    Rule: HEE index >= 0.70 is acceptable (caution), <0.70 is prohibited

    Safety approach:
    - OVER-conservative (prohibited when should be ok/caution) = safe
    - UNDER-conservative (ok/caution when should be prohibited) = dangerous
    """
    verdict = result.verdict

    # Map expected HEE index to expected verdict(s)
    if expected_index >= 0.90:
        # Good resistance - should be acceptable or caution
        expected_verdicts = [Verdict.ACCEPTABLE, Verdict.CAUTION]
    elif expected_index >= 0.70:
        # Moderate - should be caution
        expected_verdicts = [Verdict.CAUTION]
    else:
        # Severe/Extreme (<0.70) - should be prohibited
        expected_verdicts = [Verdict.PROHIBITED]

    if verdict in expected_verdicts:
        return True, "OK"
    else:
        expected_str = [v.value for v in expected_verdicts]
        return False, f"HEE={expected_index:.2f}->{expected_str}, got {verdict.value}"


def categorize_failures(results: list) -> dict:
    """Categorize failures by type."""
    over_conservative = []
    under_conservative = []
    unknown = []

    for material, result, expected_index in results:
        ok, _ = check_result(result, expected_index)
        if ok:
            continue

        verdict = result.verdict
        if verdict == Verdict.UNKNOWN:
            unknown.append((material, result, expected_index))
        elif expected_index >= 0.70 and verdict == Verdict.PROHIBITED:
            over_conservative.append((material, result, expected_index))
        elif expected_index < 0.70 and verdict in [Verdict.ACCEPTABLE, Verdict.CAUTION]:
            under_conservative.append((material, result, expected_index))
        else:
            # Other mismatch
            if verdict == Verdict.PROHIBITED:
                over_conservative.append((material, result, expected_index))
            else:
                under_conservative.append((material, result, expected_index))

    return {
        "over_conservative": over_conservative,
        "under_conservative": under_conservative,
        "unknown": unknown,
    }


def main():
    print("=" * 80)
    print("H2 Engine Authoritative Test Suite")
    print("NASA/TM-2016-218602 Table 2 - Complete Material Dataset")
    print("=" * 80)
    print()

    # Load engine
    engine = H2Engine()
    stats = engine.get_evidence_stats()
    print(f"Engine loaded: {stats['total_records']} evidence records")
    print(f"Running {len(AUTHORITATIVE_MATERIALS)} material tests...")
    print()

    results = []
    passed = 0
    failed = 0

    for mat in AUTHORITATIVE_MATERIALS:
        result = engine.query(mat.material)
        results.append((mat, result, mat.hee_index))

        ok, msg = check_result(result, mat.hee_index)
        if ok:
            passed += 1
            status = "PASS"
        else:
            failed += 1
            status = "FAIL"

        # Only print failures
        if status == "FAIL":
            actual_band = result.hee_band if result.hee_band else "unknown"
            print(f"[{status:5}] {mat.material:35} | expected={mat.expected_band:10} | "
                  f"got={actual_band:10} | verdict={result.verdict.value}")

    print()
    print("=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(AUTHORITATIVE_MATERIALS)}")
    print(f"Pass rate: {100*passed/len(AUTHORITATIVE_MATERIALS):.1f}%")
    print("=" * 80)

    # Categorize failures
    failures = categorize_failures(results)

    print()
    print("FAILURE ANALYSIS:")
    print("-" * 80)

    if failures["under_conservative"]:
        print(f"\n*** UNDER-CONSERVATIVE ({len(failures['under_conservative'])}) - SAFETY CONCERN! ***")
        print("(Returns acceptable/caution when should be prohibited)")
        for mat, result, expected_index in failures["under_conservative"]:
            print(f"  {mat.material:35} HEE={expected_index:.2f} got {result.verdict.value}")

    if failures["over_conservative"]:
        print(f"\n+++ Over-conservative ({len(failures['over_conservative'])}) - Safe but restrictive +++")
        print("(Returns prohibited when should be acceptable/caution)")
        for mat, result, expected_index in failures["over_conservative"]:
            print(f"  {mat.material:35} HEE={expected_index:.2f} got {result.verdict.value}")

    if failures["unknown"]:
        print(f"\n??? Unknown ({len(failures['unknown'])}) - Material not found ???")
        for mat, result, expected_index in failures["unknown"]:
            print(f"  {mat.material:35} HEE={expected_index:.2f}")

    # Print summary statistics
    total_failures = sum(len(v) for v in failures.values())
    safe_failures = len(failures["over_conservative"])
    unsafe_failures = len(failures["under_conservative"])
    unknown_count = len(failures["unknown"])

    print()
    print("=" * 80)
    print("SUMMARY:")
    print(f"  - Total materials tested: {len(AUTHORITATIVE_MATERIALS)}")
    print(f"  - Passed: {passed} ({100*passed/len(AUTHORITATIVE_MATERIALS):.1f}%)")
    print(f"  - Failed: {failed} ({100*failed/len(AUTHORITATIVE_MATERIALS):.1f}%)")
    print(f"    - Over-conservative (safe): {safe_failures}")
    print(f"    - Under-conservative (DANGER): {unsafe_failures}")
    print(f"    - Unknown material: {unknown_count}")
    print("=" * 80)

    # Return exit code based on failures
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
