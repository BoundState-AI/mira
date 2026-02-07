# MIUL Bug Fix Spec: EPL Column Shift + NHA Leak + Key Mismatch
## Task Spec for VSClaude

### Summary

Three bugs producing 16 bad rows + 31 wrong NHA assignments in MIUL_test.xlsx.
All fixable in two files: `text_extract.py` and `builder.py`.

---

## Bug 1: EPL Column Layout Not Detected Dynamically (15 bad rows)

### Symptoms
- Part Number has CAGE code appended: `"MER07585-001 339B2"`
- Part Description contains material name: `"A286"` instead of `"POPPET, VALVE, 10 INCH"`
- Designation is empty (material went to wrong field)
- Affected assemblies: MER07565-001, MER07570-001, MER07584-001
- Working assemblies: MER07540-001, MER07543-001 (parse correctly)

### Root Cause
`_parse_epl_row()` in `text_extract.py` uses **hardcoded column indices**:
```python
# Current code (lines 201-211):
#   [4] = PART NUMBER
#   [5] = PART NUMBER overflow
#   [6] = (more overflow)
#   [7] = CAGE CODE
#   [8] = DESCRIPTION
#   [9] = MATERIAL
```

For the broken drawings, pdfplumber returns the table with CAGE in a
different column position (likely col 5 or 6 instead of 7). The parser
then merges CAGE into the Part Number (via the `[4,5,6]` join), puts
material into description, and loses the real description.

The EPL header row (near the bottom of the table) has column labels:
```
Row 21: ['-003', '-001', '', 'FIND\nNO.', 'PART NUMBER', '', '', 'CAGE\nCODE', 'DESCRIPTION', 'MATERIAL / REMARKS (REF)']
```

This header is currently SKIPPED. It should be READ to discover column positions.

### Fix: Dynamic Column Detection in `_parse_epl_table()`

Replace the hardcoded approach with header-driven column mapping.

#### Step 1: Add column detection function

```python
def _detect_epl_columns(table: list) -> dict:
    """
    Detect EPL column layout from header row.
    
    Scans table rows (bottom-up, since headers are near the bottom in
    inverted EPLs) looking for column labels like "FIND", "PART NUMBER",
    "CAGE", "DESCRIPTION", "MATERIAL".
    
    Returns:
        dict mapping field names to column indices:
        {
            "find_no": int,
            "part_number": int,        # first PN column
            "part_number_end": int,    # last PN column (before CAGE)
            "cage_code": int,
            "description": int,
            "material": int,
            "qty_cols": list[int],     # quantity column indices
        }
        
        Returns None if no header found (fall back to hardcoded layout).
    """
    # Scan rows bottom-up for the header row
    for row_idx in range(len(table) - 1, -1, -1):
        row = table[row_idx]
        if not row:
            continue
        row_text = " ".join(str(c) for c in row if c).upper()
        
        # Header row contains "FIND" and "PART NUMBER" (or "PART" and "NUMBER")
        if "FIND" not in row_text or "PART" not in row_text:
            continue
        
        # Found the header row - map column positions
        layout = {}
        cells = [str(c).strip().upper().replace("\n", " ") if c else "" for c in row]
        
        for i, cell in enumerate(cells):
            if "FIND" in cell:
                layout["find_no"] = i
            elif "PART NUMBER" in cell or cell == "PART":
                layout["part_number"] = i
            elif "CAGE" in cell:
                layout["cage_code"] = i
            elif "DESCRIPTION" in cell:
                layout["description"] = i
            elif "MATERIAL" in cell or "REMARKS" in cell:
                layout["material"] = i
        
        # Validate we found the essential columns
        required = ["find_no", "part_number", "description"]
        if not all(k in layout for k in required):
            continue
        
        # PN spans from part_number to cage_code (exclusive) or description (exclusive)
        cage_col = layout.get("cage_code")
        desc_col = layout.get("description")
        if cage_col is not None:
            layout["part_number_end"] = cage_col - 1
        elif desc_col is not None:
            layout["part_number_end"] = desc_col - 1
        else:
            layout["part_number_end"] = layout["part_number"]
        
        # QTY columns = everything before find_no
        layout["qty_cols"] = list(range(0, layout["find_no"]))
        
        return layout
    
    return None  # No header found
```

#### Step 2: Modify `_parse_epl_table()` to use dynamic layout

```python
def _parse_epl_table(table: list) -> dict:
    """
    Parse an EPL table into structured parts data.
    Now uses dynamic column detection from header row.
    """
    # Detect column layout from header
    layout = _detect_epl_columns(table)
    
    header_anchors = {"ENGINEERING PARTS LIST", "QTY REQD", "FIND"}
    
    parts = []
    for row in table:
        row_text = " ".join(str(c) for c in row if c).upper()
        if any(anchor in row_text for anchor in header_anchors):
            continue
        
        part = _parse_epl_row(row, layout)  # Pass layout
        if part:
            parts.append(part)
    
    # ... rest unchanged (reverse order, count, max_find)
```

#### Step 3: Modify `_parse_epl_row()` to accept layout

```python
def _parse_epl_row(row: list, layout: dict = None) -> Optional[dict]:
    """
    Parse a single EPL row using dynamic column layout.
    
    If layout is None, falls back to hardcoded NASA D-format layout.
    """
    cells = [str(c).strip() if c else "" for c in row]
    
    if layout:
        # Dynamic layout from header detection
        find_col = layout["find_no"]
        pn_start = layout["part_number"]
        pn_end = layout.get("part_number_end", pn_start)
        cage_col = layout.get("cage_code")
        desc_col = layout.get("description")
        mat_col = layout.get("material")
    else:
        # Hardcoded fallback (original layout)
        find_col = 3
        pn_start = 4
        pn_end = 6
        cage_col = 7
        desc_col = 8
        mat_col = 9
    
    # Bounds check
    if len(cells) <= find_col:
        return None
    
    # Extract find number
    find_str = cells[find_col] if find_col < len(cells) else ""
    try:
        find_no = int(find_str)
    except (ValueError, TypeError):
        return None
    
    # Extract part number - span from pn_start to pn_end
    # BUT exclude the cage_code column if it falls in this range
    part_number_parts = []
    for i in range(pn_start, pn_end + 1):
        if i < len(cells) and cells[i]:
            # Don't include CAGE code in PN
            if cage_col is not None and i == cage_col:
                continue
            part_number_parts.append(cells[i])
    part_number = " ".join(part_number_parts).strip()
    
    if not part_number:
        return None
    
    # Detect ALT rows
    qty_cols = layout.get("qty_cols", [0, 1]) if layout else [0, 1]
    is_alternate = False
    if qty_cols and qty_cols[0] < len(cells):
        is_alternate = cells[qty_cols[0]].upper() == "ALT"
    
    # Quantities
    qty_003 = _parse_qty(cells[qty_cols[0]]) if qty_cols and qty_cols[0] < len(cells) and not is_alternate else ("ALT" if is_alternate else None)
    qty_001 = _parse_qty(cells[qty_cols[1]]) if len(qty_cols) > 1 and qty_cols[1] < len(cells) else None
    
    # CAGE code
    cage_code = cells[cage_col] if cage_col is not None and cage_col < len(cells) else ""
    
    # Description
    description = cells[desc_col] if desc_col is not None and desc_col < len(cells) else ""
    description = description.replace("\n", " ").replace("\u2300", "DIA ").strip()
    while "  " in description:
        description = description.replace("  ", " ")
    
    # Material
    material = cells[mat_col] if mat_col is not None and mat_col < len(cells) else ""
    material = material.replace("\n", " ").strip()
    
    return {
        "find_no": find_no,
        "part_number": part_number,
        "cage_code": cage_code,
        "description": description,
        "material": material,
        "qty_001": qty_001,
        "qty_003": qty_003,
        "is_alternate": is_alternate,
    }
```

#### Step 4: Add post-hoc sanity check (defense in depth)

After parsing all EPL rows, detect rows where description looks like a
material name. This catches any remaining column misalignment issues.

```python
# Add at end of _parse_epl_table(), after parts list is built:

MATERIAL_PATTERNS = {
    "A286", "INCONEL", "7075", "CRES", "SST", "MONEL", "HASTELLOY",
    "TITANIUM", "WASPALOY", "STELLITE", "INVAR", "KOVAR", "RENE",
}

for part in parts:
    desc = part.get("description", "").strip().upper()
    material = part.get("material", "").strip()
    
    # If description looks like a material and material is empty,
    # the columns are probably shifted
    if not material and desc:
        desc_words = set(desc.replace("-", " ").split())
        if desc_words & MATERIAL_PATTERNS:
            LOGGER.warning(
                f"EPL column shift detected for find {part['find_no']}: "
                f"description '{part['description']}' looks like material. "
                f"Check column alignment."
            )
            # Attempt repair: swap description → material
            part["material"] = part["description"]
            part["description"] = ""
    
    # If PN contains a 5-char CAGE code suffix, strip it
    pn = part.get("part_number", "")
    pn_parts = pn.rsplit(" ", 1)
    if len(pn_parts) == 2:
        suffix = pn_parts[1]
        # CAGE codes: 5 chars, alphanumeric
        if len(suffix) == 5 and suffix.isalnum():
            LOGGER.info(
                f"Stripping CAGE code '{suffix}' from PN '{pn}'"
            )
            part["cage_code"] = suffix
            part["part_number"] = pn_parts[0]
```

---

## Bug 2: Material Key Mismatch (`material` vs `material_callout`)

### Symptoms
- EPL parts have empty Designation even when material is in the text_extract output
- Material data is extracted but never reaches the MIUL row

### Root Cause
In `builder.py`:
- `_convert_text_result()` line 666 maps to key `"material"`:
  ```python
  "material": p.get("material", ""),
  ```
- `_process_assembly()` line 1399 reads key `"material_callout"`:
  ```python
  raw_material = correct_ocr_errors(part.get("material_callout", "") or "")
  ```

These keys don't match. The material data is present in the converted result
under `"material"` but the assembly processor looks for `"material_callout"`
and finds nothing.

### Fix

In `builder.py`, `_convert_text_result()`, change line 666:

```python
# BEFORE:
"material": p.get("material", ""),

# AFTER:
"material_callout": p.get("material", ""),
```

This makes the converted text result match what `_process_assembly()` expects.

**Also add spec_callout mapping** (same pattern, currently missing):

```python
# Add to the converted_parts dict:
"spec_callout": "",  # Text layer EPL doesn't have separate spec column
```

---

## Bug 3: NHA = "test" for Detail Drawing Rows (31 rows)

### Symptoms
- 31 detail drawing rows have NHA = "test" (the project name)
- Should have NHA = their parent assembly drawing number

### Root Cause
In `builder.py`, `build_miul()`, Step 3 (line 1241):
```python
nha = graph.get(dwg_num, drawing.nha or "")
```

If `graph` doesn't contain the drawing number AND `drawing.nha` is empty,
the NHA defaults to empty string. But separately, somewhere the project
name "test" is being set as the fallback.

Looking at the data: Row 1 is the MIUL header row with PN = "test" and
NHA = "test". The project name is being used as the root assembly name,
and detail drawings that aren't in the DT tree are getting NHA = project name.

The real issue: the DT tree / graph doesn't contain enough entries.
Detail drawings that appear in assembly EPLs should get NHA from the
EPL relationship (the assembly that lists them). But the graph isn't
being built correctly because the EPL parts have mangled PNs (Bug 1).

### Fix

This is a **consequence of Bug 1**. When the EPL parser mangles
`MER07585-001` as `MER07585-001 339B2`, the graph can't match
the detail drawing `MER07585-001` to its parent assembly.

**Fix Bug 1 first, then verify the NHA assignments correct themselves.**

However, also add a safeguard: if NHA resolves to the project name
(which is never a valid drawing number), leave it empty instead:

```python
# In build_miul(), Step 3, after line 1241:
nha = graph.get(dwg_num, drawing.nha or "")

# Add safeguard: project name is not a valid NHA
if nha and nha == self.project_name:
    nha = ""
```

Wait — actually the real fix is that _build_graph needs the EPL data
to map child PNs to parent assemblies. When the PNs are mangled,
the mapping fails. Fixing the EPL parser (Bug 1) fixes the graph.

Still add the safeguard as defense in depth.

---

## Bug 4: Vision Double-Character Artifact (1 row)

### Symptoms
- PN: `MMEERR0077558855--000011` (every character doubled)
- Description: `MMAATTEERRIIAALLSS` (every character doubled)
- This is MER07585-001, a detail drawing

### Root Cause
Vision OCR reads the title block text twice — once from each side of a
two-column layout — and interleaves the characters.

### Fix

Add a de-doubling detector. If every character appears exactly twice
in sequence, the string is doubled:

```python
def _detect_doubled_text(text: str) -> Optional[str]:
    """
    Detect and fix Vision double-character artifact.
    
    When Vision reads "MER07585-001" from a mirrored/doubled title block,
    it produces "MMEERR0077558855--000011".
    
    Returns de-doubled text if pattern detected, None otherwise.
    """
    if not text or len(text) < 4 or len(text) % 2 != 0:
        return None
    
    # Check if every pair of adjacent characters is identical
    for i in range(0, len(text), 2):
        if text[i] != text[i + 1]:
            return None
    
    # De-double: take every other character
    return text[::2]
```

Add this check in `_postprocess_miul()` in builder.py:

```python
# Check Part Number for doubled text
pn = str(row.get("Part Number", ""))
dedoubled = _detect_doubled_text(pn)
if dedoubled:
    LOGGER.warning(
        f"[MIULBuilder] Vision doubling detected: '{pn}' → '{dedoubled}'"
    )
    df.at[idx, "Part Number"] = dedoubled
    # Also check description
    desc = str(row.get("Part Description", ""))
    desc_dedoubled = _detect_doubled_text(desc)
    if desc_dedoubled:
        df.at[idx, "Part Description"] = desc_dedoubled
        df.at[idx, "Nomenclature"] = desc_dedoubled
    # Check Drawing Source
    ds = str(row.get("Drawing Source", ""))
    ds_dedoubled = _detect_doubled_text(ds)
    if ds_dedoubled:
        df.at[idx, "Drawing Source"] = ds_dedoubled
```

---

## Verification Plan

After applying all fixes, rebuild MIUL for DMLLV and verify:

### Bug 1 Verification
```
MER07565-001 EPL children:
  ✅ MER07567-001 | SHAFT, OFFSET, INSERT INSTALL, 10 INCH VALVE | Desig: MISC
  ✅ MER07566-001 | ROTARY TANG, OFFSET SHAFT, 10 INCH VALVE     | Desig: A286
  ✅ NAS1352N4-10 | SHCS, .2500-20 UNRC-3A, .625 LG              | Desig: A286

MER07570-001 EPL children:
  ✅ MER07573-001 | ACTUATOR WELD ASSEMBLY                        | Desig: INCONEL
  ✅ MER07572-001 | BRACKET, ANGLE, ACTUATOR                      | Desig: A286
  ✅ MER07548-001 | MOUNT BRACKET, ACTUATOR, 10 INCH VALVE        | Desig: 7075 AL
  ✅ (ASME spec)  | SBHCS, .2500-20 UNC-2A, .75 LG               | Desig: 18-8 CRES
  ✅ AS4307K04    | UNION FITTING, -04, (.250)                     | Desig: 316 CRES
  ✅ F-400521-04  | SEAL, K-PORT, GOLD PLATE                      | Desig: 304 CRES

MER07584-001 EPL children:
  ✅ 50854SCS     | SPRING, COMPRESSION, 1.575 LG                 | Desig: 316 SST
  ✅ WHM-275-S86  | RETAINING RING, INTERNAL, 2 3/4               | Desig: A286
  ✅ MER07585-001 | POPPET, VALVE, 10 INCH                        | Desig: A286
  ✅ MER07586-001 | COUPLING, POPPET                              | Desig: A286
  ✅ MER07588-001 | PUSHER, BALL, POPPET                          | Desig: INCONEL 718
  ✅ MER07587-001 | INTERFACE RING, COUPLER TO POPPET             | Desig: A286
```

No CAGE codes in Part Number. No materials in Description.

### Bug 2 Verification
Every EPL row that has material in the source table should have
a populated Designation in the MIUL output.

### Bug 3 Verification
No row should have NHA = "test". Detail drawing rows should have
NHA = their parent assembly (e.g., MER07585-001 → NHA: MER07584-001).

### Bug 4 Verification
No doubled-character strings anywhere in the output.

### Full Regression
Compare output against James's 139-row ground truth:
- Part Number match rate: target > 95%
- Description match rate: target > 90%
- NHA match rate: target > 90%
- Designation match rate: target > 85%

---

## File Locations

- `text_extract.py` — Bug 1 fix (dynamic column detection)
- `builder.py` — Bug 2 fix (key mismatch), Bug 3 fix (NHA safeguard), Bug 4 fix (de-doubling)

## Priority Order

1. Bug 1 (EPL column shift) — fixes 15 rows directly, unblocks Bug 3
2. Bug 2 (key mismatch) — fixes material propagation for ALL text layer EPLs
3. Bug 3 (NHA leak) — auto-fixes once Bug 1 fixes the graph, safeguard is bonus
4. Bug 4 (Vision doubling) — fixes 1 row, safety net for future Vision artifacts

## Notes for VSClaude

- The EPL header row is near the BOTTOM of the table (inverted EPL format)
- `_parse_epl_table()` already iterates and skips header rows — modify that
  loop to CAPTURE the header first, then parse data rows
- The header row contains `"FIND\nNO."` (with newline) — normalize before matching
- Test with MER07540-001 PDF first (it's uploaded and known-working) to verify
  the dynamic detection produces the same results as hardcoded layout
- Then the broken drawings (MER07565, MER07570, MER07584) should auto-fix
  when their PDFs are processed
