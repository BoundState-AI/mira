#!/usr/bin/env python3
"""
Module: Ocr
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

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from athena.models.enums import OCRSource, VisionTrigger
from athena.models.evidence import BoundingBox


@dataclass
class ALTOWord:
    """Single word with position and confidence from ALTO XML.

    ALTO (Analyzed Layout and Text Object) is the standard XML format
    output by ABBYY FineReader containing word-level OCR results.
    """
    content: str
    x: int                 # HPOS - horizontal position in pixels
    y: int                 # VPOS - vertical position in pixels
    width: int
    height: int
    confidence: float      # WC attribute (0.0-1.0)
    page: int

    def to_normalized_bbox(self, page_width: int, page_height: int) -> dict:
        """Convert to normalized 0.0-1.0 coordinates for Evidence model.

        Args:
            page_width: Total page width in pixels
            page_height: Total page height in pixels

        Returns:
            Dictionary with x_min, y_min, x_max, y_max (0.0-1.0)
        """
        return {
            "x_min": self.x / page_width if page_width > 0 else 0.0,
            "y_min": self.y / page_height if page_height > 0 else 0.0,
            "x_max": (self.x + self.width) / page_width if page_width > 0 else 1.0,
            "y_max": (self.y + self.height) / page_height if page_height > 0 else 1.0,
        }


@dataclass
class ALTOPage:
    """Parsed ALTO page with word-level OCR data."""
    page_number: int
    width: int
    height: int
    words: list[ALTOWord] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Reconstruct full text from words."""
        return " ".join(w.content for w in self.words)

    @property
    def low_confidence_words(self) -> list[ALTOWord]:
        """Words below confidence threshold (candidates for vision review)."""
        return [w for w in self.words if w.confidence < 0.7]

    @property
    def average_confidence(self) -> float:
        """Average OCR confidence for page."""
        if not self.words:
            return 0.0
        return sum(w.confidence for w in self.words) / len(self.words)


class OCRResult(BaseModel):
    """Result from ABBYY OCR processing for a single page.

    Contains full text, word-level data, and vision trigger flags.
    Vision triggers indicate when fallback to vision models is needed.
    """
    page: int
    ocr_source: OCRSource = OCRSource.ABBYY
    full_text: str
    word_count: int = 0
    average_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    low_confidence_regions: list[BoundingBox] = Field(default_factory=list)
    needs_vision_review: bool = False
    vision_triggers: list[VisionTrigger] = Field(default_factory=list)
    processing_time_ms: int = 0

    # Page dimensions for coordinate normalization
    page_width: int = 0
    page_height: int = 0


class BatchOCRResult(BaseModel):
    """OCR results for an entire batch/segment.

    Supports incremental processing - results saved after each page.
    """
    batch_id: str
    segment_id: str | None = None
    pages: list[OCRResult] = Field(default_factory=list)
    total_pages: int = 0
    pages_processed: int = 0
    pages_needing_vision: int = 0
    average_confidence: float = 0.0
    processing_complete: bool = False

    def add_page_result(self, result: OCRResult) -> None:
        """Add page result and update aggregates.

        CRITICAL: This enables incremental saving - call after each page.
        """
        self.pages.append(result)
        self.pages_processed = len(self.pages)
        if result.needs_vision_review:
            self.pages_needing_vision += 1
        # Recalculate average
        if self.pages:
            self.average_confidence = sum(p.average_confidence for p in self.pages) / len(self.pages)
