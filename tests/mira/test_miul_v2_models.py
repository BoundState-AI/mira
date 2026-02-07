#!/usr/bin/env python3
"""
Module: Test Miul V2 Models
Purpose: MIUL Builder v2.2 - Unit Tests for models.py

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

from mira.miul.v2.models import (
    Zone,
    BindingMethod,
    BindingConfidence,
    ExplosionPolicy,
    NodeType,
    IssueSeverity,
    IssueType,
    ZONE_WEIGHTS,
    THRESHOLD_PRIMARY,
    THRESHOLD_SUPPORTING,
    THRESHOLD_AMBIGUOUS,
    DrawingKey,
    DrawingEntity,
    DrawingGraph,
    GraphEdge,
    Issue,
    MIULEntry,
    Occurrence,
    PackageExtract,
    PageBinding,
    PageExtract,
    TitleBlock,
    BOMRow,
)


# =============================================================================
# Test Zone Weights and Thresholds
# =============================================================================

class TestZoneWeights:
    """Test zone weight constants."""

    def test_titleblock_highest_weight(self):
        """TITLEBLOCK should have the highest weight."""
        assert ZONE_WEIGHTS[Zone.TITLEBLOCK] == 70
        assert ZONE_WEIGHTS[Zone.TITLEBLOCK] > ZONE_WEIGHTS[Zone.BORDER]
        assert ZONE_WEIGHTS[Zone.TITLEBLOCK] > ZONE_WEIGHTS[Zone.BODY]
        assert ZONE_WEIGHTS[Zone.TITLEBLOCK] > ZONE_WEIGHTS[Zone.NOTES]

    def test_notes_lowest_weight(self):
        """NOTES should have the lowest weight."""
        assert ZONE_WEIGHTS[Zone.NOTES] == 10
        assert ZONE_WEIGHTS[Zone.NOTES] < ZONE_WEIGHTS[Zone.TITLEBLOCK]
        assert ZONE_WEIGHTS[Zone.NOTES] < ZONE_WEIGHTS[Zone.BORDER]
        assert ZONE_WEIGHTS[Zone.NOTES] < ZONE_WEIGHTS[Zone.BODY]

    def test_threshold_ordering(self):
        """Thresholds should be properly ordered."""
        assert THRESHOLD_PRIMARY > THRESHOLD_SUPPORTING
        assert THRESHOLD_PRIMARY == 80
        assert THRESHOLD_SUPPORTING == 50
        assert THRESHOLD_AMBIGUOUS == 10


# =============================================================================
# Test DrawingKey
# =============================================================================

class TestDrawingKey:
    """Test DrawingKey frozen dataclass."""

    def test_drawing_key_hashable(self):
        """DrawingKey should be hashable for use as dict key."""
        key1 = DrawingKey(drawing_number="MER07540-001")
        key2 = DrawingKey(drawing_number="MER07540-001")

        # Should be usable as dict key
        d = {key1: "value"}
        assert d[key2] == "value"

    def test_drawing_key_equality_same(self):
        """Same drawing number and revision should be equal."""
        key1 = DrawingKey(drawing_number="MER07540-001", revision="A")
        key2 = DrawingKey(drawing_number="MER07540-001", revision="A")
        assert key1 == key2

    def test_drawing_key_equality_different_revision(self):
        """Different revisions should NOT be equal."""
        key1 = DrawingKey(drawing_number="MER07540-001", revision="A")
        key2 = DrawingKey(drawing_number="MER07540-001", revision="B")
        assert key1 != key2

    def test_drawing_key_revision_none_vs_string(self):
        """None revision should not equal string revision."""
        key1 = DrawingKey(drawing_number="MER07540-001", revision=None)
        key2 = DrawingKey(drawing_number="MER07540-001", revision="A")
        assert key1 != key2

    def test_drawing_key_in_set(self):
        """DrawingKey should work in sets."""
        keys = {
            DrawingKey(drawing_number="A"),
            DrawingKey(drawing_number="B"),
            DrawingKey(drawing_number="A"),  # Duplicate
        }
        assert len(keys) == 2


# =============================================================================
# Test DrawingEntity
# =============================================================================

class TestDrawingEntity:
    """Test DrawingEntity dataclass."""

    def test_drawing_number_property(self):
        """drawing_number property should return key's drawing_number."""
        key = DrawingKey(drawing_number="MER07540-001")
        entity = DrawingEntity(key=key)
        assert entity.drawing_number == "MER07540-001"

    def test_revision_property(self):
        """revision property should return key's revision."""
        key = DrawingKey(drawing_number="MER07540-001", revision="B")
        entity = DrawingEntity(key=key)
        assert entity.revision == "B"

    def test_all_page_ids(self):
        """all_page_ids should combine primary and supporting pages."""
        key = DrawingKey(drawing_number="MER07540-001")
        entity = DrawingEntity(key=key)

        entity.pages_primary.append(PageBinding(
            page_id="page001",
            binding_score=100,
            binding_method=BindingMethod.TITLE_BLOCK,
            binding_confidence=BindingConfidence.HIGH,
        ))
        entity.pages_supporting.append(PageBinding(
            page_id="page002",
            binding_score=60,
            binding_method=BindingMethod.SCORED_ZONE,
            binding_confidence=BindingConfidence.MEDIUM,
        ))

        page_ids = entity.all_page_ids
        assert "page001" in page_ids
        assert "page002" in page_ids
        assert len(page_ids) == 2


# =============================================================================
# Test PageExtract
# =============================================================================

class TestPageExtract:
    """Test PageExtract dataclass."""

    def test_key_candidates_from_title_block(self):
        """key_candidates should include title block drawing number."""
        page = PageExtract(
            page_id="page001",
            page_index=0,
            source_file="test.pdf",
            title_block=TitleBlock(drawing_number="MER07540-001"),
        )

        assert "MER07540-001" in page.key_candidates

    def test_key_candidates_from_occurrences(self):
        """key_candidates should include all occurrence drawing numbers."""
        page = PageExtract(
            page_id="page001",
            page_index=0,
            source_file="test.pdf",
            drawing_number_occurrences=[
                Occurrence(drawing_number="MER07540-002", zone=Zone.BODY),
                Occurrence(drawing_number="MER07540-003", zone=Zone.NOTES),
            ],
        )

        assert "MER07540-002" in page.key_candidates
        assert "MER07540-003" in page.key_candidates

    def test_key_candidates_from_text(self):
        """key_candidates should include text-extracted drawing numbers."""
        page = PageExtract(
            page_id="page001",
            page_index=0,
            source_file="test.pdf",
            text_drawing_numbers=["MER07540-004", "MER07540-005"],
        )

        assert "MER07540-004" in page.key_candidates
        assert "MER07540-005" in page.key_candidates

    def test_key_candidates_deduplicates(self):
        """key_candidates should return unique values."""
        page = PageExtract(
            page_id="page001",
            page_index=0,
            source_file="test.pdf",
            title_block=TitleBlock(drawing_number="MER07540-001"),
            drawing_number_occurrences=[
                Occurrence(drawing_number="MER07540-001", zone=Zone.BODY),  # Same
            ],
            text_drawing_numbers=["MER07540-001"],  # Same
        )

        assert len(page.key_candidates) == 1


# =============================================================================
# Test Occurrence
# =============================================================================

class TestOccurrence:
    """Test Occurrence dataclass."""

    def test_weighted_score_calculation(self):
        """weighted_score should multiply zone weight by confidence."""
        occ = Occurrence(
            drawing_number="MER07540-001",
            zone=Zone.BODY,
            confidence=1.0,
        )
        assert occ.weighted_score == 30  # BODY weight

    def test_weighted_score_with_confidence(self):
        """weighted_score should apply confidence multiplier."""
        occ = Occurrence(
            drawing_number="MER07540-001",
            zone=Zone.BORDER,
            confidence=0.5,
        )
        assert occ.weighted_score == 25  # 50 * 0.5


# =============================================================================
# Test Issue
# =============================================================================

class TestIssue:
    """Test Issue dataclass."""

    def test_is_blocker_property(self):
        """is_blocker should return True for BLOCKER severity."""
        issue = Issue(
            severity=IssueSeverity.BLOCKER,
            issue_type=IssueType.AMBIGUOUS_BINDING,
            affected="page001",
            message="Test blocker",
        )
        assert issue.is_blocker is True

    def test_is_blocker_false_for_warning(self):
        """is_blocker should return False for WARNING severity."""
        issue = Issue(
            severity=IssueSeverity.WARNING,
            issue_type=IssueType.MISSING_CHILD,
            affected="PART-123",
            message="Test warning",
        )
        assert issue.is_blocker is False


# =============================================================================
# Test PackageExtract
# =============================================================================

class TestPackageExtract:
    """Test PackageExtract dataclass."""

    def test_has_blockers_true(self):
        """has_blockers should return True when BLOCKER issues exist."""
        package = PackageExtract(package_id="test-001")
        package.issues.append(Issue(
            severity=IssueSeverity.BLOCKER,
            issue_type=IssueType.AMBIGUOUS_BINDING,
            affected="page001",
            message="Test",
        ))

        assert package.has_blockers is True

    def test_has_blockers_false(self):
        """has_blockers should return False with only WARNINGs."""
        package = PackageExtract(package_id="test-001")
        package.issues.append(Issue(
            severity=IssueSeverity.WARNING,
            issue_type=IssueType.MISSING_CHILD,
            affected="PART-123",
            message="Test",
        ))

        assert package.has_blockers is False

    def test_blocker_count(self):
        """blocker_count should count BLOCKER issues."""
        package = PackageExtract(package_id="test-001")
        package.issues.extend([
            Issue(severity=IssueSeverity.BLOCKER, issue_type=IssueType.AMBIGUOUS_BINDING, affected="1", message=""),
            Issue(severity=IssueSeverity.WARNING, issue_type=IssueType.MISSING_CHILD, affected="2", message=""),
            Issue(severity=IssueSeverity.BLOCKER, issue_type=IssueType.CYCLE_DETECTED, affected="3", message=""),
        ])

        assert package.blocker_count == 2

    def test_warning_count(self):
        """warning_count should count WARNING issues."""
        package = PackageExtract(package_id="test-001")
        package.issues.extend([
            Issue(severity=IssueSeverity.BLOCKER, issue_type=IssueType.AMBIGUOUS_BINDING, affected="1", message=""),
            Issue(severity=IssueSeverity.WARNING, issue_type=IssueType.MISSING_CHILD, affected="2", message=""),
            Issue(severity=IssueSeverity.WARNING, issue_type=IssueType.ORPHAN_PAGE, affected="3", message=""),
        ])

        assert package.warning_count == 2

    def test_get_issues_by_type(self):
        """get_issues_by_type should filter by issue type."""
        package = PackageExtract(package_id="test-001")
        package.issues.extend([
            Issue(severity=IssueSeverity.WARNING, issue_type=IssueType.MISSING_CHILD, affected="1", message=""),
            Issue(severity=IssueSeverity.WARNING, issue_type=IssueType.ORPHAN_PAGE, affected="2", message=""),
            Issue(severity=IssueSeverity.WARNING, issue_type=IssueType.MISSING_CHILD, affected="3", message=""),
        ])

        missing_issues = package.get_issues_by_type(IssueType.MISSING_CHILD)
        assert len(missing_issues) == 2

    def test_add_issue(self):
        """add_issue should append to issues list."""
        package = PackageExtract(package_id="test-001")
        issue = Issue(
            severity=IssueSeverity.WARNING,
            issue_type=IssueType.LOW_CONFIDENCE,
            affected="PART-123",
            message="Test",
        )

        package.add_issue(issue)
        assert len(package.issues) == 1
        assert package.issues[0] == issue


# =============================================================================
# Test DrawingGraph
# =============================================================================

class TestDrawingGraph:
    """Test DrawingGraph dataclass."""

    def test_get_children(self):
        """get_children should return edges where key is parent."""
        key1 = DrawingKey(drawing_number="PARENT")
        key2 = DrawingKey(drawing_number="CHILD1")
        key3 = DrawingKey(drawing_number="CHILD2")

        graph = DrawingGraph(
            nodes={key1: DrawingEntity(key=key1), key2: DrawingEntity(key=key2), key3: DrawingEntity(key=key3)},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key1, child=key3),
            ],
        )

        children = graph.get_children(key1)
        assert len(children) == 2

    def test_get_parent(self):
        """get_parent should return edge where key is child."""
        key1 = DrawingKey(drawing_number="PARENT")
        key2 = DrawingKey(drawing_number="CHILD")

        graph = DrawingGraph(
            nodes={key1: DrawingEntity(key=key1), key2: DrawingEntity(key=key2)},
            edges=[
                GraphEdge(parent=key1, child=key2),
            ],
        )

        parent_edge = graph.get_parent(key2)
        assert parent_edge is not None
        assert parent_edge.parent == key1

    def test_get_parent_none_for_root(self):
        """get_parent should return None for root node."""
        key1 = DrawingKey(drawing_number="ROOT")
        key2 = DrawingKey(drawing_number="CHILD")

        graph = DrawingGraph(
            root=key1,
            nodes={key1: DrawingEntity(key=key1), key2: DrawingEntity(key=key2)},
            edges=[
                GraphEdge(parent=key1, child=key2),
            ],
        )

        parent_edge = graph.get_parent(key1)
        assert parent_edge is None

    def test_detect_cycles_no_cycle(self):
        """detect_cycles should return empty list for acyclic graph."""
        key1 = DrawingKey(drawing_number="A")
        key2 = DrawingKey(drawing_number="B")
        key3 = DrawingKey(drawing_number="C")

        graph = DrawingGraph(
            nodes={key1: DrawingEntity(key=key1), key2: DrawingEntity(key=key2), key3: DrawingEntity(key=key3)},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key2, child=key3),
            ],
        )

        cycles = graph.detect_cycles()
        assert len(cycles) == 0

    def test_detect_cycles_with_cycle(self):
        """detect_cycles should detect cycles."""
        key1 = DrawingKey(drawing_number="A")
        key2 = DrawingKey(drawing_number="B")

        graph = DrawingGraph(
            nodes={key1: DrawingEntity(key=key1), key2: DrawingEntity(key=key2)},
            edges=[
                GraphEdge(parent=key1, child=key2),
                GraphEdge(parent=key2, child=key1),  # Cycle!
            ],
        )

        cycles = graph.detect_cycles()
        assert len(cycles) >= 1


# =============================================================================
# Test Enumerations
# =============================================================================

class TestEnumerations:
    """Test enum values."""

    def test_zone_values(self):
        """Zone enum should have expected values."""
        assert Zone.TITLEBLOCK.value == "titleblock"
        assert Zone.BORDER.value == "border"
        assert Zone.BODY.value == "body"
        assert Zone.NOTES.value == "notes"
        assert Zone.UNKNOWN.value == "unknown"

    def test_explosion_policy_values(self):
        """ExplosionPolicy enum should have expected values."""
        assert ExplosionPolicy.EXPLODE.value == "explode"
        assert ExplosionPolicy.BLACK_BOX.value == "black_box"
        assert ExplosionPolicy.PHANTOM.value == "phantom"

    def test_node_type_values(self):
        """NodeType enum should have expected values."""
        assert NodeType.ASSEMBLY.value == "assembly"
        assert NodeType.PIECE_PART.value == "piece_part"
        assert NodeType.HARDWARE.value == "hardware"
        assert NodeType.PURCHASED.value == "purchased"
        assert NodeType.STANDARD.value == "standard"

    def test_issue_severity_values(self):
        """IssueSeverity enum should have expected values."""
        assert IssueSeverity.BLOCKER.value == "blocker"
        assert IssueSeverity.WARNING.value == "warning"
