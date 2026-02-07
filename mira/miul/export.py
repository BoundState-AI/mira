#!/usr/bin/env python3
"""
Module: Export
Purpose: Determine rationale code and text for MIUL export.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from .rationale_codes import get_mua_reference_code, get_rationale
from .schema import MIULRow
from .session import PartResolution, ResolutionType
import uuid

__all__ = [
    "get_rationale_for_export",
    "apply_resolutions_to_tree",
]

__safety_critical__ = True

logger = logging.getLogger(__name__)


def get_rationale_for_export(
    part: MIULRow,
    resolution: Optional[PartResolution],
) -> Tuple[str, str]:
    """Determine rationale code and text for MIUL export.

    Two-path workflow:
    1. Technical rationale -> code goes directly to MIUL (no MUA needed)
    2. MUA reference -> code is x01/x02 + MUA number

    Args:
        part: The MIUL row being exported
        resolution: User's resolution for this part (may be None)

    Returns:
        (rationale_code, rationale_text) tuple for MIUL columns
    """
    if resolution is None:
        # No gap or not reviewed - return empty
        return ("", "")

    if resolution.resolution_type == ResolutionType.TECHNICAL_RATIONALE:
        # Direct technical justification - use the code
        if not resolution.rationale_code:
            logger.warning(
                "[Export] Technical rationale missing code for part %s",
                part.part_number,
            )
            return ("", "")

        code = resolution.rationale_code
        rationale = get_rationale(code)
        text = rationale.rationale if rationale else resolution.rationale_text or ""
        return (code, text)

    if resolution.resolution_type == ResolutionType.EXISTING_MUA_LINKED:
        # Reference to existing approved MUA
        if not resolution.mua_number or not resolution.mua_category:
            logger.warning(
                "[Export] Existing MUA linked but missing MUA number/category for part %s",
                part.part_number,
            )
            return ("", "")

        code = get_mua_reference_code(resolution.rating_type, resolution.mua_category)
        text = f"MUA {resolution.mua_number}"
        return (code, text)

    if resolution.resolution_type == ResolutionType.NEW_MUA_REQUESTED:
        if resolution.mua_number:
            # MUA was generated and approved
            if not resolution.mua_category:
                logger.warning(
                    "[Export] MUA approved but missing category for part %s",
                    part.part_number,
                )
                return ("PENDING", "MUA approved - awaiting category assignment")

            code = get_mua_reference_code(resolution.rating_type, resolution.mua_category)
            text = f"MUA {resolution.mua_number}"
            return (code, text)
        else:
            # MUA pending - export with placeholder
            return ("PENDING", "MUA requested - awaiting approval")

    if resolution.resolution_type == ResolutionType.TESTING_REQUESTED:
        # Batch/lot testing requested
        return ("TESTING", resolution.notes or "Batch/lot testing requested")

    if resolution.resolution_type == ResolutionType.SUBSTITUTION_NEEDED:
        # Material substitution required
        return ("SUBST", resolution.notes or "Material substitution required")

    if resolution.resolution_type == ResolutionType.ENGINEERING_REVIEW:
        # Escalated to engineering
        return ("REVIEW", resolution.notes or "Engineering review required")

    # Unknown resolution type
    logger.warning(
        "[Export] Unknown resolution type '%s' for part %s",
        resolution.resolution_type,
        part.part_number,
    )
    return ("", resolution.notes or "")


def apply_resolutions_to_tree(
    rows: list,
    resolutions: list,
) -> list:
    """Apply user resolutions to MIUL tree rows for export.

    Updates the rationale_code and rationale_text fields on each row
    based on the user's resolution decisions.

    Args:
        rows: List of MIULRow objects (or dicts with row data)
        resolutions: List of PartResolution objects from session

    Returns:
        Updated list with rationale fields populated
    """
    # Build resolution lookup: (part_index, rating_type) -> resolution
    resolution_map = {}
    for resolution in resolutions:
        key = (resolution.part_index, resolution.rating_type)
        resolution_map[key] = resolution

    updated_rows = []
    for row in rows:
        # Handle both MIULRow objects and dicts
        if hasattr(row, "index"):
            part_index = row.index
            part_number = row.part_number
        else:
            part_index = row.get("index", -1)
            part_number = row.get("part_number", "")

        # Skip EOF marker
        if part_index == -1:
            updated_rows.append(row)
            continue

        # Check each rating type for resolutions
        rating_types = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]
        codes = []
        texts = []

        for rating_type in rating_types:
            key = (part_index, rating_type)
            resolution = resolution_map.get(key)

            if resolution:
                # Create a mock MIULRow for the export function
                mock_row = type("MockRow", (), {"part_number": part_number})()
                code, text = get_rationale_for_export(mock_row, resolution)
                if code:
                    codes.append(f"{rating_type}:{code}")
                    if text:
                        texts.append(f"{rating_type}: {text}")

        # Combine all rationale codes and texts
        if codes:
            combined_code = "; ".join(codes)
            combined_text = "; ".join(texts)

            # Update the row
            if hasattr(row, "rationale_code"):
                row.rationale_code = combined_code
                row.rationale_text = combined_text
            else:
                row["rationale_code"] = combined_code
                row["rationale_text"] = combined_text

        updated_rows.append(row)

    return updated_rows


def format_export_summary(
    resolutions: list,
) -> dict:
    """Generate summary of resolutions for export documentation.

    Args:
        resolutions: List of PartResolution objects

    Returns:
        Summary dict with counts by resolution type
    """
    summary = {
        "total_resolutions": len(resolutions),
        "by_type": {},
        "by_rating": {},
        "pending_mua": 0,
        "approved_mua": 0,
    }

    for resolution in resolutions:
        # Count by resolution type
        res_type = resolution.resolution_type.value
        summary["by_type"][res_type] = summary["by_type"].get(res_type, 0) + 1

        # Count by rating type
        rating = resolution.rating_type
        summary["by_rating"][rating] = summary["by_rating"].get(rating, 0) + 1

        # Track MUA status
        if resolution.resolution_type == ResolutionType.NEW_MUA_REQUESTED:
            if resolution.mua_number:
                summary["approved_mua"] += 1
            else:
                summary["pending_mua"] += 1

    return summary
