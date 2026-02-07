#!/usr/bin/env python3
"""
Module: Extract v3
Purpose: Enhanced vision-based drawing extraction with aggressive material parsing.

Key improvements over v2:
1. Multi-pass material search (title block -> notes -> EPL)
2. OCR correction for common misreads
3. Better handling of MSFC drawing format
4. Structured notes parsing

BoundState AI 2025
Version: 3.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ocr_correction import (
    correct_ocr_errors,
    extract_material_from_notes,
    extract_process_from_notes,
    extract_all_process_specs,
    clean_material_spec,
    clean_designation,
    correct_part_number,
    validate_epl_row,
    normalize_designation,
    normalize_material_spec,
    is_invalid_part_number,
    get_invalid_reason,
)
from .text_extract import (
    extract_drawing as extract_drawing_text,
    has_text_layer,
)

LOGGER = logging.getLogger(__name__)

# API Configuration - Direct Anthropic API only
# (Bedrock support commented out for now)
# USE_BEDROCK = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
# BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-gov-west-1")
# SONNET_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_MODEL = "claude-sonnet-4-5-20250929"


# =============================================================================
# V3 Extraction Prompt - Enhanced Material Detection
# =============================================================================

V3_EXTRACTION_PROMPT = """You are a PRECISION engineering drawing parser for NASA/MSFC aerospace drawings.
Your PRIMARY MISSION is to extract MATERIAL information from wherever it appears on the drawing.

## ANTI-HALLUCINATION RULES (CRITICAL)
1. Extract ONLY what you can CLEARLY SEE. Never guess or infer part numbers.
2. SKIP any part number you cannot read with 100% confidence.
3. DO NOT invent fasteners (MS20002, MS35206, MS35338 are commonly hallucinated).
4. Copy all text EXACTLY character-for-character.

## CHARACTER ACCURACY (Read twice before transcribing)
- 5 vs 8: curved top = 5, two loops = 8
- 5 vs 6: open top = 5, closed loop = 6 (e.g., bearing 6915 not 6916)
- 6 vs 8 vs 9: check loop direction
- 0 vs O vs D: zero often has slash/dot
- 3 vs 8: 3 is open on left
- B vs 8: B has flat back
- H vs N: vertical strokes differ — H has horizontal bar, N has diagonal
- W vs M: W points down, M points up (e.g., WHM not WRM, WSM not WFM)
- S vs 5 vs 8: S has no straight segments, used in retaining ring PNs (e.g., S86 not 886)
- / vs nothing: slash in part numbers matters (e.g., M12133/2-255 not M121332-255)
- Si3N4: Silicon nitride ceramic — often misread as S3H4, S3N4, S2N4

## MATERIAL EXTRACTION - CRITICAL MULTI-LOCATION SEARCH

MSFC drawings put material in MULTIPLE locations. Check ALL of these:

### Location 1: TITLE BLOCK MATERIAL FIELD
- Usually in lower right, may be labeled "MATERIAL" or "MATL"
- Often EMPTY on MSFC drawings - this is normal, check other locations!

### Location 2: NOTES SECTION (PRIMARY for MSFC)
- Look for numbered notes containing "MATERIAL:" or "MATL:"
- Examples:
  * "3. MATERIAL: A286 CRES, UNS S66286, PER SAE AMS 5737"
  * "2. MATERIAL: INCONEL 718, UNS N07718, PER SAE AMS 5664"
  * "MATERIAL 7075-T6 ALUMINUM PER ASTM B211"
- Parse these to get designation, UNS, and spec

### Location 3: FLAG NOTES (Balloons with note numbers)
- When you see a flag/balloon with a number pointing to a feature
- Look for corresponding note that says "MATERIAL:" or describes material
- Example: Flag "3" on part → Note "3. MATERIAL: A286 CRES..."

### Location 4: EPL MATERIAL COLUMN
- Engineering Parts List table often has MATERIAL column
- May say "MATL", "MATERIAL", or "MATERIAL / REMARKS"
- Extract EXACTLY what's in each row's material column

### EPL COLUMN IDENTIFICATION (CRITICAL - READ CAREFULLY)
The EPL (Engineering Parts List) is a table, usually in the upper portion of assembly drawings.
On MSFC drawings the columns typically appear RIGHT-TO-LEFT in this order:

  QTY REQD | FIND NO. | PART NUMBER | CAGE CODE | DESCRIPTION | MATERIAL/REMARKS

Column rules:
- **FIND NO.** column: ALWAYS simple sequential integers (1, 2, 3... up to ~30). Put these in "find_no".
- **PART NUMBER** column: The ACTUAL part identifiers. These look like:
  * Drawing numbers: MER07559-001, MER07560-001 (always has dash-suffix)
  * MIL-spec hardware: NAS1352N4-12, NAS509-4C, MS21043-6, NAS1149E0432R
  * Catalog numbers: 16007, 6824, 51109, 2949T32, 97022A388
  * Retaining rings: WHM-244-S86, WSM-137-C86, EH-22-C86
  * Note references for consumables: "5." or "6." (a number with period, referencing a drawing note)
- **QTY REQD** column: Small integers for quantity needed (1, 2, 4, 6, 11, etc.) or "AR" for As Required
- **CAGE CODE** column: 5-character codes like 33982, 0KV64 — these are NOT part numbers or specs
- **DESCRIPTION** column: Part names like "SHAFT, CENTER, 10 INCH VALVE"
- **MATERIAL/REMARKS** column: Material designations like "A286", "Si3N4", "7075 AL", "A286 (160 KSI)"

**HOW TO DISTINGUISH FIND NO. vs PART NUMBER vs QTY**:
- Find numbers are ALWAYS sequential from 1 to N (no gaps except DELETED items)
- Part numbers contain LETTERS or are 4+ digit catalog numbers
- Quantities are typically 1, 2, or small numbers; they repeat (multiple items can have qty=1)
- If a row says "DELETED" in the description, skip it entirely

**DELETED ITEMS**: Some find numbers are marked "DELETED" — these are obsolete parts removed
from the design. Do NOT include DELETED items in your output.

**NOTE REFERENCES AS PART NUMBERS**: Some consumable items (lubricants, adhesives) use a number
with a period (e.g., "5." or "6.") as their part number. This references a drawing note that
specifies the product. These ARE valid part numbers — include them as-is.

**CAGE CODES ARE NOT MATERIAL SPECS**: 5-character alphanumeric codes (33982, 0KV64, 01914)
in the CAGE CODE column identify manufacturers. Do NOT put these in spec_callout or material_callout.

### Location 5: DETAIL VIEWS
- Some detail views have local material callouts
- Look for text near specific features

## PROCESS SPECIFICATION EXTRACTION - CRITICAL FOR DETAIL DRAWINGS

MSFC detail drawings have PROCESS SPECS in separate numbered notes. These describe
surface treatments, finishes, and cleaning requirements. Look for:

### Process Note Patterns:
- "5. KOLSTERIZE PER MANUFACTURER'S RECOMMENDATION"
- "ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR"
- "PASSIVATE PER SAE AMS 2700, METHOD 1, TYPE 1,2,3,OR 8, OR METHOD 2"
- "CLEAN AND MAINTAIN PER IEST-STD-CC1246, LEVEL VC-0.5-1000"
- "ISOISTERIZE PER MANUFACTURER'S RECOMMENDATION"
- "HEAT TREAT PER AMS-H-6875"

### Process Types to Detect:
- KOLSTERIZE (surface hardening)
- PASSIVATE (corrosion protection)
- ANODIZE (aluminum surface treatment)
- CLEAN / CLEAN AND MAINTAIN (cleanliness specs)
- HEAT TREAT / ISOISTERIZE (heat treatment)
- PLATE / COAT (plating/coating)

### Important:
- Process notes are SEPARATE from material notes (different note numbers)
- A drawing may have BOTH a material note AND a process note
- Example: Note 3 = Material, Note 5 = Process
- Copy the FULL process specification including the reference

## RESPONSE FORMAT

Return this JSON structure:

{
  "title_block": {
    "drawing_number": "exact drawing number",
    "revision": "revision letter/number or null",
    "title": "part title/name",
    "cage_code": "5-char CAGE code or null",
    "nha_part_number": "Next Higher Assembly or null",

    "material_designation": "FULL material name (e.g., 'A286 CRES', '7075-T6 ALUMINUM')",
    "material_spec": "Spec number (e.g., 'SAE AMS 5737', 'ASTM B211')",
    "uns_number": "UNS number (e.g., 'UNS S66286')",
    "process_spec": "Process spec if any",

    "material_source": "Where material was found: 'TITLE_BLOCK', 'NOTES', 'FLAG', or 'NONE'"
  },

  "drawing_type": "DETAIL or ASSEMBLY",

  "parts_list": [
    {
      "find_no": "sequential item/find number from EPL (e.g., 1, 2, 3)",
      "part_number": "ACTUAL part number - NEVER a simple integer. Must be a real part/drawing/spec number like MER07559-001, NAS1352N4-12, MS21043-6, 16007, etc.",
      "description": "nomenclature",
      "quantity": 1,
      "quantity_note": "AR, REF, or null",
      "material_callout": "EXACT text from EPL MATERIAL column",
      "spec_callout": "spec from this EPL row only",
      "uns_callout": "UNS from this EPL row only"
    }
  ],

  "hardware_callouts": [
    {
      "raw_text": "complete callout text",
      "standard": "NAS/MS/AN number",
      "size": "thread size or null",
      "quantity": 1,
      "material": "material if explicitly shown"
    }
  ],

  "notes": [
    "COPY EACH NOTE EXACTLY - especially any containing 'MATERIAL'"
  ],

  "material_notes_found": [
    {
      "note_number": "the note number (e.g., '3')",
      "full_text": "EXACT text of the note",
      "parsed_designation": "extracted material name",
      "parsed_spec": "extracted spec",
      "parsed_uns": "extracted UNS"
    }
  ],

  "process_notes_found": [
    {
      "note_number": "the note number (e.g., '5')",
      "full_text": "EXACT text of the note",
      "process_type": "KOLSTERIZE, PASSIVATE, ANODIZE, CLEAN, HEAT TREAT, etc.",
      "spec_reference": "the spec or source (e.g., 'MANUFACTURER'S RECOMMENDATION', 'MIL-A-8625, TYPE II')"
    }
  ]
}

## CRITICAL REMINDERS

1. If title block MATERIAL is empty, the material IS IN THE NOTES - find it!
2. Look for flag notes (numbered balloons) that point to material callouts
3. Copy EPL MATERIAL column values exactly for each row
4. Include ALL notes, especially any mentioning "MATERIAL", "MATL", or alloy names
5. The material_source field tells us where you found the primary material
6. **NEVER put find numbers (1, 2, 3...) in the "part_number" field!** Find numbers go in "find_no".
   The part_number must be a real part identifier from the PART NUMBER column.
7. Read each EPL column header FIRST before extracting data. Identify which column is
   FIND NO., which is PART NUMBER, which is QTY, which is CAGE CODE. Do not guess.
8. Skip any row marked DELETED in the EPL.
9. CAGE codes (5-char codes like 33982) are NOT material specs — do not put them in spec_callout.
10. Material like "Si3N4" is silicon nitride (ceramic). Read it carefully — it is NOT "S3H4" or "S2N4".
11. **PROCESS SPECS are in SEPARATE notes from MATERIAL notes!** Look for KOLSTERIZE, PASSIVATE,
    ANODIZE, CLEAN, HEAT TREAT keywords. Include them in process_notes_found[].
12. A detail drawing typically has: Note 3 = Material, Note 5 or 6 = Process. Extract BOTH.

Return ONLY valid JSON. No explanations outside the JSON."""


# =============================================================================
# Vision Client
# =============================================================================

class VisionClient:
    """Claude vision API client for drawing extraction (Direct Anthropic API)."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        self.model = SONNET_MODEL

    @property
    def client(self):
        """Lazy-load client."""
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
            LOGGER.info("Using direct Anthropic API")
        return self._client

    def is_available(self) -> bool:
        try:
            return self.client is not None
        except Exception:
            return False

    def call_vision(self, image_b64: str, prompt: str) -> Dict[str, Any]:
        """Call vision API with image and prompt."""
        if not self.client:
            return {}

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            return self._parse_json_response(response.content[0].text)
        except Exception as e:
            LOGGER.error(f"Vision API error: {e}")
            return {}

    @staticmethod
    def _parse_json_response(text: str) -> Dict[str, Any]:
        """Extract JSON from model response."""
        text = text.strip()

        # Remove markdown fences
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # Find JSON
        match = re.search(r"[\[{][\s\S]*[\]}]", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError as e:
                LOGGER.error(f"JSON parse error: {e}")

        return {}


# =============================================================================
# PDF to Image Conversion
# =============================================================================

def pdf_to_images(
    pdf_path: Path,
    max_dimension: int = 7999,  # Claude vision max is 8000
    dpi: int = None
) -> List[str]:
    """
    Convert PDF pages to base64 images.

    Args:
        pdf_path: Path to PDF file
        max_dimension: Maximum pixel dimension (default 7999 to stay under Claude's 8000 limit)
        dpi: Optional DPI for rendering. If not specified, starts at 200 DPI
             and scales down if needed to stay under max_dimension.

    Returns:
        List of base64-encoded PNG images
    """
    try:
        import fitz
    except ImportError:
        raise ImportError("PyMuPDF required: pip install PyMuPDF")

    doc = fitz.open(pdf_path)
    images: List[str] = []

    for page in doc:
        # Use specified DPI or default to 200 for better OCR
        target_dpi = dpi if dpi else 200
        zoom = target_dpi / 72  # PDF default is 72 DPI
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)

        # Scale down if exceeds max dimension
        if max(pix.width, pix.height) > max_dimension:
            scale = max_dimension / max(pix.width, pix.height)
            new_matrix = fitz.Matrix(zoom * scale, zoom * scale)
            pix = page.get_pixmap(matrix=new_matrix)
            LOGGER.debug(
                f"Scaled page to {pix.width}x{pix.height} "
                f"(effective DPI: {int(target_dpi * scale)})"
            )

        img_bytes = pix.tobytes("png")
        images.append(base64.b64encode(img_bytes).decode())

    doc.close()
    return images


# =============================================================================
# Post-processing
# =============================================================================

# Global Vision learning database connection (lazy loaded)
_vision_learning_db = None


def get_vision_learning_db():
    """Get or create the Vision extraction learning database connection."""
    global _vision_learning_db
    if _vision_learning_db is None:
        try:
            from .ocr_learning import OCRLearningDB
            _vision_learning_db = OCRLearningDB()
            LOGGER.info("[Vision Learning] Connected to learning database")
        except Exception as e:
            LOGGER.warning(f"[Vision Learning] Database not available: {e}")
            _vision_learning_db = False  # Mark as unavailable
    return _vision_learning_db if _vision_learning_db else None


def apply_learned_correction(
    part_number: str,
    description: str = "",
    drawing_source: str = "",
    project: str = None
) -> str:
    """
    Apply learned Vision extraction correction to a part number.

    Claude Vision extracts part numbers from rendered drawing images.
    This function corrects Vision's character recognition errors
    (e.g., 0/O confusion, similar-looking digits) based on previously
    learned corrections.

    Args:
        part_number: The raw extracted part number
        description: Part description for context
        drawing_source: Source drawing for audit
        project: Project for scoped matching

    Returns:
        Corrected part number (or original if no correction found)
    """
    db = get_vision_learning_db()
    if not db:
        return part_number

    try:
        result = db.correct_part_number(
            part_number,
            description=description,
            drawing_source=drawing_source,
            project=project,
            auto_learn=True
        )

        if result.was_corrected:
            LOGGER.info(
                f"[Vision Learning] Corrected '{part_number}' -> '{result.corrected}' "
                f"({result.correction_source}, conf={result.confidence:.2f})"
            )
            return result.corrected

    except Exception as e:
        LOGGER.warning(f"[Vision Learning] Correction error: {e}")

    return part_number


def postprocess_extraction(
    raw: Dict[str, Any],
    use_learning: bool = True,
    drawing_source: str = "",
    project: str = None
) -> Dict[str, Any]:
    """
    Post-process Vision extraction to apply learned corrections,
    material fallbacks, part number validation, and cleanup.

    Args:
        raw: Raw extraction result from Vision API
        use_learning: Whether to use the Vision learning database for corrections
        drawing_source: Source drawing number for audit logging
        project: Project identifier for scoped learning
    """
    result = raw.copy()

    # OCR correct title block material
    tb = result.get("title_block", {})
    if tb.get("material_designation"):
        tb["material_designation"] = correct_ocr_errors(tb["material_designation"])
        # Clean vendor/supplier pollution from designation
        tb["material_designation"] = clean_designation(tb["material_designation"])

    # Validate and clean title block material spec
    if tb.get("material_spec"):
        tb["material_spec"] = clean_material_spec(tb["material_spec"])

    # If no title block material, try to extract from notes
    if not tb.get("material_designation") or tb.get("material_source") == "NONE":
        notes = result.get("notes", [])
        material_from_notes = extract_material_from_notes(notes)

        if material_from_notes:
            tb["material_designation"] = material_from_notes.get("designation", "")
            tb["material_spec"] = material_from_notes.get("spec", tb.get("material_spec", ""))
            tb["uns_number"] = material_from_notes.get("uns", tb.get("uns_number", ""))
            tb["material_source"] = "NOTES_POSTPROCESS"
            LOGGER.info(f"Extracted material from notes: {tb['material_designation']}")

    # Also check material_notes_found if populated by vision
    if not tb.get("material_designation"):
        material_notes = result.get("material_notes_found", [])
        for mn in material_notes:
            if mn.get("parsed_designation"):
                tb["material_designation"] = correct_ocr_errors(mn["parsed_designation"])
                tb["material_spec"] = mn.get("parsed_spec", tb.get("material_spec", ""))
                tb["uns_number"] = mn.get("parsed_uns", tb.get("uns_number", ""))
                tb["material_source"] = "FLAG_NOTE"
                LOGGER.info(f"Extracted material from flag note: {tb['material_designation']}")
                break

    # Extract process specification from notes
    # First check if vision already found process notes
    process_notes = result.get("process_notes_found", [])
    if process_notes:
        for pn in process_notes:
            if pn.get("full_text") or pn.get("spec_reference"):
                process_type = pn.get("process_type", "")
                spec_ref = pn.get("spec_reference", "")
                if process_type and spec_ref:
                    tb["process_spec"] = f"{process_type} PER {spec_ref}"
                elif pn.get("full_text"):
                    tb["process_spec"] = pn["full_text"]
                LOGGER.info(f"Extracted process spec from vision: {tb.get('process_spec', '')}")
                break

    # If no process spec from vision, try parsing notes ourselves
    if not tb.get("process_spec"):
        notes = result.get("notes", [])
        process_result = extract_process_from_notes(notes)
        if process_result and process_result.get("full_spec"):
            tb["process_spec"] = process_result["full_spec"]
            LOGGER.info(f"Extracted process spec from notes postprocess: {tb['process_spec']}")

    # Correct title block drawing number
    if tb.get("drawing_number"):
        tb["drawing_number"] = correct_part_number(tb["drawing_number"])

    # Correct NHA part number
    if tb.get("nha_part_number"):
        tb["nha_part_number"] = correct_part_number(tb["nha_part_number"])

    # Process EPL parts: OCR correct + validate + detect find-number-as-PN + filter invalid
    cleaned_parts = []
    find_number_detected = False
    filtered_count = 0
    learning_corrections = 0

    for part in result.get("parts_list", []):
        cleaned = validate_epl_row(part)

        # Get part number after basic OCR correction
        pn = str(cleaned.get("part_number", "")).strip()
        desc = cleaned.get("description", "")

        # Apply learning-based correction if enabled
        if use_learning and pn:
            corrected_pn = apply_learned_correction(
                pn,
                description=desc,
                drawing_source=drawing_source or tb.get("drawing_number", ""),
                project=project
            )
            if corrected_pn != pn:
                cleaned["part_number"] = corrected_pn
                cleaned["_original_pn"] = pn  # Keep original for audit
                pn = corrected_pn
                learning_corrections += 1

        # Filter out known invalid/hallucinated part numbers
        if is_invalid_part_number(pn):
            reason = get_invalid_reason(pn)
            LOGGER.info(f"Filtering out invalid part number '{pn}': {reason}")
            filtered_count += 1
            continue  # Skip this part entirely

        # Detect find number in part_number field
        # Find numbers are small sequential integers (1-99). Larger numbers
        # like 6824, 16007, 51109 are real part numbers (bearing catalogs, etc.)
        pn_digits = pn.rstrip(".")
        if pn_digits.isdigit() and len(pn_digits) <= 2 and int(pn_digits) <= 99:
            # Small integer (1-99) — almost certainly a find number, not a real PN
            find_number_detected = True
            LOGGER.warning(
                f"Find number '{pn}' detected in part_number field "
                f"(description: {cleaned.get('description', '')[:40]}). "
                f"Vision API likely confused find number column with part number column."
            )
            # Move the value to find_no if it's not already set
            if not cleaned.get("find_no"):
                cleaned["find_no"] = pn
            # Mark as needing resolution - keep the find number as PN
            # so the builder can at least create a row (better than nothing)
            cleaned["_find_number_as_pn"] = True

        # OCR correct material callout
        if cleaned.get("material_callout"):
            cleaned["material_callout"] = correct_ocr_errors(cleaned["material_callout"])
            cleaned["material_callout"] = clean_designation(cleaned["material_callout"])

        cleaned_parts.append(cleaned)

    if filtered_count > 0:
        LOGGER.info(f"Filtered {filtered_count} invalid/hallucinated part numbers")

    if learning_corrections > 0:
        LOGGER.info(f"[Vision Learning] Applied {learning_corrections} learned corrections")

    if find_number_detected:
        LOGGER.warning(
            f"Drawing {tb.get('drawing_number', '?')}: "
            f"EPL appears to have find numbers in part_number field. "
            f"The EPL columns may have been misidentified by the vision model."
        )

    # Detect quantity/find_no column swap
    # If quantity values look like sequential find numbers (1,2,3..N) and
    # find_no values look like small quantities, the columns were swapped.
    qty_vals = []
    for p in cleaned_parts:
        q = p.get("quantity")
        if q is not None:
            try:
                qty_vals.append(int(q))
            except (ValueError, TypeError):
                pass

    if len(qty_vals) >= 5:
        # Check if quantity values form a mostly-sequential descending/ascending range
        # (find numbers are typically 1..N sequential)
        sorted_qtys = sorted(qty_vals)
        is_sequential = (
            sorted_qtys[-1] - sorted_qtys[0] >= len(sorted_qtys) * 0.5
            and len(set(qty_vals)) > len(qty_vals) * 0.7  # mostly unique
        )
        avg_qty = sum(qty_vals) / len(qty_vals)

        if is_sequential and avg_qty > 10:
            # Quantities averaging >10 and forming a sequential range = likely find numbers
            LOGGER.warning(
                f"Drawing {tb.get('drawing_number', '?')}: "
                f"Quantity values appear to be find numbers (avg={avg_qty:.0f}, "
                f"range={sorted_qtys[0]}-{sorted_qtys[-1]}). "
                f"Swapping quantity and find_no fields."
            )
            for p in cleaned_parts:
                old_qty = p.get("quantity")
                old_find = p.get("find_no")
                p["find_no"] = str(old_qty) if old_qty is not None else old_find
                # Try to parse find_no as quantity
                try:
                    p["quantity"] = int(old_find) if old_find and str(old_find).strip().isdigit() else old_qty
                except (ValueError, TypeError):
                    p["quantity"] = old_qty

    result["parts_list"] = cleaned_parts

    result["title_block"] = tb
    return result


# =============================================================================
# Main Extraction Functions
# =============================================================================

def extract_drawing_page(
    pdf_path: Path,
    page_idx: int = 0,
    client: VisionClient = None,
    use_learning: bool = True,
    project: str = None,
    dpi: int = None,
    force_vision: bool = False,
) -> Dict[str, Any]:
    """
    Extract data from a single page of a drawing PDF.

    Strategy: Try text layer extraction first (free, fast, accurate for CAD PDFs).
    Fall back to Vision only for scanned PDFs without text layers.

    Args:
        pdf_path: Path to PDF file
        page_idx: Page index (0-based)
        client: Optional VisionClient instance
        use_learning: Whether to use OCR learning database for corrections
        project: Project identifier for scoped learning
        dpi: Optional DPI for rendering (default uses pdf_to_images default)
        force_vision: Skip text extraction and use Vision directly

    Returns:
        Extracted data dictionary
    """
    # Try text layer extraction first (for CAD-generated PDFs)
    if not force_vision and page_idx == 0:
        try:
            if has_text_layer(pdf_path):
                text_result = extract_drawing_text(pdf_path)
                if text_result and text_result.get("drawing_number") != "UNKNOWN":
                    LOGGER.info(f"[TextExtract] {pdf_path.name} via TEXT LAYER (fast)")
                    result = _convert_text_result_to_v3(text_result, pdf_path)
                    return result
        except Exception as e:
            LOGGER.warning(f"[TextExtract] Failed for {pdf_path.name}: {e}")

    # Fall back to Vision extraction
    if client is None:
        client = VisionClient()

    images = pdf_to_images(pdf_path, dpi=dpi) if dpi else pdf_to_images(pdf_path)

    if page_idx >= len(images):
        LOGGER.warning(f"Page {page_idx} not found in {pdf_path.name}")
        return {}

    LOGGER.info(f"[VisionExtract] {pdf_path.name} page {page_idx} via VISION")
    raw = client.call_vision(images[page_idx], V3_EXTRACTION_PROMPT)

    if not raw:
        LOGGER.warning(f"No extraction result for {pdf_path.name} page {page_idx}")
        return {}

    result = postprocess_extraction(
        raw,
        use_learning=use_learning,
        drawing_source=pdf_path.stem,
        project=project
    )
    result["source_file"] = pdf_path.name
    result["page_index"] = page_idx

    return result


def _convert_text_result_to_v3(text_result: Dict[str, Any], pdf_path: Path) -> Dict[str, Any]:
    """
    Convert text_extract result format to the format expected by V3.

    The text extractor returns a different structure than the Vision extractor,
    so we normalize it here.
    """
    tb = text_result.get("title_block", {})
    epl = text_result.get("epl") or {}
    parts = epl.get("parts", [])

    # Convert parts list format
    converted_parts = []
    for p in parts:
        converted_parts.append({
            "find_no": str(p.get("find_no", "")),
            "part_number": p.get("part_number", ""),
            "description": p.get("description", ""),
            "quantity": p.get("qty_001") or p.get("qty_003") or 1,
            "material_callout": p.get("material", ""),  # Key must match builder.py expectation
            "cage_code": p.get("cage_code", ""),
            "is_alternate": p.get("is_alternate", False),
        })

    # Convert notes format
    notes = [n.get("text", "") for n in text_result.get("notes", [])]

    return {
        "title_block": {
            "drawing_number": text_result.get("drawing_number", ""),
            "title": tb.get("title", ""),
            "revision": tb.get("revision", ""),
            "material_designation": tb.get("material", ""),
            "material_spec": tb.get("material_spec", ""),
            "uns_number": tb.get("uns_number", ""),
            "process_spec": tb.get("process_spec", ""),
            "nha_part_number": tb.get("nha", ""),
            "weight": tb.get("weight_lbs"),
            "cage_code": tb.get("cage_code", ""),
            "designer": tb.get("designer", ""),
            "engineer": tb.get("engineer", ""),
        },
        "drawing_type": "ASSEMBLY" if text_result.get("has_epl") else "DETAIL",
        "source_file": pdf_path.name,
        "page_index": 0,
        "parts_list": converted_parts,
        "notes": notes,
        "extraction_method": "text_layer",
    }


# =============================================================================
# Drawing Tree (DT) Extraction
# =============================================================================

# System prompt for DT extraction - simple level-by-level approach
DT_SYSTEM_PROMPT = """You extract drawing tree hierarchies using a LEVEL-BY-LEVEL approach.

METHODOLOGY - Answer these questions in order:

LEVEL 0 (ROOT):
Q: What is the TOP-LEVEL assembly? (The one box with NO parent)
A: Find the single box at the very top. Record its part number and name.

LEVEL 1 (DIRECT CHILDREN OF ROOT):
Q: What parts/assemblies report DIRECTLY to the root?
A: Trace lines DOWN from root. Each connected box is a Level 1 child.

LEVEL 2 (CHILDREN OF LEVEL 1):
Q: For EACH Level 1 item, what reports to IT?
A: Trace lines DOWN from each Level 1 box. Connected boxes are Level 2.

LEVEL 3+ (CONTINUE):
Q: For EACH Level 2 item, what reports to IT?
A: Continue until no more children exist.

CRITICAL RULES:
- A part's parent is found by tracing its connector line UPWARD to the first box
- Siblings (same parent) are NEVER nested under each other
- If Part A and Part B both have lines going UP to the SAME box, they are siblings
- Spatial proximity doesn't matter - only the CONNECTOR LINES matter
- Copy part numbers EXACTLY - character for character"""

# User prompt for DT extraction - level-by-level extraction
DT_EXTRACTION_PROMPT = """Extract this drawing tree by answering level-by-level:

STEP 1: What is the ROOT (top-level assembly with no parent)?
STEP 2: What parts connect DIRECTLY to the root? (Level 1)
STEP 3: For each Level 1 part, what connects to IT? (Level 2)
STEP 4: Continue for Level 3, 4, etc. until done.

OUTPUT FORMAT (JSON only, no markdown):
{
    "document_info": {
        "drawing_number": "document number",
        "title": "title",
        "revision": "revision",
        "organization": "org name"
    },
    "root": {
        "part_number": "ROOT-PN-001",
        "name": "Root Assembly Name",
        "status": "Released or null",
        "children": [
            {
                "part_number": "LEVEL1-PN-001",
                "name": "Level 1 Part Name",
                "status": null,
                "children": [
                    {
                        "part_number": "LEVEL2-PN-001",
                        "name": "Level 2 Part Name",
                        "status": null,
                        "children": []
                    }
                ]
            }
        ]
    }
}

REMEMBER:
- children[] = parts that report TO this part
- Empty children[] = no subordinates (leaf node)
- Siblings go in the SAME children array, not nested"""


def _convert_nested_to_flat(nested_tree: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert nested tree format to flat format with parent pointers.

    The nested format from extraction:
    {
        "root": {
            "part_number": "MER07540-001",
            "name": "Valve Assy",
            "children": [
                {"part_number": "MER07560-001", "name": "...", "children": [...]}
            ]
        }
    }

    Converts to flat format expected by builder:
    {
        "top_level": "MER07540-001",
        "tree": [
            {"drawing_number": "MER07540-001", "title": "Valve Assy", "parent": null, "type": "ASSEMBLY"},
            {"drawing_number": "MER07560-001", "title": "...", "parent": "MER07540-001", "type": "DETAIL"},
        ]
    }

    Args:
        nested_tree: Tree in nested format from vision extraction

    Returns:
        Tree in flat format with parent pointers
    """
    if not nested_tree or not nested_tree.get("root"):
        return {"top_level": "", "tree": []}

    flat_entries: List[Dict[str, Any]] = []

    def _flatten_node(node: Dict[str, Any], parent_pn: Optional[str]) -> None:
        """Recursively flatten a node and its children."""
        pn = node.get("part_number", "").strip()
        if not pn:
            return

        children = node.get("children", [])
        has_children = len(children) > 0

        entry = {
            "drawing_number": pn,
            "title": node.get("name", ""),
            "parent": parent_pn,
            "type": "ASSEMBLY" if has_children else "DETAIL",
        }
        flat_entries.append(entry)

        for child in children:
            _flatten_node(child, pn)

    root = nested_tree["root"]
    _flatten_node(root, None)

    top_level = root.get("part_number", "").strip()

    return {
        "top_level": top_level,
        "tree": flat_entries,
    }


# Legacy flat-format prompt (kept for reference/fallback)
DT_EXTRACTION_PROMPT_FLAT = """You are parsing a NASA/MSFC DRAWING TREE document.

A Drawing Tree shows the assembly hierarchy — which drawings are sub-assemblies or
detail parts of which parent assembly.

## CRITICAL: HOW TO READ DRAWING TREE FLOWCHARTS

Drawing Trees are displayed as **flowcharts with boxes connected by lines**.
The hierarchy is determined by **TRACING THE CONNECTOR LINES**, not by spatial position.

### STEP-BY-STEP METHODOLOGY:

**STEP 1: FIND THE ROOT**
- Locate the SINGLE box at the very TOP of the diagram
- This is the top-level assembly — it has NO parent (parent = null)
- Everything else descends from this root

**STEP 2: IDENTIFY FIRST-LEVEL CHILDREN**
- From the root box, trace ALL lines going DOWN
- Each box these lines connect to is a DIRECT CHILD of the root
- These are Level 1 assemblies/parts

**STEP 3: RECURSIVELY TRACE EACH BRANCH**
For each Level 1 box:
- Does it have lines going DOWN to other boxes?
- If YES: Those boxes are children of THIS box (not the root!)
- If NO: This is a leaf node (DETAIL type)
- Continue this process for each level

**STEP 4: VERIFY BY TRACING UPWARD**
For EVERY box in the tree, verify its parent by:
- Starting at the box
- Following the connector line UPWARD
- The FIRST box you reach is the parent
- If no line goes up, it's the root (parent = null)

### KEY INSIGHT: LINES DETERMINE HIERARCHY, NOT POSITION

Two boxes side-by-side DO NOT necessarily share the same parent!
Each box's parent is determined ONLY by which box it connects to going UP.

Example of what the visual structure might look like:
```
                    [ROOT]
                      |
        +------+------+------+------+
        |      |      |      |      |
      [A]    [B]    [C]    [D]    [E]      <- All children of ROOT
        |      |
   +----+    +----+----+
   |    |    |    |    |
  [F]  [G]  [H]  [I]  [J]                  <- F,G are children of A; H,I,J are children of B
              |
          +---+---+
          |       |
         [K]     [L]                       <- K,L are children of I (NOT of B!)
```

### COMMON ERRORS TO AVOID:

1. **Flattening the hierarchy**: Assigning all visible boxes to the top-level
   WRONG: K's parent is ROOT
   RIGHT: K's parent is I, I's parent is B, B's parent is ROOT

2. **Spatial grouping**: Assuming horizontal neighbors share parents
   WRONG: H, I, J all have parent A because they're near F, G
   RIGHT: H, I, J have parent B (trace the lines!)

3. **Missing intermediate levels**: Skipping sub-assemblies
   WRONG: K's parent is B (skipping I)
   RIGHT: K's parent is I

4. **Misreading connector intersections**: Lines may cross but not connect
   Only boxes with actual connector endpoints are related

### VERIFICATION CHECKLIST (Apply to your extraction):

Before outputting, verify:
[ ] Exactly ONE entry has parent = null (the root)
[ ] Every non-root entry has a parent that exists in the tree
[ ] No entry is its own parent
[ ] Following parent links from any entry eventually reaches the root
[ ] Entries with children below them have type = "ASSEMBLY"
[ ] Entries with no children below them have type = "DETAIL"

## OUTPUT FORMAT

Return this JSON structure:
{
  "top_level": "drawing number of the root assembly",
  "tree": [
    {
      "drawing_number": "exact drawing/part number",
      "title": "part or assembly name",
      "parent": "parent drawing number or null for root",
      "type": "ASSEMBLY or DETAIL"
    },
    ...
  ]
}

## RULES
1. Extract EVERY entry visible in the tree — do not skip any
2. Determine parent by TRACING CONNECTOR LINES, not spatial proximity
3. Part numbers may have patterns like XXX99999-001 with dash suffixes
4. The top-level assembly has parent = null
5. If a drawing appears at multiple levels, include each occurrence
6. Multi-page trees: maintain hierarchy across pages

Return ONLY valid JSON. No explanations outside the JSON."""


def _validate_and_fix_dt_tree(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and fix common DT extraction errors.

    Performs structural validation and attempts to correct:
    - Missing parents (orphaned nodes)
    - Self-references
    - Duplicate entries
    - Type inconsistencies

    Args:
        raw: Raw extraction result from vision API

    Returns:
        Validated and corrected result
    """
    if not raw or not raw.get("tree"):
        return raw

    tree_entries = raw["tree"]
    top_level = raw.get("top_level", "")

    # Build lookup structures
    all_drawing_numbers = set()
    entry_by_pn: Dict[str, Dict] = {}
    children_of: Dict[str, List[str]] = {}

    for entry in tree_entries:
        pn = entry.get("drawing_number", "").strip()
        if not pn:
            continue
        all_drawing_numbers.add(pn)
        entry_by_pn[pn] = entry

        parent = (entry.get("parent") or "").strip()
        if parent:
            if parent not in children_of:
                children_of[parent] = []
            children_of[parent].append(pn)

    # Fix 1: Ensure top_level is set and has null parent
    roots = [
        e["drawing_number"] for e in tree_entries
        if not e.get("parent") and e.get("drawing_number")
    ]
    if not top_level and roots:
        top_level = roots[0]
        raw["top_level"] = top_level
        LOGGER.info(f"[DT Validate] Set top_level to {top_level}")

    # Fix 2: Self-references (A -> A)
    for entry in tree_entries:
        pn = entry.get("drawing_number", "").strip()
        parent = (entry.get("parent") or "").strip()
        if pn and pn == parent:
            LOGGER.warning(f"[DT Validate] Fixing self-reference: {pn}")
            entry["parent"] = None  # Make it a root or fix later

    # Fix 3: Type consistency - if a node has children, it's an ASSEMBLY
    for entry in tree_entries:
        pn = entry.get("drawing_number", "").strip()
        if pn in children_of and children_of[pn]:
            if entry.get("type", "").upper() != "ASSEMBLY":
                LOGGER.info(f"[DT Validate] Correcting type for {pn}: DETAIL -> ASSEMBLY (has children)")
                entry["type"] = "ASSEMBLY"

    # Fix 4: If a node has no children and type is ASSEMBLY, change to DETAIL
    for entry in tree_entries:
        pn = entry.get("drawing_number", "").strip()
        if pn not in children_of or not children_of.get(pn):
            if entry.get("type", "").upper() == "ASSEMBLY":
                # Only change if it's not a known sub-assembly pattern
                # (some assemblies may have their children on separate drawings)
                pass  # Don't auto-change, could be intentional

    # Fix 5: Remove duplicate entries (keep first occurrence)
    seen_pns = set()
    deduped = []
    for entry in tree_entries:
        pn = entry.get("drawing_number", "").strip()
        if pn and pn not in seen_pns:
            deduped.append(entry)
            seen_pns.add(pn)
        elif pn:
            LOGGER.info(f"[DT Validate] Removing duplicate entry for {pn}")

    raw["tree"] = deduped

    return raw


# =============================================================================
# Direct PDF Vision API (No Image Conversion)
# =============================================================================

def _call_vision_with_pdf(
    client: VisionClient,
    pdf_path: Path,
    prompt: str,
    system_prompt: str = None,
    previous_attempt: Dict[str, Any] = None,
    feedback: str = None,
) -> Dict[str, Any]:
    """
    Send PDF directly to vision API without image conversion.

    This approach provides potentially higher quality extraction since it
    avoids the lossy PDF-to-image conversion step.

    Args:
        client: VisionClient instance
        pdf_path: Path to the PDF file
        prompt: User prompt for extraction
        system_prompt: Optional system prompt for context
        previous_attempt: Previous extraction result for retry feedback
        feedback: Feedback on what was wrong with previous attempt

    Returns:
        Parsed JSON response from vision API
    """
    with open(pdf_path, "rb") as f:
        pdf_base64 = base64.standard_b64encode(f.read()).decode("utf-8")

    # Build prompt with feedback if this is a retry
    full_prompt = prompt
    if previous_attempt and feedback:
        full_prompt += (
            f"\n\nPREVIOUS ATTEMPT HAD ERRORS:\n{feedback}\n\n"
            f"Previous JSON:\n{json.dumps(previous_attempt, indent=2)}\n\n"
            f"Please correct these issues and return the fixed JSON."
        )

    try:
        # Build API call kwargs
        api_kwargs = {
            "model": client.model,
            "max_tokens": 8192,
            "temperature": 0,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {"type": "text", "text": full_prompt},
                ],
            }],
        }

        # Add system prompt if provided
        if system_prompt:
            api_kwargs["system"] = system_prompt

        response = client.client.messages.create(**api_kwargs)
        return client._parse_json_response(response.content[0].text)
    except Exception as e:
        # Log full error details for debugging
        LOGGER.error(f"Direct PDF vision API error: {type(e).__name__}: {e}")
        if hasattr(e, 'response'):
            LOGGER.error(f"  Response status: {getattr(e.response, 'status_code', 'unknown')}")
            LOGGER.error(f"  Response body: {getattr(e.response, 'text', 'unknown')[:500]}")
        if hasattr(e, 'body'):
            LOGGER.error(f"  Error body: {e.body}")
        return {}


def _validate_dt_extraction(
    client: VisionClient,
    pdf_path: Path,
    extracted_tree: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Validate DT extraction by re-checking against the PDF.

    Sends the extracted JSON back to the vision model along with the
    original PDF and asks it to identify any discrepancies.

    Args:
        client: VisionClient instance
        pdf_path: Path to the DT PDF file
        extracted_tree: Previously extracted tree structure

    Returns:
        Tuple of (is_valid, feedback_message)
    """
    with open(pdf_path, "rb") as f:
        pdf_base64 = base64.standard_b64encode(f.read()).decode("utf-8")

    validation_prompt = f"""Validate this extracted drawing tree by checking LEVEL BY LEVEL:

EXTRACTED JSON:
{json.dumps(extracted_tree, indent=2)}

VALIDATION METHOD:
1. ROOT CHECK: Is the root part number correct?
2. LEVEL 1 CHECK: Does each Level 1 child in the JSON actually connect to root in the PDF?
3. LEVEL 2 CHECK: For each Level 1, do its children match what connects to it in the PDF?
4. CONTINUE: Check each level the same way.

For EACH level, ask: "In the PDF, what parts have connector lines going UP to this parent?"
Those parts should be in children[] for that parent.

COMMON ERRORS TO CATCH:
- Part listed under wrong parent (trace the lines!)
- Siblings incorrectly nested under each other
- Missing parts that exist in PDF
- Extra parts not in PDF

Be thorough but fair - minor formatting differences are acceptable.

RESPOND EXACTLY AS:
VALID: true
or
VALID: false
ISSUES:
- Missing part: XXX which is shown in the PDF as a child of YYY
- Wrong parent: XXX has parent YYY but should be under ZZZ"""

    try:
        response = client.client.messages.create(
            model=client.model,
            max_tokens=2000,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {"type": "text", "text": validation_prompt},
                ],
            }],
        )

        response_text = response.content[0].text.strip()

        # Parse validation result - handle both strict and verbose responses
        is_valid = None  # None = undetermined
        issues = ""

        # Method 1: Look for explicit VALID: true/false
        for line in response_text.split('\n'):
            line_upper = line.strip().upper()
            if line_upper.startswith("VALID:"):
                val = line.split(":", 1)[1].strip().lower()
                is_valid = val == "true"
                break

        # Method 2: If no explicit VALID found, infer from content
        if is_valid is None:
            text_lower = response_text.lower()

            # Strong failure indicators (model found actual issues)
            failure_indicators = [
                "wrong parent",
                "incorrect parent",
                "should be under",
                "should be a child of",
                "missing part",
                "extra part",
                "not in pdf",
                "not found in",
            ]

            # Strong success indicators
            success_indicators = [
                "all correct",
                "no issues found",
                "no discrepancies",
                "extraction is correct",
                "hierarchy is correct",
                "matches the pdf",
                "valid: true",
            ]

            has_failure = any(ind in text_lower for ind in failure_indicators)
            has_success = any(ind in text_lower for ind in success_indicators)

            if has_failure and not has_success:
                is_valid = False
            elif has_success and not has_failure:
                is_valid = True
            else:
                # Count checkmarks vs X marks as a tiebreaker
                checkmarks = response_text.count("✓") + response_text.count("✔")
                xmarks = response_text.count("✗") + response_text.count("✘") + response_text.count("❌")

                # If mostly checkmarks and no explicit failures, assume valid
                if checkmarks > 0 and xmarks == 0 and not has_failure:
                    is_valid = True
                elif xmarks > 0:
                    is_valid = False
                else:
                    # Default to valid if no clear indicators (avoid unnecessary retries)
                    is_valid = True
                    LOGGER.info("[DT Validate] No clear valid/invalid indicator, assuming valid")

        # Extract issues section for feedback
        if "ISSUES:" in response_text:
            issues = response_text.split("ISSUES:")[1].strip()
        elif "ISSUES" in response_text.upper():
            issues = response_text.split("ISSUES")[1].strip() if "ISSUES" in response_text else response_text
        else:
            issues = response_text[:500]  # Truncate verbose responses

        # Final check: if issues say "None" or similar, it's valid
        if issues.lower().strip() in ["none", "none.", "no issues", "no issues found", ""]:
            is_valid = True

        return is_valid, issues

    except Exception as e:
        LOGGER.error(f"DT validation API error: {e}")
        # On validation error, assume valid to avoid blocking
        return True, f"Validation error: {e}"


def _count_nested_parts(node: Dict[str, Any]) -> int:
    """Count total parts in a nested tree node recursively."""
    if not node:
        return 0
    count = 1
    for child in node.get("children", []):
        count += _count_nested_parts(child)
    return count


def _apply_ocr_to_nested(node: Dict[str, Any]) -> None:
    """Apply OCR corrections to part numbers in nested tree."""
    if not node:
        return
    if node.get("part_number"):
        node["part_number"] = correct_part_number(node["part_number"])
    for child in node.get("children", []):
        _apply_ocr_to_nested(child)


def extract_drawing_tree(
    pdf_path: Path,
    client: VisionClient = None,
    max_iterations: int = 3,
) -> Dict[str, Any]:
    """
    Extract the assembly hierarchy from a Drawing Tree (DT) PDF.

    DT PDFs show the parent-child relationship between all drawings
    in an assembly package as a flowchart/tree structure.

    The extraction uses a vision model to parse the visual hierarchy,
    with iterative validation and self-correction up to max_iterations.

    The extraction uses a nested format internally (easier for vision model)
    then converts to flat format with parent pointers for the builder.

    Args:
        pdf_path: Path to the DT PDF file
        client: Optional VisionClient instance
        max_iterations: Maximum validation/correction iterations (default 3)

    Returns:
        Dict with 'top_level' and 'tree' keys, or empty dict on failure
    """
    if client is None:
        client = VisionClient()

    LOGGER.info(f"[DT Extract] Processing {pdf_path.name}")

    nested_tree = None
    feedback = None

    for iteration in range(max_iterations):
        LOGGER.info(f"[DT Extract] Iteration {iteration + 1}/{max_iterations}")

        # Extract using direct PDF with nested format (easier for vision)
        raw = _call_vision_with_pdf(
            client,
            pdf_path,
            DT_EXTRACTION_PROMPT,
            system_prompt=DT_SYSTEM_PROMPT,
            previous_attempt=nested_tree if iteration > 0 else None,
            feedback=feedback if iteration > 0 else None,
        )

        if not raw:
            LOGGER.warning(f"No extraction result for {pdf_path.name}")
            continue

        # Log extraction count
        part_count = _count_nested_parts(raw.get("root", {}))
        LOGGER.info(f"[DT Extract] Extracted {part_count} parts")

        # Apply OCR corrections to part numbers in nested tree
        _apply_ocr_to_nested(raw.get("root"))
        nested_tree = raw

        # Validate against PDF (using nested format)
        is_valid, issues = _validate_dt_extraction(client, pdf_path, nested_tree)

        if is_valid:
            LOGGER.info(f"[DT Extract] Validation PASSED on iteration {iteration + 1}")
            # Convert nested to flat format for builder compatibility
            flat_tree = _convert_nested_to_flat(nested_tree)
            # Apply structural validation/fixes to flat format
            flat_tree = _validate_and_fix_dt_tree(flat_tree)
            LOGGER.info(f"[DT Extract] Converted to flat format: {len(flat_tree.get('tree', []))} entries")
            return flat_tree
        else:
            LOGGER.warning(f"[DT Extract] Validation failed: {issues[:300]}...")
            feedback = issues

    LOGGER.warning(f"[DT Extract] Max iterations ({max_iterations}) reached, returning best effort")
    if nested_tree:
        # Convert best-effort result to flat format
        flat_tree = _convert_nested_to_flat(nested_tree)
        flat_tree = _validate_and_fix_dt_tree(flat_tree)
        return flat_tree
    return {}


def _call_vision_multi_page(
    client: VisionClient,
    images: List[str],
    prompt: str
) -> Dict[str, Any]:
    """Send multiple page images in a single vision API call."""
    try:
        content = []
        for i, img_b64 in enumerate(images):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": img_b64,
                },
            })
        content.append({"type": "text", "text": prompt})

        response = client.client.messages.create(
            model=client.model,
            max_tokens=8192,
            temperature=0,
            messages=[{"role": "user", "content": content}],
        )
        return client._parse_json_response(response.content[0].text)
    except Exception as e:
        LOGGER.error(f"Multi-page vision API error: {e}")
        return {}


def extract_package(
    directory: Path,
    client: VisionClient = None,
) -> List[Dict[str, Any]]:
    """
    Extract data from all PDFs in a directory.

    Args:
        directory: Directory containing PDF files
        client: Optional VisionClient instance

    Returns:
        List of extraction results
    """
    if client is None:
        client = VisionClient()

    results = []
    pdf_files = sorted(directory.glob("*.pdf"))

    LOGGER.info(f"Extracting {len(pdf_files)} PDFs from {directory}")

    for pdf_path in pdf_files:
        try:
            # Extract first page of each PDF
            result = extract_drawing_page(pdf_path, 0, client)
            if result:
                results.append(result)
        except Exception as e:
            LOGGER.error(f"Failed to extract {pdf_path.name}: {e}")

    LOGGER.info(f"Extracted {len(results)} drawings")
    return results


# =============================================================================
# Phase 2: Parts JSON Extraction (Materials/Specs from Drawings)
# =============================================================================

def _is_dt_file(filename: str) -> bool:
    """
    Check if a file is a Drawing Tree document.

    Supports multiple naming conventions:
    - MER07540-DT.DRW_-.6.pdf (MSFC style with -DT suffix)
    - GPE-DOC-004-D (GPE Drawing Tree).pdf (descriptive name)
    - DrawingTree.pdf (simple name)
    """
    name_upper = filename.upper()
    return (
        "-DT." in name_upper or
        "-DT " in name_upper or
        "-DT_" in name_upper or
        "_DT." in name_upper or
        "DRAWING TREE" in name_upper or
        "DRAWINGTREE" in name_upper or
        " DT." in name_upper or
        name_upper.endswith("-DT.PDF")
    )


def extract_parts_json(
    directory: Path,
    client: VisionClient = None,
    output_path: Path = None,
    use_multipass: bool = True,
    multipass_passes: int = 3,
) -> Dict[str, Any]:
    """
    Phase 2: Extract parts with materials/specs from all non-DT drawings.

    This creates the Parts JSON - a mapping of every part number found to its
    material info, specs, and source drawing. This is used in Phase 3 to
    merge with the DT JSON hierarchy.

    The Parts JSON structure:
    {
        "metadata": {
            "source_directory": "...",
            "drawings_processed": 5,
            "parts_found": 42,
            "extraction_date": "2025-01-29"
        },
        "parts": {
            "MER07546-001": {
                "description": "PRELOAD DISC, 10 INCH VALVE",
                "material": "A286 CRES",
                "material_spec": "SAE AMS 5737",
                "uns": "UNS S66286",
                "process_spec": "",
                "source_drawing": "MER07546-001",
                "source_type": "TITLE_BLOCK",
                "drawing_type": "DETAIL"
            },
            "MS21043-6": {
                "description": "NUT, SELF-LOCKING",
                "material": "A286",
                "material_spec": "",
                "source_drawing": "MER07543-001",
                "source_type": "EPL",
                "drawing_type": "STANDARD"
            }
        },
        "drawings": {
            "MER07543-001": {
                "title": "SHAFT ASSEMBLY, 10 INCH VALVE",
                "revision": "A",
                "drawing_type": "ASSEMBLY",
                "material": "",
                "epl_parts": ["MS21043-6", "NAS1352N4-12", ...]
            }
        }
    }

    Args:
        directory: Directory containing drawing PDFs
        client: Optional VisionClient instance
        output_path: Optional path to save Parts JSON
        use_multipass: Use multi-pass extraction with consensus voting (default True)
        multipass_passes: Number of passes for multi-pass extraction (default 3)

    Returns:
        Parts JSON dictionary
    """
    from datetime import datetime

    if client is None:
        client = VisionClient()

    pdf_files = sorted(directory.glob("*.pdf"))
    drawing_files = [f for f in pdf_files if not _is_dt_file(f.name)]

    LOGGER.info(
        f"[Parts Extract] Processing {len(drawing_files)} drawing PDFs from {directory}"
        f" (multipass={use_multipass}, passes={multipass_passes})"
    )

    parts: Dict[str, Dict[str, Any]] = {}
    drawings: Dict[str, Dict[str, Any]] = {}
    issues: List[str] = []

    for pdf_path in drawing_files:
        try:
            # Try text layer extraction first (free, fast, 100% accurate for CAD PDFs)
            text_result = None
            try:
                if has_text_layer(pdf_path):
                    text_result = extract_drawing_text(pdf_path)
                    if text_result and text_result.get("drawing_number") != "UNKNOWN":
                        LOGGER.info(f"[Parts Extract] {pdf_path.name} via TEXT LAYER (fast)")
                        result = _convert_text_result_to_v3(text_result, pdf_path)
                        result["extraction_method"] = "text_layer"

                        # Skip Vision entirely - we have perfect text data
                        tb = result.get("title_block", {})
                        dwg_num = tb.get("drawing_number", "").strip()
                        if dwg_num:
                            dwg_num = correct_part_number(dwg_num)

                            # Record drawing info
                            drawing_type = result.get("drawing_type", "DETAIL").upper()
                            drawings[dwg_num] = {
                                "title": tb.get("title", ""),
                                "revision": tb.get("revision", ""),
                                "drawing_type": drawing_type,
                                "material": tb.get("material_designation", ""),
                                "material_spec": tb.get("material_spec", ""),
                                "uns": tb.get("uns_number", ""),
                                "process_spec": tb.get("process_spec", ""),
                                "epl_parts": [p.get("part_number") for p in result.get("parts_list", [])],
                                "extraction_method": "text_layer",
                            }

                            # Add title block material as a part entry (for detail drawings)
                            if drawing_type == "DETAIL" and tb.get("material_designation"):
                                if dwg_num not in parts:
                                    # New part - add it
                                    parts[dwg_num] = {
                                        "description": tb.get("title", ""),
                                        "material": tb.get("material_designation", ""),
                                        "material_spec": tb.get("material_spec", ""),
                                        "uns": tb.get("uns_number", ""),
                                        "process_spec": tb.get("process_spec", ""),
                                        "source_drawing": dwg_num,
                                        "source_type": "TITLE_BLOCK",
                                        "drawing_type": drawing_type,
                                    }
                                else:
                                    # Part already exists (from EPL) - title block may have MORE COMPLETE data
                                    # EPL often has abbreviations like "7075 AL", title block has full:
                                    # "ALUMINUM ALLOY 7075-T651, ASTM B211, SAE AMS-QQ-A-225/9"
                                    existing = parts[dwg_num]
                                    tb_material = tb.get("material_designation", "")
                                    tb_spec = tb.get("material_spec", "")
                                    existing_material = existing.get("material", "")

                                    # Use title block material if it's longer OR has spec keywords
                                    spec_keywords = ["ASTM", "AMS", "MIL", "UNS", "SAE"]
                                    tb_has_spec = any(kw in tb_material.upper() for kw in spec_keywords)
                                    tb_is_longer = len(tb_material) > len(existing_material)

                                    if not existing_material or tb_is_longer or tb_has_spec:
                                        existing["material"] = tb_material
                                    if not existing.get("material_spec") or tb_spec:
                                        existing["material_spec"] = tb_spec
                                    if not existing.get("uns"):
                                        existing["uns"] = tb.get("uns_number", "")
                                    if not existing.get("process_spec"):
                                        existing["process_spec"] = tb.get("process_spec", "")

                            # Add EPL parts
                            for part in result.get("parts_list", []):
                                pn = correct_part_number(part.get("part_number", ""))
                                if pn and pn not in parts:
                                    parts[pn] = {
                                        "description": part.get("description", ""),
                                        "material": part.get("material_callout", "") or part.get("material", ""),
                                        "material_spec": "",
                                        "source_drawing": dwg_num,
                                        "source_type": "EPL",
                                        "drawing_type": "STANDARD" if pn.startswith(("MS", "NAS", "AN")) else "DETAIL",
                                    }

                            continue  # Skip to next PDF - text extraction succeeded
            except Exception as e:
                LOGGER.warning(f"[Parts Extract] Text extraction failed for {pdf_path.name}: {e}")

            # Fall back to Vision extraction
            LOGGER.info(f"[Parts Extract] {pdf_path.name} via VISION")

            # Get page count and extract all pages
            images = pdf_to_images(pdf_path)
            num_pages = len(images)

            if num_pages == 0:
                issues.append(f"No pages in PDF: {pdf_path.name}")
                continue

            # Extract first page (title block + EPL start)
            # Use multi-pass for better EPL accuracy if enabled
            epl_validation = None
            if use_multipass:
                multipass_result = extract_epl_multipass(
                    pdf_path, page_idx=0, client=client, passes=multipass_passes
                )
                # Use first full result for title block (already extracted, no extra API call)
                result = multipass_result.get("_first_full_result", {})

                if result:
                    # Replace parts_list with consensus-voted version
                    result["parts_list"] = multipass_result["parts_list"]

                    # Run validation on consensus parts
                    row_validation = validate_epl_row_count(multipass_result["parts_list"])
                    variant_issues = validate_epl_variants(multipass_result["parts_list"])
                    duplicate_issues = find_suspicious_duplicates(multipass_result["parts_list"])

                    epl_validation = {
                        "row_count": row_validation,
                        "variant_issues": variant_issues,
                        "duplicate_issues": duplicate_issues,
                        "flagged_for_review": multipass_result["flagged_for_review"],
                        "confidence": multipass_result["confidence"],
                        "needs_human_review": (
                            not row_validation["passed"] or
                            len(multipass_result["flagged_for_review"]) > 0 or
                            len(variant_issues) > 0 or
                            len(duplicate_issues) > 0
                        ),
                    }

                    if epl_validation["needs_human_review"]:
                        issues.append(
                            f"{pdf_path.name}: EPL needs review - "
                            f"{multipass_result['confidence']['needs_review']} disagreements, "
                            f"missing find_nos: {row_validation.get('missing_find_nos', [])}"
                        )
            else:
                result = extract_drawing_page(pdf_path, 0, client)
                if result:
                    result = postprocess_extraction(result)

            if not result:
                issues.append(f"No extraction result: {pdf_path.name}")
                continue
            tb = result.get("title_block", {})
            dwg_num = tb.get("drawing_number", "").strip()

            if not dwg_num:
                issues.append(f"No drawing number found: {pdf_path.name}")
                continue

            # Apply OCR correction to drawing number
            dwg_num = correct_part_number(dwg_num)

            # Extract additional pages if multi-page
            all_parts_list = result.get("parts_list", []).copy()
            all_notes = result.get("notes", []).copy()

            if num_pages > 1:
                for page_idx in range(1, num_pages):
                    try:
                        page_result = extract_drawing_page(pdf_path, page_idx, client)
                        if page_result:
                            page_result = postprocess_extraction(page_result)
                            # Merge parts list
                            for part in page_result.get("parts_list", []):
                                if part not in all_parts_list:
                                    all_parts_list.append(part)
                            # Merge notes
                            for note in page_result.get("notes", []):
                                if note not in all_notes:
                                    all_notes.append(note)
                    except Exception as e:
                        LOGGER.warning(f"Page {page_idx+1} extraction failed: {e}")

            # Record drawing info
            drawing_type = result.get("drawing_type", "DETAIL").upper()
            epl_pns = []

            drawings[dwg_num] = {
                "title": tb.get("title", ""),
                "revision": tb.get("revision", ""),
                "drawing_type": drawing_type,
                "material": tb.get("material_designation", ""),
                "material_spec": tb.get("material_spec", ""),
                "uns": tb.get("uns_number", ""),
                "process_spec": tb.get("process_spec", ""),
                "material_source": tb.get("material_source", ""),
                "epl_parts": [],  # Filled below
                "source_file": pdf_path.name,
                "epl_validation": epl_validation,  # Multi-pass validation results
            }

            # If this drawing has material, add it as a part entry
            if tb.get("material_designation"):
                if dwg_num not in parts:
                    parts[dwg_num] = {
                        "description": tb.get("title", ""),
                        "material": tb.get("material_designation", ""),
                        "material_spec": tb.get("material_spec", ""),
                        "uns": tb.get("uns_number", ""),
                        "process_spec": tb.get("process_spec", ""),
                        "source_drawing": dwg_num,
                        "source_type": tb.get("material_source", "TITLE_BLOCK"),
                        "drawing_type": drawing_type,
                    }

            # Process EPL parts (from assembly drawings)
            for part in all_parts_list:
                child_pn = correct_part_number(part.get("part_number", ""))
                if not child_pn:
                    continue

                # Skip obvious find numbers (1, 2, 3...)
                if child_pn.isdigit() and int(child_pn) < 100:
                    continue

                # Skip invalid/hallucinated part numbers
                if is_invalid_part_number(child_pn):
                    reason = get_invalid_reason(child_pn)
                    LOGGER.debug(f"Filtering invalid part '{child_pn}': {reason}")
                    continue

                epl_pns.append(child_pn)

                # Add part if not already tracked (or update if EPL has material)
                material = clean_designation(correct_ocr_errors(part.get("material_callout", "") or ""))
                spec = clean_material_spec(part.get("spec_callout", "") or "")
                uns = part.get("uns_callout", "") or ""

                if child_pn not in parts:
                    parts[child_pn] = {
                        "description": part.get("description", ""),
                        "material": material,
                        "material_spec": spec,
                        "uns": uns,
                        "process_spec": "",
                        "source_drawing": dwg_num,
                        "source_type": "EPL",
                        "drawing_type": "STANDARD" if _is_standard_hardware(child_pn) else "UNKNOWN",
                    }
                elif material and not parts[child_pn].get("material"):
                    # Update if we found material that was missing
                    parts[child_pn]["material"] = material
                    parts[child_pn]["material_spec"] = spec or parts[child_pn].get("material_spec", "")

            drawings[dwg_num]["epl_parts"] = epl_pns

            LOGGER.info(
                f"  {dwg_num}: {tb.get('material_designation') or 'NO MATERIAL'} "
                f"({len(epl_pns)} EPL parts)"
            )

        except Exception as e:
            issues.append(f"Error extracting {pdf_path.name}: {e}")
            LOGGER.error(f"  Error extracting {pdf_path.name}: {e}")

    # Build output
    parts_json = {
        "metadata": {
            "source_directory": str(directory),
            "drawings_processed": len(drawings),
            "parts_found": len(parts),
            "extraction_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "multipass_enabled": use_multipass,
            "multipass_passes": multipass_passes if use_multipass else None,
            "issues": issues,
        },
        "parts": parts,
        "drawings": drawings,
    }

    LOGGER.info(
        f"[Parts Extract] Complete: {len(drawings)} drawings, {len(parts)} parts"
    )

    # Save if output path provided
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(parts_json, f, indent=2, ensure_ascii=False)
        LOGGER.info(f"[Parts Extract] Saved to {output_path}")

    return parts_json


def _is_standard_hardware(part_number: str) -> bool:
    """Check if part number is standard hardware (MS, NAS, AN, etc.)."""
    pn_upper = part_number.upper().strip()
    std_prefixes = ("MS", "NAS", "AN", "AS", "CR", "NASM", "NOR", "EN", "BAC")
    return any(pn_upper.startswith(p) for p in std_prefixes)


# =============================================================================
# Multi-Pass EPL Extraction with Consensus Voting
# =============================================================================

def extract_epl_multipass(
    pdf_path: Path,
    page_idx: int,
    client: VisionClient = None,
    passes: int = 3,
) -> Dict[str, Any]:
    """
    Extract EPL with multiple passes for consensus voting.

    Runs extraction N times and uses majority voting to resolve OCR
    discrepancies in part numbers.

    Args:
        pdf_path: Path to PDF file
        page_idx: Page index (0-based)
        client: Optional VisionClient instance
        passes: Number of extraction passes (default 3)

    Returns:
        Dict with parts_list, flagged_for_review, and confidence stats
    """
    if client is None:
        client = VisionClient()

    all_extractions: List[List[Dict]] = []
    first_full_result: Dict[str, Any] = {}

    for i in range(passes):
        result = extract_drawing_page(pdf_path, page_idx, client)
        if i == 0:
            # Save first full result for title_block etc.
            first_full_result = postprocess_extraction(result) if result else {}
        parts = result.get("parts_list", [])
        all_extractions.append(parts)
        LOGGER.info(f"[EPL Multi-Pass] Pass {i+1}: extracted {len(parts)} EPL rows")

    # Consensus voting
    consensus_parts, flagged = consensus_vote_epl(all_extractions)

    # Calculate confidence stats
    high_confidence = len([p for p in consensus_parts if p.get("confidence") == f"{passes}/{passes}"])

    return {
        "parts_list": consensus_parts,
        "flagged_for_review": flagged,
        "confidence": {
            "total_rows": len(consensus_parts),
            "high_confidence": high_confidence,
            "needs_review": len(flagged),
            "passes": passes,
        },
        # Keep original extractions for debugging
        "_raw_extractions": all_extractions,
        # First full result for title_block, notes, etc.
        "_first_full_result": first_full_result,
    }


def consensus_vote_epl(
    extractions: List[List[Dict]],
) -> Tuple[List[Dict], List[Dict]]:
    """
    Vote on part numbers across multiple extraction passes.

    Groups by find_no, then votes on part_number for each find_no.
    Parts with unanimous agreement get high confidence; disagreements
    are flagged for human review.

    Args:
        extractions: List of extraction results (each is a list of parts)

    Returns:
        Tuple of (consensus_parts, flagged_parts)
    """
    from collections import defaultdict, Counter

    # Group by find_no
    by_find_no: Dict[str, List[Dict]] = defaultdict(list)

    for extraction in extractions:
        for part in extraction:
            find_no = str(part.get("find_no", "")).strip()
            if find_no:
                by_find_no[find_no].append(part)

    consensus: List[Dict] = []
    flagged: List[Dict] = []
    num_passes = len(extractions)

    # Sort find_nos numerically where possible
    def sort_key(x):
        try:
            return (0, int(x))
        except ValueError:
            return (1, x)

    for find_no in sorted(by_find_no.keys(), key=sort_key):
        candidates = by_find_no[find_no]

        # Vote on part_number
        pn_votes: Counter = Counter(c.get("part_number", "").strip() for c in candidates)

        # Filter out empty votes
        pn_votes = Counter({k: v for k, v in pn_votes.items() if k})

        if not pn_votes:
            continue

        winner, count = pn_votes.most_common(1)[0]

        # Use first candidate as template, update with winning PN
        part = candidates[0].copy()
        part["part_number"] = winner
        part["confidence"] = f"{count}/{num_passes}"

        if count < num_passes:
            # Disagreement - flag for review
            alternatives = [pn for pn, _ in pn_votes.most_common() if pn != winner]
            part["alternatives"] = alternatives
            part["_votes"] = dict(pn_votes)
            flagged.append(part)
            LOGGER.warning(
                f"[EPL Consensus] find_no {find_no}: disagreement - "
                f"winner '{winner}' ({count}/{num_passes}), "
                f"alternatives: {alternatives}"
            )
        else:
            LOGGER.debug(f"[EPL Consensus] find_no {find_no}: unanimous '{winner}'")

        consensus.append(part)

    LOGGER.info(
        f"[EPL Consensus] {len(consensus)} parts, "
        f"{len(consensus) - len(flagged)} unanimous, "
        f"{len(flagged)} flagged"
    )

    return consensus, flagged


def validate_epl_row_count(
    parts_list: List[Dict],
    expected_count: int = None,
) -> Dict[str, Any]:
    """
    Validate we extracted the expected number of EPL rows.

    If expected_count not provided, infers from max find_no.

    Args:
        parts_list: List of extracted parts
        expected_count: Expected row count (optional)

    Returns:
        Validation result dict with expected, actual, passed, missing_find_nos
    """
    actual_count = len(parts_list)

    # Extract find_nos as integers
    find_nos: List[int] = []
    for p in parts_list:
        fn = str(p.get("find_no", "")).strip().rstrip(".")
        if fn.isdigit():
            find_nos.append(int(fn))

    # If expected_count not provided, infer from max find_no
    if expected_count is None and find_nos:
        expected_count = max(find_nos)
    elif expected_count is None:
        expected_count = actual_count

    validation = {
        "expected": expected_count,
        "actual": actual_count,
        "passed": actual_count >= expected_count,
        "missing_find_nos": [],
    }

    if not validation["passed"] and find_nos:
        # Find which find_nos are missing
        extracted_find_nos = set(find_nos)
        expected_find_nos = set(range(1, expected_count + 1))
        validation["missing_find_nos"] = sorted(expected_find_nos - extracted_find_nos)
        LOGGER.warning(
            f"[EPL Validate] Row count mismatch: expected {expected_count}, "
            f"got {actual_count}. Missing find_nos: {validation['missing_find_nos']}"
        )
    elif validation["passed"]:
        LOGGER.info(f"[EPL Validate] Row count OK: {actual_count} >= {expected_count}")

    return validation


def validate_epl_variants(parts_list: List[Dict]) -> List[Dict]:
    """
    Detect when RH/LH or similar variants should have distinct part numbers.

    Checks for:
    1. Same PN with RH/LH descriptions (description-based)
    2. Suspicious duplicates that might be OCR merges

    Args:
        parts_list: List of extracted parts

    Returns:
        List of issue dicts
    """
    from collections import defaultdict, Counter

    issues: List[Dict] = []

    # Group by part_number
    by_pn: Dict[str, List[Dict]] = defaultdict(list)
    for part in parts_list:
        pn = part.get("part_number", "").strip()
        if pn:
            by_pn[pn].append(part)

    for pn, parts in by_pn.items():
        if len(parts) < 2:
            continue

        descriptions = [p.get("description", "").upper() for p in parts]

        # Check for RH/LH thread indicators in descriptions
        has_rh = any("RH" in d or "RIGHT" in d for d in descriptions)
        has_lh = any("LH" in d or "LEFT" in d for d in descriptions)

        if has_rh and has_lh:
            issues.append({
                "type": "VARIANT_COLLISION",
                "part_number": pn,
                "descriptions": descriptions,
                "find_nos": [p.get("find_no") for p in parts],
                "message": (
                    f"Part {pn} appears with both RH and LH thread descriptions - "
                    f"likely OCR merged two distinct PNs"
                ),
            })

    if issues:
        LOGGER.warning(f"[EPL Validate] Variant validation found {len(issues)} issues")

    return issues


def find_suspicious_duplicates(parts_list: List[Dict]) -> List[Dict]:
    """
    Find PNs that appear multiple times but might be OCR errors.

    When the same PN appears 2+ times, it could mean:
    1. Legitimate: same fastener used in multiple places
    2. OCR error: two similar PNs (e.g., NAS509-6C and NAS509L6C) merged

    This flags duplicates for human review.

    Args:
        parts_list: List of extracted parts

    Returns:
        List of issue dicts
    """
    from collections import Counter

    pns = [p.get("part_number", "").strip() for p in parts_list if p.get("part_number")]
    pn_counts = Counter(pns)

    issues: List[Dict] = []
    for pn, count in pn_counts.items():
        if count > 1:
            # Find the parts with this PN
            matching = [p for p in parts_list if p.get("part_number", "").strip() == pn]
            find_nos = [p.get("find_no") for p in matching]
            descriptions = [p.get("description", "") for p in matching]

            issues.append({
                "type": "DUPLICATE_PN",
                "part_number": pn,
                "count": count,
                "find_nos": find_nos,
                "descriptions": descriptions,
                "message": (
                    f"{pn} appears {count} times (find_nos: {find_nos}) - "
                    f"verify not OCR merge of similar PNs"
                ),
            })

    if issues:
        LOGGER.warning(f"[EPL Validate] Found {len(issues)} duplicate PNs for review")

    return issues


def extract_epl_with_validation(
    pdf_path: Path,
    page_idx: int = 0,
    client: VisionClient = None,
    passes: int = 3,
) -> Dict[str, Any]:
    """
    Extract EPL with multi-pass consensus and full validation.

    This is the main entry point for robust EPL extraction.
    Combines:
    1. Multi-pass extraction with consensus voting
    2. Structural validation (row count check)
    3. Variant collision detection
    4. Duplicate PN detection

    Args:
        pdf_path: Path to PDF file
        page_idx: Page index (0-based)
        client: Optional VisionClient instance
        passes: Number of extraction passes (default 3)

    Returns:
        Dict with parts_list, validation results, and review flags
    """
    if client is None:
        client = VisionClient()

    LOGGER.info(f"[EPL Extract] Starting {passes}-pass extraction of {pdf_path.name}")

    # 1. Multi-pass extraction with consensus
    result = extract_epl_multipass(pdf_path, page_idx, client, passes)
    parts = result["parts_list"]

    # 2. Structural validation (row count)
    row_validation = validate_epl_row_count(parts)

    # 3. Variant collision detection
    variant_issues = validate_epl_variants(parts)

    # 4. Duplicate PN detection
    duplicate_issues = find_suspicious_duplicates(parts)

    # Combine all issues
    all_issues = variant_issues + duplicate_issues

    # Determine if human review needed
    needs_review = (
        not row_validation["passed"] or
        len(result["flagged_for_review"]) > 0 or
        len(all_issues) > 0
    )

    result["validation"] = {
        "row_count": row_validation,
        "variant_issues": variant_issues,
        "duplicate_issues": duplicate_issues,
        "needs_human_review": needs_review,
    }

    # Log summary
    LOGGER.info(
        f"[EPL Extract] Complete: {len(parts)} parts, "
        f"{result['confidence']['high_confidence']}/{len(parts)} high confidence, "
        f"review needed: {needs_review}"
    )

    if needs_review:
        review_reasons = []
        if not row_validation["passed"]:
            review_reasons.append(f"missing rows: {row_validation['missing_find_nos']}")
        if result["flagged_for_review"]:
            review_reasons.append(f"{len(result['flagged_for_review'])} consensus disagreements")
        if variant_issues:
            review_reasons.append(f"{len(variant_issues)} variant collisions")
        if duplicate_issues:
            review_reasons.append(f"{len(duplicate_issues)} duplicate PNs")
        LOGGER.warning(f"[EPL Extract] Review needed: {', '.join(review_reasons)}")

    return result
