#!/usr/bin/env python3
"""
Module: V6
Purpose: bok_standards_extractor_v6

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import os
import json
import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

import fitz  # PyMuPDF
from pydantic import BaseModel, Field, field_validator

__all__ = [
    "BOKStandardsExtractorV6",
    "ExtractedSection",
    "MaterialCompatibilityRecord",
    "TestProcedureRecord",
    "FlammabilityLimitRecord",
    "EnvironmentSpecification",
    "extract_bok_pdf_v6",
    "rebuild_bok_indices",
]
__safety_critical__ = True

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

USE_BEDROCK = os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-gov-west-1")
SONNET_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_MODEL_DIRECT = "claude-sonnet-4-5-20250929"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Default to Haiku for cost efficiency on large BOK extraction
DEFAULT_MODEL = os.getenv("BOK_EXTRACTOR_MODEL", "haiku")

ExtractionMode = Literal["text", "vision", "hybrid", "smart"]

# Source document paths
H2_BOK_PATH = Path(r"C:\maptis-nlp\data\bok\H2 BOK")
O2_BOK_PATH = Path(r"C:\maptis-nlp\data\bok\O2_BOK")
OUTPUT_PATH = Path(r"C:\BoundState\mira\databases")


# ============================================================================
# Enums for Classification
# ============================================================================

class GasType(str, Enum):
    """Gas type classification."""
    H2 = "H2"
    O2 = "O2"
    BOTH = "BOTH"


class ContentType(str, Enum):
    """Type of content extracted from the standard."""
    MATERIAL_COMPATIBILITY = "material_compatibility"
    TEST_PROCEDURE = "test_procedure"
    FLAMMABILITY_LIMIT = "flammability_limit"
    ENVIRONMENT_SPEC = "environment_spec"
    SAFETY_REQUIREMENT = "safety_requirement"
    GENERAL_INFO = "general_info"
    TABLE_DATA = "table_data"
    DEFINITION = "definition"


class CompatibilityClass(str, Enum):
    """Material compatibility classification."""
    A = "A"  # Excellent compatibility
    B = "B"  # Good compatibility
    C = "C"  # Limited compatibility
    D = "D"  # Not recommended
    X = "X"  # Incompatible
    U = "U"  # Unknown/untested


# ============================================================================
# Pydantic Models for Structured Output
# ============================================================================

class EnvironmentSpecification(BaseModel):
    """Environment specification extracted from standards."""
    model_config = {"extra": "ignore"}

    environment_type: Optional[str] = Field(None, description="GOX, LOX, GH2, LH2, air, vacuum, etc.")
    min_temperature_f: Optional[float] = Field(None, description="Minimum temperature in F")
    max_temperature_f: Optional[float] = Field(None, description="Maximum temperature in F")
    min_temperature_k: Optional[float] = Field(None, description="Minimum temperature in K")
    max_temperature_k: Optional[float] = Field(None, description="Maximum temperature in K")
    min_pressure_psia: Optional[float] = Field(None, description="Minimum pressure in psia")
    max_pressure_psia: Optional[float] = Field(None, description="Maximum pressure in psia")
    oxygen_concentration_pct: Optional[float] = Field(None, description="O2 concentration percentage")
    phase: Optional[str] = Field(None, description="Gas, liquid, solid, or mixed")


class MaterialCompatibilityRecord(BaseModel):
    """Material compatibility data extracted from standards tables."""
    model_config = {"extra": "ignore"}

    material_name: str = Field(..., description="Material designation (e.g., '316 SS', 'Inconel 718')")
    material_family: Optional[str] = Field(None, description="Material family (e.g., 'stainless_steel', 'nickel_alloy')")
    gas_type: GasType = Field(..., description="H2 or O2")
    compatibility_class: Optional[CompatibilityClass] = Field(None, description="A/B/C/D/X rating")
    compatibility_notes: Optional[str] = Field(None, description="Specific notes or conditions")
    environment: Optional[EnvironmentSpecification] = Field(None, description="Operating environment")
    source_table: Optional[str] = Field(None, description="Source table reference (e.g., 'Table A5.1')")
    source_section: Optional[str] = Field(None, description="Source section reference")
    source_page: Optional[int] = Field(None, description="Source page number")
    standard_reference: Optional[str] = Field(None, description="Standard document reference")

    # H2-specific fields
    embrittlement_index: Optional[float] = Field(None, description="H2 only: HEE index 0-1")

    # O2-specific fields
    ignition_sensitivity: Optional[str] = Field(None, description="O2 only: high/medium/low")
    autogenous_ignition_temp_f: Optional[float] = Field(None, description="O2 only: auto-ignition temp in F")
    cleaning_requirement: Optional[str] = Field(None, description="O2 only: e.g., 'CGA G-4.1', 'LOX clean'")
    mechanical_impact_result: Optional[str] = Field(None, description="O2 only: e.g., '20/20 no-reaction'")


class TestProcedureRecord(BaseModel):
    """Test procedure details extracted from standards."""
    model_config = {"extra": "ignore"}

    test_number: Optional[str] = Field(None, description="Test number (e.g., 'Test 13A', 'Test 17')")
    test_name: str = Field(..., description="Test procedure name")
    test_purpose: Optional[str] = Field(None, description="Purpose of the test")
    applicable_materials: Optional[List[str]] = Field(default_factory=list, description="Materials this test applies to")
    environment: Optional[EnvironmentSpecification] = Field(None, description="Test environment conditions")
    acceptance_criteria: Optional[str] = Field(None, description="Pass/fail criteria")
    standard_reference: Optional[str] = Field(None, description="Standard document reference (e.g., 'NASA-STD-6001B')")
    astm_reference: Optional[str] = Field(None, description="ASTM standard reference if applicable")
    source_section: Optional[str] = Field(None, description="Source section reference")
    source_page: Optional[int] = Field(None, description="Source page number")


class FlammabilityLimitRecord(BaseModel):
    """Flammability limit data extracted from standards."""
    model_config = {"extra": "ignore"}

    gas_type: GasType = Field(..., description="H2 or O2")
    oxidizer: Optional[str] = Field(None, description="Oxidizer (air, O2, etc.)")
    lower_flammability_limit_pct: Optional[float] = Field(None, description="LFL in volume %")
    upper_flammability_limit_pct: Optional[float] = Field(None, description="UFL in volume %")
    detonation_limit_lower_pct: Optional[float] = Field(None, description="Lower detonation limit")
    detonation_limit_upper_pct: Optional[float] = Field(None, description="Upper detonation limit")
    environment: Optional[EnvironmentSpecification] = Field(None, description="Environmental conditions")
    propagation_direction: Optional[str] = Field(None, description="Upward, downward, or horizontal")
    source_table: Optional[str] = Field(None, description="Source table reference")
    source_page: Optional[int] = Field(None, description="Source page number")
    standard_reference: Optional[str] = Field(None, description="Standard document reference")


class ExtractedSection(BaseModel):
    """A section extracted from a BOK standard with rich structured data."""
    model_config = {"extra": "ignore"}

    # Identification
    section_id: str = Field(..., description="Unique section identifier")
    gas_type: GasType = Field(..., description="H2, O2, or BOTH")
    content_type: ContentType = Field(..., description="Type of content")

    # Content
    title: str = Field(..., description="Section title")
    summary: Optional[str] = Field(None, description="AI-generated summary of section content")
    full_text: str = Field(..., description="Complete extracted text")
    key_points: List[str] = Field(default_factory=list, description="Key technical points extracted")

    # Structured data (populated based on content_type)
    material_records: List[MaterialCompatibilityRecord] = Field(default_factory=list)
    test_procedures: List[TestProcedureRecord] = Field(default_factory=list)
    flammability_limits: List[FlammabilityLimitRecord] = Field(default_factory=list)
    environment_specs: List[EnvironmentSpecification] = Field(default_factory=list)

    # Provenance
    source_document: str = Field(..., description="Source PDF filename")
    source_standard: Optional[str] = Field(None, description="Standard reference (e.g., 'NSS 1740.16')")
    page_numbers: List[int] = Field(default_factory=list, description="Page numbers covered")
    section_reference: Optional[str] = Field(None, description="Section number in document")

    # Metadata
    extraction_mode: str = Field(default="unknown", description="text, vision, or hybrid")
    extraction_confidence: float = Field(default=0.0, description="Confidence score 0-1")
    extraction_timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    # Search optimization
    tags: List[str] = Field(default_factory=list, description="Semantic tags for search")
    searchable_text: str = Field(default="", description="Optimized text for vector search")


# ============================================================================
# Extraction Prompts
# ============================================================================

SECTION_EXTRACTION_PROMPT = """You are an expert at extracting structured data from NASA safety standards.

Analyze this document and extract technical information into JSON format.

IMPORTANT: Return ONLY valid JSON. No explanation, no markdown, just the JSON object.

EXTRACTION RULES:
1. For MATERIAL COMPATIBILITY tables:
   - Extract EVERY material listed with its compatibility rating (A/B/C/D/X)
   - Include temperature and pressure conditions
   - Note any caveats or limitations

2. For TEST PROCEDURES:
   - Extract test number, name, and purpose
   - Include acceptance criteria
   - Note applicable materials and environments

3. For FLAMMABILITY LIMITS:
   - Extract LFL and UFL percentages
   - Include temperature and pressure conditions
   - Note propagation direction (upward/downward)

4. For ENVIRONMENT SPECIFICATIONS:
   - Extract BOTH minimum AND maximum temperature ranges (in F)
   - Extract BOTH minimum AND maximum pressure ranges (in psia)
   - If only a single value given, use as both min and max
   - Room temperature/ambient: use min=68, max=77
   - Cryogenic: LH2=-423F, LOX=-297F
   - Note phase (gas/liquid/solid/supercritical)

5. ALWAYS include source references:
   - Table numbers (e.g., "Table A5.1")
   - Section numbers (e.g., "Section 302")
   - Page numbers

6. For HYDROGEN (H2) EMBRITTLEMENT data:
   - Extract HEE (Hydrogen Environment Embrittlement) Index values
   - Map material rankings to compatibility_class:
     * "Negligible/Low embrittlement" or HEE Index > 0.9 -> A
     * "Slight embrittlement" or HEE Index 0.7-0.9 -> B
     * "Moderate embrittlement" or HEE Index 0.5-0.7 -> C
     * "Severe/High embrittlement" or HEE Index < 0.5 -> D
   - Include NTS (Notch Tensile Strength) ratios if available
   - Extract test pressures and temperatures for hydrogen environments

7. For OXYGEN (O2) COMPATIBILITY data:
   - Extract IGNITION SENSITIVITY ratings (high/medium/low)
   - Extract AUTOGENOUS IGNITION TEMPERATURE in F or C
   - Extract MECHANICAL IMPACT test results (e.g., "20 impacts no-reaction")
   - Extract CLEANING REQUIREMENTS (e.g., "per CGA G-4.1", "LOX clean")
   - Map material rankings to compatibility_class:
     * "Recommended" or "Excellent" -> A
     * "Acceptable with limitations" -> B
     * "Use with caution" -> C
     * "Not recommended" or "Ignition hazard" -> D
   - Note PROMOTED IGNITION or KINDLING CHAIN risks
   - Include oxygen concentration (% O2) conditions

Return ONLY valid JSON with this structure:
{
    "content_type": "material_compatibility|test_procedure|flammability_limit|environment_spec|safety_requirement|general_info|table_data|definition",
    "title": "Section title",
    "summary": "2-3 sentence technical summary",
    "key_points": ["key point 1", "key point 2"],
    "material_records": [
        {
            "material_name": "string",
            "material_family": "string or null",
            "compatibility_class": "A|B|C|D|X or null",
            "compatibility_notes": "string or null",
            "environment": {"environment_type": "GOX|LOX|GH2|LH2", "min_temperature_f": number, "max_temperature_f": number, "min_pressure_psia": number, "max_pressure_psia": number, "oxygen_concentration_pct": number or null},
            "source_table": "string or null",
            "source_section": "string or null",
            "embrittlement_index": "number or null (H2 only - HEE index 0-1)",
            "ignition_sensitivity": "high|medium|low or null (O2 only)",
            "autogenous_ignition_temp_f": "number or null (O2 only)",
            "cleaning_requirement": "string or null (O2 only - e.g., 'CGA G-4.1')",
            "mechanical_impact_result": "string or null (O2 only - e.g., '20/20 no-reaction')"
        }
    ],
    "test_procedures": [
        {
            "test_number": "Test 13A",
            "test_name": "string",
            "test_purpose": "string",
            "acceptance_criteria": "string",
            "standard_reference": "NASA-STD-6001B",
            "astm_reference": "ASTM G86 or null"
        }
    ],
    "flammability_limits": [
        {
            "oxidizer": "air|O2",
            "lower_flammability_limit_pct": number,
            "upper_flammability_limit_pct": number,
            "environment": {"min_pressure_psia": number, "max_pressure_psia": number, "min_temperature_f": number, "max_temperature_f": number},
            "propagation_direction": "upward|downward|horizontal",
            "source_table": "Table A2.2"
        }
    ],
    "environment_specs": [
        {
            "environment_type": "GOX|LOX|GH2|LH2|ambient",
            "min_temperature_f": number,
            "max_temperature_f": number,
            "min_pressure_psia": number,
            "max_pressure_psia": number,
            "oxygen_concentration_pct": number,
            "phase": "gas|liquid|solid"
        }
    ],
    "tags": ["semantic", "tags", "for", "search"]
}"""


# ============================================================================
# BOK Standards Extractor V6
# ============================================================================

class BOKStandardsExtractorV6:
    """
    Vision-first extractor for NASA H2/O2 safety standards.

    Uses same architecture as MUA Parser v6:
    - Vision mode: PDF → images → Claude Vision → structured JSON
    - Text mode: PDF → PyMuPDF text → Claude → structured JSON
    - Hybrid mode: Both, merged with vision preference

    Default: Haiku for cost efficiency on large BOK extraction.
    """

    def __init__(
        self,
        mode: ExtractionMode = "vision",
        use_bedrock: bool = None,
        bedrock_region: str = None,
        pages_per_section: int = 3,
        model: Literal["haiku", "sonnet"] = None,
    ):
        """
        Initialize extractor.

        Args:
            mode: Extraction mode - "text", "vision", or "hybrid"
            use_bedrock: Use AWS Bedrock (default: USE_BEDROCK env var)
            bedrock_region: Bedrock region
            pages_per_section: Number of pages to process per extraction call
            model: Model to use - "haiku" (default, cost efficient) or "sonnet" (higher quality)
        """
        self.mode = mode
        self.use_bedrock = use_bedrock if use_bedrock is not None else USE_BEDROCK
        self.bedrock_region = bedrock_region or BEDROCK_REGION
        self.pages_per_section = pages_per_section
        self.model_choice = model or DEFAULT_MODEL
        self.logger = logging.getLogger(self.__class__.__name__)

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
                    self.logger.error("anthropic package not installed")
                    raise
            else:
                try:
                    from anthropic import Anthropic
                    api_key = os.environ.get("ANTHROPIC_API_KEY")
                    if not api_key:
                        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
                    self._client = Anthropic(api_key=api_key)
                    # Use Haiku by default for cost efficiency
                    if self.model_choice == "haiku":
                        self._model = HAIKU_MODEL
                    else:
                        self._model = SONNET_MODEL_DIRECT
                    self.logger.info(f"Using direct Anthropic API with {self._model}")
                except ImportError:
                    self.logger.error("anthropic package not installed")
                    raise
        return self._client

    def _extract_text_from_pages(self, doc: fitz.Document, page_start: int, page_end: int) -> str:
        """Extract text from a range of pages."""
        full_text = ""
        for page_num in range(page_start, min(page_end, len(doc))):
            page = doc[page_num]
            page_text = page.get_text()
            full_text += f"\n--- Page {page_num + 1} ---\n{page_text}"
        return full_text

    def _detect_table_pages(self, doc: fitz.Document, page_start: int, page_end: int) -> bool:
        """
        Detect if page range likely contains data tables (use vision).

        Focused heuristics - avoid false positives on text-heavy pages:
        - Very high numeric ratio (> 15% digits) = clear data table
        - Tab characters with high line count = structured data
        - "Table X" explicit references with dense content
        """
        for page_num in range(page_start, min(page_end, len(doc))):
            page = doc[page_num]
            text = page.get_text()
            lines = text.splitlines()

            # Skip short pages
            if len(text) < 500:
                continue

            numeric_ratio = sum(1 for c in text if c.isdigit()) / max(len(text), 1)

            # Very high numeric content = clear data table (15%+)
            if numeric_ratio > 0.15 and len(lines) > 15:
                return True

            # Tab-separated data with many lines
            tab_count = text.count('\t')
            if tab_count > 20 and len(lines) > 20:
                return True

            # Explicit "Table X.Y" reference + dense numeric content
            text_lower = text.lower()
            import re
            if re.search(r'table\s+[a-z]?\d', text_lower) and numeric_ratio > 0.10:
                return True

        return False

    def _pages_to_images(self, doc: fitz.Document, page_start: int, page_end: int, dpi: int = 150) -> List[str]:
        """Convert page range to base64-encoded images."""
        images = []
        for page_num in range(page_start, min(page_end, len(doc))):
            page = doc[page_num]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes("png")
            b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
            images.append(b64)
            self.logger.debug(f"Converted page {page_num + 1} to image ({len(png_bytes)} bytes)")
        return images

    def _extract_via_text(self, doc: fitz.Document, page_start: int, page_end: int, gas_type: GasType) -> Dict[str, Any]:
        """Extract using text mode."""
        client = self._get_client()
        text = self._extract_text_from_pages(doc, page_start, page_end)

        self.logger.info(f"Text extraction pages {page_start + 1}-{page_end}: {len(text)} characters")

        response = client.messages.create(
            model=self._model,
            max_tokens=8192,
            messages=[
                {
                    "role": "user",
                    "content": f"Gas type context: {gas_type.value}\n\n{SECTION_EXTRACTION_PROMPT}\n\nDocument section:\n{text}"
                }
            ]
        )

        response_text = response.content[0].text.strip()
        return self._parse_json_response(response_text, "text", text)

    def _extract_via_vision(self, doc: fitz.Document, page_start: int, page_end: int, gas_type: GasType) -> Dict[str, Any]:
        """Extract using vision mode."""
        client = self._get_client()
        images = self._pages_to_images(doc, page_start, page_end)

        # Also extract text for full_text field
        raw_text = self._extract_text_from_pages(doc, page_start, page_end)

        self.logger.info(f"Vision extraction pages {page_start + 1}-{page_end}: {len(images)} images")

        content = []
        for i, img_b64 in enumerate(images):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": img_b64
                }
            })
            content.append({
                "type": "text",
                "text": f"[Page {page_start + i + 1}]"
            })

        content.append({
            "type": "text",
            "text": f"Gas type context: {gas_type.value}\n\n{SECTION_EXTRACTION_PROMPT}"
        })

        response = client.messages.create(
            model=self._model,
            max_tokens=8192,
            messages=[{"role": "user", "content": content}]
        )

        if not response.content:
            return {"extraction_mode": "vision", "parse_error": "Empty API response"}

        response_text = response.content[0].text.strip()
        return self._parse_json_response(response_text, "vision", raw_text)

    def _parse_json_response(self, response_text: str, mode: str, raw_text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response."""
        original_text = response_text

        # Handle markdown code blocks
        if "```" in response_text:
            start_idx = response_text.find("```")
            first_newline = response_text.find("\n", start_idx)
            if first_newline != -1:
                end_idx = response_text.rfind("```")
                if end_idx > first_newline:
                    response_text = response_text[first_newline + 1:end_idx].strip()

        # Try to find JSON object in response
        if not response_text.startswith("{"):
            # Look for first { and last }
            start = response_text.find("{")
            end = response_text.rfind("}")
            if start != -1 and end > start:
                response_text = response_text[start:end + 1]

        try:
            result = json.loads(response_text)
            result["extraction_mode"] = mode
            if raw_text:
                result["full_text"] = raw_text
            return result
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON: {e}")
            self.logger.debug(f"Response was: {original_text[:300]}")
            # Return a minimal valid result
            return {
                "extraction_mode": mode,
                "full_text": raw_text,
                "content_type": "general_info",
                "title": "Parse Error",
                "summary": original_text[:500] if original_text else "",
                "parse_error": str(e)
            }

    def _merge_results(self, text_result: Dict[str, Any], vision_result: Dict[str, Any]) -> Dict[str, Any]:
        """Merge text and vision results, preferring vision."""
        merged = {}
        all_keys = set(text_result.keys()) | set(vision_result.keys())
        skip_keys = {"extraction_mode", "full_text", "parse_error"}

        for key in all_keys:
            if key in skip_keys:
                continue

            text_val = text_result.get(key)
            vision_val = vision_result.get(key)

            if isinstance(text_val, list) or isinstance(vision_val, list):
                text_list = text_val if isinstance(text_val, list) else []
                vision_list = vision_val if isinstance(vision_val, list) else []
                merged[key] = vision_list if len(vision_list) >= len(text_list) else text_list
            elif vision_val is not None:
                merged[key] = vision_val
            elif text_val is not None:
                merged[key] = text_val
            else:
                merged[key] = None

        merged["extraction_mode"] = "hybrid"
        merged["full_text"] = text_result.get("full_text", "")
        return merged

    def _normalize_environment(self, env: Dict[str, Any]) -> Dict[str, Any]:
        """Apply sensible defaults for missing min/max values."""
        if not env:
            return env

        env_type = (env.get("environment_type") or "").upper()

        # Temperature defaults
        if env.get("max_temperature_f") is not None and env.get("min_temperature_f") is None:
            if "LH2" in env_type:
                env["min_temperature_f"] = -423.0
            elif "LOX" in env_type:
                env["min_temperature_f"] = -297.0
            elif "GH2" in env_type or "GOX" in env_type:
                env["min_temperature_f"] = -40.0
            else:
                env["min_temperature_f"] = 68.0  # Room temperature

        # If min exists but max doesn't
        if env.get("min_temperature_f") is not None and env.get("max_temperature_f") is None:
            env["max_temperature_f"] = env["min_temperature_f"]

        # Pressure defaults
        if env.get("max_pressure_psia") is not None and env.get("min_pressure_psia") is None:
            env["min_pressure_psia"] = 14.7  # Atmospheric

        if env.get("min_pressure_psia") is not None and env.get("max_pressure_psia") is None:
            env["max_pressure_psia"] = env["min_pressure_psia"]

        return env

    def _normalize_result_environments(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize all environment specs in extraction result."""
        # Normalize material record environments
        for rec in result.get("material_records", []):
            if "environment" in rec and rec["environment"]:
                rec["environment"] = self._normalize_environment(rec["environment"])

        # Normalize environment specs
        normalized_specs = []
        for spec in result.get("environment_specs", []):
            normalized_specs.append(self._normalize_environment(spec))
        result["environment_specs"] = normalized_specs

        # Normalize flammability limit environments
        for lim in result.get("flammability_limits", []):
            if "environment" in lim and lim["environment"]:
                lim["environment"] = self._normalize_environment(lim["environment"])

        return result

    def extract_pdf(self, pdf_path: Path, gas_type: GasType) -> List[ExtractedSection]:
        """
        Extract structured data from a BOK PDF.

        Args:
            pdf_path: Path to PDF file
            gas_type: H2 or O2 context for extraction

        Returns:
            List of ExtractedSection objects
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        self.logger.info(f"Extracting {pdf_path.name} ({gas_type.value}) with mode={self.mode}")

        doc = fitz.open(pdf_path)
        sections = []
        total_pages = len(doc)

        # Process in chunks
        for page_start in range(0, total_pages, self.pages_per_section):
            page_end = min(page_start + self.pages_per_section, total_pages)

            try:
                if self.mode == "text":
                    result = self._extract_via_text(doc, page_start, page_end, gas_type)
                elif self.mode == "vision":
                    result = self._extract_via_vision(doc, page_start, page_end, gas_type)
                elif self.mode == "smart":
                    # Smart mode: text first, vision only for detected tables
                    result = self._extract_via_text(doc, page_start, page_end, gas_type)
                    if self._detect_table_pages(doc, page_start, page_end):
                        self.logger.info(f"Tables detected pages {page_start + 1}-{page_end}, adding vision")
                        vision_result = self._extract_via_vision(doc, page_start, page_end, gas_type)
                        result = self._merge_results(result, vision_result)
                else:  # hybrid - always both
                    text_result = self._extract_via_text(doc, page_start, page_end, gas_type)
                    vision_result = self._extract_via_vision(doc, page_start, page_end, gas_type)
                    result = self._merge_results(text_result, vision_result)

                # Normalize environment min/max ranges
                result = self._normalize_result_environments(result)

                # Build ExtractedSection
                section = self._build_section(
                    result=result,
                    pdf_path=pdf_path,
                    gas_type=gas_type,
                    page_start=page_start,
                    page_end=page_end,
                )
                sections.append(section)

                self.logger.info(f"Extracted pages {page_start + 1}-{page_end}: {section.content_type.value}")

            except Exception as e:
                self.logger.error(f"Failed to extract pages {page_start + 1}-{page_end}: {e}")
                continue

        doc.close()
        return sections

    def _build_section(
        self,
        result: Dict[str, Any],
        pdf_path: Path,
        gas_type: GasType,
        page_start: int,
        page_end: int,
    ) -> ExtractedSection:
        """Build ExtractedSection from extraction result."""
        # Determine content type
        content_type_str = result.get("content_type", "general_info")
        try:
            content_type = ContentType(content_type_str)
        except ValueError:
            content_type = ContentType.GENERAL_INFO

        # Build material records
        material_records = []
        for rec in result.get("material_records", []):
            try:
                material_records.append(MaterialCompatibilityRecord(
                    material_name=rec.get("material_name", "Unknown"),
                    gas_type=gas_type,
                    **{k: v for k, v in rec.items() if k != "material_name"}
                ))
            except Exception as e:
                self.logger.debug(f"Skipping invalid material record: {e}")

        # Build test procedures
        test_procedures = []
        for proc in result.get("test_procedures", []):
            try:
                test_procedures.append(TestProcedureRecord(
                    test_name=proc.get("test_name", "Unknown"),
                    **{k: v for k, v in proc.items() if k != "test_name"}
                ))
            except Exception as e:
                self.logger.debug(f"Skipping invalid test procedure: {e}")

        # Build flammability limits
        flammability_limits = []
        for lim in result.get("flammability_limits", []):
            try:
                flammability_limits.append(FlammabilityLimitRecord(
                    gas_type=gas_type,
                    **lim
                ))
            except Exception as e:
                self.logger.debug(f"Skipping invalid flammability limit: {e}")

        # Build environment specs
        environment_specs = []
        for spec in result.get("environment_specs", []):
            try:
                environment_specs.append(EnvironmentSpecification(**spec))
            except Exception as e:
                self.logger.debug(f"Skipping invalid environment spec: {e}")

        # Build section ID
        section_id = f"{gas_type.value}BOK:{pdf_path.stem}_p{page_start + 1}-{page_end}"

        # Build searchable text for vector search
        key_points = result.get("key_points", [])
        searchable_parts = [
            result.get("title", ""),
            result.get("summary", ""),
            " ".join(key_points),
        ]
        for rec in material_records:
            searchable_parts.append(f"{rec.material_name} {rec.compatibility_class or ''} {gas_type.value}")
        searchable_text = " ".join(filter(None, searchable_parts))

        return ExtractedSection(
            section_id=section_id,
            gas_type=gas_type,
            content_type=content_type,
            title=result.get("title", f"Pages {page_start + 1}-{page_end}"),
            summary=result.get("summary"),
            full_text=result.get("full_text", ""),
            key_points=key_points,
            material_records=material_records,
            test_procedures=test_procedures,
            flammability_limits=flammability_limits,
            environment_specs=environment_specs,
            source_document=pdf_path.name,
            source_standard=self._infer_standard(pdf_path.name),
            page_numbers=list(range(page_start + 1, page_end + 1)),
            extraction_mode=result.get("extraction_mode", "unknown"),
            extraction_confidence=self._calculate_confidence(result),
            tags=result.get("tags", []) + [gas_type.value.lower(), "bok"],
            searchable_text=searchable_text,
        )

    def _infer_standard(self, filename: str) -> Optional[str]:
        """Infer standard reference from filename."""
        filename_lower = filename.lower()
        if "6001" in filename_lower:
            return "NASA-STD-6001B"
        if "6016" in filename_lower:
            return "NASA-STD-6016"
        if "1740.16" in filename_lower or "19970033338" in filename_lower:
            return "NSS 1740.16"
        if "sand2012" in filename_lower:
            return "SAND2012-7321"
        if "ksc" in filename_lower:
            return "KSC-KTI-5210C"
        return None

    def _calculate_confidence(self, result: Dict[str, Any]) -> float:
        """Calculate extraction confidence score."""
        score = 0.0
        if result.get("title"):
            score += 0.1
        if result.get("summary"):
            score += 0.15
        if result.get("key_points"):
            score += 0.1
        if result.get("material_records"):
            score += 0.15
        if result.get("test_procedures"):
            score += 0.15
        if result.get("flammability_limits"):
            score += 0.1
        if result.get("environment_specs"):
            score += 0.15
        if result.get("tags"):
            score += 0.1
        return min(score, 1.0)


# ============================================================================
# Convenience Functions
# ============================================================================

def extract_bok_pdf_v6(
    pdf_path: Path,
    gas_type: GasType,
    mode: ExtractionMode = "hybrid",
    use_bedrock: bool = None,
    model: Literal["haiku", "sonnet"] = "haiku",
) -> List[ExtractedSection]:
    """
    Extract structured data from a BOK PDF.

    Args:
        pdf_path: Path to PDF file
        gas_type: H2 or O2 context
        mode: Extraction mode
        use_bedrock: Use AWS Bedrock
        model: Model to use (haiku or sonnet)

    Returns:
        List of ExtractedSection objects
    """
    extractor = BOKStandardsExtractorV6(mode=mode, use_bedrock=use_bedrock, model=model)
    return extractor.extract_pdf(pdf_path, gas_type)


def _get_processed_pdfs(json_path: Path) -> set:
    """Get set of PDF names already processed (from section_ids)."""
    if not json_path.exists():
        return set()
    try:
        data = json.loads(json_path.read_text())
        # section_id format: "H2BOK:filename_p1-3" -> extract filename
        processed = set()
        for section in data:
            sid = section.get("section_id", "")
            if ":" in sid:
                # H2BOK:filename_p1-3 -> filename
                name_part = sid.split(":")[1].rsplit("_p", 1)[0]
                processed.add(name_part)
        return processed
    except Exception:
        return set()


def rebuild_bok_indices(
    mode: ExtractionMode = "vision",
    use_bedrock: bool = False,
    output_dir: Path = OUTPUT_PATH,
    model: Literal["haiku", "sonnet"] = "haiku",
    continue_from_checkpoint: bool = False,
) -> Dict[str, int]:
    """
    Rebuild all BOK indices from source PDFs.

    Args:
        mode: Extraction mode (default: vision for best table extraction)
        use_bedrock: Use AWS Bedrock (default: False - uses direct Anthropic API)
        output_dir: Output directory for indices
        model: Model to use (default: haiku for cost efficiency)
        continue_from_checkpoint: If True, skip already-processed PDFs

    Returns:
        Dict with counts of extracted sections per gas type
    """
    extractor = BOKStandardsExtractorV6(mode=mode, use_bedrock=use_bedrock, model=model)
    counts = {"H2": 0, "O2": 0}

    # Process H2 BOK
    if H2_BOK_PATH.exists():
        h2_output = output_dir / "h2_bok_v6"
        h2_output.mkdir(parents=True, exist_ok=True)
        h2_json_path = h2_output / "h2_bok_sections_v6.json"

        # Load existing sections if continuing (keep as dicts for simplicity)
        h2_sections_data = []  # List of dicts
        processed_pdfs = set()
        if continue_from_checkpoint and h2_json_path.exists():
            try:
                h2_sections_data = json.loads(h2_json_path.read_text())
                processed_pdfs = _get_processed_pdfs(h2_json_path)
                logger.info(f"Continuing from checkpoint: {len(h2_sections_data)} sections, {len(processed_pdfs)} PDFs already processed")
            except Exception as e:
                logger.warning(f"Could not load checkpoint: {e}, starting fresh")

        for pdf_file in H2_BOK_PATH.glob("*.pdf"):
            # Skip already-processed PDFs
            pdf_stem = pdf_file.stem
            if pdf_stem in processed_pdfs:
                logger.info(f"Skipping H2 BOK (already processed): {pdf_file.name}")
                continue

            logger.info(f"Processing H2 BOK: {pdf_file.name}")
            try:
                sections = extractor.extract_pdf(pdf_file, GasType.H2)
                # Convert new sections to dicts and append
                h2_sections_data.extend([s.model_dump() for s in sections])

                # Save after each PDF - never lose progress
                with open(h2_json_path, "w") as f:
                    json.dump(h2_sections_data, f, indent=2, default=str)
                logger.info(f"Saved {len(h2_sections_data)} H2 sections (after {pdf_file.name})")

            except Exception as e:
                logger.error(f"Failed to process {pdf_file.name}: {e}")

        counts["H2"] = len(h2_sections_data)

    # Process O2 BOK
    if O2_BOK_PATH.exists():
        o2_output = output_dir / "o2_bok_v6"
        o2_output.mkdir(parents=True, exist_ok=True)
        o2_json_path = o2_output / "o2_bok_sections_v6.json"

        # Load existing sections if continuing (keep as dicts for simplicity)
        o2_sections_data = []  # List of dicts
        processed_pdfs = set()
        if continue_from_checkpoint and o2_json_path.exists():
            try:
                o2_sections_data = json.loads(o2_json_path.read_text())
                processed_pdfs = _get_processed_pdfs(o2_json_path)
                logger.info(f"Continuing from checkpoint: {len(o2_sections_data)} sections, {len(processed_pdfs)} PDFs already processed")
            except Exception as e:
                logger.warning(f"Could not load checkpoint: {e}, starting fresh")

        for pdf_file in O2_BOK_PATH.glob("*.pdf"):
            # Skip already-processed PDFs
            pdf_stem = pdf_file.stem
            if pdf_stem in processed_pdfs:
                logger.info(f"Skipping O2 BOK (already processed): {pdf_file.name}")
                continue

            logger.info(f"Processing O2 BOK: {pdf_file.name}")
            try:
                sections = extractor.extract_pdf(pdf_file, GasType.O2)
                # Convert new sections to dicts and append
                o2_sections_data.extend([s.model_dump() for s in sections])

                # Save after each PDF - never lose progress
                with open(o2_json_path, "w") as f:
                    json.dump(o2_sections_data, f, indent=2, default=str)
                logger.info(f"Saved {len(o2_sections_data)} O2 sections (after {pdf_file.name})")

            except Exception as e:
                logger.error(f"Failed to process {pdf_file.name}: {e}")

        counts["O2"] = len(o2_sections_data)

    return counts


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    # SECURITY: API key must be set in environment
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY environment variable required")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="BOK Standards Extractor V6")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild all BOK indices (starts fresh)")
    parser.add_argument("--continue", dest="continue_run", action="store_true", help="Continue from checkpoint (skip already-processed PDFs)")
    parser.add_argument("--pdf", type=str, help="Extract single PDF")
    parser.add_argument("--gas", choices=["H2", "O2"], help="Gas type for single PDF")
    parser.add_argument(
        "--mode",
        choices=["text", "vision", "hybrid", "smart"],
        default="smart",
        help="Extraction mode (default: smart = text + vision for tables only)"
    )
    parser.add_argument("--bedrock", action="store_true", help="Use Bedrock API (default: direct Anthropic API)")
    parser.add_argument(
        "--model",
        choices=["haiku", "sonnet"],
        default="haiku",
        help="Model to use (default: haiku for cost efficiency, sonnet for quality)"
    )

    args = parser.parse_args()

    if args.rebuild or args.continue_run:
        counts = rebuild_bok_indices(
            mode=args.mode,
            use_bedrock=args.bedrock,
            model=args.model,
            continue_from_checkpoint=args.continue_run
        )
        print(f"{'Continued' if args.continue_run else 'Rebuilt'} BOK indices: {counts}")

    elif args.pdf:
        if not args.gas:
            print("Error: --gas required with --pdf")
            exit(1)

        sections = extract_bok_pdf_v6(
            Path(args.pdf),
            GasType(args.gas),
            mode=args.mode,
            use_bedrock=args.bedrock,
            model=args.model,
        )

        print(f"\nExtracted {len(sections)} sections from {args.pdf}")
        for section in sections:
            print(f"\n{'=' * 60}")
            print(f"Section: {section.section_id}")
            print(f"Type: {section.content_type.value}")
            print(f"Title: {section.title}")
            print(f"Pages: {section.page_numbers}")
            print(f"Materials: {len(section.material_records)}")
            print(f"Tests: {len(section.test_procedures)}")
            print(f"Confidence: {section.extraction_confidence:.0%}")

    else:
        parser.print_help()
