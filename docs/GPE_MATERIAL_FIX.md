# GPE Material Extraction Fix — VSClaude Handoff

## Problem Statement

GPE MIUL extraction produces only 2/67 materials. The pipeline works for NASA D-format drawings (DMLLV: 79 materials) but fails on GPE because CU Boulder uses a different drawing format.

**Two blocking issues, both in `text_extract.py`:**

1. **BOM Table Format** — GPE puts material in a BOM item table, not in `MATERIAL:` note lines
2. **Doubled Characters** — pdfplumber returns `RREEMMOOVVEE` instead of `REMOVE` on GPE PDFs

Both must be fixed. The dedup must run BEFORE the BOM parser, or the parser will fail to match material patterns.

---

## Issue 1: Doubled Character Dedup (Fix FIRST)

### What's Happening

CU Boulder's PDF generator uses overlapping text positioning that pdfplumber interprets as doubled characters. Every character appears twice:

```
Input from pdfplumber:  "RREEMMOOVVEE  AALLLL  BBUURRRRSS"
Should be:              "REMOVE ALL BURRS"

Input from pdfplumber:  "66006611--TT66"
Should be:              "6061-T6"

Input from pdfplumber:  "IITTEEMM  NNOO..  QQTTYY  MMAATTEERRIIAALL"
Should be:              "ITEM NO. QTY MATERIAL"
```

### Detection Logic

Not all GPE PDFs have this issue, and non-GPE PDFs never do. Detect before applying:

```python
def _is_doubled_text(text: str) -> bool:
    """
    Detect if pdfplumber output has doubled characters.
    
    Heuristic: sample several words. If most have repeated char pairs
    (e.g., 'RREE' for 'RE', 'MMAA' for 'MA'), the text is doubled.
    """
    if not text or len(text) < 20:
        return False
    
    # Sample first 200 chars of actual content (skip whitespace-heavy regions)
    sample = ""
    for line in text.split("\n"):
        stripped = line.strip()
        if len(stripped) > 10:
            sample = stripped[:200]
            break
    
    if not sample:
        return False
    
    # Count consecutive repeated character pairs
    # In doubled text: "RREEMMOOVVEE" has pairs RR, EE, MM, OO, VV, EE
    pair_count = 0
    total_pairs = 0
    for i in range(0, len(sample) - 1, 2):
        if sample[i].isalpha():
            total_pairs += 1
            if sample[i] == sample[i + 1]:
                pair_count += 1
    
    if total_pairs < 5:
        return False
    
    # If >70% of character pairs are repeated, it's doubled
    return (pair_count / total_pairs) > 0.7
```

### Dedup Logic

```python
def _dedupe_doubled_text(text: str) -> str:
    """
    Remove doubled characters from pdfplumber output.
    
    "RREEMMOOVVEE  AALLLL  BBUURRRRSS" -> "REMOVE ALL BURRS"
    "66006611--TT66" -> "6061-T6"
    
    Strategy: Take every other character, but handle spaces and 
    punctuation carefully since they may or may not be doubled.
    """
    if not text:
        return text
    
    result = []
    i = 0
    while i < len(text):
        char = text[i]
        
        if i + 1 < len(text) and text[i + 1] == char:
            # Doubled character — take one, skip the duplicate
            result.append(char)
            i += 2
        else:
            # Not doubled — take as-is (handles spaces, newlines,
            # and any single chars that weren't doubled)
            result.append(char)
            i += 1
    
    return "".join(result)
```

### Where to Apply

In `extract_drawing()`, right after extracting text from the page, BEFORE any parsing:

```python
def extract_drawing(pdf_path, ...):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        all_text = page.extract_text() or ""
        
        # --- DEDUP DOUBLED TEXT (GPE/CU Boulder PDFs) ---
        is_doubled = _is_doubled_text(all_text)
        if is_doubled:
            LOGGER.info(f"[TextExtract] Doubled text detected, applying dedup")
            all_text = _dedupe_doubled_text(all_text)
            
            # Also dedup table cell contents
            tables = page.extract_tables()
            tables = _dedupe_tables(tables)
        else:
            tables = page.extract_tables()
        
        # ... rest of extraction continues with clean text ...
```

Table dedup helper:

```python
def _dedupe_tables(tables: list) -> list:
    """Apply doubled-text dedup to all table cell values."""
    cleaned = []
    for table in tables:
        cleaned_table = []
        for row in table:
            cleaned_row = []
            for cell in row:
                if cell and isinstance(cell, str):
                    cleaned_row.append(_dedupe_doubled_text(cell))
                else:
                    cleaned_row.append(cell)
            cleaned_table.append(cleaned_row)
        cleaned.append(cleaned_table)
    return cleaned
```

---

## Issue 2: BOM Table Material Parser

### What GPE Drawings Look Like

GPE detail drawings have a BOM-style item table instead of (or in addition to) NASA-style `MATERIAL:` notes:

```
┌──────────┬─────┬──────────────────┬─────────┐
│ ITEM NO. │ QTY │ MATERIAL         │ LOT-S/N │
├──────────┼─────┼──────────────────┼─────────┤
│ 1        │ A/R │ 6061-T6          │         │
│ 2        │ A/R │ 15-5PH CRES H900 │         │
└──────────┴─────┴──────────────────┴─────────┘
```

The existing `_parse_title_block()` only looks for `MATERIAL:` prefix in note lines. It has zero awareness of table-based material data.

### Where to Add It

In `_parse_title_block()`, add a new section AFTER the existing NASA-format `MATERIAL:` note search. This way NASA-format wins if present, BOM table is the fallback:

```python
def _parse_title_block(tables, full_text, ...):
    tb = {}
    
    # ... existing title block parsing ...
    
    # --- EXISTING: NASA D-format MATERIAL note ---
    # (Already present around line 368-371)
    # Scans for "MATERIAL:" prefix in notes
    # This handles DMLLV and any GPE drawings with NASA-style notes
    
    # --- NEW: BOM TABLE MATERIAL (GPE format) ---
    # Only if we didn't already find material from notes
    if not tb.get("material"):
        bom_material = _extract_bom_material(tables)
        if bom_material:
            tb["material"] = bom_material.get("designation", "")
            if bom_material.get("spec"):
                tb.setdefault("material_spec", bom_material["spec"])
            LOGGER.info(f"[TitleBlock] BOM table material: {tb['material']}")
    
    return tb
```

### BOM Table Extraction Function

```python
def _extract_bom_material(tables: list) -> Optional[dict]:
    """
    Extract material from BOM-style item tables (GPE format).
    
    Looks for tables with headers like:
      ITEM NO. | QTY | MATERIAL | LOT-S/N
    
    Returns:
        {"designation": "6061-T6", "spec": "..."} or None
    """
    for table in tables:
        if not table or len(table) < 2:
            continue
        
        # Find the header row containing MATERIAL column
        material_col_idx = None
        header_row_idx = None
        
        for ri, row in enumerate(table):
            if not row:
                continue
            for ci, cell in enumerate(row):
                cell_text = str(cell).strip().upper() if cell else ""
                # Match "MATERIAL" as a column header
                # But NOT "MATERIAL:" (that's a note, not a table header)
                # And NOT in a row that looks like a note block
                if cell_text == "MATERIAL" or cell_text == "MATERIAL\nSPECIFICATION":
                    # Verify this looks like a BOM header row
                    # Should also have ITEM or QTY nearby
                    row_text = " ".join(str(c).upper() for c in row if c)
                    if any(kw in row_text for kw in ["ITEM", "QTY", "QUANTITY"]):
                        material_col_idx = ci
                        header_row_idx = ri
                        break
            if material_col_idx is not None:
                break
        
        if material_col_idx is None:
            continue
        
        # Extract material values from data rows below the header
        materials_found = []
        for ri in range(header_row_idx + 1, len(table)):
            row = table[ri]
            if ri >= len(table) or not row:
                continue
            if material_col_idx >= len(row):
                continue
            
            cell_val = str(row[material_col_idx]).strip() if row[material_col_idx] else ""
            
            # Skip empty, header-like, or garbage values
            if not cell_val or len(cell_val) < 3:
                continue
            if cell_val.upper() in ("MATERIAL", "N/A", "NONE", "-", "—"):
                continue
            
            # Clean up: remove trailing periods, extra whitespace
            cell_val = cell_val.strip().rstrip(".")
            
            # This is a material designation from the BOM
            materials_found.append(cell_val)
        
        if materials_found:
            # Use first non-empty material (primary material for the part)
            designation = materials_found[0]
            
            # Try to split designation from spec reference
            # e.g., "6061-T6 PER AMS-QQ-A-200" -> designation="6061-T6", spec="PER AMS-QQ-A-200"
            spec = ""
            spec_match = re.search(
                r'(?:ASTM|AMS|SAE|MIL-[A-Z]|UNS\s+[SNK]|MSFC-SPEC|AISI|QQ-|'
                r'PER\s+(?:AMS|SAE|ASTM|MIL|MSFC)|MMPDS)',
                designation, re.IGNORECASE
            )
            if spec_match:
                spec = designation[spec_match.start():].strip()
                designation = designation[:spec_match.start()].strip().rstrip(",").strip()
            
            return {
                "designation": designation,
                "spec": spec,
                "all_materials": materials_found,  # In case multi-item BOM
            }
    
    return None
```

### Also Check: Text-Based BOM Detection

Some GPE PDFs may not have clean table detection from pdfplumber (table lines too faint, etc.). Add a text-based fallback that scans the raw text:

```python
def _extract_bom_material_from_text(full_text: str) -> Optional[dict]:
    """
    Fallback: extract BOM material from raw text when table detection fails.
    
    Looks for patterns like:
        ITEM NO.  QTY  MATERIAL  LOT - S/N
        1         A/R  6061-T6
    """
    lines = full_text.split("\n")
    
    # Find the BOM header line
    header_idx = None
    for i, line in enumerate(lines):
        upper = line.upper()
        if "ITEM" in upper and "MATERIAL" in upper and ("QTY" in upper or "QUANTITY" in upper):
            header_idx = i
            break
    
    if header_idx is None:
        return None
    
    # The material value is typically 1-3 lines after the header
    # Look for lines with material-like content
    material_patterns = [
        r'\b\d{4}-T\d+\b',           # 6061-T6, 7075-T651
        r'\b\d{4}-H\d+\b',           # 5052-H32
        r'\bA\d{3}\b',               # A286
        r'\b\d{2}-\d\s*PH\b',        # 15-5 PH
        r'\b(?:INCONEL|MONEL|HASTELLOY|WASPALOY)\b',
        r'\b(?:CRES|STAINLESS)\b',
        r'\b(?:ALUMINUM|TITANIUM|COPPER|BRASS|BRONZE)\b',
        r'\bVESPEL\b',
        r'\bPCTFE\b',
        r'\bKAPTON\b',
        r'\bTEFLON\b',
    ]
    
    for i in range(header_idx + 1, min(header_idx + 10, len(lines))):
        line = lines[i].strip()
        if not line or len(line) < 3:
            continue
        
        for pattern in material_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                # Found material — extract the full material string
                # Try to isolate just the material portion
                # Often formatted as: "1  A/R  6061-T6  MMPDS"
                parts = line.split()
                
                # Find which token matched and take it plus any following spec words
                for pi, part in enumerate(parts):
                    if re.search(pattern, part, re.IGNORECASE):
                        # Take from this token to end, then split off spec
                        material_str = " ".join(parts[pi:])
                        
                        # Split designation from spec
                        spec = ""
                        spec_match = re.search(
                            r'(?:ASTM|AMS|SAE|MIL-[A-Z]|UNS|MSFC-SPEC|AISI|QQ-|'
                            r'PER\s+(?:AMS|SAE|ASTM|MIL)|MMPDS)',
                            material_str, re.IGNORECASE
                        )
                        if spec_match:
                            spec = material_str[spec_match.start():].strip()
                            designation = material_str[:spec_match.start()].strip().rstrip(",")
                        else:
                            designation = material_str.strip()
                        
                        return {
                            "designation": designation,
                            "spec": spec,
                        }
    
    return None
```

Update `_parse_title_block()` to use both:

```python
    # --- NEW: BOM TABLE MATERIAL (GPE format) ---
    if not tb.get("material"):
        # Try table-based extraction first
        bom_material = _extract_bom_material(tables)
        
        # Fallback to text-based if table detection failed
        if not bom_material:
            bom_material = _extract_bom_material_from_text(full_text)
        
        if bom_material:
            tb["material"] = bom_material.get("designation", "")
            if bom_material.get("spec"):
                tb.setdefault("material_spec", bom_material["spec"])
            LOGGER.info(f"[TitleBlock] BOM table material: {tb['material']}")
```

---

## Issue 3: Dash Number Merge Mismatch (builder.py)

### What's Happening

The Drawing Tree says `GPE-015-1`. The parts extractor finds `GPE-015` (no dash number). The merge does exact string match and can't link them. Material gets orphaned.

### Fix Location

In `builder.py`, in `merge_dt_and_parts()`, where it tries to match Parts JSON entries to DT entries.

### Fix Logic

```python
def _normalize_part_number_for_match(pn: str) -> str:
    """
    Strip trailing dash numbers for fuzzy matching.
    
    GPE-015-1  -> GPE-015
    GPE-015    -> GPE-015
    GPE-206-A  -> GPE-206-A  (letter suffix = revision, keep)
    GPE-206-1/2 -> GPE-206   (slash = multi-item, strip)
    GPE-A050-1 -> GPE-A050
    """
    if not pn:
        return pn
    
    # Strip trailing -N where N is a single digit (dash number)
    # But NOT -T6 (temper) or -A (revision letter with no digit)
    stripped = re.sub(r'-(\d)$', '', pn)
    
    # Also handle /N suffix (e.g., GPE-206-1/2 -> GPE-206-1 -> GPE-206)
    stripped = re.sub(r'/\d+$', '', stripped)
    # Then strip the remaining -1
    stripped = re.sub(r'-(\d)$', '', stripped)
    
    return stripped
```

In the merge loop where it looks up Parts in the DT index:

```python
# Current (exact match only):
dt_entry = pn_to_dt.get(part_number)

# Fixed (try exact first, then fuzzy):
dt_entry = pn_to_dt.get(part_number)
if dt_entry is None:
    # Try normalized match (strip dash numbers)
    norm_pn = _normalize_part_number_for_match(part_number)
    for dt_pn, dt_val in pn_to_dt.items():
        if _normalize_part_number_for_match(dt_pn) == norm_pn:
            dt_entry = dt_val
            LOGGER.info(f"[Merge] Fuzzy matched {part_number} -> {dt_pn}")
            break
```

When a fuzzy match succeeds, **merge the material data INTO the existing DT row** instead of creating a new orphan row:

```python
if dt_entry is not None:
    # Found the DT row — merge material data into it
    dt_row_idx = dt_entry["row_index"]  # or however you track the row
    existing_row = miul_rows[dt_row_idx]
    
    # Only merge material fields, don't overwrite hierarchy
    if not existing_row.get("Designation") and parts_entry.get("material"):
        existing_row["Designation"] = parts_entry["material"]
    if not existing_row.get("Material Specification") and parts_entry.get("material_spec"):
        existing_row["Material Specification"] = parts_entry["material_spec"]
    if not existing_row.get("Process Specification") and parts_entry.get("process_spec"):
        existing_row["Process Specification"] = parts_entry["process_spec"]
    
    LOGGER.info(f"[Merge] Merged material into DT row for {part_number}")
else:
    # No DT match at all — add as orphan (existing behavior)
    ...
```

---

## Execution Order

1. **`_dedupe_doubled_text()` and `_is_doubled_text()`** — Add to text_extract.py, apply in `extract_drawing()` BEFORE any parsing
2. **`_extract_bom_material()` and `_extract_bom_material_from_text()`** — Add to text_extract.py
3. **Update `_parse_title_block()`** — Add BOM fallback after existing MATERIAL: note search
4. **`_normalize_part_number_for_match()`** — Add to builder.py
5. **Update merge loop in `merge_dt_and_parts()`** — Fuzzy match + merge material into DT rows

## Verification

After all fixes, run GPE extraction:

```bash
# Run MIUL extraction
python -m mira.miul.v3 --directory /path/to/GPE/drawings --dt-json GPE-DOC-004-D_corrected.json

# Check results
python -c "
import pandas as pd
df = pd.read_excel('MIUL_GPE.xlsx')
has_mat = df['Designation'].notna().sum()
total = len(df)
print(f'Materials: {has_mat}/{total}')

# Show detail parts
detail_mask = ~df['Part Number'].str.contains('A0|A1|A2', na=False)  # Not assemblies
detail = df[detail_mask & (df['Index'] > 2) & (df['Index'] != -1)]
detail_with_mat = detail[detail['Designation'].notna()]
print(f'Detail parts with material: {len(detail_with_mat)}/{len(detail)}')
for _, row in detail_with_mat.iterrows():
    print(f'  {row[\"Part Number\"]}: {row[\"Designation\"]}')
"
```

### Expected Results

| Metric | Before | After |
|--------|--------|-------|
| Materials found | 2/67 | 13+/67 |
| Orphan rows (Parent=2, no NHA) | 2 | 0 |
| Doubled text in output | Yes | No |
| Detail drawings with material | 2/~15 | 11+/~15 |

### Known Limitations

- 4 of 15 detail drawings may genuinely not have material in the PDF (no BOM table, no MATERIAL note)
- EPL material column is empty on all GPE assemblies — this is expected, material comes from detail drawings
- Standard hardware parts (PP-, FP-, TH100-, SHC-, BY-) won't have material from drawings — need std parts DB lookup (separate issue)
