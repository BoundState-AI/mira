#!/usr/bin/env python3
"""
Module: Test Miul V2 Graph
Purpose: MIUL Builder v2.2 - Unit Tests for graph.py

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
    DrawingKey,
    ExplosionPolicy,
    GraphEdge,
    Issue,
    IssueSeverity,
    IssueType,
    NodeType,
    PackageExtract,
    PageBinding,
    BindingMethod,
    BindingConfidence,
)
from mira.miul.v2.graph import (
    is_standard_hardware,
    classify_node_type,
    determine_explosion_policy,
    build_graph_from_entities,
    select_root,
    get_leaf_nodes,
    get_path_to_root,
    calculate_total_quantity,
    detect_dt_pdf,
    STANDARD_HARDWARE_PREFIXES,
)


# =============================================================================
# Test Fixtures
# =============================================================================

def create_mock_entity(
    drawing_number: str,
    revision: str = None,
    parts_list: list[BOMRow] = None,
    has_pages: bool = True,
) -> tuple[DrawingKey, DrawingEntity]:
    """Create a mock DrawingEntity for testing."""
    key = DrawingKey(drawing_number=drawing_number, revision=revision)
    entity = DrawingEntity(key=key)

    if has_pages:
        entity.pages_primary.append(PageBinding(
            page_id=f"page_{drawing_number}",
            binding_score=100.0,
            binding_method=BindingMethod.TITLE_BLOCK,
            binding_confidence=BindingConfidence.HIGH,
        ))

    if parts_list:
        entity.parts_list = parts_list

    return key, entity


# =============================================================================
# Test Standard Hardware Detection
# =============================================================================

class TestStandardHardwareDetection:
    """Test is_standard_hardware() function."""

    @pytest.mark.parametrize("part_number,expected", [
        ("NAS1149", True),
        ("NAS1352-3-8", True),
        ("MS21042-3", True),
        ("MS24665-1", True),
        ("AN960-10", True),
        ("AN3-4A", True),
        ("AS3236-06", True),
        ("NASM21042-03", True),
        ("HCC-1000-8", True),
        ("BAC1234", True),
        # Non-standard hardware
        ("MER07540-001", False),
        ("PART-12345", False),
        ("01-885-06K", False),
        ("16007", False),
        ("CUSTOM-BOLT", False),
        # Edge cases
        ("NAS", False),  # No digits after prefix
        ("nas1149", True),  # Lowercase should work
        ("Ms21042", True),  # Mixed case
    ])
    def test_standard_hardware_patterns(self, part_number, expected):
        """Test various standard hardware patterns."""
        assert is_standard_hardware(part_number) == expected

    def test_all_prefixes_recognized(self):
        """All defined prefixes should be recognized."""
        for prefix in STANDARD_HARDWARE_PREFIXES:
            part_number = f"{prefix}12345"
            assert is_standard_hardware(part_number), f"{prefix} prefix should be recognized"


# =============================================================================
# Test Node Type Classification
# =============================================================================

class TestNodeTypeClassification:
    """Test classify_node_type() function."""

    def test_assembly_has_children(self):
        """Drawing with children should be ASSEMBLY."""
        key, entity = create_mock_entity("MER07540-001")
        node_type = classify_node_type("MER07540-001", entity, has_children=True)
        assert node_type == NodeType.ASSEMBLY

    def test_standard_hardware_no_children(self):
        """Standard hardware should be STANDARD type."""
        key, entity = create_mock_entity("NAS1149-12")
        node_type = classify_node_type("NAS1149-12", entity, has_children=False)
        assert node_type == NodeType.STANDARD

    def test_piece_part_with_pages(self):
        """Drawing with pages but no children should be PIECE_PART."""
        key, entity = create_mock_entity("MER07545-001", has_pages=True)
        node_type = classify_node_type("MER07545-001", entity, has_children=False)
        assert node_type == NodeType.PIECE_PART

    def test_purchased_no_pages(self):
        """Drawing without pages should be PURCHASED."""
        key, entity = create_mock_entity("VENDOR-PART-123", has_pages=False)
        node_type = classify_node_type("VENDOR-PART-123", entity, has_children=False)
        assert node_type == NodeType.PURCHASED

    def test_assembly_beats_standard_hardware(self):
        """Even standard hardware with children should be ASSEMBLY."""
        # Edge case: someone made an assembly drawing for standard hardware
        key, entity = create_mock_entity("NAS1149-KIT")
        node_type = classify_node_type("NAS1149-KIT", entity, has_children=True)
        assert node_type == NodeType.ASSEMBLY


# =============================================================================
# Test Explosion Policy Assignment
# =============================================================================

class TestExplosionPolicy:
    """Test determine_explosion_policy() function."""

    def test_standard_hardware_is_black_box(self):
        """Standard hardware should always be BLACK_BOX."""
        child_key = DrawingKey(drawing_number="NAS1149-12")
        entities = {}  # Empty - no entity needed for standard hardware

        policy = determine_explosion_policy(child_key, entities)
        assert policy == ExplosionPolicy.BLACK_BOX

    def test_entity_with_pages_explodes(self):
        """Entity with pages should EXPLODE."""
        child_key, entity = create_mock_entity("MER07545-001", has_pages=True)
        entities = {child_key: entity}

        policy = determine_explosion_policy(child_key, entities)
        assert policy == ExplosionPolicy.EXPLODE

    def test_entity_without_pages_is_black_box(self):
        """Entity without pages should be BLACK_BOX."""
        child_key, entity = create_mock_entity("VENDOR-PART", has_pages=False)
        entities = {child_key: entity}

        policy = determine_explosion_policy(child_key, entities)
        assert policy == ExplosionPolicy.BLACK_BOX

    def test_missing_entity_is_black_box(self):
        """Missing entity (not in dict) should be BLACK_BOX."""
        child_key = DrawingKey(drawing_number="UNKNOWN-PART")
        entities = {}

        policy = determine_explosion_policy(child_key, entities)
        assert policy == ExplosionPolicy.BLACK_BOX


# =============================================================================
# Test Root Selection
# =============================================================================

class TestRootSelection:
    """Test select_root() function."""

    def test_explicit_root_takes_priority(self):
        """Explicit root should be selected even if not max out-degree."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("MER07540-001")
        key2, entity2 = create_mock_entity("MER07545-001")

        graph = DrawingGraph(
            nodes={key1: entity1, key2: entity2},
            edges=[
                GraphEdge(parent=key1, child=key2),
            ],
        )

        # key1 has more out-degree, but we explicitly want key2
        root = select_root(graph, explicit_root="MER07545-001")
        assert root.drawing_number == "MER07545-001"

    def test_single_orphan_is_root(self):
        """Single node with no parent should be root."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("MER07540-001")
        key2, entity2 = create_mock_entity("MER07545-001")

        graph = DrawingGraph(
            nodes={key1: entity1, key2: entity2},
            edges=[
                GraphEdge(parent=key1, child=key2),
            ],
        )

        root = select_root(graph)
        assert root.drawing_number == "MER07540-001"  # key2 has parent, key1 doesn't

    def test_max_out_degree_wins_tie(self):
        """When multiple orphans, max out-degree wins."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("MER07540-001")
        key2, entity2 = create_mock_entity("MER07541-001")
        key3, entity3 = create_mock_entity("MER07545-001")
        key4, entity4 = create_mock_entity("MER07546-001")

        # key1 has 2 children, key2 has 1 child, both are orphans
        graph = DrawingGraph(
            nodes={key1: entity1, key2: entity2, key3: entity3, key4: entity4},
            edges=[
                GraphEdge(parent=key1, child=key3),
                GraphEdge(parent=key1, child=key4),
                GraphEdge(parent=key2, child=key3),  # key3 has two parents
            ],
        )

        root = select_root(graph)
        # key1 has out-degree 2, key2 has out-degree 1
        assert root.drawing_number == "MER07540-001"


# =============================================================================
# Test Cycle Detection
# =============================================================================

class TestCycleDetection:
    """Test cycle detection in graph."""

    def test_no_cycles_in_tree(self):
        """Normal tree structure should have no cycles."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("ROOT")
        key2, entity2 = create_mock_entity("CHILD1")
        key3, entity3 = create_mock_entity("CHILD2")

        graph = DrawingGraph(
            nodes={key1: entity1, key2: entity2, key3: entity3},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key1, child=key3),
            ],
        )

        cycles = graph.detect_cycles()
        assert len(cycles) == 0

    def test_direct_cycle_detected(self):
        """Direct cycle (A -> B -> A) should be detected."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("A")
        key2, entity2 = create_mock_entity("B")

        graph = DrawingGraph(
            nodes={key1: entity1, key2: entity2},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key2, child=key1),  # Cycle!
            ],
        )

        cycles = graph.detect_cycles()
        assert len(cycles) >= 1

    def test_indirect_cycle_detected(self):
        """Indirect cycle (A -> B -> C -> A) should be detected."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("A")
        key2, entity2 = create_mock_entity("B")
        key3, entity3 = create_mock_entity("C")

        graph = DrawingGraph(
            nodes={key1: entity1, key2: entity2, key3: entity3},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key2, child=key3),
                GraphEdge(parent=key3, child=key1),  # Cycle!
            ],
        )

        cycles = graph.detect_cycles()
        assert len(cycles) >= 1


# =============================================================================
# Test Graph Building from Entities
# =============================================================================

class TestGraphBuildingFromEntities:
    """Test build_graph_from_entities() function."""

    def test_basic_graph_building(self):
        """Basic parent-child relationship should create edge."""
        key1, entity1 = create_mock_entity(
            "MER07540-001",
            parts_list=[
                BOMRow(find_no="1", part_number="MER07545-001", quantity=2),
            ],
        )
        key2, entity2 = create_mock_entity("MER07545-001")

        entities = {key1: entity1, key2: entity2}
        graph, issues = build_graph_from_entities(entities, {})

        assert len(graph.edges) == 1
        assert graph.edges[0].parent.drawing_number == "MER07540-001"
        assert graph.edges[0].child.drawing_number == "MER07545-001"
        assert graph.edges[0].qty_per_parent == 2

    def test_missing_child_creates_warning(self):
        """Reference to non-existent child should create WARNING."""
        key1, entity1 = create_mock_entity(
            "MER07540-001",
            parts_list=[
                BOMRow(find_no="1", part_number="MISSING-PART", quantity=1),
            ],
        )

        entities = {key1: entity1}
        graph, issues = build_graph_from_entities(entities, {})

        # Should have MISSING_CHILD warning
        missing_issues = [i for i in issues if i.issue_type == IssueType.MISSING_CHILD]
        assert len(missing_issues) >= 1
        assert "MISSING-PART" in missing_issues[0].affected

    def test_standard_hardware_child_no_warning(self):
        """Standard hardware child should be BLACK_BOX without warning."""
        key1, entity1 = create_mock_entity(
            "MER07540-001",
            parts_list=[
                BOMRow(find_no="1", part_number="NAS1149-12", quantity=4),
            ],
        )

        entities = {key1: entity1}
        graph, issues = build_graph_from_entities(entities, {})

        # Should NOT have MISSING_CHILD warning for standard hardware
        missing_issues = [i for i in issues if i.issue_type == IssueType.MISSING_CHILD]
        assert len(missing_issues) == 0

        # Should have edge with BLACK_BOX policy
        assert len(graph.edges) == 1
        assert graph.edges[0].explosion_policy == ExplosionPolicy.BLACK_BOX

    def test_cycle_creates_blocker(self):
        """Cycle in graph should create BLOCKER issue."""
        key1, entity1 = create_mock_entity(
            "A",
            parts_list=[BOMRow(find_no="1", part_number="B", quantity=1)],
        )
        key2, entity2 = create_mock_entity(
            "B",
            parts_list=[BOMRow(find_no="1", part_number="A", quantity=1)],  # Cycle!
        )

        entities = {key1: entity1, key2: entity2}
        graph, issues = build_graph_from_entities(entities, {})

        # Should have CYCLE_DETECTED blocker
        cycle_issues = [i for i in issues if i.issue_type == IssueType.CYCLE_DETECTED]
        assert len(cycle_issues) >= 1
        assert cycle_issues[0].severity == IssueSeverity.BLOCKER


# =============================================================================
# Test Utility Functions
# =============================================================================

class TestGraphUtilities:
    """Test utility functions for graph traversal."""

    def test_get_leaf_nodes(self):
        """get_leaf_nodes should return nodes with no children."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("ROOT")
        key2, entity2 = create_mock_entity("CHILD")
        key3, entity3 = create_mock_entity("LEAF")

        graph = DrawingGraph(
            nodes={key1: entity1, key2: entity2, key3: entity3},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key2, child=key3),
            ],
        )

        leaves = get_leaf_nodes(graph)
        assert len(leaves) == 1
        assert leaves[0].drawing_number == "LEAF"

    def test_get_path_to_root(self):
        """get_path_to_root should return path from node to root."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("ROOT")
        key2, entity2 = create_mock_entity("MID")
        key3, entity3 = create_mock_entity("LEAF")

        graph = DrawingGraph(
            root=key1,
            nodes={key1: entity1, key2: entity2, key3: entity3},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key2, child=key3),
            ],
        )

        path = get_path_to_root(graph, key3)
        assert len(path) == 3
        assert path[0].drawing_number == "ROOT"
        assert path[1].drawing_number == "MID"
        assert path[2].drawing_number == "LEAF"

    def test_calculate_total_quantity(self):
        """calculate_total_quantity should multiply quantities along path."""
        from mira.miul.v2.models import DrawingGraph

        key1, entity1 = create_mock_entity("ROOT")
        key2, entity2 = create_mock_entity("MID")
        key3, entity3 = create_mock_entity("LEAF")

        graph = DrawingGraph(
            root=key1,
            nodes={key1: entity1, key2: entity2, key3: entity3},
            edges=[
                GraphEdge(parent=key1, child=key2, qty_per_parent=3),
                GraphEdge(parent=key2, child=key3, qty_per_parent=4),
            ],
        )

        total_qty = calculate_total_quantity(graph, key3)
        assert total_qty == 12  # 3 * 4


# =============================================================================
# Test DT PDF Detection
# =============================================================================

class TestDTPDFDetection:
    """Test Drawing Tree PDF detection patterns."""

    def test_detect_dt_pdf_patterns(self, tmp_path):
        """Various DT PDF naming patterns should be detected."""
        test_cases = [
            "MER07540_Drawing_Tree.pdf",
            "DMLLV-DT-001.pdf",
            "Assembly_DT_.pdf",
            "Parts_DT.pdf",
        ]

        for filename in test_cases:
            pdf_path = tmp_path / filename
            pdf_path.touch()

            result = detect_dt_pdf(tmp_path)
            assert result is not None, f"Should detect {filename}"

    def test_non_dt_pdf_not_detected(self, tmp_path):
        """Regular PDFs should not be detected as DT."""
        non_dt_files = [
            "MER07540-001.pdf",
            "Assembly_Drawing.pdf",
            "Parts_List.pdf",
        ]

        for filename in non_dt_files:
            pdf_path = tmp_path / filename
            pdf_path.touch()

        result = detect_dt_pdf(tmp_path)
        assert result is None

    def test_detect_dt_pdf_case_insensitive(self, tmp_path):
        """DT PDF detection should be case insensitive."""
        pdf_path = tmp_path / "DRAWING_TREE.PDF"
        pdf_path.touch()

        result = detect_dt_pdf(tmp_path)
        assert result is not None
