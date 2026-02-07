#!/usr/bin/env python3
"""Add missing materials from NASA/TM-2016-218602 Table 2 to H2 evidence."""
import json
from pathlib import Path

# Load existing evidence
evidence_path = Path(r'C:\BoundState\mira\data\h2_evidence_merged.json')
with open(evidence_path) as f:
    data = json.load(f)

existing = data.get('evidence', [])
print(f"Existing records: {len(existing)}")

# Get existing material keys (lowercase for matching)
existing_keys = set()
for r in existing:
    key = r.get('material_key', r.get('material_name', '')).lower()
    existing_keys.add(key)

# New materials to add from user's comprehensive list
# Format: (name, category, hee_index, pressure_mpa, notes)
new_materials = [
    # EXTREME HEE (< 0.50)
    ("CM SX-2 (single crystal)", "nickel_superalloy", 0.14, 34.5, "Single crystal Ni superalloy"),
    ("AerMet 100 (peak aged)", "martensitic_steel", 0.15, 68.9, "Ultra-high strength steel"),
    ("Ti-11.5Mo-6Zr-4.5Sn (STA)", "titanium_alloy", 0.18, 34.5, "Beta titanium alloy"),
    ("MA 754 (Longitudinal)", "nickel_ods", 0.19, 34.5, "ODS Ni-based alloy"),
    ("440A Steel", "martensitic_steel", 0.21, 24.1, "Martensitic stainless"),
    ("MAR-M200 (DS)", "nickel_superalloy", 0.23, 34.5, "Directionally solidified"),
    ("MAR-M246 (Hf) (single crystal)", "nickel_superalloy", 0.24, 48.2, "Single crystal with Hf"),
    ("Fe-9Ni-4Co-0.20C", "martensitic_steel", 0.24, 68.9, "High strength steel"),
    ("MA 754 (Transverse)", "nickel_ods", 0.27, 34.5, "ODS Ni-based alloy transverse"),
    ("D6AC Steel (300C tempered)", "martensitic_steel", 0.30, 2.1, "Low pressure test"),
    ("IN 100", "nickel_superalloy", 0.30, 34.5, "Cast Ni superalloy"),
    ("CG-27 (precipitated)", "austenitic_steel", 0.34, 68.9, "Controlled expansion alloy"),
    ("4340 Steel (1652F austen.)", "alloy_steel", 0.35, 34.5, "High austenitizing temp"),
    ("Incoloy 909 (ST + Aged)", "iron_superalloy", 0.36, 34.5, "Low expansion superalloy"),
    ("CM SX-4C (single crystal)", "nickel_superalloy", 0.36, 34.5, "Single crystal"),
    ("CM-SX5", "nickel_superalloy", 0.36, 34.5, "Single crystal"),
    ("CM SX-3 (std)", "nickel_superalloy", 0.38, 34.5, "Single crystal"),
    ("Gamma-TiAl Alloy", "titanium_aluminide", 0.39, 13.8, "Intermetallic"),
    ("Inconel 713LC", "nickel_superalloy", 0.42, 41.3, "Cast Ni superalloy"),
    ("CM SX-4D", "nickel_superalloy", 0.43, 34.5, "Single crystal"),
    ("A372 (grade J)", "ferritic_steel", 0.45, 24.1, "Pressure vessel steel"),
    ("Inconel 700", "nickel_superalloy", 0.45, 68.9, "Ni superalloy"),
    ("Rene N-4 (single crystal)", "nickel_superalloy", 0.46, 34.5, "Single crystal"),
    ("PWA 1480 (single crystal)", "nickel_superalloy", 0.49, 34.5, "Single crystal"),

    # SEVERE HEE (0.50-0.69)
    ("A286 (ST + Aged)", "iron_superalloy", 0.51, 68.9, "Fe-based superalloy aged"),
    ("Inconel 718 (ST 1750F)", "nickel_superalloy", 0.53, 34.5, "Lower ST temperature"),
    ("Alpha-2 TiAl Alloy", "titanium_aluminide", 0.54, 13.8, "Intermetallic"),
    ("RR 2000", "nickel_superalloy", 0.54, 34.5, "Rolls-Royce superalloy"),
    ("Udimet 720", "nickel_superalloy", 0.53, 34.5, "Ni superalloy"),
    ("Incoloy 903 (ST + Aged)", "iron_superalloy", 0.55, 24.0, "Low expansion aged"),
    ("MA 956 (Longitudinal)", "iron_ods", 0.58, 34.5, "Fe-based ODS"),
    ("Incoloy 901", "iron_superalloy", 0.60, 34.5, "Fe-Ni superalloy"),
    ("1080 Steel", "carbon_steel", 0.62, 6.9, "High carbon steel"),
    ("Rene 95 (PM)", "nickel_superalloy", 0.62, 34.5, "Powder metallurgy"),
    ("X100 Pipeline Steel", "ferritic_steel", 0.63, 13.8, "High strength pipeline"),
    ("MP159", "cobalt_superalloy", 0.63, 34.5, "Co-based superalloy"),
    ("Inco 4005 (experimental)", "nickel_superalloy", 0.64, 34.5, "Experimental alloy"),
    ("18-2-12 (Nitronic 32)", "austenitic_steel", 0.64, 68.9, "N-strengthened SS"),
    ("Udimet 700", "nickel_superalloy", 0.65, 51.7, "Ni superalloy"),
    ("MP35N (24 MPa)", "cobalt_superalloy", 0.66, 24.0, "At lower pressure"),
    ("18-18 Plus", "austenitic_steel", 0.67, 68.9, "High Mn austenitic"),
    ("A212-61T (normalized)", "ferritic_steel", 0.68, 68.9, "Pressure vessel steel"),
    ("430F Steel", "ferritic_steel", 0.68, 68.9, "Free-machining ferritic SS"),
    ("Ti-6Al-4V (STA 48 MPa)", "titanium_alloy", 0.69, 48.2, "At 48 MPa pressure"),

    # HIGH HEE (0.70-0.89)
    ("MP35N (34 MPa)", "cobalt_superalloy", 0.70, 34.5, "At 34.5 MPa"),
    ("K-Monel (annealed)", "nickel_alloy", 0.73, 68.9, "Annealed condition"),
    ("A515-Gr. 70", "ferritic_steel", 0.73, 68.9, "Pressure vessel steel"),
    ("MP35N (24 MPa high)", "cobalt_superalloy", 0.73, 24.0, "Different test"),
    ("A372 (class 4)", "ferritic_steel", 0.74, 68.9, "Pressure vessel steel"),
    ("1080 Steel (Transverse)", "carbon_steel", 0.74, 6.9, "Transverse orientation"),
    ("1042 Steel (Normalized)", "carbon_steel", 0.75, 48.2, "Normalized condition"),
    ("JBK-75 (ST + Aged)", "iron_superalloy", 0.75, 172.0, "High pressure test"),
    ("C1025 Steel", "carbon_steel", 0.76, 68.9, "Low carbon steel"),
    ("Haynes 230", "nickel_superalloy", 0.76, 34.5, "Solid solution Ni alloy"),
    ("Haynes 242", "nickel_superalloy", 0.77, 34.5, "Ni-Mo-Cr alloy"),
    ("A106-Gr. B", "ferritic_steel", 0.78, 6.9, "Pipe steel"),
    ("X52 Pipeline Steel", "ferritic_steel", 0.78, 13.8, "Pipeline grade"),
    ("A517-F (T-1)", "alloy_steel", 0.78, 68.9, "Quenched and tempered"),
    ("A302B", "alloy_steel", 0.79, 68.9, "Pressure vessel steel"),
    ("AF-115 (PM)", "nickel_superalloy", 0.80, 34.5, "PM Ni superalloy"),
    ("Inconel 706 (48 MPa)", "nickel_superalloy", 0.82, 48.2, "At 48 MPa"),
    ("A516", "ferritic_steel", 0.83, 6.9, "Pressure vessel steel"),
    ("AF-56 (single crystal)", "nickel_superalloy", 0.84, 34.5, "Single crystal"),
    ("Tenelon", "austenitic_steel", 0.85, 68.9, "High Mn austenitic"),
    ("4140 Steel (normalized)", "alloy_steel", 0.85, 68.9, "Normalized 4140"),
    ("MERL 76", "nickel_superalloy", 0.85, 34.5, "PM Ni superalloy"),
    ("21-6-9 + 0.3N (Nitronic 40)", "austenitic_steel", 0.85, 68.9, "Higher N content"),
    ("MP98T", "cobalt_superalloy", 0.85, 34.5, "Co-based superalloy"),
    ("X52 Pipeline (6.9 MPa)", "ferritic_steel", 0.86, 6.9, "Lower pressure"),
    ("MA 6000 (Longitudinal)", "nickel_ods", 0.86, 34.5, "ODS Ni superalloy"),
    ("X-45 (superalloy)", "cobalt_superalloy", 0.87, 34.5, "Co-based superalloy"),
    ("PWA 1480E (111 plane)", "nickel_superalloy", 0.88, 34.5, "Crystal orientation"),
    ("305 Steel", "austenitic_steel", 0.89, 68.9, "Low work hardening SS"),
    ("21-6-9 + 0.1N (Nitronic 40)", "austenitic_steel", 0.89, 68.9, "Lower N content"),

    # SMALL HEE (0.90-0.96)
    ("X70 Pipeline Steel", "ferritic_steel", 0.90, 6.9, "Pipeline grade"),
    ("X60 Pipeline Steel", "ferritic_steel", 0.92, 6.9, "Pipeline grade"),
    ("18-3-Mn", "austenitic_steel", 0.92, 68.9, "High Mn austenitic"),
    ("MA 6000 (Transverse)", "nickel_ods", 0.92, 34.5, "Transverse orientation"),
    ("Inconel 718 (ST 1900F)", "nickel_superalloy", 0.92, 34.5, "Higher ST temp"),
    ("309S Steel", "austenitic_steel", 0.93, 68.9, "Heat resistant SS"),
    ("Ni-SPAN-C (alloy 902)", "iron_superalloy", 0.93, 68.9, "Constant modulus alloy"),
    ("X42 Pipeline Steel", "ferritic_steel", 0.95, 6.9, "Pipeline grade"),
    ("MERL 76 (PM)", "nickel_superalloy", 0.96, 34.5, "PM version"),
    ("Incoloy 907", "iron_superalloy", 0.96, 68.9, "Low expansion alloy"),

    # NEGLIGIBLE HEE (0.97-1.00+)
    ("NASA-HR1", "iron_superalloy", 0.98, 34.5, "NASA developed alloy"),
    ("70-30 Brass", "copper_alloy", 0.98, 68.9, "Cartridge brass"),
    ("Incoloy 903 (ST only)", "iron_superalloy", 0.98, 34.5, "Solution treated only"),
    ("D6AC Steel (600C tempered)", "martensitic_steel", 0.98, 2.1, "High temper"),
    ("216 Steel", "austenitic_steel", 0.99, 68.9, "Austenitic SS"),
    ("22-13-5 (Nitronic 50)", "austenitic_steel", 1.00, 68.9, "High strength SS"),
    ("2011 Aluminum", "aluminum_alloy", 1.01, 68.9, "Free machining Al"),
    ("5086 Aluminum", "aluminum_alloy", 1.05, 68.9, "Marine grade Al"),
]

def get_hee_band(hee_index):
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

# Add new records
added = 0
for name, family, hee, pressure, notes in new_materials:
    evidence_id = f"NASA-TM-ADD-{added+1:03d}"
    record = {
        "evidence_id": evidence_id,
        "material_name": name,
        "material_key": name,
        "material_family": family,
        "test_conditions": {
            "pressure_mpa": pressure,
            "temperature_c": 24,
            "specimen_type": "notched",
            "reference_gas": "helium"
        },
        "metrics": {
            "nts_ratio": hee
        },
        "hee_index": hee,
        "hee_band": get_hee_band(hee),
        "source": {
            "document": "NASA/TM-2016-218602",
            "table": "Table 2 (extended)",
            "notes": notes
        },
        "he_mechanism": "HEE"
    }
    existing.append(record)
    added += 1
    print(f"Added: {name} (HEE={hee}, {get_hee_band(hee)})")

print(f"\nAdded {added} new records")
print(f"Total records now: {len(existing)}")

# Update metadata
data['total_records'] = len(existing)
data['sources'].append(f"NASA/TM-2016-218602 Table 2 extended ({added} records)")

# Save
with open(evidence_path, 'w') as f:
    json.dump(data, f, indent=2)

print(f"\nSaved to {evidence_path}")
