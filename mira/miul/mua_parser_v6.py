#!/usr/bin/env python3
"""
Module: Mua Parser V6
Purpose: MUA PDF Parser v6 - Vision-First Parser with Text/Vision/Hybrid Modes.

BoundState AI 2025
Version: 6.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016, SWE-032
Safety Critical: True
"""

from __future__ import annotations

import os
import sys
import io
import json
import base64
import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
from pydantic import BaseModel, Field, field_validator
import uuid
from typing import Tuple

__all__ = ["MUAParserV6", "MUAExtractedFieldsV6", "parse_mua_pdf_v6"]
__safety_critical__ = True

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

USE_BEDROCK = os.getenv("USE_BEDROCK", "1").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-gov-west-1")
SONNET_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_MODEL_DIRECT = "claude-sonnet-4-5-20250929"

ExtractionMode = Literal["text", "vision", "hybrid"]

# ============================================================================
# Pydantic Models for Structured Output
# ============================================================================

class MUAExtractedFieldsV6(BaseModel):
    """Extracted MUA fields for BOK - optimized for material lookup and new MUA writing."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    # Primary Identification
    mua_number: Optional[str] = Field(None, description="MUA number (e.g., '90-A-430', 'WCE-1234', 'XFMUA-567', '1001-0021')")
    category: Optional[str] = Field(None, description="MUA category I, II, or III")

    @field_validator('category', mode='before')
    @classmethod
    def normalize_category(cls, v):
        """Normalize category to uppercase Roman numerals."""
        if v is None:
            return v
        v_upper = str(v).upper().strip()
        if v_upper in ('I', 'II', 'III', '1', '2', '3'):
            mapping = {'1': 'I', '2': 'II', '3': 'III'}
            return mapping.get(v_upper, v_upper)
        return None

    # Material Information (CRITICAL for BOK)
    material_designation: Optional[str] = Field(
        None,
        description="SPECIFIC material with alloy/temper (e.g., '316 SS', 'Inconel 718', 'PTFE', 'KYNAR')"
    )
    material_specification: Optional[str] = Field(
        None,
        description="Specification number (e.g., 'AMS 5662', 'MIL-DTL-5541', 'BAC-5753N')"
    )
    material_code: Optional[str] = Field(None, description="MAPTIS material code if present")
    manufacturer: Optional[str] = Field(None, description="Manufacturer name")
    trade_name: Optional[str] = Field(None, description="Trade/brand name")

    # Configuration and Use
    configuration_details: Optional[str] = Field(
        None,
        description="Component type (e.g., 'Tank', 'Valve', 'Seal', 'Wire', 'Tubing')"
    )
    static_or_dynamic: Optional[str] = Field(
        None,
        description="Static or dynamic service"
    )
    application: Optional[str] = Field(
        None,
        description="Where/how material is used - detailed description"
    )

    # Project Context
    system: Optional[str] = Field(None, description="System name (e.g., 'ECLSS', 'Propulsion', 'Thermal')")
    project: Optional[str] = Field(None, description="Project name (e.g., 'ISS', 'SLS', 'Orion')")
    using_assembly: Optional[str] = Field(None, description="Using assembly part number(s)")
    part_number: Optional[str] = Field(None, description="Part number(s)")

    # Issue and Rationale (KEY for BOK provenance)
    issue: Optional[str] = Field(
        None,
        description="Non-conformance or problem description (e.g., 'SCC', 'FLAMM', 'TOX', 'exceeds limit')"
    )
    rationale: Optional[str] = Field(
        None,
        description="Technical justification for approval - FULL TEXT explaining how materials with issues get approved"
    )

    # Environment Conditions
    max_pressure: Optional[float] = Field(None, description="Maximum pressure (numeric only)")
    pressure_units: Optional[str] = Field(None, description="Pressure units (psi, psia, psig, torr)")
    max_temperature_f: Optional[float] = Field(None, description="Maximum temperature in F")
    min_temperature_f: Optional[float] = Field(None, description="Minimum temperature in F")
    environment: Optional[str] = Field(
        None,
        description="Environment/media (GOX, LOX, GH2, LH2, ambient, vacuum, etc.)"
    )
    location: Optional[str] = Field(
        None,
        description="Habitable or Nonhabitable"
    )

    # Disposition
    determination: Optional[str] = Field(
        None,
        description="APPROVED, APPROVED_WITH_LIMITS, REJECTED, or DEFERRED"
    )
    memo_number: Optional[str] = Field(None, description="Memo number for disposition")
    effectivity: Optional[str] = Field(None, description="Effectivity statement")

    # Supporting Documentation
    test_reports: List[str] = Field(default_factory=list, description="List of test report numbers")
    conditions: List[str] = Field(default_factory=list, description="List of approval conditions")

    # Metadata
    originator: Optional[str] = Field(None, description="Originator name")
    organization: Optional[str] = Field(None, description="Organization/contractor")
    date: Optional[str] = Field(None, description="MUA date")

    # Extraction Metadata
    extraction_mode: str = Field(default="unknown", description="Mode used: text, vision, or hybrid")
    parse_confidence: float = Field(default=0.0, description="Overall parse confidence 0-1")
    raw_text: str = Field(default="", description="Complete extracted text (for debugging)")


# ============================================================================
# Extraction Prompt
# ============================================================================

EXTRACTION_PROMPT = """You are an expert at extracting structured data from NASA Material Usage Agreement (MUA) documents.

Extract ALL available information from this MUA document into the following JSON structure.
Be thorough - capture the COMPLETE rationale and application text, not just summaries.

CRITICAL RULES:
1. For material_designation: Extract the ACTUAL material (e.g., "316 SS", "Inconel 718", "PTFE", "KYNAR fluoroplastic")
   - Do NOT extract field labels like "MANUFACTURER", "MATERIAL", "CONTRACTOR"
   - Process specification MUAs may have "N/A" for material if they're about processes
2. For rationale: Extract the COMPLETE technical justification - this is critical for provenance
3. For issue: Look for non-conformance descriptions, "FLAMM", "TOX", "SCC", requirement violations
4. For determination: Map to one of: APPROVED, APPROVED_WITH_LIMITS, REJECTED, DEFERRED
5. Return null for any field not found in the document
6. For numeric fields (pressure, temperature), extract only the number, not units

Return ONLY valid JSON with this exact structure (no markdown, no explanation):
{
    "mua_number": "string or null",
    "category": "I, II, or III or null",
    "material_designation": "string or null - the ACTUAL material name/alloy",
    "material_specification": "string or null",
    "material_code": "string or null",
    "manufacturer": "string or null",
    "trade_name": "string or null",
    "configuration_details": "string or null",
    "static_or_dynamic": "string or null",
    "application": "string or null - full application description",
    "system": "string or null",
    "project": "string or null",
    "using_assembly": "string or null",
    "part_number": "string or null",
    "issue": "string or null - the problem/non-conformance",
    "rationale": "string or null - COMPLETE technical justification",
    "max_pressure": null or number,
    "pressure_units": "string or null",
    "max_temperature_f": null or number,
    "min_temperature_f": null or number,
    "environment": "string or null",
    "location": "Habitable or Nonhabitable or null",
    "determination": "APPROVED, APPROVED_WITH_LIMITS, REJECTED, or DEFERRED or null",
    "memo_number": "string or null",
    "effectivity": "string or null",
    "test_reports": ["list of report numbers"],
    "conditions": ["list of approval conditions"],
    "originator": "string or null",
    "organization": "string or null",
    "date": "string or null"
}"""


# ============================================================================
# MUA Parser V6
# ============================================================================

class MUAParserV6:
    """
    Vision-first MUA parser with text/vision/hybrid modes.

    Uses Claude Sonnet 4.5 for intelligent extraction instead of brittle regex.
    """

    def __init__(
        self,
        mode: ExtractionMode = "hybrid",
        use_bedrock: bool = None,
        bedrock_region: str = None,
    ):
        """
        Initialize parser.

        Args:
            mode: Extraction mode - "text", "vision", or "hybrid"
            use_bedrock: Use AWS Bedrock (default: USE_BEDROCK env var)
            bedrock_region: Bedrock region (default: BEDROCK_REGION env var)
        """
        self.mode = mode
        self.use_bedrock = use_bedrock if use_bedrock is not None else USE_BEDROCK
        self.bedrock_region = bedrock_region or BEDROCK_REGION
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize client
        self._client = None
        self._model = None

    def _get_client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            if self.use_bedrock:
                try:
                    from anthropic import AnthropicBedrock
                    self._client = AnthropicBedrock(aws_region=self.bedrock_region)
                    self._model = SONNET_MODEL_BEDROCK
                    self.logger.info(f"Using Bedrock in {self.bedrock_region}")
                except ImportError:
                    self.logger.error("anthropic package not installed. Run: pip install anthropic")
                    raise
                except Exception as e:
                    self.logger.error(f"Failed to initialize Bedrock client: {e}")
                    raise
            else:
                try:
                    from anthropic import Anthropic
                    self._client = Anthropic()
                    self._model = SONNET_MODEL_DIRECT
                    self.logger.info("Using direct Anthropic API")
                except ImportError:
                    self.logger.error("anthropic package not installed. Run: pip install anthropic")
                    raise
        return self._client

    def _extract_text(self, pdf_path: Path) -> str:
        """Extract text from PDF using PyMuPDF."""
        doc = fitz.open(pdf_path)
        full_text = ""

        for page_num, page in enumerate(doc, 1):
            page_text = page.get_text()
            full_text += f"\n--- Page {page_num} ---\n{page_text}"

        doc.close()
        return full_text

    def _load_pdf_pages(
        self,
        pdf_path: Path,
        pages: List[int] | None = None
    ) -> Tuple[str, str]:
        """
        Load PDF (or subset of pages) as base64 for Claude document input.

        Args:
            pdf_path: Path to PDF file
            pages: Optional 0-indexed page numbers. If None, loads entire PDF.

        Returns:
            Tuple of (base64_data, media_type)
        """
        if pages is None:
            # Send full PDF
            data = base64.standard_b64encode(pdf_path.read_bytes()).decode()
            self.logger.info(f"Loading full PDF: {pdf_path.name}")
            return data, "application/pdf"

        # Extract only specified pages using pypdf
        reader = PdfReader(pdf_path)
        writer = PdfWriter()

        for page_num in sorted(pages):
            if page_num < len(reader.pages):
                writer.add_page(reader.pages[page_num])

        buffer = io.BytesIO()
        writer.write(buffer)
        data = base64.standard_b64encode(buffer.getvalue()).decode()

        self.logger.info(f"Loading PDF pages {pages} from {pdf_path.name} ({len(reader.pages)} total)")
        return data, "application/pdf"

    def _extract_via_text(self, pdf_path: Path) -> Dict[str, Any]:
        """
        Extract using text mode: PDF → PyMuPDF text → Sonnet → JSON
        """
        client = self._get_client()
        text = self._extract_text(pdf_path)

        self.logger.info(f"Text extraction: {len(text)} characters")

        response = client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"{EXTRACTION_PROMPT}\n\nDocument text:\n{text}"
                }
            ]
        )

        # Parse JSON response
        response_text = response.content[0].text.strip()

        # Handle markdown code blocks more robustly
        if "```" in response_text:
            # Find content between first ``` and last ```
            start_idx = response_text.find("```")
            # Skip past the first line (```json or ```)
            first_newline = response_text.find("\n", start_idx)
            if first_newline != -1:
                end_idx = response_text.rfind("```")
                if end_idx > first_newline:
                    response_text = response_text[first_newline + 1:end_idx].strip()
                else:
                    response_text = response_text[first_newline + 1:].strip()

        try:
            result = json.loads(response_text)
            result["extraction_mode"] = "text"
            result["raw_text"] = text
            return result
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON from text extraction: {e}")
            self.logger.debug(f"Response was: {response_text[:500]}")
            return {"extraction_mode": "text", "raw_text": text, "parse_error": str(e)}

    def _extract_via_vision(self, pdf_path: Path, pages: List[int] | None = None) -> Dict[str, Any]:
        """
        Extract using vision mode: PDF → direct document → Sonnet Vision → JSON

        Args:
            pdf_path: Path to PDF file
            pages: Optional 0-indexed page numbers. If None, sends entire PDF.
        """
        client = self._get_client()

        pdf_data, media_type = self._load_pdf_pages(pdf_path, pages)

        # Build page instruction for human-readable context
        page_instruction = ""
        if pages:
            page_list = ", ".join(str(p + 1) for p in pages)  # 1-indexed for human readability
            page_instruction = f"Focus on pages {page_list}. "

        self.logger.info(f"Vision extraction: {pdf_path.name}" + (f" (pages {pages})" if pages else " (full PDF)"))

        # Build content with document block (not images)
        content = [
            {"type": "text", "text": f"{page_instruction}Extract all MUA fields from this document."},
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": pdf_data
                }
            },
            {"type": "text", "text": EXTRACTION_PROMPT}
        ]

        response = client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": content
                }
            ]
        )

        # Parse JSON response - handle empty responses
        if not response.content:
            self.logger.error("API returned empty content list")
            return {"extraction_mode": "vision", "parse_error": "Empty API response"}

        response_text = response.content[0].text.strip()

        # Handle markdown code blocks more robustly
        if "```" in response_text:
            # Find content between first ``` and last ```
            start_idx = response_text.find("```")
            # Skip past the first line (```json or ```)
            first_newline = response_text.find("\n", start_idx)
            if first_newline != -1:
                end_idx = response_text.rfind("```")
                if end_idx > first_newline:
                    response_text = response_text[first_newline + 1:end_idx].strip()
                else:
                    response_text = response_text[first_newline + 1:].strip()

        try:
            result = json.loads(response_text)
            result["extraction_mode"] = "vision"
            return result
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON from vision extraction: {e}")
            self.logger.debug(f"Response was: {response_text[:500]}")
            return {"extraction_mode": "vision", "parse_error": str(e)}

    def _merge_results(
        self,
        text_result: Dict[str, Any],
        vision_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge text and vision results, preferring vision values.

        Strategy:
        - Use vision value if present and non-null
        - Fall back to text value if vision is null/missing
        - For lists, prefer longer list
        """
        merged = {}

        # Get all keys from both results
        all_keys = set(text_result.keys()) | set(vision_result.keys())

        # Skip metadata keys for merging
        skip_keys = {"extraction_mode", "raw_text", "parse_error"}

        for key in all_keys:
            if key in skip_keys:
                continue

            text_val = text_result.get(key)
            vision_val = vision_result.get(key)

            # Lists: prefer longer
            if isinstance(text_val, list) or isinstance(vision_val, list):
                text_list = text_val if isinstance(text_val, list) else []
                vision_list = vision_val if isinstance(vision_val, list) else []
                merged[key] = vision_list if len(vision_list) >= len(text_list) else text_list
            # Strings/numbers: prefer vision if present
            elif vision_val is not None:
                merged[key] = vision_val
            elif text_val is not None:
                merged[key] = text_val
            else:
                merged[key] = None

        # Set metadata
        merged["extraction_mode"] = "hybrid"
        merged["raw_text"] = text_result.get("raw_text", "")

        return merged

    def parse_pdf(self, pdf_path: Path, pages: List[int] | None = None) -> MUAExtractedFieldsV6:
        """
        Parse MUA PDF and extract fields.

        Args:
            pdf_path: Path to PDF file
            pages: Optional 0-indexed page numbers for vision mode. If None, processes entire PDF.

        Returns:
            Extracted fields as Pydantic model
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        self.logger.info(f"Parsing {pdf_path.name} with mode={self.mode}" + (f", pages={pages}" if pages else ""))

        try:
            if self.mode == "text":
                result = self._extract_via_text(pdf_path)
            elif self.mode == "vision":
                result = self._extract_via_vision(pdf_path, pages=pages)
            else:  # hybrid
                text_result = self._extract_via_text(pdf_path)
                vision_result = self._extract_via_vision(pdf_path, pages=pages)
                result = self._merge_results(text_result, vision_result)

            # Calculate confidence
            result["parse_confidence"] = self._calculate_confidence(result)

            # Remove parse_error before building Pydantic model (not a valid field)
            parse_error = result.pop("parse_error", None)
            if parse_error:
                self.logger.warning(f"Parse error during extraction: {parse_error}")

            # Build Pydantic model
            fields = MUAExtractedFieldsV6(**result)

            self.logger.info(
                f"Parsed {pdf_path.name}: "
                f"Material={fields.material_designation}, "
                f"Category={fields.category}, "
                f"Mode={fields.extraction_mode}, "
                f"Confidence={fields.parse_confidence:.2f}"
            )

            return fields

        except Exception as e:
            self.logger.error(f"Failed to parse {pdf_path}: {e}")
            raise

    def _calculate_confidence(self, fields: Dict[str, Any]) -> float:
        """Calculate overall parse confidence score."""
        weights = {
            "mua_number": 0.1,
            "category": 0.05,
            "material_designation": 0.20,
            "application": 0.15,
            "rationale": 0.20,
            "issue": 0.10,
            "environment": 0.05,
            "location": 0.05,
            "determination": 0.10,
        }

        score = 0.0
        for field, weight in weights.items():
            value = fields.get(field)
            if value is not None and value != "" and value != []:
                # Validate material isn't garbage
                if field == "material_designation":
                    if not self._validate_material(value):
                        continue
                score += weight

        return min(score, 1.0)

    def _validate_material(self, material: str) -> bool:
        """Validate material is not a field label or garbage."""
        if not material or len(material.strip()) < 2:
            return False

        # Common field labels that get misextracted
        garbage = [
            "MANUFACTURER", "MATERIAL", "DESIGNATION", "CONTRACTOR",
            "ORIGINATOR", "ORGANIZATION", "CATEGORY", "SPECIFICATION",
            "N/A", "NONE", "SEE BELOW", "VARIOUS"
        ]

        material_upper = material.upper().strip()
        if material_upper in garbage:
            return False

        # Check for partial matches
        for g in garbage:
            if g in material_upper and len(material_upper) < len(g) + 5:
                return False

        return True


# ============================================================================
# Document Container
# ============================================================================

@dataclass
class MUADocumentV6:
    """Complete MUA document with metadata."""

    file_path: Path
    fields: MUAExtractedFieldsV6
    parse_timestamp: datetime = field(default_factory=datetime.now)
    parse_success: bool = True
    parse_errors: list[str] = field(default_factory=list)
    source: str = ""  # NASA SWE-013 traceability


    @property
    def has_critical_fields(self) -> bool:
        """Check if critical fields for BOK were extracted."""
        return bool(
            self.fields.material_designation and
            (self.fields.rationale or self.fields.application) and
            self.fields.parse_confidence > 0.5
        )

    @property
    def is_process_spec_mua(self) -> bool:
        """Check if this is a process specification MUA (vs material MUA)."""
        spec = self.fields.material_specification or ""
        return spec.startswith("BAC") or "PROCESS" in spec.upper()

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "file_path": str(self.file_path),
            "parse_timestamp": self.parse_timestamp.isoformat(),
            "parse_success": self.parse_success,
            "parse_errors": self.parse_errors,
            "is_process_spec_mua": self.is_process_spec_mua,
            "fields": self.fields.model_dump(exclude_none=True, exclude={"raw_text"}),
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_bok_record(self) -> dict:
        """
        Convert to BOK record format for database storage.

        Optimized for:
        - Searching by material/environment/application
        - Finding provenance for new MUAs
        """
        return {
            "mua_number": self.fields.mua_number,
            "category": self.fields.category,
            "material_designation": self.fields.material_designation,
            "material_specification": self.fields.material_specification,
            "trade_name": self.fields.trade_name,
            "manufacturer": self.fields.manufacturer,
            "application": self.fields.application,
            "system": self.fields.system,
            "project": self.fields.project,
            "issue": self.fields.issue,
            "rationale": self.fields.rationale,
            "environment": self.fields.environment,
            "location": self.fields.location,
            "max_temperature_f": self.fields.max_temperature_f,
            "min_temperature_f": self.fields.min_temperature_f,
            "max_pressure": self.fields.max_pressure,
            "pressure_units": self.fields.pressure_units,
            "determination": self.fields.determination,
            "conditions": self.fields.conditions,
            "test_reports": self.fields.test_reports,
            "source_file": str(self.file_path.name),
            "parse_confidence": self.fields.parse_confidence,
            "is_process_spec": self.is_process_spec_mua,
        }


# ============================================================================
# Convenience Function
# ============================================================================

def parse_mua_pdf_v6(
    pdf_path: Path | str,
    mode: ExtractionMode = "hybrid",
    use_bedrock: bool = None,
    pages: List[int] | None = None,
) -> MUADocumentV6:
    """
    Parse a MUA PDF file.

    Args:
        pdf_path: Path to PDF
        mode: Extraction mode - "text", "vision", or "hybrid"
        use_bedrock: Use AWS Bedrock (default: USE_BEDROCK env var)
        pages: Optional 0-indexed page numbers for vision mode. If None, processes entire PDF.

    Returns:
        Parsed MUA document
    """
    pdf_path = Path(pdf_path)
    parser = MUAParserV6(mode=mode, use_bedrock=use_bedrock)

    try:
        fields = parser.parse_pdf(pdf_path, pages=pages)
        success = fields.parse_confidence > 0.3

        return MUADocumentV6(
            file_path=pdf_path,
            fields=fields,
            parse_success=success
        )
    except Exception as e:
        logger.error(f"Failed to parse {pdf_path}: {e}")
        return MUADocumentV6(
            file_path=pdf_path,
            fields=MUAExtractedFieldsV6(),
            parse_success=False,
            parse_errors=[str(e)]
        )


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="MUA PDF Parser V6")
    parser.add_argument("pdf_path", type=str, help="Path to MUA PDF")
    parser.add_argument(
        "--mode",
        choices=["text", "vision", "hybrid"],
        default="hybrid",
        help="Extraction mode (default: hybrid)"
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Use direct Anthropic API instead of Bedrock"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )

    args = parser.parse_args()

    pdf_file = Path(args.pdf_path)
    if not pdf_file.exists():
        print(f"File not found: {pdf_file}")
        sys.exit(1)

    # Parse
    doc = parse_mua_pdf_v6(
        pdf_file,
        mode=args.mode,
        use_bedrock=not args.direct
    )

    if args.json:
        print(doc.to_json())
    else:
        print(f"\n{'='*60}")
        print(f"MUA Parse Results - V6 ({doc.fields.extraction_mode} mode)")
        print(f"{'='*60}")
        print(f"File: {doc.file_path.name}")
        print(f"Success: {doc.parse_success}")
        print(f"Confidence: {doc.fields.parse_confidence:.0%}")
        print(f"Type: {'Process Spec MUA' if doc.is_process_spec_mua else 'Material MUA'}")

        print(f"\n--- Identification ---")
        print(f"  MUA Number: {doc.fields.mua_number}")
        print(f"  Category: {doc.fields.category}")
        print(f"  Date: {doc.fields.date}")

        print(f"\n--- Material ---")
        print(f"  Designation: {doc.fields.material_designation}")
        print(f"  Specification: {doc.fields.material_specification}")
        print(f"  Trade Name: {doc.fields.trade_name}")
        print(f"  Manufacturer: {doc.fields.manufacturer}")

        print(f"\n--- Application ---")
        print(f"  System: {doc.fields.system}")
        print(f"  Project: {doc.fields.project}")
        if doc.fields.application:
            print(f"  Application: {doc.fields.application[:200]}...")

        print(f"\n--- Environment ---")
        print(f"  Location: {doc.fields.location}")
        print(f"  Environment: {doc.fields.environment}")
        print(f"  Max Temp: {doc.fields.max_temperature_f}°F" if doc.fields.max_temperature_f else "  Max Temp: N/A")
        print(f"  Max Pressure: {doc.fields.max_pressure} {doc.fields.pressure_units or ''}" if doc.fields.max_pressure else "  Max Pressure: N/A")

        print(f"\n--- Issue ---")
        if doc.fields.issue:
            print(f"  {doc.fields.issue[:200]}...")

        print(f"\n--- Rationale ---")
        if doc.fields.rationale:
            print(f"  {doc.fields.rationale[:500]}...")

        print(f"\n--- Disposition ---")
        print(f"  Determination: {doc.fields.determination}")
        if doc.fields.conditions:
            print(f"  Conditions: {doc.fields.conditions}")

        print(f"\n{'='*60}")
