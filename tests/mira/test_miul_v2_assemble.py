#!/usr/bin/env python3
"""
Module: Test Miul V2 Assemble
Purpose: MIUL Builder v2.2 - Unit Tests for assemble.py

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
    BindingConfidence,
    BindingMethod,
    BOMRow,
    DrawingKey,
    IssueType,
    IssueSeverity,
    LayoutFlags,
    Zone,
    THRESHOLD_PRIMARY,
    THRESHOLD_SUPPORTING,
)
from mira.miul.v2.assemble import (
    assemble_drawings,
    assemble_package,
    build_score_matrix,
    compute_binding_score,
    create_mock_page,
    determine_binding_confidence,
)


class TestZoneWeightedScoring:
    """Test the zone-weighted scoring system."""

    def test_title_block_exact_match_highest_score(self):
        """Title block exact match should give +100 points."""
        page = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        score = compute_binding_score("MER07540-001", page)

        # Title block match (+100) + layout has_title_block (+20) = 120
        assert score >= 100

    def test_body_zone_occurrence_moderate_score(self):
        """BODY zone occurrence should give 30 points."""
        page = create_mock_page(
            page_id="page001",
            occurrences=[("MER07540-003", Zone.BODY, 1.0)],
            layout_flags=LayoutFlags(),
        )

        score = compute_binding_score("MER07540-003", page)

        # BODY zone = 30 points
        assert score == 30

    def test_notes_zone_occurrence_low_score(self):
        """NOTES zone occurrence should give only 10 points (KEY TEST)."""
        page = create_mock_page(
            page_id="page001",
            occurrences=[("MER07540-002", Zone.NOTES, 1.0)],
            layout_flags=LayoutFlags(),
        )

        score = compute_binding_score("MER07540-002", page)

        # NOTES zone = 10 points (below THRESHOLD_SUPPORTING of 50)
        assert score == 10
        assert score < THRESHOLD_SUPPORTING

    def test_confidence_multiplier_applied(self):
        """Confidence should multiply zone weight."""
        page = create_mock_page(
            page_id="page001",
            occurrences=[("MER07540-001", Zone.BODY, 0.5)],
            layout_flags=LayoutFlags(),
        )

        score = compute_binding_score("MER07540-001", page)

        # BODY zone (30) * confidence (0.5) = 15
        assert score == 15


class TestSpec1UnlabeledChildBindsViaBodyZone:
    """
    Test 1: Unlabeled child on later sheet binds via BODY zone occurrence.

    Scenario:
    - Page 1: title_block = "MER07540-001", parts_list references "MER07540-003"
    - Page 3: title_block = None, occurrence of "MER07540-003" in BODY zone
    - Expected: MER07540-003 binds to page 3 via SCORED_ZONE
    """

    def test_unlabeled_child_binds_via_body_zone(self):
        """Child drawing without title block should bind via BODY zone occurrence."""
        # Page 1: Parent drawing with parts list
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            title_block_title="PARENT ASSEMBLY",
            layout_flags=LayoutFlags(has_title_block=True, has_parts_list=True),
            parts_list=[
                BOMRow(find_no="1", part_number="MER07540-003", quantity=1),
            ],
        )

        # Page 3: Child drawing without title block, but has BODY occurrence
        page3 = create_mock_page(
            page_id="page003",
            page_index=2,
            occurrences=[
                ("MER07540-003", Zone.BODY, 1.0),  # Drawing number in body
            ],
            layout_flags=LayoutFlags(has_views=True, has_balloons=True),
        )

        result = assemble_drawings([page1, page3])

        # Should have 2 drawings
        assert len(result.drawings) == 2

        # Find the child drawing
        child_key = DrawingKey(drawing_number="MER07540-003")
        child_entity = result.drawings.get(child_key)

        assert child_entity is not None
        assert len(child_entity.pages_primary) > 0 or len(child_entity.pages_supporting) > 0

        # Check binding method is SCORED_ZONE (not TITLE_BLOCK)
        all_bindings = child_entity.pages_primary + child_entity.pages_supporting
        assert any(b.page_id == "page003" for b in all_bindings)

        # Verify binding was via scored zone
        page3_binding = next(b for b in all_bindings if b.page_id == "page003")
        assert page3_binding.binding_method == BindingMethod.SCORED_ZONE


class TestSpec2NotesOnlyMentionDoesNotBind:
    """
    Test 2: Notes-only mention does NOT bind.

    Scenario:
    - Page 1: title_block = "MER07540-001"
    - Page 1: occurrence of "MER07540-002" in NOTES zone only
    - Expected: MER07540-002 has NO bound pages (MISSING_CHILD warning from graph phase)
    """

    def test_notes_only_mention_does_not_bind(self):
        """Drawing number mentioned only in NOTES zone should not create a binding."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            occurrences=[
                ("MER07540-002", Zone.NOTES, 1.0),  # Only in notes!
            ],
            layout_flags=LayoutFlags(has_title_block=True),
        )

        result = assemble_drawings([page1])

        # Should only have the parent drawing (MER07540-001)
        assert len(result.drawings) == 1

        parent_key = DrawingKey(drawing_number="MER07540-001")
        assert parent_key in result.drawings

        # MER07540-002 should NOT have a DrawingEntity because its only
        # occurrence was in NOTES zone (score=10 < THRESHOLD_SUPPORTING=50)
        child_key = DrawingKey(drawing_number="MER07540-002")
        assert child_key not in result.drawings


class TestSpec3TwoDrawingsClaimSamePageBlocker:
    """
    Test 3: Two drawings claim same page -> BLOCKER.

    Scenario:
    - Page 1: occurrence of "MER07540-001" in BORDER zone (score ~50)
    - Page 1: occurrence of "MER07540-002" in BORDER zone (score ~50)
    - Expected: Issue(BLOCKER, AMBIGUOUS_BINDING)
    """

    def test_ambiguous_binding_creates_blocker(self):
        """Two drawings claiming same page within threshold should create BLOCKER."""
        page1 = create_mock_page(
            page_id="page001",
            occurrences=[
                ("MER07540-001", Zone.BORDER, 1.0),  # Score = 50
                ("MER07540-002", Zone.BORDER, 1.0),  # Score = 50
            ],
            layout_flags=LayoutFlags(),  # No title block for equal scoring
        )

        result = assemble_drawings([page1])

        # Should have BLOCKER issue
        blocker_issues = [i for i in result.issues if i.is_blocker]
        assert len(blocker_issues) >= 1

        # Should be AMBIGUOUS_BINDING type
        ambiguous_issues = [
            i for i in result.issues
            if i.issue_type == IssueType.AMBIGUOUS_BINDING
        ]
        assert len(ambiguous_issues) >= 1

        # Issue should reference page001
        assert any("page001" in str(i.affected) for i in ambiguous_issues)

    def test_clear_winner_no_blocker(self):
        """One drawing with clear score advantage should NOT create BLOCKER."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",  # +100 for title block
            occurrences=[
                ("MER07540-002", Zone.NOTES, 1.0),  # Only +10 for notes
            ],
            layout_flags=LayoutFlags(has_title_block=True),
        )

        result = assemble_drawings([page1])

        # Should NOT have ambiguous binding blocker
        ambiguous_blockers = [
            i for i in result.issues
            if i.issue_type == IssueType.AMBIGUOUS_BINDING and i.is_blocker
        ]
        assert len(ambiguous_blockers) == 0


class TestSpec4MultiRevCollisionBlocker:
    """
    Test 4: Multi-rev collision -> BLOCKER.

    Scenario:
    - Page 1: title_block = "MER07540-001", revision = "A"
    - Page 2: title_block = "MER07540-001", revision = "B"
    - Expected: Issue(BLOCKER, REV_CONFLICT)
    """

    def test_revision_conflict_creates_blocker(self):
        """Same drawing with different revisions should create BLOCKER."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            title_block_revision="A",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        page2 = create_mock_page(
            page_id="page002",
            page_index=1,
            title_block_drawing="MER07540-001",
            title_block_revision="B",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        result = assemble_drawings([page1, page2], strict_revision=True)

        # Should have REV_CONFLICT issue
        rev_issues = [
            i for i in result.issues
            if i.issue_type == IssueType.REV_CONFLICT
        ]
        assert len(rev_issues) >= 1

        # Should be BLOCKER when strict_revision=True
        assert any(i.is_blocker for i in rev_issues)

        # Issue should mention both revisions
        issue_msg = rev_issues[0].message
        assert "A" in issue_msg or "B" in issue_msg

    def test_revision_conflict_warning_when_not_strict(self):
        """Revision conflict should be WARNING when strict_revision=False."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            title_block_revision="A",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        page2 = create_mock_page(
            page_id="page002",
            page_index=1,
            title_block_drawing="MER07540-001",
            title_block_revision="B",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        result = assemble_drawings([page1, page2], strict_revision=False)

        # Should have REV_CONFLICT issue
        rev_issues = [
            i for i in result.issues
            if i.issue_type == IssueType.REV_CONFLICT
        ]
        assert len(rev_issues) >= 1

        # Should be WARNING when strict_revision=False
        assert all(i.severity == IssueSeverity.WARNING for i in rev_issues)


class TestSpec6OrphanPagesWarning:
    """
    Test 6: Orphan pages -> WARNING list.

    Scenario:
    - Page 1: title_block = "MER07540-001"
    - Page 2: no drawing numbers anywhere, no title block
    - Expected: page 2's page_id in PackageExtract.orphan_page_ids
    """

    def test_orphan_page_tracked(self):
        """Page with no drawing numbers should be tracked as orphan."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        # Page 2: completely blank, no drawing numbers
        page2 = create_mock_page(
            page_id="page002",
            page_index=1,
            layout_flags=LayoutFlags(),  # No title block, no occurrences
        )

        result = assemble_drawings([page1, page2])

        # page002 should be in orphan list
        assert "page002" in result.orphan_page_ids

        # Should have ORPHAN_PAGE warning
        orphan_issues = [
            i for i in result.issues
            if i.issue_type == IssueType.ORPHAN_PAGE
        ]
        assert len(orphan_issues) >= 1
        assert any("page002" in i.affected for i in orphan_issues)

    def test_bound_page_not_orphan(self):
        """Page that binds to a drawing should NOT be orphan."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        result = assemble_drawings([page1])

        # page001 should NOT be orphan
        assert "page001" not in result.orphan_page_ids


class TestBindingConfidenceLevels:
    """Test binding confidence level assignment."""

    def test_high_confidence_threshold(self):
        """Score >= 80 should be HIGH confidence."""
        assert determine_binding_confidence(80) == BindingConfidence.HIGH
        assert determine_binding_confidence(100) == BindingConfidence.HIGH
        assert determine_binding_confidence(150) == BindingConfidence.HIGH

    def test_medium_confidence_threshold(self):
        """Score 50-79 should be MEDIUM confidence."""
        assert determine_binding_confidence(50) == BindingConfidence.MEDIUM
        assert determine_binding_confidence(65) == BindingConfidence.MEDIUM
        assert determine_binding_confidence(79) == BindingConfidence.MEDIUM

    def test_low_confidence_threshold(self):
        """Score < 50 should be LOW confidence."""
        assert determine_binding_confidence(49) == BindingConfidence.LOW
        assert determine_binding_confidence(30) == BindingConfidence.LOW
        assert determine_binding_confidence(0) == BindingConfidence.LOW


class TestPackageExtractIntegration:
    """Test the PackageExtract creation."""

    def test_assemble_package_creates_complete_structure(self):
        """assemble_package should create a complete PackageExtract."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            layout_flags=LayoutFlags(has_title_block=True),
        )

        package = assemble_package([page1], package_id="test-package-001")

        assert package.package_id == "test-package-001"
        assert len(package.pages) == 1
        assert len(package.drawings) == 1
        assert not package.has_blockers

    def test_package_has_blockers_property(self):
        """has_blockers should return True when BLOCKER issues exist."""
        # Create ambiguous binding scenario
        page1 = create_mock_page(
            page_id="page001",
            occurrences=[
                ("MER07540-001", Zone.BORDER, 1.0),
                ("MER07540-002", Zone.BORDER, 1.0),
            ],
        )

        package = assemble_package([page1], package_id="test-package-002")

        assert package.has_blockers
        assert package.blocker_count >= 1


class TestPartsListMerging:
    """Test parts list merging from multiple pages."""

    def test_parts_list_merged_from_bound_pages(self):
        """Parts lists from all bound pages should be merged."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            layout_flags=LayoutFlags(has_title_block=True, has_parts_list=True),
            parts_list=[
                BOMRow(find_no="1", part_number="PART-A", quantity=2),
            ],
        )

        page2 = create_mock_page(
            page_id="page002",
            page_index=1,
            title_block_drawing="MER07540-001",  # Same drawing, sheet 2
            layout_flags=LayoutFlags(has_title_block=True, has_parts_list=True),
            parts_list=[
                BOMRow(find_no="2", part_number="PART-B", quantity=3),
            ],
        )

        result = assemble_drawings([page1, page2])

        parent_key = DrawingKey(drawing_number="MER07540-001")
        entity = result.drawings[parent_key]

        # Should have both parts
        part_numbers = [p.part_number for p in entity.parts_list]
        assert "PART-A" in part_numbers
        assert "PART-B" in part_numbers

    def test_duplicate_parts_deduplicated(self):
        """Duplicate parts (same find_no + part_number) should be deduplicated."""
        page1 = create_mock_page(
            page_id="page001",
            title_block_drawing="MER07540-001",
            layout_flags=LayoutFlags(has_title_block=True, has_parts_list=True),
            parts_list=[
                BOMRow(find_no="1", part_number="PART-A", quantity=2),
            ],
        )

        page2 = create_mock_page(
            page_id="page002",
            page_index=1,
            title_block_drawing="MER07540-001",
            layout_flags=LayoutFlags(has_title_block=True, has_parts_list=True),
            parts_list=[
                BOMRow(find_no="1", part_number="PART-A", quantity=2),  # Duplicate!
            ],
        )

        result = assemble_drawings([page1, page2])

        parent_key = DrawingKey(drawing_number="MER07540-001")
        entity = result.drawings[parent_key]

        # Should have only one PART-A
        part_a_count = sum(1 for p in entity.parts_list if p.part_number == "PART-A")
        assert part_a_count == 1
