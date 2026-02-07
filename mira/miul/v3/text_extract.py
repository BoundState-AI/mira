#!/usr/bin/env python3
"""
Module: text_extract
Purpose: Extract EPL and title block data from CAD-generated NASA/MSFC drawings

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Sonnet 4 <noreply@anthropic.com>
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016C
Safety Critical: False

EPL + Detail Drawing Text Layer Extractor
==========================================
Phase 1: Extracts Engineering Parts Lists from assembly drawings (v1.0)
Phase 2: Extracts material/process specs from detail drawing notes (v2.0)

Uses pdfplumber's text layer extraction. No regex for table parsing.
No Vision API. No OCR. Works on any NASA D-format drawing with embedded text.

Usage:
    from mira.miul.v3.text_extract import extract_drawing

    result = extract_drawing("MER07545-001_DRW_-_12_RELEASED.pdf")

    if result["drawing_type"] == "detail":
        tb = result["title_block"]
        print(f"Material: {tb.get('material', '')}")
        print(f"MatSpec:  {tb.get('material_spec', '')}")
        print(f"ProcSpec: {tb.get('process_spec', '')}")
        print(f"NHA:      {tb.get('nha', '')}")

    if result["has_epl"]:
        for part in result["epl"]["parts"]:
            print(f"Find {part['find_no']}: {part['part_number']}")
"""

import logging
import re
from pathlib import Path
from typing import Optional
import pdfplumber

# Silence pdfminer DEBUG spam
logging.getLogger("pdfminer").setLevel(logging.WARNING)

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Spec reference patterns — these mark where designation ends and spec begins
# in a MATERIAL note like "ALUMINUM ALLOY 7075-T651, ASTM B211, SAE AMS-QQ-A-225/9"
_SPEC_PATTERN = re.compile(
    r'(?:ASTM|AMS|SAE\s+AMS|MIL-[A-Z]|UNS\s+[SNK]|MSFC-SPEC|AISI|QQ-|'
    r'PER\s+(?:AMS|SAE|ASTM|MIL|MANUFACTURERS))',
    re.IGNORECASE
)

# Process specification keywords — notes containing these are process specs
_PROCESS_KEYWORDS = [
    'ANODIZE', 'KOLSTERIZE', 'PASSIVATE', 'WELD PER', 'SOLUTION TREAT',
    'HEAT TREAT', 'PLATE PER', 'COAT PER', 'PAINT PER', 'PRIME PER',
    'CADMIUM', 'NICKEL PLATE', 'CHROME PLATE', 'ION IMPLANT',
    'SHOT PEEN', 'STRESS RELIEVE', 'NORMALIZE', 'BRAZE', 'SOLDER',
    'BOND PER', 'CLEAN AND MAINTAIN', 'SURFACE TEXTURE PER',
]


# ---------------------------------------------------------------------------
# Text Layer Deduplication (GPE/CU Boulder PDF Format)
# ---------------------------------------------------------------------------

def _is_doubled_text(text: str) -> bool:
    """
    Detect if pdfplumber output has doubled characters (CU Boulder PDF format).

    CU Boulder's PDF generator uses overlapping text positioning that pdfplumber
    interprets as doubled characters:
        "REMOVE ALL BURRS" -> "RREEMMOOVVEE  AALLLL  BBUURRRRSS"
        "6061-T6" -> "66006611--TT66"

    Heuristic: Sample first 200 chars of actual content. If >70% of alphabetic
    character pairs are repeated (RR, EE, MM...), text is doubled.

    Not all GPE PDFs have this issue, and NASA D-format PDFs never do.
    Detection prevents false-positive dedup on normal text.
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
    ratio = pair_count / total_pairs
    is_doubled = ratio > 0.7
    if is_doubled:
        LOGGER.debug(f"[Dedup] Doubled text detected: {pair_count}/{total_pairs} = {ratio:.1%}")
    return is_doubled


def _dedupe_doubled_text(text: str) -> str:
    """
    Remove doubled characters from pdfplumber output.

    Handles CU Boulder PDF format where characters are doubled:
        "RREEMMOOVVEE  AALLLL  BBUURRRRSS" -> "REMOVE ALL BURRS"
        "66006611--TT66" -> "6061-T6"
        "IITTEEMM  NNOO..  QQTTYY  MMAATTEERRIIAALL" -> "ITEM NO. QTY MATERIAL"

    Strategy: Walk char-by-char. If current char equals next char,
    take one and skip the duplicate. Otherwise take as-is.
    This handles spaces, newlines, and any chars that weren't doubled.
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


def _dedupe_tables(tables: list) -> list:
    """Apply _dedupe_doubled_text to all string cells in tables."""
    if not tables:
        return tables
    result = []
    for table in tables:
        if table is None:
            result.append(None)
            continue
        new_table = []
        for row in table:
            if row is None:
                new_table.append(None)
                continue
            new_row = [
                _dedupe_doubled_text(cell) if isinstance(cell, str) else cell
                for cell in row
            ]
            new_table.append(new_row)
        result.append(new_table)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_drawing(pdf_path: str | Path) -> dict:
    """
    Extract everything useful from a NASA/MSFC engineering drawing.

    Handles both:
    - Assembly drawings (have EPL table with parts list)
    - Detail drawings (single part, material in notes)

    Returns:
        {
            "drawing_number": str,
            "has_epl": bool,
            "drawing_type": "assembly" | "detail",
            "epl": { "parts": [...], "count": int, "max_find": int } | None,
            "title_block": {
                "drawing_number": str,
                "nha": str,
                "title": str,
                "material": str,           # designation (e.g., "7075-T651 ALUMINUM")
                "material_spec": str,       # spec refs (e.g., "ASTM B211, SAE AMS-QQ-A-225/9")
                "uns_number": str,          # UNS if found (e.g., "S66286")
                "process_spec": str,        # process notes (e.g., "ANODIZE PER MIL-A-8625...")
                "weight_lbs": float,
                "cage_code": str,
                "designer": str,
                "engineer": str,
            },
            "notes": [ {"number": int, "text": str}, ... ],
            "source": "text_layer",
            "pages": int,
        }
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        # Page 1 always has the title block and EPL (if assembly)
        page = pdf.pages[0]

        # Extract raw text and tables
        raw_text = page.extract_text() or ""
        raw_tables = page.extract_tables() or []

        # Detect and fix doubled-character artifacts (GPE/CU Boulder PDFs)
        # Detection-first: only apply dedup if >70% of char pairs are repeated
        # This prevents false-positive dedup on NASA D-format PDFs
        is_doubled = _is_doubled_text(raw_text)
        if is_doubled:
            LOGGER.info(f"[TextExtract] Doubled text detected in {pdf_path.name}, applying dedup")
            all_text = _dedupe_doubled_text(raw_text)
            tables = _dedupe_tables(raw_tables)
        else:
            all_text = raw_text
            tables = raw_tables

        # Identify which table is the EPL (if any)
        epl_table = _find_epl_table(tables)
        has_epl = epl_table is not None

        # Parse EPL if found
        epl_data = None
        if epl_table is not None:
            epl_data = _parse_epl_table(epl_table)

        # Extract notes (needed before title block for cross-referencing)
        notes = _parse_notes(all_text)

        # Parse title block (always present) — now includes material/process parsing
        title_block = _parse_title_block(tables, all_text, notes)

        # Fallback: extract drawing number from filename if title block parsing failed
        drawing_number = title_block.get("drawing_number", "UNKNOWN")
        if drawing_number == "UNKNOWN":
            # Try to extract from filename (e.g., "GPE-010-A (Top Plate Drawing).pdf" -> "GPE-010")
            import re
            filename_stem = pdf_path.stem
            # Pattern: alphanumeric prefix with dashes, before any parentheses or extra text
            match = re.match(r'^([A-Z]{2,5}-?\d{2,5}(?:-[A-Z0-9]+)?)', filename_stem, re.IGNORECASE)
            if match:
                drawing_number = match.group(1).upper()

                # Strip trailing revision letter (-A, -B, etc.) - DT is source of truth
                # GPE-010-A -> GPE-010, GPE-A050-A -> GPE-A050
                parts = drawing_number.split('-')
                if len(parts) >= 2 and len(parts[-1]) == 1 and parts[-1].isalpha():
                    drawing_number = '-'.join(parts[:-1])

                title_block["drawing_number"] = drawing_number
                LOGGER.info(f"Drawing number extracted from filename: {drawing_number}")

        return {
            "drawing_number": drawing_number,
            "has_epl": has_epl,
            "drawing_type": "assembly" if has_epl else "detail",
            "epl": epl_data,
            "title_block": title_block,
            "notes": notes,
            "source": "text_layer",
            "pages": len(pdf.pages),
        }


def has_text_layer(pdf_path: str | Path) -> bool:
    """Check if PDF has an extractable text layer."""
    with pdfplumber.open(Path(pdf_path)) as pdf:
        text = pdf.pages[0].extract_text() or ""
        return len(text.strip()) > 100


# ---------------------------------------------------------------------------
# EPL Parsing
# ---------------------------------------------------------------------------

def _find_epl_table(tables: list) -> Optional[list]:
    """
    Find the EPL table by looking for the anchor text.

    The EPL is a standalone table with columns like FIND NO., PART NUMBER, etc.
    On NASA D-format drawings, pdfplumber often finds multiple tables:
      - A big blob merging title block + notes + everything
      - The actual clean EPL table

    We want the one where "ENGINEERING PARTS LIST" appears as its OWN row
    (not buried in a giant text blob), and the table has a reasonable
    column count (8-12 columns typical for EPL).
    """
    candidates = []

    for ti, table in enumerate(tables):
        for ri, row in enumerate(table):
            row_text = " ".join(str(cell) for cell in row if cell)
            if "ENGINEERING PARTS LIST" in row_text:
                # Score this candidate: prefer tables where the anchor is
                # in a short row (dedicated label row) vs buried in a blob
                anchor_cell_len = max(len(str(c)) for c in row if c) if any(c for c in row) else 9999
                n_cols = len(row)
                candidates.append((ti, table, anchor_cell_len, n_cols))

    if not candidates:
        return None

    # Prefer: shortest anchor cell (means it's a dedicated label row, not a blob)
    # Among ties, prefer 8-12 column tables (typical EPL width)
    candidates.sort(key=lambda x: (x[2], abs(x[3] - 10)))
    return candidates[0][1]


def _detect_epl_columns(table: list) -> Optional[dict]:
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
            if "FIND" in cell and "NO" in cell:
                layout["find_no"] = i
            elif cell == "FIND":
                layout["find_no"] = i
            elif "PART NUMBER" in cell or cell == "PART":
                if "part_number" not in layout:
                    layout["part_number"] = i
            elif "CAGE" in cell:
                layout["cage_code"] = i
            elif "DESCRIPTION" in cell:
                layout["description"] = i
            elif "MATERIAL" in cell or "REMARKS" in cell:
                layout["material"] = i

        # Validate we found the essential columns
        required = ["find_no", "part_number"]
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

        LOGGER.info(f"Detected EPL column layout: {layout}")
        return layout

    return None  # No header found


# Material patterns for detecting column shift issues
_MATERIAL_PATTERNS = {
    "A286", "INCONEL", "7075", "CRES", "SST", "MONEL", "HASTELLOY",
    "TITANIUM", "WASPALOY", "STELLITE", "INVAR", "KOVAR", "RENE",
    "ALUMINUM", "BRASS", "BRONZE", "COPPER", "NICKEL", "STEEL",
}


def _parse_epl_table(table: list) -> dict:
    """
    Parse an EPL table into structured parts data.

    The EPL table from pdfplumber comes in visual order (top-to-bottom),
    which for inverted EPLs means highest find number first.

    Now uses dynamic column detection from header row.
    """
    # Detect column layout from header
    layout = _detect_epl_columns(table)

    parts = []
    header_anchors = {"ENGINEERING PARTS LIST", "QTY REQD", "FIND"}

    for row in table:
        # Skip header/label rows
        row_text = " ".join(str(cell) for cell in row if cell).strip()
        if any(anchor in row_text for anchor in header_anchors):
            continue

        # Skip empty rows
        if not any(cell for cell in row):
            continue

        part = _parse_epl_row(row, layout)
        if part:
            # Skip DELETED rows
            desc = part.get("description", "").strip().upper()
            pn = part.get("part_number", "").strip().upper()
            if desc == "DELETED" or pn == "DELETED":
                LOGGER.info(f"Skipping DELETED row: PN={part.get('part_number')}")
                continue
            parts.append(part)

    # Post-hoc sanity checks for column shift detection
    for part in parts:
        desc = part.get("description", "").strip().upper()
        material = part.get("material", "").strip()

        # If description looks like a material and material is empty,
        # the columns are probably shifted - swap them
        if not material and desc:
            desc_words = set(desc.replace("-", " ").split())
            if desc_words & _MATERIAL_PATTERNS:
                LOGGER.warning(
                    f"EPL column shift detected for find {part['find_no']}: "
                    f"description '{part['description']}' looks like material. Swapping."
                )
                part["material"] = part["description"]
                part["description"] = ""

        # If PN contains a 5-char CAGE code suffix, strip it
        pn = part.get("part_number", "")
        pn_parts = pn.rsplit(" ", 1)
        if len(pn_parts) == 2:
            suffix = pn_parts[1]
            # CAGE codes: 5 chars, alphanumeric
            if len(suffix) == 5 and suffix.isalnum():
                LOGGER.info(f"Stripping CAGE code '{suffix}' from PN '{pn}'")
                if not part.get("cage_code"):
                    part["cage_code"] = suffix
                part["part_number"] = pn_parts[0]

    # Sort by find number (they come in reverse order from inverted table)
    parts.sort(key=lambda p: (p["find_no"], p.get("is_alternate", False)))

    return {
        "parts": parts,
        "count": len(parts),
        "max_find": max((p["find_no"] for p in parts), default=0),
    }


def _parse_epl_row(row: list, layout: Optional[dict] = None) -> Optional[dict]:
    """
    Parse a single EPL row into a structured part record.

    Uses dynamic column layout if provided, otherwise falls back to
    hardcoded NASA D-format layout.

    Args:
        row: Table row cells from pdfplumber
        layout: Optional column layout dict from _detect_epl_columns()
    """
    # Normalize: replace None with empty string
    cells = [str(c).strip() if c else "" for c in row]

    # Determine column indices
    if layout:
        # Dynamic layout from header detection
        find_col = layout["find_no"]
        pn_start = layout["part_number"]
        pn_end = layout.get("part_number_end", pn_start)
        cage_col = layout.get("cage_code")
        desc_col = layout.get("description")
        mat_col = layout.get("material")
        qty_cols = layout.get("qty_cols", [0, 1])
    else:
        # Hardcoded fallback (original layout)
        find_col = 3
        pn_start = 4
        pn_end = 6
        cage_col = 7
        desc_col = 8
        mat_col = 9
        qty_cols = [0, 1]

    # Bounds check
    if len(cells) <= find_col:
        return None

    # Extract find number
    find_str = cells[find_col] if find_col < len(cells) else ""
    try:
        find_no = int(find_str)
    except (ValueError, TypeError):
        return None  # Not a valid data row

    # Extract part number - span from pn_start to pn_end
    # BUT exclude CAGE code column if it falls in this range
    part_number_parts = []
    for i in range(pn_start, min(pn_end + 1, len(cells))):
        if cells[i]:
            # Don't include CAGE code column in PN
            if cage_col is not None and i == cage_col:
                continue
            # Don't include description column in PN
            if desc_col is not None and i == desc_col:
                continue
            part_number_parts.append(cells[i])
    part_number = " ".join(part_number_parts).strip()

    # Handle special cases where "part number" is just a note reference
    if not part_number:
        return None

    # Detect ALT rows
    is_alternate = False
    if qty_cols and qty_cols[0] < len(cells):
        is_alternate = cells[qty_cols[0]].upper() == "ALT"

    # Parse quantities for each dash number
    qty_003 = _parse_qty(cells[qty_cols[0]]) if qty_cols and qty_cols[0] < len(cells) and not is_alternate else ("ALT" if is_alternate else None)
    qty_001 = _parse_qty(cells[qty_cols[1]]) if len(qty_cols) > 1 and qty_cols[1] < len(cells) else None

    # Cage code
    cage_code = cells[cage_col] if cage_col is not None and cage_col < len(cells) else ""

    # Description - clean up special chars and newlines
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


def _parse_qty(val: str) -> Optional[int | str]:
    """Parse a quantity value. Can be int, 'AR', '-', or None."""
    if not val:
        return None
    val = val.strip()
    if val == "-":
        return "-"
    if val.upper() == "AR":
        return "AR"
    try:
        return int(val)
    except ValueError:
        return val


# ---------------------------------------------------------------------------
# BOM Table Parsing (GPE-style drawings)
# ---------------------------------------------------------------------------

# Column header variants for BOM tables
_BOM_HEADERS = {
    "item": ["ITEM", "ITEM NO", "ITEM NO.", "ITEM NUMBER", "NO", "NO."],
    "qty": ["QTY", "QTY.", "QUANTITY"],
    "material": ["MATERIAL", "MATL", "MAT'L", "MATERIAL/FINISH", "MAT/FINISH"],
    "lot_sn": ["LOT-S/N", "LOT/S/N", "LOT", "S/N", "SERIAL"],
    "description": ["DESCRIPTION", "DESC", "NOMENCLATURE", "NAME"],
}


def _find_bom_table(tables: list) -> Optional[tuple[list, dict]]:
    """
    Find BOM-style table with columns: ITEM NO., QTY, MATERIAL, etc.

    GPE drawings use this format instead of NASA's "MATERIAL:" notes.
    Returns (data_rows, column_map) or None.
    """
    if not tables:
        return None

    for table in tables:
        if not table:
            continue

        # Check first 5 rows for header row
        for row_idx, row in enumerate(table[:5]):
            if not row:
                continue

            row_upper = [str(c or "").upper().strip() for c in row]
            col_map = {}

            # Try to match each field to a column
            for field, variants in _BOM_HEADERS.items():
                for col_idx, cell in enumerate(row_upper):
                    if any(v in cell for v in variants):
                        col_map[field] = col_idx
                        break

            # Need at least ITEM and MATERIAL columns to be a valid BOM
            if "item" in col_map and "material" in col_map:
                data_rows = table[row_idx + 1:]  # Rows after header
                LOGGER.info(
                    f"[BOM] Found BOM table: {len(data_rows)} data rows, "
                    f"columns={list(col_map.keys())}"
                )
                return data_rows, col_map

    return None


def _parse_bom_materials(table: list, col_map: dict) -> list[dict]:
    """
    Extract material info from BOM table rows.

    Returns list of dicts with: item_no, material, description (if available)
    """
    materials = []
    mat_col = col_map["material"]
    item_col = col_map.get("item")
    desc_col = col_map.get("description")

    # Values to skip as "no material"
    skip_values = {"", "-", "N/A", "NA", "SEE NOTE", "SEE NOTES", "NONE", "TBD"}

    for row in table:
        if not row or len(row) <= mat_col:
            continue

        material = str(row[mat_col] or "").strip()
        if not material or material.upper() in skip_values:
            continue

        item_no = ""
        if item_col is not None and len(row) > item_col:
            item_no = str(row[item_col] or "").strip()

        description = ""
        if desc_col is not None and len(row) > desc_col:
            description = str(row[desc_col] or "").strip()

        materials.append({
            "item_no": item_no,
            "material": material,
            "description": description,
            "source": "BOM_TABLE",
        })

    if materials:
        LOGGER.info(f"[BOM] Extracted {len(materials)} materials from BOM table")

    return materials


def _extract_bom_material_from_text(full_text: str) -> Optional[dict]:
    """
    Fallback: extract BOM material from raw text when table detection fails.

    Some GPE PDFs have faint table lines that pdfplumber misses entirely.
    This scans raw text for BOM-style patterns:
        ITEM NO.  QTY  MATERIAL  LOT - S/N
        1         A/R  6061-T6

    Returns:
        {"designation": "6061-T6", "spec": "..."} or None
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

    # Material patterns to look for in data rows after header
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

    # Scan lines after header for material designations
    for i in range(header_idx + 1, min(header_idx + 10, len(lines))):
        line = lines[i].strip()
        if not line or len(line) < 3:
            continue

        for pattern in material_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                # Found material — extract the full material string
                parts = line.split()

                # Find which token matched and take it plus any following spec words
                for pi, part in enumerate(parts):
                    if re.search(pattern, part, re.IGNORECASE):
                        # Take from this token to end, then split off spec
                        material_str = " ".join(parts[pi:])

                        # Split designation from spec
                        spec = ""
                        spec_match = _SPEC_PATTERN.search(material_str)
                        if spec_match:
                            spec = material_str[spec_match.start():].strip()
                            designation = material_str[:spec_match.start()].strip().rstrip(",")
                        else:
                            designation = material_str.strip()

                        LOGGER.info(f"[BOM] Text fallback found material: {designation}")
                        return {
                            "designation": designation,
                            "spec": spec,
                            "source": "BOM_TEXT_FALLBACK",
                        }

    return None


# ---------------------------------------------------------------------------
# Title Block Parsing
# ---------------------------------------------------------------------------

def _parse_title_block(
    tables: list, full_text: str, notes: list[dict] = None
) -> dict:
    """
    Extract title block fields from the drawing.

    For detail drawings, also extracts:
    - Material designation (from MATERIAL note)
    - Material specification (AMS/ASTM/etc references from MATERIAL note)
    - UNS number (if present)
    - Process specification (from process-related notes)
    """
    tb = {}

    # --- DRAWING NUMBER ---
    for table in tables:
        for row in table:
            for cell in row:
                cell_str = str(cell) if cell else ""

                # Pattern: "DRAWING NUMBER\nMER..." in one cell
                if "DRAWING NUMBER" in cell_str:
                    lines = cell_str.split("\n")
                    for line in lines:
                        line = line.strip()
                        if line and line != "DRAWING NUMBER" and "REV" not in line:
                            if any(c.isdigit() for c in line):
                                tb["drawing_number"] = line.split()[0]
                                break

                # Pattern: "MODEL NUMBER MER07540-001"
                if "MODEL NUMBER" in cell_str and "drawing_number" not in tb:
                    parts = cell_str.split()
                    for i, p in enumerate(parts):
                        if p == "NUMBER" and i + 1 < len(parts):
                            candidate = parts[i + 1]
                            if any(c.isdigit() for c in candidate):
                                tb["drawing_number"] = candidate

    # --- NHA (Next Higher Assembly) ---
    # Generic detection: look for title block field labels like "NEXT ASSY USED ON" or "NHA"
    for table in tables:
        for ri, row in enumerate(table):
            for ci, cell in enumerate(row):
                cell_str = str(cell) if cell else ""
                cell_upper = cell_str.strip().upper()

                # Look for NHA field label in title block
                is_nha_label = (
                    ("NEXT" in cell_upper and "ASSY" in cell_upper) or  # "NEXT ASSY USED ON"
                    cell_upper == "NHA" or
                    cell_upper == "NEXT HIGHER ASSEMBLY"
                )

                if is_nha_label:
                    # NHA value is typically in an adjacent cell (before or after the label)
                    # Check cells after the label first
                    for j in range(ci + 1, len(row)):
                        nha_candidate = str(row[j]).strip() if row[j] else ""
                        if nha_candidate and nha_candidate.upper() not in ("FINAL", "NONE", "N/A", ""):
                            # Valid NHA: contains digits and is a reasonable part number length
                            if any(c.isdigit() for c in nha_candidate) and len(nha_candidate) > 3:
                                tb.setdefault("nha", nha_candidate)
                                break

                    # Also check cells before the label (some layouts put value first)
                    if "nha" not in tb:
                        for j in range(ci - 1, -1, -1):
                            nha_candidate = str(row[j]).strip() if row[j] else ""
                            if nha_candidate and nha_candidate.upper() not in ("FINAL", "NONE", "N/A", ""):
                                if any(c.isdigit() for c in nha_candidate) and len(nha_candidate) > 3:
                                    tb.setdefault("nha", nha_candidate)
                                    break

    # --- WEIGHT ---
    for table in tables:
        for row in table:
            for cell in row:
                cell_str = str(cell) if cell else ""
                if "LBS" in cell_str:
                    try:
                        weight = cell_str.split("LBS")[0].strip().split()[-1]
                        tb["weight_lbs"] = float(weight)
                    except (ValueError, IndexError):
                        pass

    # --- SHEET / TOTAL SHEETS ---
    for table in tables:
        for row in table:
            for cell in row:
                cell_str = str(cell) if cell else ""
                if "SHEET" in cell_str and "OF" in cell_str:
                    parts = cell_str.split()
                    for i, p in enumerate(parts):
                        if p == "OF" and i > 0 and i + 1 < len(parts):
                            try:
                                tb["sheet"] = int(parts[i - 1])
                                tb["total_sheets"] = int(parts[i + 1])
                            except (ValueError, IndexError):
                                pass

    # --- MATERIAL (from notes, detail drawings) ---
    # Phase 2: Split MATERIAL note into designation + spec + UNS
    for line in full_text.split("\n"):
        if "MATERIAL:" in line.upper() and "REMARKS" not in line.upper():
            content = line.split(":", 1)[1].strip().rstrip(".")

            # Split: designation is before first spec reference, spec is after
            spec_match = _SPEC_PATTERN.search(content)

            if spec_match:
                designation = content[:spec_match.start()].strip().rstrip(",").strip()
                spec = content[spec_match.start():].strip()
                tb.setdefault("material", designation)
                tb.setdefault("material_spec", spec)

                # Extract UNS number if present
                uns_match = re.search(r'UNS\s+([SNK]\d{5})', spec, re.IGNORECASE)
                if uns_match:
                    tb.setdefault("uns_number", uns_match.group(1).upper())
                    LOGGER.info(
                        f"Detail material: des={designation!r} spec={spec!r} "
                        f"UNS={uns_match.group(1)}"
                    )
                else:
                    LOGGER.info(
                        f"Detail material: des={designation!r} spec={spec!r}"
                    )
            else:
                # No spec references found — entire content is designation
                tb.setdefault("material", content)
                LOGGER.info(f"Detail material (no spec): des={content!r}")
            break  # Only use first MATERIAL note

    # --- BOM TABLE FALLBACK (GPE-style drawings) ---
    # If no material from "MATERIAL:" line, try BOM table
    if not tb.get("material"):
        bom_result = _find_bom_table(tables)
        if bom_result:
            bom_table, col_map = bom_result
            bom_materials = _parse_bom_materials(bom_table, col_map)
            if bom_materials:
                # Use first material entry (primary part material)
                first_mat = bom_materials[0]
                tb["material"] = first_mat["material"]
                tb["material_source"] = "BOM_TABLE"
                LOGGER.info(f"[TitleBlock] Material from BOM table: {tb['material']}")

                # Try to extract spec from material string
                spec_match = _SPEC_PATTERN.search(first_mat["material"])
                if spec_match:
                    designation = first_mat["material"][:spec_match.start()].strip().rstrip(",").strip()
                    spec = first_mat["material"][spec_match.start():].strip()
                    if designation:
                        tb["material"] = designation
                    tb["material_spec"] = spec

        # Text-based BOM fallback if table detection failed
        # (handles GPE PDFs with faint table lines that pdfplumber misses)
        if not tb.get("material"):
            bom_text = _extract_bom_material_from_text(full_text)
            if bom_text:
                tb["material"] = bom_text["designation"]
                tb["material_source"] = "BOM_TEXT_FALLBACK"
                if bom_text.get("spec"):
                    tb["material_spec"] = bom_text["spec"]
                LOGGER.info(f"[TitleBlock] Material from text fallback: {tb['material']}")

    # --- PROCESS SPEC (from notes, detail drawings) ---
    # Phase 2: Extract process specifications from numbered notes
    process_parts = []
    for line in full_text.split("\n"):
        stripped = line.strip().rstrip(".")
        if not stripped or len(stripped) < 15:
            continue

        # Check if this line contains a process keyword
        upper = stripped.upper()
        if any(kw in upper for kw in _PROCESS_KEYWORDS):
            # Skip lines that are about material (already handled above)
            if upper.startswith("MATERIAL") or "MATERIAL:" in upper:
                continue
            # Skip generic drawing prep notes
            if "DRAWING PREPARED" in upper:
                continue
            # Skip part identification notes
            if "IDENTIFY PART" in upper:
                continue

            # Remove leading note number (e.g., "5." or "7." or "5 .")
            cleaned = re.sub(r'^\d+\s*[\.\)]\s*', '', stripped)
            if cleaned and len(cleaned) > 10:
                process_parts.append(cleaned)

    if process_parts:
        # Deduplicate while preserving order
        seen = set()
        unique_parts = []
        for p in process_parts:
            key = p.upper()
            if key not in seen:
                seen.add(key)
                unique_parts.append(p)

        tb.setdefault("process_spec", "; ".join(unique_parts))
        LOGGER.info(f"Process specs found: {len(unique_parts)}")

    # --- CAGE CODE ---
    # CAGE codes are 5-character alphanumeric identifiers per DFARS/FAR
    # Generic detection: look for "CODE" or "CAGE" label and extract 5-char alphanumeric
    for table in tables:
        for row in table:
            for cell in row:
                cell_str = str(cell) if cell else ""
                cell_upper = cell_str.upper()
                if "CODE" in cell_upper or "CAGE" in cell_upper:
                    for word in cell_str.replace("\n", " ").split():
                        word = word.strip()
                        # CAGE codes are exactly 5 alphanumeric characters
                        if len(word) == 5 and word.isalnum() and word.upper() not in ("CODES", "CAGES"):
                            tb.setdefault("cage_code", word)
                            break

    # --- DESIGNER / ENGINEER ---
    for table in tables:
        for row in table:
            for i, cell in enumerate(row):
                cell_str = str(cell) if cell else ""
                if cell_str.strip().upper() == "DESIGNER":
                    for j in range(i + 1, len(row)):
                        val = str(row[j]).strip() if row[j] else ""
                        if val and val.upper() not in ("REVISIONS", "", "NONE"):
                            tb.setdefault("designer", val)
                            break
                if cell_str.strip().upper() == "ENGINEER":
                    for j in range(i + 1, len(row)):
                        val = str(row[j]).strip() if row[j] else ""
                        if val and val.upper() not in ("REVISIONS", "", "NONE"):
                            tb.setdefault("engineer", val)
                            break

    # Note: dedup is now applied globally in extract_drawing() before any parsing

    return tb


# ---------------------------------------------------------------------------
# Notes Parsing
# ---------------------------------------------------------------------------

def _parse_notes(full_text: str) -> list[dict]:
    """Extract numbered notes from the drawing text."""
    notes = []
    current_note = None
    current_text = []

    for line in full_text.split("\n"):
        stripped = line.strip()

        # Check for numbered note start: "1.", "2.", "10." etc at line start
        if stripped and stripped[0].isdigit():
            dot_pos = stripped.find(".")
            if dot_pos > 0 and dot_pos <= 3:
                try:
                    note_num = int(stripped[:dot_pos])
                    rest = stripped[dot_pos + 1:].strip()

                    # Save previous note
                    if current_note is not None:
                        notes.append({
                            "number": current_note,
                            "text": " ".join(current_text).strip(),
                        })

                    current_note = note_num
                    current_text = [rest] if rest else []
                    continue
                except ValueError:
                    pass

        # Continuation of current note
        if current_note is not None and stripped:
            if "ENGINEERING PARTS LIST" in stripped:
                break
            if "REVISIONS" in stripped:
                break
            if "INTERNATIONAL TRAFFIC" in stripped:
                break
            current_text.append(stripped)

    # Save last note
    if current_note is not None:
        notes.append({
            "number": current_note,
            "text": " ".join(current_text).strip(),
        })

    return notes


# ---------------------------------------------------------------------------
# CLI / Quick Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python text_extract.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    result = extract_drawing(pdf_path)

    print(f"\n{'='*70}")
    print(f"Drawing: {result['drawing_number']}")
    print(f"Type: {result['drawing_type']}")
    print(f"Pages: {result['pages']}")
    print(f"Source: {result['source']}")
    print(f"{'='*70}")

    # Title block
    print("\n--- TITLE BLOCK ---")
    for k, v in result["title_block"].items():
        print(f"  {k}: {v}")

    # EPL
    if result["has_epl"]:
        epl = result["epl"]
        print(f"\n--- ENGINEERING PARTS LIST ({epl['count']} parts, max find #{epl['max_find']}) ---")
        print(f"  {'Find':>4}  {'Part Number':<20}  {'Cage':>6}  {'Description':<50}  {'Material'}")
        print(f"  {'----':>4}  {'------------':<20}  {'----':>6}  {'-----------':<50}  {'--------'}")
        for p in epl["parts"]:
            alt = " (ALT)" if p["is_alternate"] else ""
            desc = p['description'][:50] if p['description'] else ""
            print(f"  {p['find_no']:>4}  {p['part_number']:<20}  {p['cage_code']:>6}  {desc:<50}  {p['material']}{alt}")
    else:
        print("\n--- NO EPL (Detail Drawing) ---")
        # Show detail drawing material info
        tb = result["title_block"]
        if tb.get("material"):
            print(f"  Designation:  {tb['material']}")
        if tb.get("material_spec"):
            print(f"  MatSpec:      {tb['material_spec']}")
        if tb.get("uns_number"):
            print(f"  UNS:          {tb['uns_number']}")
        if tb.get("process_spec"):
            print(f"  ProcSpec:     {tb['process_spec']}")
        if tb.get("nha"):
            print(f"  NHA:          {tb['nha']}")

    # Notes
    if result["notes"]:
        print(f"\n--- NOTES ({len(result['notes'])}) ---")
        for n in result["notes"]:
            text = n["text"][:100] + "..." if len(n["text"]) > 100 else n["text"]
            # Clean special chars for Windows console
            text = text.replace("\u2300", "DIA ")
            print(f"  {n['number']:>2}. {text}")

    print()
