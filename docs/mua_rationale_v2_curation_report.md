# MUA Rationale V2 Curation Report

- Input rows: **5000**
- Rows passing quality filters (pre-cap): **880**
- Rows selected after quality ranking cap (`target_total=900`): **880**
- Train rows written: **704** -> `mua_rationale_train_v2_curated.jsonl`
- Val rows written: **176** -> `mua_rationale_val_v2_curated.jsonl`

## Filter Thresholds

- min_words: `25`
- max_words: `140`
- max_uppercase_ratio: `0.65`
- min_deficiency_recall: `0.2`
- min_context_recall: `0.06`
- min_evidence_recall (when explicit evidence exists): `0.08`

## Quality Metrics (Selected Pool)

- avg quality_score: `0.5174`
- avg deficiency_recall: `0.6187`
- avg context_recall: `0.1738`
- avg evidence_recall: `0.7794`
- avg word_count: `63.68`

## Quality Metrics (Train)

- avg quality_score: `0.5184`
- avg deficiency_recall: `0.6185`
- avg context_recall: `0.1776`
- avg evidence_recall: `0.7795`
- avg word_count: `63.60`

## Quality Metrics (Validation)

- avg quality_score: `0.5130`
- avg deficiency_recall: `0.6192`
- avg context_recall: `0.1585`
- avg evidence_recall: `0.7792`
- avg word_count: `63.98`

## Top Deficiency Buckets (Selected)

- corrosion: 310
- offgassing: 221
- flammability: 172
- workmanship: 61
- tvs: 30
- scc: 29
- toxicity: 16
- fluid: 15
- other: 13
- process: 7
- o2: 5
- fracture: 1

## Top Deficiency Buckets (Train)

- corrosion: 248
- offgassing: 177
- flammability: 137
- workmanship: 49
- tvs: 24
- scc: 23
- toxicity: 13
- fluid: 12
- other: 10
- process: 6
- o2: 4
- fracture: 1

## Top Deficiency Buckets (Validation)

- corrosion: 62
- offgassing: 44
- flammability: 35
- workmanship: 12
- scc: 6
- tvs: 6
- toxicity: 3
- other: 3
- fluid: 3
- process: 1
- o2: 1

## Filter Drop Reasons

- low_deficiency_grounding: 1597
- too_short: 1250
- all_caps_style: 532
- low_context_grounding: 374
- low_evidence_grounding: 360
- duplicate_target: 7
