#!/usr/bin/env python3
"""
Module: Test Excel Writer
Purpose: MIUL Excel Writer Tests for BoundState

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
from io import BytesIO
from unittest.mock import MagicMock, patch

sys.path.insert(0, r"C:\BoundState")

from mira.miul.excel_writer import (
    MIULExcelWriter,
    MIUL_COLUMNS,
    write_miul_excel,
)


# =============================================================================
# MIUL_COLUMNS Tests
# =============================================================================


class TestMiulColumns:
    """Tests for MIUL column specification."""

    def test_has_required_columns(self):
        """Should have all required MIUL columns."""
        required = [
            "Index", "Parent", "Part Number", "Part Description",
            "NHA", "Criticality", "Material Code", "Designation",
            "FLAM", "SCC", "CORR", "TVS", "TOX", "FS", "MUA",
        ]

        headers = [col[0] for col in MIUL_COLUMNS]
        for req in required:
            assert req in headers, f"Missing required column: {req}"

    def test_has_rating_columns(self):
        """Should have all 6 rating columns."""
        headers = [col[0] for col in MIUL_COLUMNS]

        ratings = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]
        for rating in ratings:
            assert rating in headers

    def test_columns_have_widths(self):
        """Each column should have a width specification."""
        for header, attr, width in MIUL_COLUMNS:
            assert isinstance(width, int)
            assert width > 0


# =============================================================================
# MIULExcelWriter Tests
# =============================================================================


class TestMiulExcelWriterInit:
    """Tests for MIULExcelWriter initialization."""

    def test_default_options(self):
        """Should initialize with default highlighting options."""
        writer = MIULExcelWriter()
        assert writer.highlight_gaps is True
        assert writer.highlight_critical is True

    def test_custom_options(self):
        """Should accept custom highlighting options."""
        writer = MIULExcelWriter(highlight_gaps=False, highlight_critical=False)
        assert writer.highlight_gaps is False
        assert writer.highlight_critical is False


class TestMiulExcelWriterStyles:
    """Tests for style constants."""

    def test_has_header_styles(self):
        """Should have header fill and font defined."""
        assert MIULExcelWriter.HEADER_FILL is not None
        assert MIULExcelWriter.HEADER_FONT is not None

    def test_has_criticality_fills(self):
        """Should have criticality highlighting fills."""
        assert MIULExcelWriter.CRIT_1_FILL is not None
        assert MIULExcelWriter.CRIT_2_FILL is not None

    def test_has_gap_fill(self):
        """Should have gap highlighting fill."""
        assert MIULExcelWriter.GAP_FILL is not None


class TestMiulExcelWriterWrite:
    """Tests for write functionality."""

    @patch("mira.miul.excel_writer.Workbook")
    def test_creates_three_sheets(self, mock_wb_class):
        """Should create MIUL, Summary, and Validation sheets."""
        mock_wb = MagicMock()
        mock_ws_miul = MagicMock()
        mock_wb.active = mock_ws_miul
        mock_wb.create_sheet = MagicMock(return_value=MagicMock())
        mock_wb_class.return_value = mock_wb

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.tree.rows = []
        mock_doc.program = "TEST"
        mock_doc.end_item = "TEST ITEM"
        mock_doc.revision = "A"
        mock_doc.source = "test"
        mock_doc.critical_items = []
        mock_doc.mua_required_items = []
        mock_doc.missing_criticality = []
        mock_doc.validate_completeness.return_value = []

        writer = MIULExcelWriter()
        output = BytesIO()
        writer.write(mock_doc, output)

        # Verify sheet creation
        assert mock_wb.create_sheet.call_count >= 2

    @patch("mira.miul.excel_writer.Workbook")
    def test_writes_headers(self, mock_wb_class):
        """Should write column headers to first row."""
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_wb.active = mock_ws
        mock_wb.create_sheet = MagicMock(return_value=MagicMock())
        mock_wb_class.return_value = mock_wb

        mock_doc = MagicMock()
        mock_doc.tree.rows = []
        mock_doc.program = "TEST"
        mock_doc.end_item = "TEST ITEM"
        mock_doc.revision = "A"
        mock_doc.source = "test"
        mock_doc.critical_items = []
        mock_doc.mua_required_items = []
        mock_doc.missing_criticality = []
        mock_doc.validate_completeness.return_value = []

        writer = MIULExcelWriter()
        writer.write(mock_doc, BytesIO())

        # Should have called cell() for header row
        assert mock_ws.cell.called


class TestMiulExcelWriterValidateRow:
    """Tests for row validation."""

    def test_warns_missing_criticality(self):
        """Should warn when criticality is missing."""
        writer = MIULExcelWriter()

        mock_row = MagicMock()
        mock_row.criticality = None
        mock_row.material_code = "12345"
        mock_row.has_rating_gap = False
        mock_row.mua_number = None

        issues = writer._validate_row(mock_row)

        assert len(issues) > 0
        severities = [i[0] for i in issues]
        assert "WARNING" in severities

    def test_errors_critical_missing_material(self):
        """Should error when critical item missing Material Code."""
        writer = MIULExcelWriter()

        mock_crit = MagicMock()
        mock_crit.category = 1

        mock_row = MagicMock()
        mock_row.criticality = mock_crit
        mock_row.material_code = None
        mock_row.has_rating_gap = False
        mock_row.mua_number = None

        issues = writer._validate_row(mock_row)

        severities = [i[0] for i in issues]
        assert "ERROR" in severities

    def test_warns_rating_gap_without_mua(self):
        """Should warn when rating gap has no MUA reference."""
        writer = MIULExcelWriter()

        mock_crit = MagicMock()
        mock_crit.category = 2

        mock_row = MagicMock()
        mock_row.criticality = mock_crit
        mock_row.material_code = "12345"
        mock_row.has_rating_gap = True
        mock_row.mua_number = None

        issues = writer._validate_row(mock_row)

        assert len(issues) > 0


# =============================================================================
# write_miul_excel Function Tests
# =============================================================================


class TestWriteMiulExcel:
    """Tests for write_miul_excel convenience function."""

    @patch("mira.miul.excel_writer.MIULExcelWriter")
    @patch("mira.miul.excel_writer.MIULDocument")
    def test_creates_document(self, mock_doc_class, mock_writer_class):
        """Should create MIULDocument from tree."""
        mock_tree = MagicMock()
        output = BytesIO()

        write_miul_excel(
            tree=mock_tree,
            program="ORION",
            end_item="SM Propulsion",
            output=output,
        )

        # Verify document was created
        mock_doc_class.assert_called_once()

    @patch("mira.miul.excel_writer.MIULExcelWriter")
    @patch("mira.miul.excel_writer.MIULDocument")
    def test_uses_writer(self, mock_doc_class, mock_writer_class):
        """Should use MIULExcelWriter to write."""
        mock_tree = MagicMock()
        output = BytesIO()

        write_miul_excel(
            tree=mock_tree,
            program="ORION",
            end_item="SM Propulsion",
            output=output,
        )

        # Verify writer was used
        mock_writer_class.assert_called_once()
        mock_writer_class.return_value.write.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
