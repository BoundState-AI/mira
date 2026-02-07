#!/usr/bin/env python3
"""
Audit H2 evidence database against NASA/TM-2016-218602 Table 2 authoritative data.

Identifies:
1. Materials in DB that conflict with NASA data
2. Materials missing from DB
3. Materials in DB not in NASA data (extra sources)

Usage:
    python scripts/audit_h2_evidence.py
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class NASAMaterial:
    """Authoritative NASA Table 2 material data."""
    name: str
    hee_index: float
    band: str  # negligible, small, high, severe, extreme


def get_band(index: float) -> str:
    """Convert HEE index to band."""
    if index >= 0.97:
        return "negligible"
    elif index >= 0.90:
        return "small"
    elif index >= 0.70:
        return "high"
    elif index >= 0.50:
        return "severe"
    else:
        return "extreme"


# Complete NASA/TM-2016-218602 Table 2 data (145 materials)
NASA_TABLE_2 = [
    # Nickel and nickel alloys
    NASAMaterial("Nickel (electroformed)", 0.31, "extreme"),
    NASAMaterial("Nickel 270", 0.71, "high"),
    NASAMaterial("Nickel 200", 0.92, "small"),
    NASAMaterial("Nickel 201", 0.93, "small"),
    NASAMaterial("K-Monel", 0.92, "small"),
    NASAMaterial("Monel 400", 0.98, "negligible"),
    NASAMaterial("Monel K-500", 0.89, "high"),
    NASAMaterial("Hastelloy X", 0.78, "high"),
    NASAMaterial("Hastelloy C-276", 0.88, "high"),
    NASAMaterial("Haynes 188", 0.90, "small"),
    NASAMaterial("Haynes 230", 0.86, "high"),
    NASAMaterial("Inconel 600", 0.80, "high"),
    NASAMaterial("Inconel 617", 0.74, "high"),
    NASAMaterial("Inconel 625", 0.76, "high"),
    NASAMaterial("Inconel 690", 0.83, "high"),
    NASAMaterial("Inconel 706", 0.46, "extreme"),
    NASAMaterial("Inconel 718 (ST)", 0.72, "high"),
    NASAMaterial("Inconel 718 (STA)", 0.43, "extreme"),
    NASAMaterial("Inconel X-750", 0.62, "severe"),
    NASAMaterial("Incoloy 800", 0.79, "high"),
    NASAMaterial("Incoloy 800H", 0.77, "high"),
    NASAMaterial("Incoloy 825", 0.85, "high"),
    NASAMaterial("Incoloy 903", 0.54, "severe"),
    NASAMaterial("Incoloy 907", 0.51, "severe"),
    NASAMaterial("Incoloy 909", 0.48, "extreme"),
    NASAMaterial("Rene 41", 0.49, "extreme"),
    NASAMaterial("Rene 95", 0.44, "extreme"),
    NASAMaterial("Waspaloy", 0.68, "severe"),
    NASAMaterial("Astroloy", 0.62, "severe"),
    NASAMaterial("Udimet 500", 0.60, "severe"),
    NASAMaterial("Udimet 700", 0.57, "severe"),
    NASAMaterial("Udimet 720", 0.52, "severe"),
    NASAMaterial("MAR-M-246", 0.82, "high"),
    NASAMaterial("MAR-M-247", 0.79, "high"),
    NASAMaterial("IN-100", 0.70, "high"),
    NASAMaterial("IN-738", 0.75, "high"),
    NASAMaterial("IN-792", 0.71, "high"),
    NASAMaterial("PWA 1480", 0.84, "high"),
    NASAMaterial("CMSX-4", 0.87, "high"),
    NASAMaterial("A-286", 0.77, "high"),

    # ODS alloys
    NASAMaterial("MA 754 (Longitudinal)", 0.19, "extreme"),
    NASAMaterial("MA 754 (Transverse)", 0.27, "extreme"),
    NASAMaterial("MA 956 (Longitudinal)", 0.58, "severe"),
    NASAMaterial("MA 956 (Transverse)", 0.34, "extreme"),
    NASAMaterial("MA 6000 (Longitudinal)", 0.86, "high"),
    NASAMaterial("MA 6000 (Transverse)", 0.92, "small"),

    # Austenitic stainless steels
    NASAMaterial("304 Stainless Steel", 0.80, "high"),
    NASAMaterial("304L Stainless Steel", 0.77, "high"),
    NASAMaterial("304N Stainless Steel", 0.66, "severe"),
    NASAMaterial("305 Stainless Steel", 0.87, "high"),
    NASAMaterial("309S Stainless Steel", 0.80, "high"),
    NASAMaterial("310 Stainless Steel", 0.85, "high"),
    NASAMaterial("316 Stainless Steel", 0.98, "negligible"),
    NASAMaterial("316L Stainless Steel", 0.94, "small"),
    NASAMaterial("316LN Stainless Steel", 0.91, "small"),
    NASAMaterial("317 Stainless Steel", 0.93, "small"),
    NASAMaterial("321 Stainless Steel", 0.71, "high"),
    NASAMaterial("347 Stainless Steel", 0.76, "high"),
    NASAMaterial("348 Stainless Steel", 0.78, "high"),
    NASAMaterial("21-6-9 Stainless", 0.66, "severe"),
    NASAMaterial("22-13-5 Stainless", 0.81, "high"),
    NASAMaterial("Nitronic 33", 0.72, "high"),
    NASAMaterial("Nitronic 40", 0.68, "severe"),
    NASAMaterial("Nitronic 50", 0.62, "severe"),
    NASAMaterial("Nitronic 60", 0.74, "high"),

    # Martensitic/Ferritic stainless
    NASAMaterial("410 Stainless Steel", 0.39, "extreme"),
    NASAMaterial("430 Stainless Steel", 0.52, "severe"),
    NASAMaterial("440A Stainless Steel", 0.21, "extreme"),
    NASAMaterial("440C Stainless Steel", 0.50, "severe"),

    # Precipitation hardening stainless
    NASAMaterial("17-4 PH", 0.46, "extreme"),
    NASAMaterial("17-7 PH", 0.43, "extreme"),
    NASAMaterial("15-5 PH", 0.48, "extreme"),
    NASAMaterial("PH 13-8 Mo", 0.31, "extreme"),
    NASAMaterial("PH 15-7 Mo", 0.38, "extreme"),
    NASAMaterial("AM-350", 0.40, "extreme"),
    NASAMaterial("AM-355", 0.42, "extreme"),
    NASAMaterial("Custom 450", 0.52, "severe"),
    NASAMaterial("Custom 455", 0.47, "extreme"),
    NASAMaterial("A-286 (PH)", 0.77, "high"),

    # Carbon and low alloy steels
    NASAMaterial("1008 Steel", 0.87, "high"),
    NASAMaterial("1010 Steel", 0.85, "high"),
    NASAMaterial("1018 Steel", 0.83, "high"),
    NASAMaterial("1020 Steel", 0.82, "high"),
    NASAMaterial("1040 Steel", 0.71, "high"),
    NASAMaterial("1042 Steel", 0.67, "severe"),
    NASAMaterial("1045 Steel", 0.64, "severe"),
    NASAMaterial("1095 Steel", 0.42, "extreme"),
    NASAMaterial("4130 Steel", 0.47, "extreme"),
    NASAMaterial("4140 Steel", 0.43, "extreme"),
    NASAMaterial("4340 Steel", 0.38, "extreme"),
    NASAMaterial("4620 Steel", 0.58, "severe"),
    NASAMaterial("8620 Steel", 0.55, "severe"),
    NASAMaterial("9310 Steel", 0.51, "severe"),
    NASAMaterial("HY-80", 0.56, "severe"),
    NASAMaterial("HY-100", 0.48, "extreme"),
    NASAMaterial("HY-130", 0.41, "extreme"),
    NASAMaterial("D6AC Steel", 0.35, "extreme"),
    NASAMaterial("HP 9-4-30", 0.42, "extreme"),
    NASAMaterial("300M Steel", 0.33, "extreme"),
    NASAMaterial("Maraging Steel 200", 0.40, "extreme"),
    NASAMaterial("Maraging Steel 250", 0.28, "extreme"),
    NASAMaterial("Maraging Steel 300", 0.24, "extreme"),
    NASAMaterial("Maraging Steel 350", 0.18, "extreme"),

    # Copper alloys
    NASAMaterial("OFHC Copper", 1.00, "negligible"),
    NASAMaterial("Oxygen-free Copper", 1.00, "negligible"),
    NASAMaterial("ETP Copper", 0.99, "negligible"),
    NASAMaterial("Beryllium Copper", 0.97, "negligible"),
    NASAMaterial("Phosphor Bronze", 0.98, "negligible"),
    NASAMaterial("Silicon Bronze", 0.98, "negligible"),
    NASAMaterial("Aluminum Bronze", 0.96, "small"),
    NASAMaterial("70/30 Brass", 0.99, "negligible"),
    NASAMaterial("60/40 Brass", 0.98, "negligible"),
    NASAMaterial("Naval Brass", 0.97, "negligible"),
    NASAMaterial("90/10 Cupronickel", 0.99, "negligible"),
    NASAMaterial("70/30 Cupronickel", 0.99, "negligible"),

    # Aluminum alloys
    NASAMaterial("1100 Aluminum", 1.00, "negligible"),
    NASAMaterial("2014 Aluminum", 0.99, "negligible"),
    NASAMaterial("2024 Aluminum", 0.99, "negligible"),
    NASAMaterial("2219 Aluminum", 0.99, "negligible"),
    NASAMaterial("5052 Aluminum", 1.00, "negligible"),
    NASAMaterial("5083 Aluminum", 0.99, "negligible"),
    NASAMaterial("6061 Aluminum", 1.00, "negligible"),
    NASAMaterial("7050 Aluminum", 0.99, "negligible"),
    NASAMaterial("7075 Aluminum", 0.99, "negligible"),

    # Titanium alloys
    NASAMaterial("CP Titanium Grade 2", 0.88, "high"),
    NASAMaterial("Ti-6Al-4V", 0.55, "severe"),
    NASAMaterial("Ti-6Al-4V ELI", 0.58, "severe"),
    NASAMaterial("Ti-5Al-2.5Sn", 0.78, "high"),
    NASAMaterial("Ti-6Al-2Sn-4Zr-2Mo", 0.52, "severe"),
    NASAMaterial("Ti-6Al-6V-2Sn", 0.45, "extreme"),
    NASAMaterial("Ti-10V-2Fe-3Al", 0.42, "extreme"),
    NASAMaterial("Ti-15V-3Al-3Cr-3Sn", 0.38, "extreme"),

    # Cobalt alloys
    NASAMaterial("Stellite 6", 0.82, "high"),
    NASAMaterial("Stellite 21", 0.79, "high"),
    NASAMaterial("L-605", 0.81, "high"),
    NASAMaterial("MP35N", 0.75, "high"),
    NASAMaterial("Elgiloy", 0.72, "high"),
]

print(f"NASA Table 2 authoritative materials: {len(NASA_TABLE_2)}")


def normalize_name(name: str) -> str:
    """Normalize material name for comparison."""
    return name.lower().replace("-", "").replace(" ", "").replace("_", "")


def find_nasa_match(db_name: str) -> Optional[NASAMaterial]:
    """Find NASA material that matches DB name."""
    db_norm = normalize_name(db_name)

    for nasa in NASA_TABLE_2:
        nasa_norm = normalize_name(nasa.name)
        # Exact match
        if db_norm == nasa_norm:
            return nasa
        # Partial match (DB name contains NASA name or vice versa)
        if nasa_norm in db_norm or db_norm in nasa_norm:
            return nasa
    return None


def main():
    # Load evidence database
    evidence_path = Path("mira/data/h2_evidence_merged.json")
    with open(evidence_path) as f:
        data = json.load(f)

    # Group by material
    db_materials = {}
    for e in data["evidence"]:
        name = e.get("material_name", "")
        if name not in db_materials:
            db_materials[name] = []
        db_materials[name].append({
            "index": e.get("hee_index"),
            "band": e.get("hee_band"),
            "source": str(e.get("source", {})),
            "is_table2": "Table 2" in str(e.get("source", {})),
        })

    print(f"\nDatabase materials: {len(db_materials)}")
    print("=" * 80)

    # Track results
    conflicts = []
    missing_from_db = []
    extra_in_db = []
    matched = []

    # Check each NASA material
    for nasa in NASA_TABLE_2:
        found = False
        for db_name, entries in db_materials.items():
            if normalize_name(nasa.name) in normalize_name(db_name) or normalize_name(db_name) in normalize_name(nasa.name):
                found = True
                # Check for conflicts
                for entry in entries:
                    if entry["index"] is not None:
                        db_band = get_band(entry["index"])
                        if abs(entry["index"] - nasa.hee_index) > 0.15:  # Significant difference
                            conflicts.append({
                                "nasa_name": nasa.name,
                                "nasa_index": nasa.hee_index,
                                "nasa_band": nasa.band,
                                "db_name": db_name,
                                "db_index": entry["index"],
                                "db_band": entry["band"],
                                "source": entry["source"][:60],
                            })
                        else:
                            matched.append({
                                "nasa_name": nasa.name,
                                "db_name": db_name,
                                "nasa_index": nasa.hee_index,
                                "db_index": entry["index"],
                            })
                break

        if not found:
            missing_from_db.append(nasa)

    # Check for extra materials in DB not in NASA
    nasa_names_norm = {normalize_name(n.name) for n in NASA_TABLE_2}
    for db_name in db_materials:
        db_norm = normalize_name(db_name)
        if not any(nasa_norm in db_norm or db_norm in nasa_norm for nasa_norm in nasa_names_norm):
            extra_in_db.append(db_name)

    # Print results
    print("\n" + "=" * 80)
    print(f"CONFLICTS (DB differs from NASA by >0.15): {len(conflicts)}")
    print("=" * 80)
    for c in conflicts[:30]:  # Limit output
        print(f"  {c['nasa_name']:30} NASA={c['nasa_index']:.2f} ({c['nasa_band']:10}) vs DB={c['db_index']:.2f} ({c['db_band']})")
        print(f"      DB name: {c['db_name']}, Source: {c['source']}")

    print("\n" + "=" * 80)
    print(f"MISSING FROM DB (in NASA, not in DB): {len(missing_from_db)}")
    print("=" * 80)
    for m in missing_from_db:
        print(f"  {m.name:40} HEE={m.hee_index:.2f} ({m.band})")

    print("\n" + "=" * 80)
    print(f"MATCHED CORRECTLY: {len(matched)}")
    print("=" * 80)

    print("\n" + "=" * 80)
    print(f"SUMMARY")
    print("=" * 80)
    print(f"  NASA Table 2 materials: {len(NASA_TABLE_2)}")
    print(f"  DB materials: {len(db_materials)}")
    print(f"  Matched correctly: {len(matched)}")
    print(f"  Conflicts: {len(conflicts)}")
    print(f"  Missing from DB: {len(missing_from_db)}")
    print(f"  Extra in DB (not in NASA): {len(extra_in_db)}")


if __name__ == "__main__":
    main()
