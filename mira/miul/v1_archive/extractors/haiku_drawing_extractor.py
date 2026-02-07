#!/usr/bin/env python3
"""
Module: Haiku Drawing Extractor
Purpose: Bedrock Sonnet 4.5-based multi-pass drawing extraction.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

# Configuration from environment (same as MUA parser)
# Default to direct API (USE_BEDROCK=0) - set ANTHROPIC_API_KEY env var
USE_BEDROCK = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-gov-west-1")

# Model IDs
SONNET_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_MODEL_DIRECT = "claude-sonnet-4-5-20250929"


class HaikuDrawingExtractor:
    """Multi-pass drawing extractor using Claude Sonnet 4.5 vision.

    Supports both AWS Bedrock and direct Anthropic API.

    Extracts:
    1. Title block material (primary)
    2. Embedded hardware (inserts, fasteners) with material inference
    3. Referenced standards

    Falls back to regex extraction (InsertExtractor) for reliable insert detection.
    """

    def __init__(self, use_bedrock: bool = None, bedrock_region: str = None, api_key: str = None):
        """Initialize the extractor with Claude Sonnet 4.5.

        Args:
            use_bedrock: Use AWS Bedrock. If False/None, uses direct Anthropic API.
            bedrock_region: Bedrock region (default: BEDROCK_REGION env var)
            api_key: Anthropic API key (default: ANTHROPIC_API_KEY env var)
        """
        self.use_bedrock = use_bedrock if use_bedrock is not None else USE_BEDROCK
        self.bedrock_region = bedrock_region or BEDROCK_REGION
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        self.model = SONNET_MODEL_BEDROCK if self.use_bedrock else SONNET_MODEL_DIRECT

    @property
    def client(self):
        """Lazy-load Anthropic client (Bedrock or direct API)."""
        if self._client is None:
            if self.use_bedrock:
                try:
                    from anthropic import AnthropicBedrock
                    self._client = AnthropicBedrock(aws_region=self.bedrock_region)
                    LOGGER.info(f"Using Bedrock in {self.bedrock_region}")
                except ImportError:
                    LOGGER.error("anthropic package not installed. Run: pip install anthropic")
                    raise
            else:
                try:
                    from anthropic import Anthropic
                    self._client = Anthropic(api_key=self.api_key)
                    LOGGER.info(f"Using direct Anthropic API with {self.model}")
                except ImportError:
                    LOGGER.error("anthropic package not installed. Run: pip install anthropic")
                    raise
        return self._client

    def is_available(self) -> bool:
        """Check if API client is available."""
        try:
            return self.client is not None
        except Exception:
            return False

    def _is_valid_hardware_standard(self, standard: str) -> bool:
        """Filter out dimension values misidentified as hardware standards.

        The vision API sometimes extracts diameter callouts, radius dimensions,
        and other non-hardware text as "standards". This filters them out.
        """
        if not standard:
            return False

        standard = standard.strip()

        # Reject dimension patterns
        NON_HARDWARE_PATTERNS = [
            r'^Ø',              # Diameter dimensions (Ø.010, Ø.0000)
            r'^R\d',            # Radius dimensions (R3.205)
            r'^\.\d+$',         # Pure decimals (.010, .0100)
            r'±',               # Tolerance values
            r'^AR$',            # "As Required"
            r'^REQD$',          # "Required"
            r'^\d+\.\d+$',      # Pure numbers (3.205)
            r'^\(S\)$',         # Parenthetical (S)
            r'^UNKNOWN$',       # Default fallback
        ]

        for pattern in NON_HARDWARE_PATTERNS:
            if re.search(pattern, standard, re.IGNORECASE):
                LOGGER.debug(f"Filtered non-hardware: {standard}")
                return False

        # Must look like a real hardware standard
        VALID_HARDWARE_PATTERNS = [
            r'^(NAS|MS|AN|NASM|SAE|AMS|ASTM|MIL|HCC)',  # Standard prefixes
            r'^[A-Z]+-\d+',     # Standard-number format
            r'HELICO?IL',       # Helicoil variants
            r'INSERT',          # Insert callouts
        ]

        for pattern in VALID_HARDWARE_PATTERNS:
            if re.search(pattern, standard, re.IGNORECASE):
                return True

        # If it doesn't match known patterns, reject it
        LOGGER.debug(f"Unknown standard format rejected: {standard}")
        return False

    def extract_from_pdf(self, pdf_path: Path) -> "DrawingExtraction":
        """Extract all materials from a multi-page drawing PDF.

        Uses vision API for each page, with regex fallback for text extraction.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Complete extraction result with all materials.
        """
        from mira.miul.extractors.drawing_parser import (
            DrawingExtraction,
            DrawingMaterial,
            EmbeddedHardware,
            MaterialSource,
            DrawingParserPrompts,
            aggregate_hardware_by_standard,
            resolve_hardware_material,
            check_material_compatibility,
        )
        from mira.miul.extractors.insert_extractor import InsertExtractor

        # Extract text for regex fallback
        text = self._extract_text_from_pdf(pdf_path)
        LOGGER.info(f"Extracted {len(text)} chars from {pdf_path.name}")

        # Try vision-based extraction first
        title_data = {}
        all_hardware: List[EmbeddedHardware] = []
        all_standards: List[str] = []

        if self.is_available():
            try:
                images = self._pdf_to_images(pdf_path)
                LOGGER.info(f"Converted {len(images)} pages to images")

                # Pass 1: Title block (page 1)
                prompts = DrawingParserPrompts()
                title_data = self._call_bedrock(images[0], prompts.pass1_title_block())

                # Pass 2: Embedded hardware (all pages)
                for i, img in enumerate(images):
                    hw_data = self._call_bedrock(img, prompts.pass2_embedded_hardware())
                    items = hw_data.get("items", [])
                    valid_count = 0
                    for item in items:
                        standard = item.get("standard", "UNKNOWN")

                        # VALIDATE before adding - filter out dimension garbage
                        if not self._is_valid_hardware_standard(standard):
                            continue

                        try:
                            hw = EmbeddedHardware(
                                standard=standard,
                                thread_size=item.get("thread_size"),
                                quantity=item.get("quantity", 1),
                                raw_callout=item.get("raw_callout", ""),
                            )
                            all_hardware.append(hw)
                            valid_count += 1
                        except Exception as e:
                            LOGGER.warning(f"Failed to parse hardware item: {e}")

                    LOGGER.debug(f"Page {i + 1}: {valid_count}/{len(items)} valid hardware callouts")

                # Pass 3: Standards (all pages)
                for img in images:
                    std_data = self._call_bedrock(img, prompts.pass3_referenced_standards())
                    all_standards.extend(std_data.get("standards", []))

            except Exception as e:
                LOGGER.warning(f"Vision extraction failed, using regex fallback: {e}")

        # Regex fallback for insert extraction
        insert_extractor = InsertExtractor()
        regex_inserts = insert_extractor.extract_inserts(text, pdf_path.name)

        # Convert regex inserts to EmbeddedHardware
        for ins in regex_inserts:
            hw = EmbeddedHardware(
                standard=ins.spec_number,
                thread_size=ins.thread_size,
                quantity=ins.quantity,
                raw_callout=ins.raw_text,
            )
            all_hardware.append(hw)

        # Deduplicate and aggregate
        all_hardware = aggregate_hardware_by_standard(all_hardware)

        # Resolve materials for each hardware item
        for hw in all_hardware:
            resolve_hardware_material(hw)

        # Build primary material from title data or regex
        primary_material = None
        if title_data.get("material_designation"):
            primary_material = DrawingMaterial(
                designation=title_data["material_designation"],
                specification=title_data.get("material_spec"),
                uns_number=title_data.get("uns_number"),
                source=MaterialSource.TITLE_BLOCK,
                raw_text=title_data.get("material_line", ""),
            )
        else:
            # Try regex extraction from text
            primary_material = self._extract_title_block_material(text)

        # Check for material compatibility warnings
        warnings: List[str] = []
        if primary_material and all_hardware:
            warnings = check_material_compatibility(
                primary_material.designation,
                all_hardware,
            )

        # Extract drawing number
        drawing_number = title_data.get("drawing_number")
        if not drawing_number:
            drawing_number = self._extract_drawing_number(pdf_path.name, text)

        return DrawingExtraction(
            drawing_number=drawing_number or "UNKNOWN",
            revision=title_data.get("revision"),
            title=title_data.get("title"),
            primary_material=primary_material,
            subordinate_materials=[],
            embedded_hardware=all_hardware,
            referenced_standards=sorted(set(all_standards)),
            extraction_warnings=warnings,
        )

    def _call_bedrock(self, image_b64: str, prompt: str) -> Dict[str, Any]:
        """Call Bedrock Sonnet 4.5 API with an image and prompt.

        Uses AnthropicBedrock client which has same API as regular Anthropic client.

        Args:
            image_b64: Base64-encoded image.
            prompt: Extraction prompt.

        Returns:
            Parsed JSON response.
        """
        if not self.client:
            return {}

        try:
            # AnthropicBedrock uses same API format as regular Anthropic
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=0,
                messages=[
                    {
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
                    }
                ],
            )

            return self._parse_json_response(response.content[0].text)

        except Exception as e:
            LOGGER.error(f"Bedrock API call failed: {e}")
            return {}

    def _pdf_to_images(self, pdf_path: Path) -> List[str]:
        """Convert PDF pages to base64 images.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            List of base64-encoded PNG images.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF required: pip install PyMuPDF")

        doc = fitz.open(pdf_path)
        images: List[str] = []

        for page in doc:
            # J-size drawings (34x44") need lower DPI to stay under 8000px API limit
            # Start with 72 DPI for large drawings
            pix = page.get_pixmap(dpi=72)

            # If still too large, scale down further
            if max(pix.width, pix.height) > 7500:
                scale = 7500 / max(pix.width, pix.height)
                import fitz as fitz_module
                matrix = fitz_module.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=matrix)

            img_bytes = pix.tobytes("png")
            images.append(base64.b64encode(img_bytes).decode())

        doc.close()
        return images

    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF for regex fallback.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Extracted text.
        """
        try:
            import fitz
        except ImportError:
            raise ImportError("PyMuPDF required: pip install PyMuPDF")

        doc = fitz.open(pdf_path)
        text_parts: List[str] = []

        for page in doc:
            text_parts.append(page.get_text())

        doc.close()
        return "\n".join(text_parts)

    def _extract_title_block_material(self, text: str) -> Optional["DrawingMaterial"]:
        """Extract primary material from text using regex.

        Args:
            text: Drawing text content.

        Returns:
            DrawingMaterial if found, None otherwise.
        """
        from mira.miul.extractors.drawing_parser import (
            DrawingMaterial,
            MaterialSource,
        )

        # Common material patterns in title blocks
        patterns = [
            # "MATERIAL: ALUMINUM ALLOY 7075-T6, UNS A97075, PER SAE AMS4124"
            r"MATERIAL:\s*([A-Z0-9\s\-]+(?:ALLOY)?[A-Z0-9\s\-]+),?\s*(?:UNS\s*([A-Z]\d+))?,?\s*(?:PER\s*)?([A-Z]+\s*\d+)?",
            # "MATERIAL ALUMINUM 6061-T6"
            r"MATERIAL\s+([A-Z]+\s+\d+[A-Z]?\-[A-Z]\d+)",
            # Just material name in notes
            r"(?:MADE FROM|MACHINED FROM)\s+([A-Z0-9\s\-]+(?:ALLOY)?[A-Z0-9\s\-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                designation = match.group(1).strip()
                uns = match.group(2) if len(match.groups()) > 1 else None
                spec = match.group(3) if len(match.groups()) > 2 else None

                return DrawingMaterial(
                    designation=designation,
                    specification=spec,
                    uns_number=uns,
                    source=MaterialSource.TITLE_BLOCK,
                    raw_text=match.group(0),
                )

        return None

    def _extract_drawing_number(self, filename: str, text: str) -> Optional[str]:
        """Extract drawing number from filename or text.

        Args:
            filename: PDF filename.
            text: Drawing text content.

        Returns:
            Drawing number if found.
        """
        # Try filename first (flexible aerospace format)
        # Handles: MER07564-001.pdf, GPE-010-1.pdf, GPE-A000-1.pdf, etc.
        match = re.match(r"([A-Z]{2,6}[-]?[A-Z]?\d{2,5}[-]?\d{0,3})", filename, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # Try text patterns
        patterns = [
            r"DRAWING\s+NUMBER\s*[\n:]\s*([A-Z]+\d+-\d+)",
            r"DWG\s+NO\.?\s*[\n:]\s*([A-Z]+\d+-\d+)",
            # Flexible aerospace format: MER07564-001, GPE-010-1, GPE-A000-1, etc.
            r"([A-Z]{2,6}[-]?[A-Z]?\d{2,5}[-]?\d{0,3})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        return None

    @staticmethod
    def _parse_json_response(text: str) -> Dict[str, Any]:
        """Extract JSON from model response.

        Args:
            text: Model response text.

        Returns:
            Parsed JSON dict.
        """
        text = text.strip()

        # Remove markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # Find JSON object or array
        match = re.search(r"[\[{][\s\S]*[\]}]", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError as e:
                LOGGER.error(f"JSON parse error: {e}")

        return {}


def extract_all_materials_from_drawing(
    pdf_path: Path,
) -> Dict[str, Any]:
    """Convenience function for complete drawing extraction.

    Uses Bedrock Sonnet 4.5 with InsertExtractor regex fallback.

    Args:
        pdf_path: Path to drawing PDF.

    Returns:
        Dictionary with all extracted materials ready for MIUL.
    """
    extractor = HaikuDrawingExtractor()
    result = extractor.extract_from_pdf(pdf_path)

    return {
        "drawing_number": result.drawing_number,
        "revision": result.revision,
        "title": result.title,
        "primary_material": result.primary_material.model_dump() if result.primary_material else None,
        "embedded_hardware": [hw.model_dump() for hw in result.embedded_hardware],
        "all_materials_for_miul": result.all_materials_for_miul(),
        "referenced_standards": result.referenced_standards,
        "warnings": result.extraction_warnings,
    }
