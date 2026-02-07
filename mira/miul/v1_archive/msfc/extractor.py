#!/usr/bin/env python3
"""
Module: Extractor
Purpose: extractor.py

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
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import (
    AssemblyNode,
    DrawingExtraction,
    DrawingMaterial,
    DrawingTreeExtraction,
    DrawingType,
    EmbeddedHardware,
    MaterialSource,
)
from .format import MSFCFormatSpec, detect_msfc_format
from .prompts import MSFCPrompts

__all__ = ["MSFCExtractor", "ExtractionResult"]

__safety_critical__: bool = False

logger = logging.getLogger(__name__)


# =============================================================================
# Text-First Extraction Patterns (No Vision Required)
# =============================================================================

# Helical coil insert callouts
# Matches: "4X .3125-18 UNC-3B HELICAL COIL INSERT THD PER NASM33537"
PATTERN_HELICAL_INSERT = re.compile(
    r"(\d+)\s*[Xx]\s+"                          # Quantity: "4X "
    r"\.?(\d{3,4})-(\d{1,2})\s+"                # Thread: ".3125-18 "
    r"UN[CFE][FS]?-\d[AB]?\s+"                  # Class: "UNC-3B "
    r"(?:HELICAL\s+COIL\s*\n?\s*INSERT|"        # "HELICAL COIL INSERT" or
    r"HELI-?COIL)\s+"                           # "HELICOIL"
    r"(?:THD\s+)?PER\s+"                        # "THD PER "
    r"(NAS[M]?\d{5})",                          # Standard: "NASM33537"
    re.IGNORECASE | re.MULTILINE,
)

# Material callout in title block or notes
# Matches: "MATERIAL: ALUMINUM ALLOY 7075-T6, UNS A97075, PER SAE AMS4124"
PATTERN_MATERIAL_CALLOUT = re.compile(
    r"MATERIAL[:\s]+([A-Z][A-Z0-9\s\-]+)"       # Material name
    r"(?:,?\s*UNS\s+([A-Z]\d{5}))?"             # Optional UNS
    r"(?:,?\s*PER\s+([\w\-]+\d+[\w]*))?"        # Optional spec
    r"(?:,?\s*(SAE|AMS|MIL|ASTM|QQ)\s*[\-]?\s*([\w\-]+))?",  # Alt spec format
    re.IGNORECASE,
)

# Drawing number pattern (MSFC style)
PATTERN_DRAWING_NUMBER = re.compile(
    r"(MER\d{5}-\d{3})",
    re.IGNORECASE,
)

# Weight callout
PATTERN_WEIGHT = re.compile(
    r"(?:CALC\s+)?WEIGHT[:\s]+(\d+\.?\d*)\s*(?:LBS?|POUNDS?)?",
    re.IGNORECASE,
)

# Standard references (for Pass 3)
PATTERN_STANDARDS = re.compile(
    r"((?:SAE\s+)?AMS[\s\-]?\d+[A-Z]?|"         # AMS specs
    r"MIL-[A-Z]-\d+[A-Z]?|"                     # MIL specs
    r"MIL-STD-\d+[A-Z]?|"                       # MIL standards
    r"NASA-STD-\d+[A-Z]?|"                      # NASA standards
    r"ASTM\s+[A-Z]\d+|"                         # ASTM specs
    r"ASME\s+[BY]\d+\.\d+|"                     # ASME standards
    r"NAS[M]?\d{4,5}|"                          # NAS/NASM hardware
    r"MS\d{5}|"                                 # MS hardware
    r"AN\d{3,4}|"                               # AN hardware
    r"QQ-[A-Z]-\d+)",                           # QQ specs
    re.IGNORECASE,
)


def extract_helical_inserts_from_text(text: str, page_num: int = 1) -> list[EmbeddedHardware]:
    """Extract helical coil insert callouts using regex.

    Args:
        text: Text extracted from PDF page.
        page_num: Source page number for traceability.

    Returns:
        List of EmbeddedHardware items found.

    Compliance: SWE-013
    """
    results: list[EmbeddedHardware] = []

    for match in PATTERN_HELICAL_INSERT.finditer(text):
        qty = int(match.group(1))
        thread_major = match.group(2)
        thread_pitch = match.group(3)
        standard = match.group(4).upper()

        # Normalize NAS -> NASM for inserts
        if standard.startswith("NAS") and not standard.startswith("NASM"):
            standard = "NASM" + standard[3:]

        hw = EmbeddedHardware(
            standard=standard,
            thread_size=f".{thread_major}-{thread_pitch}",
            quantity=qty,
            raw_callout=match.group(0).strip(),
        )
        hw.resolve_material()
        results.append(hw)

    return results


def extract_title_block_from_text(text: str) -> dict[str, Any]:
    """Extract title block fields using regex.

    Args:
        text: Full text from PDF (typically first page).

    Returns:
        Dict with extracted fields, empty strings for missing.
    """
    result: dict[str, Any] = {}

    # Drawing number
    dwg_match = PATTERN_DRAWING_NUMBER.search(text)
    if dwg_match:
        result["drawing_number"] = dwg_match.group(1).upper()

    # Material
    mat_match = PATTERN_MATERIAL_CALLOUT.search(text)
    if mat_match:
        result["material_designation"] = mat_match.group(1).strip()
        result["uns_number"] = mat_match.group(2)
        # Combine spec from either capture group
        spec = mat_match.group(3) or ""
        if mat_match.group(4) and mat_match.group(5):
            spec = f"{mat_match.group(4)} {mat_match.group(5)}"
        result["material_spec"] = spec.strip() if spec else None

    # Weight
    weight_match = PATTERN_WEIGHT.search(text)
    if weight_match:
        result["calc_weight_lbs"] = float(weight_match.group(1))

    return result


def extract_standards_from_text(text: str) -> list[str]:
    """Extract all referenced standards using regex.

    Args:
        text: Full text from PDF.

    Returns:
        Deduplicated list of standard references.
    """
    matches = PATTERN_STANDARDS.findall(text)
    # Normalize and dedupe
    standards = {m.upper().replace("  ", " ") for m in matches}
    return sorted(standards)


class ExtractionResult:
    """Container for extraction results with success/failure tracking."""

    def __init__(
        self,
        success: bool,
        data: Any = None,
        error: str | None = None,
        raw_response: str | None = None,
    ):
        self.success = success
        self.data = data
        self.error = error
        self.raw_response = raw_response


class MSFCExtractor:
    """Multi-pass extractor for MSFC-format engineering drawings.

    Architecture: Text-First, Vision Fallback
    - Pass 1: Title block - regex first, vision if incomplete
    - Pass 2: Embedded hardware - regex first, vision for pages with unmatched keywords
    - Pass 3: Referenced standards - text only (no vision needed)

    Supports AWS Bedrock (GovCloud) or direct Anthropic API.

    Compliance: SWE-013, SWE-033
    Safety Critical: False
    """

    def __init__(self, api_key: str | None = None, use_bedrock: bool = True, model: str | None = None):
        """Initialize extractor.

        Args:
            api_key: Anthropic API key. If None, reads from ANTHROPIC_API_KEY env var.
            use_bedrock: If True (default), use AWS Bedrock. If False, use direct Anthropic API.
            model: Model to use. Defaults to Sonnet 4.5 on Bedrock, Haiku on direct API.
        """
        import os

        # Default to direct API (USE_BEDROCK=0) - set ANTHROPIC_API_KEY env var
        self.use_bedrock = use_bedrock or os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
        self.request_id = str(uuid.uuid4())  # Audit trail

        if self.use_bedrock:
            try:
                from anthropic import AnthropicBedrock
            except ImportError:
                raise ImportError("pip install anthropic[bedrock]")

            region = os.getenv("AWS_REGION", os.getenv("BEDROCK_REGION", "us-gov-west-1"))
            self.client = AnthropicBedrock(aws_region=region)
            # Default to Sonnet 4.5 for better extraction quality
            # Note: GovCloud uses "us-gov" prefix, commercial uses "us" or "anthropic" prefix
            self.model = model or os.getenv("BEDROCK_MODEL", "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0")
            logger.info(f"Using AWS Bedrock in {region} with {self.model}")
        else:
            try:
                from anthropic import Anthropic
            except ImportError:
                raise ImportError("pip install anthropic")

            self.client = Anthropic(api_key=api_key)
            self.model = model or "claude-3-haiku-20240307"
            logger.info(f"Using direct Anthropic API with {self.model}")

        self.prompts = MSFCPrompts()

    def extract_drawing(self, pdf_path: Path) -> DrawingExtraction:
        """Extract all information from an MSFC detail drawing.

        Uses text-first extraction with vision fallback to minimize API calls.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Complete DrawingExtraction object.

        Compliance: SWE-013, SWE-033
        """
        # Extract text from all pages FIRST (no external API call)
        page_texts = self._extract_text_by_page(pdf_path)
        full_text = "\n".join(page_texts)
        logger.info(f"Processing {pdf_path.name}: {len(page_texts)} pages, {len(full_text)} chars text")

        # Detect format from text
        format_spec = detect_msfc_format(full_text)

        if format_spec and format_spec.is_drawing_tree:
            logger.warning(f"{pdf_path.name} appears to be a Drawing Tree, not a detail drawing")

        # =====================================================================
        # Pass 1: Title Block - Text First, Vision Fallback
        # =====================================================================
        title_data = extract_title_block_from_text(full_text)
        text_extraction_sufficient = (
            title_data.get("drawing_number") and
            title_data.get("material_designation")
        )

        if not text_extraction_sufficient:
            logger.info("Title block incomplete from text – falling back to vision")
            title_data = self._vision_fallback_title_block(pdf_path, title_data)

        # =====================================================================
        # Pass 2: Embedded Hardware - Text First, Vision Fallback
        # =====================================================================
        all_hardware: list[EmbeddedHardware] = []
        pages_needing_vision: list[int] = []

        for i, page_text in enumerate(page_texts):
            page_hardware = extract_helical_inserts_from_text(page_text, page_num=i + 1)

            if page_hardware:
                logger.debug(f"Page {i + 1}: {len(page_hardware)} inserts via text")
                all_hardware.extend(page_hardware)
            elif "HELICAL" in page_text.upper() or "INSERT" in page_text.upper():
                # Text mentions inserts but regex didn't catch them
                pages_needing_vision.append(i)
                logger.debug(f"Page {i + 1}: Insert keywords found, queuing for vision")

        # Vision fallback ONLY for pages where text extraction failed
        if pages_needing_vision:
            logger.info(f"Vision fallback for {len(pages_needing_vision)} pages with unparsed inserts")
            vision_hardware = self._vision_fallback_hardware(pdf_path, pages_needing_vision)
            all_hardware.extend(vision_hardware)

        # Aggregate hardware by standard + size
        aggregated_hardware = self._aggregate_hardware(all_hardware)

        # =====================================================================
        # Pass 3: Referenced Standards - Text Only (No Vision Needed)
        # =====================================================================
        all_standards = extract_standards_from_text(full_text)
        logger.debug(f"Found {len(all_standards)} standard references via text")

        # Build primary material
        primary_mat = None
        if title_data.get("material_designation"):
            primary_mat = DrawingMaterial(
                designation=title_data["material_designation"],
                specification=title_data.get("material_spec"),
                uns_number=title_data.get("uns_number"),
                source=MaterialSource.TITLE_BLOCK,
                raw_text=title_data.get("material_line", ""),
            )

        # Build warnings
        warnings: list[str] = []
        if primary_mat and aggregated_hardware:
            primary_upper = primary_mat.designation.upper()
            for hw in aggregated_hardware:
                if hw.inferred_material:
                    hw_upper = hw.inferred_material.upper()
                    # Detect aluminum parent with steel inserts
                    if ("ALUMINUM" in primary_upper or "7075" in primary_upper) and \
                       ("CRES" in hw_upper or "STEEL" in hw_upper):
                        warnings.append(
                            f"Material mismatch: Parent is aluminum but {hw.standard} "
                            f"inserts are {hw.inferred_material}. Separate MUA required."
                        )

        # Determine drawing type
        drawing_type = DrawingType.UNKNOWN
        title = title_data.get("title", "").upper()
        if "ASSEMBLY" in title:
            drawing_type = DrawingType.ASSEMBLY if "SUB" not in title else DrawingType.SUBASSEMBLY
        elif "WELD" in title:
            drawing_type = DrawingType.WELDMENT
        elif title:
            drawing_type = DrawingType.DETAIL

        return DrawingExtraction(
            drawing_number=title_data.get("drawing_number", "UNKNOWN"),
            revision=title_data.get("revision"),
            title=title_data.get("title"),
            cage_code=title_data.get("cage_code"),
            primary_material=primary_mat,
            subordinate_materials=[],
            embedded_hardware=aggregated_hardware,
            referenced_standards=sorted(set(all_standards)),
            sheet_count=len(page_texts),
            calc_weight_lbs=title_data.get("calc_weight_lbs"),
            drawing_type=drawing_type,
            extraction_warnings=warnings,
        )

    def _vision_fallback_title_block(
        self,
        pdf_path: Path,
        existing_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Call vision API for title block when text extraction failed.

        Only extracts the first page title block region.
        """
        images = self._pdf_to_images(pdf_path, pages=[0])
        if not images:
            return existing_data

        result = self._call_vision_with_retry(
            images[0],
            self.prompts.title_block_extraction(),
        )

        if result.success and result.data:
            # Merge: existing text data wins on conflict
            merged = dict(result.data)
            for key, val in existing_data.items():
                if val:  # Only overwrite if existing has value
                    merged[key] = val
            return merged

        return existing_data

    def _vision_fallback_hardware(
        self,
        pdf_path: Path,
        page_indices: list[int],
    ) -> list[EmbeddedHardware]:
        """Call vision API for specific pages where text extraction failed.

        Args:
            pdf_path: Source PDF.
            page_indices: 0-indexed page numbers needing vision.

        Returns:
            Hardware items extracted via vision.
        """
        images = self._pdf_to_images(pdf_path, pages=page_indices)
        results: list[EmbeddedHardware] = []

        for img, page_idx in zip(images, page_indices):
            hw_result = self._call_vision_with_retry(
                img,
                self.prompts.embedded_hardware_extraction(),
            )

            if not hw_result.success:
                continue

            for item in hw_result.data.get("items", []):
                try:
                    hw = EmbeddedHardware(
                        standard=item["standard"],
                        thread_size=item.get("thread_size"),
                        quantity=item.get("quantity", 1),
                        raw_callout=item.get("raw_callout", ""),
                    )
                    hw.resolve_material()
                    results.append(hw)
                except (KeyError, ValidationError) as e:
                    logger.warning(f"Vision hardware parse failed: {e}")

        return results

    def _extract_text_by_page(self, pdf_path: Path) -> list[str]:
        """Extract text from each PDF page.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            List of text strings, one per page.
        """
        try:
            import fitz
        except ImportError as e:
            raise ImportError("pip install PyMuPDF --break-system-packages") from e

        doc = fitz.open(pdf_path)
        texts = [page.get_text() for page in doc]
        doc.close()
        return texts

    def _call_vision_with_retry(
        self,
        image_b64: str,
        prompt: str,
        max_retries: int = 3,
    ) -> ExtractionResult:
        """Call vision API with exponential backoff retries.

        Args:
            image_b64: Base64-encoded image.
            prompt: Extraction prompt.
            max_retries: Maximum retry attempts.

        Returns:
            ExtractionResult from vision API.
        """
        import time

        for attempt in range(1, max_retries + 1):
            result = self._call_haiku(image_b64, prompt)
            if result.success:
                return result
            logger.warning(f"Vision attempt {attempt}/{max_retries} failed: {result.error}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)

        return ExtractionResult(success=False, error="All retries exhausted")

    def extract_drawing_tree(self, pdf_path: Path) -> DrawingTreeExtraction:
        """Extract assembly hierarchy from an MSFC Drawing Tree.

        Args:
            pdf_path: Path to the DT PDF file.

        Returns:
            Complete DrawingTreeExtraction object.
        """
        images = self._pdf_to_images(pdf_path)
        logger.info(f"Processing Drawing Tree {pdf_path.name}")

        # Drawing Trees are usually single page
        dt_result = self._call_haiku(images[0], self.prompts.drawing_tree_extraction())

        if not dt_result.success:
            logger.error(f"Failed to extract Drawing Tree: {dt_result.error}")
            return DrawingTreeExtraction(
                dt_drawing_number="UNKNOWN-DT",
                top_assembly="UNKNOWN",
                extraction_warnings=[f"Extraction failed: {dt_result.error}"],
            )

        data = dt_result.data
        nodes: dict[str, AssemblyNode] = {}

        for node_data in data.get("nodes", []):
            dwg_num = node_data.get("drawing_number", "")
            if not dwg_num:
                continue

            title = node_data.get("title", "")
            drawing_type = self._classify_drawing_type(title)

            nodes[dwg_num] = AssemblyNode(
                drawing_number=dwg_num,
                title=title,
                parent_drawing=node_data.get("parent"),
                children=node_data.get("children", []),
                drawing_type=drawing_type,
            )

        # Assign levels via BFS
        top = data.get("top_assembly", "")
        if top and top in nodes:
            self._assign_levels(nodes, top)

        return DrawingTreeExtraction(
            dt_drawing_number=data.get("dt_drawing_number", f"{top}-DT"),
            top_assembly=top,
            total_weight_lbs=data.get("total_weight_lbs"),
            nodes=nodes,
        )

    def _call_haiku(self, image_b64: str, prompt: str) -> ExtractionResult:
        """Make a single call to Claude Haiku with an image.

        Args:
            image_b64: Base64-encoded image.
            prompt: Extraction prompt.

        Returns:
            ExtractionResult with parsed JSON or error.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
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

            raw_text = response.content[0].text
            parsed = self._parse_json_response(raw_text)

            if parsed is None:
                return ExtractionResult(
                    success=False,
                    error="Failed to parse JSON from response",
                    raw_response=raw_text,
                )

            return ExtractionResult(success=True, data=parsed, raw_response=raw_text)

        except Exception as e:
            logger.error(f"Haiku API call failed: {e}")
            return ExtractionResult(success=False, error=str(e))

    def _pdf_to_images(
        self,
        pdf_path: Path,
        pages: list[int] | None = None,
        max_pixels: int = 7500,
    ) -> list[str]:
        """Convert PDF pages to base64 PNG images, respecting max size limits.

        Args:
            pdf_path: Path to PDF file.
            pages: Optional list of 0-indexed page numbers. If None, all pages.
            max_pixels: Maximum dimension in pixels (Bedrock limit is 8000).

        Returns:
            List of base64-encoded PNG images.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("pip install PyMuPDF --break-system-packages")

        doc = fitz.open(pdf_path)
        images: list[str] = []

        page_indices = pages if pages is not None else range(len(doc))

        for i in page_indices:
            if i >= len(doc):
                continue
            page = doc[i]
            # Start with 150 DPI for good quality
            dpi = 150
            pix = page.get_pixmap(dpi=dpi)

            # If image exceeds max size, reduce DPI to fit
            while max(pix.width, pix.height) > max_pixels and dpi > 50:
                dpi = int(dpi * max_pixels / max(pix.width, pix.height) * 0.95)
                pix = page.get_pixmap(dpi=dpi)
                logger.debug(f"Reduced DPI to {dpi} ({pix.width}x{pix.height})")

            img_bytes = pix.tobytes("png")
            images.append(base64.b64encode(img_bytes).decode())
            logger.debug(f"Page {i+1} image: {pix.width}x{pix.height} at {dpi} DPI")

        doc.close()
        logger.debug(f"Converted {len(images)} pages from {pdf_path.name}")
        return images

    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract raw text from PDF for format detection.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Concatenated text from all pages.
        """
        try:
            import fitz
        except ImportError:
            return ""

        doc = fitz.open(pdf_path)
        text_parts: list[str] = []

        for page in doc:
            text_parts.append(page.get_text())

        doc.close()
        return "\n".join(text_parts)

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any] | None:
        """Extract and parse JSON from model response.

        Args:
            text: Raw response text from model.

        Returns:
            Parsed JSON dict or None if parsing fails.
        """
        text = text.strip()

        # Remove markdown code fences
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]

        # Find JSON object or array
        match = re.search(r"[\[{][\s\S]*[\]}]", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error: {e}")

        return None

    @staticmethod
    def _aggregate_hardware(items: list[EmbeddedHardware]) -> list[EmbeddedHardware]:
        """Aggregate hardware items by standard and thread size.

        Args:
            items: List of hardware items (may have duplicates).

        Returns:
            Aggregated list with combined quantities.
        """
        by_key: dict[str, EmbeddedHardware] = {}

        for item in items:
            key = f"{item.standard}|{item.thread_size or 'NA'}"
            if key in by_key:
                by_key[key].quantity += item.quantity
            else:
                by_key[key] = item.model_copy()

        return list(by_key.values())

    @staticmethod
    def _classify_drawing_type(title: str) -> DrawingType:
        """Classify drawing type from title text.

        Args:
            title: Drawing title string.

        Returns:
            Classified DrawingType.
        """
        title_upper = title.upper()

        if "DRAWING TREE" in title_upper:
            return DrawingType.DRAWING_TREE
        if "WELD" in title_upper:
            return DrawingType.WELDMENT
        if "SUB-ASSEMBLY" in title_upper or "SUBASSEMBLY" in title_upper:
            return DrawingType.SUBASSEMBLY
        if "ASSEMBLY" in title_upper:
            return DrawingType.ASSEMBLY

        return DrawingType.DETAIL

    @staticmethod
    def _assign_levels(nodes: dict[str, AssemblyNode], top: str) -> None:
        """Assign hierarchy levels via BFS traversal.

        Args:
            nodes: Dictionary of assembly nodes.
            top: Top-level assembly drawing number.
        """
        from collections import deque

        queue = deque([(top, 0)])
        visited: set[str] = set()

        while queue:
            current, level = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if current in nodes:
                nodes[current].level = level
                for child in nodes[current].children:
                    if child in nodes:
                        queue.append((child, level + 1))
