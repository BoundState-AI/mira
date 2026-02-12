#!/usr/bin/env python3
"""
Diagnostic: Compare MIUL pair_builder NHA/Parent output vs ground truth DT JSON.

Traces through the exact same logic as pair_builder.py to show what NHA
and Parent values each row gets, then compares against the corrected DT JSON.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ground truth
GT_PATH = Path(r"C:\Users\jwilde2\Desktop\DMLLV\MER07540-001_corrected.json")
# Latest extraction session
SESSION_PATH = Path(r"C:\BoundState\temp\miul_sessions\f78c9dd4-4af0-4d29-b0cf-795fe0101adc")


def _norm(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+\d+\.$", "", text)
    return text


def _source_drawing_from_file(source_file: str) -> str:
    if not source_file:
        return ""
    stem = Path(source_file).stem
    for sep in (".DRW", "_DRW", "_drw", "_Drw"):
        if sep in stem:
            return stem.split(sep)[0].upper()
    return (stem.split("_")[0] if "_" in stem else stem).upper()


def _is_noise_material(part_number: str, description: str) -> bool:
    pn = _norm(part_number)
    desc = str(description or "").upper()
    if not pn:
        return True
    if re.fullmatch(r"\d+\.?", pn):
        return True
    if pn.startswith("NOTE") or re.fullmatch(r"NOTE-?\d+", pn):
        return True
    if "REFERENCE ONLY" in desc:
        return True
    return False


def load_ground_truth() -> Dict[str, str]:
    """Load ground truth parent map: drawing_number -> parent drawing_number."""
    with open(GT_PATH, "r") as f:
        gt = json.load(f)
    parent_map = {}
    for node in gt["tree"]:
        dn = _norm(node["drawing_number"])
        parent = _norm(node.get("parent") or "")
        parent_map[dn] = parent
    return parent_map


def load_extraction() -> Dict[str, Any]:
    """Load extraction JSON."""
    extraction_path = SESSION_PATH / "extraction.json"
    with open(extraction_path, "r") as f:
        return json.load(f)


def load_review() -> Dict[str, Any]:
    """Load review JSON."""
    review_path = SESSION_PATH / "review.json"
    with open(review_path, "r") as f:
        return json.load(f)


def simulate_pair_rows(extraction: Dict, review: Dict, dt_json: Dict) -> List[Dict]:
    """Simulate build_pair_rows_from_v4_extraction exactly."""
    dt_nodes = dt_json.get("tree", [])
    dt_lookup = {_norm(node.get("drawing_number", "")) for node in dt_nodes if node.get("drawing_number")}

    grouped: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for material in extraction.get("materials", []):
        pn = _norm(material.get("part_number", ""))
        desc = str(material.get("part_description", "") or "")
        if _is_noise_material(pn, desc):
            continue

        source_file = str(material.get("source_file", "") or "")
        source_drawing = _source_drawing_from_file(source_file)
        if not source_drawing and pn in dt_lookup:
            source_drawing = pn
        if not source_drawing:
            source_drawing = _norm(material.get("nha", ""))

        grouped[(pn, source_drawing)].append(material)

    pair_rows = []
    for (pn, source_drawing), sightings in grouped.items():
        pair_rows.append({
            "part_number": pn,
            "source_drawing": source_drawing,
            "part_description": sightings[0].get("part_description", ""),
            "sighting_count": len(sightings),
        })
    return pair_rows


def simulate_miul_build(pair_rows: List[Dict], dt_json: Dict) -> List[Dict]:
    """Simulate build_miul_from_pair_rows NHA/Parent logic exactly."""
    tree = dt_json.get("tree", [])
    tree_order = {_norm(node.get("drawing_number", "")): i for i, node in enumerate(tree)}
    dt_parent = {
        _norm(node.get("drawing_number", "")): _norm(node.get("parent") or "")
        for node in tree
    }

    miul_number = "MER07540"

    # Sort
    sortable = []
    for row in pair_rows:
        pn = _norm(row["part_number"])
        source = _norm(row["source_drawing"])
        sortable.append((
            tree_order.get(source, 9999),
            0 if source != pn else 1,
            tree_order.get(pn, 9999),
            pn, source, row,
        ))
    sortable.sort()

    # Build rows
    pn_to_first_index: Dict[str, int] = {miul_number: 2}
    next_index = 3
    rows = []
    for _, _, _, _, _, row in sortable:
        pn = _norm(row["part_number"])
        source = _norm(row["source_drawing"])

        if pn in dt_parent and source == pn:
            nha = dt_parent.get(pn) or miul_number
        else:
            nha = source or dt_parent.get(pn) or miul_number

        rows.append({
            "index": next_index,
            "part_number": pn,
            "source_drawing": source,
            "nha": nha,
            "description": row.get("part_description", "")[:40],
        })
        if pn not in pn_to_first_index:
            pn_to_first_index[pn] = next_index
        next_index += 1

    # Resolve Parent indices
    for row in rows:
        nha = _norm(row["nha"])
        row["parent_index"] = pn_to_first_index.get(nha, 2)
        row["parent_pn"] = nha

    return rows


def main():
    print("=" * 100)
    print("MIUL NHA/Parent Diagnostic")
    print("=" * 100)

    gt_parent = load_ground_truth()
    extraction = load_extraction()
    dt_json = extraction.get("dt_context") or {}

    print(f"\nGround truth nodes: {len(gt_parent)}")
    print(f"DT context in extraction: {len(dt_json.get('tree', []))} nodes")

    # Check if DT context matches ground truth
    dt_nodes = {_norm(n.get("drawing_number", "")): _norm(n.get("parent") or "")
                for n in dt_json.get("tree", [])}

    print("\n--- DT Context vs Ground Truth ---")
    all_dt_keys = set(gt_parent.keys()) | set(dt_nodes.keys())
    mismatches = []
    for dn in sorted(all_dt_keys):
        gt_p = gt_parent.get(dn, "(NOT IN GT)")
        dt_p = dt_nodes.get(dn, "(NOT IN DT)")
        if gt_p != dt_p:
            mismatches.append((dn, gt_p, dt_p))
            print(f"  MISMATCH: {dn}: GT parent={gt_p}, DT parent={dt_p}")
    if not mismatches:
        print("  All DT parent relationships match ground truth!")

    # Load review
    review = load_review()

    # Simulate pair rows
    pair_rows = simulate_pair_rows(extraction, review, dt_json)
    print(f"\nPair rows: {len(pair_rows)}")

    # Show unique part numbers and their source drawings
    print("\n--- Pair Row Source Drawings ---")
    by_pn: Dict[str, List[str]] = defaultdict(list)
    for pr in pair_rows:
        by_pn[pr["part_number"]].append(pr["source_drawing"])

    # Only show DT nodes (parts that should have tree relationships)
    dt_parts = set(gt_parent.keys())
    for pn in sorted(dt_parts):
        sources = by_pn.get(pn, [])
        gt_p = gt_parent.get(pn, "?")
        marker = ""
        if sources:
            for s in sources:
                if s != pn and s != gt_p:
                    # Source drawing != self and != expected parent
                    marker = " *** SOURCE != GT PARENT ***"
        print(f"  {pn}: sources={sources}, gt_parent={gt_p}{marker}")

    # Simulate MIUL build
    rows = simulate_miul_build(pair_rows, dt_json)

    # Compare NHA vs ground truth
    print("\n--- MIUL NHA vs Ground Truth Parent ---")
    print(f"{'Part Number':<20} {'Source Drawing':<20} {'MIUL NHA':<20} {'GT Parent':<20} {'Match?':<8}")
    print("-" * 100)

    errors = []
    seen_pn = set()
    for row in rows:
        pn = row["part_number"]
        if pn not in gt_parent:
            continue  # Not a DT node, skip (purchased parts, etc.)

        gt_p = gt_parent.get(pn, "")
        nha = row["nha"]
        match = "OK" if nha == gt_p else "WRONG"

        # Only report first occurrence of each PN (to reduce noise)
        is_first = pn not in seen_pn
        seen_pn.add(pn)

        if match == "WRONG" or is_first:
            print(f"  {pn:<20} {row['source_drawing']:<20} {nha:<20} {gt_p:<20} {match:<8}")

        if match == "WRONG":
            errors.append({
                "part_number": pn,
                "source_drawing": row["source_drawing"],
                "miul_nha": nha,
                "gt_parent": gt_p,
                "description": row["description"],
            })

    print(f"\n{'=' * 100}")
    print(f"SUMMARY: {len(errors)} NHA mismatches out of {len([r for r in rows if r['part_number'] in gt_parent])} DT rows")

    if errors:
        print("\nDETAILED ERRORS:")
        for e in errors:
            print(f"  {e['part_number']} ({e['description']})")
            print(f"    Source drawing: {e['source_drawing']}")
            print(f"    MIUL NHA:      {e['miul_nha']}")
            print(f"    GT Parent:     {e['gt_parent']}")
            print()

    # Also check: are there DT nodes missing from the MIUL entirely?
    miul_pns = {row["part_number"] for row in rows}
    missing_from_miul = dt_parts - miul_pns
    if missing_from_miul:
        print(f"\nDT nodes MISSING from MIUL ({len(missing_from_miul)}):")
        for pn in sorted(missing_from_miul):
            print(f"  {pn} (gt_parent={gt_parent.get(pn, '?')})")


if __name__ == "__main__":
    main()
