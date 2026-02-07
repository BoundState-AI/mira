#!/usr/bin/env python3
"""
Module: Test Miul V2 Miul
Purpose: MIUL Builder v2.2 - Unit Tests for miul.py

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
from pathlib import Path

from mira.miul.v2.models import (
    BOMRow,
    DrawingEntity,
    DrawingGraph,
    DrawingKey,
    ExplosionPolicy,
    GraphEdge,
    Issue,
    IssueSeverity,
    IssueType,
    MIULEntry,
    NodeType,
    PackageExtract,
    PageBinding,
    BindingMethod,
    BindingConfidence,
)
from mira.miul.v2.miul import (
    traverse_tree,
    generate_miul_entries,
    deduplicate_miul_entries,
    generate_miul,
    build_evidence_chain,
    LEAF_NODE_TYPES,
)


# =============================================================================
# Test Fixtures
# =============================================================================

def create_mock_entity(
    drawing_number: str,
    title: str = "",
    parts_list: list[BOMRow] = None,
    node_type: NodeType = NodeType.ASSEMBLY,
) -> tuple[DrawingKey, DrawingEntity]:
    """Create a mock DrawingEntity for testing."""
    key = DrawingKey(drawing_number=drawing_number)
    entity = DrawingEntity(key=key, title=title, node_type=node_type)

    entity.pages_primary.append(PageBinding(
        page_id=f"page_{drawing_number}",
        binding_score=100.0,
        binding_method=BindingMethod.TITLE_BLOCK,
        binding_confidence=BindingConfidence.HIGH,
    ))

    if parts_list:
        entity.parts_list = parts_list

    return key, entity


def create_simple_tree() -> DrawingGraph:
    """
    Create a simple tree for testing:

    ROOT
    ├── SUBASSY (qty=2)
    │   ├── PART-A (qty=3, PIECE_PART)
    │   └── NAS1149 (qty=4, STANDARD - BLACK_BOX)
    └── PART-B (qty=1, PIECE_PART)
    """
    root_key, root_entity = create_mock_entity(
        "ROOT",
        title="ROOT ASSEMBLY",
        parts_list=[
            BOMRow(find_no="1", part_number="SUBASSY", quantity=2),
            BOMRow(find_no="2", part_number="PART-B", quantity=1, material_callout="AL 6061"),
        ],
    )

    sub_key, sub_entity = create_mock_entity(
        "SUBASSY",
        title="SUB ASSEMBLY",
        parts_list=[
            BOMRow(find_no="1", part_number="PART-A", quantity=3, material_callout="STEEL 4130"),
            BOMRow(find_no="2", part_number="NAS1149", quantity=4),
        ],
    )

    part_a_key, part_a_entity = create_mock_entity(
        "PART-A",
        title="PIECE PART A",
        node_type=NodeType.PIECE_PART,
    )

    part_b_key, part_b_entity = create_mock_entity(
        "PART-B",
        title="PIECE PART B",
        node_type=NodeType.PIECE_PART,
    )

    nas_key, nas_entity = create_mock_entity(
        "NAS1149",
        title="WASHER",
        node_type=NodeType.STANDARD,
    )

    graph = DrawingGraph(
        root=root_key,
        nodes={
            root_key: root_entity,
            sub_key: sub_entity,
            part_a_key: part_a_entity,
            part_b_key: part_b_entity,
            nas_key: nas_entity,
        },
        edges=[
            GraphEdge(parent=root_key, child=sub_key, find_no="1", qty_per_parent=2, explosion_policy=ExplosionPolicy.EXPLODE),
            GraphEdge(parent=root_key, child=part_b_key, find_no="2", qty_per_parent=1, explosion_policy=ExplosionPolicy.EXPLODE),
            GraphEdge(parent=sub_key, child=part_a_key, find_no="1", qty_per_parent=3, explosion_policy=ExplosionPolicy.EXPLODE),
            GraphEdge(parent=sub_key, child=nas_key, find_no="2", qty_per_parent=4, explosion_policy=ExplosionPolicy.BLACK_BOX),
        ],
    )

    return graph


# =============================================================================
# Test Evidence Chain Building
# =============================================================================

class TestEvidenceChain:
    """Test evidence chain building."""

    def test_basic_evidence_chain(self):
        """Evidence chain should include drawing, page, and row."""
        key = DrawingKey(drawing_number="MER07540-001")
        page_ids = ["page001", "page002"]

        chain = build_evidence_chain(key, page_ids, row_index=5)

        assert "drawing:MER07540-001" in chain
        assert "page:page001" in chain
        assert "row:5" in chain

    def test_evidence_chain_without_row(self):
        """Evidence chain without row_index should omit row."""
        key = DrawingKey(drawing_number="MER07540-001")
        page_ids = ["page001"]

        chain = build_evidence_chain(key, page_ids)

        assert "drawing:MER07540-001" in chain
        assert any("row:" in c for c in chain) is False


# =============================================================================
# Test Tree Traversal
# =============================================================================

class TestTreeTraversal:
    """Test DFS tree traversal with explosion policies."""

    def test_traverse_collects_leaf_items(self):
        """Traversal should collect all leaf items."""
        graph = create_simple_tree()

        leaves = list(traverse_tree(graph, graph.root))

        # Should have PART-A, PART-B, and NAS1149
        part_numbers = [leaf.part_number for leaf in leaves]
        assert "PART-A" in part_numbers
        assert "PART-B" in part_numbers
        assert "NAS1149" in part_numbers

    def test_traverse_skips_subassemblies(self):
        """Traversal should NOT include subassemblies as leaf items."""
        graph = create_simple_tree()

        leaves = list(traverse_tree(graph, graph.root))

        part_numbers = [leaf.part_number for leaf in leaves]
        assert "SUBASSY" not in part_numbers
        assert "ROOT" not in part_numbers

    def test_quantity_multiplication(self):
        """Quantities should multiply through the tree."""
        graph = create_simple_tree()

        leaves = list(traverse_tree(graph, graph.root))

        # PART-A: qty=3 under SUBASSY, SUBASSY qty=2 under ROOT → 3*2=6
        part_a = next(l for l in leaves if l.part_number == "PART-A")
        assert part_a.quantity == 6

        # PART-B: qty=1 directly under ROOT → 1
        part_b = next(l for l in leaves if l.part_number == "PART-B")
        assert part_b.quantity == 1

        # NAS1149: qty=4 under SUBASSY, SUBASSY qty=2 → 4*2=8
        nas = next(l for l in leaves if l.part_number == "NAS1149")
        assert nas.quantity == 8


class TestExplosionPolicies:
    """Test per-edge explosion policies."""

    def test_explode_policy_recurses(self):
        """EXPLODE policy should recurse into children."""
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[BOMRow(find_no="1", part_number="CHILD", quantity=1)],
        )
        child_key, child_entity = create_mock_entity(
            "CHILD",
            parts_list=[BOMRow(find_no="1", part_number="GRANDCHILD", quantity=1, material_callout="AL")],
        )
        grandchild_key, grandchild_entity = create_mock_entity(
            "GRANDCHILD",
            node_type=NodeType.PIECE_PART,
        )

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, child_key: child_entity, grandchild_key: grandchild_entity},
            edges=[
                GraphEdge(parent=root_key, child=child_key, qty_per_parent=1, explosion_policy=ExplosionPolicy.EXPLODE),
                GraphEdge(parent=child_key, child=grandchild_key, qty_per_parent=1, explosion_policy=ExplosionPolicy.EXPLODE),
            ],
        )

        leaves = list(traverse_tree(graph, graph.root))
        part_numbers = [l.part_number for l in leaves]

        assert "GRANDCHILD" in part_numbers  # Should have recursed

    def test_black_box_stops_recursion(self):
        """BLACK_BOX policy should stop recursion and include node as leaf."""
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[BOMRow(find_no="1", part_number="BLACK_BOX_PART", quantity=1)],
        )
        bb_key, bb_entity = create_mock_entity(
            "BLACK_BOX_PART",
            title="PURCHASED ASSEMBLY",
            parts_list=[BOMRow(find_no="1", part_number="INTERNAL_PART", quantity=5)],  # Should NOT be reached
        )
        internal_key, internal_entity = create_mock_entity(
            "INTERNAL_PART",
            node_type=NodeType.PIECE_PART,
        )

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, bb_key: bb_entity, internal_key: internal_entity},
            edges=[
                GraphEdge(parent=root_key, child=bb_key, qty_per_parent=1, explosion_policy=ExplosionPolicy.BLACK_BOX),
                GraphEdge(parent=bb_key, child=internal_key, qty_per_parent=5, explosion_policy=ExplosionPolicy.EXPLODE),
            ],
        )

        leaves = list(traverse_tree(graph, graph.root))
        part_numbers = [l.part_number for l in leaves]

        assert "BLACK_BOX_PART" in part_numbers  # Should include as leaf
        assert "INTERNAL_PART" not in part_numbers  # Should NOT recurse into

    def test_phantom_skips_node(self):
        """PHANTOM policy should skip node and recurse into children."""
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[BOMRow(find_no="1", part_number="PHANTOM_NODE", quantity=2)],
        )
        phantom_key, phantom_entity = create_mock_entity(
            "PHANTOM_NODE",
            parts_list=[BOMRow(find_no="1", part_number="ACTUAL_PART", quantity=3, material_callout="STEEL")],
        )
        actual_key, actual_entity = create_mock_entity(
            "ACTUAL_PART",
            node_type=NodeType.PIECE_PART,
        )

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, phantom_key: phantom_entity, actual_key: actual_entity},
            edges=[
                GraphEdge(parent=root_key, child=phantom_key, qty_per_parent=2, explosion_policy=ExplosionPolicy.PHANTOM),
                GraphEdge(parent=phantom_key, child=actual_key, qty_per_parent=3, explosion_policy=ExplosionPolicy.EXPLODE),
            ],
        )

        leaves = list(traverse_tree(graph, graph.root))
        part_numbers = [l.part_number for l in leaves]

        assert "PHANTOM_NODE" not in part_numbers  # Should NOT include phantom
        assert "ACTUAL_PART" in part_numbers  # Should include its children

        # Quantity should multiply through phantom: 2 * 3 = 6
        actual = next(l for l in leaves if l.part_number == "ACTUAL_PART")
        assert actual.quantity == 6


# =============================================================================
# Test MIUL Entry Generation
# =============================================================================

class TestMIULGeneration:
    """Test MIUL entry generation."""

    def test_generate_miul_entries_basic(self):
        """generate_miul_entries should create entries for all leaf items."""
        graph = create_simple_tree()

        entries, issues = generate_miul_entries(graph)

        assert len(entries) >= 3  # PART-A, PART-B, NAS1149

        part_numbers = [e.part_number for e in entries]
        assert "PART-A" in part_numbers
        assert "PART-B" in part_numbers
        assert "NAS1149" in part_numbers

    def test_entries_have_correct_quantities(self):
        """MIUL entries should have rolled-up quantities."""
        graph = create_simple_tree()

        entries, issues = generate_miul_entries(graph)

        part_a = next(e for e in entries if e.part_number == "PART-A")
        assert part_a.qty_per_top == 6  # 3 * 2

        part_b = next(e for e in entries if e.part_number == "PART-B")
        assert part_b.qty_per_top == 1

    def test_entries_have_evidence_chain(self):
        """MIUL entries should have evidence chains."""
        graph = create_simple_tree()

        entries, issues = generate_miul_entries(graph)

        for entry in entries:
            assert len(entry.evidence_chain) > 0

    def test_missing_material_creates_warning(self):
        """Piece part without material should create WARNING."""
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[BOMRow(find_no="1", part_number="NO_MATERIAL_PART", quantity=1)],
        )
        part_key, part_entity = create_mock_entity(
            "NO_MATERIAL_PART",
            node_type=NodeType.PIECE_PART,
        )

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, part_key: part_entity},
            edges=[
                GraphEdge(parent=root_key, child=part_key, qty_per_parent=1, explosion_policy=ExplosionPolicy.EXPLODE),
            ],
        )

        entries, issues = generate_miul_entries(graph)

        # Should have LOW_CONFIDENCE warning for missing material
        material_issues = [i for i in issues if i.issue_type == IssueType.LOW_CONFIDENCE]
        assert len(material_issues) >= 1


# =============================================================================
# Test Deduplication
# =============================================================================

class TestDeduplication:
    """Test MIUL entry deduplication."""

    def test_dedup_sums_quantities(self):
        """Deduplication should sum quantities for same part."""
        entries = [
            MIULEntry(index=1, part_number="PART-A", qty_per_top=5),
            MIULEntry(index=2, part_number="PART-B", qty_per_top=3),
            MIULEntry(index=3, part_number="PART-A", qty_per_top=7),  # Duplicate
        ]

        deduped = deduplicate_miul_entries(entries)

        assert len(deduped) == 2

        part_a = next(e for e in deduped if e.part_number == "PART-A")
        assert part_a.qty_per_top == 12  # 5 + 7

    def test_dedup_preserves_first_metadata(self):
        """Deduplication should preserve first occurrence's metadata."""
        entries = [
            MIULEntry(index=1, part_number="PART-A", qty_per_top=5, material="STEEL"),
            MIULEntry(index=2, part_number="PART-A", qty_per_top=7, material="ALUMINUM"),  # Different material
        ]

        deduped = deduplicate_miul_entries(entries)

        part_a = deduped[0]
        assert part_a.material == "STEEL"  # First occurrence

    def test_dedup_reindexes(self):
        """Deduplication should reindex entries."""
        entries = [
            MIULEntry(index=5, part_number="PART-A", qty_per_top=1),
            MIULEntry(index=10, part_number="PART-B", qty_per_top=1),
            MIULEntry(index=15, part_number="PART-A", qty_per_top=1),
        ]

        deduped = deduplicate_miul_entries(entries)

        indices = [e.index for e in deduped]
        assert indices == [1, 2]


# =============================================================================
# Test Generate MIUL (Integration)
# =============================================================================

class TestGenerateMIULIntegration:
    """Integration tests for generate_miul()."""

    def test_generate_miul_from_package(self):
        """generate_miul should work with PackageExtract."""
        graph = create_simple_tree()

        package = PackageExtract(
            package_id="test-001",
            graph=graph,
        )

        result = generate_miul(package, deduplicate=True)

        assert len(result.miul) >= 3
        assert not result.has_blockers

    def test_generate_miul_without_graph_creates_blocker(self):
        """generate_miul without graph should create BLOCKER."""
        package = PackageExtract(
            package_id="test-002",
            graph=None,  # No graph!
        )

        result = generate_miul(package)

        assert result.has_blockers
        graph_issues = [i for i in result.issues if i.issue_type == IssueType.GRAPH_MISMATCH]
        assert len(graph_issues) >= 1

    def test_generate_miul_respects_dedupe_flag(self):
        """deduplicate flag should control deduplication."""
        # Create tree with duplicate parts
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[
                BOMRow(find_no="1", part_number="SUBASSY-1", quantity=1),
                BOMRow(find_no="2", part_number="SUBASSY-2", quantity=1),
            ],
        )
        sub1_key, sub1_entity = create_mock_entity(
            "SUBASSY-1",
            parts_list=[BOMRow(find_no="1", part_number="COMMON-PART", quantity=2, material_callout="AL")],
        )
        sub2_key, sub2_entity = create_mock_entity(
            "SUBASSY-2",
            parts_list=[BOMRow(find_no="1", part_number="COMMON-PART", quantity=3, material_callout="AL")],
        )
        common_key, common_entity = create_mock_entity(
            "COMMON-PART",
            node_type=NodeType.PIECE_PART,
        )

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, sub1_key: sub1_entity, sub2_key: sub2_entity, common_key: common_entity},
            edges=[
                GraphEdge(parent=root_key, child=sub1_key, qty_per_parent=1, explosion_policy=ExplosionPolicy.EXPLODE),
                GraphEdge(parent=root_key, child=sub2_key, qty_per_parent=1, explosion_policy=ExplosionPolicy.EXPLODE),
                GraphEdge(parent=sub1_key, child=common_key, qty_per_parent=2, explosion_policy=ExplosionPolicy.EXPLODE),
                GraphEdge(parent=sub2_key, child=common_key, qty_per_parent=3, explosion_policy=ExplosionPolicy.EXPLODE),
            ],
        )

        package = PackageExtract(package_id="test-003", graph=graph)

        # With dedup
        result_dedup = generate_miul(PackageExtract(package_id="dedup", graph=graph), deduplicate=True)
        common_entries = [e for e in result_dedup.miul if e.part_number == "COMMON-PART"]
        assert len(common_entries) == 1
        assert common_entries[0].qty_per_top == 5  # 2 + 3

        # Without dedup
        result_no_dedup = generate_miul(PackageExtract(package_id="no-dedup", graph=graph), deduplicate=False)
        common_entries_no = [e for e in result_no_dedup.miul if e.part_number == "COMMON-PART"]
        assert len(common_entries_no) == 2  # Separate entries


# =============================================================================
# Test Leaf Node Types
# =============================================================================

class TestLeafNodeTypes:
    """Test LEAF_NODE_TYPES constant."""

    def test_leaf_types_include_expected(self):
        """LEAF_NODE_TYPES should include all leaf types."""
        assert NodeType.PIECE_PART in LEAF_NODE_TYPES
        assert NodeType.HARDWARE in LEAF_NODE_TYPES
        assert NodeType.PURCHASED in LEAF_NODE_TYPES
        assert NodeType.STANDARD in LEAF_NODE_TYPES

    def test_leaf_types_exclude_assemblies(self):
        """LEAF_NODE_TYPES should NOT include assemblies."""
        assert NodeType.ASSEMBLY not in LEAF_NODE_TYPES
        assert NodeType.SUBASSEMBLY not in LEAF_NODE_TYPES


# =============================================================================
# Test Material Fallback to Title Block
# =============================================================================

class TestMaterialFallback:
    """Test material fallback from EPL to detail drawing title block."""

    def test_material_fallback_to_detail_drawing(self):
        """When EPL has no material, use detail drawing's title block material."""
        # ROOT assembly with part that has NO material in EPL
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[
                BOMRow(find_no="1", part_number="DETAIL-PART", quantity=1),
                # Note: NO material_callout
            ],
        )

        # DETAIL-PART has material in its own title block (via entity.material_designation)
        detail_key, detail_entity = create_mock_entity(
            "DETAIL-PART",
            title="CAP, ACTUATOR",
            node_type=NodeType.PIECE_PART,
        )
        detail_entity.material_designation = "INCONEL 625"
        detail_entity.material_spec = "SAE AMS 5666"
        detail_entity.uns_number = "UNS N06625"

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, detail_key: detail_entity},
            edges=[
                GraphEdge(
                    parent=root_key,
                    child=detail_key,
                    qty_per_parent=1,
                    explosion_policy=ExplosionPolicy.EXPLODE,
                ),
            ],
        )

        entries, issues = generate_miul_entries(graph)

        # Should have one entry for DETAIL-PART with INCONEL 625 material
        assert len(entries) == 1
        assert entries[0].part_number == "DETAIL-PART"
        assert entries[0].material == "INCONEL 625"
        assert entries[0].spec == "SAE AMS 5666"

        # Should NOT have a "missing material" warning since we found material in title block
        material_issues = [i for i in issues if "Missing material" in i.message]
        assert len(material_issues) == 0

    def test_epl_material_takes_precedence(self):
        """EPL material should take precedence over title block material."""
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[
                BOMRow(
                    find_no="1",
                    part_number="DETAIL-PART",
                    quantity=1,
                    material_callout="INCONEL 718",  # EPL has material
                    spec_callout="AMS 5662",
                ),
            ],
        )

        # DETAIL-PART also has material in title block (different)
        detail_key, detail_entity = create_mock_entity(
            "DETAIL-PART",
            title="HOUSING",
            node_type=NodeType.PIECE_PART,
        )
        detail_entity.material_designation = "INCONEL 625"  # Different from EPL
        detail_entity.material_spec = "SAE AMS 5666"

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, detail_key: detail_entity},
            edges=[
                GraphEdge(
                    parent=root_key,
                    child=detail_key,
                    qty_per_parent=1,
                    explosion_policy=ExplosionPolicy.EXPLODE,
                ),
            ],
        )

        entries, issues = generate_miul_entries(graph)

        # Should use EPL material (INCONEL 718), not title block (INCONEL 625)
        assert len(entries) == 1
        assert entries[0].material == "INCONEL 718"
        assert entries[0].spec == "AMS 5662"

    def test_no_material_anywhere_creates_warning(self):
        """If neither EPL nor title block has material, should create warning."""
        root_key, root_entity = create_mock_entity(
            "ROOT",
            parts_list=[
                BOMRow(find_no="1", part_number="BLANK-PART", quantity=1),
            ],
        )

        # BLANK-PART has NO material in title block either
        blank_key, blank_entity = create_mock_entity(
            "BLANK-PART",
            title="UNKNOWN PART",
            node_type=NodeType.PIECE_PART,
        )
        # No material_designation set

        graph = DrawingGraph(
            root=root_key,
            nodes={root_key: root_entity, blank_key: blank_entity},
            edges=[
                GraphEdge(
                    parent=root_key,
                    child=blank_key,
                    qty_per_parent=1,
                    explosion_policy=ExplosionPolicy.EXPLODE,
                ),
            ],
        )

        entries, issues = generate_miul_entries(graph)

        # Should have warning about missing material
        material_issues = [i for i in issues if i.issue_type == IssueType.LOW_CONFIDENCE]
        assert len(material_issues) >= 1
        assert "BLANK-PART" in material_issues[0].affected

        # Should still have entry with "MATERIAL TBD"
        assert entries[0].material == "MATERIAL TBD"
