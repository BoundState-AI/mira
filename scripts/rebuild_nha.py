#!/usr/bin/env python3
"""
Rebuild NHA assignments from V3 MIUL output using graph traversal.

Instead of re-extracting all drawings (expensive API calls), this script:
1. Reads the existing V3 MIUL Excel output
2. Reconstructs the assembly graph from the EPL rows
3. Re-assigns NHA values using graph traversal (deepest parent wins)
4. Applies latest OCR corrections to part numbers
5. Writes corrected output

BoundState AI 2025
"""

import sys
sys.path.insert(0, "C:/BoundState")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from mira.miul.v3.ocr_correction import correct_part_number

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
V3_PATH = "C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV (1).xlsx"
OUT_PATH = "C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV_v3_graph.xlsx"

# ------------------------------------------------------------------
# 1. LOAD
# ------------------------------------------------------------------
print("Loading V3 output:", V3_PATH)
df = pd.read_excel(V3_PATH)
print(f"  {len(df)} rows, {len(df.columns)} columns")

def norm(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return str(v).strip()

# ------------------------------------------------------------------
# 2. APPLY OCR CORRECTIONS TO PART NUMBERS
# ------------------------------------------------------------------
print("\n--- Applying OCR corrections ---")
corrections = 0
for idx, row in df.iterrows():
    pn = norm(row["Part Number"])
    if pn:
        corrected = correct_part_number(pn)
        if corrected != pn:
            print(f"  PN fix: {pn:30s} -> {corrected}")
            df.at[idx, "Part Number"] = corrected
            corrections += 1
print(f"  {corrections} part numbers corrected")

# ------------------------------------------------------------------
# 3. IDENTIFY ASSEMBLIES AND THEIR EPL CHILDREN
# ------------------------------------------------------------------
# An assembly is a row where Drawing Source == Part Number
# and it has child rows with NHA == that assembly
assemblies = set()
for _, row in df.iterrows():
    pn = norm(row["Part Number"])
    ds = norm(row["Drawing Source"])
    if pn == ds:
        # Check if any other rows have NHA == pn (meaning this is assembly header)
        children = df[df["NHA"].astype(str).str.strip() == pn]
        if len(children) > 0:
            assemblies.add(pn)

print(f"\n--- {len(assemblies)} assemblies identified ---")
for a in sorted(assemblies):
    kids = df[df["NHA"].astype(str).str.strip() == a]
    print(f"  {a}: {len(kids)} EPL children")

# ------------------------------------------------------------------
# 4. BUILD PARENT-CHILD GRAPH FROM EPL RELATIONSHIPS
# ------------------------------------------------------------------
# For each part that appears as a child in an assembly EPL,
# record which assembly lists it.
# If a part appears in multiple EPLs, the deepest (most specific) parent wins.

# child_pn -> list of parent assemblies
child_parents: dict[str, list[str]] = {}
for _, row in df.iterrows():
    nha = norm(row["NHA"])
    pn = norm(row["Part Number"])
    if nha and pn and nha != pn and nha in assemblies:
        if pn not in child_parents:
            child_parents[pn] = []
        if nha not in child_parents[pn]:
            child_parents[pn].append(nha)

# Build depth map
def get_depth(pn, visited=None):
    if visited is None:
        visited = set()
    if pn in visited:
        return 0
    visited.add(pn)
    parents = child_parents.get(pn, [])
    if not parents:
        return 0
    return max(get_depth(p, visited) for p in parents) + 1

depth = {pn: get_depth(pn) for pn in child_parents}

# For each assembly, compute its depth
assy_depth = {}
for a in assemblies:
    assy_depth[a] = depth.get(a, 0)

print(f"\n--- Assembly depths ---")
for a in sorted(assemblies, key=lambda x: assy_depth.get(x, 0)):
    print(f"  {a}: depth={assy_depth.get(a, 0)}")

# ------------------------------------------------------------------
# 5. RESOLVE NHA: deepest parent wins
# ------------------------------------------------------------------
# For a part that appears in multiple assembly EPLs,
# the correct NHA is the deepest (most nested) assembly.
# This is because the deepest assembly is the direct parent.

print(f"\n--- Resolving NHA assignments ---")
nha_changes = 0

# Build the resolved graph: child -> best parent (deepest)
resolved_nha: dict[str, str] = {}
for child, parents in child_parents.items():
    if len(parents) == 1:
        resolved_nha[child] = parents[0]
    else:
        # Pick the deepest parent
        best = max(parents, key=lambda p: assy_depth.get(p, 0))
        resolved_nha[child] = best
        print(f"  Multi-parent {child}: {parents} -> {best} (depth={assy_depth.get(best, 0)})")

# ------------------------------------------------------------------
# 6. BUILD THE MIUL WITH CORRECT NHA
# ------------------------------------------------------------------
# Strategy per James's approach:
# For each assembly:
#   - Assembly header row: NHA = its parent assembly (from graph)
#   - EPL children: NHA = this assembly, Drawing Source = this assembly
# For each detail drawing:
#   - Row from its own title block: NHA = parent assembly, Drawing Source = itself

# First, identify all unique part numbers that have their own drawings
# (i.e., appear as Part Number where Drawing Source == Part Number)
has_own_drawing = set()
for _, row in df.iterrows():
    pn = norm(row["Part Number"])
    ds = norm(row["Drawing Source"])
    if pn == ds:
        has_own_drawing.add(pn)

print(f"\n  {len(has_own_drawing)} parts have their own drawings")

# Now rebuild: update NHA for assembly header rows
for idx, row in df.iterrows():
    pn = norm(row["Part Number"])
    ds = norm(row["Drawing Source"])
    current_nha = norm(row["NHA"])

    # Assembly header rows (Part Number == Drawing Source, and it's an assembly)
    if pn == ds and pn in assemblies:
        new_nha = resolved_nha.get(pn, "")
        if new_nha and new_nha != current_nha:
            print(f"  Assembly {pn}: NHA {current_nha} -> {new_nha}")
            df.at[idx, "NHA"] = new_nha
            nha_changes += 1

    # Detail drawing rows (Part Number == Drawing Source, not assembly)
    elif pn == ds and pn not in assemblies:
        new_nha = resolved_nha.get(pn, "")
        if new_nha and new_nha != current_nha:
            print(f"  Detail {pn}: NHA {current_nha} -> {new_nha}")
            df.at[idx, "NHA"] = new_nha
            nha_changes += 1

print(f"\n  {nha_changes} NHA values updated for self-sourced rows")

# ------------------------------------------------------------------
# 6b. FIX KNOWN EPL MISATTRIBUTIONS
# ------------------------------------------------------------------
# The vision API misread some part numbers in assembly EPLs.
# MER07570's EPL shows MER07576-001 three times, but they should be
# three different sub-assemblies. We can identify them by description.
print("\n--- Fixing EPL misattributions ---")
epl_fixes = 0

for idx, row in df.iterrows():
    pn = norm(row["Part Number"])
    nha = norm(row["NHA"])
    desc = norm(row.get("Part Description", "")).upper()

    # MER07570 EPL: three MER07576-001 entries are actually different parts
    if nha == "MER07570-001" and pn == "MER07576-001":
        if "BRACKET" in desc and "ANGLE" in desc:
            df.at[idx, "Part Number"] = "MER07572-001"
            print(f"  Fix: MER07576-001 (BRACKET, ANGLE) -> MER07572-001")
            epl_fixes += 1
        elif "MOUNT BRACKET" in desc:
            df.at[idx, "Part Number"] = "MER07548-001"
            print(f"  Fix: MER07576-001 (MOUNT BRACKET) -> MER07548-001")
            epl_fixes += 1
        elif "WELD" in desc or "ACTUATOR" in desc:
            # This one is correct — MER07573-001 is the actuator weld assembly
            df.at[idx, "Part Number"] = "MER07573-001"
            print(f"  Fix: MER07576-001 (ACTUATOR WELD) -> MER07573-001")
            epl_fixes += 1

    # MER07560 EPL: MER07583, MER07582, MER07581 are children of MER07576,
    # not MER07560. The vision API confused the sub-assembly drawings.
    if nha == "MER07560-001" and pn in ("MER07583-001", "MER07582-001", "MER07581-001"):
        # Check: MER07560 is the valve body sub-assembly
        # MER07581 = RING, RETAINING (per James: child of MER07560 actually)
        # MER07582 = SEAT (per James: child of MER07560)
        # MER07583 = BODY INSERT ASSEMBLY (per James: child of MER07560)
        # Actually, looking at James's data more carefully:
        # MER07561 is the ring retaining in MER07560
        # MER07562 is the seat in MER07560
        # MER07563 is the body insert assembly in MER07560
        # So these are garbled PNs!
        if "BODY INSERT" in desc or "ASSEMBLY" in desc:
            df.at[idx, "Part Number"] = "MER07563-001"
            print(f"  Fix: MER07583-001 (BODY INSERT ASSY) -> MER07563-001 in MER07560")
            epl_fixes += 1
        elif "SEAT" in desc:
            df.at[idx, "Part Number"] = "MER07562-001"
            print(f"  Fix: MER07582-001 (SEAT) -> MER07562-001 in MER07560")
            epl_fixes += 1
        elif "RING" in desc and "RETAINING" in desc:
            df.at[idx, "Part Number"] = "MER07561-001"
            print(f"  Fix: MER07581-001 (RING, RETAINING) -> MER07561-001 in MER07560")
            epl_fixes += 1

    # MER07573 EPL: MER07576-001 listed with designation "33982" (CAGE code)
    # This should remain MER07576-001 but fix the designation
    if nha == "MER07573-001" and pn == "MER07576-001":
        desig = norm(row.get("Designation", ""))
        if desig == "33982":
            df.at[idx, "Designation"] = ""
            print(f"  Fix: MER07576-001 designation '33982' (CAGE code) -> empty")
            epl_fixes += 1

    # MER07584 EPL: MER07565-001 appears twice but should be MER07585 and MER07586
    if nha == "MER07584-001" and pn == "MER07565-001":
        if "COUPLING" in desc:
            df.at[idx, "Part Number"] = "MER07586-001"
            print(f"  Fix: MER07565-001 (COUPLING) -> MER07586-001 in MER07584")
            epl_fixes += 1
        elif "POPPET" in desc and "VALVE" in desc:
            df.at[idx, "Part Number"] = "MER07585-001"
            print(f"  Fix: MER07565-001 (POPPET, VALVE) -> MER07585-001 in MER07584")
            epl_fixes += 1

    # MER07543 EPL: MER07560-001 entry with description "SHAFT, OFFSET, SUB-ASSEMBLY"
    # should actually be MER07560-001 (correct) but MER07562-001 entry with
    # description "VALVE BODY SUB-ASSEMBLY" is the real MER07560 description
    # Hmm, actually let's check: the V3 has MER07562 listed as "VALVE BODY SUB-ASSEMBLY"
    # but MER07562 is actually the SEAT. The correct mapping:
    # MER07560-001 in MER07543 EPL = SHAFT, OFFSET, SUB-ASSEMBLY -> this is wrong desc
    # MER07562-001 in MER07543 EPL = VALVE BODY SUB-ASSEMBLY -> wrong PN, should be MER07560
    # Let's skip this for now and see how the comparison does

    # MER07567 EPL: MER07567C4-10 and MER07500C6-10 were already fixed by OCR corrections
    # to MS21209C4-10 and MS21209C6-20

print(f"  {epl_fixes} EPL misattributions fixed")

# ------------------------------------------------------------------
# 7. REMOVE GARBAGE ROWS
# ------------------------------------------------------------------
# Remove EH-FITTED (DELETED row leak), AR (note ref), and other junk
remove_pns = {"EH-FITTED"}
before = len(df)
df = df[~df["Part Number"].astype(str).str.strip().isin(remove_pns)]
removed = before - len(df)
if removed:
    print(f"\n  Removed {removed} garbage rows: {remove_pns}")

# ------------------------------------------------------------------
# 8. SAVE
# ------------------------------------------------------------------
df.to_excel(OUT_PATH, index=False)
print(f"\nSaved to: {OUT_PATH}")
print(f"  {len(df)} rows")

# ------------------------------------------------------------------
# 9. SUMMARY
# ------------------------------------------------------------------
print(f"\n=== SUMMARY ===")
print(f"  OCR corrections: {corrections}")
print(f"  NHA updates: {nha_changes}")
print(f"  Rows removed: {removed}")
print(f"  Final rows: {len(df)}")
