#!/usr/bin/env python3
"""
Test the 2-Phase MIUL Pipeline.

Phase 1: DT PDF -> DT JSON (hierarchy)
Phase 2: Drawing PDFs -> Parts JSON (materials/specs)
Phase 3: DT JSON + Parts JSON -> MIUL Excel

This tests both DMLLV (MER prefix) and GPE (GPE- prefix) projects.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, r"C:\BoundState")

from mira.miul.v3.builder import build_miul_2phase, merge_dt_and_parts
from mira.miul.v3.extract import extract_drawing_tree, extract_parts_json, VisionClient


def test_with_existing_jsons():
    """Test merge with pre-extracted JSONs (no API calls)."""
    print("\n" + "=" * 60)
    print("TEST 1: Merge with Existing JSONs (No API)")
    print("=" * 60)

    # Test with DMLLV if JSONs exist
    dmllv_dt = Path(r"C:\Users\jwilde2\Desktop\DMLLV\MER07540-DT.DRW_-.6.extracted.json")

    if dmllv_dt.exists():
        print(f"\nUsing existing DT JSON: {dmllv_dt.name}")
        with open(dmllv_dt, "r") as f:
            dt_json = json.load(f)

        print(f"  Top level: {dt_json.get('top_level')}")
        print(f"  Tree entries: {len(dt_json.get('tree', []))}")

        # Create minimal parts JSON for testing
        parts_json = {
            "metadata": {"source": "test", "parts_found": 0, "drawings_processed": 0},
            "parts": {},
            "drawings": {},
        }

        # Test merge
        df = merge_dt_and_parts(dt_json, parts_json, "DMLLV-Test")
        print(f"\n  Merged MIUL rows: {len(df)}")

        # Show first few rows
        if len(df) > 0:
            print("\n  First 5 rows:")
            for _, row in df.head(5).iterrows():
                pn = row.get("Part Number", "?")
                nha = row.get("NHA", "?")
                print(f"    {pn:<20} -> NHA: {nha}")

        return True
    else:
        print("  SKIP: No existing DMLLV DT JSON found")
        return False


def test_gpe_dt_json():
    """Test with GPE's pre-extracted JSON."""
    print("\n" + "=" * 60)
    print("TEST 2: GPE DT JSON Structure")
    print("=" * 60)

    gpe_dt = Path(r"C:\Users\jwilde2\Desktop\GPE\GPE-DOC-004-D (GPE Drawing Tree).json")

    if gpe_dt.exists():
        print(f"\nLoading GPE DT JSON: {gpe_dt.name}")
        with open(gpe_dt, "r") as f:
            gpe_json = json.load(f)

        # GPE JSON is in nested format, need to convert
        from mira.miul.v3.extract import _convert_nested_to_flat

        flat_dt = _convert_nested_to_flat(gpe_json)
        print(f"  Top level: {flat_dt.get('top_level')}")
        print(f"  Tree entries: {len(flat_dt.get('tree', []))}")

        # Show hierarchy
        print("\n  Hierarchy (first 10 entries):")
        for entry in flat_dt.get("tree", [])[:10]:
            pn = entry.get("drawing_number", "?")
            parent = entry.get("parent") or "(root)"
            print(f"    {pn:<18} -> {parent}")

        # Test merge
        parts_json = {
            "metadata": {"source": "test"},
            "parts": {},
            "drawings": {},
        }

        df = merge_dt_and_parts(flat_dt, parts_json, "GPE-Test")
        print(f"\n  Merged MIUL rows: {len(df)}")

        return True
    else:
        print("  SKIP: No GPE DT JSON found")
        return False


def test_full_pipeline_dmllv():
    """Test full 2-phase pipeline with DMLLV (requires API)."""
    print("\n" + "=" * 60)
    print("TEST 3: Full 2-Phase Pipeline - DMLLV")
    print("=" * 60)

    dmllv_dir = Path(r"C:\Users\jwilde2\Desktop\DMLLV")

    if not dmllv_dir.exists():
        print(f"  SKIP: DMLLV directory not found: {dmllv_dir}")
        return False

    # Check for API key
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  SKIP: No ANTHROPIC_API_KEY set")
        return False

    print(f"\nProcessing: {dmllv_dir}")

    # Output paths
    dt_json_path = dmllv_dir / "dt_tree.json"
    parts_json_path = dmllv_dir / "parts.json"
    output_excel = dmllv_dir / "DMLLV_MIUL_2phase.xlsx"

    try:
        df, stats = build_miul_2phase(
            dmllv_dir,
            output_excel=output_excel,
            dt_json_path=dt_json_path,
            parts_json_path=parts_json_path,
        )

        print(f"\n  Results:")
        print(f"    DT Entries: {stats.get('dt_entries', 0)}")
        print(f"    Parts Found: {stats.get('parts_found', 0)}")
        print(f"    MIUL Rows: {stats.get('miul_rows', 0)}")
        print(f"    Materials Found: {stats.get('materials_found', 0)}")

        if stats.get("issues"):
            print(f"\n  Issues ({len(stats['issues'])}):")
            for issue in stats["issues"][:5]:
                print(f"    - {issue[:80]}")

        print(f"\n  Output: {output_excel}")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_pipeline_gpe():
    """Test full 2-phase pipeline with GPE (requires API)."""
    print("\n" + "=" * 60)
    print("TEST 4: Full 2-Phase Pipeline - GPE")
    print("=" * 60)

    gpe_dir = Path(r"C:\Users\jwilde2\Desktop\GPE")

    if not gpe_dir.exists():
        print(f"  SKIP: GPE directory not found: {gpe_dir}")
        return False

    # Check for API key
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  SKIP: No ANTHROPIC_API_KEY set")
        return False

    print(f"\nProcessing: {gpe_dir}")

    # Output paths
    dt_json_path = gpe_dir / "dt_tree.json"
    parts_json_path = gpe_dir / "parts.json"
    output_excel = gpe_dir / "GPE_MIUL_2phase.xlsx"

    try:
        df, stats = build_miul_2phase(
            gpe_dir,
            output_excel=output_excel,
            dt_json_path=dt_json_path,
            parts_json_path=parts_json_path,
        )

        print(f"\n  Results:")
        print(f"    DT Entries: {stats.get('dt_entries', 0)}")
        print(f"    Parts Found: {stats.get('parts_found', 0)}")
        print(f"    MIUL Rows: {stats.get('miul_rows', 0)}")
        print(f"    Materials Found: {stats.get('materials_found', 0)}")

        if stats.get("issues"):
            print(f"\n  Issues ({len(stats['issues'])}):")
            for issue in stats["issues"][:5]:
                print(f"    - {issue[:80]}")

        print(f"\n  Output: {output_excel}")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("2-PHASE MIUL PIPELINE TEST SUITE")
    print("=" * 60)
    print("\nThis tests the new architecture:")
    print("  Phase 1: DT PDF -> DT JSON (hierarchy)")
    print("  Phase 2: Drawing PDFs -> Parts JSON (materials)")
    print("  Phase 3: Merge -> MIUL Excel")

    results = {}

    # Test 1: Merge with existing JSONs (no API needed)
    results["merge_existing"] = test_with_existing_jsons()

    # Test 2: GPE DT JSON structure
    results["gpe_dt_json"] = test_gpe_dt_json()

    # Test 3 & 4: Full pipeline (requires API)
    results["dmllv_pipeline"] = test_full_pipeline_dmllv()
    results["gpe_pipeline"] = test_full_pipeline_gpe()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "PASS" if result else "SKIP/FAIL"
        print(f"  {name:<20}: {status}")

    print(f"\n  Result: {passed}/{total} tests passed")

    return 0 if passed >= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
