#!/usr/bin/env python3
"""
Module: Test Ocr
Purpose: Tests for athena.models.ocr module.

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

import pytest

from athena.models.ocr import ALTOPage, ALTOWord, BatchOCRResult, OCRResult
from athena.models.enums import OCRSource, VisionTrigger


class TestALTOWord:
    """Tests for ALTOWord dataclass."""

    def test_alto_word_creation(self, sample_alto_word):
        """Create ALTOWord with all fields."""
        assert sample_alto_word.content == "Test"
        assert sample_alto_word.x == 100
        assert sample_alto_word.y == 200
        assert sample_alto_word.width == 50
        assert sample_alto_word.height == 20
        assert sample_alto_word.confidence == 0.95
        assert sample_alto_word.page == 1

    def test_normalized_bbox_standard(self, sample_alto_word):
        """Normalize coordinates to 0.0-1.0 range."""
        bbox = sample_alto_word.to_normalized_bbox(page_width=1000, page_height=2000)

        assert bbox["x_min"] == 0.1    # 100/1000
        assert bbox["y_min"] == 0.1    # 200/2000
        assert bbox["x_max"] == 0.15   # (100+50)/1000
        assert bbox["y_max"] == 0.11   # (200+20)/2000

    def test_normalized_bbox_zero_dimensions(self, sample_alto_word):
        """Handle zero page dimensions gracefully."""
        bbox = sample_alto_word.to_normalized_bbox(page_width=0, page_height=0)

        # Should use fallback values
        assert bbox["x_min"] == 0.0
        assert bbox["y_min"] == 0.0
        assert bbox["x_max"] == 1.0
        assert bbox["y_max"] == 1.0

    def test_normalized_bbox_full_page(self):
        """Word spanning entire page normalizes correctly."""
        word = ALTOWord(
            content="Full",
            x=0,
            y=0,
            width=1000,
            height=1000,
            confidence=1.0,
            page=1,
        )
        bbox = word.to_normalized_bbox(page_width=1000, page_height=1000)

        assert bbox["x_min"] == 0.0
        assert bbox["y_min"] == 0.0
        assert bbox["x_max"] == 1.0
        assert bbox["y_max"] == 1.0


class TestALTOPage:
    """Tests for ALTOPage dataclass."""

    def test_alto_page_creation(self, sample_alto_page):
        """Create ALTOPage with word list."""
        assert sample_alto_page.page_number == 1
        assert sample_alto_page.width == 2480
        assert sample_alto_page.height == 3508
        assert len(sample_alto_page.words) == 3

    def test_full_text_reconstruction(self, sample_alto_page):
        """Reconstruct full text from words."""
        text = sample_alto_page.full_text

        assert text == "Hello World Low"

    def test_full_text_empty_page(self):
        """Empty page returns empty string."""
        page = ALTOPage(page_number=1, width=1000, height=1000, words=[])

        assert page.full_text == ""

    def test_low_confidence_words_filtering(self, sample_alto_page):
        """Filter words below 0.7 confidence threshold."""
        low_conf = sample_alto_page.low_confidence_words

        assert len(low_conf) == 1
        assert low_conf[0].content == "Low"
        assert low_conf[0].confidence == 0.60

    def test_low_confidence_words_all_high(self):
        """No low confidence words when all are high."""
        page = ALTOPage(
            page_number=1,
            width=1000,
            height=1000,
            words=[
                ALTOWord(content="Good", x=0, y=0, width=10, height=10, confidence=0.95, page=1),
                ALTOWord(content="Quality", x=0, y=0, width=10, height=10, confidence=0.88, page=1),
            ],
        )

        assert page.low_confidence_words == []

    def test_average_confidence(self, sample_alto_page):
        """Calculate average confidence correctly."""
        # (0.95 + 0.88 + 0.60) / 3 = 0.81
        avg = sample_alto_page.average_confidence

        assert abs(avg - 0.81) < 0.01

    def test_average_confidence_empty_page(self):
        """Empty page returns 0.0 confidence."""
        page = ALTOPage(page_number=1, width=1000, height=1000, words=[])

        assert page.average_confidence == 0.0


class TestOCRResult:
    """Tests for OCRResult Pydantic model."""

    def test_ocr_result_creation(self, sample_ocr_result):
        """Create OCRResult with standard fields."""
        assert sample_ocr_result.page == 1
        assert sample_ocr_result.ocr_source == OCRSource.ABBYY
        assert sample_ocr_result.full_text == "Hello World Low"
        assert sample_ocr_result.word_count == 3
        assert sample_ocr_result.average_confidence == 0.81

    def test_ocr_result_vision_flags(self, sample_ocr_result_vision_needed):
        """OCRResult with vision review flags."""
        assert sample_ocr_result_vision_needed.needs_vision_review is True
        assert VisionTrigger.LOW_OCR_CONFIDENCE in sample_ocr_result_vision_needed.vision_triggers

    def test_ocr_result_confidence_validation(self):
        """Confidence must be in [0.0, 1.0] range."""
        # Valid range
        result = OCRResult(page=1, full_text="Test", average_confidence=0.5)
        assert result.average_confidence == 0.5

        # Edge cases
        result_min = OCRResult(page=1, full_text="Test", average_confidence=0.0)
        assert result_min.average_confidence == 0.0

        result_max = OCRResult(page=1, full_text="Test", average_confidence=1.0)
        assert result_max.average_confidence == 1.0

    def test_ocr_result_serialization(self, sample_ocr_result):
        """OCRResult can be serialized to dict."""
        data = sample_ocr_result.model_dump()

        assert isinstance(data, dict)
        assert data["page"] == 1
        assert data["full_text"] == "Hello World Low"

    def test_ocr_result_default_values(self):
        """OCRResult uses sensible defaults."""
        result = OCRResult(page=1, full_text="Minimal")

        assert result.ocr_source == OCRSource.ABBYY
        assert result.word_count == 0
        assert result.average_confidence == 0.0
        assert result.low_confidence_regions == []
        assert result.needs_vision_review is False
        assert result.vision_triggers == []


class TestBatchOCRResult:
    """Tests for BatchOCRResult with incremental state updates."""

    def test_batch_ocr_result_creation(self):
        """Create BatchOCRResult."""
        batch = BatchOCRResult(batch_id="batch-001")

        assert batch.batch_id == "batch-001"
        assert batch.pages == []
        assert batch.total_pages == 0
        assert batch.pages_processed == 0
        assert batch.pages_needing_vision == 0
        assert batch.processing_complete is False

    def test_add_page_result_updates_state(self, sample_ocr_result):
        """add_page_result updates all state correctly."""
        batch = BatchOCRResult(batch_id="batch-001")

        batch.add_page_result(sample_ocr_result)

        assert len(batch.pages) == 1
        assert batch.pages_processed == 1
        assert batch.pages_needing_vision == 0
        assert batch.average_confidence == 0.81

    def test_add_page_result_tracks_vision_triggers(
        self,
        sample_ocr_result,
        sample_ocr_result_vision_needed,
    ):
        """add_page_result tracks vision trigger count."""
        batch = BatchOCRResult(batch_id="batch-001")

        batch.add_page_result(sample_ocr_result)
        assert batch.pages_needing_vision == 0

        batch.add_page_result(sample_ocr_result_vision_needed)
        assert batch.pages_needing_vision == 1

    def test_add_page_result_incremental_confidence(self):
        """Average confidence updates incrementally."""
        batch = BatchOCRResult(batch_id="batch-001")

        # Add first page with 0.8 confidence
        page1 = OCRResult(page=1, full_text="Page 1", average_confidence=0.8)
        batch.add_page_result(page1)
        assert batch.average_confidence == 0.8

        # Add second page with 0.6 confidence
        page2 = OCRResult(page=2, full_text="Page 2", average_confidence=0.6)
        batch.add_page_result(page2)
        # (0.8 + 0.6) / 2 = 0.7
        assert abs(batch.average_confidence - 0.7) < 0.01

    def test_add_page_result_multiple_pages(self):
        """Process multiple pages incrementally."""
        batch = BatchOCRResult(batch_id="batch-001", total_pages=5)

        for i in range(5):
            page = OCRResult(
                page=i + 1,
                full_text=f"Page {i + 1}",
                average_confidence=0.9,
                needs_vision_review=(i == 2),  # Page 3 needs vision
            )
            batch.add_page_result(page)

        assert batch.pages_processed == 5
        assert batch.pages_needing_vision == 1
        assert len(batch.pages) == 5

    def test_batch_ocr_result_serialization(self, sample_ocr_result):
        """BatchOCRResult can be serialized."""
        batch = BatchOCRResult(batch_id="batch-001", segment_id="seg-001")
        batch.add_page_result(sample_ocr_result)

        data = batch.model_dump()

        assert isinstance(data, dict)
        assert data["batch_id"] == "batch-001"
        assert data["segment_id"] == "seg-001"
        assert len(data["pages"]) == 1

    def test_batch_ocr_result_empty_average(self):
        """Empty batch has 0.0 average confidence."""
        batch = BatchOCRResult(batch_id="empty")

        assert batch.average_confidence == 0.0
