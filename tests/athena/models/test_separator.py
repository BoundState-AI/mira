#!/usr/bin/env python3
"""
Module: Test Separator
Purpose: Tests for athena.models.separator module.

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

from uuid import UUID

import pytest

from athena.models.separator import FolderSegment, SeparatorResult


class TestSeparatorResult:
    """Tests for SeparatorResult model."""

    def test_minimal_separator_result(self):
        """Create SeparatorResult with only required field."""
        result = SeparatorResult(separator_id="test-123")

        assert result.separator_id == "test-123"
        assert result.confidence == 1.0  # Default
        assert result.folder_name is None
        assert result.date_range_start is None
        assert result.date_range_end is None

    def test_full_separator_result(self, sample_separator_result):
        """Create SeparatorResult with all fields."""
        assert sample_separator_result.separator_id == "test-uuid-12345"
        assert sample_separator_result.confidence == 1.0
        assert sample_separator_result.folder_name == "Engineering Records 1980"
        assert sample_separator_result.date_range_start == "1980-01-01"
        assert sample_separator_result.date_range_end == "1980-12-31"
        assert sample_separator_result.doc_count_expected == 50
        assert sample_separator_result.scanned_by == "J. Doe"

    def test_separator_result_serialization(self, sample_separator_result):
        """SeparatorResult can be serialized to dict."""
        data = sample_separator_result.model_dump()

        assert isinstance(data, dict)
        assert data["separator_id"] == "test-uuid-12345"
        assert data["folder_name"] == "Engineering Records 1980"

    def test_separator_result_from_dict(self):
        """SeparatorResult can be created from dict."""
        data = {
            "separator_id": "from-dict-uuid",
            "folder_name": "Test Folder",
            "confidence": 1.0,
        }
        result = SeparatorResult(**data)

        assert result.separator_id == "from-dict-uuid"
        assert result.folder_name == "Test Folder"


class TestFolderSegment:
    """Tests for FolderSegment model."""

    def test_minimal_folder_segment(self):
        """Create FolderSegment with required fields."""
        sep = SeparatorResult(separator_id="seg-001")
        segment = FolderSegment(
            batch_id="batch-001",
            separator=sep,
            page_range=(1, 10),
            page_count=10,
        )

        assert segment.batch_id == "batch-001"
        assert segment.separator.separator_id == "seg-001"
        assert segment.page_range == (1, 10)
        assert segment.page_count == 10
        assert isinstance(segment.segment_id, UUID)

    def test_folder_segment_auto_generated_id(self):
        """FolderSegment generates unique UUID."""
        sep = SeparatorResult(separator_id="test")

        seg1 = FolderSegment(batch_id="b1", separator=sep, page_range=(1, 5), page_count=5)
        seg2 = FolderSegment(batch_id="b1", separator=sep, page_range=(6, 10), page_count=5)

        assert seg1.segment_id != seg2.segment_id

    def test_folder_segment_documents_list(self, sample_folder_segment):
        """FolderSegment tracks document UUIDs."""
        assert sample_folder_segment.documents == []

        # Simulate adding documents
        from uuid import uuid4
        doc_id = uuid4()
        sample_folder_segment.documents.append(doc_id)

        assert len(sample_folder_segment.documents) == 1
        assert sample_folder_segment.documents[0] == doc_id

    def test_folder_segment_processing_status(self, sample_folder_segment):
        """FolderSegment tracks processing completion."""
        assert sample_folder_segment.processing_complete is False

        sample_folder_segment.processing_complete = True
        assert sample_folder_segment.processing_complete is True

    def test_folder_segment_serialization(self, sample_folder_segment):
        """FolderSegment can be serialized."""
        data = sample_folder_segment.model_dump()

        assert isinstance(data, dict)
        assert data["batch_id"] == "batch-001"
        assert data["page_range"] == (1, 50)
        assert "segment_id" in data

    def test_folder_segment_page_range_tuple(self):
        """FolderSegment page_range is a tuple."""
        sep = SeparatorResult(separator_id="test")
        segment = FolderSegment(
            batch_id="b1",
            separator=sep,
            page_range=(15, 30),
            page_count=16,
        )

        start, end = segment.page_range
        assert start == 15
        assert end == 30
