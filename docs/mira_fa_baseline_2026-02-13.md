# MIRA F/A Baseline (Existing Schema)

Date: 2026-02-13
Scope:
- Raw MAPTIS source audit: `C:\MIRA backup full\maptis-nlp\mira\data\raw`
- Live PostgreSQL audit: local `mira` database

Artifacts:
- Detailed machine report: `tmp/mira_fa_raw_audit.json`

## Executive Result
- F/A status: `FAIL` for production-grade intel-layer onboarding.
- You can define a `mira-ready` schema now, but it must be gated and treated as a controlled target, not assumed cleanly derivable from current source/runtime data.

## Gate Summary
### Raw Source Gates
- `header_hygiene`: `FAIL`
- `required_core_columns`: `PASS`
- `key_type_integrity`: `PASS`
- `lookup_join_coverage`: `FAIL`
- `material_type_dimension_coverage`: `FAIL`

### Live DB Gates
- `schema_namespace_determinism`: `FAIL` (duplicate table names across `public` and `maptis`)
- `schema_alignment_between_duplicates`: `FAIL` (same table names with different column contracts)
- `knowledge_twins_presence`: `FAIL` (`knowledge_twins.compatibility_records` absent)

## Evidence (Raw Source)
Raw totals:
- Report files audited: `24`
- Total report rows: `82,789`
- Lookup rows:
  - `materials_report.csv`: `31,446` parsed rows
  - `material_specfications_report.csv`: `16,427`
  - `matl_types_report.csv`: `19`

Header anomalies (3 files):
- `fluid_compatibility_report.csv`: duplicate header `FLUC_BaseLineDate x2`
- `electric_wire_insulation_report.csv`: duplicate header `EWI_BaseLineDate x2`
- `toxicity_report.csv`: `7` empty/unnamed trailing headers

Join coverage:
- Distinct `MaterialKey` in reports: `20,369`
- Distinct lookup material keys: `31,443`
- Report keys missing from lookup: `2,339` (`11.48%` of referenced report keys)
- Most severe file: `toxicity_report.csv` missing `1,993 / 5,393` distinct keys (`36.96%`)

Material type integrity (`lookup/materials_report.csv`):
- Non-numeric `MATL_MaterialTypeKey` rows: `421`
- Numeric type keys not present in `matl_types_report`: `24`
- Examples: `-1`, `1`, `711`, `788`, `1463`, `9778`, `10381`, `10510`, `20157`

Other quality notes:
- Core key fields in reports (`TestReportKey`, `MaterialKey`, `TestTypeKey`) parse as numeric (pass).
- Temperature ranges show no `max < min` inversions in this pass.

## Evidence (Live DB)
Current schema inventory:
- Base tables: `136`
- Non-system schemas with tables: `bok`, `map`, `maptis`, `public`, `ref`, `stage`

Duplicate table names across `public` and `maptis`: `25`
- Includes: `materials`, `flammability_tests`, `fluid_compatibility_tests`, `toxicity_tests`, etc.

Critical drift examples:
- `public.materials` (13 columns) vs `maptis.materials` (10 columns)
  - `public` has `material_key`, `material_type_key`, `material_type_name` that `maptis` lacks.
- Multiple `*_tests` / `*_results` tables have divergent contracts between schemas.

Row-count parity drift (raw file vs `public.silver_report_rows`):
- `flammability_report`: raw `17,784` vs silver `17,862` (`+78`)
- `pneumatic_impact_report`: raw `1,252` vs silver `1,263` (`+11`)
- Others in this pass: parity.

Key runtime tables:
- `public.materials`: `31,531`
- `maptis.materials`: `31,571`
- `public.silver_report_rows`: `130,844`
- `public.mua_precedents_v7`: `5,650`
- `public.heritage_failures`: `0`
- `knowledge_twins.compatibility_records`: missing

## What This Means For "MIRA-Ready"
`MIRA-ready` should be treated as a controlled canonical contract with strict ingestion gates:

1. Canonical entities:
- `materials`
- `material_conditions`
- `environment_envelopes` (separate tested vs rated envelope semantics)
- `test_evidence`
- `mua_precedents`
- `heritage_failures`
- provenance/audit/version tables

2. Mandatory controls before go-live:
- Header canonicalization (dedupe/rename duplicate columns deterministically)
- Contract-level parser for malformed CSV tails
- Referential repair policy for orphan `MaterialKey` rows
- Strict type-dimension reconciliation for material types
- Deterministic schema qualification (`public.` vs `maptis.`) in all runtime SQL
- Silver parity reconciliation gate (raw row count vs ingested row count per contract)

3. Runtime safety requirement:
- No unqualified table access in production-grade pipelines where duplicate names exist across schemas.

## Recommended Next Step
Proceed with F/A Phase 2 implementation plan:
1. Freeze this baseline as `v0`.
2. Implement remediation gates in ingestion.
3. Re-run F/A and require all critical gates `PASS`.
4. Only then freeze `mira-ready schema v1` as the intel-layer onboarding contract.

