#!/usr/bin/env python3
"""
Post-correction script for MIUL V3 output.

Applies all known corrections from the V3 extractor fixes to an existing
MIUL Excel file without re-running the full vision extraction pipeline.

Fixes applied:
1. Part number OCR corrections (vision API misreads)
2. Material spec garbage rejection (CAGE codes, numeric junk)
3. Designation pollution cleanup (vendor/supplier info)
4. Standard parts material lookup (MS21043, NAS fasteners, etc.)
5. Known designation corrections (Inconel 625 vs 718, Vespel SP-3 vs SP-21)

Usage:
    python scripts/fix_miul_v3.py

Output:
    C:/Users/jwilde2/Desktop/DMLLV/DMLLV_MIUL_v3_corrected.xlsx
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from mira.miul.v3.ocr_correction import (
    correct_part_number,
    clean_designation,
    clean_material_spec,
    correct_ocr_errors,
    lookup_standard_part_material,
)

V3_PATH = r"C:\Users\jwilde2\Desktop\DMLLV\DMLLV_MIUL_v3.xlsx"
OUTPUT_PATH = r"C:\Users\jwilde2\Desktop\DMLLV\DMLLV_MIUL_v3_corrected.xlsx"

# MER07543-001 find number -> actual part number mapping
# The vision API returned find numbers (1,2,3...) instead of actual PNs
# for this assembly's EPL. Per MIUL spec (SLS-RQMT-340 Appendix F),
# Part Number column must contain actual part/drawing numbers, not find numbers.
FIND_NUMBER_MAP_MER07543 = {
    "1": "MER07560-001",     # VALVE BODY SUB-ASSEMBLY
    "2": "MER07565-001",     # SHAFT, OFFSET, SUB-ASSEMBLY
    "3": "51109",            # BEARING, THRUST
    "4": "MER07557-001",     # SHAFT, CENTER
    "5": "6915",             # BEARING, THIN SECTION
    "6": "6824",             # BEARING, SINGLE ROW RADIAL
    "7": "MER07558-001",     # OFFSET ROTARY SHAFT, LOWER
    "8": "MER07559-001",     # OFFSET ROTARY SHAFT, UPPER
    # Find 9 = DELETED on drawing (not a real part, skip)
    "10": "MER07556-001",    # RING, INTERMEDIATE, ROTATIONAL
    "11": "MER07554-001",    # SLIDER, ROTARY TANG
    "12": "MER07555-001",    # PIN, TRANSLATING
    "13": "M12133/2-255",    # WASHER, BELLEVILLE, .25 ID
    "14": "MER07553-001",    # COVER, BEARING
    "15": "16007",           # BEARING, DEEP GROOVE (Si3N4)
    # Find 16 has two rows: retaining ring + bearing (resolved via FIND_16_MAP)
    "17": "MER07546-001",    # PRELOAD DISC (BEARING DISC on drawing)
    "18": "M12133/2-100",    # WASHER, BELLEVILLE, 1.0 ID
    "19": "97022A388",       # RING SHIM
    "20": "MER07545-001",    # LOWER CAM MODULE
    "21": "NAS1352N4-12",    # SHCS, .2500-20, .750 LG
    "22": "NAS1352N4-14",    # SHCS, .2500-20, .875 LG
    # Find 23 appears twice: washer + SHCS (resolved via FIND_23_MAP)
    "24": "MER07584-001",    # POPPET SUB-ASSEMBLY
    "25": "2949T32",         # HOIST RING
    "26": "6.",              # LUBRICANT, LOX COMPATIBLE (note reference per drawing)
    "27": "NAS1351N4H16",   # SHCS, DRILLED, .2500-28
    "28": "NAS509-4C",       # NUT, JAM, DRILLED
    "29": "NASM20995N32",    # WIRE, SAFETY OR LOCK
}

# Special handling for find 16 (two items) and find 23 (two items)
# These are resolved by description matching in fix_find_numbers()
FIND_16_MAP = {
    "RETAINING RING": "WHM-244-S86",
    "BEARING": "16007",
}

FIND_23_MAP = {
    "WASHER": "NAS1149E0432R",
    "SHCS": "NAS1352N4-12",
}

# Known designation corrections from comparison with human review
# These are cases where the vision extraction picked up wrong material
# from a different location on the drawing
DESIGNATION_OVERRIDES = {
    # MER07574-001 under MER07573-001 EPL shows "INCONEL 718" but the
    # detail drawing clearly says INCONEL 625 per AMS 5666 / UNS N06625
    # The 718 came from bellows material on the same assembly drawing
    ("MER07574-001", "MER07573-001"): {
        "designation": "INCONEL 625",
        "material_spec": "SAE AMS 5666",
    },
    # Vespel bushings: EPL on MER07573-001 says "VESPEL SP-21" but
    # detail drawings MER07578/79 say "VESPEL SP-3"
    ("MER07578-001", "MER07573-001"): {
        "designation": "VESPEL SP-3 POLYIMIDE RESIN",
        "material_spec": "ASTM 6456-10",
    },
    ("MER07579-001", "MER07573-001"): {
        "designation": "VESPEL SP-3 POLYIMIDE RESIN",
        "material_spec": "ASTM 6456-10",
    },
    # MER07580-001 under MER07560-001 shows "7075 AL" but detail drawing
    # clearly says INCONEL 625 per AMS 5666
    ("MER07580-001", "MER07560-001"): {
        "designation": "INCONEL 625",
        "material_spec": "AMS 5666",
    },
}


def norm(val):
    """Normalize a cell value to string."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    return str(val).strip()


def fix_find_numbers(row):
    """
    Resolve find numbers to actual part numbers for MER07543-001 EPL.

    Returns (row, changes) with the part number corrected if it was a find number.
    """
    changes = []
    nha = norm(row.get("NHA", ""))
    pn = norm(row.get("Part Number", ""))
    desc = norm(row.get("Part Description", "")).upper()

    if nha != "MER07543-001":
        return row, changes

    # Check if PN is a find number (simple integer)
    if not pn or not pn.rstrip(".").isdigit():
        return row, changes

    find_no = pn.rstrip(".")

    # Find 9 is DELETED on the drawing - not a real part
    if find_no == "9":
        changes.append(
            "  Find# 9 -> DELETED (marked on drawing as deleted)"
        )
        row["Part Description"] = "DELETED"
        row["_deleted"] = True
        return row, changes

    # Handle special multi-item find numbers
    if find_no == "16":
        if "RETAINING" in desc:
            new_pn = FIND_16_MAP.get("RETAINING RING", pn)
        elif "GROOVE" in desc or "DEEP" in desc:
            new_pn = FIND_16_MAP.get("BEARING", pn)
        else:
            new_pn = pn
    elif find_no == "23":
        if "WASHER" in desc or "FLAT" in desc:
            new_pn = FIND_23_MAP.get("WASHER", pn)
        elif "SHCS" in desc or "CAP SCREW" in desc:
            new_pn = FIND_23_MAP.get("SHCS", pn)
        else:
            new_pn = pn
    else:
        new_pn = FIND_NUMBER_MAP_MER07543.get(find_no, pn)

    if new_pn != pn:
        changes.append(
            "  Find# %s -> PN '%s' (was find number)" % (find_no, new_pn)
        )
        row["Part Number"] = new_pn

    return row, changes


def fix_row(row):
    """Apply corrections to a single MIUL row."""
    changes = []

    # 0. Resolve find numbers to actual part numbers (MER07543)
    row, fn_changes = fix_find_numbers(row)
    changes.extend(fn_changes)

    # 1. Fix part number
    old_pn = norm(row.get("Part Number", ""))
    new_pn = correct_part_number(old_pn)
    if new_pn != old_pn and old_pn:
        changes.append(f"  PN: '{old_pn}' -> '{new_pn}'")
        row["Part Number"] = new_pn

    # 2. Clean designation (remove vendor pollution)
    old_desig = norm(row.get("Designation", ""))
    if old_desig:
        # Apply OCR correction first
        new_desig = correct_ocr_errors(old_desig)
        new_desig = clean_designation(new_desig)
        if new_desig != old_desig:
            changes.append(f"  Designation: '{old_desig[:60]}' -> '{new_desig}'")
            row["Designation"] = new_desig

    # 3. Clean material spec (reject garbage)
    old_spec = norm(row.get("Material Specification", ""))
    if old_spec:
        new_spec = clean_material_spec(old_spec)
        if new_spec != old_spec:
            changes.append(f"  MatSpec: '{old_spec}' -> '{new_spec or '<rejected>'}'")
            row["Material Specification"] = new_spec

    # 4. Apply designation overrides (known wrong extractions)
    pn = norm(row.get("Part Number", ""))
    nha = norm(row.get("NHA", ""))
    override_key = (pn, nha)
    if override_key in DESIGNATION_OVERRIDES:
        override = DESIGNATION_OVERRIDES[override_key]
        if "designation" in override:
            old_d = norm(row.get("Designation", ""))
            if old_d != override["designation"]:
                changes.append(
                    f"  Designation OVERRIDE: '{old_d}' -> '{override['designation']}'"
                )
                row["Designation"] = override["designation"]
        if "material_spec" in override:
            old_s = norm(row.get("Material Specification", ""))
            if old_s != override["material_spec"]:
                changes.append(
                    f"  MatSpec OVERRIDE: '{old_s}' -> '{override['material_spec']}'"
                )
                row["Material Specification"] = override["material_spec"]

    # 5. Standard parts material lookup (fill gaps)
    pn = norm(row.get("Part Number", ""))
    desig = norm(row.get("Designation", ""))
    spec = norm(row.get("Material Specification", ""))

    if pn and not desig:
        std = lookup_standard_part_material(pn)
        if std:
            row["Designation"] = std["designation"]
            changes.append(
                f"  Std part lookup: '{pn}' -> Designation='{std['designation']}'"
            )
            if not spec and std.get("material_spec"):
                row["Material Specification"] = std["material_spec"]
                changes.append(f"  Std part lookup: MatSpec='{std['material_spec']}'")
    elif pn and desig and not spec:
        std = lookup_standard_part_material(pn)
        if std and std.get("material_spec"):
            row["Material Specification"] = std["material_spec"]
            changes.append(
                f"  Std part spec fill: '{pn}' -> MatSpec='{std['material_spec']}'"
            )

    # 6. Fix NHA part numbers too
    old_nha = norm(row.get("NHA", ""))
    if old_nha:
        new_nha = correct_part_number(old_nha)
        if new_nha != old_nha:
            changes.append(f"  NHA: '{old_nha}' -> '{new_nha}'")
            row["NHA"] = new_nha

    # 7. Fix Drawing Source part numbers
    old_ds = norm(row.get("Drawing Source", ""))
    if old_ds:
        new_ds = correct_part_number(old_ds)
        if new_ds != old_ds:
            changes.append(f"  DrawSrc: '{old_ds}' -> '{new_ds}'")
            row["Drawing Source"] = new_ds

    return row, changes


def main():
    print("=" * 80)
    print("  MIUL V3 Post-Correction Tool")
    print("=" * 80)
    print(f"Input:  {V3_PATH}")
    print(f"Output: {OUTPUT_PATH}")
    print()

    # Load V3 MIUL
    df = pd.read_excel(V3_PATH)
    print(f"Loaded {len(df)} rows")
    print()

    # Apply fixes row by row
    total_changes = 0
    pn_fixes = 0
    desig_fixes = 0
    spec_fixes = 0
    spec_fills = 0
    override_fixes = 0
    find_fixes = 0
    deleted_rows = []
    all_changes = []

    for idx in range(len(df)):
        row = df.iloc[idx].copy()
        fixed_row, changes = fix_row(row)

        if changes:
            pn = norm(fixed_row.get("Part Number", ""))
            nha = norm(fixed_row.get("NHA", ""))
            all_changes.append(
                f"Row {idx+2}: {pn} (NHA: {nha})\n" + "\n".join(changes)
            )
            total_changes += len(changes)

            for c in changes:
                if "Find#" in c and "DELETED" in c:
                    deleted_rows.append(idx)
                elif "Find#" in c:
                    find_fixes += 1
                elif "PN:" in c:
                    pn_fixes += 1
                elif "OVERRIDE" in c:
                    override_fixes += 1
                elif "Designation:" in c:
                    desig_fixes += 1
                elif "MatSpec:" in c:
                    spec_fixes += 1
                elif "Std part" in c or "spec fill" in c:
                    spec_fills += 1

            # Apply fixes back to DataFrame
            for col in fixed_row.index:
                df.at[idx, col] = fixed_row[col]

    # Remove deleted rows (find 9 = DELETED on drawing)
    if deleted_rows:
        print(f"  Removing {len(deleted_rows)} DELETED rows (find numbers marked deleted on drawing)")
        df = df.drop(deleted_rows).reset_index(drop=True)

    # Print all changes
    print("-" * 80)
    print("  ALL CORRECTIONS APPLIED")
    print("-" * 80)
    for change in all_changes:
        print(change)
        print()

    # Summary
    print("=" * 80)
    print("  CORRECTION SUMMARY")
    print("=" * 80)
    print(f"  Total rows processed:       {len(df)}")
    print(f"  Total corrections applied:  {total_changes}")
    print(f"  Part number fixes:          {pn_fixes}")
    print(f"  Designation cleanups:       {desig_fixes}")
    print(f"  MatSpec garbage rejected:   {spec_fixes}")
    print(f"  Standard part fills:        {spec_fills}")
    print(f"  Known override fixes:       {override_fixes}")
    print()

    # Save corrected file
    df.to_excel(OUTPUT_PATH, index=False)
    print(f"Saved corrected MIUL to: {OUTPUT_PATH}")
    print("=" * 80)


if __name__ == "__main__":
    main()
