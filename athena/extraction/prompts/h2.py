#!/usr/bin/env python3
"""
Module: H2
Purpose: ATHENA H2 Domain-Specific Extraction Prompts.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

__all__ = ["H2_TABLE_EXTRACTION_PROMPT", "H2_CONTEXT_FIELDS"]
__safety_critical__ = True


# Fields we need to extract for EvidenceObject
H2_CONTEXT_FIELDS = [
    "heat_treatment",
    "product_form",
    "specimen_type",
    "test_method",
    "strain_rate",
    "pressure",
    "grain_direction",
    "weld_state",
]


H2_TABLE_EXTRACTION_PROMPT = """Extract hydrogen embrittlement test data from this table.

You are extracting data for hydrogen compatibility assessment. The output will be used
to populate EvidenceObjects for the H2 Knowledge Twin system.

## Required Output Schema

Return JSON with ALL fields you can determine from the table AND page context:

```json
{
  "table_metadata": {
    "title": "Table title if visible",
    "source": "Document reference if mentioned",
    "test_method": "ASTM G129 | ASTM E1681 | SSRT | etc.",
    "specimen_type": "smooth | notched | precracked",
    "pressure_mpa": 34.5,
    "temperature_c": 22,
    "strain_rate_s": 1e-5,
    "reference_environment": "helium | air | nitrogen"
  },
  "records": [
    {
      "material_name": "Inconel 718",
      "material_spec": "AMS 5662",
      "uns_number": "N07718",

      "heat_treatment": {
        "condition": "STA | ST | annealed | Q&T | as-received",
        "solution_temp_c": 1037,
        "solution_time_hr": 1,
        "age_temp_c": 718,
        "age_time_hr": 8,
        "cooling": "air | water | oil"
      },

      "product_form": "bar | plate | forging | sheet | tubing | wire | casting",
      "grain_direction": "longitudinal | transverse | short-transverse",
      "weld_state": "base_metal | weld_metal | HAZ",

      "strength_mpa": {
        "yield": 1034,
        "tensile": 1241
      },

      "test_data": {
        "ra_h2_pct": 12.5,
        "ra_he_pct": 45.2,
        "ra_ratio": 0.28,

        "el_h2_pct": 8.2,
        "el_he_pct": 15.4,
        "el_ratio": 0.53,

        "nts_h2": 1150,
        "nts_he": 1580,
        "nts_ratio": 0.73,

        "yield_ratio": 0.95,
        "tensile_ratio": 0.88
      },

      "reference": "NASA/TM-2016-218602 Table 7"
    }
  ]
}
```

## CRITICAL METADATA EXTRACTION

Look in these locations for metadata (not just table cells):
1. **Table title/caption** - often contains test method, pressure, temperature
2. **Column headers** - may include units, environment (H2/He), specimen type
3. **Footnotes** - strain rate, test method details, heat treatment codes
4. **Page headers/footers** - document reference
5. **Adjacent text** - context about test conditions

### Heat Treatment Codes (common abbreviations):
- ST = Solution Treated (good H2 resistance)
- STA = Solution Treated and Aged (often worse)
- SA = Solution Annealed
- Ann = Annealed
- Q&T = Quenched and Tempered
- AR = As-Received
- CW = Cold Worked

### Product Form:
- Look for: bar, plate, forging, sheet, tube/tubing, wire, casting, PM (powder metallurgy)

### Specimen Type:
- smooth = no stress concentration (for RA, elongation)
- notched = has notch (for NTS - Notched Tensile Strength)
- precracked = fatigue precracked (for K_TH, K_IC)

### Test Methods:
- ASTM G129 = Slow Strain Rate Test (SSRT)
- ASTM E1681 = Rising Step Load
- ASTM E399 = Fracture toughness

## Data Extraction Rules

1. **Ratios**: If table shows H2 and He (or air) values, calculate ratio = H2/He
2. **Percentages**: RA and elongation are typically in % - convert to decimal for ratio
3. **NTS**: Notched tensile strength is often in MPa or ksi - note units
4. **Temperature**: Convert to Celsius if given in other units
5. **Pressure**: Convert to MPa if given in ksi/psi/bar

## Handle Missing Data

- Use null for any field you cannot determine
- Do NOT guess or interpolate missing values
- If heat treatment is mentioned but details unclear, set condition only

Return ONLY the JSON object, no additional text."""


H2_ENRICHMENT_PROMPT = """Given this extracted table data and the original page context,
fill in missing metadata fields for hydrogen embrittlement testing.

## Current Extracted Data:
{extracted_data}

## Page Context (text surrounding table):
{page_context}

## Fields to Enrich:
- heat_treatment: Look for ST, STA, annealed, aged, solution temp, age temp
- product_form: plate, bar, forging, sheet, tubing, wire
- specimen_type: smooth, notched, precracked
- test_method: ASTM G129, ASTM E1681, SSRT, etc.
- pressure_mpa: Test gas pressure (often in title or footnotes)
- strain_rate_s: Often as 10^-5 /s or similar
- reference: Document citation

Return enriched JSON with updated fields. Keep all original data."""
