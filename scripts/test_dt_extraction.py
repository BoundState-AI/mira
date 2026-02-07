#!/usr/bin/env python3
"""
Test script for Drawing Tree (DT) extraction.

Tests the updated DT_EXTRACTION_PROMPT against MER07540-DT to verify
correct NHA parent-child relationship parsing.

Usage:
    python scripts/test_dt_extraction.py

BoundState AI 2025
"""

import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.miul.v3.extract import extract_drawing_tree, VisionClient


# VSClaude's correct NHA mapping (ground truth)
EXPECTED_NHA = {
    # Direct children of MER07540-001
    "MER07560-001": "MER07540-001",  # VALVE BODY SUB-ASSEMBLY
    "MER07543-001": "MER07540-001",  # SHAFT ASSEMBLY
    "MER07570-001": "MER07540-001",  # ACTUATOR ASSEMBLY
    "MER07550-001": "MER07540-001",  # DRIVE LINK
    "MER07571-001": "MER07540-001",  # CONNECTING ROD

    # Under MER07560-001 (VALVE BODY SUB-ASSEMBLY)
    "MER07563-001": "MER07560-001",  # BODY INSERT ASSEMBLY
    "MER07565-001": "MER07560-001",  # SHAFT, OFFSET, SUB-ASSEMBLY
    "MER07584-001": "MER07560-001",  # POPPET SUB-ASSEMBLY
    "MER07545-001": "MER07560-001",  # LOWER CAM MOUNT

    # Under MER07563-001 (BODY INSERT ASSEMBLY)
    "MER07564-001": "MER07563-001",  # BODY
    "MER07561-001": "MER07563-001",  # RING, RETAINING
    "MER07562-001": "MER07563-001",  # SEAT
    "MER07569-001": "MER07563-001",  # BRACE, REAR

    # Under MER07565-001 (SHAFT, OFFSET, SUB-ASSEMBLY)
    "MER07567-001": "MER07565-001",  # SHAFT, OFFSET, INSERT INSTALL
    "MER07568-001": "MER07565-001",  # SHAFT, OFFSET
    "MER07566-001": "MER07565-001",  # ROTARY TANG, OFFSET SHAFT

    # Under MER07584-001 (POPPET SUB-ASSEMBLY)
    "MER07585-001": "MER07584-001",  # POPPET, VALVE
    "MER07586-001": "MER07584-001",  # COUPLING, POPPET
    "MER07587-001": "MER07584-001",  # INTERFACE RING
    "MER07588-001": "MER07584-001",  # PUSHER, BALL

    # Under MER07545-001 (LOWER CAM MOUNT)
    "MER07546-001": "MER07545-001",  # PRELOAD DISC
    "MER07553-001": "MER07545-001",  # COVER, BEARING
    "MER07554-001": "MER07545-001",  # SLIDER, ROTARY TANG
    "MER07555-001": "MER07545-001",  # PIN, TRANSLATING
    "MER07556-001": "MER07545-001",  # RING, INTERMEDIATE
    "MER07557-001": "MER07545-001",  # SHAFT, CENTER
    "MER07558-001": "MER07545-001",  # OFFSET ROTARY SHAFT, LOWER
    "MER07559-001": "MER07545-001",  # OFFSET ROTARY SHAFT, UPPER

    # Under MER07570-001 (ACTUATOR ASSEMBLY)
    "MER07573-001": "MER07570-001",  # ACTUATOR WELD ASSEMBLY
    "MER07580-001": "MER07570-001",  # CAP, ACTUATOR
    "MER07574-001": "MER07570-001",  # HOUSING, ACTUATOR
    "MER07548-001": "MER07570-001",  # MOUNT BRACKET
    "MER07572-001": "MER07570-001",  # BRACKET, ANGLE

    # Under MER07573-001 (ACTUATOR WELD ASSEMBLY)
    "MER07581-001": "MER07573-001",  # SHAFT, PISTON
    "MER07576": "MER07573-001",      # ACTUATOR INTERNAL WELD ASSEMBLY
    "MER07582-001": "MER07573-001",  # BELLOWS, INTERNAL
    "MER07577-001": "MER07573-001",  # MOUNT CAP
    "MER07583-001": "MER07573-001",  # BELLOWS, EXTERNAL
    "MER07578-001": "MER07573-001",  # BUSHING, SMALL
    "MER07579-001": "MER07573-001",  # BUSHING, LARGE
}


def test_dt_extraction(dt_path: Path) -> dict:
    """
    Extract and validate the Drawing Tree.

    Returns:
        dict with 'correct', 'incorrect', 'missing', 'extra' keys
    """
    LOGGER.info(f"Testing DT extraction on: {dt_path}")

    client = VisionClient()
    result = extract_drawing_tree(dt_path, client)

    if not result or not result.get("tree"):
        LOGGER.error("DT extraction returned no tree!")
        return {"error": "No tree extracted"}

    tree_entries = result["tree"]
    LOGGER.info(f"Extracted {len(tree_entries)} entries from DT")
    LOGGER.info(f"Top-level assembly: {result.get('top_level', '?')}")

    # Build extracted NHA map
    extracted_nha = {}
    for entry in tree_entries:
        child = entry.get("drawing_number", "").strip()
        parent = (entry.get("parent") or "").strip()
        if child and parent:
            extracted_nha[child] = parent

    # Compare with expected
    correct = []
    incorrect = []
    missing = []
    extra = []

    for child, expected_parent in EXPECTED_NHA.items():
        if child in extracted_nha:
            actual_parent = extracted_nha[child]
            if actual_parent == expected_parent:
                correct.append(child)
            else:
                incorrect.append({
                    "child": child,
                    "expected": expected_parent,
                    "actual": actual_parent
                })
        else:
            missing.append({
                "child": child,
                "expected": expected_parent
            })

    # Check for extra entries not in expected
    for child in extracted_nha:
        if child not in EXPECTED_NHA and child != result.get("top_level"):
            extra.append({
                "child": child,
                "parent": extracted_nha[child]
            })

    return {
        "correct": correct,
        "incorrect": incorrect,
        "missing": missing,
        "extra": extra,
        "total_expected": len(EXPECTED_NHA),
        "total_extracted": len(extracted_nha),
    }


def main():
    dt_path = Path(r"C:\Users\jwilde2\Desktop\DMLLV\MER07540-DT.DRW_-.6.pdf")

    if not dt_path.exists():
        LOGGER.error(f"DT file not found: {dt_path}")
        return 1

    results = test_dt_extraction(dt_path)

    if "error" in results:
        LOGGER.error(f"Extraction failed: {results['error']}")
        return 1

    # Print results
    print("\n" + "="*80)
    print("DT EXTRACTION TEST RESULTS")
    print("="*80)

    print(f"\nTotal expected NHA entries: {results['total_expected']}")
    print(f"Total extracted NHA entries: {results['total_extracted']}")

    correct_count = len(results['correct'])
    incorrect_count = len(results['incorrect'])
    missing_count = len(results['missing'])

    accuracy = (correct_count / results['total_expected'] * 100) if results['total_expected'] > 0 else 0
    print(f"\nAccuracy: {accuracy:.1f}% ({correct_count}/{results['total_expected']} correct)")

    if results['correct']:
        print(f"\n[OK] CORRECT ({len(results['correct'])} entries):")
        for child in sorted(results['correct'])[:10]:
            print(f"  {child} -> {EXPECTED_NHA[child]}")
        if len(results['correct']) > 10:
            print(f"  ... and {len(results['correct']) - 10} more")

    if results['incorrect']:
        print(f"\n[WRONG] INCORRECT ({len(results['incorrect'])} entries):")
        for item in results['incorrect']:
            print(f"  {item['child']}: expected {item['expected']}, got {item['actual']}")

    if results['missing']:
        print(f"\n? MISSING ({len(results['missing'])} entries):")
        for item in results['missing']:
            print(f"  {item['child']} (expected parent: {item['expected']})")

    if results['extra']:
        print(f"\n+ EXTRA ({len(results['extra'])} entries not in expected):")
        for item in results['extra'][:5]:
            print(f"  {item['child']} -> {item['parent']}")
        if len(results['extra']) > 5:
            print(f"  ... and {len(results['extra']) - 5} more")

    print("\n" + "="*80)

    # Return exit code based on accuracy
    if accuracy >= 90:
        print("[PASS] Extraction accuracy >= 90%")
        return 0
    else:
        print("[FAIL] Extraction accuracy < 90%")
        return 1


if __name__ == "__main__":
    sys.exit(main())
