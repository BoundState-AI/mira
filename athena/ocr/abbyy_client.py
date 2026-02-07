#!/usr/bin/env python3
"""
Module: Abbyy Client
Purpose: abbyy_client

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from athena.models.enums import OCRSource, VisionTrigger
from athena.models.ocr import BatchOCRResult, OCRResult
from athena.ocr.alto_parser import ALTOParser

if TYPE_CHECKING:
    import fitz

__all__ = ["ABBYYClient", "ABBYYServerClient", "MockABBYYClient"]

logger = logging.getLogger(__name__)


class ABBYYClientProtocol(Protocol):
    """Protocol for ABBYY client implementations."""

    async def process_pdf(
        self,
        pdf_path: Path,
        start_page: int,
        end_page: int,
        output_dir: Path | None = None,
    ) -> Path:
        """Process PDF pages and return path to ALTO XML output.

        Args:
            pdf_path: Path to input PDF
            start_page: Start page (1-indexed)
            end_page: End page (1-indexed, inclusive)
            output_dir: Output directory for ALTO XML

        Returns:
            Path to generated ALTO XML file
        """
        ...

    async def is_available(self) -> bool:
        """Check if ABBYY server is available."""
        ...


class ABBYYClient:
    """High-level client for ABBYY OCR processing.

    Wraps low-level client with parsing and result building.
    Supports incremental processing with save after each page.
    """

    def __init__(
        self,
        server_url: str | None = None,
        confidence_threshold: float = 0.7,
    ):
        """Initialize ABBYY client.

        Args:
            server_url: ABBYY FineReader Server URL (None for mock)
            confidence_threshold: Threshold for vision fallback trigger
        """
        self.confidence_threshold = confidence_threshold
        self.parser = ALTOParser(confidence_threshold)

        # Use mock client if no server URL provided
        if server_url:
            self._client: ABBYYClientProtocol = ABBYYServerClient(server_url)
        else:
            logger.warning("No ABBYY server URL - using mock client")
            self._client = MockABBYYClient()

    async def process_segment(
        self,
        pdf_path: Path,
        segment_id: str,
        batch_id: str,
        start_page: int,
        end_page: int,
        output_dir: Path | None = None,
        save_callback=None,
    ) -> BatchOCRResult:
        """Process PDF segment with ABBYY OCR.

        CRITICAL: Supports incremental saving via save_callback.

        Args:
            pdf_path: Path to input PDF
            segment_id: Segment identifier
            batch_id: Batch identifier
            start_page: Start page (1-indexed)
            end_page: End page (1-indexed, inclusive)
            output_dir: Output directory for ALTO XML
            save_callback: Called after each page with BatchOCRResult

        Returns:
            BatchOCRResult with all page results
        """
        # Get ALTO output from ABBYY
        alto_path = await self._client.process_pdf(
            pdf_path, start_page, end_page, output_dir
        )

        # Parse ALTO
        alto_pages = self.parser.parse_file(alto_path)

        # Build results with incremental saving
        batch_result = BatchOCRResult(
            batch_id=batch_id,
            segment_id=segment_id,
            total_pages=end_page - start_page + 1,
        )

        for alto_page in alto_pages:
            page_result = self._build_page_result(alto_page)
            batch_result.add_page_result(page_result)

            # CRITICAL: Save after each page
            if save_callback:
                await save_callback(batch_result)
                logger.debug(f"Saved OCR progress: {batch_result.pages_processed}/{batch_result.total_pages}")

        batch_result.processing_complete = True
        return batch_result

    def _build_page_result(self, alto_page) -> OCRResult:
        """Build OCRResult from parsed ALTO page.

        Args:
            alto_page: Parsed ALTOPage

        Returns:
            OCRResult with vision triggers if needed
        """
        # Check for vision triggers
        triggers = self._check_vision_triggers(alto_page)
        needs_vision = len(triggers) > 0

        # Get low confidence regions for vision review
        low_conf_regions = []
        for word in alto_page.low_confidence_words:
            bbox_dict = word.to_normalized_bbox(alto_page.width, alto_page.height)
            from athena.models.evidence import BoundingBox
            low_conf_regions.append(BoundingBox(
                x_min=bbox_dict["x_min"],
                y_min=bbox_dict["y_min"],
                x_max=bbox_dict["x_max"],
                y_max=bbox_dict["y_max"],
            ))

        return OCRResult(
            page=alto_page.page_number,
            ocr_source=OCRSource.ABBYY,
            full_text=alto_page.full_text,
            word_count=len(alto_page.words),
            average_confidence=alto_page.average_confidence,
            low_confidence_regions=low_conf_regions,
            needs_vision_review=needs_vision,
            vision_triggers=triggers,
            page_width=alto_page.width,
            page_height=alto_page.height,
        )

    def _check_vision_triggers(self, alto_page) -> list[VisionTrigger]:
        """Determine if page needs vision model review.

        Args:
            alto_page: Parsed ALTOPage

        Returns:
            List of vision triggers (empty if OCR sufficient)
        """
        triggers = []

        # Low average confidence
        if alto_page.average_confidence < self.confidence_threshold:
            triggers.append(VisionTrigger.LOW_OCR_CONFIDENCE)

        # Many low-confidence words (>20%)
        if alto_page.words:
            low_conf_ratio = len(alto_page.low_confidence_words) / len(alto_page.words)
            if low_conf_ratio > 0.2:
                triggers.append(VisionTrigger.LOW_OCR_CONFIDENCE)

        # Very little text (might be drawing/diagram)
        if len(alto_page.words) < 20:
            triggers.append(VisionTrigger.DRAWING_DIAGRAM)

        return triggers


class ABBYYServerClient:
    """Client for ABBYY FineReader Server REST API.

    Connects to ABBYY FineReader Server for production OCR processing.
    """

    def __init__(self, server_url: str):
        """Initialize server client.

        Args:
            server_url: ABBYY FineReader Server URL
        """
        self.server_url = server_url.rstrip("/")

    async def process_pdf(
        self,
        pdf_path: Path,
        start_page: int,
        end_page: int,
        output_dir: Path | None = None,
    ) -> Path:
        """Submit PDF to ABBYY server and retrieve ALTO output.

        Args:
            pdf_path: Path to input PDF
            start_page: Start page (1-indexed)
            end_page: End page (1-indexed, inclusive)
            output_dir: Output directory for ALTO XML

        Returns:
            Path to generated ALTO XML file

        Raises:
            ConnectionError: If server is unreachable
            RuntimeError: If OCR processing fails
        """
        import httpx

        output_dir = output_dir or Path(tempfile.gettempdir()) / "athena_ocr"
        output_dir.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=300.0) as client:
            # Submit PDF
            with open(pdf_path, "rb") as f:
                files = {"file": (pdf_path.name, f, "application/pdf")}
                params = {
                    "startPage": start_page,
                    "endPage": end_page,
                    "outputFormat": "alto",
                }
                response = await client.post(
                    f"{self.server_url}/api/process",
                    files=files,
                    params=params,
                )
                response.raise_for_status()
                job_id = response.json()["jobId"]

            # Poll for completion
            while True:
                status_resp = await client.get(f"{self.server_url}/api/jobs/{job_id}")
                status_resp.raise_for_status()
                status = status_resp.json()

                if status["status"] == "completed":
                    break
                elif status["status"] == "failed":
                    raise RuntimeError(f"ABBYY processing failed: {status.get('error')}")

                import asyncio
                await asyncio.sleep(1)

            # Download ALTO output
            alto_resp = await client.get(f"{self.server_url}/api/jobs/{job_id}/output/alto")
            alto_resp.raise_for_status()

            alto_path = output_dir / f"{pdf_path.stem}_pages_{start_page}-{end_page}.xml"
            alto_path.write_bytes(alto_resp.content)

            return alto_path

    async def is_available(self) -> bool:
        """Check if ABBYY server is available."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.server_url}/api/health")
                return response.status_code == 200
        except Exception:
            return False


class MockABBYYClient:
    """Mock ABBYY client for testing without actual server.

    Generates minimal ALTO XML from PDF text extraction.
    """

    async def process_pdf(
        self,
        pdf_path: Path,
        start_page: int,
        end_page: int,
        output_dir: Path | None = None,
    ) -> Path:
        """Generate mock ALTO output from PDF.

        Uses PyMuPDF text extraction as fallback.
        Real deployments should use actual ABBYY server.

        Args:
            pdf_path: Path to input PDF
            start_page: Start page (1-indexed)
            end_page: End page (1-indexed, inclusive)
            output_dir: Output directory

        Returns:
            Path to mock ALTO XML file
        """
        import fitz

        output_dir = output_dir or Path(tempfile.gettempdir()) / "athena_ocr"
        output_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(pdf_path)

        # Build ALTO XML
        alto_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">',
            '<Layout>',
        ]

        for page_idx in range(start_page - 1, min(end_page, len(doc))):
            page = doc[page_idx]
            rect = page.rect
            width = int(rect.width)
            height = int(rect.height)

            alto_lines.append(f'<Page WIDTH="{width}" HEIGHT="{height}" PHYSICAL_IMG_NR="{page_idx + 1}">')
            alto_lines.append('<PrintSpace>')
            alto_lines.append('<TextBlock>')

            # Extract words with positions
            words = page.get_text("words")
            for word_data in words:
                x0, y0, x1, y1, text, block_no, line_no, word_no = word_data
                w = int(x1 - x0)
                h = int(y1 - y0)
                # Mock confidence (0.85 for typed text via PyMuPDF)
                conf = 0.85
                alto_lines.append(
                    f'<String CONTENT="{self._escape_xml(text)}" '
                    f'HPOS="{int(x0)}" VPOS="{int(y0)}" '
                    f'WIDTH="{w}" HEIGHT="{h}" WC="{conf:.2f}"/>'
                )

            alto_lines.append('</TextBlock>')
            alto_lines.append('</PrintSpace>')
            alto_lines.append('</Page>')

        doc.close()

        alto_lines.append('</Layout>')
        alto_lines.append('</alto>')

        alto_path = output_dir / f"{pdf_path.stem}_pages_{start_page}-{end_page}.xml"
        alto_path.write_text("\n".join(alto_lines), encoding="utf-8")

        logger.info(f"Generated mock ALTO: {alto_path}")
        return alto_path

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    async def is_available(self) -> bool:
        """Mock is always available."""
        return True
