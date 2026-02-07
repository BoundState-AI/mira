#!/usr/bin/env python3
"""
Analyze H2 Evidence Database

Lists all materials, their HEE bands, and helps identify test case issues.

Usage: python scripts/analyze_h2_evidence.py
"""
import json
from pathlib import Path
from collections import defaultdict

def main():
    evidence_path = Path(r"C:\BoundState\mira\data\h2_evidence_merged.json")

    if not evidence_path.exists():
        print(f"ERROR: {evidence_path} not found")
        return

    with open(evidence_path) as f:
        data = json.load(f)

    evidence = data.get('evidence', [])
    print(f"Total evidence records: {len(evidence)}")
    print(f"Sources: {data.get('sources', [])}")
    print()

    # Organize by material
    materials = defaultdict(list)
    for ev in evidence:
        name = ev.get('material_name', 'unknown')
        materials[name].append(ev)

    print(f"Unique materials: {len(materials)}")
    print()
    print("=" * 80)
    print("MATERIALS AND HEE BANDS")
    print("=" * 80)

    for name in sorted(materials.keys()):
        records = materials[name]
        bands = [r.get('hee_band', 'unknown') for r in records]
        indices = [r.get('hee_index') for r in records if r.get('hee_index')]
        conditions = set(r.get('heat_treatment', {}).get('condition', 'unknown') for r in records)

        print(f"\n{name}:")
        print(f"  Records: {len(records)}")
        print(f"  HEE Bands: {set(bands)}")
        if indices:
            print(f"  HEE Indices: {min(indices):.2f} - {max(indices):.2f}")
        print(f"  Conditions: {conditions}")

    # Summary by band
    print()
    print("=" * 80)
    print("SUMMARY BY HEE BAND")
    print("=" * 80)

    by_band = defaultdict(list)
    for name, records in materials.items():
        for r in records:
            band = r.get('hee_band', 'unknown')
            by_band[band].append(name)

    for band in ['negligible', 'small', 'high', 'severe', 'extreme', 'unknown']:
        if band in by_band:
            names = sorted(set(by_band[band]))
            print(f"\n{band.upper()} ({len(names)} materials):")
            for n in names[:10]:
                print(f"  - {n}")
            if len(names) > 10:
                print(f"  ... and {len(names) - 10} more")


if __name__ == "__main__":
    main()
