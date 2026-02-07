#!/usr/bin/env python3
"""
Module: Standards Extractor
Purpose: ATHENA Standards Extractor.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import anthropic
import pdfplumber

from athena.interpreters.models.requirement import (
    RequirementRecord,
    RequirementType,
)

__all__ = ["StandardsExtractor", "StandardsExtractionResult"]
__safety_critical__ = True

logger = logging.getLogger(__name__)


STANDARDS_EXTRACTION_PROMPT = """Extract requirements from this standards document page as JSON.

OUTPUT: Return ONLY a JSON array. No explanations, no markdown, no text before or after.

If NO requirements found, return exactly: []

For EACH requirement with "shall", "must", "required", or "prohibited":
{
  "section": "4.2.3.1",
  "requirement_type": "testing|cleaning|prohibition|approval|documentation|inspection|handling|general",
  "material_category": "Category A metals" or null,
  "environment": "GOX" or null,
  "pressure_threshold": ">200 psi" or null,
  "temperature_threshold": "<-150°F" or null,
  "requirement_text": "Materials shall be tested per ASTM G124",
  "test_method": "ASTM G124" or null,
  "cleaning_spec": "ASTM G93 Level 100A" or null,
  "full_paragraph": "Complete original text"
}

IMPORTANT:
- Return ONLY the JSON array
- Skip TOC, references, definitions - only extract SHALL/MUST statements
- If page has no requirements, return []
"""


class StandardsExtractionResult:
    """Result of extracting requirements from a standards document."""

    def __init__(self, document_id: str, source_path: str):
        self.document_id = document_id
        self.source_path = source_path
        self.source_hash: str = ""
        self.extraction_timestamp = datetime.now().isoformat()

        self.requirements: list[RequirementRecord] = []
        self.pages_processed: int = 0
        self.pages_with_requirements: int = 0

        self.api_calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0

        self.errors: list[str] = []

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate API cost (Sonnet pricing)."""
        # Sonnet: $3/MTok input, $15/MTok output
        input_cost = self.input_tokens * 3.00 / 1_000_000
        output_cost = self.output_tokens * 15.00 / 1_000_000
        return round(input_cost + output_cost, 4)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "document_id": self.document_id,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "extraction_timestamp": self.extraction_timestamp,
            "requirements": [r.model_dump() for r in self.requirements],
            "pages_processed": self.pages_processed,
            "pages_with_requirements": self.pages_with_requirements,
            "api_calls": self.api_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "errors": self.errors,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), indent=indent)


class StandardsExtractor:
    """
    Extracts RequirementRecords from standards documents.

    Uses vision-based extraction to process each page and identify
    structured requirements for materials compatibility assessment.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        render_dpi: int = 150,
        skip_pages: Optional[list[int]] = None,
    ):
        """
        Initialize the standards extractor.

        Args:
            model: Claude model for vision extraction
            render_dpi: DPI for rendering PDF pages
            skip_pages: Page numbers to skip (e.g., TOC, index)
        """
        self.model = model
        self.render_dpi = render_dpi
        self.skip_pages = set(skip_pages or [])
        self.client = anthropic.Anthropic()
        self.logger = logging.getLogger(self.__class__.__name__)

    def extract_pdf(
        self,
        pdf_path: Union[str, Path],
        document_id: Optional[str] = None,
        page_range: Optional[tuple[int, int]] = None,
    ) -> StandardsExtractionResult:
        """
        Extract requirements from a standards PDF.

        Args:
            pdf_path: Path to PDF file
            document_id: Document identifier (e.g., "NASA-STD-6016")
            page_range: Optional (start, end) page range (1-indexed)

        Returns:
            StandardsExtractionResult with all requirements
        """
        pdf_path = Path(pdf_path)

        # Derive document ID from filename if not provided
        if not document_id:
            document_id = self._derive_document_id(pdf_path)

        self.logger.info(f"Extracting standards: {document_id} from {pdf_path.name}")

        result = StandardsExtractionResult(
            document_id=document_id,
            source_path=str(pdf_path),
        )
        result.source_hash = self._compute_file_hash(pdf_path)

        requirement_counter = 0

        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Determine page range
                start_page = page_range[0] if page_range else 1
                end_page = page_range[1] if page_range else len(pdf.pages)
                end_page = min(end_page, len(pdf.pages))

                for page_num in range(start_page, end_page + 1):
                    if page_num in self.skip_pages:
                        self.logger.debug(f"Skipping page {page_num}")
                        continue

                    page = pdf.pages[page_num - 1]
                    result.pages_processed += 1

                    # Extract requirements from this page
                    try:
                        page_reqs = self._extract_page(
                            page=page,
                            page_num=page_num,
                            document_id=document_id,
                            result=result,
                            counter_start=requirement_counter,
                        )

                        if page_reqs:
                            result.pages_with_requirements += 1
                            requirement_counter += len(page_reqs)
                            result.requirements.extend(page_reqs)
                            self.logger.info(
                                f"  Page {page_num}: {len(page_reqs)} requirements"
                            )

                    except Exception as e:
                        self.logger.error(f"Failed page {page_num}: {e}")
                        result.errors.append(f"Page {page_num}: {e}")

        except Exception as e:
            self.logger.error(f"Failed to process {pdf_path.name}: {e}")
            result.errors.append(str(e))

        self.logger.info(
            f"  -> {len(result.requirements)} requirements extracted, "
            f"{result.pages_processed} pages, "
            f"${result.estimated_cost_usd:.4f}"
        )

        return result

    def _extract_page(
        self,
        page,
        page_num: int,
        document_id: str,
        result: StandardsExtractionResult,
        counter_start: int,
    ) -> list[RequirementRecord]:
        """
        Extract requirements from a single page.

        Args:
            page: pdfplumber page object
            page_num: Page number (1-indexed)
            document_id: Document identifier
            result: Result object to update with token counts
            counter_start: Starting counter for requirement IDs

        Returns:
            List of RequirementRecords from this page
        """
        # Render page to image
        img_bytes = self._render_page(page)
        img_base64 = base64.standard_b64encode(img_bytes).decode("utf-8")

        # Call Claude vision
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": STANDARDS_EXTRACTION_PROMPT,
                        },
                    ],
                }
            ],
        )

        # Update token counts
        result.api_calls += 1
        result.input_tokens += response.usage.input_tokens
        result.output_tokens += response.usage.output_tokens

        # Parse response
        content = response.content[0].text

        # Debug: log raw response
        self.logger.debug(f"Page {page_num} raw response: {content[:500]}")

        # Strip markdown fences if present
        if "```" in content:
            content = re.sub(r"```json?\n?", "", content)
            content = re.sub(r"```\n?", "", content)

        # Handle empty array case
        content = content.strip()
        if not content or content == "":
            self.logger.info(f"Page {page_num}: No requirements found (empty response)")
            return []

        try:
            raw_requirements = json.loads(content)
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse page {page_num}: {e}")
            self.logger.warning(f"Content was: {content[:200]}")
            return []

        if not isinstance(raw_requirements, list):
            return []

        # Convert to RequirementRecords
        records = []
        for i, raw in enumerate(raw_requirements):
            try:
                # Generate requirement ID
                # Use `or` to handle both missing key AND null value
                section = raw.get("section") or "unknown"
                req_id = f"{document_id}-{section}-{counter_start + i + 1:03d}"

                # Extract keywords from requirement text
                keywords = self._extract_keywords(raw)

                # Map requirement type
                req_type_str = (raw.get("requirement_type") or "general").lower()
                req_type = RequirementType.GENERAL
                for rt in RequirementType:
                    if rt.value == req_type_str:
                        req_type = rt
                        break

                record = RequirementRecord(
                    requirement_id=req_id,
                    keywords=keywords,
                    source_document=document_id,
                    section=section,
                    page=page_num,
                    material_category=raw.get("material_category"),
                    environment=raw.get("environment"),
                    pressure_threshold=raw.get("pressure_threshold"),
                    temperature_threshold=raw.get("temperature_threshold"),
                    requirement_type=req_type,
                    requirement_text=raw.get("requirement_text") or "",
                    test_method=raw.get("test_method"),
                    cleaning_spec=raw.get("cleaning_spec"),
                    full_paragraph=raw.get("full_paragraph") or "",
                )
                records.append(record)

            except Exception as e:
                self.logger.warning(f"Failed to create record: {e}")

        return records

    def _extract_keywords(self, raw: dict) -> list[str]:
        """Extract keywords from requirement data for fast filtering."""
        keywords = set()

        # From material category
        if raw.get("material_category"):
            cat = raw["material_category"].lower()
            # Extract material names
            for term in ["stainless", "steel", "aluminum", "copper", "nickel",
                        "inconel", "monel", "titanium", "polymer", "teflon",
                        "kel-f", "viton", "rubber", "316", "304", "6061"]:
                if term in cat:
                    keywords.add(term)

        # From environment
        if raw.get("environment"):
            env = raw["environment"].lower()
            for term in ["gox", "lox", "oxygen", "o2", "air"]:
                if term in env:
                    keywords.add(term)

        # From test methods
        if raw.get("test_method"):
            keywords.add(raw["test_method"].split()[0].lower())

        return sorted(keywords)

    def _render_page(self, page) -> bytes:
        """Render page to PNG bytes."""
        img = page.to_image(resolution=self.render_dpi)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _derive_document_id(self, pdf_path: Path) -> str:
        """Derive document ID from filename."""
        name = pdf_path.stem

        # Common patterns
        patterns = [
            r"(NASA-STD-\d+[A-Z]?)",
            r"(ASTM-?[A-Z]\d+)",
            r"(MIL-STD-\d+)",
            r"(\d{4,})",  # Just a number like 6016
        ]

        for pattern in patterns:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        # Fallback to filename
        return name.upper()


def extract_standards(
    input_path: Union[str, Path],
    document_id: Optional[str] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> StandardsExtractionResult:
    """
    Convenience function to extract requirements from a standards PDF.

    Args:
        input_path: PDF file path
        document_id: Document identifier (e.g., "NASA-STD-6016")
        output_path: Optional path to save JSON results

    Returns:
        StandardsExtractionResult
    """
    extractor = StandardsExtractor()
    result = extractor.extract_pdf(input_path, document_id)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.to_json())
        logger.info(f"Saved to {output_path}")

    return result
