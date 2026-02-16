# MUA Data Map (Updated)

Generated: 2026-02-15 11:09

## Canonical Dataset

**`C:\BoundState\data\mua_merged_clean.jsonl`** -- 7,346 records

This is the clean merged dataset. Ghost records removed, v5 material names backfilled.

### Schema

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `file` | string | v6_parsed | Source PDF filename |
| `success` | bool | Recomputed | True only if actual content was extracted |
| `confidence` | float | v6_parsed | 0.0-1.0 extraction confidence |
| `material_designation` | string | v6_parsed (backfilled from v6_cleaned) | Best v6 material name |
| `material_designation_v6` | string | v6_parsed | Original v6 extraction (may be empty) |
| `material_name_v5` | string | historic_mua.jsonl | v5 parser material name (cruder but wider coverage) |
| `material_family` | string | v6_cleaned | Normalized family (aluminum, stainless_steel, etc.) |
| `issues_cleaned` | array | v6_cleaned | Parsed concern list ["scc", "flammability", ...] |
| `environment_structured` | object | v6_cleaned | `{type, o2_percent, pressure_psia, ...}` |
| `mua_number` | string | v6_parsed | MUA document number |
| `category` | string | v6_parsed | I, II, III |
| `determination` | string | v6_parsed | APPROVED, DEFERRED, REJECTED, etc. |
| `environment` | string | v6_parsed | Raw environment text |
| `location` | string | v6_parsed | Habitable/Nonhabitable |
| `application` | string | v6_parsed | What the material is used for (max 500 chars) |
| `rationale` | string | v6_parsed | Why deviation is acceptable (max 500 chars) |
| `issue` | string | v6_parsed | Concern domain description (max 200 chars) |
| `manufacturer` | string | v6_parsed | Material manufacturer |
| `trade_name` | string | v6_parsed | Commercial name |
| `specification` | string | v6_parsed | Governing spec |
| `extraction_mode` | string | v6_parsed | vision or unknown |

## Source Lineage

```
v6_parsed (13,786 raw) --> filter ghosts (-6,440)
                      --> backfill v5 materials (+657)
                      --> backfill v6_cleaned (+1 mat, +6,377 family)
                      --> recompute success field
                      = mua_merged_clean.jsonl (7,346 records)
```

## Pipeline Bug Fix

**File**: `sandbox/scripts/batch_parse_muas_v6.py` line 146

**Before**: `success: True` (unconditional)

**After**: Validation gate checks `doc.parse_success AND has_content`. A parse that returns no material, no rationale, AND no application is now `success=False`.

## Raw Data Sources

| Source | Path | Records | Role |
|--------|------|---------|------|
| v6_parsed | `C:\BoundState\data\mua_v6_parsed_results.jsonl` | 13,786 | Primary extraction |
| v6_cleaned | `C:\BoundState\data\mua_v6_cleaned.jsonl` | 6,370 | Structured enrichment |
| historic_mua | `C:\maptis-nlp\mira\databases\mua_faiss_db\historic_mua.jsonl` | 9,058 | v5 material backfill |
| rag_precedents | `C:\BoundState\data\mua_rag_precedents\metadata.jsonl` | 4,120 | FAISS semantic index |
| **merged** | **`C:\BoundState\data\mua_merged_clean.jsonl`** | **7,346** | **Canonical for audit** |

## Key Scripts

| Script | Purpose |
|--------|--------|
| `scripts/mua_merge_and_reprofile.py` | This script: merge, filter, profile, sample |
| `scripts/mua_phase1_profile.py` | Original profiling (superseded) |
| `scripts/mua_diagnose_missing_materials.py` | Ghost diagnosis |
| `sandbox/scripts/batch_parse_muas_v6.py` | v6 extraction pipeline (bug fixed) |
| `mira/miul/mua_parser_v6.py` | Core parser with confidence calculation |
