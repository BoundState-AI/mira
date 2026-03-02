# MUA Golden Set V1 Candidate

Generated: 2026-03-01T19:45:41.365364+00:00

## Source

- Dataset: `historic_muas_v2_heavy_maptis_full.ndjson`
- Path: `/mnt/c/maptis-nlp/output/historic_muas_v2_heavy_maptis_full.ndjson`
- Valid rows parsed: 4,868
- Bad rows skipped: 0

## Candidate Size

- Total candidate records: **270**

## Strata Counts

| Stratum | Count |
|---|---:|
| `edge.low_mapping_conf` | 15 |
| `edge.no_material` | 15 |
| `edge.no_rationale` | 20 |
| `legacy.COMPAT` | 20 |
| `legacy.OC` | 20 |
| `v10.CORR` | 30 |
| `v10.FLAM` | 30 |
| `v10.FS` | 30 |
| `v10.SCC` | 30 |
| `v10.TOX` | 30 |
| `v10.TVS` | 30 |

## Selected Issue Counts

| Issue | Count |
|---|---:|
| `EMPTY` | 14 |
| `CORR` | 30 |
| `FLAM` | 43 |
| `FS` | 32 |
| `LEGACY_COMPAT` | 22 |
| `LEGACY_OC` | 34 |
| `SCC` | 32 |
| `TOX` | 33 |
| `TVS` | 30 |

## Output Files

- JSONL: `/mnt/d/BoundState/boundstate_mira/data/mua_golden/golden_set_mua_v1_candidate.jsonl`
- Manifest: `/mnt/d/BoundState/boundstate_mira/data/mua_golden/golden_set_mua_v1_manifest.json`

## Promotion Criteria To True Golden Set

1. Dual-review adjudication on each candidate row (pass/fail and correction notes).
2. Freeze labels under versioned schema (e.g., `golden_set_mua_v1.0`).
3. Add regression harness checks in CI for deterministic replay.
