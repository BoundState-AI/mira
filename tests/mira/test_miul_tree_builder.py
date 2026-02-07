#!/usr/bin/env python3
"""
Module: Test Miul Tree Builder
Purpose: Tests for MIUL tree builder.

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

from mira.miul.tree_builder import (
    BOMInputFormat,
    BOMRow,
    TreeBuilder,
    TreeBuildResult,
    build_miul_tree,
)
from mira.miul.schema import MIULTree


class TestBOMInputFormat:
    """Tests for BOM input format enum."""

    def test_all_formats_defined(self):
        """Verify all expected formats are defined."""
        formats = {f.value for f in BOMInputFormat}
        expected = {"parent_reference", "indented", "wbs_numbered", "flat"}
        assert formats == expected


class TestBOMRow:
    """Tests for BOM row input model."""

    def test_minimal_row(self):
        """Test creating minimal BOM row."""
        row = BOMRow(part_number="TEST-001")
        assert row.part_number == "TEST-001"
        assert row.parent_ref is None  # Uses parent_ref, not parent
        assert row.level is None

    def test_parent_reference_row(self):
        """Test BOM row with parent reference."""
        row = BOMRow(
            part_number="CHILD-001",
            parent_ref="PARENT-001",  # Uses parent_ref
            part_description="Child part",  # Uses part_description
        )
        assert row.parent_ref == "PARENT-001"
        assert row.part_description == "Child part"

    def test_indented_row(self):
        """Test BOM row with indentation level."""
        row = BOMRow(
            part_number="CHILD-001",
            level=2,
        )
        assert row.level == 2

    def test_wbs_row(self):
        """Test BOM row with WBS number."""
        row = BOMRow(
            part_number="CHILD-001",
            wbs="1.2.3",
        )
        assert row.wbs == "1.2.3"


class TestTreeBuilder:
    """Tests for TreeBuilder class."""

    def test_build_detects_parent_reference_format(self):
        """Test auto-detection of parent reference format via build result."""
        rows = [
            BOMRow(part_number="ROOT"),
            BOMRow(part_number="CHILD-1", parent_ref="ROOT"),
            BOMRow(part_number="CHILD-2", parent_ref="ROOT"),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)
        # Format detection is internal, verify via result
        assert result.detected_format == BOMInputFormat.PARENT_REFERENCE

    def test_build_detects_indented_format(self):
        """Test auto-detection of indented format via build result."""
        rows = [
            BOMRow(part_number="ROOT", level=0),
            BOMRow(part_number="CHILD-1", level=1),
            BOMRow(part_number="GRANDCHILD", level=2),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)
        assert result.detected_format == BOMInputFormat.INDENTED

    def test_build_detects_wbs_format(self):
        """Test auto-detection of WBS format via build result."""
        rows = [
            BOMRow(part_number="ROOT", wbs="1"),
            BOMRow(part_number="CHILD-1", wbs="1.1"),
            BOMRow(part_number="CHILD-2", wbs="1.2"),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)
        assert result.detected_format == BOMInputFormat.WBS_NUMBERED

    def test_build_detects_flat_format(self):
        """Test auto-detection of flat format via build result."""
        rows = [
            BOMRow(part_number="PART-1"),
            BOMRow(part_number="PART-2"),
            BOMRow(part_number="PART-3"),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)
        assert result.detected_format == BOMInputFormat.FLAT

    def test_build_from_parent_reference(self):
        """Test building tree from parent reference format."""
        rows = [
            BOMRow(part_number="ROOT"),
            BOMRow(part_number="CHILD-1", parent_ref="ROOT"),
            BOMRow(part_number="CHILD-2", parent_ref="ROOT"),
            BOMRow(part_number="GRANDCHILD", parent_ref="CHILD-1"),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)

        assert isinstance(result, TreeBuildResult)
        assert isinstance(result.tree, MIULTree)
        assert len(result.tree.rows) == 5  # 4 parts + EOF

        # Check parent relationships
        # First row is ROOT at index 1
        root = result.tree.rows[0]
        assert root.part_number == "ROOT"
        assert root.parent == 0  # Root has parent=0

    def test_build_from_indented(self):
        """Test building tree from indented format."""
        rows = [
            BOMRow(part_number="ROOT", level=0),
            BOMRow(part_number="CHILD-1", level=1),
            BOMRow(part_number="GRANDCHILD-1", level=2),
            BOMRow(part_number="CHILD-2", level=1),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)

        assert len(result.tree.rows) == 5  # 4 parts + EOF

    def test_build_from_wbs(self):
        """Test building tree from WBS numbered format."""
        rows = [
            BOMRow(part_number="ROOT", wbs="1"),
            BOMRow(part_number="CHILD-1", wbs="1.1"),
            BOMRow(part_number="CHILD-2", wbs="1.2"),
            BOMRow(part_number="GRANDCHILD", wbs="1.1.1"),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)

        assert len(result.tree.rows) == 5  # 4 parts + EOF

    def test_build_flat(self):
        """Test building tree from flat format (all at root level)."""
        rows = [
            BOMRow(part_number="PART-1"),
            BOMRow(part_number="PART-2"),
            BOMRow(part_number="PART-3"),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)

        # Flat: all parts at root level (parent=0)
        data_rows = [r for r in result.tree.rows if r.index != -1]
        assert all(row.parent == 0 for row in data_rows)

    def test_build_with_material_data(self):
        """Test that material data is preserved."""
        rows = [
            BOMRow(
                part_number="ROOT",
                material_code="MAT-6061",
                designation="6061-T6",
                manufacturer="ALCOA",
            ),
        ]
        builder = TreeBuilder()
        result = builder.build(rows)

        assert result.tree.rows[0].material_code == "MAT-6061"
        assert result.tree.rows[0].designation == "6061-T6"
        assert result.tree.rows[0].manufacturer == "ALCOA"


class TestBuildMIULTreeFunction:
    """Tests for the build_miul_tree convenience function."""

    def test_basic_usage(self):
        """Test basic usage of convenience function."""
        rows = [
            {"part_number": "ROOT"},
            {"part_number": "CHILD", "Parent": "ROOT"},
        ]
        result = build_miul_tree(rows)

        assert isinstance(result, TreeBuildResult)
        assert isinstance(result.tree, MIULTree)
        # First row should be ROOT
        assert result.tree.rows[0].part_number == "ROOT"

    def test_with_dict_rows(self):
        """Test with dictionary rows as input."""
        rows = [
            {"part_number": "ROOT"},
            {"part_number": "CHILD", "Parent": "ROOT"},
        ]
        result = build_miul_tree(rows, source="test")

        assert len(result.tree.rows) == 3  # 2 parts + EOF

    def test_empty_input_returns_empty_tree(self):
        """Test that empty input returns tree with just EOF."""
        result = build_miul_tree([])
        # Empty input returns tree with just EOF row
        assert len(result.tree.rows) == 1
        assert result.tree.rows[0].index == -1
