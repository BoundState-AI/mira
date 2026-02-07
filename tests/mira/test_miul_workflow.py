#!/usr/bin/env python3
"""
Module: Test Miul Workflow
Purpose: MIUL Workflow Tests for BoundState

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
boto3 = pytest.importorskip("boto3", reason="boto3 required for workflow")
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd

sys.path.insert(0, r"C:\BoundState")

from mira.miul.workflow import (
    MIULWorkflow,
    get_miul_workflow,
    reset_workflow,
    MIUL_COLUMNS,
    RATING_COLUMNS,
    GAP_VALUES,
)


class TestWorkflowConstants:
    """Tests for workflow constants."""

    def test_miul_columns_complete(self):
        """MIUL should have all required columns."""
        # Check key columns exist
        assert "Index" in MIUL_COLUMNS
        assert "Parent" in MIUL_COLUMNS
        assert "Detail Drawing" in MIUL_COLUMNS
        assert "Designation" in MIUL_COLUMNS
        assert "Material Code" in MIUL_COLUMNS

    def test_rating_columns_match_jsc27301f(self):
        """Rating columns should match JSC 27301F Section 4.2.1."""
        expected = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]
        assert RATING_COLUMNS == expected

    def test_rating_columns_in_miul_columns(self):
        """All rating columns should be in MIUL columns."""
        for col in RATING_COLUMNS:
            assert col in MIUL_COLUMNS

    def test_gap_values_include_expected(self):
        """Gap values should include empty and unknown ratings."""
        assert "" in GAP_VALUES
        assert None in GAP_VALUES
        assert "U" in GAP_VALUES  # Unknown
        assert "I" in GAP_VALUES  # Incomplete
        assert "X" in GAP_VALUES  # Not tested


class TestWorkflowInit:
    """Tests for workflow initialization."""

    def test_default_initialization(self):
        """Should initialize with default services."""
        with patch("mira.miul.workflow.get_extractor_service"), \
             patch("mira.miul.workflow.get_enrichment_service"):
            workflow = MIULWorkflow()
            assert workflow._extractor is not None
            assert workflow._enrichment is not None
            assert workflow._tree_builder is not None

    def test_dependency_injection(self):
        """Should accept injected services."""
        mock_extractor = MagicMock()
        mock_enrichment = MagicMock()
        mock_tree_builder = MagicMock()

        workflow = MIULWorkflow(
            extractor_service=mock_extractor,
            enrichment_service=mock_enrichment,
            tree_builder=mock_tree_builder,
        )

        assert workflow._extractor is mock_extractor
        assert workflow._enrichment is mock_enrichment
        assert workflow._tree_builder is mock_tree_builder


class TestLookupMaterialCodes:
    """Tests for material code lookup step."""

    def test_skips_existing_codes(self):
        """Should not overwrite existing material codes."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Designation": ["7075-T6", "316L"],
            "Material Code": ["12345", ""],  # First has code, second doesn't
        })

        # Mock lookup service to avoid DB
        with patch("mira.miul.workflow.MATERIAL_LOOKUP_AVAILABLE", False):
            workflow._enrichment.find_material_code_by_designation.return_value = "99999"
            result_df, count = workflow.lookup_material_codes(df)

        # Should only have looked up the one without code
        assert result_df.at[0, "Material Code"] == "12345"  # Unchanged

    def test_counts_codes_found(self):
        """Should return count of codes found."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Designation": ["7075-T6", "316L", "UNKNOWN"],
            "Material Code": ["", "", ""],
        })

        with patch("mira.miul.workflow.MATERIAL_LOOKUP_AVAILABLE", False):
            workflow._enrichment.find_material_code_by_designation.side_effect = [
                "12345",  # Found
                "67890",  # Found
                None,     # Not found
            ]
            _, count = workflow.lookup_material_codes(df)

        assert count == 2


class TestFetchRatings:
    """Tests for ratings fetch step."""

    @patch("mira.miul.workflow.get_ratings_bulk")
    def test_uses_bulk_lookup(self, mock_bulk):
        """Should use bulk ratings lookup."""
        mock_bulk.return_value = {
            "12345": {"FLAM": "A", "SCC": "B"},
        }

        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Material Code": ["12345"],
            "FLAM": [""],
            "SCC": [""],
            "CORR": [""],
            "TVS": [""],
            "TOX": [""],
            "FS": [""],
        })

        result_df, stats = workflow.fetch_ratings(df)

        mock_bulk.assert_called_once()
        assert result_df.at[0, "FLAM"] == "A"
        assert result_df.at[0, "SCC"] == "B"

    @patch("mira.miul.workflow.get_ratings_bulk")
    def test_returns_stats(self, mock_bulk):
        """Should return enrichment statistics."""
        mock_bulk.return_value = {
            "12345": {"FLAM": "A"},
            "67890": {},
        }

        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Material Code": ["12345", "67890"],
            "FLAM": ["", ""],
            "SCC": ["", ""],
            "CORR": ["", ""],
            "TVS": ["", ""],
            "TOX": ["", ""],
            "FS": ["", ""],
        })

        _, stats = workflow.fetch_ratings(df)

        assert "total_materials" in stats
        assert "enriched_count" in stats
        assert "coverage_pct" in stats

    @patch("mira.miul.workflow.get_ratings_bulk")
    def test_handles_no_material_codes(self, mock_bulk):
        """Should handle case with no material codes."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Material Code": ["", None],
            "FLAM": ["", ""],
            "SCC": ["", ""],
            "CORR": ["", ""],
            "TVS": ["", ""],
            "TOX": ["", ""],
            "FS": ["", ""],
        })

        result_df, stats = workflow.fetch_ratings(df)

        mock_bulk.assert_not_called()
        assert stats["total_materials"] == 0


class TestIdentifyRatingGaps:
    """Tests for rating gap identification."""

    def test_identifies_empty_ratings_as_gaps(self):
        """Empty ratings should be identified as gaps."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Detail Drawing": ["DWG-001"],
            "Designation": ["316L"],
            "Material Code": ["12345"],
            "Line Number": [1],
            "FLAM": [""],
            "SCC": ["A"],
            "CORR": [""],
            "TVS": ["B"],
            "TOX": [""],
            "FS": ["A"],
        })

        gaps = workflow.identify_rating_gaps(df)

        assert len(gaps) == 1
        assert "FLAM" in gaps[0]["gaps"]
        assert "CORR" in gaps[0]["gaps"]
        assert "TOX" in gaps[0]["gaps"]
        assert "SCC" not in gaps[0]["gaps"]

    def test_identifies_unknown_ratings_as_gaps(self):
        """Unknown (U) and incomplete (I) should be gaps."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Detail Drawing": ["DWG-001"],
            "Designation": ["316L"],
            "Material Code": ["12345"],
            "Line Number": [1],
            "FLAM": ["U"],
            "SCC": ["I"],
            "CORR": ["A"],
            "TVS": ["X"],
            "TOX": ["N"],
            "FS": ["A"],
        })

        gaps = workflow.identify_rating_gaps(df)

        assert len(gaps) == 1
        gap_ratings = gaps[0]["gaps"]
        assert "FLAM" in gap_ratings
        assert "SCC" in gap_ratings
        assert "TVS" in gap_ratings
        assert "TOX" in gap_ratings

    def test_no_gaps_returns_empty(self):
        """Parts with complete ratings should not be in gaps."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "Detail Drawing": ["DWG-001"],
            "Designation": ["316L"],
            "Material Code": ["12345"],
            "Line Number": [1],
            "FLAM": ["A"],
            "SCC": ["A"],
            "CORR": ["A"],
            "TVS": ["A"],
            "TOX": ["A"],
            "FS": ["A"],
        })

        gaps = workflow.identify_rating_gaps(df)

        assert len(gaps) == 0


class TestApplyRationale:
    """Tests for rationale application."""

    def test_applies_rationale_code(self):
        """Should apply rationale code to MUA Rationale column."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "MUA Rationale": [""],
            "Remarks": [""],
        })

        resolutions = [
            {"index": 0, "rat_code": "403", "rat_text": "VCM is within limits"},
        ]

        result_df = workflow.apply_rationale(df, resolutions)

        assert result_df.at[0, "MUA Rationale"] == "403"
        assert "VCM" in result_df.at[0, "Remarks"]

    def test_appends_to_existing_rationale(self):
        """Should append to existing rationale."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "MUA Rationale": ["101"],
            "Remarks": ["Existing note"],
        })

        resolutions = [
            {"index": 0, "rat_code": "403"},
        ]

        result_df = workflow.apply_rationale(df, resolutions)

        assert "101" in result_df.at[0, "MUA Rationale"]
        assert "403" in result_df.at[0, "MUA Rationale"]

    def test_skips_invalid_index(self):
        """Should skip resolutions with invalid index."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({
            "MUA Rationale": [""],
            "Remarks": [""],
        })

        resolutions = [
            {"index": 999, "rat_code": "403"},  # Invalid index
        ]

        result_df = workflow.apply_rationale(df, resolutions)

        # Should not crash, rationale should be unchanged
        assert result_df.at[0, "MUA Rationale"] == ""


class TestTransformPartsToMiul:
    """Tests for parts transformation to MIUL format."""

    def test_creates_all_columns(self):
        """Should create all MIUL columns."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        parts = [
            {"part_number": "DWG-001", "material": "7075-T6"},
        ]

        df = workflow._transform_parts_to_miul(parts)

        for col in MIUL_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_maps_part_number_to_detail_drawing(self):
        """part_number should map to Detail Drawing."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        parts = [
            {"part_number": "ABC-123"},
        ]

        df = workflow._transform_parts_to_miul(parts)

        assert df.at[0, "Detail Drawing"] == "ABC-123"

    def test_maps_material_to_designation(self):
        """material should map to Designation."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        parts = [
            {"part_number": "DWG-001", "material": "7075-T6"},
        ]

        df = workflow._transform_parts_to_miul(parts)

        assert df.at[0, "Designation"] == "7075-T6"

    def test_supports_designation_key(self):
        """Should also support 'designation' key."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        parts = [
            {"part_number": "DWG-001", "designation": "316L SS"},
        ]

        df = workflow._transform_parts_to_miul(parts)

        assert df.at[0, "Designation"] == "316L SS"

    def test_preserves_tree_structure(self):
        """Should preserve Index/Parent from tree builder."""
        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        parts = [
            {"part_number": "A", "Index": 1, "Parent": 0},
            {"part_number": "B", "Index": 2, "Parent": 1},
        ]

        df = workflow._transform_parts_to_miul(parts)

        assert df.at[0, "Index"] == 1
        assert df.at[0, "Parent"] == 0
        assert df.at[1, "Index"] == 2
        assert df.at[1, "Parent"] == 1


class TestSingletonManagement:
    """Tests for singleton workflow management."""

    def test_get_returns_singleton(self):
        """get_miul_workflow should return same instance."""
        reset_workflow()

        with patch("mira.miul.workflow.get_extractor_service"), \
             patch("mira.miul.workflow.get_enrichment_service"):
            workflow1 = get_miul_workflow()
            workflow2 = get_miul_workflow()

            assert workflow1 is workflow2

        reset_workflow()

    def test_reset_clears_singleton(self):
        """reset_workflow should clear the singleton."""
        reset_workflow()

        with patch("mira.miul.workflow.get_extractor_service"), \
             patch("mira.miul.workflow.get_enrichment_service"):
            workflow1 = get_miul_workflow()
            reset_workflow()
            workflow2 = get_miul_workflow()

            # After reset, new instance should be created
            assert workflow1 is not workflow2

        reset_workflow()


class TestExportToExcel:
    """Tests for Excel export."""

    def test_returns_bytesio(self):
        """Should return BytesIO buffer."""
        from io import BytesIO

        workflow = MIULWorkflow(
            extractor_service=MagicMock(),
            enrichment_service=MagicMock(),
            tree_builder=MagicMock(),
        )

        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        result = workflow.export_to_excel(df)

        assert isinstance(result, BytesIO)
        assert result.getvalue()  # Should have content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
