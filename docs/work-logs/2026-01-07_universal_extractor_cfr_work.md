# Work Log: Universal Extractor & CFR Pipeline Development
**Date**: January 7, 2026
**Session**: Continuation from January 6, 2026
**Author**: Claude Code (Opus 4.5)
**Cost**: ~$54.71 (previous session) + ongoing

---

## Executive Summary

Multi-day development session focused on:
1. Universal document triage pipeline (v3)
2. BOK ultimate extraction pipeline with schema discovery
3. CFR (Code of Federal Regulations) XML extraction as control test
4. Schema discovery fixes for diverse corpora
5. Single-file extraction mode implementation

---

## Files Created/Modified

### Python Scripts

| File | Location | Purpose | Status |
|------|----------|---------|--------|
| `universal_triage_v3.py` | `C:\BoundState\sandbox\scripts\` | Discovery-first document triage | Complete |
| `bok_ultimate_extract_1.py` | `C:\BoundState\sandbox\scripts\` | Original extractor | Base version |
| `bok_ultimate_extract_1_5.py` | `C:\BoundState\sandbox\scripts\` | Added CLI flags | Intermediate |
| `bok_ultimate_extract_1_6.py` | `C:\BoundState\sandbox\scripts\` | Fixed global syntax error | Intermediate |
| `bok_ultimate_extract_1_7.py` | `C:\BoundState\sandbox\scripts\` | Added --file, --output-dir, single-file mode | **Current** |
| `cfr_extractor.py` | `C:\boundstate_backup\` | Purpose-built CFR extractor (pre-existing) | Control |

### Databases

| Database | Location | Contents | Records |
|----------|----------|----------|---------|
| `o2_h2_triage.db` | `C:\BoundState\sandbox\scripts\triage_output\` | 46 H2/O2 BOK PDFs/DOCX triage results | 46 docs |
| `o2_h2_ultimate.db` | `C:\BoundState\sandbox\scripts\bok_ultimate_output\` | H2/O2 BOK extraction results | 6,248 records |
| `triage.db` | `C:\boundstate_backup\cfr_triage\` | 11 CFR XML files triage | 11 docs |
| `ultimate.db` | `C:\BoundState\sandbox\scripts\bok_ultimate_output\` | CFR extraction (via auto mode) | 264 records |
| `ultimate.db` | `C:\boundstate_backup\cfr_extracts\` | Single-file CFR extraction | **In progress** |

### JSON Schema Files

| File | Location | Doc Family |
|------|----------|------------|
| `regulatory_code_schema_v1.json` | `C:\BoundState\sandbox\scripts\bok_ultimate_output\schemas\` | regulatory_code (empty - 0 record types) |
| `single_22-CFR-121-usml_schema_v1.json` | `C:\boundstate_backup\cfr_extracts\schemas\` | single-file schema (in progress) |

### Output JSON Files

| File | Location | Purpose |
|------|----------|---------|
| `cfr22_120_sections.json` | `C:\boundstate_backup\cfr_extracts\` | Purpose-built CFR extractor output (488 items) |
| `22-CFR-121-usml_extraction.json` | `C:\boundstate_backup\cfr_extracts\` | Universal extractor single-file output (in progress) |

---

## Functions Implemented/Modified

### bok_ultimate_extract_1_7.py

#### New Functions

1. **`run_single_file(file_path: Path, output_dir: str = None)`** (Lines 1770-1994)
   - Process single file without triage database
   - 3-phase pipeline: Scan → Build Schema → Extract
   - Saves to custom output directory
   - Creates per-file schema automatically

#### Modified Functions

2. **Argparse additions** (Lines 2058-2059):
   ```python
   parser.add_argument("--output-dir", type=str, help="Path to output directory")
   parser.add_argument("--file", type=str, help="Process single file directly")
   ```

3. **Single-file dispatch** (Lines 2315-2325):
   ```python
   if args.file:
       file_path = P(args.file)
       asyncio.run(run_single_file(file_path, args.output_dir))
   ```

4. **Record type aggregation fix** (Lines 1831-1878):
   - Added defensive handling for string vs dict record types
   - Fixed field name mismatches: `trigger_pattern` not `trigger`, `field_type` not `type`, `sample_verbatim` not `sample`

---

## Problems Encountered & Solutions

### Problem 1: Empty Schema for Regulatory Code
**Symptom**: Schema had `record_types: []` for CFR documents
**Root Cause**: 40% frequency threshold too high for diverse corpora where each CFR part has unique record types
**Solution**: Oracle consultation recommended morphology-aware grouping via `schema_scope_key`

### Problem 2: Global Declaration Syntax Error
**Symptom**: `SyntaxError: name 'TRIAGE_DB' is assigned to before global declaration`
**Root Cause**: `global` statement after assignment in if block
**Solution**: Removed global declarations (not needed at module level under `if __name__ == "__main__"`)

### Problem 3: CFR Extractor Crash
**Symptom**: `FileNotFoundError: D:\BoundState\packs\itar\extracts`
**Root Cause**: Hardcoded output path to non-existent drive
**Solution**: Added `--output-dir` flag to specify valid path

### Problem 4: AttributeError in Single-File Mode
**Symptom**: `AttributeError: 'str' object has no attribute 'get'`
**Root Cause**: Model returning record_types as strings instead of dicts
**Solution**: Added defensive type checking and conversion

---

## Oracle Consultation Results

### Participants
- **Gemini** (Google)
- **Grok** (xAI)
- **Fran** (Internal)
- **VSClaude** (VS Code)

### Consensus Recommendations
1. Fix `schema_scope_key` computation in triage to include `structured_content_types`
2. Use cascading fallback: `document_type` → `schema_scope_key` → per-file schemas
3. Lower frequency threshold for diverse corpora (10% vs 40%)

### Implementation Plan (from `jiggly-painting-owl.md`)
```
C:\Users\jwilde2\.claude\plans\jiggly-painting-owl.md
```

Key changes:
1. Add `--group-by` flag: `document_type | schema_scope_key | document_id | file`
2. Cascading fallback in `run_aggregate()`
3. Per-file schema generation as last resort

---

## Extraction Comparison: Purpose-Built vs Universal

### Purpose-Built CFR Extractor (`cfr_extractor.py`)
- **Output**: `cfr22_120_sections.json`
- **Records**: 488 items
- **Fields**: Domain-specific (SME/MTCR flags, obligation_type, usml_category)
- **Pros**: Rich semantic understanding
- **Cons**: Single-purpose, not generalizable

### Universal Extractor (`bok_ultimate_extract_1_7.py`)
- **Output**: `bok_ultimate_output/ultimate.db`
- **Records**: 264 records (via auto mode on 11 CFR files)
- **Record Types**: controlled_article, regulatory_requirement, definition, etc.
- **Pros**: Schema discovery, generalizable
- **Cons**: Lower fidelity without domain-specific prompts

---

## CFR Triage Database Contents

```
C:\boundstate_backup\cfr_triage\triage.db
```

| Document Type | Routing | Count |
|---------------|---------|-------|
| regulatory_code | extract_full | 11 |

Files:
- 22-CFR-120.xml (Definitions)
- 22-CFR-121-usml.xml (USML Categories)
- 22-CFR-122.xml through 22-CFR-130.xml (ITAR Parts)

---

## Pipeline Architecture

```
┌─────────────────┐
│ universal_      │
│ triage_v3.py    │ → triage.db (document_type, domains, routing, schema_scope_key)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ bok_ultimate_   │
│ extract_1_7.py  │
│                 │
│ Modes:          │
│ --auto          │ → Process all families from triage
│ --file          │ → Single-file mode (no triage needed)
│ --scan          │ → Phase 0 only
│ --aggregate     │ → Phase 1+1.5 only
│ --extract       │ → Phase 3 only
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ultimate.db     │ → records, schemas, page_scans, extractions, runs
│ schemas/*.json  │ → Human-readable schema files
│ *_extraction.json │ → Full extraction output (single-file mode)
└─────────────────┘
```

---

## CLI Reference

### Universal Triage
```bash
python universal_triage_v3.py --input-dir "C:\path\to\docs" --output-dir "C:\path\to\output"
```

### BOK Ultimate Extractor
```bash
# Auto mode (all families)
python bok_ultimate_extract_1_7.py --auto

# Single family
python bok_ultimate_extract_1_7.py --auto --family regulatory_code

# Custom triage DB
python bok_ultimate_extract_1_7.py --auto --triage-db "C:\path\to\triage.db"

# Morphology-aware grouping (Oracle fix)
python bok_ultimate_extract_1_7.py --auto --group-by schema_scope_key

# Lower threshold for diverse corpora
python bok_ultimate_extract_1_7.py --auto --min-freq 0.10

# Single file mode (NEW)
python bok_ultimate_extract_1_7.py --file "C:\path\to\file.xml" --output-dir "C:\output"
```

---

## Next Steps

1. **Complete single-file extraction test** on `22-CFR-121-usml.xml`
2. **Compare results** with purpose-built CFR extractor
3. **Implement cascading fallback** in `run_aggregate()` per Oracle recommendation
4. **Add variance detection** for auto-splitting diverse families

---

## Session Cost Tracking

| Phase | Model | Calls | Est. Cost |
|-------|-------|-------|-----------|
| Previous session | Various | Many | ~$54.71 |
| CFR Triage | claude-3-5-sonnet | 11 | ~$0.50 |
| CFR Auto Extraction | claude-3-5-sonnet | ~100 | ~$5.00 |
| Single-file scan (partial) | claude-3-5-sonnet | 2 | ~$0.03 |
| **Total** | | | **~$60.24** |

---

## File Checksums (for verification)

```
bok_ultimate_extract_1_7.py: Modified 2026-01-07
  - Lines: ~2350
  - Key additions: run_single_file(), --file/--output-dir flags

triage.db (cfr_triage): 11 documents
ultimate.db (bok_ultimate_output): 264 records
```

---

*Log generated by Claude Code (Opus 4.5) on 2026-01-07*
