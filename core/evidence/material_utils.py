#!/usr/bin/env python3
"""
Module: Material Utils
Purpose: Material Utilities - Shared functions for material name matching and validation.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (traceability), SWE-033 (deterministic safety)
Safety Critical: True
"""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from re import Pattern

logger = logging.getLogger(__name__)

# NASA-STD-8739.8B: Safety-critical module flag
__safety_critical__: bool = True

__all__ = [
    "materials_match",
    "normalize_material_name",
    "extract_alloy_number",
    "FAMILY_ALIASES",
]

# ============================================================================
# COMPILED REGEX PATTERNS
# ============================================================================

# Matches 3-4 digit alloy numbers with optional trailing letter (e.g., 6061, 316L, 718)
_ALLOY_NUMBER_PATTERN: Pattern[str] = re.compile(r"\b(\d{3,4})[A-Za-z]?\b")

# Matches titanium-style alloy designations (e.g., 6al-4v, 6-4)
_TI_ALLOY_PATTERN: Pattern[str] = re.compile(r"\b(\d+al-\d+v)\b", re.IGNORECASE)


# ============================================================================
# MATERIAL FAMILY ALIASES
# ============================================================================

FAMILY_ALIASES: dict[str, list[str]] = {
    "aluminum": ["al", "aluminium"],
    "stainless": ["ss", "cres", "stainless steel"],
    "inconel": ["in", "inconel"],
    "hastelloy": ["ha", "hastelloy"],
    "monel": ["monel"],
    "titanium": ["ti", "titanium"],
    "copper": ["cu", "copper"],
    "nickel": ["ni", "nickel"],
    "steel": ["steel"],
}


# ============================================================================
# FUNCTIONS
# ============================================================================


def normalize_material_name(name: str) -> str:
    """
    Normalize material name for comparison.

    Strips whitespace, lowercases, and normalizes common variations.

    Args:
        name: Raw material name

    Returns:
        Normalized name for comparison

    Compliance: SWE-013 (traceability)
    """
    if not name:
        return ""
    return name.lower().strip()


def extract_alloy_number(name: str) -> set[str]:
    """
    Extract alloy numbers from material name.

    Handles patterns like:
    - "6061" from "AL 6061-T6"
    - "316" from "SS 316L"
    - "718" from "Inconel 718"

    Args:
        name: Material name

    Returns:
        Set of alloy number strings (without suffix letters)

    Compliance: SWE-013 (traceability)
    """
    if not name:
        return set()
    return set(_ALLOY_NUMBER_PATTERN.findall(name.lower()))


def materials_match(query_material: str, db_material: str) -> bool:
    """
    Determine if query material matches database material name.

    Handles common aerospace material naming variations:
    - "aluminum 6061" matches "AL 6061-O SHAPES"
    - "stainless steel 316" matches "SS 316L" or "CRES 316"
    - "inconel 718" matches "INCONEL 718"
    - "titanium 6al-4v" matches "TI 6AL-4V"

    Args:
        query_material: Material name from user query
        db_material: Material name from database

    Returns:
        True if materials are considered equivalent

    Compliance: SWE-013 (traceability), SWE-033 (deterministic safety)
    """
    if not query_material or not db_material:
        return False

    q = normalize_material_name(query_material)
    d = normalize_material_name(db_material)

    # Direct containment match
    if q in d or d in q:
        return True

    # Extract alloy numbers
    q_numbers = extract_alloy_number(q)
    d_numbers = extract_alloy_number(d)

    # Extract titanium-style designations (6al-4v)
    q_ti_alloys = set(_TI_ALLOY_PATTERN.findall(q))
    d_ti_alloys = set(_TI_ALLOY_PATTERN.findall(d))

    # Titanium alloy match (6al-4v style)
    if q_ti_alloys and d_ti_alloys and q_ti_alloys & d_ti_alloys:
        return True

    # Alloy number match with family verification
    if q_numbers and d_numbers and q_numbers & d_numbers:
        for family, aliases in FAMILY_ALIASES.items():
            q_has_family = family in q or any(alias in q for alias in aliases)
            d_has_family = family in d or any(alias in d for alias in aliases)

            # Both have same family + matching alloy number
            if q_has_family and d_has_family:
                return True

            # Query has family, db has matching alloy number (assume same family)
            if q_has_family and q_numbers & d_numbers:
                return True

    return False
