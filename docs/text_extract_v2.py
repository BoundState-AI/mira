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
        all_text = page.extract_text() or ""
        tables = page.extract_tables()

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

        return {
            "drawing_number": title_block.get("drawing_number", "UNKNOWN"),
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


def _parse_epl_table(table: list) -> dict:
    """
    Parse an EPL table into structured parts data.

    The EPL table from pdfplumber comes in visual order (top-to-bottom),
    which for inverted EPLs means highest find number first.

    The last few rows are headers/labels:
        - "ENGINEERING PARTS LIST"
        - "QTY REQD"
        - Column headers (FIND NO., PART NUMBER, etc.)

    Data rows have this structure (by column index):
        [0] = QTY for dash -003 (or 'ALT')
        [1] = QTY for dash -001
        [2] = (usually empty spacer)
        [3] = FIND NO.
        [4] = PART NUMBER (primary)
        [5] = PART NUMBER (overflow - e.g., note callouts like "10.")
        [6] = PART NUMBER (overflow continued)
        [7] = CAGE CODE
        [8] = DESCRIPTION
        [9] = MATERIAL / REMARKS (REF)
    """
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

        part = _parse_epl_row(row)
        if part:
            # Skip DELETED rows
            desc = part.get("description", "").strip().upper()
            pn = part.get("part_number", "").strip().upper()
            if desc == "DELETED" or pn == "DELETED":
                LOGGER.info(f"Skipping DELETED row: PN={part.get('part_number')}")
                continue
            parts.append(part)

    # Sort by find number (they come in reverse order from inverted table)
    parts.sort(key=lambda p: (p["find_no"], p.get("is_alternate", False)))

    return {
        "parts": parts,
        "count": len(parts),
        "max_find": max((p["find_no"] for p in parts), default=0),
    }


def _parse_epl_row(row: list) -> Optional[dict]:
    """
    Parse a single EPL row into a structured part record.

    Column layout (10 columns for NASA D-format EPL):
        [0] = QTY for first dash number (e.g., -003) or 'ALT'
        [1] = QTY for second dash number (e.g., -001)
        [2] = (spacer, usually empty)
        [3] = FIND NO.
        [4] = PART NUMBER (primary field)
        [5] = PART NUMBER overflow (note callouts like "5.", "10.")
        [6] = (sometimes more overflow)
        [7] = CAGE CODE
        [8] = DESCRIPTION
        [9] = MATERIAL / REMARKS (REF)
    """
    # Normalize: replace None with empty string
    cells = [str(c).strip() if c else "" for c in row]

    # We need at least a find number (index 3)
    if len(cells) < 5:
        return None

    # Extract find number
    find_str = cells[3] if len(cells) > 3 else ""
    try:
        find_no = int(find_str)
    except (ValueError, TypeError):
        return None  # Not a valid data row

    # Extract part number - may span columns 4, 5, 6
    # Column 4 is primary. Columns 5-6 hold overflow (note refs like "10.")
    part_number_parts = []
    for i in [4, 5, 6]:
        if i < len(cells) and cells[i]:
            part_number_parts.append(cells[i])
    part_number = " ".join(part_number_parts).strip()

    # Handle special cases where "part number" is just a note reference
    if not part_number:
        return None

    # Detect ALT rows
    is_alternate = cells[0].upper() == "ALT" if cells[0] else False

    # Parse quantities for each dash number
    qty_003 = _parse_qty(cells[0]) if not is_alternate else "ALT"
    qty_001 = _parse_qty(cells[1]) if len(cells) > 1 else None

    # Cage code (column 7)
    cage_code = cells[7] if len(cells) > 7 and cells[7] else ""

    # Description (column 8) - clean up special chars and newlines
    description = cells[8] if len(cells) > 8 else ""
    description = description.replace("\n", " ").replace("\u2300", "DIA ").strip()
    while "  " in description:
        description = description.replace("  ", " ")

    # Material (column 9)
    material = cells[9] if len(cells) > 9 else ""
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
    for table in tables:
        for ri, row in enumerate(table):
            for ci, cell in enumerate(row):
                cell_str = str(cell) if cell else ""
                if cell_str.strip() == "DMLLV":
                    # NHA is typically in a cell before "DMLLV"
                    for j in range(ci):
                        nha_candidate = str(row[j]).strip() if row[j] else ""
                        if nha_candidate and nha_candidate.upper() != "FINAL":
                            if any(c.isdigit() for c in nha_candidate) and len(nha_candidate) > 3:
                                tb["nha"] = nha_candidate
                                break

                    # Title is usually further right in the same row
                    for j in range(ci + 1, len(row)):
                        title_candidate = str(row[j]).strip() if row[j] else ""
                        if title_candidate and title_candidate.upper() not in ("MATERIALS", ""):
                            if len(title_candidate) > 3 and not title_candidate.startswith("MATERIAL"):
                                tb["title"] = title_candidate.replace("\n", " ").strip()
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
    for table in tables:
        for row in table:
            for cell in row:
                cell_str = str(cell) if cell else ""
                if "CODE" in cell_str.upper() and "339B2" in cell_str:
                    tb["cage_code"] = "339B2"

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
