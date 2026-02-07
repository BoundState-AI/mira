#!/usr/bin/env python3
"""
Module: Extract H2
Purpose: Extract H2 Evidence from PDFs - v2.1

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

import anthropic
import base64
import json
import sys
from pathlib import Path
import uuid

client = anthropic.Anthropic()

PROMPT = """Extract ALL hydrogen embrittlement test data from this document into JSON.

## CRITICAL FIELDS TO CAPTURE

For each material/test combination, you MUST determine:

1. **he_mechanism** - CRITICAL, do not mix:
   - "HEE" = Hydrogen Environment Embrittlement (external gaseous H2)
   - "IHE" = Internal Hydrogen Embrittlement (precharged/electrochemical)
   - "HRE" = Hydrogen Reaction Embrittlement (hydride formation, mainly Ti)

2. **grade** - Evidence quality:
   - "primary_test" = Direct test result with specific conditions (from tables, figures)
   - "secondary_summary" = Aggregated/averaged from multiple tests
   - "guideline_statement" = General guidance without specific test data

3. **environment.phase**:
   - "GH2" = Gaseous hydrogen (room temp or elevated)
   - "LH2" = Liquid hydrogen (cryogenic, below -150°C)

4. **loading.mode**:
   - "static" = Constant load or slow strain rate
   - "cyclic" = Fatigue, repeated loading
   - "impact" = Dynamic/impact loading

## OUTPUT SCHEMA

```json
{
  "evidence": [
    {
      "material_name": "Inconel 718",
      "uns_number": "N07718",
      "material_family": "nickel_superalloy",

      "heat_treatment": {
        "condition": "solution_treated_aged",
        "solution_temp_c": 954,
        "solution_time_hr": 1,
        "age_temp_c": 718,
        "age_time_hr": 8,
        "description": "954°C/1hr AC + 718°C/8hr"
      },

      "product_form": "bar",
      "weld_state": "base_metal",
      "grain_direction": null,

      "strength": {
        "yield_mpa": 1034,
        "uts_mpa": 1241
      },

      "environment": {
        "phase": "GH2",
        "pressure_mpa": 34.5,
        "temperature_c": 22,
        "reference_gas": "helium"
      },

      "loading": {
        "mode": "static",
        "strain_rate_per_s": 1e-5
      },

      "test": {
        "specimen_type": "notched",
        "method": "ASTM G129",
        "kt_factor": 8.0
      },

      "he_mechanism": "HEE",

      "metrics": {
        "nts_ratio": 0.54,
        "ra_ratio": null,
        "el_ratio": null,
        "kth_ratio": null
      },

      "hee_index": 0.54,
      "hee_band": "severe",

      "grade": "primary_test",

      "source": {
        "document": "NASA/TM-2016-218602",
        "table": "Table 9",
        "page": 47
      },

      "notes": "Delta phase at grain boundaries when ST at lower temp"
    }
  ]
}
```

## EXTRACTION RULES

### HEE Band Thresholds (NASA)
- negligible: 0.97-1.00
- small: 0.90-0.96
- high: 0.70-0.89
- severe: 0.50-0.69
- extreme: 0.00-0.49

### hee_index Priority
Use the best available ratio: NTS > RA > elongation > KTH

### Detecting HE Mechanism
- "gaseous hydrogen", "high pressure H2", "external" → HEE
- "precharged", "electrochemical", "cathodic", "internal" → IHE
- "hydride", titanium alloys with hydrogen reaction → HRE

### Detecting Phase
- Temperature < -150°C or mentions "LH2", "liquid hydrogen", "cryogenic" → LH2
- Otherwise → GH2

### Detecting Loading Mode
- "SSRT", "slow strain rate", "constant load", "sustained load" → static
- "fatigue", "cyclic", "LCF", "HCF", "da/dN" → cyclic
- "impact", "Charpy", "dynamic" → impact

### Detecting Grade
- Specific test result in a data table → primary_test
- "Studies show...", "Generally...", summarized values → secondary_summary
- "Should be used...", "Not recommended...", design guidance → guideline_statement

### Heat Treatment Codes
- ST = solution_treated
- STA = solution_treated_aged
- Ann = annealed
- Q&T = quenched_tempered
- AR = as_received
- CW = cold_worked

### Unit Conversions
- ksi → MPa: multiply by 6.895
- psi → MPa: multiply by 0.006895
- °F → °C: (°F - 32) × 5/9

### Material Family Classification
- 304, 316, 321, 347 → austenitic_ss
- 21-6-9, Nitronic → nitrogen_ss
- 17-4 PH, 15-5 PH → ph_ss
- 410, 440C → martensitic_ss
- Inconel, Waspaloy, Rene, Hastelloy → nickel_superalloy
- A-286, JBK-75, Incoloy → iron_superalloy
- Haynes 188, MP35N → cobalt_superalloy
- 4140, 4340, HY-80/100 → low_alloy_steel
- 1020, 1040, A515 → carbon_steel
- Maraging → martensitic_ss

## IMPORTANT

1. Extract EVERY data point from tables - each row is a separate evidence object
2. Look in table titles, footnotes, and captions for test conditions
3. If mechanism is unclear, default to "HEE" for gaseous H2 tests
4. If grade is unclear but data is from a table, use "primary_test"
5. Include strength values (YS, UTS) when available - needed for high-strength rules
6. Preserve any caveats or footnotes in the "notes" field

Return ONLY valid JSON. Extract ALL data from ALL tables."""


def extract_pdf(pdf_path: Path) -> list[dict]:
    """Send PDF to Claude, get evidence JSON back."""
    print(f"  Sending to Claude...")

    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64
                    }
                },
                {"type": "text", "text": PROMPT}
            ]
        }]
    )

    text = response.content[0].text

    # Strip markdown fences if present
    if "```" in text:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        else:
            text = text.split("```")[1].split("```")[0]

    text = text.strip()

    try:
        data = json.loads(text)
        evidence = data.get("evidence", data if isinstance(data, list) else [])

        # Validate and set defaults
        for e in evidence:
            # Ensure required fields have defaults
            if "he_mechanism" not in e:
                e["he_mechanism"] = "HEE"  # Default for gaseous tests
            if "grade" not in e:
                e["grade"] = "primary_test"  # Default if from table
            if "environment" not in e:
                e["environment"] = {}
            if "phase" not in e.get("environment", {}):
                # Infer from temperature
                temp = e.get("environment", {}).get("temperature_c")
                if temp is not None and temp < -150:
                    e["environment"]["phase"] = "LH2"
                else:
                    e["environment"]["phase"] = "GH2"
            if "loading" not in e:
                e["loading"] = {"mode": "static"}
            if "mode" not in e.get("loading", {}):
                e["loading"]["mode"] = "static"

        return evidence
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        print(f"  Raw response: {text[:500]}...")
        return []


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_h2_v2.py <pdf_or_directory>")
        sys.exit(1)

    target = Path(sys.argv[1])

    if target.is_file():
        pdfs = [target]
    elif target.is_dir():
        pdfs = list(target.glob("*.pdf"))
    else:
        print(f"Not found: {target}")
        sys.exit(1)

    print(f"Found {len(pdfs)} PDF(s)")

    all_evidence = []
    errors = []

    for pdf in sorted(pdfs):
        print(f"\n[{pdfs.index(pdf)+1}/{len(pdfs)}] {pdf.name}")
        try:
            evidence = extract_pdf(pdf)
            print(f"  → {len(evidence)} records")
            all_evidence.extend(evidence)
        except Exception as e:
            print(f"  → ERROR: {e}")
            errors.append({"file": pdf.name, "error": str(e)})

    # Save output
    output_file = Path("h2_evidence_v2.json")
    output = {
        "version": "2.1",
        "schema": "H2EvidenceObject per Fran's spec",
        "total_records": len(all_evidence),
        "source_files": len(pdfs),
        "errors": errors,
        "evidence": all_evidence
    }

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"DONE: {len(all_evidence)} evidence records from {len(pdfs)} files")
    print(f"Saved: {output_file}")

    if errors:
        print(f"Errors: {len(errors)} files failed")

    # Stats
    print("\n--- COVERAGE STATS ---")

    by_band = {}
    by_mechanism = {}
    by_grade = {}
    by_phase = {}
    by_loading = {}

    for e in all_evidence:
        band = e.get("hee_band", "unknown")
        by_band[band] = by_band.get(band, 0) + 1

        mech = e.get("he_mechanism", "unknown")
        by_mechanism[mech] = by_mechanism.get(mech, 0) + 1

        grade = e.get("grade", "unknown")
        by_grade[grade] = by_grade.get(grade, 0) + 1

        phase = e.get("environment", {}).get("phase", "unknown")
        by_phase[phase] = by_phase.get(phase, 0) + 1

        mode = e.get("loading", {}).get("mode", "unknown")
        by_loading[mode] = by_loading.get(mode, 0) + 1

    print("\nBy HEE Band:")
    for k in ["negligible", "small", "high", "severe", "extreme", "unknown"]:
        if k in by_band:
            print(f"  {k}: {by_band[k]}")

    print("\nBy HE Mechanism:")
    for k, v in sorted(by_mechanism.items()):
        print(f"  {k}: {v}")

    print("\nBy Grade:")
    for k, v in sorted(by_grade.items()):
        print(f"  {k}: {v}")

    print("\nBy Phase:")
    for k, v in sorted(by_phase.items()):
        print(f"  {k}: {v}")

    print("\nBy Loading Mode:")
    for k, v in sorted(by_loading.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
