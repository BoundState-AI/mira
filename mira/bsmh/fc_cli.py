#!/usr/bin/env python3
"""
Fracture Control Authority Pack — Standalone CLI Tester.

Tests the deterministic classification engine WITHOUT requiring
database, API keys, or running server.

Usage:
    python -m mira.bsmh.fc_cli
    python -m mira.bsmh.fc_cli --interactive

BoundState AI 2026
Co-Authored-By: Claude "Beth" Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
import sys

from .fracture_engine import build_fracture_decision, SEED_CLASSIFICATION_RULES
from .models import FractureContextInput


# =============================================================================
# Gold-Set Test Cases (deterministic expected outputs)
# =============================================================================

GOLD_SET = [
    {
        "name": "Catastrophic pressure vessel → FRACTURE_CRITICAL_1",
        "context": {
            "material": "Inconel 718",
            "part_name": "Main combustion chamber",
            "pressure_boundary": True,
            "consequence_of_failure": "catastrophic",
            "inspectability": "non_inspectable",
            "geometry_type": "pressure_vessel",
            "material_condition": "wrought",
            "center_code": "MSFC",
        },
        "expected_class": "FRACTURE_CRITICAL_1",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": True,
        "expected_fcr_count_min": 13,
    },
    {
        "name": "Catastrophic structural (non-pressure) → FRACTURE_CRITICAL_1",
        "context": {
            "material": "Ti-6Al-4V",
            "part_name": "Thrust structure strut",
            "pressure_boundary": False,
            "consequence_of_failure": "catastrophic",
            "inspectability": "limited_access",
            "geometry_type": "structural",
            "material_condition": "forged",
        },
        "expected_class": "FRACTURE_CRITICAL_1",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": True,
        "expected_fcr_count_min": 13,
    },
    {
        "name": "Critical pressure boundary → FRACTURE_CRITICAL_2",
        "context": {
            "material": "316L",
            "part_name": "Propellant feed line",
            "pressure_boundary": True,
            "consequence_of_failure": "critical",
            "inspectability": "inspectable",
            "geometry_type": "line",
            "material_condition": "wrought",
        },
        "expected_class": "FRACTURE_CRITICAL_2",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": True,
        "expected_fcr_count_min": 10,
    },
    {
        "name": "Critical non-inspectable structural → FRACTURE_CRITICAL_2",
        "context": {
            "material": "Al 2219-T87",
            "part_name": "Internal bracket",
            "pressure_boundary": False,
            "consequence_of_failure": "critical",
            "inspectability": "non_inspectable",
            "geometry_type": "structural",
            "material_condition": "wrought",
        },
        "expected_class": "FRACTURE_CRITICAL_2",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": True,
        "expected_fcr_count_min": 10,
    },
    {
        "name": "Critical inspectable → LOW_RISK_FRACTURE",
        "context": {
            "material": "Al 6061-T6",
            "part_name": "Access panel frame",
            "pressure_boundary": False,
            "consequence_of_failure": "critical",
            "inspectability": "inspectable",
            "geometry_type": "structural",
            "material_condition": "wrought",
        },
        "expected_class": "LOW_RISK_FRACTURE",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": False,
        "expected_fcr_count_min": 3,
    },
    {
        "name": "Non-critical → NON_FRACTURE_CRITICAL",
        "context": {
            "material": "Al 6061-T6",
            "part_name": "Equipment shelf",
            "pressure_boundary": False,
            "consequence_of_failure": "non_critical",
            "inspectability": "inspectable",
            "geometry_type": "structural",
            "material_condition": "wrought",
        },
        "expected_class": "NON_FRACTURE_CRITICAL",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": False,
        "expected_fcr_count_min": 1,
    },
    {
        "name": "Missing required fields → NEEDS_CLARIFICATION",
        "context": {
            "material": "Inconel 625",
            "part_name": "Unknown fitting",
        },
        "expected_class": "UNCLASSIFIED",
        "expected_verdict": "NEEDS_CLARIFICATION",
        "expected_nde": False,
        "expected_fcr_count_min": 0,
    },
    {
        "name": "Empty context → NEEDS_CLARIFICATION",
        "context": {},
        "expected_class": "UNCLASSIFIED",
        "expected_verdict": "NEEDS_CLARIFICATION",
        "expected_nde": False,
        "expected_fcr_count_min": 0,
    },
    # --- Regression: non_critical must NOT match LOW_RISK_FRACTURE ---
    {
        "name": "Non-critical non-inspectable → NON_FRACTURE_CRITICAL (not LOW_RISK)",
        "context": {
            "material": "Al 2024-T3",
            "part_name": "Cable tray support",
            "pressure_boundary": False,
            "consequence_of_failure": "non_critical",
            "inspectability": "non_inspectable",
            "geometry_type": "structural",
            "material_condition": "wrought",
        },
        "expected_class": "NON_FRACTURE_CRITICAL",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": False,
        "expected_fcr_count_min": 1,
    },
    # --- Consensus Record hybrid gold-set: PH13-8Mo fastener ---
    # This tests the FC engine classification only; hydrogen compatibility
    # is assessed by the materials pipeline in a hybrid query.
    {
        "name": "PH13-8Mo fracture-critical fastener (Consensus Record test)",
        "context": {
            "material": "PH13-8Mo",
            "part_name": "High-pressure bolt",
            "pressure_boundary": True,
            "consequence_of_failure": "catastrophic",
            "inspectability": "non_inspectable",
            "geometry_type": "fastener",
            "material_condition": "wrought",
            "center_code": "MSFC",
            "operating_pressure_psi": 5000,
            "operating_pressure_unit": "psi",
        },
        "expected_class": "FRACTURE_CRITICAL_1",
        "expected_verdict": "CLASSIFIED",
        "expected_nde": True,
        "expected_fcr_count_min": 13,
    },
]


def _run_gold_set() -> bool:
    """Run all gold-set tests. Returns True if all pass."""
    print("=" * 70)
    print("FRACTURE CONTROL AUTHORITY PACK — GOLD SET VALIDATION")
    print("=" * 70)
    print()

    passed = 0
    failed = 0

    for i, test in enumerate(GOLD_SET, 1):
        ctx = FractureContextInput.model_validate(test["context"])
        result = build_fracture_decision(context=ctx)

        cls = result.classification
        actual_class = cls.part_class if cls else "NONE"
        actual_nde = cls.nde_required if cls else False
        actual_fcr_count = len(cls.fcr_set) if cls else 0

        checks = [
            ("verdict", result.verdict, test["expected_verdict"]),
            ("part_class", actual_class, test["expected_class"]),
            ("nde_required", actual_nde, test["expected_nde"]),
        ]
        fcr_ok = actual_fcr_count >= test["expected_fcr_count_min"]

        all_ok = all(actual == expected for _, actual, expected in checks) and fcr_ok

        status = "✓ PASS" if all_ok else "✗ FAIL"
        if all_ok:
            passed += 1
        else:
            failed += 1

        print(f"  [{status}] Test {i}: {test['name']}")
        if not all_ok:
            for label, actual, expected in checks:
                if actual != expected:
                    print(f"         {label}: expected={expected}, got={actual}")
            if not fcr_ok:
                print(f"         fcr_count: expected>={test['expected_fcr_count_min']}, got={actual_fcr_count}")
        print(f"         Rules applied: {result.rules_applied}")
        print()

    print("=" * 70)
    print(f"  RESULTS: {passed} passed, {failed} failed, {len(GOLD_SET)} total")
    print("=" * 70)

    return failed == 0


def _interactive_mode():
    """Interactive classification with manual input."""
    print("\nFRACTURE CONTROL CLASSIFICATION — INTERACTIVE MODE")
    print("Enter context fields (blank = null, 'q' = quit)\n")

    while True:
        print("-" * 50)
        material = input("Material designation: ").strip() or None
        if material and material.lower() == "q":
            break
        part_name = input("Part name: ").strip() or None

        pb_raw = input("Pressure boundary? (y/n/blank): ").strip().lower()
        pressure_boundary = True if pb_raw == "y" else (False if pb_raw == "n" else None)

        cof = input("Consequence of failure (catastrophic/critical/non_critical/blank): ").strip() or None
        insp = input("Inspectability (inspectable/limited_access/non_inspectable/blank): ").strip() or None
        geom = input("Geometry type (pressure_vessel/fitting/line/structural/fastener/mechanism/other/blank): ").strip() or None
        cond = input("Material condition (wrought/cast/forged/welded/am_printed/powder_metallurgy/blank): ").strip() or None
        center = input("Center code (MSFC/JSC/KSC/GRC/blank): ").strip() or None

        ctx = FractureContextInput(
            material=material,
            part_name=part_name,
            pressure_boundary=pressure_boundary,
            consequence_of_failure=cof,
            inspectability=insp,
            geometry_type=geom,
            material_condition=cond,
            center_code=center,
        )

        result = build_fracture_decision(context=ctx)
        print(f"\n{'=' * 50}")
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        print(f"{'=' * 50}\n")


def main():
    if "--interactive" in sys.argv:
        _interactive_mode()
    else:
        success = _run_gold_set()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
