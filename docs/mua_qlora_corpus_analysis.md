# MUA QLoRA Corpus Analysis

- Source file: `/mnt/d/BoundState/BoundState_other/BoundState/data/mua_v6_cleaned.jsonl`
- Total records: **6370**
- Usable records (category + rationale + application + confidence >= 0.7): **1953**
- Rationale truncated at 1024 tokens (whitespace proxy): **0** records

## Category Distribution (All Records with Category)

- I: 1527
- II: 366
- III: 73
- IV: 0

## Category Distribution (Usable Records)

- I: 1517 (77.68%)
- II: 366 (18.74%)
- III: 70 (3.58%)
- IV: 0 (0.00%)

## Determination Distribution (Usable, 3-Class Mapping)

- APPROVED: 1704 (87.25%)
- APPROVED_WITH_LIMITS: 237 (12.14%)
- DENIED: 12 (0.61%)

## Top Issues (All Records)

- flammability: 2730
- offgassing: 1427
- corrosion: 1357
- other: 1251
- toxicity: 1247
- scc: 1193
- tvs: 969
- workmanship: 640
- fluid_compat: 374
- o2_compat: 167
- process_spec: 75
- dissimilar_metals: 47
- fracture_control: 34

## Top Issues (Usable Records)

- flammability: 837
- corrosion: 451
- offgassing: 441
- scc: 372
- other: 345
- tvs: 331
- toxicity: 328
- workmanship: 217
- fluid_compat: 127
- o2_compat: 75
- process_spec: 28
- dissimilar_metals: 17
- fracture_control: 15

## Missing/Filter Failure Counts

- application: 59
- category: 4404
- confidence_lt_0.7: 173
- rationale: 11

## Split Summary

- Validation size requested/effective: 553/553
- Training size requested/effective: 1400/1400
- Unique train pool after val holdout: 1400

### Train Category Counts

- I: 1088
- II: 262
- III: 50
- IV: 0

### Validation Category Counts

- I: 429
- II: 104
- III: 20
- IV: 0
