# H2 Knowledge Twin v2.0 - Merged Specification

## Team Credits

| Role | Contributor | Contribution |
|------|-------------|--------------|
| **Lead** | Claude | Domain model, NASA thresholds, heat treatment structure, validity envelope |
| **Architecture** | Fran | Evidence-first design, verdict structure, API spec, audit trail |
| **Color** | Grok | Graph concepts, historical context, persona ideas (decorative) |

---

## What Changed from v1

### From Claude's v1
- ✅ Kept: Full heat treatment structure (not enum)
- ✅ Kept: Three loading rates for three specimen types
- ✅ Kept: NASA Table 1 thresholds (0.97/0.90/0.70/0.50)
- ✅ Kept: Ni content predictor (12.5% threshold)
- ✅ Kept: Temperature behavior patterns
- ✅ Kept: Validity envelope checks
- ➕ Added: Evidence grading hierarchy
- ➕ Added: Verdict structure with gaps/constraints/recommended_tests
- ➕ Added: Envelope match scoring
- ➕ Added: Full audit trail

### From Fran's Spec
- ✅ Adopted: `Verdict` enum (allowed/allowed_with_constraints/not_recommended/unknown)
- ✅ Adopted: `EvidenceGrade` hierarchy (primary_test > secondary_summary > guideline_statement)
- ✅ Adopted: `gaps[]` and `recommended_tests[]` outputs
- ✅ Adopted: Conservative aggregation (worst credible evidence)
- ✅ Adopted: Confidence scoring methodology
- ✅ Adopted: "No ALLOWED without primary_test" rule
- 🔧 Modified: Envelope scoring uses weighted average, not product

### From Grok
- ✅ Concept only: Graph relationships for materials (future work)
- ✅ Concept only: Historical events as context (decorative, not data)
- ❌ Rejected: GNN predictions for unlisted alloys (dangerous)
- ❌ Rejected: Persona as engineering rigor (theater, not safety)
- ❌ Rejected: Imperial units (source docs use SI)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        H2 Knowledge Twin v2.0                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐ │
│  │   Query     │ → │  Envelope   │ → │    Rule     │ → │  Verdict    │ │
│  │  Normalize  │   │   Matcher   │   │   Engine    │   │  Generator  │ │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘ │
│         │                │                 │                 │         │
│         ▼                ▼                 ▼                 ▼         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     Evidence Store                               │   │
│  │  • EvidenceObject with full provenance                          │   │
│  │  • Graded: PRIMARY_TEST > SECONDARY_SUMMARY > GUIDELINE         │   │
│  │  • Traceable to NASA TM, Sandia SAND, ASTM standards            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                           Response Package                              │
│  • verdict: allowed | allowed_with_constraints | not_recommended | unknown │
│  • confidence: 0-1                                                      │
│  • drivers[]: failure modes with evidence                              │
│  • constraints[]: explicit limits                                       │
│  • gaps[]: missing inputs                                              │
│  • recommended_tests[]: what would close the gaps                      │
│  • audit: full reproducibility trail                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Core Data Models

### Material Entity
```python
MaterialRecord
├── material_key        # Canonical ID
├── name               # Human readable  
├── spec               # AMS 5662, etc.
├── uns                # UNS number
├── family             # MaterialFamily enum (aligned with Sandia codes)
├── composition        # Composition object (Ni is KEY PREDICTOR)
├── heat_treatment     # FULL OBJECT, not enum!
│   ├── condition      # HeatTreatCondition enum
│   ├── solution_temp_c    # 940°C vs 1037°C MATTERS!
│   ├── solution_time_hr
│   ├── age_temp_c
│   ├── age_time_hr
│   └── ...
├── strength           # StrengthData
├── product_form       # Plate vs bar vs HAZ...
├── weld_state        # BASE_METAL | WELD_METAL | HAZ
└── grain_direction    # "longitudinal" | "transverse"
```

### Evidence Object (The Unit of Truth)
```python
EvidenceObject
├── evidence_id
├── material_key / material_family
├── heat_treatment     # FULL OBJECT again
├── environment        # HydrogenEnvironment
├── loading           # LoadingState
├── specimen_type     # SMOOTH | NOTCHED | PRECRACKED
├── metric            # MetricValue (NTS_ratio, RA_ratio, etc.)
├── hee_band          # NEGLIGIBLE | SMALL | HIGH | SEVERE | EXTREME
├── grade             # PRIMARY_TEST | SECONDARY_SUMMARY | GUIDELINE_STATEMENT
├── provenance        # REQUIRED - doc, page, table, authors
└── notes
```

---

## Verdict Logic

### Decision Flow
```
1. Find candidate evidence (material name matching)
2. Score envelope match per evidence object
3. Filter to credible evidence (score ≥ threshold)
4. Apply rule gates (hard blocks, soft warnings)
5. Get worst credible HEE band (conservative)
6. Map band to verdict floor
7. Check for ALLOWED upgrade conditions:
   - Strong match (≥0.8)
   - Minimal gaps
   - At least one PRIMARY_TEST grade evidence
8. Generate explanation with drivers, constraints, gaps
```

### Verdict Assignment
| HEE Band | Base Verdict | Can Upgrade to ALLOWED? |
|----------|--------------|-------------------------|
| NEGLIGIBLE | allowed_with_constraints | Yes, if strong match + primary test |
| SMALL | allowed_with_constraints | Yes, if strong match + primary test |
| HIGH | allowed_with_constraints | No |
| SEVERE | not_recommended | No |
| EXTREME | not_recommended | No |

---

## Authoritative Thresholds

**NASA/TM-2016-218602 Table 1** (THE NUMBERS):
```
NEGLIGIBLE: 0.97 - 1.00
SMALL:      0.90 - 0.96
HIGH:       0.70 - 0.89
SEVERE:     0.50 - 0.69
EXTREME:    0.00 - 0.49
```

**Validity Envelope** (test data boundaries):
```
Temperature: 20-26°C (nominal 22°C)
Pressure: 34.5-69 MPa (5-10 ksi)
```

**Ni Content Predictor** (Fe-Ni-Cr systems only):
```
< 8%:     SEVERE (typically)
8-12.5%:  HIGH (transition zone)
12.5-35%: NEGLIGIBLE (if annealed/ST)
> 35%:    HIGH (Ni-rich superalloys can be worse)

⚠️ NOT VALID FOR AGED CONDITIONS
```

---

## Demo Results

```
Query 1: 316 SS at 70 MPa, room temp
→ Verdict: allowed_with_constraints
→ Confidence: 0.75
→ Warning: Pressure outside NASA envelope

Query 2: Inconel 718 (aged) at 35 MPa, room temp  
→ Verdict: not_recommended
→ Confidence: 0.71
→ Drivers: HEE (severe), Heat treatment sensitivity (high)

Query 3: Unknown material
→ Verdict: unknown
→ Confidence: 0.0
→ Recommended: notched tensile per ASTM G129

Query 4: 316 SS in LH2 (cryogenic)
→ Verdict: unknown
→ Confidence: 0.2
→ Warning: Temperature -253°C outside NASA envelope
```

---

## Files

| File | Lines | Description |
|------|-------|-------------|
| `h2_knowledge_twin_v2.py` | ~1200 | Complete implementation |
| `H2_KNOWLEDGE_TWIN_V2_SUMMARY.md` | This file | Summary documentation |

---

## Next Steps

1. **O2 Knowledge Twin** - Different failure modes (ignition, promoted combustion)
2. **Evidence Ingestion** - Connect to Athena table extraction
3. **Graph Storage** - Neo4j for material relationships
4. **Fatigue Module** - da/dN curves, LCF life reduction
5. **API Server** - FastAPI wrapper for POST /h2/compatibility/query

---

## What This Replaces

| Old Approach | Problem | v2 Solution |
|--------------|---------|-------------|
| Material lists | No conditions | Evidence objects with full envelope |
| Hardcoded rules | Not traceable | Rules reference evidence_id |
| "Be careful" guidance | Not actionable | Explicit constraints with limits |
| Single HEE index | Loses context | Full envelope match with dimensions |
| Vibes-based confidence | Not reproducible | Deterministic scoring formula |
