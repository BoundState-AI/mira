#!/usr/bin/env python3
"""
Module: Extract
Purpose: # =============================================================================

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import base64
import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

from .models import (
    BOMRow,
    HardwareCallout,
    Issue,
    IssueSeverity,
    IssueType,
    LayoutFlags,
    Occurrence,
    PageExtract,
    TitleBlock,
    Zone,
)


# =============================================================================
# Configuration
# =============================================================================

PROMPT_VERSION = "v2.3.3"  # MSFC notes-based material extraction
MODEL_VERSION = "claude-sonnet-4-20250514"


# =============================================================================
# Vision Extraction Prompt (v1-quality, proven anti-hallucination)
# =============================================================================

VISION_EXTRACTION_PROMPT = """You are a STRICT forensic engineering drawing parser.
Extract ONLY what you can CLEARLY SEE in this drawing. Do NOT guess or infer.

CRITICAL ANTI-HALLUCINATION RULES:
1. Extract ONLY part numbers that are CLEARLY VISIBLE in the drawing.
2. If you cannot read a part number clearly, SKIP IT. Do not guess.
3. SKIP rows where part_number would be "ITEM NOT SHOWN", "NOT SHOWN", "-", or blank.
4. DO NOT invent fasteners - MS20002, MS35206, MS35338 series are commonly hallucinated.
5. Copy part numbers EXACTLY as shown - character for character.
6. If unsure about a digit or letter, SKIP that part entirely.

CHARACTER ACCURACY RULES - READ TWICE BEFORE TRANSCRIBING:
7. Common misreads to watch for:
   - 5 vs 8 (look for curved top = 5, two loops = 8)
   - 6 vs 8 vs 9 (check loop direction carefully)
   - 1 vs I vs l (one vs capital-I vs lowercase-L)
   - 0 vs O vs D (zero often has slash or dot, O is rounder)
   - V vs W vs M (count the points - V=1, W=2 valleys, M=2 peaks)
   - B vs 8 (B has flat back, 8 is curved)
   - S vs 5 (S is curvy throughout, 5 has flat top)
   - 3 vs 8 (3 is open on left, 8 is closed)
8. For MS/NAS/AN standard hardware, the format is PREFIX-NUMBER (e.g., NAS509-6C, MS14198N6).
   Double-check each digit in the number portion.
9. For MIL specs (M81935, MS14198), read the full number carefully - these are 5+ digits.
10. If a part number seems unusual or doesn't match typical patterns, re-examine before transcribing.

Return JSON with this structure:

{
  "title_block": {
    "drawing_number": "The drawing number from title block or null",
    "sheet": "Sheet number (e.g. '3 of 5') or null",
    "revision": "Revision letter/number or null",
    "title": "The drawing title/name (e.g., TOP PLATE, BRACKET ASSY, VALVE BODY) or null",
    "cage_code": "5-digit CAGE code from title block (e.g., 1EYB0, 1CRL0) or null",
    "nha_part_number": "Next Higher Assembly from USED ON field or null",
    "material_designation": "FULL material name with alloy/temper (e.g., 6061-T6 ALUMINUM, 7075-T73 ALUMINUM, A286 CRES, INCONEL 718). Include alloy number and temper!",
    "material_spec": "Spec number only (e.g., SAE AMS 5737, MIL-S-5000, ASTM A564) or null",
    "uns_number": "UNS number if shown (e.g., UNS S66286, UNS N07718) or null",
    "process_spec": "Process spec from notes if any (e.g., passivation per SAE-AMS-QQ-P-35) or null"
  },
  "drawing_type": "DETAIL or ASSEMBLY (ASSEMBLY if it has an ENGINEERING PARTS LIST table)",
  "drawing_number_occurrences": [
    {
      "drawing_number": "the drawing number found",
      "text_found": "exact text as it appears",
      "zone": "TITLEBLOCK | BORDER | BODY | NOTES | UNKNOWN",
      "confidence": 0.0-1.0
    }
  ],
  "layout_flags": {
    "has_title_block": true/false,
    "has_revision_block": true/false,
    "has_views": true/false,
    "has_balloons": true/false,
    "has_parts_list": true/false
  },
  "parts_list": [
    {
      "find_no": "from EPL or '-' for detail drawing",
      "part_number": "EXACT as shown - copy character for character!",
      "description": "nomenclature from EPL or title block",
      "quantity": integer or null,
      "quantity_note": "AR, REF, TBD if non-numeric",
      "material_callout": "EPL MATERIAL column ONLY for THIS row (else empty string)",
      "spec_callout": "ONLY if EPL row has its own spec (else empty string)",
      "uns_callout": "ONLY if EPL row shows UNS (else empty string)",
      "form_callout": "material form if shown (SHEET, BAR, FORGING) or null",
      "finish_callout": "finish/process from EPL (else empty string)"
    }
  ],
  "hardware_callouts": [
    {
      "raw_text": "Complete callout text from drawing",
      "standard": "NAS/MS/AN/NASM prefix and number",
      "size": "thread size if applicable or null",
      "quantity": integer (look for nX prefix like '4X', '24X'),
      "material": "material if explicitly specified or null"
    }
  ],
  "notes": ["array of relevant notes from the drawing"]
}

ZONE CLASSIFICATION IS CRITICAL (for binding):
- TITLEBLOCK: In the title block area (typically lower right corner)
- BORDER: In the border/frame area around the drawing
- BODY: In the main drawing area (views, details, sections)
- NOTES: In the notes section (general notes, references)
- UNKNOWN: Cannot determine location

SPEC/UNS RULES - CRITICAL:
- spec_callout and uns_callout are ONLY for parts that have their OWN spec in the EPL MATERIAL column.
- DO NOT copy title block spec (like ASTM B209) to EPL line items.
- Child drawing references should have spec_callout="" and uns_callout="" (they have their own drawings).
- Only fill spec/uns if the EPL row itself shows a spec number.

MATERIAL DESIGNATION RULES:
- material_callout = ONLY from EPL MATERIAL column text for that specific row.
- Child drawing numbers should have material_callout="" (material comes from their own drawing).
- Standard hardware (NAS, MS, AN) gets material from EPL if shown, else "".
- For title_block.material_designation: Include SPECIFIC alloy and temper (6061-T6, not just ALUMINUM).

CRITICAL - MATERIAL FROM NOTES (MSFC Format):
- Many MSFC drawings have EMPTY title block MATERIAL field but specify material in the NOTES section.
- Look for numbered notes starting with "MATERIAL:" (e.g., "3. MATERIAL: A286 CRES, UNS S66286, PER SAE AMS 5737")
- When you find "MATERIAL:" in notes, parse it and populate title_block fields:
  * material_designation = the alloy/material name (e.g., "A286 CRES", "INCONEL 718", "6061-T6 ALUMINUM")
  * uns_number = the UNS code if present (e.g., "UNS S66286", "UNS N07718")
  * material_spec = the spec after "PER" (e.g., "SAE AMS 5737", "SAE AMS 5666")
- THIS IS THE PRIMARY SOURCE for detail drawing materials - title block MATERIAL field is often empty!

WHERE TO LOOK:
- Title block is typically in the lower right corner.
- CAGE code is usually a 5-character alphanumeric code in the title block.
- USED ON field shows Next Higher Assembly.
- NOTES section often contains the actual MATERIAL callout - CHECK THE NOTES FIRST for "MATERIAL:" keyword.
- If title block MATERIAL is empty, the material WILL be in the notes section.

Return ONLY valid JSON. Do NOT include explanations outside the JSON."""


# =============================================================================
# Page ID Generation
# =============================================================================

def make_page_id(source_file: str, page_index: int) -> str:
    """
    Generate page_id per v2.3 spec: "filename:page_index"

    No image hashing - simple and deterministic.
    """
    return f"{source_file}:{page_index}"


# =============================================================================
# PDF Handling
# =============================================================================

def get_pdf_page_count(pdf_path: Path) -> int:
    """Get total page count from PDF without full parsing."""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        count = len(doc)
        doc.close()
        return count
    except ImportError:
        # Fallback: try pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                return len(pdf.pages)
        except ImportError:
            raise RuntimeError("No PDF library available (need PyMuPDF or pdfplumber)")


def read_pdf_bytes(pdf_path: Path) -> bytes:
    """Read entire PDF file as bytes."""
    return pdf_path.read_bytes()


def extract_single_page_pdf(pdf_path: Path, page_index: int) -> bytes:
    """
    Extract a single page as a standalone PDF.

    Claude Vision accepts multi-page PDFs but for per-page extraction
    we send one page at a time.
    """
    try:
        import fitz
        doc = fitz.open(pdf_path)
        if page_index >= len(doc):
            doc.close()
            raise ValueError(f"Page {page_index} out of range (PDF has {len(doc)} pages)")

        # Create new doc with just this page
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=page_index, to_page=page_index)
        pdf_bytes = new_doc.tobytes()
        new_doc.close()
        doc.close()
        return pdf_bytes
    except ImportError:
        # If no fitz, send whole PDF (less efficient but works)
        LOGGER.warning("PyMuPDF not available, sending whole PDF to Vision")
        return pdf_path.read_bytes()


# =============================================================================
# Vision API Call
# =============================================================================

def call_vision_api(
    pdf_bytes: bytes,
    anthropic_client: 'anthropic.Anthropic',
    model: str = MODEL_VERSION,
) -> dict:
    """
    Send PDF directly to Claude Vision API.

    Per SPEC v2.3: Native PDF input, no image conversion.
    Uses type: "document" with media_type: "application/pdf"
    """
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

    LOGGER.debug(f"Calling Vision API with {len(pdf_bytes):,} bytes PDF")

    message = anthropic_client.messages.create(
        model=model,
        max_tokens=4096,
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
                {
                    "type": "text",
                    "text": VISION_EXTRACTION_PROMPT,
                },
            ],
        }],
    )

    response_text = message.content[0].text

    # Parse JSON from response
    json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1:
            json_str = response_text[start:end + 1]
        else:
            json_str = response_text

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        LOGGER.warning(f"Failed to parse vision response: {e}")
        LOGGER.debug(f"Response was: {response_text[:500]}")
        return {}


# =============================================================================
# Caching
# =============================================================================

def compute_cache_key(source_file: str, page_index: int, prompt_version: str, model_version: str) -> str:
    """
    Cache key per v2.3: hash(source_file, page_index, prompt_version, model_version)
    """
    combined = f"{source_file}:{page_index}:{prompt_version}:{model_version}"
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


def load_from_cache(cache_dir: Path, cache_key: str) -> Optional[dict]:
    """Load cached extraction result."""
    if not cache_dir or not cache_dir.exists():
        return None

    cache_file = cache_dir / f"{cache_key}.json"
    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_to_cache(cache_dir: Path, cache_key: str, data: dict) -> None:
    """Save extraction result to cache."""
    if not cache_dir:
        return

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{cache_key}.json"

    with open(cache_file, 'w') as f:
        json.dump(data, f, indent=2)


# =============================================================================
# Result Parsing
# =============================================================================

def normalize_revision(rev: str | None) -> str:
    """
    Normalize revision values.

    - "-" (dash) is often used to mean "no revision" or "initial release"
    - Treat these as empty string to avoid false revision conflicts
    """
    if rev is None:
        return ""
    rev = str(rev).strip()
    # Dash alone means no revision
    if rev in ("-", "—", "–", ""):
        return ""
    return rev


def parse_vision_result(
    vision_result: dict,
) -> tuple[TitleBlock, list[Occurrence], LayoutFlags, list[BOMRow], list[HardwareCallout]]:
    """Parse vision JSON response into model objects."""

    # Title block
    # Title block with v1-quality material fields
    tb = vision_result.get("title_block", {})
    title_block = TitleBlock(
        drawing_number=tb.get("drawing_number"),
        sheet=tb.get("sheet"),
        revision=normalize_revision(tb.get("revision")),
        title=tb.get("title"),
        cage_code=tb.get("cage_code"),
        nha_part_number=tb.get("nha_part_number"),
        # Material fields (v1-proven)
        material_designation=tb.get("material_designation"),
        material_spec=tb.get("material_spec"),
        uns_number=tb.get("uns_number"),
        process_spec=tb.get("process_spec"),
    )

    # Occurrences with zone classification (THE KEY FIX)
    occurrences = []
    zone_map = {
        "titleblock": Zone.TITLEBLOCK,
        "border": Zone.BORDER,
        "body": Zone.BODY,
        "notes": Zone.NOTES,
        "unknown": Zone.UNKNOWN,
    }

    for occ in vision_result.get("drawing_number_occurrences", []):
        zone_str = occ.get("zone", "unknown").lower()
        zone = zone_map.get(zone_str, Zone.UNKNOWN)

        occurrences.append(Occurrence(
            drawing_number=occ.get("drawing_number", ""),
            zone=zone,
            confidence=occ.get("confidence", 1.0),
            source="vision",
        ))

    # Layout flags
    lf = vision_result.get("layout_flags", {})
    layout_flags = LayoutFlags(
        has_title_block=lf.get("has_title_block", False),
        has_revision_block=lf.get("has_revision_block", False),
        has_views=lf.get("has_views", False),
        has_balloons=lf.get("has_balloons", False),
        has_parts_list=lf.get("has_parts_list", False),
    )

    # Parts list with v1-quality field mapping
    parts_list = []
    for part in vision_result.get("parts_list", []):
        qty = part.get("quantity")
        if isinstance(qty, str):
            try:
                qty = int(qty)
            except ValueError:
                qty = None

        parts_list.append(BOMRow(
            find_no=part.get("find_no"),
            part_number=part.get("part_number", ""),
            description=part.get("description", ""),
            quantity=qty if qty is not None else 1,
            quantity_note=part.get("quantity_note", ""),
            material_callout=part.get("material_callout", ""),
            spec_callout=part.get("spec_callout", ""),
            uns_callout=part.get("uns_callout", ""),
            form_callout=part.get("form_callout", ""),
            finish_callout=part.get("finish_callout", ""),
            notes=part.get("notes", ""),
        ))

    # Hardware callouts
    hardware = []
    for hw in vision_result.get("hardware_callouts", []):
        qty = hw.get("quantity", 1)
        if isinstance(qty, str):
            try:
                qty = int(qty)
            except ValueError:
                qty = 1

        hardware.append(HardwareCallout(
            raw_text=hw.get("raw_text", ""),
            standard=hw.get("standard", ""),
            size=hw.get("size", ""),
            quantity=qty,
            material=hw.get("material", ""),
        ))

    return title_block, occurrences, layout_flags, parts_list, hardware


# =============================================================================
# Part Number Validation (Flag Suspicious OCR)
# =============================================================================

# Known standard hardware prefixes and their typical patterns
STANDARD_HARDWARE_PATTERNS = {
    "NAS": r"^NAS\d{3,4}[A-Z]?\d*[A-Z]?$",      # NAS509-6C, NAS1149FN416P
    "MS": r"^MS\d{4,5}[A-Z]?\d*$",               # MS14198N6, MS21042-3
    "AN": r"^AN\d{3,4}[A-Z]?\d*$",               # AN960-416, AN3-3A
    "NASM": r"^NASM\d{4,5}[A-Z]?\d*$",           # NASM20470AD4-4
    "BAC": r"^BAC\d{4,5}[A-Z]?\d*$",             # BAC10MR3C10
}

# MIL-SPEC patterns (M followed by 5+ digits)
MIL_SPEC_PATTERN = r"^M\d{5,}[/-]?\d*[A-Z]?\d*$"  # M81935/3-6C


def validate_part_numbers(
    parts_list: list[BOMRow],
    page_id: str,
) -> list[Issue]:
    """
    Validate extracted part numbers for suspicious patterns.

    Flags part numbers that:
    - Have unusual character sequences suggesting OCR misreads
    - Don't match typical standard hardware patterns
    - Have repeated digits that might indicate confusion (e.g., 555 vs 585)

    Returns list of WARNING issues for suspicious part numbers.
    Does NOT auto-correct - just flags for manual review.
    """
    issues = []

    for part in parts_list:
        pn = part.part_number.upper().strip()
        if not pn:
            continue

        # Check for potential 5/8 confusion in standard hardware
        # These are the most commonly misread characters
        suspicious_patterns = []

        # Check standard hardware format
        for prefix, pattern in STANDARD_HARDWARE_PATTERNS.items():
            if pn.startswith(prefix):
                if not re.match(pattern, pn.replace("-", ""), re.IGNORECASE):
                    suspicious_patterns.append(f"Non-standard {prefix} format")
                break

        # Check MIL-SPEC format
        if pn.startswith("M") and pn[1:2].isdigit():
            clean_pn = pn.replace("-", "").replace("/", "")
            if not re.match(MIL_SPEC_PATTERN, clean_pn, re.IGNORECASE):
                suspicious_patterns.append("Non-standard MIL-SPEC format")

        # Check for unusual digit sequences (potential 5/8 or 6/8 confusion)
        # Numbers with 3+ same digit in a row are rare in part numbers
        if re.search(r'(\d)\1{2,}', pn):
            suspicious_patterns.append("Unusual repeated digits")

        # Flag part numbers starting with V that might be W (VEM vs WEM, VSM vs WSM)
        if pn.startswith(("VEM", "VSM", "VCM")):
            suspicious_patterns.append("V-prefix may be W (VEM→WEM, VSM→WSM)")

        if suspicious_patterns:
            issues.append(Issue(
                severity=IssueSeverity.WARNING,
                issue_type=IssueType.SUSPICIOUS_PART_NUMBER,
                affected=pn,
                message=f"May be misread: {', '.join(suspicious_patterns)}",
                evidence_page_ids=[page_id],
            ))

    return issues


# =============================================================================
# Main Extraction Function
# =============================================================================

def extract_page(
    pdf_path: Path,
    page_index: int,
    anthropic_client: Optional['anthropic.Anthropic'] = None,
    cache_dir: Optional[Path] = None,
    skip_vision: bool = False,
) -> tuple[PageExtract, list[Issue]]:
    """
    Extract structured data from a single PDF page.

    Per SPEC v2.3:
    1. Extract single-page PDF bytes
    2. Check cache
    3. Call Vision API (native PDF, no text in prompt)
    4. Parse result into PageExtract
    5. Cache result

    Args:
        pdf_path: Path to source PDF
        page_index: 0-indexed page number
        anthropic_client: Anthropic client for Vision API
        cache_dir: Optional cache directory
        skip_vision: If True, skip Vision API call (for testing)

    Returns:
        (PageExtract, list of Issues)
    """
    issues = []
    source_file = pdf_path.name
    page_id = make_page_id(source_file, page_index)

    # Step 1: Extract single-page PDF
    try:
        pdf_bytes = extract_single_page_pdf(pdf_path, page_index)
    except Exception as e:
        return _create_error_extract(source_file, page_index, page_id), [
            Issue(
                severity=IssueSeverity.WARNING,
                issue_type=IssueType.PARSE_FAILURE,
                affected=page_id,
                message=f"Failed to extract PDF page: {e}",
                evidence_page_ids=[page_id],
            )
        ]

    # Step 2: Vision extraction
    vision_result = {}

    if not skip_vision and anthropic_client:
        cache_key = compute_cache_key(source_file, page_index, PROMPT_VERSION, MODEL_VERSION)

        # Check cache
        if cache_dir:
            cached = load_from_cache(cache_dir, cache_key)
            if cached:
                LOGGER.debug(f"Cache hit for {page_id}")
                vision_result = cached

        # Call Vision API if not cached
        if not vision_result:
            try:
                vision_result = call_vision_api(pdf_bytes, anthropic_client)
                if cache_dir and vision_result:
                    save_to_cache(cache_dir, cache_key, vision_result)
            except Exception as e:
                issues.append(Issue(
                    severity=IssueSeverity.WARNING,
                    issue_type=IssueType.PARSE_FAILURE,
                    affected=page_id,
                    message=f"Vision API failed: {e}",
                    evidence_page_ids=[page_id],
                ))

    # Step 3: Parse results
    if vision_result:
        title_block, occurrences, layout_flags, parts_list, hardware = parse_vision_result(vision_result)
    else:
        title_block = TitleBlock()
        occurrences = []
        layout_flags = LayoutFlags()
        parts_list = []
        hardware = []

    # Step 4: Validate part numbers for suspicious OCR
    validation_issues = validate_part_numbers(parts_list, page_id)
    issues.extend(validation_issues)

    # Create PageExtract
    page_extract = PageExtract(
        page_id=page_id,
        page_index=page_index,
        source_file=source_file,
        title_block=title_block,
        drawing_number_occurrences=occurrences,
        layout_flags=layout_flags,
        parts_list=parts_list,
        hardware_callouts=hardware,
        revision=title_block.revision or "",
    )

    return page_extract, issues


def _create_error_extract(source_file: str, page_index: int, page_id: str) -> PageExtract:
    """Create a minimal PageExtract for error cases."""
    return PageExtract(
        page_id=page_id,
        page_index=page_index,
        source_file=source_file,
        title_block=TitleBlock(),
        drawing_number_occurrences=[],
        layout_flags=LayoutFlags(),
        parts_list=[],
        hardware_callouts=[],
        revision="",
    )


# =============================================================================
# Batch Extraction
# =============================================================================

def extract_pdf(
    pdf_path: Path,
    anthropic_client: Optional['anthropic.Anthropic'] = None,
    cache_dir: Optional[Path] = None,
    skip_vision: bool = False,
) -> tuple[list[PageExtract], list[Issue]]:
    """
    Extract all pages from a PDF.

    Args:
        pdf_path: Path to PDF file
        anthropic_client: Anthropic client for Vision API
        cache_dir: Optional cache directory
        skip_vision: If True, skip Vision API calls

    Returns:
        (list of PageExtract, list of Issues)
    """
    all_extracts = []
    all_issues = []

    page_count = get_pdf_page_count(pdf_path)
    LOGGER.info(f"Extracting {page_count} pages from {pdf_path.name}")

    for page_index in range(page_count):
        extract, issues = extract_page(
            pdf_path,
            page_index,
            anthropic_client,
            cache_dir,
            skip_vision,
        )
        all_extracts.append(extract)
        all_issues.extend(issues)

    return all_extracts, all_issues


def extract_pdf_parallel(
    pdf_path: Path,
    anthropic_client: Optional['anthropic.Anthropic'] = None,
    cache_dir: Optional[Path] = None,
    skip_vision: bool = False,
    max_workers: int = 5,
) -> tuple[list[PageExtract], list[Issue]]:
    """
    Extract all pages from a PDF in parallel.

    Uses ThreadPoolExecutor to send multiple pages to Vision API concurrently.
    Expected ~5x speedup with 5 workers.

    Args:
        pdf_path: Path to PDF file
        anthropic_client: Anthropic client for Vision API
        cache_dir: Optional cache directory
        skip_vision: If True, skip Vision API calls
        max_workers: Number of concurrent workers (default 5)

    Returns:
        (list of PageExtract, list of Issues)
    """
    page_count = get_pdf_page_count(pdf_path)
    LOGGER.info(f"Extracting {page_count} pages from {pdf_path.name} (parallel, {max_workers} workers)")

    # Pre-allocate results list to maintain page order
    results: list[PageExtract | None] = [None] * page_count
    all_issues: list[Issue] = []
    issues_lock = threading.Lock()

    def extract_one(page_index: int) -> tuple[int, PageExtract, list[Issue]]:
        """Extract a single page and return with index."""
        extract, issues = extract_page(
            pdf_path,
            page_index,
            anthropic_client,
            cache_dir,
            skip_vision,
        )
        return page_index, extract, issues

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_one, i): i
            for i in range(page_count)
        }

        for future in as_completed(futures):
            try:
                page_index, extract, issues = future.result()
                results[page_index] = extract
                with issues_lock:
                    all_issues.extend(issues)
            except Exception as e:
                page_index = futures[future]
                LOGGER.error(f"Failed to extract page {page_index}: {e}")
                with issues_lock:
                    all_issues.append(Issue(
                        severity=IssueSeverity.WARNING,
                        issue_type=IssueType.PARSE_FAILURE,
                        affected=f"{pdf_path.name}:{page_index}",
                        message=f"Parallel extraction failed: {e}",
                        evidence_page_ids=[f"{pdf_path.name}:{page_index}"],
                    ))

    # Filter out any None results (shouldn't happen but safety check)
    final_results = [r for r in results if r is not None]

    return final_results, all_issues


def extract_directory(
    directory: Path,
    anthropic_client: Optional['anthropic.Anthropic'] = None,
    cache_dir: Optional[Path] = None,
    skip_vision: bool = False,
    pattern: str = "*.pdf",
    max_workers: int = 5,
) -> tuple[list[PageExtract], list[Issue]]:
    """
    Extract all PDFs from a directory using parallel extraction.

    Args:
        directory: Directory containing PDFs
        anthropic_client: Anthropic client for Vision API
        cache_dir: Optional cache directory
        skip_vision: If True, skip Vision API calls
        pattern: Glob pattern for PDF files
        max_workers: Number of concurrent workers for Vision API calls (default 5)

    Returns:
        (list of PageExtract from all PDFs, list of Issues)
    """
    all_extracts = []
    all_issues = []

    pdf_files = sorted(directory.glob(pattern))
    LOGGER.info(f"Found {len(pdf_files)} PDFs in {directory}")

    for pdf_path in pdf_files:
        extracts, issues = extract_pdf_parallel(
            pdf_path,
            anthropic_client,
            cache_dir,
            skip_vision,
            max_workers,
        )
        all_extracts.extend(extracts)
        all_issues.extend(issues)

    return all_extracts, all_issues
