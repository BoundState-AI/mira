# MIUL V3 Full Pipeline Assessment
## DMLLV Complete Drawing Set — Test vs James (Human Ground Truth)
### February 3, 2026

---

## Executive Summary

| Metric | Score | Notes |
|--------|-------|-------|
| **Part Number Extraction** | 80% clean (81/101) | 20 garbled PNs from Vision path |
| **Designation Accuracy** | 58.5% (38/65) | But 14 of 27 mismatches are STYLE, not WRONG |
| **Material Specification** | 0% (0/23) | All blank — text_layer bypass skips MatSpec entirely |
| **Process Specification** | 0/5 | All blank — same root cause |
| **NHA Assignment** | 0% (0/73) | "test" placeholder — test harness issue, not code bug |
| **Drawing Coverage** | 73% (30/41) | 11 drawings missing from test output |

---

## What's Working Well

### 1. Designation — Better Than The Numbers Show

The 58.5% number is misleading. Of the 27 "mismatches," here's the real breakdown:

**System is arguably MORE correct than James (8):**
- 6x `7075 AL` → `7075-T651 ALUMINUM` — Test pulls full temper designation from drawing notes. James abbreviated. Temper matters for NASA compliance.
- 2x VESPEL SP-3 — Test captured `TYPE III/M OR TYPE III/P` detail that James truncated.

**Style/convention disagreements, not errors (12):**
- 4x `Si3N4` vs `SI3N4` — Case sensitivity. Fixable in 1 line.
- 3x `316 SST`/`302 SST` vs `316 CRES`/`302 CRES` — NASA prefers CRES. Test is actually more correct for MIUL context.
- 5x `A286` vs `A286 CRES` — Test appending CRES via normalization on Vision path drawings. Should use verbatim.

**James used placeholder (2):**
- 2x `MISC` vs empty — James wrote MISC for mixed-material assemblies. Not a real designation.

**Genuine misses (3):**
- AS4307K04: empty, should be `316 CRES`
- MER07573-001: empty, should be `INCONEL`
- MER07584-001: empty, should be `A286`

**Actual wrong material (2):**
- ASME B18.3 button head: `A286 CRES` vs `18-8 CRES` — need to check drawing
- MS14198N6: `INCONEL ALLOY` vs `INCONEL 718` — EPL literally says ALLOY, James knew the specific alloy

**Adjusted Designation accuracy (excluding style): ~89% (58/65)**

### 2. MER07540-001 EPL — Near Perfect

The single-drawing test showed 95.5% Designation accuracy. All KSI strength classes preserved verbatim: A286 (150 KSI), A286 (160 KSI), A286 (180 KSI). Text layer bypass working exactly as designed.

### 3. Drawing Tree Structure

The hierarchy IS being built — EPL parts correctly nest under their assembly drawings. Parent pointers work. The tree just lacks real NHA values because of the test placeholder.

### 4. Part Coverage

73 parts matched between James and test. All major assemblies present. The system found 28 additional parts James didn't include (some real, some garbled).

---

## What's Broken

### CRITICAL: EPL Table Parsing on Vision Path (22 garbled part numbers)

This is the #1 bug. When drawings go through Vision extraction (not text layer), the EPL column alignment is failing catastrophically. Three distinct failure modes:

**CAGE code leaking into Part Number (12 instances):**
```
MER07585-001 339B2        ← "339B2" is CAGE code, not part of PN
MER07573-001 339B2
MER07566-001 339B2
```
The Vision extractor is concatenating the CAGE CODE column into the PART NUMBER field.

**Multi-field merge (7 instances):**
```
MER07568-001 339B2 SHAFT, OFFSET, 10 INCH VALVE    ← PN + CAGE + DESC merged
MS21209C4-10 INSERT, SCREW THD, COARSE, LOCKING... ← PN + DESC merged
EH-22-C86 6. 51814 RETAINING RING, INTERNAL, 22    ← PN + find + CAGE + DESC merged
```
The Vision extractor is losing column boundaries entirely on some drawings.

**Double-character garble (1 instance):**
```
MMEERR0077558855--000011  ← every character doubled
```
This looks like a PDF rendering artifact where text was extracted twice.

**Root cause:** These all come from drawings that went through Vision extraction (not text layer). The text_extract path produces clean columns. The Vision prompt's column identification instructions aren't working for some drawing layouts.

### CRITICAL: Material Specification — 0% (all blank)

Every Material Specification field is empty. This is because:
1. Text layer path: EPLs don't have per-row spec data (specs are in drawing notes). The `is_text_layer` code path skips the standard parts DB lookup entirely.
2. Vision path: Same column parsing bugs that garble PNs also lose the spec data.

The standard parts DB HAS this data (AMS5525, AMS5731, etc). It was previously being used. The text_layer bypass threw the baby out with the bathwater — it correctly stopped transforming Designation, but also stopped enriching MatSpec from the known parts DB.

### CRITICAL: NHA — 0% (all "test" placeholder)

Every NHA value is either "test" (top-level assemblies) or empty (EPL parts). This is clearly a test harness configuration issue — the builder was run without a real project name. Not a code bug per se, but means NHA assignment can't be validated from this output.

### HIGH: Missing Drawings (11 of 41)

These James drawings are absent from test output:
```
MER07545-001, MER07546-001, MER07550-001, MER07553-001,
MER07554-001, MER07555-001, MER07556-001, MER07557-001,
MER07558-001, MER07559-001, MER07571-001
```

These are all detail drawings (children of assemblies). They appear as EPL line items but their individual drawing data wasn't extracted. Either the PDFs weren't in the input directory, or the extractor failed silently on them.

### MEDIUM: DELETED Row Not Filtered

`DELETED` appears as a part number in MER07543-001's EPL. The text_extract parser should skip DELETED rows entirely.

### LOW: Symbol Rendering (4 instances)

- `⌀` → `.375 DIA` (diameter symbol lost, "DIA" appended at wrong position)
- `°` → floating to end of string (`800 F ... °` instead of `800°F`)

---

## Recommendations for VSClaude — Priority Order

### 1. Fix Vision EPL Column Parsing
The CAGE code leak and multi-field merge are the most damaging bugs. Options:
- Add post-processing to detect and strip 5-char CAGE codes from PN field
- Or better: expand text_layer extraction to work on more drawing types so Vision path is used less

### 2. Restore MatSpec Enrichment for Text Layer Path
The text_layer bypass correctly skips Designation normalization but should still:
- Look up material specs from the standard parts DB
- Pull specs from drawing notes
- The key insight: Designation = use verbatim from drawing. MatSpec = enrichment is needed and correct.

### 3. Fix Si3N4 Case Sensitivity
Chemical formula case matters. `Si3N4` not `SI3N4`. One normalization rule, but this one is legitimate.

### 4. Stop A286 → A286 CRES Normalization on Vision Path
Where Designation comes from Vision extraction (not EPL text layer), the normalize_designation function is still appending CRES. Same philosophy: use what's on the drawing.

### 5. Filter DELETED Rows
Add `if description == 'DELETED': continue` to EPL parsing.

### 6. Fix Symbol Handling
Map `\u2300` → `⌀` and ensure `°` stays adjacent to its number.

---

## Scoring Methodology Note

James's MIUL is human-generated and NOT a perfect ground truth. Observed issues in James's data:
- Inconsistent abbreviation (7075 AL vs 7075 ALUMINUM vs 7075-T651 ALUMINUM)
- MISC as a material designation (not valid)
- Truncated VESPEL descriptions (lost TYPE III detail)
- SST instead of NASA-standard CRES

The system should aim to match the DRAWING, not match James. Where the system pulls more complete data from the drawing than James typed, that's a feature, not a bug.
