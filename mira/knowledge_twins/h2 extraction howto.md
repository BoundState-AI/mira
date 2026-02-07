# H2 Evidence Extraction Prompt v2.1

Aligned with Fran's H2 Knowledge Twin Implementation Spec v2.1

---

## PROMPT (copy this):

```
Extract ALL hydrogen embrittlement test data from this document into JSON.

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

      "notes": "Delta phase precipitation at lower ST temp"
    }
  ]
}

## RULES

### HEE Band (NASA thresholds)
- negligible: 0.97-1.00
- small: 0.90-0.96
- high: 0.70-0.89
- severe: 0.50-0.69
- extreme: <0.50

### hee_index = best ratio available (NTS > RA > EL > KTH)

### Detecting HE Mechanism
- "gaseous hydrogen", "high pressure H2", "external" → HEE
- "precharged", "electrochemical", "cathodic", "internal" → IHE
- "hydride", titanium + hydrogen reaction → HRE

### Detecting Phase
- Temp < -150°C OR "LH2", "liquid hydrogen", "cryogenic" → LH2
- Otherwise → GH2

### Detecting Loading Mode
- "SSRT", "slow strain rate", "constant load" → static
- "fatigue", "cyclic", "LCF", "HCF" → cyclic
- "impact", "Charpy", "dynamic" → impact

### Detecting Grade
- Data in table with specific conditions → primary_test
- "Studies show...", summarized → secondary_summary
- "Should be used...", design guidance → guideline_statement

### Heat Treatment Codes
ST=solution_treated, STA=solution_treated_aged, Ann=annealed, Q&T=quenched_tempered

### Material Families
- 304/316/321/347 → austenitic_ss
- 21-6-9/Nitronic → nitrogen_ss
- 17-4/15-5 PH → ph_ss
- Inconel/Waspaloy/Rene/Hastelloy → nickel_superalloy
- A-286/JBK-75/Incoloy → iron_superalloy
- 4140/4340/HY-80 → low_alloy_steel
- Maraging → martensitic_ss

### Units: ksi→MPa (×6.895), psi→MPa (×0.006895)

Extract EVERY row from EVERY table. Return ONLY valid JSON.
```

---

## WHAT'S NEW IN v2.1

| Field | Why It Matters |
|-------|----------------|
| `he_mechanism` | IHE data must not be mixed with HEE - different failure modes |
| `grade` | Guideline statements must NEVER dominate over primary test data |
| `environment.phase` | GH2 vs LH2 - cryo boundary (-150°C) is regime change |
| `loading.mode` | Cyclic loading generally worse than static |
| `strength` | Needed for R004 high-strength rule (>1000 MPa triggers constraint) |

---

## FIELD MAPPING TO FRAN'S SPEC

| Extraction Field | → | EvidenceObject Field |
|-----------------|---|---------------------|
| `material_name` | → | `material_key` |
| `material_family` | → | `material_family` |
| `heat_treatment.condition` | → | `heat_treatment.condition` |
| `heat_treatment.*_temp_c` | → | `heat_treatment.*_temp_c` |
| `product_form` | → | `product_form` |
| `weld_state` | → | `weld_state` |
| `environment.phase` | → | `environment.phase` |
| `environment.pressure_mpa` | → | `environment.pressure_mpa` |
| `environment.temperature_c` | → | `environment.temperature_c` |
| `environment.reference_gas` | → | `reference_environment` |
| `loading.mode` | → | `loading.mode` |
| `test.specimen_type` | → | `specimen_type` |
| `test.method` | → | `test_method` |
| `he_mechanism` | → | `he_mechanism` |
| `metrics.*_ratio` | → | `metric` |
| `hee_band` | → | `hee_band` |
| `grade` | → | `grade` |
| `strength.yield_mpa` | → | `strength.yield_mpa` |
| `strength.uts_mpa` | → | `strength.uts_mpa` |
| `source` | → | `provenance` |

All fields now align with `H2DecisionEngine` requirements.
