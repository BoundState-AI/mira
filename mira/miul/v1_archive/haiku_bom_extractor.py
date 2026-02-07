#!/usr/bin/env python3
"""
Module: Haiku Bom Extractor
Purpose: Haiku Vision MIUL Generator – PURE AI, NO LOCAL OCR, NO PYPDF2 GARBAGE

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), JSC 27301F Section 4.2.1, NASA-STD-6016C
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    for p in [Path(__file__).parent.parent / '.env', Path(__file__).parent / '.env', Path('C:/BoundState/.env')]:
        if p.exists():
            load_dotenv(p)
            break
except ImportError:
    pass

import base64

import fitz  # PyMuPDF - no external dependencies needed
import pandas as pd

# Material code lookup (optional)
try:
    from mira.miul.material_code_lookup import get_lookup_service
    MATERIAL_LOOKUP_AVAILABLE = True
except Exception:
    MATERIAL_LOOKUP_AVAILABLE = False

# AWS Bedrock vs Direct API
USE_BEDROCK = os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")

# Model IDs
HAIKU_MODEL_DIRECT = "claude-3-haiku-20240307"
HAIKU_MODEL_BEDROCK = "anthropic.claude-3-haiku-20240307-v1:0"


def get_anthropic_client(api_key: Optional[str] = None, use_bedrock: bool = USE_BEDROCK):
    """Create Anthropic client - either direct API or AWS Bedrock."""
    if use_bedrock:
        try:
            from anthropic import AnthropicBedrock
        except ImportError:
            raise ImportError("pip install anthropic[bedrock]")

        region = os.getenv("AWS_REGION", "us-east-1")
        logger.info(f"Using AWS Bedrock in region: {region}")
        return AnthropicBedrock(aws_region=region), HAIKU_MODEL_BEDROCK
    else:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key), HAIKU_MODEL_DIRECT


# =============================================================================
# STEP 1: HAIKU EXTRACTION (Expensive - produces JSON)
# =============================================================================

class HaikuBOMExtractor:
    """Extract BOM data from engineering drawings using Claude Haiku vision."""

    def __init__(self, api_key: Optional[str] = None, use_bedrock: bool = USE_BEDROCK):
        self.client, self.model = get_anthropic_client(api_key=api_key, use_bedrock=use_bedrock)
        logger.info(f"Initialized extractor with model: {self.model}")

    def pdf_to_base64_images(self, pdf_path: Path, dpi: int = 150, max_pixels: int = 7500) -> List[str]:
        """Convert PDF pages to base64-encoded PNG images.

        Args:
            pdf_path: Path to PDF file
            dpi: Target DPI (may be reduced for large pages)
            max_pixels: Maximum dimension in pixels (Haiku limit is 8000)

        Returns:
            List of base64-encoded PNG images
        """
        doc = fitz.open(pdf_path)
        b64_images = []
        for page in doc:
            # Check if page would exceed max_pixels at target DPI
            rect = page.rect
            width_at_dpi = rect.width * dpi / 72  # PDF points to pixels
            height_at_dpi = rect.height * dpi / 72

            # Auto-reduce DPI if page is too large
            actual_dpi = dpi
            if max(width_at_dpi, height_at_dpi) > max_pixels:
                # Calculate DPI that keeps largest dimension under limit
                scale_factor = max_pixels / max(width_at_dpi, height_at_dpi)
                actual_dpi = int(dpi * scale_factor * 0.95)  # 5% margin
                logger.info(f"Page {page.number + 1}: Reducing DPI from {dpi} to {actual_dpi} (page is {int(width_at_dpi)}x{int(height_at_dpi)}px)")

            pix = page.get_pixmap(dpi=actual_dpi)
            img_bytes = pix.tobytes("png")
            b64_images.append(base64.b64encode(img_bytes).decode("utf-8"))
        doc.close()
        return b64_images

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract raw text from PDF using PyMuPDF.

        This is used to ANCHOR Haiku vision to actual document content,
        preventing hallucination of part numbers that don't exist.

        Returns:
            Concatenated text from all pages
        """
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                text_parts.append(text)
        doc.close()
        return "\n\n".join(text_parts)

    def call_haiku_vision(self, b64_images: List[str], prompt: str, max_tokens: int = 4096) -> str:
        """Send images to Haiku vision API."""
        content = []
        for b64_img in b64_images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64_img}
            })
        content.append({"type": "text", "text": prompt})

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": content}]
        )
        return resp.content[0].text.strip()

    def parse_json_response(self, raw: str) -> Any:
        """Parse JSON from Haiku response, handling markdown wrappers and surrounding text."""
        # First try: handle markdown code blocks
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    raw = part[4:].strip()
                    break
                elif part.startswith("{") or part.startswith("["):
                    raw = part
                    break

        # Second try: if response starts with "json" prefix
        if raw.startswith("json"):
            raw = raw.removeprefix("json").strip()

        # Third try: find JSON array in text (handles "Here is the JSON..." prefix)
        # Look for the first '[' and last ']' to extract JSON array
        if not raw.strip().startswith('[') and '[' in raw:
            start = raw.find('[')
            end = raw.rfind(']')
            if start != -1 and end != -1 and end > start:
                raw = raw[start:end + 1]
                logger.debug(f"  Extracted JSON array from text (chars {start}-{end})")

        # Fourth try: find JSON object in text
        elif not raw.strip().startswith('{') and '{' in raw:
            start = raw.find('{')
            end = raw.rfind('}')
            if start != -1 and end != -1 and end > start:
                raw = raw[start:end + 1]
                logger.debug(f"  Extracted JSON object from text (chars {start}-{end})")

        return json.loads(raw)

    def extract_drawing_tree(self, directory: Path, dt_path: Optional[Path] = None) -> Dict[str, str]:
        """Extract parent-child hierarchy from Drawing Tree PDF.

        Args:
            directory: Folder to search for DT PDF
            dt_path: Optional explicit path to DT PDF (overrides auto-detection)

        Returns:
            Dict mapping child drawing -> parent drawing
        """
        if dt_path and dt_path.exists():
            tree_path = dt_path
        else:
            candidates = list(directory.glob("*drawing*tree*.pdf")) + list(directory.glob("*DT*.pdf"))
            if not candidates:
                logger.info("No drawing tree PDF found - NHA will use title block fallback")
                return {}
            tree_path = candidates[0]

        logger.info(f"Extracting hierarchy from: {tree_path.name}")
        b64_images = self.pdf_to_base64_images(tree_path)

        prompt = """You are looking at an Engineering Drawing Tree diagram.
Extract the parent-child hierarchy of all drawing numbers shown.

Return ONLY a valid JSON object where:
- Keys are CHILD drawing numbers
- Values are PARENT (next higher assembly) drawing numbers
- Do NOT include self-references (a drawing cannot be its own parent)
- Do NOT include DT (Drawing Tree) as a parent - use the actual top assembly

Example format:
{
  "MER07558-001": "MER07543-001",
  "MER07543-001": "MER07540-001",
  "MER07545-001": "MER07540-001"
}

Return ONLY the JSON object, no other text."""

        try:
            raw = self.call_haiku_vision(b64_images, prompt)
            hierarchy = self.parse_json_response(raw)

            # Clean up: remove self-references and DT references
            clean_hierarchy = {}
            for child, parent in hierarchy.items():
                if child == parent:  # Skip self-references
                    continue
                if "-DT" in parent.upper() or "TREE" in parent.upper():  # Skip DT as parent
                    continue
                clean_hierarchy[child] = parent

            logger.info(f"Drawing tree: {len(clean_hierarchy)} valid parent links found")
            return clean_hierarchy
        except Exception as e:
            logger.warning(f"Drawing tree parse failed: {e}")
            return {}

    def extract_drawing_info(self, b64_images: List[str]) -> Dict[str, str]:
        """Extract drawing metadata from title block."""
        prompt = """Look at this engineering drawing and extract info from the title block AND notes.

Return ONLY this JSON (no extra text):
{
  "drawing_number": "The drawing number from title block",
  "title": "The drawing title/name (e.g., TOP PLATE, BRACKET ASSY, VALVE BODY)",
  "drawing_type": "DETAIL or ASSEMBLY (ASSEMBLY if it has an ENGINEERING PARTS LIST table)",
  "next_assembly": "The next higher assembly if shown (USED ON field), else empty string",
  "cage_code": "5-digit CAGE code from title block (e.g., 1EYB0, 1CRL0), or company name if shown",
  "material_designation": "FULL material name with alloy/temper (e.g., 6061-T6 ALUMINUM, 7075-T73 ALUMINUM, A286 CRES, INCONEL 718). Include alloy number and temper!",
  "material_spec": "Spec number only (e.g., SAE AMS 5737, MIL-S-5000, ASTM A564)",
  "uns_number": "UNS number if shown (e.g., UNS S66286, UNS N07718)",
  "process_spec": "Process spec from notes if any (e.g., passivation per SAE-AMS-QQ-P-35)"
}
IMPORTANT:
- Check the NOTES section for material/process specs that may not be in title block.
- For material_designation, include the SPECIFIC alloy and temper (6061-T6, not just ALUMINUM)
- CAGE code is usually a 5-character alphanumeric code in the title block"""

        try:
            raw = self.call_haiku_vision(b64_images[:1], prompt, max_tokens=500)
            return self.parse_json_response(raw)
        except Exception as e:
            logger.warning(f"Drawing info extraction failed: {e}")
            return {"drawing_number": "", "title": "", "drawing_type": "", "next_assembly": "", "title_block_material": ""}

    def extract_parts_list(self, b64_images: List[str], drawing_type: str, extracted_text: str = "") -> List[Dict]:
        """Extract parts list from drawing.

        Args:
            b64_images: Base64-encoded page images
            drawing_type: "DETAIL" or "ASSEMBLY"
            extracted_text: Raw text extracted from PDF (used to anchor/validate results)

        Returns:
            List of part dictionaries
        """
        is_detail = drawing_type.upper() != "ASSEMBLY"

        # Detect scanned PDFs (sparse text extraction)
        MIN_TEXT_FOR_ANCHORING = 500
        is_scanned_pdf = len(extracted_text) < MIN_TEXT_FOR_ANCHORING if extracted_text else True

        # Truncate extracted text if too long (keep first 8000 chars for context)
        # Only use text context if we have enough text (not a scanned PDF)
        text_context = extracted_text[:8000] if extracted_text and not is_scanned_pdf else ""

        if is_detail:
            prompt = """Look at this DETAIL engineering drawing.
Extract the single main part. Check BOTH the title block AND the NOTES section.

Return ONLY a JSON array with ONE object:
[{
  "find_no": "-",
  "part_number": "drawing number from title block",
  "description": "part title/description from title block",
  "qty": "1",
  "designation": "FULL material name with alloy/temper (e.g., 6061-T6 ALUMINUM, 7075-T73 ALUMINUM, A286 CRES, INCONEL 718)",
  "spec": "material spec number (e.g., SAE AMS 5737, MIL-S-5000, ASTM A564)",
  "uns": "UNS number if shown (e.g., S66286, N07718)",
  "form": "material form (e.g., SHEET, BAR, FORGING)",
  "process": "process spec from notes (e.g., passivation per SAE-AMS-QQ-P-35)"
}]
IMPORTANT:
- Material specs like AMS, MIL, ASTM numbers are often in NOTES section, not title block.
- Include SPECIFIC alloy and temper (6061-T6, not just ALUMINUM)
Use empty string "" for missing fields. Return ONLY the JSON array."""
        else:
            # For scanned PDFs, use pure vision mode without text anchoring
            if is_scanned_pdf:
                prompt = """You are a STRICT forensic engineering drawing parser extracting the ENGINEERING PARTS LIST (EPL).
Look CAREFULLY at the image and extract ONLY what is visible in the EPL table.

CRITICAL ANTI-HALLUCINATION RULES:
1. Extract ONLY part numbers that are CLEARLY VISIBLE in the EPL table.
2. If you cannot read a part number clearly, SKIP IT. Do not guess.
3. SKIP rows where part_number would be "ITEM NOT SHOWN", "NOT SHOWN", "-", or blank.
4. DO NOT invent fasteners - MS20002, MS35206, MS35338 series are commonly hallucinated.
5. Copy part numbers EXACTLY as shown - character for character.
6. If unsure about a digit or letter, SKIP that part entirely.

SPEC/UNS RULES - CRITICAL:
- spec and uns fields are ONLY for parts that have their OWN spec in the EPL MATERIAL column.
- DO NOT copy title block spec (like ASTM B209) to EPL line items.
- Child drawing references should have spec="" and uns="" (they have their own drawings).
- Only fill spec/uns if the EPL row itself shows a spec number.

DESIGNATION RULES:
- designation = ONLY from EPL MATERIAL column text for that specific row.
- Child drawing numbers should have designation="" (material comes from their own drawing).
- Standard hardware (NAS, MS, AN) gets designation from EPL if shown, else "".

Return ONLY a JSON array of actual parts (skip NOT SHOWN items):
[{
  "find_no": "from EPL",
  "part_number": "EXACT as shown - copy character for character!",
  "description": "nomenclature from EPL",
  "qty": "quantity",
  "designation": "EPL material column ONLY (else empty)",
  "spec": "ONLY if EPL row has its own spec (else empty)",
  "uns": "ONLY if EPL row shows UNS (else empty)",
  "form": "form if shown",
  "process": ""
}, ...]

Return ONLY the JSON array. SKIP any "ITEM NOT SHOWN" rows entirely."""
            else:
                # HYBRID APPROACH: Include extracted text to anchor Haiku to real content
                prompt = f"""You are a STRICT forensic engineering drawing parser extracting the ENGINEERING PARTS LIST (EPL).

=== EXTRACTED TEXT FROM THIS DRAWING (GROUND TRUTH) ===
{text_context}
=== END EXTRACTED TEXT ===

CRITICAL ANTI-HALLUCINATION RULES:
1. You may ONLY return part numbers that appear in the EXTRACTED TEXT above.
2. If a part number is NOT in the extracted text, DO NOT include it.
3. SKIP rows where part_number would be "ITEM NOT SHOWN", "NOT SHOWN", "-", or blank.
4. DO NOT invent fasteners - MS20002, MS35206, MS35338 series are commonly hallucinated.
5. TRANSCRIBE EXACTLY from the image - match what's in the extracted text.

SPEC/UNS RULES - CRITICAL:
- spec and uns fields are ONLY for parts that have their OWN spec in the EPL MATERIAL column.
- DO NOT copy title block spec (like ASTM B209) to EPL line items.
- Child drawing references (GPE-051-1, GPE-A050-1) should have spec="" and uns="" (they have their own drawings).
- Only fill spec/uns if the EPL row itself shows a spec number.

DESIGNATION RULES:
- designation = ONLY from EPL MATERIAL column text for that specific row.
- Child drawing numbers should have designation="" (material comes from their own drawing).
- Standard hardware (NAS, MS, AN) gets designation from EPL if shown, else "".

Return ONLY a JSON array of actual parts (skip NOT SHOWN items):
[{{
  "find_no": "from EPL",
  "part_number": "EXACT as written - must exist in extracted text!",
  "description": "nomenclature from EPL",
  "qty": "quantity",
  "designation": "EPL material column ONLY (else empty)",
  "spec": "ONLY if EPL row has its own spec (else empty)",
  "uns": "ONLY if EPL row shows UNS (else empty)",
  "form": "form if shown",
  "process": ""
}}, ...]

Return ONLY the JSON array. SKIP any "ITEM NOT SHOWN" rows entirely."""

        try:
            raw = self.call_haiku_vision(b64_images, prompt)

            # Log raw response for debugging if it looks suspicious
            if not raw or not raw.strip().startswith('['):
                logger.warning(f"  Raw response (first 200 chars): {raw[:200] if raw else 'EMPTY'}")

            parts = self.parse_json_response(raw)

            # Post-extraction validation: filter out parts not in extracted text
            # BUT skip validation if text extraction was too sparse (likely a scanned PDF)
            # Scanned PDFs typically have <500 chars of extractable text
            MIN_TEXT_FOR_VALIDATION = 500

            if extracted_text and len(extracted_text) >= MIN_TEXT_FOR_VALIDATION and not is_detail:
                validated_parts = []
                text_lower = extracted_text.lower()
                for part in parts:
                    pn = part.get("part_number", "")
                    # Check if part number appears in extracted text (fuzzy match)
                    pn_clean = pn.replace("-", "").replace(" ", "").lower()
                    # Also check with dashes/spaces normalized
                    if pn.lower() in text_lower or pn_clean in text_lower.replace("-", "").replace(" ", ""):
                        validated_parts.append(part)
                    else:
                        logger.warning(f"  FILTERED: {pn} not found in extracted text")
                return validated_parts
            elif extracted_text and len(extracted_text) < MIN_TEXT_FOR_VALIDATION and not is_detail:
                logger.info(f"  SCANNED PDF detected ({len(extracted_text)} chars) - using pure vision mode (no text validation)")
                return parts  # Trust vision for scanned PDFs

            return parts
        except Exception as e:
            logger.warning(f"Parts extraction failed: {e}")
            return []

    def extract_to_json(self, directory: Path, output_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        STEP 1: Extract all drawings to JSON.

        This is the expensive step - calls Haiku for each PDF.
        Results are cached to JSON for re-use.

        Args:
            directory: Folder containing PDF drawings
            output_path: Where to save JSON (default: directory/extraction_results.json)

        Returns:
            Dict with 'parts', 'drawings', 'hierarchy', 'metadata'
        """
        hierarchy = self.extract_drawing_tree(directory)

        all_parts: List[Dict] = []
        all_drawings: List[Dict] = []

        pdf_files = sorted(directory.glob("*.pdf"))
        pdf_files = [p for p in pdf_files if not ("drawing tree" in p.name.lower() or "-DT" in p.name.upper())]

        logger.info(f"\nProcessing {len(pdf_files)} drawings with Haiku vision...")

        for i, pdf_path in enumerate(pdf_files, 1):
            logger.info(f"\n[{i}/{len(pdf_files)}] {pdf_path.name}")

            try:
                # HYBRID APPROACH: Extract text first for anchoring
                extracted_text = self.extract_text_from_pdf(pdf_path)
                if extracted_text:
                    logger.info(f"  Extracted {len(extracted_text)} chars of text")

                b64_images = self.pdf_to_base64_images(pdf_path)
                logger.info(f"  Pages: {len(b64_images)}")

                # Extract drawing info
                info = self.extract_drawing_info(b64_images)
                info["source_file"] = pdf_path.name
                all_drawings.append(info)
                logger.info(f"  Drawing: {info.get('drawing_number', 'UNKNOWN')} ({info.get('drawing_type', '?')})")

                # Extract parts with text anchoring
                parts = self.extract_parts_list(b64_images, info.get("drawing_type", "DETAIL"), extracted_text)
                logger.info(f"  Parts: {len(parts)}")

                for p in parts:
                    p["source_file"] = pdf_path.name
                    p["source_drawing"] = info.get("drawing_number", "")
                    p["drawing_title"] = info.get("title", "")  # Actual drawing title
                    p["cage_code"] = info.get("cage_code", "")  # CAGE code / company
                    # Propagate drawing-level material info to parts
                    p["title_block_material"] = info.get("material_designation", "")
                    # If part has no spec but drawing does, use drawing's spec
                    if not p.get("spec") and info.get("material_spec"):
                        p["spec"] = info.get("material_spec", "")
                    if not p.get("uns") and info.get("uns_number"):
                        p["uns"] = info.get("uns_number", "")
                    if not p.get("process") and info.get("process_spec"):
                        p["process"] = info.get("process_spec", "")
                    if info.get("next_assembly"):
                        p["fallback_nha"] = info["next_assembly"]

                # Add assembly itself if it has material
                if info.get("drawing_type", "").upper() == "ASSEMBLY" and info.get("material_designation"):
                    all_parts.append({
                        "find_no": "-",
                        "part_number": info["drawing_number"],
                        "description": info.get("title", ""),
                        "qty": "1",
                        "designation": info.get("material_designation", ""),
                        "spec": info.get("material_spec", ""),
                        "uns": info.get("uns_number", ""),
                        "form": "",
                        "process": info.get("process_spec", ""),
                        "source_file": pdf_path.name,
                        "source_drawing": info["drawing_number"],
                        "title_block_material": info.get("material_designation", ""),
                        "drawing_title": info.get("title", ""),
                        "cage_code": info.get("cage_code", ""),
                    })

                all_parts.extend(parts)

            except Exception as e:
                logger.error(f"  ERROR: {e}")

        result = {
            "parts": all_parts,
            "drawings": all_drawings,
            "hierarchy": hierarchy,
            "metadata": {
                "extracted_at": datetime.now().isoformat(),
                "source_directory": str(directory),
                "pdf_count": len(pdf_files),
                "parts_count": len(all_parts),
                "model": self.model,
            }
        }

        # Save to JSON
        if output_path is None:
            output_path = directory / "extraction_results.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        logger.info(f"\n=== EXTRACTION COMPLETE ===")
        logger.info(f"Drawings: {len(all_drawings)}")
        logger.info(f"Parts: {len(all_parts)}")
        logger.info(f"Saved to: {output_path}")

        return result


# =============================================================================
# STEP 2: JSON TO MIUL (Cheap - can tweak and re-run)
# =============================================================================

class MIULAssembler:
    """Assemble MIUL Excel from extracted JSON data."""

    @staticmethod
    def load_json(json_path: Path) -> Dict[str, Any]:
        """Load extraction results from JSON."""
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _is_drawing_reference(part_number: str, project_prefix: str = "") -> bool:
        """Check if a part number is a reference to another drawing (not hardware).

        Drawing numbers typically match patterns like:
        - GPE-051-1, GPE-A050-1, MER07564-001
        - Project prefix + numbers

        Hardware/consumables typically:
        - Start with NAS, MS, AN, PP-, SHC-, FH, HHS
        - Or are catalog numbers like 9246K13
        """
        pn = str(part_number).upper().strip()
        if not pn:
            return False

        # These are definitely NOT drawing references (hardware/consumables)
        hardware_prefixes = ('NAS', 'MS', 'AN', 'PP-', 'SHC-', 'SHC', 'SHCS', 'FH', 'FHS', 'HHS', 'BHS', 'BHCS')
        if any(pn.startswith(p) for p in hardware_prefixes):
            return False

        # Catalog/vendor numbers (digits with optional letter suffix)
        if re.match(r'^\d+[A-Z]?\d*$', pn):
            return False

        # If it matches drawing number pattern (letters + numbers + dash + numbers)
        # e.g., GPE-051-1, MER07564-001, GPE-A050-1
        if re.match(r'^[A-Z]{2,6}[-]?[A-Z]?\d{2,5}[-]?\d{0,3}$', pn):
            return True

        # If project prefix provided, check if it matches
        if project_prefix and pn.startswith(project_prefix.upper()):
            return True

        return False

    @staticmethod
    def _infer_fastener_material(row: Dict) -> str:
        """Infer material for common fasteners from part number or description.

        Per NASA-STD-6016C, all materials must be identified even for standard parts.
        """
        pn = str(row.get('part_number', '')).upper()
        desc = str(row.get('description', '')).upper()
        combined = f"{pn} {desc}"

        # =================================================================
        # HELICOILS / INSERTS - very common in aerospace
        # =================================================================
        if 'HELICOIL' in combined or 'HELI-COIL' in combined:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            if 'INCONEL' in combined or '718' in combined:
                return 'INCONEL 718'
            if 'A286' in combined:
                return 'A286 CRES'
            return 'CORROSION RESISTANT STEEL'  # Default helicoils

        if 'INSERT' in combined:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            if 'BRASS' in combined:
                return 'BRASS'
            if 'ALUMINUM' in combined:
                return 'ALUMINUM ALLOY'
            return 'CORROSION RESISTANT STEEL'  # Default inserts

        # NAS fasteners - common material codes
        # NAS1351 = A286 CRES, NAS1352 = A286 CRES
        if 'NAS135' in pn:
            return 'A286 CRES'
        if 'NAS1149' in pn or 'NAS1153' in pn:
            return 'CORROSION RESISTANT STEEL'

        # MS (Military Standard) fasteners
        if pn.startswith('MS') or 'MS ' in pn:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            if 'A286' in combined:
                return 'A286 CRES'
            return 'ALLOY STEEL'  # Default MS fasteners

        # AN (Air Force-Navy) fasteners
        if pn.startswith('AN') or 'AN ' in pn:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        # Captive screws
        if 'CAPTIVE' in combined and 'SCREW' in combined:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        # Shoulder screws
        if 'SHOULDER' in combined and 'SCREW' in combined:
            if '18-8' in combined:
                return '18-8 STAINLESS STEEL'
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        # 18-8 Stainless
        if '18-8' in combined or '188' in pn:
            return '18-8 STAINLESS STEEL'

        # Common material keywords in description
        if 'ALUMINUM' in desc or 'AL ' in desc:
            return 'ALUMINUM ALLOY'
        if 'CRES' in desc or 'STAINLESS' in desc:
            return 'CORROSION RESISTANT STEEL'
        if 'INCONEL' in desc:
            return 'INCONEL'
        if 'TITANIUM' in desc or 'TI ' in desc:
            return 'TITANIUM ALLOY'
        if 'STEEL' in desc:
            return 'ALLOY STEEL'

        # Thread-lock compound
        if 'LOCTITE' in combined or ('THREAD' in combined and 'LOCK' in combined):
            return 'ANAEROBIC ADHESIVE'

        # Kapton tape
        if 'KAPTON' in combined:
            return 'POLYIMIDE FILM'

        # Socket head cap screws (SHC, SHCS)
        if pn.startswith('SHC') or 'SHCS' in combined or 'SOCKET HEAD' in desc:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        # Flat head screws (FH, FHS)
        if pn.startswith('FH') or 'FLAT HEAD' in desc:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        # Hex head screws (HHS)
        if pn.startswith('HHS') or 'HEX HEAD' in desc:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        # Button head screws (BHS, BHCS)
        if pn.startswith('BH') or 'BUTTON HEAD' in desc:
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        # Generic screws/bolts/nuts
        if any(x in desc for x in ['SCREW', 'BOLT', 'NUT', 'WASHER']):
            if 'CRES' in combined or 'STAINLESS' in combined:
                return 'CORROSION RESISTANT STEEL'
            return 'ALLOY STEEL'

        return ''

    @staticmethod
    def build_fuzzy_map(hierarchy: Dict[str, str]) -> Dict[str, str]:
        """Build fuzzy lookup map for NHA resolution."""
        clean_map = {}
        for child, parent in hierarchy.items():
            # Standard: "GPE-101-1" -> "GPE1011"
            clean_key = re.sub(r'[\s\-]', '', child).upper()
            clean_map[clean_key] = parent
            # Also store base without revision suffix
            base_key = re.sub(r"-[A-Z0-9]+$", "", child).replace("-", "").upper()
            if base_key not in clean_map:
                clean_map[base_key] = parent
        return clean_map

    @staticmethod
    def resolve_nha(part_number: str, hierarchy: Dict[str, str], clean_map: Dict[str, str], fallback: str = "") -> str:
        """Resolve Next Higher Assembly using 4-strategy matching."""
        d = str(part_number).strip()
        if not d:
            return ""

        # Strategy 1: Exact match
        if d in hierarchy:
            return hierarchy[d]

        # Strategy 2: Fuzzy match (strip spaces/dashes)
        clean_part = re.sub(r'[\s\-]', '', d).upper()
        if clean_part in clean_map:
            return clean_map[clean_part]

        # Strategy 3: Strip revision suffix
        base_part = re.sub(r"-[A-Z0-9]+$", "", d)
        clean_base = re.sub(r'[\s\-]', '', base_part).upper()
        if clean_base in clean_map:
            return clean_map[clean_base]

        # Strategy 4: Title block fallback
        if fallback and str(fallback).upper() not in ["", "N/A", "NONE", "NAN"]:
            return fallback

        return ""

    @classmethod
    def json_to_miul(
        cls,
        json_path: Path,
        output_path: Optional[Path] = None,
        default_nha: str = "",
        project_name: str = "PROJECT",
    ) -> Path:
        """
        STEP 2: Convert extraction JSON to MIUL Excel.

        Args:
            json_path: Path to extraction_results.json
            output_path: Where to save Excel (default: same folder as JSON)
            default_nha: Default NHA if resolution fails
            project_name: Project name for Document Title column

        Returns:
            Path to output Excel file
        """
        data = cls.load_json(json_path)
        parts = data.get("parts", [])
        drawings = data.get("drawings", [])
        hierarchy = data.get("hierarchy", {})

        if not parts:
            logger.warning("No parts in JSON - nothing to build")
            return None

        # Build drawing lookup for backfilling specs
        drawing_map = {d.get("drawing_number", ""): d for d in drawings}

        # Backfill specs from drawing-level data to parts
        # Only for DETAIL drawings where the part IS the drawing
        # Assembly parts list items have their own materials
        for p in parts:
            source_dwg = p.get("source_drawing", "")
            if source_dwg and source_dwg in drawing_map:
                dwg_info = drawing_map[source_dwg]
                dwg_type = dwg_info.get("drawing_type", "").upper()

                # Only backfill from DETAIL drawings (not assembly parts lists)
                if dwg_type == "DETAIL":
                    if not p.get("spec") and dwg_info.get("material_spec"):
                        p["spec"] = dwg_info["material_spec"]
                    if not p.get("uns") and dwg_info.get("uns_number"):
                        p["uns"] = dwg_info["uns_number"]
                    if not p.get("process") and dwg_info.get("process_spec"):
                        p["process"] = dwg_info["process_spec"]
                    if not p.get("title_block_material") and dwg_info.get("material_designation"):
                        p["title_block_material"] = dwg_info["material_designation"]

        df = pd.DataFrame(parts)

        # Build drawing lookup for type checking
        drawing_map = {d.get("drawing_number", ""): d for d in drawings}

        # =========================================================================
        # DESIGNATION: Smart handling for DETAIL vs ASSEMBLY drawings
        # - DETAIL drawings: use title_block_material (it IS the part)
        # - ASSEMBLY parts:
        #   - Drawing references (GPE-051-1): DON'T inherit assembly material
        #   - Actual hardware (screws, etc.): use EPL designation or infer
        # =========================================================================
        def get_designation(row):
            source_dwg = row.get('source_drawing', '')
            dwg_info = drawing_map.get(source_dwg, {})
            dwg_type = dwg_info.get('drawing_type', '').upper()
            part_number = str(row.get('part_number', '')).strip()

            # For DETAIL drawings, the title_block_material IS the material
            if dwg_type == 'DETAIL' and row.get('title_block_material'):
                return str(row['title_block_material']).strip().upper()

            # For ASSEMBLY parts, check if this is a drawing reference
            if dwg_type == 'ASSEMBLY':
                # Check if this part_number is itself a drawing (not hardware)
                if cls._is_drawing_reference(part_number, project_name):
                    # This is a child drawing - check if we have its own detail drawing
                    child_dwg = drawing_map.get(part_number, {})
                    if child_dwg.get('material_designation'):
                        return str(child_dwg['material_designation']).strip().upper()
                    # No detail drawing found - leave empty (it has its own drawing)
                    # But first check if EPL had a designation for it
                    designation = str(row.get('designation', '')).strip().upper()
                    if designation and designation not in ('', 'AR', 'N/A', 'NONE', 'ALUMINUM ALLOY'):
                        return designation
                    return ''  # Will get material from its own detail drawing

            # For assembly parts that ARE hardware, use their EPL designation
            designation = str(row.get('designation', '')).strip().upper()
            if designation and designation not in ('', 'AR', 'N/A', 'NONE'):
                return designation

            # Infer material for common fasteners/hardware
            inferred = cls._infer_fastener_material(row)
            if inferred:
                return inferred

            # Last fallback - but NOT for drawing references
            if not cls._is_drawing_reference(part_number, project_name):
                if row.get('title_block_material'):
                    return str(row['title_block_material']).strip().upper()

            return ''

        df['Designation'] = df.apply(get_designation, axis=1)

        # Normalize other columns
        df['Detail Drawing'] = df['part_number'].astype(str).str.strip()
        df['Material Specification'] = df.get('spec', pd.Series(dtype=str)).fillna('').astype(str)
        df['Material Form'] = df.get('form', pd.Series(dtype=str)).fillna('').astype(str).str.upper()
        df['Process Specification'] = df.get('process', pd.Series(dtype=str)).fillna('').astype(str)
        df['Quantity'] = df['qty']

        # =========================================================================
        # DRAWING SOURCE: Use CAGE code or company name from title block
        # =========================================================================
        def is_valid_cage_code(s: str) -> bool:
            """Check if string looks like a valid CAGE code (not a material)."""
            if not s or len(s) < 3:
                return False
            s = s.upper().strip()
            # CAGE codes are 5 alphanumeric chars, don't contain material keywords
            material_indicators = ('ALUMINUM', 'STEEL', 'CRES', 'INCONEL', 'TITANIUM',
                                   'ALLOY', '6061', '7075', '2024', '316', '304', '18-8',
                                   'A286', 'COPPER', 'BRASS', 'NICKEL', 'SILICONE',
                                   'POLYIMIDE', 'KAPTON', 'TEFLON')
            if any(ind in s for ind in material_indicators):
                return False
            # Materials often have T6, T73, etc. temper designations
            if '-T' in s or '-H' in s:
                return False
            # Valid CAGE codes are alphanumeric, 5 chars
            if len(s) == 5 and s.isalnum():
                return True
            # Also allow longer company names
            if len(s) > 5 and not any(c.isdigit() for c in s[:3]):
                return True
            return False

        def get_source(row):
            # Prefer CAGE code extracted from title block (if valid)
            cage = str(row.get('cage_code', '')).strip()
            if cage and is_valid_cage_code(cage):
                return cage

            # Fallback: Check if it's a standard part
            pn = str(row.get('part_number', ''))
            if pn:
                pn_upper = pn.upper()
                if pn_upper.startswith(('NAS', 'MS', 'AN')):
                    return f"STD_{pn.split('-')[0].split()[0]}"
                if 'INSERT' in pn_upper:
                    return "STD_INSERT"

            # Last resort: derive from file name
            return Path(str(row.get('source_file', 'UNKNOWN'))).stem

        df['Drawing Source'] = df.apply(get_source, axis=1)

        # Build fuzzy map for NHA resolution
        clean_map = cls.build_fuzzy_map(hierarchy)
        logger.info(f"Resolving NHA for {len(df)} parts using {len(clean_map)} tree links...")

        # Resolve NHA for each row
        df['Next Assembly'] = df.apply(
            lambda row: cls.resolve_nha(
                row['Detail Drawing'],
                hierarchy,
                clean_map,
                row.get('fallback_nha', '')
            ) or default_nha,
            axis=1
        )

        # =========================================================================
        # DOCUMENT TITLE: Use actual drawing title, not generic project name
        # =========================================================================
        def get_document_title(row):
            # First try drawing_title (actual title from title block)
            title = str(row.get('drawing_title', '')).strip()
            if title and title not in ('', 'CONFIGURATION SHOWN THIS SHEET'):
                return title

            # Fall back to description
            desc = str(row.get('description', '')).strip()
            if desc and desc not in ('', 'CONFIGURATION SHOWN THIS SHEET'):
                return desc

            # Last resort: project name
            return f"{project_name} PART"

        df['Document Title'] = df.apply(get_document_title, axis=1)

        # Material Code lookup (optional)
        if MATERIAL_LOOKUP_AVAILABLE:
            try:
                svc = get_lookup_service()
                def get_material_code(designation: str) -> str:
                    if not designation:
                        return ""
                    matches = svc.lookup_by_designation(designation)
                    if matches:
                        # Return highest confidence match
                        best = max(matches, key=lambda m: m.score)
                        return best.material_code
                    return ""
                df['Material Code'] = df['Designation'].apply(get_material_code)
                svc.close()
            except Exception as e:
                logger.warning(f"Material code lookup failed: {e}")
                df['Material Code'] = ""
        else:
            df['Material Code'] = ""

        # NASA-STD-6016C column structure
        columns = [
            'Index', 'Parent', 'Detail Drawing', 'Next Assembly', 'Change Letter',
            'Drawing Source', 'Material Form', 'Material Manufacturer',
            'Designation', 'Material Specification', 'Process Specification',
            'Environment', 'Material Code', 'Standard Part Number',
            'Contractor', 'System', 'Subsystem', 'Max Temperature', 'Min Temperature',
            'Fluid Type', 'Associate Contractor', 'Project', 'Document Title',
            'Criticality', 'Line Number', 'Overall Evaluation', 'Configuration Test',
            'Max Pressure', 'Min Pressure', 'MUA Rationale', 'Cure Codes',
            'FLAM', 'SCC', 'CORR', 'TVS', 'TOX', 'FS', 'Remarks'
        ]
        for c in columns:
            if c not in df.columns:
                df[c] = ''

        df = df.reindex(columns=columns)

        # =========================================================================
        # INDEX/PARENT: Build proper tree structure from NHA hierarchy
        # Per NASA-STD-6016C, Parent is the Index of the parent assembly row
        # =========================================================================
        # First assign Index values (1, 2, 3, ...)
        df['Index'] = range(1, len(df) + 1)

        # Build a map of drawing number -> Index for parent lookups
        drawing_to_index = {}
        for idx, row in df.iterrows():
            drawing_num = str(row.get('Detail Drawing', '')).strip()
            if drawing_num:
                drawing_to_index[drawing_num] = row['Index']
                # Also store without revision suffix for fuzzy matching
                base_num = re.sub(r'-\d+$', '', drawing_num)
                if base_num not in drawing_to_index:
                    drawing_to_index[base_num] = row['Index']

        # Now assign Parent based on Next Assembly
        def get_parent_index(row):
            nha = str(row.get('Next Assembly', '')).strip()
            if not nha:
                return ''  # No parent = root level

            # Try exact match first
            if nha in drawing_to_index:
                return drawing_to_index[nha]

            # Try without revision suffix
            base_nha = re.sub(r'-\d+$', '', nha)
            if base_nha in drawing_to_index:
                return drawing_to_index[base_nha]

            # Try fuzzy match (remove dashes)
            clean_nha = re.sub(r'[\s\-]', '', nha).upper()
            for dwg, idx in drawing_to_index.items():
                clean_dwg = re.sub(r'[\s\-]', '', dwg).upper()
                if clean_dwg == clean_nha:
                    return idx

            return ''  # Parent not found in this MIUL

        df['Parent'] = df.apply(get_parent_index, axis=1)

        # Add -1 terminator row per NASA-STD-6016C F5.0
        terminator = pd.DataFrame([{c: '' for c in columns}])
        terminator['Index'] = -1
        df = pd.concat([df, terminator], ignore_index=True)

        # Output path
        if output_path is None:
            output_path = json_path.parent / "MIUL_output.xlsx"

        df.to_excel(output_path, index=False)

        # Stats
        nha_resolved = len(df[df['Next Assembly'].ne('')])
        with_material = df['Designation'].ne('').sum()

        logger.info(f"\n=== MIUL GENERATED ===")
        logger.info(f"Rows: {len(df)}")
        logger.info(f"With material: {with_material}")
        logger.info(f"NHA resolved: {nha_resolved}")
        logger.info(f"Saved to: {output_path}")

        return output_path


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Haiku BOM Extractor - 2-Step Process")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Step 1: Extract
    extract_parser = subparsers.add_parser("extract", help="Step 1: Extract PDFs to JSON using Haiku vision")
    extract_parser.add_argument("directory", help="Folder containing PDF drawings")
    extract_parser.add_argument("--output", "-o", help="Output JSON path")
    extract_parser.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY)")

    # Step 2: Assemble
    assemble_parser = subparsers.add_parser("assemble", help="Step 2: Convert JSON to MIUL Excel")
    assemble_parser.add_argument("json_file", help="Path to extraction_results.json")
    assemble_parser.add_argument("--output", "-o", help="Output Excel path")
    assemble_parser.add_argument("--default-nha", default="", help="Default NHA if resolution fails")
    assemble_parser.add_argument("--project", default="PROJECT", help="Project name")

    # Full pipeline
    full_parser = subparsers.add_parser("full", help="Run both steps: Extract then Assemble")
    full_parser.add_argument("directory", help="Folder containing PDF drawings")
    full_parser.add_argument("--api-key", help="Anthropic API key")
    full_parser.add_argument("--project", default="PROJECT", help="Project name")

    args = parser.parse_args()

    if args.command == "extract":
        extractor = HaikuBOMExtractor(api_key=args.api_key)
        output = Path(args.output) if args.output else None
        extractor.extract_to_json(Path(args.directory), output)

    elif args.command == "assemble":
        output = Path(args.output) if args.output else None
        MIULAssembler.json_to_miul(
            Path(args.json_file),
            output,
            default_nha=args.default_nha,
            project_name=args.project,
        )

    elif args.command == "full":
        # Step 1
        extractor = HaikuBOMExtractor(api_key=args.api_key)
        json_path = Path(args.directory) / "extraction_results.json"
        extractor.extract_to_json(Path(args.directory), json_path)

        # Step 2
        MIULAssembler.json_to_miul(json_path, project_name=args.project)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
