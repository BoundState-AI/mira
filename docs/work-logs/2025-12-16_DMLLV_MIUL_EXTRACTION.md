# DMLLV MIUL Extraction - Lessons Learned

**Date:** 2025-12-16
**Author:** Claude Opus 4.5 + Dr. Joseph Wilde
**Status:** RESOLVED

## Problem Statement

Need to extract a complete MIUL (Material Identification Usage List) from DMLLV 10-inch valve engineering drawings with:
- Correct NHA (Next Higher Assembly) tree structure per SLS PIRD Appendix F
- ALL materials including fasteners, screws, bearings, helicoils
- Proper Parent/Index hierarchy for MAPTIS import

## Troubles Encountered

### 1. NHA Structure Was Wrong
**Initial output:** All rows had `Parent=0` (flat structure) and empty `NHA` column.

**Root cause:** Misunderstanding of MIUL spec. The NHA column is NOT the parent drawing number - it's the **MIUL acronym** for tree nodes.

**Per SLS PIRD Appendix F:**
- `Index`: Sequential 1, 2, 3... ending with -1 (terminator)
- `Parent`: Points to **Index** of parent row (NOT drawing number)
- `NHA`: MIUL acronym (e.g., "DMLLV") for tree nodes, **BLANK** for subparts

### 2. BoundState MIULWorkflow Failed
Tried using `C:\BoundState\mira\miul\workflow.py` but got:
```
TypeError: HaikuBOMExtractor.extract_drawing_info() takes 2 positional arguments but 3 were given
```
- Only extracted 39 drawing placeholders
- 0% material coverage
- No fasteners/hardware extracted

**Root cause:** The `msfc/extractor.py` is designed for single-drawing analysis (title block + helical inserts), NOT full BOM parts list extraction.

### 3. Missing Fasteners and Hardware
Initial extractions missed:
- NAS screws (NAS1351, NAS1352)
- NAS washers (NAS1149E)
- McMaster parts (98380A542, 97345A624)
- Bearings (51109, 6915, 6824)
- Retaining rings (WSM-137-C86, WHM-244-S86)

## Solution: Standalone Parser

Created `c:\maptis-nlp\dmllv_miul_parser.py` with:

### Architecture
1. **Text extraction** via PyPDF2 (no vision needed for these drawings)
2. **Claude Sonnet 4.5** via AWS Bedrock GovCloud for intelligent JSON extraction
3. **Full parts list parsing** from ENGINEERING PARTS LIST tables
4. **Drawing Tree extraction** for assembly hierarchy
5. **MIUL tree builder** with correct Index/Parent/NHA structure

### Key Code Fix for NHA
```python
def to_miul_dataframe(self, miul_acronym: str = "DMLLV") -> pd.DataFrame:
    """Per SLS PIRD Appendix F:
    - Tree nodes (MER assemblies) get MIUL acronym in NHA column
    - Subparts (fasteners, hardware) get BLANK NHA but have Parent index
    """
    for part in self.all_parts:
        is_tree_node = part.part_number.startswith("MER")
        nha_value = miul_acronym if is_tree_node and part.parent > 0 else ""
        # ...
```

## Final Results

**Output:** `C:\maptis-nlp\data\DMLLV_MIUL_final.xlsx`

| Metric | Value |
|--------|-------|
| Total Parts | 85 |
| MER Assemblies | 39 |
| Fasteners/Hardware | 46 |
| Unique Materials | 15 |

### Materials Extracted
- A286 (31 parts) - aerospace superalloy
- 316 SST (10 parts) - stainless steel
- INCONEL 718 (6 parts) - nickel alloy
- 18-8 SST (6 parts) - stainless steel
- 302 SST (5 parts) - stainless steel
- 7075-T6 AL (4 parts) - aluminum
- Si3N4 (4 parts) - silicon nitride ceramic (bearings)
- BRONZE (3 parts)
- VESPEL SP-21 (2 parts) - polyimide
- PCTFE, INCONEL, etc.

### Hardware Extracted
- NAS screws: NAS1351N4-20, NAS1352N4-12, NAS1352N4-14, NAS1352N5-12
- NAS washers: NAS1149E0432R, NAS1149E0532R
- McMaster: 98380A542, 97345A624, 95878A310, 9713K64, 9713K94, 97022A388
- Retaining rings: WSM-137-C86, WHM-244-S86
- Bearings: 51109, 6915, 6824, 16007

### Verified NHA Structure
```
MER Assemblies (38 with NHA='DMLLV'):
  Index=2, Parent=1, NHA=DMLLV  (MER07543-001)
  Index=3, Parent=1, NHA=DMLLV  (MER07550-001)
  Index=4, Parent=1, NHA=DMLLV  (MER07570-001)
  ...

Fasteners (46 with blank NHA):
  Index=40, Parent=1, NHA=''    (98380A542)
  Index=45, Parent=1, NHA=''    (NAS1351N4-20)
  ...
```

## Comparison: Three Extractors

### Head-to-Head Results

| Metric | `dmllv_miul_parser.py` | `dmllv_bom_to_miul.py` | `msfc/extractor.py` |
|--------|------------------------|------------------------|---------------------|
| **Location** | `c:\maptis-nlp\` | `src/parsers/` | `C:\BoundState\mira\miul\msfc\` |
| **Model** | Sonnet 4.5 (text) | Sonnet 4.5 (Vision) | Haiku (vision fallback) |
| **Total Rows** | 85 | 90 | N/A |
| **Tree Nodes** | 38 | 45 | N/A |
| **Hardware Items** | 47 | 45 | N/A |
| **Unique Materials** | 18 | 23 | N/A |
| **Full Parts List** | ✓ | ✓ | ✗ |
| **Material Specs** | Partial | Full (UNS, AMS) | ✗ |
| **Intermediate JSON** | ✗ | ✓ | ✗ |
| **Cost** | Medium | Higher | Lower |

### Key Differences

**`dmllv_bom_to_miul.py` (RECOMMENDED)**
- Uses Claude Vision to directly read drawing images
- Two-step pipeline: PDF → JSON → Excel
- Extracts **full material specifications** (e.g., "A286 CRES, UNS S66286, PER SAE AMS 5737")
- Intermediate JSON allows inspection and manual edits
- Recursive tree building handles nested assemblies
- Auto-detects metal vs non-metal for rating columns

**`dmllv_miul_parser.py` (Legacy)**
- Text extraction via PyPDF2 first, then LLM parse
- Single-step: PDF → Excel
- Simpler material extraction (designation only)
- Fixed NHA column issue resolved here

**`msfc/extractor.py` (Single Drawing)**
- Designed for title block + helical insert extraction
- Not suitable for full BOM extraction
- Use only for per-drawing analysis

## Recommendations

1. **Use `src/parsers/dmllv_bom_to_miul.py`** for DMLLV BOM extraction (BEST)
   ```bash
   py src/parsers/dmllv_bom_to_miul.py full "C:\maptis-nlp\data\DMLLV BOM"
   ```
2. **Keep `dmllv_miul_parser.py`** as backup for text-extractable PDFs
3. **Use `msfc/extractor.py`** only for single-drawing analysis
4. **Always verify NHA structure** against SLS PIRD Appendix F before import
5. **Check for fasteners** - they're easy to miss but critical for material certification

## Files

### Outputs
- **Best MIUL:** `C:\maptis-nlp\data\DMLLV BOM\DMLLV_MIUL_Generated.xlsx` (90 rows, vision parser)
- **Backup MIUL:** `C:\maptis-nlp\data\DMLLV_MIUL_final.xlsx` (85 rows, text parser)
- **Intermediate JSON:** `C:\maptis-nlp\data\DMLLV BOM\DMLLV_BOM_extracted.json`

### Parsers
- **Recommended:** `c:\maptis-nlp\src\parsers\dmllv_bom_to_miul.py`
- **Legacy:** `c:\maptis-nlp\dmllv_miul_parser.py`
- **Single-drawing:** `C:\BoundState\mira\miul\msfc\extractor.py`

### Reference
- **MIUL Spec:** `C:\Users\jwilde2\Documents\MIUL.pdf` (SLS PIRD Appendix F)
