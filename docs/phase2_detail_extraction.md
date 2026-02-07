# Phase 2: Detail Drawing Note Extraction
## Task Spec for VSClaude

### The Problem

The DMLLV project has 41 drawings. Only 9 are assemblies (have EPLs). The other 32 are **detail drawings** — single parts where material data lives in the NOTES block and title block, NOT in a parts list table.

`text_extract.py` currently handles assembly EPLs perfectly (95.5% accuracy). But it does **nothing** with detail drawings. When it sees no EPL, it returns `has_epl: False, drawing_type: "detail"` and that's it. No material, no spec, no process.

James got **65 fields** from detail drawings that we're returning blank:
- 34 Material Specification fields
- 31 Process Specification fields

Plus the text_layer bypass in builder.py accidentally disabled standard parts DB enrichment, losing another 22 MatSpec fields.

### The Data (Proven on MER07545-001)

Text layer from a detail drawing contains:

```
NOTES:
1. DRAWING PREPARED PER ASME Y14.41-2003, EXCEPT AS NOTED BELOW:
   ...
2. REMOVE ALL BURRS AND SHARP EDGES.
3. MATERIAL: ALUMINUM ALLOY 7075-T651, ASTM B211, SAE AMS-QQ-A-225/9.
4. UNLESS OTHERWISE SPECIFIED, ALL MACHINED SURFACES. SURFACE TEXTURE PER ASME B46.1.
5. ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR
6. IDENTIFY PART WITH PART NUMBER AND CAGE CODE PER MIL-STD-130...
7. CLEAN AND MAINTAIN PER IEST-STD-CC1246, LEVEL VC-0.5-1000.
```

Title block contains:
```
MER07543-001 DMLLV                     ← NHA (NEXT ASSY USED ON)
MATERIAL 3.                            ← note reference for material
FINISH 5.                              ← note reference for finish/process
```

From Note 3: `MATERIAL: ALUMINUM ALLOY 7075-T651, ASTM B211, SAE AMS-QQ-A-225/9.`
- **Designation** = `ALUMINUM ALLOY 7075-T651` (everything before first spec ref)
- **Material Spec** = `ASTM B211, SAE AMS-QQ-A-225/9` (spec references)

From Notes 5 + 7 (process-related):
- **Process Spec** = `ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR`
- Could also include: `CLEAN AND MAINTAIN PER IEST-STD-CC1246, LEVEL VC-0.5-1000`

### What to Change

#### File 1: `text_extract.py` — Add detail drawing extraction

The existing `_parse_title_block()` at line 368-371 already grabs `MATERIAL:` but dumps it all into `tb["material"]` as one unsplit string. It doesn't extract `material_spec`, `process_spec`, or `uns_number`.

**Replace lines 368-371** (the MATERIAL section in `_parse_title_block`) with full detail extraction:

```python
# --- MATERIAL (from notes, detail drawings) ---
# Parse the MATERIAL note and split into designation vs specification
for line in full_text.split("\n"):
    if "MATERIAL:" in line.upper() and "REMARKS" not in line.upper():
        content = line.split(":", 1)[1].strip().rstrip(".")
        
        # Split: designation is before spec references, spec is after
        spec_pattern = r'(?:ASTM|AMS|SAE|MIL-[A-Z]|UNS\s+[SNK]|MSFC-SPEC|AISI|QQ-|PER\s+(?:AMS|SAE|ASTM|MIL))'
        spec_match = re.search(spec_pattern, content, re.IGNORECASE)
        
        if spec_match:
            designation = content[:spec_match.start()].strip().rstrip(",").strip()
            spec = content[spec_match.start():].strip()
            tb.setdefault("material", designation)
            tb.setdefault("material_spec", spec)
            
            # Extract UNS number if present in spec
            uns_match = re.search(r'UNS\s+([SNK]\d{5})', spec, re.IGNORECASE)
            if uns_match:
                tb.setdefault("uns_number", uns_match.group(1).upper())
        else:
            tb.setdefault("material", content)
```

**Add process spec extraction** after the MATERIAL section (new code, insert after the material block above):

```python
# --- PROCESS SPEC (from notes, detail drawings) ---
# Process specs are notes containing manufacturing operations
_PROCESS_KEYWORDS = [
    'ANODIZE', 'KOLSTERIZE', 'PASSIVATE', 'WELD', 'SOLUTION TREAT',
    'HEAT TREAT', 'PLATE', 'COAT', 'PAINT', 'PRIME', 'CADMIUM',
    'NICKEL PLATE', 'CHROME', 'ION IMPLANT', 'SHOT PEEN',
    'STRESS RELIEVE', 'NORMALIZE', 'BRAZE', 'SOLDER', 'BOND',
    'CLEAN AND MAINTAIN', 'SURFACE TEXTURE',
]

# Use already-parsed notes to find process specs
# (notes are parsed by _parse_notes which runs before title block)
process_parts = []
for line in full_text.split("\n"):
    stripped = line.strip().rstrip(".")
    if any(kw in stripped.upper() for kw in _PROCESS_KEYWORDS):
        # Remove leading note number (e.g., "5." or "7.")
        cleaned = re.sub(r'^\d+\s*[\.\)]\s*', '', stripped)
        if cleaned and len(cleaned) > 10:  # skip short fragments
            process_parts.append(cleaned)

if process_parts:
    # Join multiple process notes with separator
    # James uses ", " for combined specs and "; " for distinct operations
    tb.setdefault("process_spec", "; ".join(process_parts))
```

**Add `import re`** at the top of text_extract.py (it's not currently imported).

#### File 2: `builder.py` — Restore standard parts DB enrichment

In `_process_assembly()` around line 1399, the text_layer path currently reads `material_callout` from parts. But `_convert_text_result()` at line 666 maps text_extract's `"material"` field to... `"material"`. Then `_process_assembly` reads `part.get("material_callout")` — **different key name**.

**This is a key mismatch bug.** The text_layer path puts material into `"material"` but _process_assembly looks for `"material_callout"`. So text_layer material NEVER flows through.

**Fix in `_convert_text_result()`** at line 661-669, change `"material"` to `"material_callout"`:

```python
converted_parts.append({
    "find_no": str(p.get("find_no", "")),
    "part_number": p.get("part_number", ""),
    "description": p.get("description", ""),
    "quantity": p.get("qty_001") or p.get("qty_003") or 1,
    "material_callout": p.get("material", ""),  # ← was "material", must be "material_callout"
    "cage_code": p.get("cage_code", ""),
    "is_alternate": p.get("is_alternate", False),
})
```

The standard parts DB enrichment in `_process_assembly()` lines 1409-1423 is already correct — it checks `if not raw_material` and falls through to `lookup_standard_part_material()`. The bug was that `raw_material` was always getting the empty string from the wrong key name, so it was falling through to std parts lookup BUT only for designation, not for spec (because the fallback logic at 1419-1423 checks `elif not raw_spec` which requires `raw_material` to be truthy).

**Wait — re-read this.** Actually the fallback at 1409 says `if not raw_material`, and std_lookup fills both designation AND spec. So std parts DB should have been working even with the key mismatch, because raw_material would be empty and trigger the lookup. Let me re-examine...

The issue is that for text_layer parts, `raw_material` = `correct_ocr_errors(part.get("material_callout", ""))` = `correct_ocr_errors("")` = `""`. So it falls to Fallback 1 (line 1404): check child drawing. If child drawing has material, it gets that. If not, Fallback 2 (line 1410): std parts lookup. So the std parts lookup **should work for parts that have no child drawing**.

The **real** gap is Fallback 1: for text_layer assemblies, the child detail drawings now correctly have `material_designation` and `material_spec` populated (after our Phase 2 fix). So the chain becomes:

1. EPL row says `material = "A286 (150 KSI)"` → goes through as `material_callout` (after key fix)
2. If EPL material is empty, check child drawing → now has material from note parsing
3. If no child drawing, check std parts DB → works for NAS/MS parts

**All three tiers will work after these two fixes.**

#### File 3: `builder.py` — Fix normalize_designation on text_layer path

In `_process_assembly()` at line 1426:
```python
material, uns = normalize_designation(raw_material)
```

For text_layer extracted parts, the material is already verbatim from the drawing. Running it through `normalize_designation()` can mangle it (A286 → A286 CRES, etc.). 

**Add a flag or check:** if the material came from text_layer (not Vision), skip normalization:

```python
# For text_layer extracted material, use verbatim (already correct from drawing)
# For Vision-extracted material, normalize to fix OCR artifacts
extraction_method = getattr(drawing, 'source_file', '')  # Check how we got here
is_text_layer = any(
    p.get("source") == "text_layer" for p in [part]
) if "source" in part else hasattr(drawing, '_extraction_method') and drawing._extraction_method == "text_layer"
```

Actually, simpler approach — **check if the drawing's extraction method was text_layer**. The DrawingData doesn't currently store extraction_method. Add it:

In DrawingData (line 107-121), add:
```python
extraction_method: str = ""  # "text_layer" or "vision"
```

In `_result_to_drawing_data()` (line 696-713), add:
```python
extraction_method=result.get("extraction_method", ""),
```

Then in `_process_assembly()` at line 1425-1427:
```python
if drawing.extraction_method == "text_layer":
    # Text layer gives verbatim material from drawing — don't normalize
    material = raw_material
    uns = ""
    # But still check for UNS in the spec
    import re
    uns_match = re.search(r'UNS\s+([SNK]\d{5})', raw_spec, re.IGNORECASE)
    if uns_match:
        uns = uns_match.group(1).upper()
else:
    material, uns = normalize_designation(raw_material)
spec = normalize_material_spec(raw_spec, uns)
```

#### File 4: `text_extract.py` — Filter DELETED rows

In `_parse_epl_table()` at line 183-185, after calling `_parse_epl_row(row)`:

```python
part = _parse_epl_row(row)
if part:
    # Skip DELETED rows
    desc = part.get("description", "").strip().upper()
    pn = part.get("part_number", "").strip().upper()
    if desc == "DELETED" or pn == "DELETED":
        continue
    parts.append(part)
```

### Verification Plan

After all changes, run the full DMLLV pipeline and compare against James's ground truth:

| Field | Before | Expected After |
|-------|--------|----------------|
| Designation (EPL parts) | 95.5% | 95.5%+ (key fix ensures verbatim flows) |
| Designation (detail parts) | 0% (blank) | ~90%+ (from note parsing) |
| Material Specification | 0% (all blank) | ~80%+ (from notes + std parts DB) |
| Process Specification | 0% (all blank) | ~80%+ (from notes) |
| Part Number accuracy | 80.2% | 80.2%+ (DELETED filtered) |
| NHA | 0% | Depends on graph config |

### Priority Order

1. **text_extract.py: material note splitting** (unlocks 34 MatSpec fields)
2. **builder.py: key name fix** (material → material_callout in _convert_text_result)
3. **text_extract.py: process spec extraction** (unlocks 31 ProcSpec fields)
4. **builder.py: skip normalize_designation for text_layer** (preserves verbatim)
5. **text_extract.py: filter DELETED rows** (removes garbage)
6. **builder.py: add extraction_method to DrawingData** (enables text_layer flag)

### Architecture Note

This is NOT a new module. It's extending the existing `_parse_title_block()` function in `text_extract.py` to extract what's already there. The notes are already being parsed by `_parse_notes()`. We just need to:

1. Split the MATERIAL note into designation + spec + UNS
2. Identify process-related notes
3. Pass these through existing title_block dict → _convert_text_result → DrawingData → MIUL rows

The entire data flow already exists. We're just not populating the fields.
