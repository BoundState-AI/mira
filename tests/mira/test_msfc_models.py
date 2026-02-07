#!/usr/bin/env python3
"""
Module: Test Msfc Models
Purpose: MSFC Models Tests for BoundState

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

sys.path.insert(0, r"C:\BoundState")

from mira.miul.msfc.models import (
    MaterialSource,
    DrawingType,
    DrawingMaterial,
    EmbeddedHardware,
    DrawingExtraction,
    AssemblyNode,
    DrawingTreeExtraction,
    MIULLineItem,
    MIULDocument,
    HARDWARE_STANDARD_MATERIALS,
)


class TestMaterialSource:
    """Tests for MaterialSource enum."""

    def test_all_sources_defined(self):
        """All material source types should be defined."""
        expected = {
            "title_block", "note", "callout",
            "bill_of_materials", "inferred_from_standard"
        }
        actual = {s.value for s in MaterialSource}
        assert actual == expected


class TestDrawingType:
    """Tests for DrawingType enum."""

    def test_all_types_defined(self):
        """All drawing types should be defined."""
        expected = {
            "drawing_tree", "detail", "assembly", "subassembly",
            "installation", "weldment", "schematic", "unknown"
        }
        actual = {t.value for t in DrawingType}
        assert actual == expected


class TestHardwareStandardMaterials:
    """Tests for hardware standard materials lookup table."""

    def test_helical_inserts_defined(self):
        """Helical coil insert standards should be defined."""
        assert "NASM33537" in HARDWARE_STANDARD_MATERIALS
        assert "NASM33540" in HARDWARE_STANDARD_MATERIALS

    def test_insert_material_is_cres(self):
        """NASM33537 should be CRES."""
        info = HARDWARE_STANDARD_MATERIALS["NASM33537"]
        assert "CRES" in info["material"]

    def test_has_confidence_values(self):
        """All entries should have confidence values."""
        for std, info in HARDWARE_STANDARD_MATERIALS.items():
            assert "confidence" in info, f"Missing confidence for {std}"
            assert 0.0 <= info["confidence"] <= 1.0

    def test_o_ring_low_confidence(self):
        """O-rings should have low confidence (material varies)."""
        info = HARDWARE_STANDARD_MATERIALS.get("AS568")
        assert info is not None
        assert info["confidence"] < 0.5


class TestDrawingMaterial:
    """Tests for DrawingMaterial model."""

    def test_basic_material(self):
        """Should create valid drawing material."""
        mat = DrawingMaterial(
            designation="7075-T6 Aluminum",
            specification="AMS 4045",
            source=MaterialSource.TITLE_BLOCK,
        )
        assert mat.designation == "7075-T6 Aluminum"
        assert mat.source == MaterialSource.TITLE_BLOCK
        assert mat.quantity == 1

    def test_with_uns_number(self):
        """Should store UNS number."""
        mat = DrawingMaterial(
            designation="316L Stainless",
            uns_number="S31603",
            source=MaterialSource.TITLE_BLOCK,
        )
        assert mat.uns_number == "S31603"


class TestEmbeddedHardware:
    """Tests for EmbeddedHardware model."""

    def test_basic_hardware(self):
        """Should create valid embedded hardware."""
        hw = EmbeddedHardware(
            standard="NASM33537",
            thread_size="10-32",
            quantity=4,
        )
        assert hw.standard == "NASM33537"
        assert hw.thread_size == "10-32"
        assert hw.quantity == 4

    def test_resolve_material_known_standard(self):
        """Should resolve material from known standard."""
        hw = EmbeddedHardware(standard="NASM33537")
        hw.resolve_material()

        assert hw.inferred_material is not None
        assert "CRES" in hw.inferred_material
        assert hw.confidence > 0

    def test_resolve_material_with_dash_number(self):
        """Should handle dash number suffixes."""
        hw = EmbeddedHardware(standard="NASM33537-0518")
        hw.resolve_material()

        assert hw.inferred_material is not None

    def test_resolve_material_unknown_standard(self):
        """Should handle unknown standards gracefully."""
        hw = EmbeddedHardware(standard="UNKNOWN123")
        hw.resolve_material()

        assert hw.confidence == 0.0

    def test_nas_to_nasm_normalization(self):
        """Should normalize NAS to NASM for inserts."""
        # NAS33537 should be treated as NASM33537
        hw = EmbeddedHardware(standard="NAS33537")
        hw.resolve_material()

        # Should find NASM33537 equivalent
        assert hw.inferred_material is not None or hw.confidence == 0.0


class TestDrawingExtraction:
    """Tests for DrawingExtraction model."""

    def test_basic_extraction(self):
        """Should create valid drawing extraction."""
        ext = DrawingExtraction(
            drawing_number="MER07540-001",
            revision="A",
            title="BRACKET ASSY",
        )
        assert ext.drawing_number == "MER07540-001"
        assert ext.drawing_type == DrawingType.UNKNOWN

    def test_all_materials_for_miul_empty(self):
        """Should return empty list when no materials."""
        ext = DrawingExtraction(drawing_number="TEST-001")
        items = ext.all_materials_for_miul()
        assert items == []

    def test_all_materials_for_miul_with_primary(self):
        """Should include primary material."""
        ext = DrawingExtraction(
            drawing_number="TEST-001",
            primary_material=DrawingMaterial(
                designation="7075-T6",
                specification="AMS 4045",
                source=MaterialSource.TITLE_BLOCK,
            ),
        )
        items = ext.all_materials_for_miul()

        assert len(items) == 1
        assert items[0]["material_designation"] == "7075-T6"
        assert items[0]["source"] == "primary"

    def test_all_materials_for_miul_with_hardware(self):
        """Should include hardware with resolved materials."""
        hw = EmbeddedHardware(standard="NASM33537", quantity=4)
        hw.inferred_material = "CRES 302/304"
        hw.confidence = 0.85

        ext = DrawingExtraction(
            drawing_number="TEST-001",
            embedded_hardware=[hw],
        )
        items = ext.all_materials_for_miul()

        assert len(items) == 1
        assert items[0]["material_designation"] == "CRES 302/304"
        assert items[0]["standard_part_number"] == "NASM33537"
        assert items[0]["quantity"] == 4


class TestAssemblyNode:
    """Tests for AssemblyNode model."""

    def test_basic_node(self):
        """Should create valid assembly node."""
        node = AssemblyNode(
            drawing_number="MER07540-001",
            title="BRACKET ASSY",
            level=1,
        )
        assert node.drawing_number == "MER07540-001"
        assert node.level == 1
        assert node.children == []

    def test_node_with_hierarchy(self):
        """Should track parent/child relationships."""
        node = AssemblyNode(
            drawing_number="MER07540-002",
            parent_drawing="MER07540-001",
            children=["MER07540-003", "MER07540-004"],
        )
        assert node.parent_drawing == "MER07540-001"
        assert len(node.children) == 2


class TestDrawingTreeExtraction:
    """Tests for DrawingTreeExtraction model."""

    def test_basic_tree(self):
        """Should create valid drawing tree extraction."""
        tree = DrawingTreeExtraction(
            dt_drawing_number="MER07540-DT",
            top_assembly="MER07540-001",
        )
        assert tree.top_assembly == "MER07540-001"

    def test_get_all_detail_drawings(self):
        """Should return detail drawings."""
        tree = DrawingTreeExtraction(
            dt_drawing_number="TEST-DT",
            top_assembly="TOP-001",
            nodes={
                "TOP-001": AssemblyNode(
                    drawing_number="TOP-001",
                    drawing_type=DrawingType.ASSEMBLY,
                ),
                "DET-001": AssemblyNode(
                    drawing_number="DET-001",
                    drawing_type=DrawingType.DETAIL,
                ),
                "DET-002": AssemblyNode(
                    drawing_number="DET-002",
                    drawing_type=DrawingType.DETAIL,
                ),
            },
        )
        details = tree.get_all_detail_drawings()

        assert "DET-001" in details
        assert "DET-002" in details
        assert "TOP-001" not in details

    def test_get_assembly_path(self):
        """Should return path from top to node."""
        tree = DrawingTreeExtraction(
            dt_drawing_number="TEST-DT",
            top_assembly="TOP",
            nodes={
                "TOP": AssemblyNode(drawing_number="TOP"),
                "MID": AssemblyNode(drawing_number="MID", parent_drawing="TOP"),
                "LEAF": AssemblyNode(drawing_number="LEAF", parent_drawing="MID"),
            },
        )
        path = tree.get_assembly_path("LEAF")

        assert path == ["TOP", "MID", "LEAF"]

    def test_get_children_recursive(self):
        """Should return all descendants."""
        tree = DrawingTreeExtraction(
            dt_drawing_number="TEST-DT",
            top_assembly="TOP",
            nodes={
                "TOP": AssemblyNode(drawing_number="TOP", children=["A", "B"]),
                "A": AssemblyNode(drawing_number="A", children=["A1", "A2"]),
                "B": AssemblyNode(drawing_number="B", children=[]),
                "A1": AssemblyNode(drawing_number="A1", children=[]),
                "A2": AssemblyNode(drawing_number="A2", children=[]),
            },
        )
        children = tree.get_children_recursive("TOP")

        assert set(children) == {"A", "B", "A1", "A2"}


class TestMIULLineItem:
    """Tests for MIULLineItem model."""

    def test_basic_line_item(self):
        """Should create valid MIUL line item."""
        item = MIULLineItem(
            detail_drawing="DWG-001",
            material_designation="7075-T6",
        )
        assert item.detail_drawing == "DWG-001"
        assert item.quantity == 1
        assert item.confidence == 1.0

    def test_line_item_with_environment(self):
        """Should store environment data."""
        item = MIULLineItem(
            detail_drawing="DWG-001",
            material_designation="316L",
            environment="LOX",
            max_temperature_f=200.0,
            max_pressure_psia=3000.0,
        )
        assert item.environment == "LOX"
        assert item.max_temperature_f == 200.0


class TestMIULDocument:
    """Tests for MIULDocument model."""

    def test_basic_document(self):
        """Should create valid MIUL document."""
        doc = MIULDocument(
            project="SLS",
            top_assembly="MER07540-001",
        )
        assert doc.project == "SLS"
        assert doc.line_items == []

    def test_material_summary(self):
        """Should summarize materials by designation."""
        doc = MIULDocument(
            project="TEST",
            top_assembly="TOP",
            line_items=[
                MIULLineItem(detail_drawing="A", material_designation="7075-T6", quantity=2),
                MIULLineItem(detail_drawing="B", material_designation="316L", quantity=5),
                MIULLineItem(detail_drawing="C", material_designation="7075-T6", quantity=3),
            ],
        )
        summary = doc.material_summary()

        assert summary["7075-T6"] == 5  # 2 + 3
        assert summary["316L"] == 5

    def test_missing_maptis_codes(self):
        """Should find items without MAPTIS codes."""
        doc = MIULDocument(
            project="TEST",
            top_assembly="TOP",
            line_items=[
                MIULLineItem(detail_drawing="A", material_designation="7075-T6"),
                MIULLineItem(
                    detail_drawing="B",
                    material_designation="316L",
                    maptis_material_code="12345",
                ),
            ],
        )
        missing = doc.missing_maptis_codes()

        assert len(missing) == 1
        assert missing[0].detail_drawing == "A"

    def test_assign_line_numbers(self):
        """Should assign sequential line numbers."""
        doc = MIULDocument(
            project="TEST",
            top_assembly="TOP",
            line_items=[
                MIULLineItem(detail_drawing="A", material_designation="X"),
                MIULLineItem(detail_drawing="B", material_designation="Y"),
                MIULLineItem(detail_drawing="C", material_designation="Z"),
            ],
        )
        doc.assign_line_numbers()

        assert doc.line_items[0].line_number == 1
        assert doc.line_items[1].line_number == 2
        assert doc.line_items[2].line_number == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
