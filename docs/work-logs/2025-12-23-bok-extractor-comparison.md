# BOK Extractor Architecture Review & Design Convergence

**Date:** 2025-12-23
**Authors:** Claude Opus 4.5, Claude Desktop, Frans, Dr. Joseph Wilde
**Status:** Architecture decided - implementing 2-stage pipeline

---

## Executive Summary

Compared V6, V7, V8, and V9 BOK extractors. Found that V7/V8 are over-fitted to Sandia H2 table formats. Converged on a **stable core extractor + pluggable domain interpreters** architecture.

**Key Mantra:**
> Extract structure faithfully → map semantics via validated model → derive deterministically → fail loudly when safety signal is missing.

---

## The Core Problem

Sandia H2 BOK tables don't label "HEE" or "embrittlement" anywhere. The data is **implicit**:

```
Cell contains:     69 MPa He     RA column:    78
                   69 MPa H2                   71

Embrittlement = 71/78 = 0.91
```

This requires **semantic understanding**, not pattern matching.

Additionally:
- H2 renders as "H\n2" in PDF extraction (subscript split)
- V6 (LLM-based) and V7 (pdfplumber) both produced 0 HEE records initially
- Building a "Sandia parser" is useless - we need **core BoundState extractor** that generalizes

---

## Test Results

Tested on: `technical reference for hydrogen.pdf` (Sandia SAND2012-7321)

| Metric | V7 (patched3a) | V8 |
|--------|----------------|-----|
| Tables | 149 | 149 |
| Total records | 633 | 652 |
| HEE/Embrittlement records | 72 | 155 |
| API calls | 0 | 0 |

V8 extracts 2x more embrittlement records due to better paired-cell parsing.

---

## Why V7/V8 Failed as Core Tech

Hardcoded domain patterns that won't generalize:

```python
# Hardcoded for Sandia H2 format
ENVIRONMENT_COL = [r"test\s*environment", r"environment"]
SIGMA_S_COL = [r"σ", r"sigma", r"\bnts\b", r"notched\s*tensile"]
RA_COL = [r"\bra\b", r"reduction\s*of\s*area", r"ductility"]

def _find_env_index(envs, kind):  # Looks for "he" vs "h2"
def normalize_environment_lines():  # Fixes "H" + "2" PDF splits
```

Will fail on:
- O2 BOK documents (different structure)
- Other H2 sources (NASA, DoE, Red River)
- Future domains

---

## Decided Architecture: 2-Stage Pipeline

### Stage 1: Generic Table Extraction (core infrastructure, stable)

**Goal:** Produce a *faithful table grid* and evidence, **not** domain meaning.

**Output Schema: TableGrid** (not dict-by-header)
- Why: dict-by-header breaks on duplicate headers, multi-row headers, blank headers, spanning headers
- Cells with (row, col, text)
- header_rows indicator
- context_text (nearby captions)

**Evidence must include:**
- PDF path, page index/number
- Rendered page image path
- Table bbox/cell bbox (optional)
- Nearby caption/context text

**Backends (swappable):**
- pdfplumber backend (good when PDF has clean text/structure)
- Vision backend (source of truth when structure is ambiguous)
- Optional future backends (camelot/tabula/line-detection)

### Stage 2a: Semantic Mapping (shared)

Column meaning from validated semantic tagger / ontology mapping (NOT regex guessing).

Ontology tags:
- material.identifier
- environment.gas / environment.pressure / environment.temperature
- mechanical.ra
- mechanical.notched_tensile_strength OR mechanical.uts
- o2.ait / flammability ratings

### Stage 2b: Domain Interpreter (pluggable per twin/domain)

**H2 interpreter:**
- Find paired baseline vs H2 rows (via semantics)
- Compute derived safety metrics deterministically:
  - embrittlement_index = RA(H2)/RA(baseline)
  - nts_ratio = Strength(H2)/Strength(baseline)

**O2 interpreter:**
- Extract/normalize AIT, MIE, ratings (domain-specific)

**Future domains:** Add another interpreter; core extractor stays unchanged.

### Stage 3: Validation Gates (non-negotiable)

Runs must **FAIL LOUDLY** if safety-critical outputs aren't produced.

Example for H2 twin:
- Require at least one of embrittlement_index or nts_ratio with evidence

Must output diagnostics:
- "We extracted N tables but semantic mapping didn't find env.gas"
- "Baseline not detected"
- "RA/strength missing"

---

## V9 Analysis

**Good direction:**
- Separation of extraction philosophy from domain logic
- Using vision API to handle tables
- Generic prompt: "Read this table. Return exactly what you see."

**Structural issues to fix:**
- V9 emits rows as dict(header->value) -> will silently drop/merge columns in real-world tables
- V9 relies on pdfplumber find_tables() for bboxes -> brittle for scans/OCR geometry
- V9 lacks run-level "safety signal required" validation gates

---

## Why Not Just Use Vision?

If the PDF is image-based (scans), pdfplumber is often not reliable for tables.

With FineReader OCR:
- OCR text layer is great for page scouting/routing
- But OCR-only table structure is still brittle

**Best approach: vision-first for table grids**, OCR/text for scouting, with cost control:
- Haiku default
- Sonnet fallback only on low-confidence pages/tables

> "Regex doesn't really work, why fuck with it when we can just use vision?"
> Correct. Cost of debugging regex for every new doc format > cost of vision API.

---

## pdfplumber vs Vision Decision Matrix

| Option | Pro | Con |
|--------|-----|-----|
| pdfplumber | Free, fast | May fail on weird layouts |
| Vision | Handles anything | ~$3/doc |
| Hybrid | Best of both | More code |

**Action:** Test pdfplumber on a Red River sample PDF to see if it handles their format.

---

## Grok's Data Was Fake

The embrittlement_index: 1.2 for 316L that Grok provided was **simulated from training data**, not extracted from the PDF. Actual 304L data from Sandia: 0.91 (RA: 78% -> 71%).

**Don't trust LLM "extractions" without provenance.**

---

## Files

Current extractors in mira/knowledge_twins/:
- bok_extractor_v7.py - patched3a with HEE extraction (domain-specific, works but brittle)
- bok_extractor_v8.py - enhanced paired comparison (domain-specific, works but brittle)

In maptis-nlp/:
- bok_extractor_v9.py - vision-based generic extractor (ready to refactor)

POC Package:
- boundstate_bok_vision_core_poc.zip - generic pipeline with vision-first TableGrid

---

## Next Steps

1. **Refactor V9 output schema -> TableGrid**
   - Cells with (r,c,text), header_rows, context_text, evidence refs

2. **Make extractor backend strategy-based**
   - Keep pdfplumber bbox extraction when it works
   - Add fallback: page-level vision table detection when pdfplumber misses

3. **Plug in semantic mapping**
   - Connect to validated tagger (no header regex)

4. **Implement interpreters**
   - interpreters/h2.py for H2 twin derived indices
   - interpreters/o2.py for O2 twin outputs

5. **Add validation gates + diagnostics**
   - Fail run if 0 safety-critical outputs

6. **FineReader OCR workflow**
   - Decide standardized output format
   - PDF with hidden text layer, or PDF + OCR geometry artifact (hOCR/ALTO/XML)

7. **Get Red River sample PDF**
   - Test if pdfplumber captures structure
   - Decide pdfplumber-only vs vision-first

---

## Open Decision Points

- **Bedrock-only vs Anthropic direct:** Pick one transport for production; keep adapter layer
- **FineReader export format:** hOCR/ALTO/XML improves evidence alignment + QA

---

## Commands to Resume

```bash
# Test v9 on Sandia (needs ANTHROPIC_API_KEY)
python bok_extractor_v9.py "technical reference for hydrogen.pdf" -o sandia_raw.json

# Compare v8 (regex) output
python bok_extractor_v8.py "technical reference for hydrogen.pdf" --gas H2 -o sandia_v8.json
```
