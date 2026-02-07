#!/usr/bin/env python3
"""
Module: Parts Inventory Extractor
Purpose: Parts Inventory Extractor - JSON output for drawing analysis.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

# Configuration from environment
USE_BEDROCK = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-gov-west-1")

# Model IDs - use Sonnet for vision tasks
SONNET_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_MODEL_DIRECT = "claude-sonnet-4-5-20250929"


@dataclass
class TitleBlockInfo:
    """Title block extraction result."""
    drawing_number: str = ""
    revision: str = ""
    title: str = ""
    material: str = ""
    material_spec: str = ""
    uns_number: str = ""


@dataclass
class PartItem:
    """Single part/item from parts list or EPL."""
    find_no: str = ""
    part_number: str = ""
    description: str = ""
    quantity: int = 1
    material: str = ""
    source: str = ""  # Which drawing it came from


@dataclass
class HardwareItem:
    """Embedded hardware (inserts, fasteners, etc.)."""
    standard: str = ""
    thread_size: str = ""
    quantity: int = 1
    material: str = ""
    raw_callout: str = ""
    source: str = ""


@dataclass
class DrawingInventory:
    """Inventory for a single drawing."""
    file_name: str = ""
    drawing_number: str = ""
    revision: str = ""
    title: str = ""
    drawing_type: str = ""  # DETAIL, ASSEMBLY, UNKNOWN
    primary_material: str = ""
    material_spec: str = ""
    parts: List[PartItem] = field(default_factory=list)
    hardware: List[HardwareItem] = field(default_factory=list)
    standards: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_name": self.file_name,
            "drawing_number": self.drawing_number,
            "revision": self.revision,
            "title": self.title,
            "drawing_type": self.drawing_type,
            "primary_material": self.primary_material,
            "material_spec": self.material_spec,
            "parts": [asdict(p) for p in self.parts],
            "hardware": [asdict(h) for h in self.hardware],
            "standards": self.standards,
            "warnings": self.warnings,
        }


@dataclass
class InventoryResult:
    """Complete inventory extraction result."""
    drawings: List[DrawingInventory] = field(default_factory=list)
    total_parts: int = 0
    total_hardware: int = 0
    unique_part_numbers: int = 0
    unique_standards: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "summary": {
                "total_drawings": len(self.drawings),
                "total_parts": self.total_parts,
                "total_hardware": self.total_hardware,
                "unique_part_numbers": self.unique_part_numbers,
                "unique_standards": self.unique_standards,
            },
            "drawings": [d.to_dict() for d in self.drawings],
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class PartsInventoryExtractor:
    """Extract parts inventory from engineering drawings using vision API."""

    def __init__(
        self,
        use_bedrock: bool = None,
        bedrock_region: str = None,
        api_key: str = None,
    ):
        """Initialize extractor.

        Args:
            use_bedrock: Use AWS Bedrock (default: USE_BEDROCK env var)
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
        """Lazy-load Anthropic client."""
        if self._client is None:
            if self.use_bedrock:
                from anthropic import AnthropicBedrock
                self._client = AnthropicBedrock(aws_region=self.bedrock_region)
                LOGGER.info(f"Using Bedrock in {self.bedrock_region}")
            else:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.api_key)
                LOGGER.info(f"Using direct Anthropic API with {self.model}")
        return self._client

    def extract_inventory(self, pdf_paths: List[Path]) -> InventoryResult:
        """Extract parts inventory from multiple PDFs.

        Args:
            pdf_paths: List of paths to PDF drawing files.

        Returns:
            InventoryResult with all extracted parts and hardware.
        """
        result = InventoryResult()
        all_part_numbers = set()
        all_standards = set()

        for pdf_path in pdf_paths:
            LOGGER.info(f"Processing: {pdf_path.name}")
            try:
                drawing_inv = self._extract_single_drawing(pdf_path)
                result.drawings.append(drawing_inv)

                # Accumulate totals
                result.total_parts += len(drawing_inv.parts)
                result.total_hardware += len(drawing_inv.hardware)

                for part in drawing_inv.parts:
                    if part.part_number:
                        all_part_numbers.add(part.part_number)

                for std in drawing_inv.standards:
                    all_standards.add(std)

            except Exception as e:
                LOGGER.error(f"Failed to process {pdf_path.name}: {e}")
                # Add failed drawing with error
                result.drawings.append(DrawingInventory(
                    file_name=pdf_path.name,
                    warnings=[f"Extraction failed: {str(e)}"],
                ))

        result.unique_part_numbers = len(all_part_numbers)
        result.unique_standards = len(all_standards)

        return result

    def _extract_single_drawing(self, pdf_path: Path) -> DrawingInventory:
        """Extract inventory from a single PDF drawing."""
        inventory = DrawingInventory(file_name=pdf_path.name)

        # HYBRID APPROACH: Extract text first for anchoring (same as MIUL builder)
        extracted_text = self._extract_text_from_pdf(pdf_path)
        if extracted_text:
            LOGGER.info(f"  Extracted {len(extracted_text)} chars of anchor text")

        # Convert PDF to images at 150 DPI (same as MIUL builder)
        images = self._pdf_to_images(pdf_path)
        if not images:
            inventory.warnings.append("Failed to convert PDF to images")
            return inventory

        # Use first page for title block, all pages for parts/hardware
        first_page = images[0]

        # Step 1: Extract title block info
        title_data = self._extract_title_block(first_page)
        inventory.drawing_number = title_data.get("drawing_number", "")
        inventory.revision = title_data.get("revision", "")
        inventory.title = title_data.get("title", "")
        inventory.primary_material = title_data.get("material", "")
        inventory.material_spec = title_data.get("material_spec", "")

        # Step 2: Determine drawing type and extract parts/hardware
        drawing_type_data = self._determine_drawing_type(first_page)
        inventory.drawing_type = drawing_type_data.get("type", "UNKNOWN")

        # Step 3: Extract parts list (for assemblies) or embedded hardware
        if inventory.drawing_type == "ASSEMBLY":
            # Pass extracted text for anchoring/validation
            parts_data = self._extract_parts_list(images, extracted_text)
            for part in parts_data.get("parts", []):
                inventory.parts.append(PartItem(
                    find_no=str(part.get("find_no", "")),
                    part_number=part.get("part_number", ""),
                    description=part.get("description", ""),
                    quantity=part.get("quantity", 1),
                    material=part.get("material", ""),
                    source=pdf_path.name,
                ))
        else:
            # Detail drawing - the drawing itself is the "part"
            inventory.parts.append(PartItem(
                part_number=inventory.drawing_number,
                description=inventory.title,
                quantity=1,
                material=inventory.primary_material,
                source=pdf_path.name,
            ))

        # Step 4: Extract embedded hardware from ALL pages
        hardware_data = self._extract_hardware(images)
        for hw in hardware_data.get("hardware", []):
            inventory.hardware.append(HardwareItem(
                standard=hw.get("standard", ""),
                thread_size=hw.get("thread_size", ""),
                quantity=hw.get("quantity", 1),
                material=hw.get("material", ""),
                raw_callout=hw.get("raw_callout", ""),
                source=pdf_path.name,
            ))

        # Step 5: Extract referenced standards
        standards_data = self._extract_standards(first_page)
        inventory.standards = standards_data.get("standards", [])

        return inventory

    def _extract_title_block(self, image_b64: str) -> Dict[str, Any]:
        """Extract title block information."""
        prompt = """Analyze this engineering drawing and extract the TITLE BLOCK information.

Return JSON:
{
    "drawing_number": "string - part/drawing number",
    "revision": "string - revision letter or number",
    "title": "string - part name/title",
    "material": "string - material callout (e.g., 'ALUMINUM ALLOY 7075-T6')",
    "material_spec": "string - material specification (e.g., 'AMS4124')",
    "uns_number": "string or null - UNS number if present"
}

Look in the title block area (typically lower right corner).
Return ONLY valid JSON."""

        return self._call_vision_api(image_b64, prompt)

    def _determine_drawing_type(self, image_b64: str) -> Dict[str, Any]:
        """Determine if drawing is ASSEMBLY or DETAIL."""
        prompt = """Analyze this engineering drawing and determine its type.

An ASSEMBLY drawing has:
- A PARTS LIST or EPL (Engineering Parts List) table
- Multiple parts referenced with find numbers
- Assembly instructions or views

A DETAIL drawing has:
- Single part with dimensions
- Manufacturing notes
- No parts list table

Return JSON:
{
    "type": "ASSEMBLY" or "DETAIL",
    "has_parts_list": true/false,
    "confidence": 0.0 to 1.0
}

Return ONLY valid JSON."""

        return self._call_vision_api(image_b64, prompt)

    def _extract_parts_list(self, images: List[str], extracted_text: str = "") -> Dict[str, Any]:
        """Extract parts list from assembly drawing.

        Uses HYBRID APPROACH same as MIUL builder:
        - If extracted_text is available, use it to anchor/validate results
        - Prevents hallucination of part numbers that don't exist in PDF
        """
        # Detect scanned PDFs (sparse text extraction)
        MIN_TEXT_FOR_ANCHORING = 500
        is_scanned_pdf = len(extracted_text) < MIN_TEXT_FOR_ANCHORING if extracted_text else True
        text_context = extracted_text[:8000] if extracted_text and not is_scanned_pdf else ""

        if is_scanned_pdf:
            # Pure vision mode for scanned PDFs
            prompt = """You are a STRICT forensic engineering drawing parser extracting the ENGINEERING PARTS LIST (EPL).
Look CAREFULLY at the image and extract ONLY what is visible in the EPL table.

CRITICAL ANTI-HALLUCINATION RULES:
1. Extract ONLY part numbers that are CLEARLY VISIBLE in the EPL table.
2. If you cannot read a part number clearly, SKIP IT. Do not guess.
3. SKIP rows where part_number would be "ITEM NOT SHOWN", "NOT SHOWN", "-", or blank.
4. DO NOT invent part numbers - copy EXACTLY what you see, character by character.
5. If unsure about a digit (6 vs 8, 0 vs D), look carefully and transcribe exactly.

For EACH part in the table, extract:
- find_no: Find number / item number
- part_number: EXACT as shown - copy character for character!
- quantity: Quantity (number), use 0 for "AR"
- description: Part name/description
- material: Material if shown in table

Return JSON:
{
    "parts": [
        {
            "find_no": "1",
            "part_number": "ABC-12345",
            "quantity": 1,
            "description": "HOUSING",
            "material": "AL 7075-T6"
        }
    ]
}

Return ONLY valid JSON. SKIP any "ITEM NOT SHOWN" rows entirely."""
        else:
            # HYBRID APPROACH: Include extracted text to anchor vision to real content
            prompt = f"""You are a STRICT forensic engineering drawing parser extracting the ENGINEERING PARTS LIST (EPL).

=== EXTRACTED TEXT FROM THIS DRAWING (GROUND TRUTH) ===
{text_context}
=== END EXTRACTED TEXT ===

CRITICAL ANTI-HALLUCINATION RULES:
1. You may ONLY return part numbers that appear in the EXTRACTED TEXT above.
2. If a part number is NOT in the extracted text, DO NOT include it.
3. SKIP rows where part_number would be "ITEM NOT SHOWN", "NOT SHOWN", "-", or blank.
4. TRANSCRIBE EXACTLY from the image - match what's in the extracted text.
5. For digits that look similar (6/8, 0/D), match against the extracted text.

For EACH part in the table, extract:
- find_no: Find number / item number
- part_number: EXACT as written - must exist in extracted text!
- quantity: Quantity (number), use 0 for "AR"
- description: Part name/description
- material: Material if shown in table

Return JSON:
{{
    "parts": [
        {{
            "find_no": "1",
            "part_number": "ABC-12345",
            "quantity": 1,
            "description": "HOUSING",
            "material": "AL 7075-T6"
        }}
    ]
}}

Return ONLY valid JSON. SKIP any "ITEM NOT SHOWN" rows entirely."""

        # Try each page to find parts list
        all_parts = []
        for i, image in enumerate(images[:5]):  # Check first 5 pages
            data = self._call_vision_api(image, prompt)
            parts = data.get("parts", [])
            if parts:
                all_parts.extend(parts)
                LOGGER.info(f"Found {len(parts)} parts on page {i+1}")

        # Post-extraction validation: filter out parts not in extracted text
        # (Same approach as MIUL builder)
        if extracted_text and len(extracted_text) >= MIN_TEXT_FOR_ANCHORING:
            validated_parts = []
            text_lower = extracted_text.lower()
            for part in all_parts:
                pn = part.get("part_number", "")
                # Check if part number appears in extracted text (fuzzy match)
                pn_clean = pn.replace("-", "").replace(" ", "").lower()
                if pn.lower() in text_lower or pn_clean in text_lower.replace("-", "").replace(" ", ""):
                    validated_parts.append(part)
                else:
                    LOGGER.warning(f"  FILTERED: {pn} not found in extracted text")
            return {"parts": validated_parts}
        elif extracted_text and len(extracted_text) < MIN_TEXT_FOR_ANCHORING:
            LOGGER.info(f"  SCANNED PDF detected ({len(extracted_text)} chars) - using pure vision mode")

        return {"parts": all_parts}

    def _extract_hardware(self, images: List[str]) -> Dict[str, Any]:
        """Extract embedded hardware from all pages."""
        prompt = """Extract ALL embedded hardware callouts from this drawing.

Look for:
1. HELICAL COIL INSERTS: "4X .3125-18 UNC-3B HELICAL COIL INSERT PER NASM33537"
2. THREAD INSERTS: NASM33537, NASM33538, MS21209, HCC-xxx
3. FASTENERS: NAS, MS, AN part numbers with quantities
4. PRESS-FIT items: DOWEL PINS, BUSHINGS with material specs
5. Any hardware with "nX" quantity prefix (4X, 6X, 24X, etc.)

For EACH hardware item:
{
    "standard": "NASM33537",
    "thread_size": ".3125-18 UNC-3B",
    "quantity": 4,
    "material": "CRES 302/304",
    "raw_callout": "4X .3125-18 UNC-3B HELICAL COIL INSERT PER NASM33537"
}

CRITICAL: Count the quantity prefix (4X = 4, 24X = 24).
If same callout appears multiple times on different views, report each.

Return JSON:
{
    "hardware": [...]
}

Return ONLY valid JSON. Return empty array if no hardware found."""

        all_hardware = []
        seen_callouts = set()

        for i, image in enumerate(images):
            data = self._call_vision_api(image, prompt)
            for hw in data.get("hardware", []):
                # Dedupe by raw callout
                callout = hw.get("raw_callout", "")
                if callout and callout not in seen_callouts:
                    seen_callouts.add(callout)
                    all_hardware.append(hw)
                elif not callout:
                    all_hardware.append(hw)

        return {"hardware": all_hardware}

    def _extract_standards(self, image_b64: str) -> Dict[str, Any]:
        """Extract referenced standards."""
        prompt = """List ALL standards and specifications referenced on this drawing.

Look for:
- Material specs: AMS, MIL-SPEC, QQ-, ASTM, SAE, UNS
- Hardware standards: NASM, NAS, MS, AN
- Process specs: MIL-STD, NASA-STD, ASME
- Quality specs: AS9100, ISO

Return JSON:
{
    "standards": ["AMS4124", "NASM33537", "MIL-STD-130"]
}

Return ONLY valid JSON."""

        return self._call_vision_api(image_b64, prompt)

    def _call_vision_api(self, image_b64: str, prompt: str) -> Dict[str, Any]:
        """Call Claude vision API."""
        try:
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
            LOGGER.error(f"Vision API call failed: {e}")
            return {}

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response."""
        # Strip markdown code fences
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the text
            import re
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {}

    def _pdf_to_images(self, pdf_path: Path, dpi: int = 150, max_pixels: int = 7500) -> List[str]:
        """Convert PDF to base64 images.

        Args:
            pdf_path: Path to PDF file
            dpi: Target DPI (150 for better OCR accuracy - same as MIUL builder)
            max_pixels: Maximum dimension in pixels (Claude limit is 8000)

        Returns:
            List of base64-encoded PNG images
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF required: pip install PyMuPDF")

        doc = fitz.open(pdf_path)
        images: List[str] = []

        for page in doc:
            # Check if page would exceed max_pixels at target DPI
            rect = page.rect
            width_at_dpi = rect.width * dpi / 72  # PDF points to pixels
            height_at_dpi = rect.height * dpi / 72

            # Auto-reduce DPI if page is too large (same logic as MIUL builder)
            actual_dpi = dpi
            if max(width_at_dpi, height_at_dpi) > max_pixels:
                scale_factor = max_pixels / max(width_at_dpi, height_at_dpi)
                actual_dpi = int(dpi * scale_factor * 0.95)  # 5% margin
                LOGGER.info(f"Page {page.number + 1}: Reducing DPI from {dpi} to {actual_dpi}")

            pix = page.get_pixmap(dpi=actual_dpi)
            img_bytes = pix.tobytes("png")
            images.append(base64.b64encode(img_bytes).decode())

        doc.close()
        return images

    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract raw text from PDF using PyMuPDF.

        This is used to ANCHOR vision results to actual document content,
        preventing hallucination of part numbers that don't exist.
        Same approach as MIUL builder.

        Returns:
            Concatenated text from all pages
        """
        try:
            import fitz
        except ImportError:
            return ""

        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                text_parts.append(text)
        doc.close()
        return "\n\n".join(text_parts)


def extract_parts_inventory(
    pdf_paths: List[Path],
    output_path: Optional[Path] = None,
) -> InventoryResult:
    """Convenience function to extract parts inventory.

    Args:
        pdf_paths: List of PDF file paths.
        output_path: Optional path to save JSON output.

    Returns:
        InventoryResult with all extracted data.
    """
    extractor = PartsInventoryExtractor()
    result = extractor.extract_inventory(pdf_paths)

    if output_path:
        output_path.write_text(result.to_json())
        LOGGER.info(f"Saved inventory to {output_path}")

    return result


# CLI support
if __name__ == "__main__":
    import sys
    import glob as glob_module

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python parts_inventory_extractor.py <pdf_or_dir> [pdf2] ... [-o output.json]")
        print("Examples:")
        print("  python -m mira.miul.parts_inventory_extractor C:/path/to/drawings")
        print("  python -m mira.miul.parts_inventory_extractor drawing1.pdf drawing2.pdf")
        print("  python -m mira.miul.parts_inventory_extractor C:/drawings/*.pdf -o inventory.json")
        sys.exit(1)

    # Parse args
    input_paths = []
    output_file = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            output_file = Path(args[i + 1])
            i += 2
        else:
            input_paths.append(args[i])
            i += 1

    # Expand inputs: directories, globs, and individual files
    pdf_files = []
    seen_paths = set()  # Dedupe by resolved path

    for input_path in input_paths:
        p = Path(input_path)

        # If it's a directory, get all PDFs in it (case-insensitive)
        if p.is_dir():
            for pdf in p.iterdir():
                if pdf.suffix.lower() == ".pdf":
                    resolved = pdf.resolve()
                    if resolved not in seen_paths:
                        seen_paths.add(resolved)
                        pdf_files.append(pdf)
            print(f"Found {len([f for f in pdf_files if f.parent.resolve() == p.resolve()])} PDFs in {p}")

        # If it contains wildcards, expand the glob (Windows doesn't do this)
        elif "*" in input_path or "?" in input_path:
            expanded = glob_module.glob(input_path)
            count = 0
            for f in expanded:
                if f.lower().endswith(".pdf"):
                    resolved = Path(f).resolve()
                    if resolved not in seen_paths:
                        seen_paths.add(resolved)
                        pdf_files.append(Path(f))
                        count += 1
            print(f"Glob '{input_path}' matched {count} files")

        # Otherwise treat as individual file
        elif p.exists() and p.suffix.lower() == ".pdf":
            resolved = p.resolve()
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                pdf_files.append(p)
        else:
            print(f"Warning: '{input_path}' not found or not a PDF")

    if not pdf_files:
        print("No PDF files found")
        sys.exit(1)

    print(f"Processing {len(pdf_files)} PDF files...")
    for f in pdf_files:
        print(f"  - {f.name}")

    result = extract_parts_inventory(
        pdf_files,
        output_path=output_file,
    )

    if not output_file:
        print(result.to_json())
    else:
        print(f"\nSaved to {output_file}")
        print(f"Summary: {len(result.drawings)} drawings, {result.total_parts} parts, {result.total_hardware} hardware items")
