#!/usr/bin/env python3
"""
Module: MAPTIS PDF Extractor
Purpose: Vision-first extraction of MAPTIS material/test data from PDF exports

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016, SWE-032
Safety Critical: False
"""

from __future__ import annotations

import os
import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Configuration
USE_BEDROCK = os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-gov-west-1")
SONNET_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_MODEL_DIRECT = "claude-sonnet-4-5-20250929"

ExtractionMode = Literal["text", "vision", "hybrid"]


# ============================================================================
# Pydantic Models - Match silver_report_rows Schema
# ============================================================================

class MAPTISMaterialRecord(BaseModel):
    """Extracted material record matching silver_report_rows schema."""
    material_key: str = Field(..., description="5-digit material code (e.g., '01242')")
    matl_designation: str = Field(..., description="Material designation/name")
    matl_materialcode: Optional[str] = Field(None, description="Material code")
    matl_spec1: Optional[str] = Field(None, description="Primary specification")
    matl_manufacturer: Optional[str] = Field(None, description="Manufacturer name")
    matl_tradename: Optional[str] = Field(None, description="Trade name")


class MAPTISFlammabilityTest(BaseModel):
    """Extracted flammability test record."""
    material_key: str
    flam_rating: Optional[str] = Field(None, description="A, B, C, D, X, or U")
    flam_gasname: Optional[str] = Field(None, description="Test gas (e.g., OXYGEN, NITROGEN)")
    flam_originalpercentoxygen: Optional[float] = Field(None, description="O2 percentage")
    flam_testpressure: Optional[float] = Field(None, description="Test pressure psia")
    flam_reportnumber: Optional[str] = Field(None, description="Test report number")


class MAPTISPneumaticTest(BaseModel):
    """Extracted pneumatic impact test record."""
    material_key: str
    pneu_rating: Optional[str] = Field(None, description="A, B, C, D, X, or U")
    pneu_gasname: Optional[str] = Field(None, description="Test gas")
    pneu_testpressure: Optional[float] = Field(None, description="Test pressure psia")
    pneu_reportnumber: Optional[str] = Field(None, description="Test report number")


class ExtractionResult(BaseModel):
    """Result of PDF extraction."""
    materials: List[MAPTISMaterialRecord] = Field(default_factory=list)
    flammability_tests: List[MAPTISFlammabilityTest] = Field(default_factory=list)
    pneumatic_tests: List[MAPTISPneumaticTest] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    source_file: str = ""


# ============================================================================
# Extraction Prompts
# ============================================================================

MATERIAL_TABLE_PROMPT = """Extract ALL materials from this MAPTIS material family report PDF.

This is a NASA MAPTIS (Materials and Processes Technical Information System) export.
Look for tables with columns like: Material Code, Designation, Specification, Manufacturer, Trade Name.

For each row in the table, extract:
- material_key: The 5-digit material code (e.g., "01242", "05094", "05276"). Look for numeric codes.
- matl_designation: Full material name/designation (e.g., "FLUOROSILICONE RUBBER", "SILICONE RUBBER, FLUOROSILICONE TYPE")
- matl_materialcode: Same as material_key if shown separately
- matl_spec1: Specification number (e.g., MIL-DTL-25988, AMS-xxxx, ASTM-xxxx)
- matl_manufacturer: Manufacturer name if present
- matl_tradename: Trade name if present

Extract EVERY row from ALL pages. Do not skip any materials.

Return ONLY valid JSON array (no explanation, no markdown):
[
  {"material_key": "01242", "matl_designation": "FLUOROSILICONE RUBBER", "matl_spec1": "MIL-DTL-25988", "matl_manufacturer": null, "matl_tradename": null},
  ...
]"""

FLAMMABILITY_TEST_PROMPT = """Extract ALL flammability test records from this MAPTIS report PDF.

This is a NASA MAPTIS flammability test report. Look for tables with test data including:
- Material codes
- Rating letters (A, B, C, D, X, U)
- Test gas (OXYGEN, NITROGEN, AIR, GOX, LOX)
- Oxygen percentage
- Pressure values

For each test row, extract:
- material_key: The 5-digit material code (e.g., "01242")
- flam_rating: Rating letter (A, B, C, D, X, or U)
- flam_gasname: Test gas environment (e.g., "OXYGEN", "NITROGEN", "AIR", "GOX", "LOX")
- flam_originalpercentoxygen: Oxygen percentage as number (e.g., 99.7, 23.5, 100.0)
- flam_testpressure: Test pressure in psia as number
- flam_reportnumber: Test report reference number (e.g., "WSTF# 123456")

Extract EVERY test from ALL pages. Do not skip any tests.

Return ONLY valid JSON array (no explanation, no markdown):
[
  {"material_key": "01242", "flam_rating": "C", "flam_gasname": "OXYGEN", "flam_originalpercentoxygen": 99.7, "flam_testpressure": 14.7, "flam_reportnumber": "WSTF# 12345"},
  ...
]"""

PNEUMATIC_TEST_PROMPT = """Extract ALL pneumatic impact test records from this MAPTIS report PDF.

This is a NASA MAPTIS pneumatic impact test report. Look for tables with test data including:
- Material codes
- Rating letters (A, B, C, D, X, U)
- Test gas
- Pressure values

For each test row, extract:
- material_key: The 5-digit material code
- pneu_rating: Rating letter (A, B, C, D, X, or U)
- pneu_gasname: Test gas environment
- pneu_testpressure: Test pressure in psia
- pneu_reportnumber: Test report reference number

Extract EVERY test from ALL pages. Do not skip any tests.

Return ONLY valid JSON array (no explanation, no markdown):
[
  {"material_key": "01242", "pneu_rating": "A", "pneu_gasname": "OXYGEN", "pneu_testpressure": 10000, "pneu_reportnumber": "WSTF# 67890"},
  ...
]"""


# ============================================================================
# Main Extractor Class
# ============================================================================

class MAPTISPDFExtractor:
    """
    Vision-first MAPTIS PDF extractor following MUAParserV6 pattern.

    Supports three report types:
    - Material family reports (material list)
    - Flammability test reports
    - Pneumatic impact test reports
    """

    def __init__(
        self,
        mode: ExtractionMode = "vision",
        use_bedrock: bool = None,
        bedrock_region: str = None,
    ):
        """
        Initialize extractor.

        Args:
            mode: Extraction mode - "vision" recommended for MAPTIS tables
            use_bedrock: Use AWS Bedrock (default: USE_BEDROCK env var)
            bedrock_region: Bedrock region (default: BEDROCK_REGION env var)
        """
        self.mode = mode
        self.use_bedrock = use_bedrock if use_bedrock is not None else USE_BEDROCK
        self.bedrock_region = bedrock_region or BEDROCK_REGION
        self._client = None
        self._model = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _get_client(self):
        """Lazy-load Anthropic client (same pattern as MUAParserV6)."""
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
                    self._client = Anthropic()
                    self._model = SONNET_MODEL_DIRECT
                    self.logger.info("Using direct Anthropic API")
                except ImportError:
                    self.logger.error("anthropic package not installed")
                    raise
        return self._client

    def _load_pdf_as_base64(self, pdf_path: Path) -> str:
        """Load PDF as base64 for Claude document input."""
        return base64.standard_b64encode(pdf_path.read_bytes()).decode()

    def _extract_via_vision(self, pdf_path: Path, prompt: str) -> List[Dict]:
        """
        Extract using vision mode (same pattern as MUAParserV6).

        Args:
            pdf_path: Path to PDF file
            prompt: Extraction prompt

        Returns:
            List of extracted records as dicts
        """
        client = self._get_client()
        pdf_data = self._load_pdf_as_base64(pdf_path)

        self.logger.info(f"Extracting from {pdf_path.name} via vision...")

        import contextlib
        from mira.core.bedrock_semaphore import bedrock_limiter_sync

        limiter = bedrock_limiter_sync("vision") if self.use_bedrock else contextlib.nullcontext()
        with limiter:
            response = client.messages.create(
                model=self._model,
                max_tokens=16384,  # Large for multi-page tables
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all data from this MAPTIS report. Be thorough - extract every row from every page."},
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_data
                            }
                        },
                        {"type": "text", "text": prompt}
                    ]
                }]
        )

        # Parse JSON response (same cleanup as MUAParserV6)
        if not response.content:
            self.logger.error("Empty response from API")
            return []

        response_text = response.content[0].text.strip()

        # Handle markdown code blocks
        if "```" in response_text:
            start = response_text.find("```")
            newline = response_text.find("\n", start)
            end = response_text.rfind("```")
            if newline != -1 and end > newline:
                response_text = response_text[newline + 1:end].strip()

        try:
            result = json.loads(response_text)
            self.logger.info(f"Extracted {len(result)} records from {pdf_path.name}")
            return result
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON: {e}")
            self.logger.debug(f"Response was: {response_text[:500]}")
            return []

    def extract_materials(self, pdf_path: Path) -> List[MAPTISMaterialRecord]:
        """
        Extract material records from family report PDF.

        Args:
            pdf_path: Path to material family report PDF

        Returns:
            List of MAPTISMaterialRecord
        """
        pdf_path = Path(pdf_path)
        raw = self._extract_via_vision(pdf_path, MATERIAL_TABLE_PROMPT)
        records = []
        for r in raw:
            try:
                records.append(MAPTISMaterialRecord(**r))
            except Exception as e:
                self.logger.warning(f"Failed to parse material record: {e}")
        return records

    def extract_flammability_tests(self, pdf_path: Path) -> List[MAPTISFlammabilityTest]:
        """
        Extract flammability test records from test report PDF.

        Args:
            pdf_path: Path to flammability test report PDF

        Returns:
            List of MAPTISFlammabilityTest
        """
        pdf_path = Path(pdf_path)
        raw = self._extract_via_vision(pdf_path, FLAMMABILITY_TEST_PROMPT)
        records = []
        for r in raw:
            try:
                records.append(MAPTISFlammabilityTest(**r))
            except Exception as e:
                self.logger.warning(f"Failed to parse flam test record: {e}")
        return records

    def extract_pneumatic_tests(self, pdf_path: Path) -> List[MAPTISPneumaticTest]:
        """
        Extract pneumatic impact test records from test report PDF.

        Args:
            pdf_path: Path to pneumatic test report PDF

        Returns:
            List of MAPTISPneumaticTest
        """
        pdf_path = Path(pdf_path)
        raw = self._extract_via_vision(pdf_path, PNEUMATIC_TEST_PROMPT)
        records = []
        for r in raw:
            try:
                records.append(MAPTISPneumaticTest(**r))
            except Exception as e:
                self.logger.warning(f"Failed to parse pneu test record: {e}")
        return records

    def extract_all(
        self,
        materials_pdf: Path = None,
        flam_pdf: Path = None,
        pneu_pdf: Path = None,
    ) -> ExtractionResult:
        """
        Extract from multiple PDFs in one call.

        Args:
            materials_pdf: Path to material family report PDF
            flam_pdf: Path to flammability test report PDF
            pneu_pdf: Path to pneumatic test report PDF

        Returns:
            ExtractionResult with all extracted data
        """
        result = ExtractionResult()

        if materials_pdf:
            try:
                result.materials = self.extract_materials(materials_pdf)
                result.source_file = str(materials_pdf)
            except Exception as e:
                result.errors.append(f"Materials extraction failed: {e}")

        if flam_pdf:
            try:
                result.flammability_tests = self.extract_flammability_tests(flam_pdf)
            except Exception as e:
                result.errors.append(f"Flammability extraction failed: {e}")

        if pneu_pdf:
            try:
                result.pneumatic_tests = self.extract_pneumatic_tests(pneu_pdf)
            except Exception as e:
                result.errors.append(f"Pneumatic extraction failed: {e}")

        return result


# ============================================================================
# Convenience Function
# ============================================================================

def extract_maptis_pdf(
    pdf_path: Path | str,
    report_type: Literal["materials", "flammability", "pneumatic"],
    use_bedrock: bool = None,
) -> List[Dict]:
    """
    Extract data from a single MAPTIS PDF.

    Args:
        pdf_path: Path to PDF file
        report_type: Type of report
        use_bedrock: Use AWS Bedrock API

    Returns:
        List of extracted records as dicts
    """
    extractor = MAPTISPDFExtractor(use_bedrock=use_bedrock)

    if report_type == "materials":
        records = extractor.extract_materials(Path(pdf_path))
    elif report_type == "flammability":
        records = extractor.extract_flammability_tests(Path(pdf_path))
    elif report_type == "pneumatic":
        records = extractor.extract_pneumatic_tests(Path(pdf_path))
    else:
        raise ValueError(f"Unknown report type: {report_type}")

    return [r.model_dump() for r in records]


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="MAPTIS PDF Extractor")
    parser.add_argument("pdf_path", type=str, help="Path to MAPTIS PDF")
    parser.add_argument(
        "--type",
        choices=["materials", "flammability", "pneumatic"],
        required=True,
        help="Report type"
    )
    parser.add_argument(
        "--bedrock",
        action="store_true",
        help="Use AWS Bedrock instead of direct API"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file (default: stdout)"
    )

    args = parser.parse_args()

    pdf_file = Path(args.pdf_path)
    if not pdf_file.exists():
        print(f"File not found: {pdf_file}")
        sys.exit(1)

    # Extract
    records = extract_maptis_pdf(
        pdf_file,
        report_type=args.type,
        use_bedrock=args.bedrock
    )

    # Output
    output_json = json.dumps(records, indent=2)

    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Wrote {len(records)} records to {args.output}")
    else:
        print(output_json)
