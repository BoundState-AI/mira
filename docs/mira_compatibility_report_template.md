# MIRA Compatibility Report Template

Date: `YYYY-MM-DD`
Source System: `<source_name>`
Source Version/Snapshot: `<snapshot_id_or_date>`
Report Version: `v0`
Status: `DRAFT | READY | BLOCKED`

## 1) Executive Summary
- Readiness Decision: `PASS | CONDITIONAL | FAIL`
- Intended Use:
  - `Search`
  - `Compatibility reasoning`
  - `Compliance/MUA generation`
  - `Provenance/audit`
- Top blockers:
  - `<blocker_1>`
  - `<blocker_2>`

## 2) Source Inventory
### 2.1 Structural Inventory
- Schemas:
- Tables:
- Row counts:
- Key candidates (PK/FK):
- Last update cadence:

### 2.2 Field Inventory
- Column coverage profile:
- Data types profile:
- Null distribution:
- Duplicate headers / duplicate columns:

## 3) MIRA Concept Coverage Map
| MIRA Canonical Concept | Source Coverage | Primary Source Fields/Tables | Coverage Level | Notes |
|---|---|---|---|---|
| `material_identity` |  |  | `FULL/PARTIAL/NONE` |  |
| `material_condition` |  |  |  |  |
| `environment` |  |  |  |  |
| `test_evidence` |  |  |  |  |
| `determination` |  |  |  |  |
| `provenance` |  |  |  |  |
| `safety_context` |  |  |  |  |

## 4) Transformation Rules (Source -> Canonical)
### 4.1 Identity Rules
- Material key normalization:
- Report key normalization:
- Deduping policy:

### 4.2 Units and Normalization
- Temperature:
- Pressure:
- Concentration:
- Rating normalization:

### 4.3 Type and Enum Canonicalization
- Material type mapping:
- Test type mapping:
- Environment type mapping:

## 5) Data Quality Profile
### 5.1 Integrity Metrics
- Key parse success:
- FK/join coverage:
- Type integrity:
- Schema drift:

### 5.2 Anomaly Metrics
- Header anomalies:
- Orphan key rates:
- Unexpected value distributions:
- Parity drift (raw vs ingested):

## 6) Gap Analysis
| Needed by MIRA | Available? | Gap Severity | Workaround | Long-term Fix |
|---|---|---|---|---|
|  |  | `LOW/MED/HIGH` |  |  |

## 7) Readiness Gates
| Gate | Rule | Result | Evidence |
|---|---|---|---|
| `header_hygiene` | No duplicate/empty headers in ingest contracts | `PASS/FAIL` |  |
| `key_integrity` | Required keys parse and remain stable | `PASS/FAIL` |  |
| `join_coverage` | Material/report joins meet threshold | `PASS/FAIL` |  |
| `type_dimension_coverage` | Type keys fully map to canonical dims | `PASS/FAIL` |  |
| `schema_determinism` | No ambiguous table resolution at runtime | `PASS/FAIL` |  |
| `parity_reconciliation` | Raw-to-silver parity within tolerance | `PASS/FAIL` |  |
| `provenance_traceability` | Raw->Silver->Decision trace complete | `PASS/FAIL` |  |

### Gate Threshold Profile
- `join_coverage_missing_rate <= <threshold>`
- `type_unmapped_rate <= <threshold>`
- `parity_delta <= <threshold>`
- `critical_gate_failures == 0`

## 8) Adapter Contract (Execution Spec)
### 8.1 Input Contract
- Required source tables:
- Required columns:
- Required schemas:

### 8.2 Canonical Output Contract
- Output entities:
- Required canonical fields:
- Confidence fields:
- Provenance fields:

### 8.3 Deterministic Rules
- `search_path` / explicit schema qualification:
- Conflict resolution policy:
- Reprocessing idempotency rules:

## 9) Decision
- Current recommendation: `ONBOARD | ONBOARD_WITH_GUARDS | DO_NOT_ONBOARD`
- Preconditions to move forward:
  1. 
  2. 
  3. 

## 10) Artifacts
- Audit JSON:
- SQL validation scripts:
- Mapping dictionaries:
- Sample reconciled extracts:

