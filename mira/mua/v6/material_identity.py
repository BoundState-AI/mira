#!/usr/bin/env python3
"""
Module: Material Identity
Purpose: Material Identity Resolution for MUA v6.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: True
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from mira.miul.material_code_lookup import (
    MaterialMatch,
    get_lookup_service,
    FAMILY_PATTERNS,
)

__all__ = [
    "MaterialIdentity",
    "MaterialCandidate",
    "ResolutionMethod",
    "ConfidenceLevel",
    "resolve_material_identity",
]

__safety_critical__ = True

LOGGER = logging.getLogger(__name__)


class ResolutionMethod(str, Enum):
    """How the material identity was resolved.

    Maps directly to MaterialMatch.method values from MaterialCodeLookupService.
    """
    DIRECT_LOOKUP = "direct_lookup"
    UNS_NORMALIZED = "uns_normalized"
    EXACT_MATCH = "exact_match"
    FAMILY_FILTERED = "family_filtered"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ConfidenceLevel(str, Enum):
    """Confidence in the material identity resolution.

    Thresholds match MaterialCodeLookupService scoring:
    - HIGH: score >= 0.7 (auto-apply)
    - MEDIUM: 0.5 <= score < 0.7 (apply with warning)
    - LOW: score < 0.5 (quarantine for human review)
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MaterialCandidate(BaseModel):
    """A candidate material for ambiguous cases.

    When MaterialCodeLookupService cannot uniquely resolve a designation,
    it returns multiple candidates for human review.
    """
    model_config = {"extra": "forbid"}

    material_code: str = Field(description="MAPTIS material code")
    designation: str = Field(description="Material designation from MAPTIS")
    score: float = Field(ge=0.0, le=1.0, description="Match confidence score")


class MaterialIdentity(BaseModel):
    """Resolved material identity from MAPTIS lookup.

    When material_code is None, the identity is ambiguous or unresolved
    and requires human review (quarantine pattern).

    SWE-013: All results include source field for traceability.
    """
    model_config = {"extra": "forbid"}

    material_code: Optional[str] = Field(
        default=None,
        description="MAPTIS material code (None if ambiguous/unresolved)"
    )
    designation: str = Field(
        description="Material designation/name as queried"
    )
    confidence: ConfidenceLevel = Field(
        description="Confidence level in the resolution"
    )
    method: ResolutionMethod = Field(
        description="Method used to resolve identity"
    )
    score: float = Field(
        ge=0.0, le=1.0,
        description="Numeric confidence score (0.0-1.0)"
    )
    specs: List[str] = Field(
        default_factory=list,
        description="Associated specifications (UNS codes, AMS specs)"
    )
    material_family: Optional[str] = Field(
        default=None,
        description="Detected material family (TITANIUM, NICKEL, STAINLESS, ALUMINUM)"
    )
    candidates: List[MaterialCandidate] = Field(
        default_factory=list,
        description="Candidate materials for ambiguous cases"
    )
    source: str = Field(
        default="MaterialCodeLookupService",
        description="SWE-013: Source system for traceability"
    )

    @property
    def is_resolved(self) -> bool:
        """True if material identity was successfully resolved to a unique code."""
        return self.material_code is not None

    @property
    def needs_review(self) -> bool:
        """True if material should be quarantined for human review.

        Quarantine conditions:
        - material_code is None (ambiguous or unresolved)
        - score < 0.5 (low confidence even with a code)
        """
        return self.material_code is None or self.score < 0.5

    @property
    def is_ambiguous(self) -> bool:
        """True if multiple candidates exist requiring human selection."""
        return self.method == ResolutionMethod.AMBIGUOUS and len(self.candidates) > 0


def _detect_family(designation: str) -> Optional[str]:
    """Detect material family from designation using word-boundary patterns.

    Uses FAMILY_PATTERNS from MaterialCodeLookupService to ensure consistency.
    Order: TITANIUM, NICKEL, STAINLESS, ALUMINUM (most specific first).

    Args:
        designation: Material designation string

    Returns:
        Family name (TITANIUM, NICKEL, STAINLESS, ALUMINUM) or None
    """
    if not designation:
        return None

    # Check patterns in order (TITANIUM first to handle TI-6AL-4V correctly)
    for family, pattern in FAMILY_PATTERNS.items():
        if pattern.search(designation):
            return family
    return None


def _map_confidence(confidence_str: str, score: float) -> ConfidenceLevel:
    """Map MaterialMatch confidence string to ConfidenceLevel enum.

    Falls back to score-based classification if string doesn't match.
    """
    confidence_map = {
        "high": ConfidenceLevel.HIGH,
        "medium": ConfidenceLevel.MEDIUM,
        "low": ConfidenceLevel.LOW,
    }

    # Try string mapping first
    if confidence_str.lower() in confidence_map:
        return confidence_map[confidence_str.lower()]

    # Fall back to score-based classification
    if score >= 0.7:
        return ConfidenceLevel.HIGH
    elif score >= 0.5:
        return ConfidenceLevel.MEDIUM
    else:
        return ConfidenceLevel.LOW


def _map_method(method_str: str) -> ResolutionMethod:
    """Map MaterialMatch method string to ResolutionMethod enum."""
    method_map = {
        "direct_lookup": ResolutionMethod.DIRECT_LOOKUP,
        "uns_normalized": ResolutionMethod.UNS_NORMALIZED,
        "exact_match": ResolutionMethod.EXACT_MATCH,
        "family_filtered": ResolutionMethod.FAMILY_FILTERED,
        "ambiguous": ResolutionMethod.AMBIGUOUS,
        "unresolved": ResolutionMethod.UNRESOLVED,
    }
    return method_map.get(method_str.lower(), ResolutionMethod.UNRESOLVED)


def resolve_material_identity(designation: str) -> MaterialIdentity:
    """Resolve material identity from designation string.

    Wraps MaterialCodeLookupService.lookup_material_code() with Pydantic model.

    Args:
        designation: Material designation/name (e.g., "INCONEL 625", "316L SST")

    Returns:
        MaterialIdentity with resolution result.
        - material_code=None means ambiguous or unresolved
        - needs_review=True means should be quarantined for human review

    SWE-013: All results traceable via source field.

    Example:
        >>> identity = resolve_material_identity("INCONEL 625")
        >>> if identity.is_resolved:
        ...     print(f"Material code: {identity.material_code}")
        >>> elif identity.is_ambiguous:
        ...     print(f"Candidates: {[c.material_code for c in identity.candidates]}")
    """
    # Handle empty input
    if not designation or not designation.strip():
        LOGGER.warning("resolve_material_identity called with empty designation")
        return MaterialIdentity(
            material_code=None,
            designation=designation or "",
            confidence=ConfidenceLevel.LOW,
            method=ResolutionMethod.UNRESOLVED,
            score=0.0,
            material_family=None,
            source="MaterialCodeLookupService:empty_input",
        )

    designation_clean = designation.strip()

    # Get the singleton lookup service
    lookup = get_lookup_service()

    # Perform the lookup
    try:
        match: MaterialMatch = lookup.lookup_material_code(designation_clean)
    except Exception as e:
        LOGGER.error(f"MaterialCodeLookupService error for '{designation_clean}': {e}")
        return MaterialIdentity(
            material_code=None,
            designation=designation_clean,
            confidence=ConfidenceLevel.LOW,
            method=ResolutionMethod.UNRESOLVED,
            score=0.0,
            material_family=_detect_family(designation_clean),
            source=f"MaterialCodeLookupService:error:{type(e).__name__}",
        )

    # Map confidence and method to enums
    confidence = _map_confidence(match.confidence, match.score)
    method = _map_method(match.method)

    # Convert candidates if present (for ambiguous cases)
    candidates: List[MaterialCandidate] = []
    if match.candidates:
        for c in match.candidates:
            if c.material_code:  # Only include resolved candidates
                candidates.append(MaterialCandidate(
                    material_code=c.material_code,
                    designation=c.designation,
                    score=c.score,
                ))

    # Build the result
    identity = MaterialIdentity(
        material_code=match.material_code,  # Can be None for ambiguous/unresolved
        designation=match.designation,
        confidence=confidence,
        method=method,
        score=match.score,
        specs=match.specs or [],
        material_family=_detect_family(designation_clean),
        candidates=candidates,
        source=f"MaterialCodeLookupService:{match.method}",
    )

    # Log the resolution result
    if identity.is_resolved:
        LOGGER.debug(
            f"Resolved '{designation_clean}' -> {identity.material_code} "
            f"(method={method.value}, score={match.score:.2f})"
        )
    elif identity.is_ambiguous:
        LOGGER.info(
            f"Ambiguous '{designation_clean}' -> {len(candidates)} candidates "
            f"(needs human review)"
        )
    else:
        LOGGER.info(f"Unresolved '{designation_clean}' (method={method.value})")

    return identity
