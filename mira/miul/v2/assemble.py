#!/usr/bin/env python3
"""
Module: Assemble
Purpose: MIUL Builder v2.3 - Phase 2: Assemble

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

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .models import (
    BindingConfidence,
    BindingMethod,
    BOMRow,
    DrawingEntity,
    DrawingKey,
    Issue,
    IssueSeverity,
    IssueType,
    LayoutFlags,
    Occurrence,
    PackageExtract,
    PageBinding,
    PageExtract,
    TitleBlock,
    Zone,
    ZONE_WEIGHTS,
    THRESHOLD_PRIMARY,
    THRESHOLD_SUPPORTING,
    THRESHOLD_AMBIGUOUS,
)


# =============================================================================
# Binding Score Calculation
# =============================================================================

def compute_binding_score(drawing_number: str, page: PageExtract) -> float:
    """
    Compute the binding score for a drawing number on a page.

    Per spec v2.2, this uses zone-weighted scoring:
    - Title block exact match: +100 (strongest signal)
    - Zone-weighted occurrences: weight * confidence
    - Layout evidence: +20 for title block, +10 for views/balloons, +20 for parts list

    Args:
        drawing_number: The drawing number to score
        page: The PageExtract containing occurrences

    Returns:
        Binding score (higher = stronger binding)
    """
    score = 0.0

    # Title block exact match (strongest signal)
    if page.title_block.drawing_number == drawing_number:
        score += 100

    # Zone-weighted occurrences
    for occ in page.drawing_number_occurrences:
        if occ.drawing_number == drawing_number:
            zone_weight = ZONE_WEIGHTS.get(occ.zone, ZONE_WEIGHTS[Zone.UNKNOWN])
            score += zone_weight * occ.confidence

    # Layout evidence (applies to the best candidate)
    if page.layout_flags.has_title_block:
        score += 20
    if page.layout_flags.has_views:
        score += 10
    if page.layout_flags.has_balloons:
        score += 10
    if page.layout_flags.has_parts_list:
        score += 20

    return score


def determine_binding_confidence(score: float) -> BindingConfidence:
    """
    Determine binding confidence level from score.

    Per spec v2.2:
    - HIGH: score >= 80
    - MEDIUM: 50 <= score < 80
    - LOW: score < 50
    """
    if score >= THRESHOLD_PRIMARY:
        return BindingConfidence.HIGH
    elif score >= THRESHOLD_SUPPORTING:
        return BindingConfidence.MEDIUM
    else:
        return BindingConfidence.LOW


def determine_binding_method(page: PageExtract, drawing_number: str) -> BindingMethod:
    """Determine how a page was bound to a drawing."""
    if page.title_block.drawing_number == drawing_number:
        return BindingMethod.TITLE_BLOCK
    return BindingMethod.SCORED_ZONE


# =============================================================================
# Score Matrix Builder
# =============================================================================

@dataclass
class ScoreEntry:
    """A single (drawing, page) score entry."""
    drawing_number: str
    page_id: str
    score: float
    revision: Optional[str] = None


def build_score_matrix(pages: list[PageExtract]) -> dict[str, dict[str, ScoreEntry]]:
    """
    Build a matrix of (drawing_number -> page_id -> score).

    This lets us:
    1. Find all pages that might bind to each drawing
    2. Find all drawings that might claim each page
    3. Detect ambiguous bindings

    Returns:
        Dict[drawing_number, Dict[page_id, ScoreEntry]]
    """
    matrix: dict[str, dict[str, ScoreEntry]] = defaultdict(dict)

    for page in pages:
        # Get all drawing number candidates from this page
        candidates = page.key_candidates

        for drawing_number in candidates:
            score = compute_binding_score(drawing_number, page)
            if score > 0:
                # Get revision from title block if this drawing matches
                revision = None
                if page.title_block.drawing_number == drawing_number:
                    revision = page.title_block.revision or page.revision

                matrix[drawing_number][page.page_id] = ScoreEntry(
                    drawing_number=drawing_number,
                    page_id=page.page_id,
                    score=score,
                    revision=revision,
                )

    return dict(matrix)


# =============================================================================
# Binding Resolution
# =============================================================================

@dataclass
class BindingResult:
    """Result of binding pages to drawings."""
    drawings: dict[DrawingKey, DrawingEntity]
    issues: list[Issue]
    orphan_page_ids: list[str]


def resolve_bindings(
    pages: list[PageExtract],
    score_matrix: dict[str, dict[str, ScoreEntry]],
    strict_revision: bool = True,
) -> BindingResult:
    """
    Resolve page-to-drawing bindings using scored evidence.

    Per spec v2.2 resolution rules:
    1. Score all (drawing, page) pairs
    2. For each drawing:
       - pages_primary = pages with score >= 80
       - pages_supporting = pages with 50 <= score < 80 (minus primaries)
    3. If two drawings claim same page within 10 points: BLOCKER
    4. Pages that don't bind to anything with score >= 30: orphan_page_ids
    5. Same drawing_number, different revision: BLOCKER (if strict_revision)

    Args:
        pages: List of PageExtract from Phase 2
        score_matrix: Pre-computed score matrix
        strict_revision: If True, revision conflicts are BLOCKERs

    Returns:
        BindingResult with drawings, issues, and orphan_page_ids
    """
    issues: list[Issue] = []
    orphan_page_ids: list[str] = []
    page_lookup = {p.page_id: p for p in pages}

    # Track which pages are claimed and by whom
    page_claims: dict[str, list[tuple[str, float]]] = defaultdict(list)  # page_id -> [(drawing, score)]

    # First pass: collect all claims
    for drawing_number, page_scores in score_matrix.items():
        for page_id, entry in page_scores.items():
            if entry.score >= THRESHOLD_SUPPORTING:  # Only consider meaningful scores
                page_claims[page_id].append((drawing_number, entry.score))

    # Check for ambiguous bindings
    for page_id, claims in page_claims.items():
        if len(claims) >= 2:
            # Sort by score descending
            claims.sort(key=lambda x: x[1], reverse=True)
            top_score = claims[0][1]
            second_score = claims[1][1]

            # If top two are within THRESHOLD_AMBIGUOUS points, it's ambiguous
            if top_score - second_score <= THRESHOLD_AMBIGUOUS:
                issue = Issue(
                    severity=IssueSeverity.BLOCKER,
                    issue_type=IssueType.AMBIGUOUS_BINDING,
                    affected=page_id,
                    message=f"Page {page_id} claimed by multiple drawings within {THRESHOLD_AMBIGUOUS} points: "
                           f"{claims[0][0]} ({claims[0][1]:.1f}) vs {claims[1][0]} ({claims[1][1]:.1f})",
                    evidence_page_ids=[page_id],
                )
                issues.append(issue)

    # Check for revision conflicts
    revision_map: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for drawing_number, page_scores in score_matrix.items():
        for page_id, entry in page_scores.items():
            if entry.revision and entry.score >= THRESHOLD_PRIMARY:
                revision_map[drawing_number][entry.revision].append(page_id)

    for drawing_number, revisions in revision_map.items():
        if len(revisions) > 1:
            rev_list = list(revisions.keys())
            all_page_ids = []
            for pages_list in revisions.values():
                all_page_ids.extend(pages_list)

            severity = IssueSeverity.BLOCKER if strict_revision else IssueSeverity.WARNING
            issue = Issue(
                severity=severity,
                issue_type=IssueType.REV_CONFLICT,
                affected=drawing_number,
                message=f"Drawing {drawing_number} has multiple revisions: {rev_list}",
                evidence_page_ids=all_page_ids,
            )
            issues.append(issue)

    # Build drawings from bindings
    drawings: dict[DrawingKey, DrawingEntity] = {}

    for drawing_number, page_scores in score_matrix.items():
        # Determine revision (use highest-scoring page's revision)
        best_page_id = max(page_scores.keys(), key=lambda pid: page_scores[pid].score)
        revision = page_scores[best_page_id].revision
        # Normalize empty string to None for consistent key matching
        revision = revision if revision else None

        key = DrawingKey(drawing_number=drawing_number, revision=revision)

        # Skip if we already have this drawing (shouldn't happen with unique keys)
        if key in drawings:
            continue

        entity = DrawingEntity(key=key)

        # Bind pages
        for page_id, entry in page_scores.items():
            if entry.score < THRESHOLD_SUPPORTING:
                continue

            page = page_lookup.get(page_id)
            if not page:
                continue

            confidence = determine_binding_confidence(entry.score)
            method = determine_binding_method(page, drawing_number)

            binding = PageBinding(
                page_id=page_id,
                binding_score=entry.score,
                binding_method=method,
                binding_confidence=confidence,
            )

            if entry.score >= THRESHOLD_PRIMARY:
                entity.pages_primary.append(binding)
            else:
                entity.pages_supporting.append(binding)

            # Extract title from first page with title block
            if not entity.title and page.title_block.title:
                entity.title = page.title_block.title

            # Extract material info from title block (for detail drawings)
            # Priority: first page with material_designation wins
            if not entity.material_designation and page.title_block.material_designation:
                entity.material_designation = page.title_block.material_designation
            if not entity.material_spec and page.title_block.material_spec:
                entity.material_spec = page.title_block.material_spec
            if not entity.uns_number and page.title_block.uns_number:
                entity.uns_number = page.title_block.uns_number
            if not entity.process_spec and page.title_block.process_spec:
                entity.process_spec = page.title_block.process_spec

        # Only include drawings that have at least one bound page
        if entity.pages_primary or entity.pages_supporting:
            # Merge parts lists from all bound pages
            seen_parts: set[tuple] = set()
            for page_id in entity.all_page_ids:
                page = page_lookup.get(page_id)
                if page:
                    for part in page.parts_list:
                        # Dedupe by (find_no, part_number)
                        part_key = (part.find_no, part.part_number)
                        if part_key not in seen_parts:
                            seen_parts.add(part_key)
                            entity.parts_list.append(part)

                    # Merge hardware callouts
                    entity.hardware.extend(page.hardware_callouts)

            drawings[key] = entity

    # Find orphan pages (pages that don't bind to anything with score >= 30)
    bound_page_ids: set[str] = set()
    for entity in drawings.values():
        bound_page_ids.update(entity.all_page_ids)

    for page in pages:
        if page.page_id not in bound_page_ids:
            # Check if this page had any meaningful scores at all
            max_score = 0.0
            for drawing_scores in score_matrix.values():
                if page.page_id in drawing_scores:
                    max_score = max(max_score, drawing_scores[page.page_id].score)

            if max_score < 30:  # Threshold for "didn't bind to anything meaningful"
                orphan_page_ids.append(page.page_id)
                issues.append(Issue(
                    severity=IssueSeverity.WARNING,
                    issue_type=IssueType.ORPHAN_PAGE,
                    affected=page.page_id,
                    message=f"Page {page.page_id} (from {page.source_file}) did not bind to any drawing "
                           f"(max score: {max_score:.1f})",
                    evidence_page_ids=[page.page_id],
                ))

    return BindingResult(
        drawings=drawings,
        issues=issues,
        orphan_page_ids=orphan_page_ids,
    )


# =============================================================================
# Main Assembly Function
# =============================================================================

def assemble_drawings(
    pages: list[PageExtract],
    strict_revision: bool = True,
) -> BindingResult:
    """
    Assemble pages into DrawingEntity objects using zone-weighted scoring.

    This is the main entry point for Phase 3.

    Args:
        pages: List of PageExtract from Phase 2
        strict_revision: If True, revision conflicts are BLOCKERs

    Returns:
        BindingResult with drawings, issues, and orphan_page_ids
    """
    # Build score matrix
    score_matrix = build_score_matrix(pages)

    # Resolve bindings
    return resolve_bindings(pages, score_matrix, strict_revision)


def assemble_package(
    pages: list[PageExtract],
    package_id: str,
    strict_revision: bool = True,
) -> PackageExtract:
    """
    Assemble pages into a PackageExtract.

    Convenience wrapper that creates the full PackageExtract structure.

    Args:
        pages: List of PageExtract from Phase 2
        package_id: Unique ID for this extraction run
        strict_revision: If True, revision conflicts are BLOCKERs

    Returns:
        PackageExtract with drawings, issues, and orphan_page_ids
    """
    result = assemble_drawings(pages, strict_revision)

    package = PackageExtract(
        package_id=package_id,
        pages=pages,
        drawings=result.drawings,
        issues=result.issues,
        orphan_page_ids=result.orphan_page_ids,
    )

    return package


# =============================================================================
# Utility Functions for Testing
# =============================================================================

def create_mock_page(
    page_id: str,
    source_file: str = "test.pdf",
    page_index: int = 0,
    title_block_drawing: Optional[str] = None,
    title_block_revision: Optional[str] = None,
    title_block_title: Optional[str] = None,
    occurrences: Optional[list[tuple[str, Zone, float]]] = None,
    layout_flags: Optional[LayoutFlags] = None,
    parts_list: Optional[list[BOMRow]] = None,
) -> PageExtract:
    """
    Create a mock PageExtract for testing.

    Args:
        page_id: Unique page ID
        source_file: Source PDF filename
        page_index: Page index within PDF
        title_block_drawing: Drawing number in title block
        title_block_revision: Revision in title block
        title_block_title: Title in title block
        occurrences: List of (drawing_number, zone, confidence) tuples
        layout_flags: Layout flags (has_title_block, etc.)
        parts_list: List of BOMRow objects

    Returns:
        Mocked PageExtract
    """
    title_block = TitleBlock(
        drawing_number=title_block_drawing,
        revision=title_block_revision,
        title=title_block_title,
    )

    occ_list = []
    if occurrences:
        for dn, zone, conf in occurrences:
            occ_list.append(Occurrence(
                drawing_number=dn,
                zone=zone,
                confidence=conf,
            ))

    flags = layout_flags or LayoutFlags(has_title_block=bool(title_block_drawing))

    return PageExtract(
        page_id=page_id,
        page_index=page_index,
        source_file=source_file,
        title_block=title_block,
        drawing_number_occurrences=occ_list,
        layout_flags=flags,
        parts_list=parts_list or [],
    )
