#!/usr/bin/env python3
"""
Module: Material Resolution Model
Purpose: Material resolver output with canonical identifiers

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - Material Resolution Model

MaterialResolutionResult: Output from material resolver with canonical identifiers.

Fran Fix #5: When resolved, pass canonical_name to H2 twin, not the raw plan string.
Also includes h2_token_match_risk assessment.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from typing import Any, Optional

from pydantic import BaseModel, model_validator

from mira.compliance.models.evidence import EvidenceRef


class MaterialResolutionResult(BaseModel):
    """
    Material resolution result.

    Fran Fix #5: When resolved, pass canonical_name to H2 twin,
    not the raw plan string. Set h2_token_match_risk when appropriate.

    The resolver takes plan input (which may be ambiguous, misspelled,
    or underspecified) and resolves to canonical MAPTIS identifiers.
    """

    # Input (what the plan said)
    input_maptis_code: Optional[int] = None
    """MAPTIS code from plan, if provided."""

    input_material_name: Optional[str] = None
    """Material name from plan (may be informal/incomplete)."""

    input_material_spec: Optional[str] = None
    """Material specification from plan (e.g., 'AMS-4928')."""

    # Resolution result
    resolved: bool
    """Whether resolution succeeded."""

    resolution_method: str
    """How the material was resolved (e.g., 'maptis_code_direct', 'name_search')."""

    resolution_confidence: float
    """Confidence in resolution (0.0-1.0)."""

    # Resolved identifiers (authoritative)
    canonical_maptis_code: Optional[int] = None
    """Resolved MAPTIS code (authoritative)."""

    canonical_material_id: Optional[str] = None
    """Canonical material ID (e.g., 'MAPTIS:12345')."""

    canonical_name: Optional[str] = None
    """Canonical material name - pass THIS to H2, not input_material_name."""

    canonical_spec: Optional[str] = None
    """Canonical specification (e.g., 'AMS 4928T')."""

    material_family: Optional[str] = None
    """Material family classification (e.g., 'nickel_alloy')."""

    # H2 token match risk assessment (Fran Fix #5)
    h2_token_match_risk: bool = False
    """Whether H2 twin may have token matching issues with this material."""

    h2_token_match_risk_reasons: list[str] = []
    """Why H2 token match risk was flagged."""

    # Ambiguity handling
    ambiguous: bool = False
    """Whether resolution was ambiguous (multiple candidates)."""

    ambiguous_candidates: list[str] = []
    """List of candidate materials if ambiguous."""

    # Audit trail
    evidence_ref: Optional[EvidenceRef] = None
    """Evidence for resolution (MAPTIS lookup result)."""

    decision_trace: dict[str, Any] = {}
    """Trace of resolution decisions for debugging."""

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_resolved_has_identifiers(self):
        """Ensure resolved materials have required identifiers."""
        if self.resolved:
            if not self.canonical_material_id:
                raise ValueError("resolved=True requires canonical_material_id")
            if not self.evidence_ref:
                raise ValueError("resolved=True requires evidence_ref")
            if not self.canonical_name:
                raise ValueError("resolved=True requires canonical_name")
        return self

    def should_flag_h2_risk(self) -> bool:
        """
        Determine if H2 token match risk should be flagged.

        Fran Fix #5: Flag when:
        - canonical_name is generic (e.g., just "steel")
        - input contained multiple alloys/specs
        - resolution method was fuzzy

        Returns:
            True if H2 token match risk is present.
        """
        reasons = []

        # Generic name check
        generic_terms = {
            "steel", "aluminum", "alloy", "metal", "polymer",
            "plastic", "rubber", "composite", "ceramic"
        }
        if self.canonical_name and self.canonical_name.lower() in generic_terms:
            reasons.append("canonical_name is generic")

        # Multiple specs in input
        if self.input_material_name:
            spec_patterns = ["/", " or ", " and ", ",", ";"]
            if any(p in self.input_material_name for p in spec_patterns):
                reasons.append("input_material_name contains multiple specs")

        # Fuzzy resolution methods that may be unreliable
        fuzzy_methods = {"name_search_single", "approved_synonym", "fuzzy_match"}
        if self.resolution_method in fuzzy_methods:
            reasons.append(f"resolution_method={self.resolution_method}")

        # Low confidence resolution
        if self.resolution_confidence < 0.8:
            reasons.append(f"low resolution confidence ({self.resolution_confidence:.2f})")

        # Ambiguous resolution
        if self.ambiguous:
            reasons.append("resolution was ambiguous")

        self.h2_token_match_risk = len(reasons) > 0
        self.h2_token_match_risk_reasons = reasons
        return self.h2_token_match_risk

    def get_h2_query_name(self) -> Optional[str]:
        """
        Get the name to use for H2 twin queries.

        Fran Fix #5: Always use canonical_name, not input.

        Returns:
            canonical_name if resolved, None otherwise.
        """
        if not self.resolved:
            return None
        return self.canonical_name

    def format_for_audit(self) -> str:
        """Format resolution for audit trail."""
        if not self.resolved:
            return f"UNRESOLVED: '{self.input_material_name}' (spec: {self.input_material_spec})"

        parts = [
            f"Material: {self.canonical_name}",
            f"MAPTIS: {self.canonical_maptis_code}",
            f"Spec: {self.canonical_spec}",
            f"Family: {self.material_family}",
            f"Confidence: {self.resolution_confidence:.2f}",
        ]

        if self.h2_token_match_risk:
            parts.append(f"H2 Risk: {', '.join(self.h2_token_match_risk_reasons)}")

        return " | ".join(parts)


class MaterialResolutionBatch(BaseModel):
    """
    Batch of material resolution results for a plan.

    Provides utilities for analyzing resolution quality.
    """

    resolutions: list[MaterialResolutionResult] = []
    """List of resolution results."""

    model_config = {"extra": "forbid"}

    @property
    def total_materials(self) -> int:
        """Total number of materials."""
        return len(self.resolutions)

    @property
    def resolved_count(self) -> int:
        """Number of successfully resolved materials."""
        return sum(1 for r in self.resolutions if r.resolved)

    @property
    def unresolved_count(self) -> int:
        """Number of unresolved materials."""
        return sum(1 for r in self.resolutions if not r.resolved)

    @property
    def ambiguous_count(self) -> int:
        """Number of ambiguous resolutions."""
        return sum(1 for r in self.resolutions if r.ambiguous)

    @property
    def h2_risk_count(self) -> int:
        """Number of materials with H2 token match risk."""
        return sum(1 for r in self.resolutions if r.h2_token_match_risk)

    def get_resolved(self) -> list[MaterialResolutionResult]:
        """Get all resolved materials."""
        return [r for r in self.resolutions if r.resolved]

    def get_unresolved(self) -> list[MaterialResolutionResult]:
        """Get all unresolved materials."""
        return [r for r in self.resolutions if not r.resolved]

    def get_with_h2_risk(self) -> list[MaterialResolutionResult]:
        """Get materials with H2 token match risk."""
        return [r for r in self.resolutions if r.h2_token_match_risk]

    def all_resolved(self) -> bool:
        """Check if all materials were resolved."""
        return all(r.resolved for r in self.resolutions)
