# Work Log: 2026-02-28

## Session Focus
- Audit the PostgreSQL `mira_h2` database (`h2_knowledge` schema) to understand its role relative to the existing JSON-based H2 engine.
- Identify data gaps — what Sandia data exists on disk vs what was actually loaded into PG.
- Fix any loader issues preventing complete ingestion.

## Context

### Data Flow (current)
```
Sandia XLSX (9 files, E:/BoundState/data/H2/)
    ↓ h2_excel_parser.py
Intermediate JSON (h2_corpus_merged.json, h2_degradation_ratios.json)
    ↓ h2_pg_loader.py
PostgreSQL mira_h2 → h2_knowledge schema (127.0.0.1:55433)
```

The live H2 engine (`engine_simple.py`) runs off a separate flat file (`h2_evidence_merged.json`, 371 HEE records from 3 sources). The PG database holds structured Sandia test data — a complementary dataset with quantitative property values, compositions, and degradation ratios that the JSON evidence file doesn't have.

### PG Database Tables
| Table | Purpose |
|-------|---------|
| `materials` | Master material records — alloy identity, composition (JSONB), base tensile properties |
| `property_records` | Individual test records — fracture toughness (KIC, JIC), tensile, fatigue crack growth — in reference gas vs H2 |
| `degradation_ratios` | Pre-computed H2/reference ratios — the quantitative embrittlement signal |
| `training_pairs` | 309 Q&A pairs for fine-tuning the H2 model (`ft:gpt-4.1-2025-04-14:boundstate:mira-h2-v7b-balanced:DCXuyfKW`) |
| `dataset_manifest` | Provenance tracking — which datasets loaded, SHA256 hashes, row counts |
| `coverage_gaps` | Materials the engine couldn't answer — tracked for future data collection |

## Bug Found: Material Key Collisions

### Problem
`material_key_from_entry()` in `h2_pg_loader.py` hashed `name|form|temper|source_doc` to generate the primary key. Since all 9 XLSX files share `source_document=SAND2012-7321`, materials that appear in multiple microstructure-variant XLSX files (e.g., X42 base vs X42 banded ferrite-pearlite) produced **identical keys**. The `ON CONFLICT DO UPDATE` for materials silently overwrote, and `ON CONFLICT DO NOTHING` for property_records silently dropped the duplicates.

### Impact
| Alloy | XLSX files | Unique keys (before) | Records lost |
|-------|-----------|---------------------|-------------|
| 7475 | 1 | 1 | 0 |
| 4130X | 2 (base + tempered martensite) | 1 | 1 entry |
| X42 | 2 (base + banded ferrite-pearlite) | 1 | 1 entry |
| X80 | 3 (acicular ferrite + skelp + polygonal) | 1 | 2 entries |
| X60 HIC | 1 | 1 | 0 |

**4 material entries and 17 property records were silently dropped.**

### Fix Applied
**File:** `E:\BoundState\data\H2\h2_pg_loader.py`, line 280-288

Added `source_file` to the material key hash so microstructure variants get distinct keys:

```python
# Before
key = f"{common}|{form}|{temper}|{src_doc}".lower()

# After
src_file = norm(str(entry.get("source_file", "")))
key = f"{common}|{form}|{temper}|{src_doc}|{src_file}".lower()
```

### Result After Reload (`--truncate`)
| Table | Before | After | Delta |
|-------|--------|-------|-------|
| materials | 5 | **9** | +4 microstructure variants recovered |
| property_records | 24 | **41** | +17 test records recovered |
| degradation_ratios | 22 | 22 | Correctly deduplicated (same numerical values across variants) |
| training_pairs | 309 | 309 | Unchanged |
| coverage_gaps | 37 | 37 | Unchanged |

## Sandia Data Coverage

All 9 XLSX files from `E:\BoundState\data\H2\` are now fully loaded:

| XLSX File | Material | Form | Temper |
|-----------|----------|------|--------|
| aluminum.xlsx | 7475 | plate | T7351 |
| low alloy ferritic steels.xlsx | 4130X | vessel | Q&T |
| low alloy ferritic steels tempered martinsite.xlsx | 4130X | vessel | Q&T |
| plain carbon ferritic steels.xlsx | X42 | line pipe | — |
| plain carbon ferritic steels banded ferrite pearlite.xlsx | X42 | line pipe | — |
| plain carbon ferritic steels fine acicular ferrite.xlsx | X80 | skelp | — |
| plain carbon ferritic steels fine acicular ferrite skelp.xlsx | X80 | skelp | — |
| plain carbon ferritic steels fine polygonal acicular ferrite.xlsx | X80 | skelp | — |
| plain carbon ferritic steels fine polygonal skelp ferrite.xlsx | X60 HIC | skelp | — |

All source data is from **SAND2012-7321** (Sandia Technical Reference for Hydrogen Compatibility of Materials).

Note: The full SAND2012-7321 report covers many more alloy families (austenitic stainless, nickel alloys, titanium, copper, etc.) but the parsed XLSX files only cover plain carbon ferritic steels, low alloy ferritic steels, and one aluminum alloy. Additional alloy families would require sourcing and parsing additional Sandia chapters.

## Gas Compatibility Page Status

Earlier in this session, the Gas Compatibility page (`GasCompatibility.tsx`) was rewritten with the full E: drive feature set:
- Condition Compare table (grid showing conditions with HEE band, verdict, evidence count)
- Known Conditions dropdown with Apply button
- Condition Alias Review panel (amber panel for unresolved condition labels)
- H2/He Decision Band card
- Engineering Review card
- Condition Clarification card

API types updated in `api.ts` to support condition alias management (`H2ConditionAliasRecord`, `H2ConditionAliasListResponse`, etc.).

Build verified clean (TypeScript + Vite).

## Remaining Work

### 1. Wire PG quantitative data into Gas Compatibility UI
The PG `property_records` and `degradation_ratios` tables have actual test values (KIC = 174 MPa-sqrt-m in N2 vs 104 in H2, 40% degradation). Currently the Gas Compat page only shows qualitative HEE band verdicts. Surfacing the quantitative ratios would give engineers the numbers they need.

### 2. Decide on Knowledge Twins vs Gas Compatibility merge
KT has a unique "Ask a Question" NL query mode not present in Gas Compat. Options:
- Fold "Ask" into Gas Compat as a 4th tab
- Keep both pages with distinct purposes (Gas Compat = structured evaluation, KT = free-form NL query)

### 3. Expand Sandia XLSX coverage
Only 3 alloy families parsed (plain carbon ferritic steels, low alloy ferritic steels, aluminum). The full SAND2012-7321 report covers 10+ families. Additional XLSX files would need to be created from the remaining Sandia chapters.

### 4. Connect PG to live H2 engine
Currently the H2 engine (`engine_simple.py`) reads `h2_evidence_merged.json` (371 HEE records). The PG data is a parallel structured dataset. Options:
- Query PG directly from the engine as a secondary data source
- Export PG data to augment the JSON evidence file
- Use PG as the authoritative source and deprecate the JSON file

### 5. Training pipeline integration
The 309 training pairs and 37 coverage gaps in PG feed the fine-tuned model. A workflow to:
- Re-run coverage gap detection after adding new evidence
- Generate new training pairs from newly parsed Sandia data
- Trigger fine-tuning retrains
would close the model improvement loop.

## Net Status
- PG database is now fully loaded with all available Sandia data (9/9 XLSX files).
- Material key collision bug fixed — no more silent data loss on reload.
- Gas Compatibility page wired up with full H2 feature set.
- Main remaining work is connecting the PG quantitative data to the frontend and expanding alloy coverage.
