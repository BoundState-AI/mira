#!/usr/bin/env python3
"""
Module: Ocr Stage
Purpose: [Automatically migrated - needs manual review]

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

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

from athena.models.enums import VisionTrigger
from athena.models.ocr import BatchOCRResult, OCRResult
from athena.models.separator import FolderSegment
from athena.ocr.abbyy_client import ABBYYClient
from athena.ocr.alto_parser import ALTOParser

if TYPE_CHECKING:
    import fitz

__all__ = ["OCRStage"]

logger = logging.getLogger(__name__)


class OCRStage:
    """Run ABBYY OCR on documents and segments.

    CRITICAL: Saves progress INCREMENTALLY after each page.
    The Wasted Run of 2025-12-22: Never lose progress on interrupt.

    Yields-first design: ABBYY has higher yield than vision-based OCR.
    """

    def __init__(
        self,
        abbyy_server_url: str | None = None,
        confidence_threshold: float = 0.7,
        output_dir: Path | None = None,
    ):
        """Initialize OCR stage.

        Args:
            abbyy_server_url: ABBYY FineReader Server URL (None for mock)
            confidence_threshold: Threshold for vision fallback trigger
            output_dir: Directory for ALTO XML output
        """
        self.abbyy_client = ABBYYClient(
            server_url=abbyy_server_url,
            confidence_threshold=confidence_threshold,
        )
        self.parser = ALTOParser(confidence_threshold)
        self.output_dir = output_dir or Path("./ocr_output")
        self.confidence_threshold = confidence_threshold

    async def process_segment(
        self,
        segment: FolderSegment,
        pdf_path: Path,
        save_callback: Callable[[BatchOCRResult], Awaitable[None]] | None = None,
    ) -> BatchOCRResult:
        """Process folder segment with ABBYY OCR.

        CRITICAL: Saves after each page via save_callback.

        Args:
            segment: Folder segment to process
            pdf_path: Path to source PDF
            save_callback: Called after each page with current results

        Returns:
            BatchOCRResult with all page results
        """
        start_page, end_page = segment.page_range

        result = await self.abbyy_client.process_segment(
            pdf_path=pdf_path,
            segment_id=str(segment.segment_id),
            batch_id=segment.batch_id,
            start_page=start_page,
            end_page=end_page,
            output_dir=self.output_dir,
            save_callback=save_callback,
        )

        logger.info(
            f"OCR complete for segment {str(segment.segment_id)[:8]}: "
            f"{result.pages_processed} pages, "
            f"{result.pages_needing_vision} need vision review"
        )

        return result

    async def process_pdf(
        self,
        pdf_path: Path,
        batch_id: str,
        start_page: int = 1,
        end_page: int | None = None,
        save_callback: Callable[[BatchOCRResult], Awaitable[None]] | None = None,
    ) -> BatchOCRResult:
        """Process PDF with ABBYY OCR.

        CRITICAL: Saves after each page via save_callback.

        Args:
            pdf_path: Path to source PDF
            batch_id: Batch identifier
            start_page: Start page (1-indexed)
            end_page: End page (1-indexed, None for all)
            save_callback: Called after each page

        Returns:
            BatchOCRResult with all page results
        """
        import fitz

        doc = fitz.open(pdf_path)
        if end_page is None:
            end_page = len(doc)
        doc.close()

        result = await self.abbyy_client.process_segment(
            pdf_path=pdf_path,
            segment_id=None,
            batch_id=batch_id,
            start_page=start_page,
            end_page=end_page,
            output_dir=self.output_dir,
            save_callback=save_callback,
        )

        return result

    def get_pages_needing_vision(
        self,
        batch_result: BatchOCRResult,
    ) -> list[int]:
        """Get page numbers that need vision model review.

        Args:
            batch_result: OCR batch result

        Returns:
            List of 1-indexed page numbers
        """
        return [
            page.page
            for page in batch_result.pages
            if page.needs_vision_review
        ]

    def get_vision_trigger_summary(
        self,
        batch_result: BatchOCRResult,
    ) -> dict[str, int]:
        """Get summary of vision triggers by type.

        Args:
            batch_result: OCR batch result

        Returns:
            Dictionary of trigger type -> count
        """
        from collections import Counter
        triggers: list[str] = []

        for page in batch_result.pages:
            for trigger in page.vision_triggers:
                triggers.append(trigger.value)

        return dict(Counter(triggers))


async def save_ocr_result(
    result: BatchOCRResult,
    output_path: Path,
) -> None:
    """Default save callback for OCR results.

    Saves result as JSON after each page.

    Args:
        result: Current OCR result
        output_path: Path to save JSON
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to JSON-serializable dict
    data = {
        "batch_id": result.batch_id,
        "segment_id": result.segment_id,
        "total_pages": result.total_pages,
        "pages_processed": result.pages_processed,
        "pages_needing_vision": result.pages_needing_vision,
        "average_confidence": result.average_confidence,
        "processing_complete": result.processing_complete,
        "pages": [
            {
                "page": p.page,
                "ocr_source": p.ocr_source.value,
                "full_text": p.full_text[:500] + "..." if len(p.full_text) > 500 else p.full_text,
                "word_count": p.word_count,
                "average_confidence": p.average_confidence,
                "needs_vision_review": p.needs_vision_review,
                "vision_triggers": [t.value for t in p.vision_triggers],
            }
            for p in result.pages
        ],
    }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    logger.debug(f"Saved OCR result: {result.pages_processed} pages to {output_path}")
