# MUA Rationale SFT Corpus Analysis

- Source file: `/mnt/d/BoundState/BoundState_other/BoundState/data/mua_v6_cleaned.jsonl`
- Total records: **6370**
- Usable records (rationale + application + issues + confidence >= 0.7): **6181**
- Rationale truncated at 1024 tokens (whitespace proxy): **0** records

## Deficiency Bucket Distribution (Usable)

- flammability: 1431 (23.15%)
- corrosion: 1331 (21.53%)
- other: 1159 (18.75%)
- offgassing: 1042 (16.86%)
- workmanship: 440 (7.12%)
- scc: 190 (3.07%)
- o2: 156 (2.52%)
- toxicity: 130 (2.10%)
- tvs: 115 (1.86%)
- fluid: 103 (1.67%)
- process: 55 (0.89%)
- fracture: 23 (0.37%)
- dissimilar: 6 (0.10%)

## Evidence Type Coverage (Usable)

- No explicit supporting evidence captured in parsed fields: 3805 (61.56%)
- Configuration or qualification testing: 1615 (26.13%)
- Referenced test reports: 663 (10.73%)
- Similarity to tested configuration: 334 (5.40%)
- Engineering analysis: 285 (4.61%)
- MAPTIS reference: 208 (3.37%)
- Rationale code references: 35 (0.57%)
- Flight heritage: 13 (0.21%)

## Missing/Filter Failure Counts

- application: 59
- confidence_lt_0.7: 173
- rationale: 11

## Split Summary

- Training rows: 4000
- Validation rows: 1000
- Unique pool after val holdout: 5181

### Train Deficiency Buckets (Top 20)

- flammability: 926
- corrosion: 862
- other: 750
- offgassing: 674
- workmanship: 285
- scc: 123
- o2: 101
- toxicity: 84
- tvs: 74
- fluid: 66
- process: 36
- fracture: 15
- dissimilar: 4

### Validation Deficiency Buckets (Top 20)

- flammability: 231
- corrosion: 215
- other: 187
- offgassing: 169
- workmanship: 71
- scc: 31
- o2: 25
- toxicity: 21
- tvs: 19
- fluid: 17
- process: 9
- fracture: 4
- dissimilar: 1
