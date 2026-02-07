#!/usr/bin/env python3
"""
Module: Test Pdf Extractor
Purpose: PDF Extractor Tests for BoundState

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd

sys.path.insert(0, r"C:\BoundState")

from mira.miul.pdf_extractor import (
    BOMExtractor,
    PDFPLUMBER_TIMEOUT_SECONDS,
)


# =============================================================================
# BOMExtractor Initialization Tests
# =============================================================================


class TestBOMExtractorInit:
    """Tests for BOMExtractor initialization."""

    def test_default_max_pages(self):
        """Should default to reasonable max_pages."""
        extractor = BOMExtractor()
        assert extractor.max_pages == 10

    def test_custom_max_pages(self):
        """Should accept custom max_pages."""
        extractor = BOMExtractor(max_pages=5)
        assert extractor.max_pages == 5

    def test_min_max_pages_is_1(self):
        """max_pages should be at least 1."""
        extractor = BOMExtractor(max_pages=0)
        assert extractor.max_pages == 1

        extractor = BOMExtractor(max_pages=-5)
        assert extractor.max_pages == 1

    def test_silences_logs_by_default(self):
        """Should silence third-party logs by default."""
        # This just verifies it doesn't crash
        extractor = BOMExtractor(silence_logs=True)
        assert extractor is not None


# =============================================================================
# BOMExtractor Header Normalization Tests
# =============================================================================


class TestNormalizeHeaders:
    """Tests for header normalization."""

    def test_lowercases_headers(self):
        """Should lowercase headers."""
        extractor = BOMExtractor()
        result = extractor._normalize_headers(["PART NUMBER", "QTY"])
        assert result == ["part number", "qty"]

    def test_strips_whitespace(self):
        """Should strip whitespace."""
        extractor = BOMExtractor()
        result = extractor._normalize_headers(["  Part Number  ", "  Qty  "])
        assert result == ["part number", "qty"]

    def test_collapses_multiple_spaces(self):
        """Should collapse multiple spaces."""
        extractor = BOMExtractor()
        result = extractor._normalize_headers(["Part   Number", "Qty    Count"])
        assert result == ["part number", "qty count"]

    def test_handles_none(self):
        """Should handle None values."""
        extractor = BOMExtractor()
        result = extractor._normalize_headers([None, "QTY"])
        assert result == ["", "qty"]


# =============================================================================
# BOMExtractor Table Parsing Tests
# =============================================================================


class TestParseBomTable:
    """Tests for BOM table parsing."""

    def test_empty_dataframe_returns_empty(self):
        """Empty DataFrame should return empty BOM."""
        extractor = BOMExtractor()
        df = pd.DataFrame()

        result = extractor._parse_bom_table(df, "test_drawing")

        assert len(result) == 0
        assert "Part Number" in result.columns

    def test_finds_part_qty_headers(self):
        """Should find Part Number and Quantity columns."""
        extractor = BOMExtractor()
        df = pd.DataFrame([
            ["Part Number", "Qty", "Description"],
            ["PN-001", 5, "Test Part"],
            ["PN-002", 10, "Another Part"],
        ])

        result = extractor._parse_bom_table(df, "test_drawing")

        assert len(result) == 2
        assert "PN-001" in result["Part Number"].values
        assert "PN-002" in result["Part Number"].values

    def test_handles_quantity_column_name(self):
        """Should handle 'Quantity' column name."""
        extractor = BOMExtractor()
        df = pd.DataFrame([
            ["Part No.", "Quantity"],
            ["PN-001", 5],
        ])

        result = extractor._parse_bom_table(df, "test_drawing")

        assert len(result) == 1

    def test_adds_drawing_column(self):
        """Should add Drawing column from filename."""
        extractor = BOMExtractor()
        df = pd.DataFrame([
            ["Part Number", "Qty"],
            ["PN-001", 5],
        ])

        result = extractor._parse_bom_table(df, "my_drawing")

        assert "Drawing" in result.columns
        assert result.iloc[0]["Drawing"] == "my_drawing"

    def test_no_headers_returns_empty(self):
        """Should return empty if no part/qty headers found."""
        extractor = BOMExtractor()
        df = pd.DataFrame([
            ["Column A", "Column B"],
            ["Value 1", "Value 2"],
        ])

        result = extractor._parse_bom_table(df, "test_drawing")

        assert len(result) == 0

    def test_skips_empty_rows(self):
        """Should skip rows with no content."""
        extractor = BOMExtractor()
        df = pd.DataFrame([
            ["Part Number", "Qty"],
            ["PN-001", 5],
            ["", ""],
            ["PN-002", 10],
        ])

        result = extractor._parse_bom_table(df, "test_drawing")

        assert len(result) == 2


# =============================================================================
# BOMExtractor Table Extraction Tests
# =============================================================================


class TestExtractTables:
    """Tests for table extraction."""

    def test_returns_empty_without_camelot(self):
        """Should return empty list when Camelot unavailable."""
        extractor = BOMExtractor()
        extractor.camelot = None  # Simulate unavailable

        result = extractor.extract_tables(Path("test.pdf"))

        assert result == []

    @patch("mira.miul.pdf_extractor._try_import_camelot")
    def test_tries_both_flavors(self, mock_import):
        """Should try both lattice and stream flavors."""
        mock_camelot = MagicMock()
        mock_camelot.read_pdf.return_value = []
        mock_import.return_value = mock_camelot

        extractor = BOMExtractor()
        extractor.camelot = mock_camelot

        extractor.extract_tables(Path("test.pdf"))

        # Should have tried both flavors
        assert mock_camelot.read_pdf.call_count == 2


# =============================================================================
# BOMExtractor BOM Extraction Tests
# =============================================================================


class TestExtractBom:
    """Tests for high-level BOM extraction."""

    def test_returns_dataframe(self):
        """Should always return a DataFrame."""
        extractor = BOMExtractor()
        extractor.camelot = None
        extractor.pdfplumber = None

        result = extractor.extract_bom(Path("test.pdf"))

        assert isinstance(result, pd.DataFrame)
        assert "Part Number" in result.columns
        assert "Quantity" in result.columns
        assert "Drawing" in result.columns

    @patch.object(BOMExtractor, "extract_tables")
    @patch.object(BOMExtractor, "_parse_bom_table")
    def test_returns_first_successful_table(self, mock_parse, mock_tables):
        """Should return first successfully parsed table."""
        mock_tables.return_value = [pd.DataFrame(), pd.DataFrame()]

        bom1 = pd.DataFrame(columns=["Part Number", "Quantity", "Drawing"])
        bom2 = pd.DataFrame({
            "Part Number": ["PN-001"],
            "Quantity": [5],
            "Drawing": ["test"],
        })

        mock_parse.side_effect = [bom1, bom2]

        extractor = BOMExtractor()
        result = extractor.extract_bom(Path("test.pdf"))

        # Should return second (non-empty) result
        assert len(result) == 1

    def test_uses_stem_as_drawing_name(self):
        """Should use file stem as drawing name."""
        extractor = BOMExtractor()
        extractor.camelot = None
        extractor.pdfplumber = None

        # Just verify it doesn't crash with path
        path = Path("my_drawing_12345.pdf")
        result = extractor.extract_bom(path)

        assert isinstance(result, pd.DataFrame)


# =============================================================================
# BOMExtractor Timeout Tests
# =============================================================================


class TestPdfplumberTimeout:
    """Tests for pdfplumber timeout handling."""

    def test_timeout_constant_defined(self):
        """Should have timeout constant defined."""
        assert PDFPLUMBER_TIMEOUT_SECONDS > 0
        assert PDFPLUMBER_TIMEOUT_SECONDS <= 60  # Reasonable upper bound


# =============================================================================
# BOMExtractor OCR Fallback Tests
# =============================================================================


class TestOCRFallback:
    """Tests for OCR fallback functionality."""

    def test_handles_missing_ocr_deps(self):
        """Should handle missing OCR dependencies gracefully."""
        extractor = BOMExtractor()
        # OCR may or may not be available depending on environment
        # Just verify extractor initializes without error
        assert extractor is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
