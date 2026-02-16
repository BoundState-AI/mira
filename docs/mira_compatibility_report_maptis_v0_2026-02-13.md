# MIRA Compatibility Report: MAPTIS v0

Date: `2026-02-13`
Source System: `MAPTIS raw CSV + local PostgreSQL ("mira")`
Source Snapshot: `C:\MIRA backup full\maptis-nlp\mira\data\raw`
Report Version: `v0`
Status: `BLOCKED`

Related artifacts:
- `docs/mira_fa_baseline_2026-02-13.md`
- `tmp/mira_fa_raw_audit.json`

## 1) Executive Summary
- Readiness Decision: `FAIL` (not yet `MIRA-ready` for production intel-layer onboarding).
- This source is viable as onboarding case #1, but only with enforced gates and deterministic adapter rules.
- Primary blockers:
  - Header/contract anomalies in core CSV inputs.
  - Material lookup join gaps (`MaterialKey` references unresolved).
  - Schema ambiguity and drift across `public` and `maptis` runtime tables.

## 2) Source Inventory
### 2.1 Structural Inventory
- Raw report contracts: `24` CSVs (`*_report.csv`) with shared core columns:
  - `TestReportKey`, `MaterialKey`, `TestTypeKey`, `TestTypeCaption`, `TestReportNumber`, `RequestDate`, `TemperatureMinimum`, `TemperatureMaximum`
- Lookup tables:
  - `materials_report.csv`
  - `material_specfications_report.csv`
  - `matl_types_report.csv`
- Raw totals:
  - Report rows: `82,789`
  - Lookup material rows parsed: `31,446`
  - Lookup spec rows: `16,427`
  - Lookup type rows: `19`

### 2.2 Live DB Inventory (local)
- Non-system schemas with tables: `bok`, `map`, `maptis`, `public`, `ref`, `stage`
- Base tables total: `136`
- Duplicate table names across `public` and `maptis`: `25`
- Key runtime counts:
  - `public.materials`: `31,531`
  - `maptis.materials`: `31,571`
  - `public.silver_report_rows`: `130,844`
  - `public.mua_precedents_v7`: `5,650`
  - `public.heritage_failures`: `0`
  - `knowledge_twins.compatibility_records`: missing

## 3) MIRA Concept Coverage Map
| MIRA Canonical Concept | Source Coverage | Primary Source Fields/Tables | Coverage Level | Notes |
|---|---|---|---|---|
| `material_identity` | Material master records | `materials_report`, `public.materials`, `maptis.materials` | `PARTIAL` | Strong identity basis, but lookup/report join gaps and schema drift exist. |
| `material_condition` | Partial condition-like fields | `composition`, `use_type`, test-specific fields | `PARTIAL` | No clean canonical condition entity yet. |
| `environment` | Test envelope signals | `TemperatureMinimum/Maximum` + test-specific pressure/fluid/O2 fields | `PARTIAL` | Usable but fragmented by test contract. |
| `test_evidence` | Strong coverage | 24 report contracts + `silver_report_rows.normalized_payload` | `FULL` | Best-covered concept in current source. |
| `determination` | Separate precedent layer | `public.mua_precedents_v7` | `PARTIAL` | Available for MUA workflows; not unified with all evidence models. |
| `provenance` | Row-level lineage base | `contract_id`, `row_uid`, source files, migration tables | `PARTIAL` | Needs enforced trace chain raw->silver->decision in adapter. |
| `safety_context` | Indirect | test contract type + env fields | `PARTIAL` | Requires deterministic derivation rules. |

## 4) Transformation Rules (v0 Adapter Proposal)
### 4.1 Identity Rules
- Canonical material key source: `material_key` (integer) from qualified table (`public.materials` or `maptis.materials`, chosen explicitly per adapter profile).
- Canonical report identity: `contract_id + testreportkey` from `normalized_payload`.
- Deterministic dedupe key:
  - `contract_id`
  - normalized `testreportkey`
  - normalized `materialkey`
  - `sha256(normalized_payload)`

### 4.2 Units and Normalization
- Temperature: source Fahrenheit-like fields -> canonical Celsius for MIRA runtime layers.
- Pressure/O2/media: extracted from contract-specific payload keys into canonical envelope fields.
- Ratings: contract-specific rating columns normalized to canonical rating enums.

### 4.3 Type and Enum Canonicalization
- Material type mapping: `MATL_MaterialTypeKey` -> canonical material class via type dimension table.
- Test type mapping: `contract_id`/`TestTypeKey` -> canonical `test_type`.
- Safety context derivation: deterministic rules based on fluid, O2 concentration, pressure, and known test classes.

## 5) Data Quality Profile
### 5.1 Integrity Metrics
- `required_core_columns`: `PASS` across 24 report contracts.
- `key_type_integrity`: `PASS` for report-level required keys in this pass.
- `lookup_join_coverage`: `FAIL`
  - Distinct report `MaterialKey`: `20,369`
  - Missing in lookup: `2,339` (`11.48%`)
  - Highest impact contract: `toxicity_report` missing `1,993 / 5,393` (`36.96%`)
- `material_type_dimension_coverage`: `FAIL`
  - Non-numeric `MATL_MaterialTypeKey` rows: `421`
  - Unknown numeric type keys not in dimension: `24`

### 5.2 Anomaly Metrics
- Header anomalies:
  - `fluid_compatibility_report.csv`: `FLUC_BaseLineDate x2`
  - `electric_wire_insulation_report.csv`: `EWI_BaseLineDate x2`
  - `toxicity_report.csv`: `7` empty headers
- Runtime schema ambiguity:
  - Same table names across `public` and `maptis` with non-identical column contracts.
- Raw/silver parity drift:
  - `flammability_report`: raw `17,784` vs silver `17,862` (`+78`)
  - `pneumatic_impact_report`: raw `1,252` vs silver `1,263` (`+11`)

## 6) Gap Analysis
| Needed by MIRA | Available? | Gap Severity | Workaround | Long-term Fix |
|---|---|---|---|---|
| Deterministic source contract (no malformed headers) | No | HIGH | Contract-specific parser shims | Enforce source export contract + schema checks |
| 100% material lookup joinability | No | HIGH | Quarantine unresolved keys; confidence penalty | Repair lookup coverage and key governance |
| Clean material type dimension | No | HIGH | Temporary fallback class `unknown` | Fix non-numeric corruption + complete type map |
| Unambiguous runtime schema resolution | No | HIGH | Force fully-qualified schema names in all SQL | Rationalize duplicated tables/schemas |
| Knowledge twins physical tables available | No | MED | Disable twin-backed paths in this adapter profile | Apply migrations and validate tables |

## 7) Readiness Gates (v0)
| Gate | Rule | Result | Evidence |
|---|---|---|---|
| `header_hygiene` | No duplicate/empty headers in ingest contracts | `FAIL` | 3 contracts with anomalies |
| `required_core_columns` | Required report keys/columns always present | `PASS` | 24/24 contracts |
| `key_type_integrity` | Core keys parse correctly | `PASS` | 0 invalid core key rows in reports |
| `join_coverage` | `MaterialKey` lookup coverage >= threshold | `FAIL` | 2,339 missing keys |
| `type_dimension_coverage` | Type keys fully map to dimension | `FAIL` | 421 non-numeric + 24 unknown numeric |
| `schema_determinism` | No ambiguous table resolution | `FAIL` | 25 duplicate names across schemas |
| `parity_reconciliation` | Raw-to-silver parity within tolerance | `FAIL` | 2 contract deltas detected |
| `knowledge_twin_presence` | Required twin tables exist when enabled | `FAIL` | tables absent |

## 8) Adapter Contract (MAPTIS v0)
### 8.1 Input Contract
- Required source:
  - Raw CSV contracts in fixed set (`*_report.csv`, lookup files), or
  - Equivalent `public.silver_report_rows` + qualified material dimensions.
- Required schemas:
  - Explicitly qualified (`public.` / `maptis.`), never implicit resolution.

### 8.2 Canonical Output Contract
- Entities emitted by adapter:
  - `materials`
  - `test_evidence`
  - `environment_envelopes`
  - `determinations` (from `mua_precedents_v7` where applicable)
  - `provenance_links`
- Each output row carries:
  - canonical id
  - source id(s)
  - transform version
  - confidence
  - hash lineage

### 8.3 Deterministic Rules
- Stable `search_path` policy or explicit schema prefixes in every query.
- Source anomaly policy:
  - duplicate headers -> deterministic rename/reject rule
  - orphan keys -> quarantine + confidence downgrade
  - unmapped type keys -> `unknown` class + escalation
- Idempotent processing:
  - repeat ingest with same input yields same canonical records and hashes.

## 9) Decision
- Current recommendation: `DO_NOT_ONBOARD` as unrestricted production profile.
- Allowed recommendation: `ONBOARD_WITH_GUARDS` for controlled pilot profile.

Preconditions to move forward:
1. Implement and enforce adapter gates above (`header`, `join`, `type`, `schema`, `parity`).
2. Freeze a canonical mapping dictionary (`source_field -> canonical_field`) with versioning.
3. Re-run F/A and require critical gates to pass before upgrading status to `CONDITIONAL` or `READY`.

## 10) Artifacts
- Baseline narrative: `docs/mira_fa_baseline_2026-02-13.md`
- Machine audit: `tmp/mira_fa_raw_audit.json`
- This compatibility report: `docs/mira_compatibility_report_maptis_v0_2026-02-13.md`
- Reusable template: `docs/mira_compatibility_report_template.md`

