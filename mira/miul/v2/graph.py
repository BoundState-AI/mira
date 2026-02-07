#!/usr/bin/env python3
"""
Module: Graph
Purpose: MIUL Builder v2.3 - Phase 3: Graph

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

import base64
import json
import logging
import re
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

from .models import (
    DrawingEntity,
    DrawingGraph,
    DrawingKey,
    ExplosionPolicy,
    GraphEdge,
    Issue,
    IssueSeverity,
    IssueType,
    PackageExtract,
    PageExtract,
)


# =============================================================================
# Configuration
# =============================================================================

# Standard hardware prefixes - always BLACK_BOX
STANDARD_HARDWARE_PREFIXES = ("NAS", "MS", "AN", "AS", "NASM", "BAC", "HCC")

STANDARD_HARDWARE_PATTERN = re.compile(
    r'^(' + '|'.join(STANDARD_HARDWARE_PREFIXES) + r')-?\d',
    re.IGNORECASE
)

# DT PDF detection patterns
DT_PDF_PATTERNS = [
    r'.*drawing.*tree.*\.pdf$',
    r'.*-DT.*\.pdf$',
    r'.*_DT_.*\.pdf$',
    r'.*_DT\.pdf$',
]

# =============================================================================
# DT Extraction Prompt (v2.3.1 - Generic for all DT formats)
# =============================================================================

DT_EXTRACTION_PROMPT = """Analyze this Engineering Drawing Tree document and extract the parent-child hierarchy.

This document may be in various formats:
- Visual tree diagram with boxes and connecting lines
- Indented list/outline format
- Table format with columns for Level, Drawing Number, Parent, Description
- Hierarchical flowchart

Return ONLY a valid JSON object where:
- Keys are CHILD drawing numbers
- Values are PARENT (next higher assembly) drawing numbers
- Do NOT include self-references (a drawing cannot be its own parent)
- Do NOT include "DT" or "Drawing Tree" as a parent - use the actual top assembly

DRAWING NUMBER FORMATS TO LOOK FOR:
- GPE-###-# (e.g., GPE-010-A, GPE-A000-D, GPE-A100-A)
- MER#####-### (e.g., MER07540-001, MER07584-001)
- Prefix-Number-Revision (e.g., ABC-12345-A, XYZ-001-B)
- Any alphanumeric code that appears to be a drawing/part number

IMPORTANT:
- Drawing numbers are alphanumeric codes, NOT file paths or URLs
- If the document shows assembly levels (1, 2, 3, etc.), use them to determine parent-child
- If you see "NHA" or "Next Higher Assembly", that indicates the parent

Example output:
{
  "GPE-A100-A": "GPE-A000-D",
  "GPE-101-A": "GPE-A100-A",
  "GPE-A200-B": "GPE-A000-D",
  "MER07558-001": "MER07543-001"
}

Return ONLY the JSON object, no other text."""


# =============================================================================
# Helpers
# =============================================================================

def is_standard_hardware(part_number: str) -> bool:
    """Check if a part number is standard hardware."""
    return bool(STANDARD_HARDWARE_PATTERN.match(part_number))


def detect_dt_pdf(directory: Path) -> Optional[Path]:
    """Find a Drawing Tree PDF in the directory."""
    if not directory.exists():
        return None

    for pattern in DT_PDF_PATTERNS:
        regex = re.compile(pattern, re.IGNORECASE)
        for pdf_path in directory.glob("*.pdf"):
            if regex.match(pdf_path.name):
                return pdf_path
    return None


def get_explosion_policy(
    child_drawing: str,
    entities: dict[str, DrawingEntity],
) -> ExplosionPolicy:
    """
    Determine explosion policy for a child.

    Simple rules:
    - Standard hardware → BLACK_BOX
    - Child has pages in our package → EXPLODE
    - Else → BLACK_BOX
    """
    if is_standard_hardware(child_drawing):
        return ExplosionPolicy.BLACK_BOX

    if child_drawing in entities:
        entity = entities[child_drawing]
        if entity.pages_primary:
            return ExplosionPolicy.EXPLODE

    return ExplosionPolicy.BLACK_BOX


# =============================================================================
# DT Parsing (Vision API)
# =============================================================================

def _is_valid_drawing_number(value: str) -> bool:
    """Check if a string looks like a valid drawing number (not a file path)."""
    if not value:
        return False
    # Reject if it looks like a file path
    if "/" in value or "\\" in value or ":" in value:
        return False
    # Must have at least 3 alphanumeric characters
    if not re.search(r'[A-Z0-9]{3,}', value, re.IGNORECASE):
        return False
    return True


def extract_dt_hierarchy(
    dt_pdf_path: Path,
    anthropic_client: 'anthropic.Anthropic',
) -> dict[str, str]:
    """
    Parse Drawing Tree PDF with Vision API.

    Returns:
        Dict of {child_drawing: parent_drawing}
    """
    # Read PDF
    pdf_bytes = dt_pdf_path.read_bytes()
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

    LOGGER.info(f"Parsing Drawing Tree: {dt_pdf_path.name}")

    message = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_base64,
                    },
                },
                {
                    "type": "text",
                    "text": DT_EXTRACTION_PROMPT,
                },
            ],
        }],
    )

    response_text = message.content[0].text
    LOGGER.debug(f"DT Vision response length: {len(response_text)} chars")

    # Parse JSON
    try:
        # Try to find JSON in response
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1:
            json_str = response_text[start:end + 1]
            raw_hierarchy = json.loads(json_str)

            # Validate and filter the hierarchy
            validated_hierarchy = {}
            invalid_count = 0
            for child, parent in raw_hierarchy.items():
                # Validate both child and parent are valid drawing numbers
                if not _is_valid_drawing_number(child):
                    LOGGER.warning(f"Skipping invalid child drawing number: {child}")
                    invalid_count += 1
                    continue
                # Parent can be empty (for root) but if not empty, must be valid
                if parent and not _is_valid_drawing_number(parent):
                    LOGGER.warning(f"Skipping invalid parent drawing number: {parent} (for child {child})")
                    invalid_count += 1
                    continue
                validated_hierarchy[child] = parent

            if invalid_count > 0:
                LOGGER.warning(f"Filtered out {invalid_count} invalid drawing number entries")

            LOGGER.info(f"DT hierarchy extracted: {len(validated_hierarchy)} valid relationships")
            return validated_hierarchy

    except json.JSONDecodeError as e:
        LOGGER.warning(f"Failed to parse DT response: {e}")
        LOGGER.debug(f"Response text: {response_text[:500]}...")

    return {}


# =============================================================================
# Hierarchy Inference (No DT)
# =============================================================================

def infer_hierarchy_from_entities(
    entities: dict[str, DrawingEntity],
    page_lookup: dict[str, PageExtract],
) -> dict[str, str]:
    """
    Infer parent-child hierarchy from NHA fields ONLY.

    Per v1 architecture: DT is SSOT for hierarchy. When no DT, use only
    the NHA (Next Higher Assembly) field which is a reliable single field.

    Parts lists are NOT used for hierarchy inference - they contain all
    sorts of items (fasteners, seals, hardware, specs) that aren't drawings.
    Parts lists contribute MIUL entries (leaf parts) during tree traversal.

    Returns:
        Dict of {child_drawing: parent_drawing}
    """
    hierarchy: dict[str, str] = {}

    # NHA fields tell us child → parent directly
    # This is the ONLY reliable source when no DT
    for drawing_number, entity in entities.items():
        for page_id in entity.all_page_ids:
            if page_id in page_lookup:
                page = page_lookup[page_id]
                nha = page.title_block.nha_part_number
                if nha and nha != drawing_number:
                    hierarchy[drawing_number] = nha
                    LOGGER.debug(f"NHA: {drawing_number} -> {nha}")
                    break

    return hierarchy


# =============================================================================
# Graph Building
# =============================================================================

def build_graph(
    entities: dict[str, DrawingEntity],
    page_lookup: dict[str, PageExtract],
    dt_pdf_path: Optional[Path] = None,
    anthropic_client: Optional['anthropic.Anthropic'] = None,
    root_drawing: Optional[str] = None,
) -> tuple[DrawingGraph, list[Issue]]:
    """
    Build the drawing hierarchy graph.

    Simple approach:
    1. If DT exists and we have a client → parse DT (source of truth)
    2. Else → infer from NHA and parts lists
    3. Build edges with explosion policies
    4. Find root

    Args:
        entities: Dict of drawing_number → DrawingEntity
        page_lookup: Dict of page_id → PageExtract
        dt_pdf_path: Optional Drawing Tree PDF
        anthropic_client: Anthropic client for Vision API
        root_drawing: Optional explicit root drawing number

    Returns:
        (DrawingGraph, list of Issues)
    """
    issues: list[Issue] = []

    # Get hierarchy
    if dt_pdf_path and anthropic_client:
        hierarchy = extract_dt_hierarchy(dt_pdf_path, anthropic_client)
        LOGGER.info(f"DT hierarchy: {len(hierarchy)} relationships")
    else:
        hierarchy = infer_hierarchy_from_entities(entities, page_lookup)
        LOGGER.info(f"Inferred hierarchy: {len(hierarchy)} relationships")

    # Build graph
    graph = DrawingGraph(nodes={})

    # Add all entities as nodes
    for drawing_number, entity in entities.items():
        key = DrawingKey(drawing_number=drawing_number)
        graph.nodes[key] = entity

    # Build edges
    for child, parent in hierarchy.items():
        policy = get_explosion_policy(child, entities)

        # Check if child is missing from our package
        if child not in entities and not is_standard_hardware(child):
            issues.append(Issue(
                severity=IssueSeverity.WARNING,
                issue_type=IssueType.MISSING_CHILD,
                affected=child,
                message=f"Child {child} referenced but no pages found",
                evidence_page_ids=[],
            ))

        edge = GraphEdge(
            parent=DrawingKey(drawing_number=parent),
            child=DrawingKey(drawing_number=child),
            qty_per_parent=1,  # Will be filled from parts list
            explosion_policy=policy,
        )
        graph.edges.append(edge)

    # Find root (drawing with no parent)
    children = set(hierarchy.keys())
    parents = set(hierarchy.values())
    roots = parents - children

    # Filter to roots that are actually in our package
    valid_roots = {r for r in roots if r in entities}

    if root_drawing:
        # Explicit root from CLI
        graph.root = DrawingKey(drawing_number=root_drawing)
    elif len(valid_roots) == 1:
        # Single valid root found
        graph.root = DrawingKey(drawing_number=valid_roots.pop())
    elif len(valid_roots) > 1:
        # Multiple roots - pick the one with most children
        root_child_counts = {r: sum(1 for c, p in hierarchy.items() if p == r) for r in valid_roots}
        best_root = max(root_child_counts, key=root_child_counts.get)
        graph.root = DrawingKey(drawing_number=best_root)
        LOGGER.warning(f"Multiple roots found: {valid_roots}, selected {best_root}")
    elif entities:
        # No hierarchy or all roots are external - pick first entity as root
        first_key = next(iter(entities.keys()))
        graph.root = DrawingKey(drawing_number=first_key)
        LOGGER.info(f"No root in package, using first entity: {first_key}")

    return graph, issues


# =============================================================================
# Main Entry Point
# =============================================================================

def build_drawing_graph(
    package: PackageExtract,
    dt_pdf_path: Optional[Path] = None,
    anthropic_client: Optional['anthropic.Anthropic'] = None,
    root_drawing: Optional[str] = None,
) -> PackageExtract:
    """
    Build graph and update package.

    Args:
        package: PackageExtract from Phase 2
        dt_pdf_path: Optional Drawing Tree PDF
        anthropic_client: Anthropic client for Vision API
        root_drawing: Optional explicit root drawing number

    Returns:
        Updated PackageExtract with graph
    """
    # Build entity lookup by drawing number
    entities: dict[str, DrawingEntity] = {}
    for key, entity in package.drawings.items():
        entities[key.drawing_number] = entity

    # Build page lookup
    page_lookup: dict[str, PageExtract] = {p.page_id: p for p in package.pages}

    # Build graph
    graph, issues = build_graph(
        entities,
        page_lookup,
        dt_pdf_path,
        anthropic_client,
        root_drawing,
    )

    # Update package
    package.graph = graph
    package.issues.extend(issues)

    return package
