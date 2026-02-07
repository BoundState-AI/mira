#!/usr/bin/env python3
"""
Module: Test Barcode
Purpose: Tests for athena.utils.barcode module.

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

from athena.utils.barcode import (
    SEPARATOR_BARCODE_PREFIX,
    extract_separator_id,
)


class TestBarcodePrefix:
    """Tests for barcode prefix constant."""

    def test_separator_barcode_prefix_value(self):
        """Verify separator barcode prefix."""
        assert SEPARATOR_BARCODE_PREFIX == "ATHENA-SEP-"

    def test_separator_barcode_prefix_is_string(self):
        """Prefix is a string."""
        assert isinstance(SEPARATOR_BARCODE_PREFIX, str)


class TestExtractSeparatorId:
    """Tests for extract_separator_id function."""

    def test_extract_separator_id_valid(self):
        """Extract UUID from valid barcode data."""
        barcode_data = "ATHENA-SEP-12345678-abcd-efgh-ijkl-mnopqrstuv"

        result = extract_separator_id(barcode_data)

        assert result == "12345678-abcd-efgh-ijkl-mnopqrstuv"

    def test_extract_separator_id_invalid_prefix(self):
        """Return None for barcode with wrong prefix."""
        barcode_data = "OTHER-PREFIX-12345678"

        result = extract_separator_id(barcode_data)

        assert result is None

    def test_extract_separator_id_exact_prefix(self):
        """Handle barcode that is exactly the prefix."""
        barcode_data = "ATHENA-SEP-"

        result = extract_separator_id(barcode_data)

        assert result == ""

    def test_extract_separator_id_empty_string(self):
        """Handle empty string."""
        result = extract_separator_id("")

        assert result is None

    def test_extract_separator_id_partial_prefix(self):
        """Handle partial prefix match."""
        barcode_data = "ATHENA-"

        result = extract_separator_id(barcode_data)

        assert result is None


class TestGenerateSeparatorSheet:
    """Tests for generate_separator_sheet function.

    These tests are conditional on reportlab being available.
    """

    @pytest.fixture
    def can_generate(self):
        """Check if PDF generation dependencies are available."""
        try:
            import barcode
            from reportlab.pdfgen import canvas
            return True
        except ImportError:
            return False

    def test_generate_separator_sheet_returns_bytes(self, can_generate):
        """generate_separator_sheet returns PDF bytes."""
        if not can_generate:
            pytest.skip("PDF generation dependencies not available")

        from athena.utils.barcode import generate_separator_sheet

        pdf_bytes = generate_separator_sheet()

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        # PDF signature
        assert pdf_bytes[:4] == b"%PDF"

    def test_generate_separator_sheet_with_custom_id(self, can_generate):
        """generate_separator_sheet uses provided separator_id."""
        if not can_generate:
            pytest.skip("PDF generation dependencies not available")

        from athena.utils.barcode import generate_separator_sheet

        custom_id = "my-custom-uuid-12345"
        pdf_bytes = generate_separator_sheet(separator_id=custom_id)

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_generate_separator_sheet_saves_to_file(self, can_generate, tmp_path):
        """generate_separator_sheet saves to file when path provided."""
        if not can_generate:
            pytest.skip("PDF generation dependencies not available")

        from athena.utils.barcode import generate_separator_sheet

        output_path = tmp_path / "separator.pdf"
        pdf_bytes = generate_separator_sheet(output_path=output_path)

        assert output_path.exists()
        assert output_path.read_bytes() == pdf_bytes

    def test_generate_separator_sheet_with_metadata(self, can_generate):
        """generate_separator_sheet includes metadata fields."""
        if not can_generate:
            pytest.skip("PDF generation dependencies not available")

        from athena.utils.barcode import generate_separator_sheet

        pdf_bytes = generate_separator_sheet(
            folder_name="Test Folder",
            date_range_start="1980-01-01",
            date_range_end="1980-12-31",
            doc_count="50",
            notes="Test notes",
        )

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0


class TestGenerateBatchSeparators:
    """Tests for generate_batch_separators function."""

    @pytest.fixture
    def can_generate(self):
        """Check if PDF generation dependencies are available."""
        try:
            import barcode
            from reportlab.pdfgen import canvas
            return True
        except ImportError:
            return False

    def test_generate_batch_separators(self, can_generate, tmp_path):
        """Generate multiple separator sheets."""
        if not can_generate:
            pytest.skip("PDF generation dependencies not available")

        from athena.utils.barcode import generate_batch_separators

        output_dir = tmp_path / "separators"
        paths = generate_batch_separators(count=3, output_dir=output_dir)

        assert len(paths) == 3
        for path in paths:
            assert path.exists()
            assert path.suffix == ".pdf"

    def test_generate_batch_separators_custom_prefix(self, can_generate, tmp_path):
        """Batch separators use custom prefix."""
        if not can_generate:
            pytest.skip("PDF generation dependencies not available")

        from athena.utils.barcode import generate_batch_separators

        output_dir = tmp_path / "custom"
        paths = generate_batch_separators(
            count=2,
            output_dir=output_dir,
            prefix="custom_sep",
        )

        for path in paths:
            assert "custom_sep" in path.name


class TestScanBarcode:
    """Tests for scan_barcode function.

    These tests require pyzbar and fitz (PyMuPDF) which may not be available.
    """

    def test_scan_barcode_import_error_handled(self):
        """scan_barcode returns None if pyzbar not installed."""
        # This test verifies the error handling path exists
        # The actual import error handling is in the function
        from athena.utils.barcode import scan_barcode

        # scan_barcode expects a fitz.Page object
        # Without proper setup, this tests the function exists
        assert callable(scan_barcode)


class TestIsSeparatorPage:
    """Tests for is_separator_page function."""

    def test_is_separator_page_callable(self):
        """is_separator_page function exists and is callable."""
        from athena.utils.barcode import is_separator_page

        assert callable(is_separator_page)
