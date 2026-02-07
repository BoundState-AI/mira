#!/usr/bin/env python3
"""
Module: Miul Extractor V2
Purpose: MIUL Extractor v2 - Dynamic 3-Pass AI Extraction

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Load environment FIRST before any imports that need it
import os
try:
    from dotenv import load_dotenv
    for p in [Path(__file__).parent / '.env', Path('C:/BoundState/.env'), Path.home() / '.env']:
        if p.exists():
            load_dotenv(p, override=True)
            logger.info(f"Loaded .env from {p}")
            break
except ImportError:
    pass

# AWS Bedrock vs Direct API
USE_BEDROCK = os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")

# Model IDs - Direct API (use Sonnet 4.5 for everything - better accuracy)
SONNET_MODEL_DIRECT = "claude-sonnet-4-5-20250929"

# Model IDs - AWS Bedrock (GovCloud uses us-gov. prefix)
SONNET_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"

import fitz  # PyMuPDF
from anthropic import Anthropic


def get_anthropic_client(api_key: Optional[str] = None, use_bedrock: bool = USE_BEDROCK):
    """Create Anthropic client - either direct API or AWS Bedrock."""
    if use_bedrock:
        try:
            from anthropic import AnthropicBedrock
        except ImportError:
            raise ImportError("pip install anthropic[bedrock]")

        region = os.getenv("AWS_REGION", "us-gov-west-1")
        logger.info(f"Using AWS Bedrock in region: {region}")
        return AnthropicBedrock(aws_region=region)
    else:
        if not api_key and not os.getenv("ANTHROPIC_API_KEY"):
            logger.warning("ANTHROPIC_API_KEY not set - will need to pass api_key explicitly")
        logger.info("Using direct Anthropic API")
        return Anthropic(api_key=api_key)


def get_model_id(use_bedrock: bool = USE_BEDROCK) -> str:
    """Get the correct model ID based on API type."""
    return SONNET_MODEL_BEDROCK if use_bedrock else SONNET_MODEL_DIRECT


# Runtime model selection - use Sonnet 4.5 for everything
MODEL_ID = get_model_id()

# Anti-hallucination thresholds
MIN_TEXT_FOR_ANCHORING = 500  # Below this = scanned PDF, use pure vision
KNOWN_HALLUCINATIONS = {"MS20002", "MS35206", "MS35338", "MS20426", "MS21042"}


@dataclass
class DrawingInfo:
    """Extracted drawing metadata."""
    path: Path
    drawing_number: str = ""
    title: str = ""
    drawing_type: str = ""  # DETAIL or ASSEMBLY
    parent: str = ""
    cage_code: str = ""
    extracted_text: str = ""
    is_scanned: bool = False
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class MaterialEntry:
    """Single material entry for MIUL."""
    index: int
    parent_index: int
    part_number: str
    nha: str
    description: str
    material_type: str  # METAL, NON-METAL, ASSEMBLY, EEE
    designation: str
    material_spec: str
    process_spec: str
    form: str
    quantity: int
    source_drawing: str
    is_helicoil: bool = False
    helicoil_details: Optional[Dict] = None
    source: str = ""  # NASA SWE-013 traceability



class MIULExtractorV2:
    """Dynamic 3-pass MIUL extraction from engineering drawings."""

    def __init__(self, api_key: Optional[str] = None, use_bedrock: bool = USE_BEDROCK):
        self.use_bedrock = use_bedrock
        self.client = get_anthropic_client(api_key=api_key, use_bedrock=use_bedrock)
        self.drawings: Dict[str, DrawingInfo] = {}
        self.hierarchy: Dict[str, str] = {}  # child -> parent
        self.top_assembly: str = ""  # top-level assembly from drawing tree
        self.all_assemblies: set = set()  # all assembly drawing numbers from DT
        self.materials: List[MaterialEntry] = []

        # Set model ID - use Sonnet 4.5 for everything (better accuracy)
        self.model = get_model_id(use_bedrock)
        logger.info(f"Model: {self.model}")

    # =========================================================================
    # PDF UTILITIES
    # =========================================================================

    def pdf_to_base64(self, pdf_path: Path, dpi: int = 250) -> List[str]:
        """Convert PDF pages to base64 PNG images."""
        doc = fitz.open(pdf_path)
        images = []
        for page in doc:
            # Auto-scale large pages
            rect = page.rect
            w, h = rect.width * dpi / 72, rect.height * dpi / 72
            if max(w, h) > 7500:
                dpi = int(dpi * 7500 / max(w, h) * 0.95)
            pix = page.get_pixmap(dpi=dpi)
            images.append(base64.b64encode(pix.tobytes("png")).decode())
        doc.close()
        return images

    def extract_text(self, pdf_path: Path) -> str:
        """Extract raw text from PDF for anchoring."""
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text("text") for page in doc)
        doc.close()
        return text

    def call_vision(self, images: List[str], prompt: str, model: str, max_tokens: int = 4096) -> str:
        """Call Claude vision API."""
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}} for img in images]
        content.append({"type": "text", "text": prompt})

        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": content}]
        )
        return resp.content[0].text.strip()

    def parse_json(self, raw: str) -> Any:
        """Parse JSON from AI response."""
        # Strip markdown code blocks
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    raw = part[4:].strip()
                    break
                elif part.startswith(("{", "[")):
                    raw = part
                    break
        # Find JSON in text
        if not raw.startswith(("[", "{")):
            for start_char, end_char in [("[", "]"), ("{", "}")]:
                start = raw.find(start_char)
                end = raw.rfind(end_char)
                if start != -1 and end > start:
                    raw = raw[start:end + 1]
                    break
        return json.loads(raw)

    # =========================================================================
    # PASS 1: STRUCTURE EXTRACTION (Sonnet)
    # =========================================================================

    def pass1_structure(self, directory: Path) -> Dict[str, str]:
        """Extract drawing tree hierarchy and classify drawings."""
        logger.info("=" * 60)
        logger.info("PASS 1: STRUCTURE EXTRACTION (Sonnet)")
        logger.info("=" * 60)

        # Files to skip (not engineering drawings)
        SKIP_PATTERNS = ["DOC", "DT", "TREE", "MIUL", "BOM", "LIST"]

        def should_skip(filename: str) -> bool:
            """Check if file is a document, not a drawing."""
            fn_upper = filename.upper()
            for pattern in SKIP_PATTERNS:
                if f"-{pattern}" in fn_upper or fn_upper.startswith(pattern) or fn_upper == f"{pattern}.PDF":
                    return True
            return False

        # Find drawing tree PDF
        dt_candidates = list(directory.glob("*-DT*")) + list(directory.glob("*DOC*")) + list(directory.glob("*tree*"))
        dt_path = None
        for c in dt_candidates:
            if c.suffix.lower() == ".pdf":
                text = self.extract_text(c)
                if "DRAWING" in text.upper() and ("TREE" in text.upper() or "LIST" in text.upper()):
                    dt_path = c
                    break

        if dt_path:
            logger.info(f"Found drawing tree: {dt_path.name}")
            images = self.pdf_to_base64(dt_path)

            prompt = """Analyze this engineering Drawing Tree document.

Extract the COMPLETE parent-child hierarchy of all drawings shown. The tree shows
which parts belong to which assemblies.

CRITICAL RULES:
1. Read ALL drawing numbers EXACTLY as shown (e.g., MER07540-001, GPE-A000-1, 123-456-A)
2. Extract EVERY drawing number visible in the tree
3. Each child reports to its IMMEDIATE parent assembly
4. Identify the TOP-LEVEL assembly (the one at the root with no parent)
5. List ALL assemblies (drawings that contain other parts)
6. Do NOT include self-references
7. Do NOT use DOC/DT/ICD numbers as parents

Return ONLY valid JSON:
{
  "hierarchy": {
    "CHILD_DRAWING_NUMBER": "PARENT_DRAWING_NUMBER",
    ...
  },
  "top_assembly": "THE_TOP_LEVEL_ASSEMBLY_NUMBER",
  "all_assemblies": ["LIST", "OF", "ALL", "ASSEMBLY", "DRAWING", "NUMBERS"]
}

The "all_assemblies" list must include EVERY drawing that contains sub-parts or sub-assemblies,
including the top assembly and all intermediate assemblies shown in the tree."""

            try:
                raw = self.call_vision(images, prompt, self.model)
                data = self.parse_json(raw)
                self.hierarchy = data.get("hierarchy", {})
                self.top_assembly = data.get("top_assembly", "")
                self.all_assemblies = set(data.get("all_assemblies", []))

                # Filter out document numbers (DT, DOC, ICD, etc.) from assemblies
                doc_patterns = ["-DT", "-DOC", "-ICD", "-BOM", "-LIST", "-TREE"]
                def is_document(pn: str) -> bool:
                    pn_upper = pn.upper()
                    return any(pat in pn_upper for pat in doc_patterns)

                # Clean up top_assembly if it's a document
                if self.top_assembly and is_document(self.top_assembly):
                    logger.warning(f"Top assembly '{self.top_assembly}' is a document, searching for actual top assembly...")
                    # Find actual top assembly from hierarchy (node with no parent)
                    children = set(self.hierarchy.keys())
                    parents = set(self.hierarchy.values())
                    roots = [p for p in parents if p not in children and not is_document(p)]
                    if roots:
                        self.top_assembly = roots[0]
                        logger.info(f"Found actual top assembly: {self.top_assembly}")
                    else:
                        self.top_assembly = ""

                # Filter document numbers from all_assemblies
                self.all_assemblies = {a for a in self.all_assemblies if not is_document(a)}

                # Ensure top_assembly is in all_assemblies
                if self.top_assembly:
                    self.all_assemblies.add(self.top_assembly)
                logger.info(f"Extracted {len(self.hierarchy)} parent-child relationships")
                logger.info(f"Identified {len(self.all_assemblies)} assemblies: {sorted(self.all_assemblies)}")
            except Exception as e:
                logger.warning(f"Drawing tree extraction failed: {e}")
        else:
            logger.info("No drawing tree found - will infer hierarchy from title blocks")

        # Scan all PDFs and classify (skip documents)
        all_pdfs = sorted(directory.glob("*.pdf"))
        pdfs = [p for p in all_pdfs if not should_skip(p.name)]
        skipped = [p for p in all_pdfs if should_skip(p.name)]

        if skipped:
            logger.info(f"Skipping {len(skipped)} non-drawing documents: {[p.name for p in skipped]}")
        logger.info(f"Found {len(pdfs)} PDF files")

        for pdf in pdfs:
            text = self.extract_text(pdf)
            is_scanned = len(text) < MIN_TEXT_FOR_ANCHORING

            # Quick classification from text
            drawing_type = "ASSEMBLY" if "PARTS LIST" in text.upper() or "EPL" in text.upper() else "DETAIL"

            # Extract drawing number from filename
            dn = pdf.stem.split("_")[0].upper()

            self.drawings[dn] = DrawingInfo(
                path=pdf,
                drawing_number=dn,
                drawing_type=drawing_type,
                extracted_text=text,
                is_scanned=is_scanned
            )

            # IMPORTANT: Add assemblies detected from PDF content to all_assemblies
            # This catches assemblies that may not be in the Drawing Tree but have EPL/parts lists
            if drawing_type == "ASSEMBLY":
                self.all_assemblies.add(dn)

            logger.info(f"  {pdf.name}: {drawing_type} {'(SCANNED)' if is_scanned else ''}")

        return self.hierarchy

    # =========================================================================
    # PASS 2: BULK EXTRACTION (Haiku Vision)
    # =========================================================================

    def pass2_bulk_extraction(self) -> List[Dict]:
        """Extract EPL tables and title block info from all drawings."""
        logger.info("=" * 60)
        logger.info("PASS 2: BULK EXTRACTION (Haiku Vision)")
        logger.info("=" * 60)

        all_parts = []

        for dn, info in self.drawings.items():
            logger.info(f"Processing: {info.path.name}")
            images = self.pdf_to_base64(info.path)

            # Title block extraction
            title_prompt = """Extract from this engineering drawing:

IMPORTANT: The TITLE field is the part/assembly NAME - a short descriptive name like:
- "TOP PLATE", "BOTTOM PLATE", "ROD", "VALVE ASSEMBLY", "POPPET SUB-ASSEMBLY"
- NOT "CONFIGURATION SHOWN THIS SHEET" or revision notes
- The title is usually in the center-bottom of the title block, in larger text

Look in the title block area (usually bottom right) AND elsewhere on the drawing for:
- TITLE: The part/assembly name (short descriptive title)
- DRAWING NUMBER: The part/drawing number (read EXACTLY as shown)
- MATERIAL: CRITICAL - Search the ENTIRE drawing for material designation:
  * Title block MATERIAL field
  * A labeled "MATERIAL:" callout anywhere on the drawing (often near the part view)
  * Material notes in the drawing area (e.g., "A286 CRES, UNS S66286, PER SAE AMS 5737")
  * Include the FULL material with alloy, temper, UNS number, and spec if shown
- MATERIAL SPEC: The specification (e.g., AMS 5737, ASTM B211)
- USED ON / NEXT ASSY: The parent assembly drawing number

Return ONLY JSON:
{
  "drawing_number": "exact drawing number as shown",
  "title": "the PART NAME from title block",
  "drawing_type": "DETAIL or ASSEMBLY",
  "cage_code": "5-char CAGE code if shown",
  "material": "FULL material designation from ANYWHERE on drawing",
  "material_spec": "material specification number",
  "next_assembly": "drawing number from USED ON field"
}"""

            try:
                # Use Sonnet for title extraction - more accurate than Haiku
                raw = self.call_vision(images[:1], title_prompt, self.model, max_tokens=500)
                title_data = self.parse_json(raw)
                info.title = title_data.get("title", "")
                info.drawing_type = title_data.get("drawing_type", info.drawing_type)
                info.cage_code = title_data.get("cage_code", "")
                if title_data.get("next_assembly"):
                    self.hierarchy[dn] = title_data["next_assembly"]
            except Exception as e:
                logger.warning(f"  Title block failed: {e}")
                title_data = {}

            # Parts list extraction for assemblies
            if info.drawing_type == "ASSEMBLY":
                parts = self._extract_epl(images, info)
                all_parts.extend(parts)
            else:
                # Detail drawing - single part
                part = {
                    "source_drawing": dn,
                    "part_number": dn,
                    "description": info.title or title_data.get("title", ""),
                    "quantity": 1,
                    "designation": title_data.get("material", ""),
                    "material_spec": title_data.get("material_spec", ""),
                    "form": "",
                    "is_detail": True
                }
                all_parts.append(part)
                logger.info(f"  DETAIL: {part['designation'] or 'no material'}")

        logger.info(f"Pass 2 complete: {len(all_parts)} parts extracted")
        return all_parts

    def _extract_epl(self, images: List[str], info: DrawingInfo) -> List[Dict]:
        """Extract Engineering Parts List from assembly drawing."""

        # Build prompt with text anchoring if not scanned
        if info.is_scanned:
            anchor_text = ""
            logger.info("  (Scanned PDF - pure vision mode)")
        else:
            anchor_text = f"""
=== EXTRACTED TEXT (GROUND TRUTH) ===
{info.extracted_text[:8000]}
=== END TEXT ===

CRITICAL: Only return part numbers that appear in the extracted text above.
"""

        prompt = f"""Extract the ENGINEERING PARTS LIST (EPL) table from this assembly drawing.
{anchor_text}
The EPL table typically has columns like: FIND NO., QTY REQD, PART NUMBER, DESCRIPTION, MATERIAL/REMARKS

READ THE TABLE VISUALLY - match each row's PART NUMBER with its QTY from the same row.

CRITICAL RULES:
1. Read the QUANTITY from the QTY column for EACH part - don't guess
2. Extract EVERY row - do not skip any
3. Read part numbers EXACTLY as shown (e.g., MER07543-001, NAS1352N4-12, MS21043-6)
4. Include sub-assembly references (drawing numbers that appear in the EPL)
5. DO NOT hallucinate part numbers not visible in the table
6. Extract the MATERIAL from the MATERIAL/REMARKS column if present

Return ONLY JSON array:
[{{
  "find_no": "item/find number",
  "part_number": "exact part number from table",
  "description": "part title/description",
  "qty": "quantity from QTY column for THIS row",
  "designation": "material designation if shown (e.g., A286, INCONEL 718)",
  "spec": "material spec if shown",
  "form": "form if shown"
}}]"""

        try:
            raw = self.call_vision(images, prompt, self.model)
            parts = self.parse_json(raw)

            # Post-validation against extracted text
            if not info.is_scanned:
                validated = []
                text_lower = (info.extracted_text or "").lower().replace("-", "").replace(" ", "")
                for p in parts:
                    pn = p.get("part_number") or ""
                    pn_clean = pn.lower().replace("-", "").replace(" ", "")
                    if pn_clean in text_lower or pn.upper() in KNOWN_HALLUCINATIONS:
                        if pn.upper() in KNOWN_HALLUCINATIONS:
                            logger.warning(f"  FILTERED (known hallucination): {pn}")
                            continue
                        validated.append(p)
                    else:
                        logger.warning(f"  FILTERED (not in text): {pn}")
                parts = validated

            # Add source drawing
            for p in parts:
                p["source_drawing"] = info.drawing_number

            logger.info(f"  EPL: {len(parts)} parts")
            return parts

        except Exception as e:
            logger.warning(f"  EPL extraction failed: {e}")
            return []

    # =========================================================================
    # PASS 3: DEEP EXTRACTION (Sonnet)
    # =========================================================================

    def pass3_deep_extraction(self) -> Tuple[List[Dict], List[Dict]]:
        """Extract helicoils from NOTES and surface finishes."""
        logger.info("=" * 60)
        logger.info("PASS 3: DEEP EXTRACTION (Sonnet)")
        logger.info("=" * 60)

        helicoils = []
        finishes = []

        for dn, info in self.drawings.items():
            if info.drawing_type != "DETAIL":
                continue

            logger.info(f"Deep extraction: {info.path.name}")
            images = self.pdf_to_base64(info.path)

            prompt = f"""Analyze this DETAIL engineering drawing carefully.

Extract from the NOTES section:

1. HELICOIL/HELICAL COIL INSERTS - Look for patterns like:
   - "24X .2500-20 UNC-3B HELICAL COIL INSERT THD PER NASM33537"
   - "59X TAP FOR #6-40 HELICOIL INSERT"
   - Quantity (e.g., 24X), thread size, spec number

2. SURFACE FINISHES - Look for:
   - Chemical conversion coating (MIL-DTL-5541, Chem Film, Alodine)
   - Passivation (ASTM-A967, AMS-QQ-P-35)
   - Powder coat (FED-STD-595)
   - Anodize, paint, plating

=== EXTRACTED TEXT FOR VALIDATION ===
{info.extracted_text[:6000]}
=== END TEXT ===

Return ONLY JSON:
{{
  "helicoils": [
    {{
      "quantity": 24,
      "thread_size": ".2500-20",
      "thread_class": "UNC-3B",
      "spec": "NASM33537",
      "raw_callout": "exact text from drawing"
    }}
  ],
  "surface_finishes": [
    {{
      "finish_type": "CHEM FILM",
      "spec": "MIL-DTL-5541",
      "class": "1A or 3 if specified",
      "color": "GOLD, CLEAR, etc if specified"
    }}
  ]
}}

If no helicoils or finishes found, return empty arrays."""

            try:
                raw = self.call_vision(images, prompt, self.model)
                data = self.parse_json(raw)

                # Process helicoils
                for h in data.get("helicoils", []):
                    h["source_drawing"] = dn
                    h["parent"] = self.hierarchy.get(dn, "")
                    helicoils.append(h)
                    logger.info(f"  HELICOIL: {h.get('quantity')}X {h.get('thread_size')} {h.get('spec')}")

                # Process finishes
                for f in data.get("surface_finishes", []):
                    f["source_drawing"] = dn
                    finishes.append(f)
                    logger.info(f"  FINISH: {f.get('finish_type')} {f.get('spec')}")

            except Exception as e:
                logger.warning(f"  Deep extraction failed: {e}")

        logger.info(f"Pass 3 complete: {len(helicoils)} helicoils, {len(finishes)} finishes")
        return helicoils, finishes

    # =========================================================================
    # MIUL BUILDER
    # =========================================================================

    def build_miul(self, parts: List[Dict], helicoils: List[Dict], finishes: List[Dict]) -> Dict:
        """Build final MIUL structure per NASA MIUL Excel template format.

        Key fields per spec:
        - Index: Sequential 1,2,3... ending with -1
        - Parent: INDEX number of parent row (0 for top-level)
        - NHA: PART NUMBER of parent (for tree parts only, blank for subparts)
        - Part Description / Nomenclature: Drawing title
        - Designation: Material (e.g., "Aluminum 6061-T6")
        - Material Spec: Drawing material spec (e.g., AMS-QQ-A-250/11)
        - Process Spec: Surface finish (e.g., MIL-DTL-5541)
        - Title: Drawing title
        """
        logger.info("=" * 60)
        logger.info("BUILDING MIUL")
        logger.info("=" * 60)

        materials = []
        index = 1

        # Build lookup: part_number -> index (for parent references)
        pn_to_index: Dict[str, int] = {}

        def clean_pn(pn: str) -> str:
            """Clean part number - remove description in parentheses, .DRW suffix, strip whitespace."""
            if not pn:
                return ""
            cleaned = pn.split("(")[0].strip().upper()
            # Remove common file extensions that AI might include
            for ext in [".DRW", ".PDF", ".DWG"]:
                if cleaned.endswith(ext):
                    cleaned = cleaned[:-len(ext)]
            return cleaned

        def find_matching_drawing(part_number: str) -> Optional[str]:
            """Find the drawing file that matches this part number using fuzzy matching.

            This is AI-friendly: it uses simple string matching that works for ANY
            drawing numbering scheme (MER07xxx, GPE-xxx, Boeing, Lockheed, etc.)
            """
            pn_clean = clean_pn(part_number)
            if not pn_clean:
                return None

            # Direct match
            if pn_clean in self.drawings:
                return pn_clean

            # Try matching against drawing filenames
            for dn in self.drawings:
                dn_clean = clean_pn(dn)
                # Exact match after cleaning
                if pn_clean == dn_clean:
                    return dn
                # Part number is contained in drawing name or vice versa
                if pn_clean in dn_clean or dn_clean in pn_clean:
                    return dn

            return None

        def is_assembly_drawing(part_number: str) -> bool:
            """Check if this part number is an assembly (from the Drawing Tree)."""
            pn_clean = clean_pn(part_number)
            # Check against AI-extracted assembly list
            for assy in self.all_assemblies:
                if clean_pn(assy) == pn_clean:
                    return True
            return False

        def is_valid_drawing_number(pn: str) -> bool:
            """Check if string looks like a valid drawing number (not garbage from title block).

            Valid: GPE-A000-1, MER07540-001, 123-456, ABC-123-X
            Invalid: DOOR SHIM, CAMPUS BOX 29, UNLESS OTHERWISE SPECIFIED, 15-5 PH SS
            """
            if not pn or len(pn) < 3:
                return False
            # Must contain at least one dash and be alphanumeric-dash format
            if "-" not in pn:
                return False
            # Must start with letter or digit
            if not pn[0].isalnum():
                return False
            # Should have format like XXX-YYY or XXX-YYY-Z (drawing number pattern)
            # Check that it matches typical drawing number patterns
            # Valid patterns: GPE-010, MER07540-001, 123-456-A
            pattern = re.match(r'^[A-Z0-9]+-[A-Z0-9]+(-[A-Z0-9]+)?$', pn.upper())
            if not pattern:
                return False
            # Reject if it contains common garbage words
            garbage_words = ['SHIM', 'CAMPUS', 'BOX', 'UNLESS', 'OTHERWISE', 'SPECIFIED',
                           'NOTES', 'MATERIAL', 'FINISH', 'TOLERANCES', 'INTERPRET']
            pn_upper = pn.upper()
            for word in garbage_words:
                if word in pn_upper:
                    return False
            return True

        # Build lookup: source_drawing -> surface finish spec
        finish_by_drawing: Dict[str, str] = {}
        for f in finishes:
            src = f.get("source_drawing", "")
            spec = f.get("spec", "")
            if src and spec:
                # Combine multiple finishes for same drawing
                if src in finish_by_drawing:
                    finish_by_drawing[src] += f"; {spec}"
                else:
                    finish_by_drawing[src] = spec

        # Build set of known drawing numbers for duplicate detection (simple and generic)
        known_drawings = set()
        for dn in self.drawings:
            known_drawings.add(clean_pn(dn))

        def is_drawing_reference(part_number: str) -> bool:
            """Check if part number is a reference to another drawing (generic approach)."""
            if not part_number:
                return False
            pn_clean = clean_pn(part_number)
            # Check if it matches any known drawing
            return pn_clean in known_drawings or find_matching_drawing(part_number) is not None

        def get_parent_pn(source_drawing: str) -> str:
            """Get parent part number from hierarchy (generic approach).

            Uses the AI-extracted hierarchy directly without pattern assumptions.
            """
            source_clean = clean_pn(source_drawing)

            # Try direct lookup first
            parent = self.hierarchy.get(source_drawing, "")
            if parent and parent not in ("USED ON", "N/A", "NONE", "-", "not provided", "not specified", ""):
                if is_valid_drawing_number(parent):
                    return parent

            # Try cleaned version
            for child, parent in self.hierarchy.items():
                if clean_pn(child) == source_clean:
                    if parent and parent not in ("USED ON", "N/A", "NONE", "-", "not provided", "not specified", ""):
                        if is_valid_drawing_number(parent):
                            return parent

            return ""

        # Pass 0: Add ALL assemblies from the Drawing Tree (AI-extracted list)
        # This ensures every assembly has an index for parent lookup
        logger.info(f"Adding {len(self.all_assemblies)} assemblies from Drawing Tree...")

        # Sort assemblies: top assembly first, then by hierarchy depth
        def get_depth(assy: str) -> int:
            """Get depth in hierarchy (0 = top, 1 = direct child, etc.)"""
            if assy == self.top_assembly:
                return 0
            depth = 0
            current = assy
            while current in self.hierarchy and depth < 10:
                current = self.hierarchy[current]
                depth += 1
            return depth

        assembly_list = sorted(self.all_assemblies, key=get_depth)

        for assy_pn in assembly_list:
            # Find the corresponding drawing file
            matching_drawing = find_matching_drawing(assy_pn)

            # Get parent of this assembly from hierarchy
            parent_pn = self.hierarchy.get(assy_pn, "")
            if not parent_pn:
                # Try to find parent by checking if any hierarchy entry matches
                assy_clean = clean_pn(assy_pn)
                for child, parent in self.hierarchy.items():
                    if clean_pn(child) == assy_clean:
                        parent_pn = parent
                        break

            # Find parent index
            parent_idx = 0
            if parent_pn:
                parent_clean = clean_pn(parent_pn)
                parent_idx = pn_to_index.get(parent_pn, pn_to_index.get(parent_clean, 0))

            drawing_info = self.drawings.get(matching_drawing) if matching_drawing else None
            title = drawing_info.title if drawing_info else assy_pn

            entry = {
                "index": index,
                "parent": parent_idx,
                "part_number": assy_pn,
                "nha": parent_pn if parent_pn and parent_pn not in ("USED ON", "N/A", "NONE", "-", "") else "",
                "part_description": title,
                "nomenclature": title,
                "title": title,
                "material_type": "ASSEMBLY",
                "designation": "",
                "material_spec": "",
                "process_spec": "",
                "form": "",
                "qty": 1,
                "source_drawing": matching_drawing or assy_pn,
                "dwg_number": assy_pn
            }
            materials.append(entry)

            # Register this assembly in the lookup with multiple keys for flexibility
            pn_to_index[assy_pn] = index
            pn_to_index[clean_pn(assy_pn)] = index
            if matching_drawing:
                pn_to_index[matching_drawing] = index
                pn_to_index[clean_pn(matching_drawing)] = index

            logger.info(f"  Added assembly: {assy_pn} (index={index}, parent_idx={parent_idx})")
            index += 1

        def clean_part_number(pn: str) -> str:
            """Clean part number - remove description in parentheses.

            GPE-052-A (ROD CONNECTOR DRAWING) -> GPE-052-A
            """
            if "(" in pn:
                return pn.split("(")[0].strip()
            return pn

        # First pass: add all parts (skip drawing references from EPL)
        skipped_refs = []
        for p in parts:
            source_dn = p.get("source_drawing", "")
            pn = clean_part_number(p.get("part_number", ""))

            # Skip EPL entries that are references to other drawings
            is_from_epl = not p.get("is_detail", False)
            if is_from_epl and is_drawing_reference(pn):
                skipped_refs.append(pn)
                continue

            # Get parent info - different logic for EPL vs detail drawings
            # EPL parts: parent is the source assembly drawing they came from
            # Detail drawings: parent comes from drawing tree hierarchy
            is_from_epl_part = not p.get("is_detail", False)

            if is_from_epl_part:
                # EPL parts: parent is the source assembly drawing
                source_norm = clean_pn(source_dn)
                parent_idx = pn_to_index.get(source_dn, pn_to_index.get(source_norm, 0))
                parent_pn = ""  # EPL parts don't have NHA - they're subparts
            else:
                # Detail drawings: parent from drawing tree hierarchy
                parent_pn = get_parent_pn(source_dn)
                parent_norm = clean_pn(parent_pn) if parent_pn else ""
                parent_idx = pn_to_index.get(parent_norm, pn_to_index.get(parent_pn, 0))

            # Determine if this is a "tree part" vs "subpart" per NASA MIUL spec:
            # - Tree parts: Parts in the drawing tree (have NHA = parent PART NUMBER)
            # - Subparts: Hardware/fasteners from EPL (have NHA = blank)
            #
            # Detail drawings are TREE PARTS - NHA = parent part number
            # EPL items (fasteners, COTS) are SUBPARTS - blank NHA
            is_tree_part = p.get("is_detail", False)  # Detail drawings are tree parts

            # NHA must be a valid drawing number - filter garbage from title block extractions
            nha_value = ""
            if is_tree_part and parent_pn and is_valid_drawing_number(parent_pn):
                nha_value = parent_pn

            # Get surface finish for this drawing
            process_spec = finish_by_drawing.get(source_dn, "")

            # Determine material type
            designation = p.get("designation", "")
            mat_type = self._classify_material(designation, pn)

            # Get title/description
            # - For DETAIL drawings: Use the drawing's title (from title block)
            # - For EPL parts: Use the part_title/description from the EPL table
            is_detail = p.get("is_detail", False)
            if is_detail:
                # Detail drawing - use title from drawing's title block
                drawing_info = self.drawings.get(source_dn)
                title = drawing_info.title if drawing_info else p.get("description", "")
            else:
                # EPL part - use description from the EPL extraction
                title = p.get("description", "")

            entry = {
                "index": index,
                "parent": parent_idx,  # INDEX of parent row
                "part_number": pn,
                "nha": nha_value,  # Tree parts: parent PN (validated), Subparts: blank
                "part_description": title,
                "nomenclature": title,
                "title": title,
                "material_type": mat_type,
                "designation": designation,  # Material: "Aluminum 6061-T6"
                "material_spec": p.get("spec", p.get("material_spec", "")),  # AMS-QQ-A-250/11
                "process_spec": process_spec,  # Surface finish: MIL-DTL-5541
                "form": p.get("form", ""),
                "qty": self._parse_qty(p.get("qty", p.get("quantity", 1))),
                "source_drawing": source_dn,
                "dwg_number": source_dn.split("(")[0].strip() if "(" in source_dn else source_dn
            }
            materials.append(entry)
            pn_to_index[pn] = index
            # Only add source_dn mapping for DETAIL drawings, not EPL parts
            # (EPL parts share the same source_dn as their parent assembly)
            if not is_from_epl_part:
                pn_to_index[source_dn] = index  # Also map by source drawing
                pn_to_index[clean_pn(source_dn)] = index  # Normalized key for hierarchy lookup
            index += 1

        # Second pass: add helicoils (consolidated by parent + thread size)
        # Group helicoils by parent drawing and thread size
        helicoil_groups: Dict[tuple, List[Dict]] = {}
        for h in helicoils:
            parent_dn = h.get("source_drawing", "")
            thread_size = h.get("thread_size", "")
            key = (parent_dn, thread_size)
            if key not in helicoil_groups:
                helicoil_groups[key] = []
            helicoil_groups[key].append(h)

        # Create consolidated helicoil entries
        for (parent_dn, thread_size), group in helicoil_groups.items():
            parent_idx = pn_to_index.get(parent_dn, pn_to_index.get(clean_pn(parent_dn), 0))
            total_qty = sum(h.get("quantity", 0) for h in group)

            # Get best spec from group
            spec = next((h.get("spec") for h in group if h.get("spec")), "NASM33537")
            thread_class = next((h.get("thread_class") for h in group if h.get("thread_class")), "")

            # Build installation note (e.g., "59x + 30x + 4x installations")
            install_note = " + ".join(f"{h.get('quantity')}x" for h in group if h.get('quantity'))

            # Helicoils are subparts - blank NHA per NASA MIUL spec
            entry = {
                "index": index,
                "parent": parent_idx,  # INDEX of parent row
                "part_number": f"HCC-{(thread_size or '').replace('.', '').replace('-', '-').replace(' ', '')}",
                "nha": "",  # Subparts have blank NHA
                "part_description": f"Helicoil Insert, {thread_size} {thread_class}".strip(),
                "nomenclature": f"Helicoil Insert, {thread_size}",
                "title": "",
                "material_type": "METAL",
                "designation": "Stainless Steel 18-8",  # Helicoils are typically 18-8 SS
                "material_spec": spec,
                "process_spec": "",
                "form": "INSERT",
                "qty": total_qty,
                "source_drawing": parent_dn,
                "dwg_number": parent_dn.split("(")[0].strip() if "(" in parent_dn else parent_dn,
                "is_helicoil": True,
                "helicoil_details": {
                    "thread_size": thread_size,
                    "thread_class": thread_class,
                    "spec": spec,
                    "installations": install_note,
                    "individual_callouts": group
                }
            }
            materials.append(entry)
            index += 1

        # MAPTIS Material Code Lookup - add material codes to all entries with designations
        logger.info("Looking up MAPTIS material codes...")
        lookup_stats = {"matched": 0, "unresolved": 0, "ambiguous": 0, "skipped": 0}

        def normalize_designation_for_lookup(designation: str) -> str:
            """Clean designation for MAPTIS lookup.

            Handles:
            - Strength designations: "A286 (180 KSI)" -> "A286"
            - Specification notes: "A286 CRES, UNS S66286" -> "A286 CRES, UNS S66286"
            - Extra whitespace
            """
            if not designation:
                return ""

            cleaned = designation.strip()

            # Remove strength designations like "(180 KSI)", "(160 KSI)", "(150 KSI)"
            # Common patterns: (NNN KSI), (NNN,NNN PSI), etc.
            import re
            strength_pattern = r'\s*\(\s*\d+[,.]?\d*\s*(?:KSI|ksi|PSI|psi)\s*\)'
            cleaned = re.sub(strength_pattern, '', cleaned)

            # Also handle patterns like "A286, 160 KSI" without parentheses
            strength_pattern2 = r',?\s*\d+\s*(?:KSI|ksi)\s*$'
            cleaned = re.sub(strength_pattern2, '', cleaned)

            return cleaned.strip()

        try:
            from mira.miul.material_code_lookup import get_lookup_service
            lookup_service = get_lookup_service()

            for entry in materials:
                designation = entry.get("designation", "")
                mat_type = entry.get("material_type", "")

                # Skip assemblies and entries without designations
                if mat_type == "ASSEMBLY" or not designation:
                    lookup_stats["skipped"] += 1
                    continue

                # Normalize designation for lookup (strip strength designations)
                designation_normalized = normalize_designation_for_lookup(designation)

                # Look up material code
                match = lookup_service.lookup_material_code(designation_normalized)
                if match.material_code:
                    entry["material_code"] = match.material_code
                    entry["material_code_confidence"] = match.confidence
                    entry["material_code_method"] = match.method
                    lookup_stats["matched"] += 1
                elif match.method == "ambiguous":
                    entry["material_code"] = None
                    entry["material_code_candidates"] = [c.material_code for c in (match.candidates or [])]
                    lookup_stats["ambiguous"] += 1
                else:
                    entry["material_code"] = None
                    lookup_stats["unresolved"] += 1

            logger.info(f"MAPTIS lookup complete: {lookup_stats['matched']} matched, "
                       f"{lookup_stats['unresolved']} unresolved, {lookup_stats['ambiguous']} ambiguous, "
                       f"{lookup_stats['skipped']} skipped (assemblies/no designation)")
        except ImportError as e:
            logger.warning(f"MAPTIS lookup service not available: {e}")
        except Exception as e:
            logger.warning(f"MAPTIS lookup failed: {e}")

        # Build summary
        total_helicoils = sum(h.get("quantity", 0) for h in helicoils)
        maptis_coverage = lookup_stats["matched"] / max(1, lookup_stats["matched"] + lookup_stats["unresolved"] + lookup_stats["ambiguous"])

        miul = {
            "extraction_method": "dynamic_3pass_v2",
            "api_type": "bedrock" if self.use_bedrock else "direct",
            "model": self.model,
            "summary": {
                "total_materials": len(materials),
                "total_helicoils": total_helicoils,
                "assemblies": sum(1 for m in materials if m["material_type"] == "ASSEMBLY"),
                "details": sum(1 for m in materials if m["material_type"] != "ASSEMBLY"),
                "surface_finishes": len(finishes),
                "maptis_lookup": {
                    "matched": lookup_stats["matched"],
                    "unresolved": lookup_stats["unresolved"],
                    "ambiguous": lookup_stats["ambiguous"],
                    "skipped": lookup_stats["skipped"],
                    "coverage_pct": round(maptis_coverage * 100, 1)
                }
            },
            "hierarchy": self.hierarchy,
            "materials": materials,
            "surface_finishes": finishes
        }

        if skipped_refs:
            logger.info(f"Skipped {len(skipped_refs)} drawing references from EPL (avoiding duplicates): {skipped_refs[:10]}{'...' if len(skipped_refs) > 10 else ''}")
        logger.info(f"MIUL built: {len(materials)} materials, {total_helicoils} helicoils")
        return miul

    def _parse_qty(self, val) -> int:
        """Parse quantity, handling A/R, REF, etc."""
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            val = val.strip().upper()
            if val in ("A/R", "AR", "REF", "-", ""):
                return 1
            try:
                return int(val)
            except ValueError:
                return 1
        return 1

    def _classify_material(self, designation: str, part_number: str) -> str:
        """Classify material type."""
        d = (designation or "").upper()
        pn = (part_number or "").upper()

        # Assemblies
        if not designation or "ASSY" in pn or "A0" in pn:
            return "ASSEMBLY"

        # Metals
        metals = ["ALUMINUM", "AL", "STEEL", "CRES", "INCONEL", "TITANIUM", "BRASS", "BRONZE", "COPPER", "A286", "SS", "6061", "7075", "304", "316"]
        if any(m in d for m in metals):
            return "METAL"

        # Non-metals
        nonmetals = ["KAPTON", "FEP", "TEFLON", "SILICONE", "RUBBER", "PLASTIC", "FOAM", "THERMAL", "CERAMIC"]
        if any(m in d for m in nonmetals):
            return "NON-METAL"

        # EEE
        if any(x in pn for x in ["EEE", "ELECT", "CONN", "WIRE", "CABLE"]):
            return "EEE"

        return "METAL"  # Default

    # =========================================================================
    # DT VERIFICATION
    # =========================================================================

    def verify_against_dt(self, dt_pdf_path: str, miul: Dict = None) -> Dict:
        """Verify MIUL structure against Drawing Tree using AI vision.

        Uses Claude Vision to extract the hierarchy from the DT drawing,
        then compares it against the generated MIUL to identify:
        - Missing assemblies (in DT but not in MIUL)
        - Extra assemblies (in MIUL but not in DT)
        - Hierarchy mismatches (wrong parent relationships)

        Args:
            dt_pdf_path: Path to the Drawing Tree PDF
            miul: The MIUL dict from build_miul(). If None, uses self from last extraction.

        Returns:
            Dict with verification results:
            - status: "PASS" or "FAIL"
            - dt_assemblies: List of assemblies from DT
            - miul_assemblies: List of assemblies from MIUL
            - missing_from_miul: Assemblies in DT but not in MIUL
            - extra_in_miul: Assemblies in MIUL but not in DT
            - hierarchy_errors: List of parent-child mismatches
        """
        logger.info(f"Verifying MIUL against Drawing Tree: {dt_pdf_path}")

        dt_path = Path(dt_pdf_path)
        if not dt_path.exists():
            return {"status": "ERROR", "error": f"DT file not found: {dt_pdf_path}"}

        # Convert DT PDF to base64 images
        images = self.pdf_to_base64(dt_path)
        if not images:
            return {"status": "ERROR", "error": "Could not convert DT PDF to images"}

        # AI prompt to extract DT hierarchy
        prompt = """Analyze this Drawing Tree document and extract the COMPLETE assembly hierarchy.

For EACH assembly shown in the tree, identify:
1. The drawing/part number (e.g., MER07540-001, MER07543-001, GPE-052-A)
2. Its parent assembly (the assembly it belongs to)
3. Whether it's a top-level assembly (no parent)

CRITICAL RULES:
- Extract ONLY actual drawing numbers (MER#####-###, GPE-###-#, etc.)
- Do NOT include document numbers (-DT, -DOC, -ICD, -BOM)
- Read numbers EXACTLY as shown
- Include ALL assemblies visible in the tree

Return ONLY valid JSON:
{
  "top_assembly": "THE_TOP_LEVEL_ASSEMBLY_NUMBER",
  "hierarchy": {
    "CHILD_DRAWING": "PARENT_DRAWING",
    "CHILD_DRAWING_2": "PARENT_DRAWING",
    ...
  },
  "all_assemblies": ["LIST", "OF", "ALL", "ASSEMBLY", "NUMBERS"]
}"""

        # Call Claude Vision to extract DT hierarchy
        try:
            raw_response = self.call_vision(images, prompt, model=MODEL_ID, max_tokens=4096)
            dt_data = self.parse_json(raw_response)

            if not dt_data:
                return {"status": "ERROR", "error": "Could not parse DT extraction response"}

        except Exception as e:
            logger.error(f"DT extraction failed: {e}")
            return {"status": "ERROR", "error": str(e)}

        # Extract data from DT
        dt_top = dt_data.get("top_assembly", "")
        dt_hierarchy = dt_data.get("hierarchy", {})
        dt_assemblies = set(dt_data.get("all_assemblies", []))

        # Add top assembly to set
        if dt_top:
            dt_assemblies.add(dt_top)

        # Extract assemblies from MIUL materials list
        miul_assemblies = set()
        miul_nha_map = {}  # part_number -> nha

        materials = miul.get("materials", []) if miul else []
        for m in materials:
            pn = str(m.get("part_number", ""))
            nha = str(m.get("nha", ""))
            material_type = m.get("material_type", "")

            # Include if it's an assembly or has NHA (tree part)
            if material_type == "ASSEMBLY" or nha:
                # Clean the part number (remove .DRW suffix)
                clean_pn = re.sub(r'\.DRW.*$', '', pn, flags=re.IGNORECASE)
                if clean_pn:
                    miul_assemblies.add(clean_pn)
                    miul_nha_map[clean_pn] = re.sub(r'\.DRW.*$', '', nha, flags=re.IGNORECASE)

        # Clean DT assemblies (remove .DRW suffixes)
        dt_assemblies_clean = {re.sub(r'\.DRW.*$', '', a, flags=re.IGNORECASE) for a in dt_assemblies}

        # Compare
        missing_from_miul = dt_assemblies_clean - miul_assemblies
        extra_in_miul = miul_assemblies - dt_assemblies_clean

        # Check hierarchy relationships
        hierarchy_errors = []
        for child, parent in dt_hierarchy.items():
            child_clean = re.sub(r'\.DRW.*$', '', child, flags=re.IGNORECASE)
            parent_clean = re.sub(r'\.DRW.*$', '', parent, flags=re.IGNORECASE)

            # Find this child in MIUL and check its NHA
            if child_clean in miul_nha_map:
                miul_nha = miul_nha_map[child_clean]
                if miul_nha and parent_clean and miul_nha.upper() != parent_clean.upper():
                    hierarchy_errors.append({
                        "child": child_clean,
                        "dt_parent": parent_clean,
                        "miul_nha": miul_nha,
                    })

        # Determine status
        status = "PASS" if not missing_from_miul and not hierarchy_errors else "FAIL"

        result = {
            "status": status,
            "dt_top_assembly": dt_top,
            "dt_assemblies": sorted(dt_assemblies_clean),
            "miul_assemblies": sorted(miul_assemblies),
            "missing_from_miul": sorted(missing_from_miul),
            "extra_in_miul": sorted(extra_in_miul),
            "hierarchy_errors": hierarchy_errors,
            "summary": {
                "dt_count": len(dt_assemblies_clean),
                "miul_count": len(miul_assemblies),
                "missing_count": len(missing_from_miul),
                "extra_count": len(extra_in_miul),
                "hierarchy_error_count": len(hierarchy_errors),
            },
        }

        if status == "PASS":
            logger.info(f"DT Verification PASSED: {len(miul_assemblies)} assemblies match")
        else:
            logger.warning(f"DT Verification FAILED: "
                          f"{len(missing_from_miul)} missing, {len(hierarchy_errors)} hierarchy errors")

        return result

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    def extract(self, directory: Path, output_path: Optional[Path] = None, dt_pdf_path: Optional[Path] = None) -> Dict:
        """Run full 3-pass extraction on a drawing folder.

        Args:
            directory: Path to folder containing drawing PDFs
            output_path: Optional path for output JSON. Defaults to directory/name_MIUL.json
            dt_pdf_path: Optional path to Drawing Tree PDF for verification

        Returns:
            Dict containing MIUL data and optional verification results
        """
        directory = Path(directory)

        logger.info("=" * 60)
        logger.info(f"MIUL EXTRACTOR V2 - {directory.name}")
        logger.info("=" * 60)

        # Pass 1: Structure
        self.pass1_structure(directory)

        # Pass 2: Bulk extraction
        parts = self.pass2_bulk_extraction()

        # Pass 3: Deep extraction
        helicoils, finishes = self.pass3_deep_extraction()

        # Build MIUL
        miul = self.build_miul(parts, helicoils, finishes)

        # Optional: Verify against Drawing Tree
        if dt_pdf_path:
            logger.info(f"Verifying MIUL against Drawing Tree: {dt_pdf_path}")
            verification = self.verify_against_dt(str(dt_pdf_path), miul)
            miul["verification"] = verification

            if verification.get("status") == "FAIL":
                logger.warning(f"DT Verification FAILED:")
                logger.warning(f"  Missing from MIUL: {verification.get('missing_from_miul', [])}")
                logger.warning(f"  Hierarchy errors: {verification.get('hierarchy_errors', [])}")
            else:
                logger.info("MIUL verification PASSED against Drawing Tree")

        # Save output
        if output_path is None:
            output_path = directory / f"{directory.name}_MIUL.json"

        with open(output_path, "w") as f:
            json.dump(miul, f, indent=2)

        logger.info(f"MIUL saved to: {output_path}")

        # Print tree
        self._print_tree(miul)

        return miul

    def _print_tree(self, miul: Dict):
        """Print material tree to console."""
        print("\n" + "=" * 60)
        print("MATERIAL TREE")
        print("=" * 60)

        materials = miul.get("materials", [])

        # Build lookup by parent INDEX
        by_parent: Dict[int, List[Dict]] = {}
        for m in materials:
            pi = m.get("parent", 0)  # Use 'parent' field (index of parent)
            if pi not in by_parent:
                by_parent[pi] = []
            by_parent[pi].append(m)

        def print_node(idx: int, depth: int):
            children = by_parent.get(idx, [])
            for c in children:
                prefix = "  " * depth + "+-- "
                helicoil_tag = " [HELICOIL]" if c.get("is_helicoil") else ""
                qty = f"({c.get('qty', 1)}x) " if c.get("qty", 1) > 1 else ""
                designation = c.get('designation') or ''
                proc = c.get('process_spec', '')
                proc_tag = f" [{proc[:20]}]" if proc else ""
                print(f"{prefix}{qty}{c.get('part_number', '???')}: {designation[:35]}{proc_tag}{helicoil_tag}")
                print_node(c.get("index", 0), depth + 1)

        # Start from root (parent = 0)
        print_node(0, 0)

        print("\n" + "=" * 60)
        print(f"Total: {miul['summary']['total_materials']} materials, {miul['summary']['total_helicoils']} helicoils")
        print("=" * 60)


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MIUL Extractor v2 - Dynamic 3-Pass AI Extraction")
    parser.add_argument("directory", type=Path, help="Directory containing drawing PDFs")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON path")
    parser.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    parser.add_argument("--bedrock", action="store_true", help="Use AWS Bedrock instead of direct API (or set USE_BEDROCK=1)")
    parser.add_argument("--region", default="us-gov-west-1", help="AWS region for Bedrock (default: us-gov-west-1)")
    args = parser.parse_args()

    # Set region if using Bedrock
    if args.bedrock:
        os.environ["USE_BEDROCK"] = "1"
        os.environ["AWS_REGION"] = args.region

    use_bedrock = args.bedrock or USE_BEDROCK
    extractor = MIULExtractorV2(api_key=args.api_key, use_bedrock=use_bedrock)
    extractor.extract(args.directory, args.output)


if __name__ == "__main__":
    main()
