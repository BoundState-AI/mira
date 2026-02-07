#!/usr/bin/env python3
"""
Module: Gap and Constraint Models
Purpose: Typed gap/failure signals and operational constraints

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
NASA-STD-6016C Compliance Module - Gap and Constraint Models

GapSignal: Typed gap/failure signal emitted by adapters.
OperationalConstraint: Structured constraint for COMPLIANT_WITH_CONSTRAINTS status.

Fran Fix #6: Hash-based IDs for collision prevention.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from typing import Optional

from pydantic import BaseModel, Field

from mira.compliance.models.enums import (
    ComplianceBasis,
    ConstraintSource,
    FailureMode,
    GapSeverity,
    GapTrigger,
)
from mira.compliance.models.evidence import EvidenceRef


class GapSignal(BaseModel):
    """
    Typed gap/failure signal emitted by adapters.

    IMPORTANT: Adapters emit these. Conductor maps them to MPRs.
    The gap_id is a deterministic hash, not a formatted string.

    Fran Fix #1: Adapters emit signals only, conductor maps to MPRs.
    Fran Fix #6: gap_id is computed via compute_gap_id() for collision prevention.
    """

    # Identity (hash-based, not formatted string)
    gap_id: str
    """Deterministic hash computed via compute_gap_id()."""

    # Classification
    gap_type: FailureMode
    """Type of failure mode this gap represents."""

    trigger: GapTrigger
    """What triggered this gap signal."""

    trigger_parameter: str
    """What input or rule fired (e.g., 'material_family', 'pressure')."""

    # Material & environment linkage
    material_id: str
    """Canonical material identifier (e.g., 'MAPTIS:12345')."""

    environment_id: Optional[str] = None
    """Environment identifier if applicable."""

    # Details (structured, not free-text)
    failing_rating: Optional[str] = None
    """Rating that failed (e.g., 'B', 'C', 'X')."""

    hee_band: Optional[str] = None
    """HEE band if applicable (extreme, severe, high, small, negligible)."""

    test_value: Optional[float] = None
    """Actual test/measured value that triggered the gap."""

    required_value: Optional[float] = None
    """Required value that was not met."""

    policy_rule: Optional[str] = None
    """Policy rule that triggered the gap (e.g., 'O2 family gate: titanium')."""

    # Severity (deterministic from HEE band or policy)
    severity: GapSeverity
    """Severity level - derived deterministically, not from human text."""

    # Confidence
    confidence: float = Field(ge=0.0, le=1.0)
    """Confidence in this gap signal (0.0-1.0)."""

    # Evidence
    evidence_refs: list[EvidenceRef] = []
    """Evidence supporting this gap signal."""

    # Metadata
    summary: str
    """Human-readable summary of the gap."""

    source_adapter: str
    """Which adapter emitted this signal (e.g., 'o2_adapter', 'h2_adapter')."""

    # Basis recommendation (adapter suggests, conductor decides)
    suggested_basis: ComplianceBasis
    """Adapter's suggested basis - conductor makes final decision."""

    model_config = {"extra": "forbid"}

    def is_critical(self) -> bool:
        """Check if this gap is critical severity."""
        return self.severity == GapSeverity.CRITICAL

    def is_hee_related(self) -> bool:
        """Check if this gap is HEE-related."""
        return self.gap_type == FailureMode.HEE

    def is_o2_related(self) -> bool:
        """Check if this gap is O2-related."""
        return self.gap_type in {FailureMode.O2_PROHIBITED, FailureMode.O2_RESTRICTED, FailureMode.FLAM}

    def requires_mua(self) -> bool:
        """Check if this gap requires MUA generation."""
        return self.severity in {GapSeverity.CRITICAL, GapSeverity.HIGH}


class OperationalConstraint(BaseModel):
    """
    Structured constraint for COMPLIANT_WITH_CONSTRAINTS status.

    Captures specific operational limits that must be observed
    for the material to be used safely.

    Fran Fix #6: constraint_id is hash-based via compute_constraint_id().
    """

    # Identity
    constraint_id: str
    """Deterministic hash computed via compute_constraint_id()."""

    # Content
    description: str
    """Human-readable description of the constraint."""

    source_basis: ConstraintSource
    """Where this constraint comes from."""

    parameter: str
    """Constrained parameter (e.g., 'pressure', 'temperature', 'exposure_time')."""

    limit_type: str
    """Type of limit: 'max', 'min', 'avoid', 'require'."""

    limit_value: str
    """Value of the limit (as string to handle units)."""

    verification_method: str
    """How to verify this constraint is met."""

    # Evidence
    evidence_ref: Optional[EvidenceRef] = None
    """Evidence supporting this constraint."""

    model_config = {"extra": "forbid"}

    def is_pressure_constraint(self) -> bool:
        """Check if this constrains pressure."""
        return "pressure" in self.parameter.lower()

    def is_temperature_constraint(self) -> bool:
        """Check if this constrains temperature."""
        return "temp" in self.parameter.lower()

    def format_for_document(self) -> str:
        """Format constraint for inclusion in compliance document."""
        return f"{self.parameter}: {self.limit_type} {self.limit_value} ({self.verification_method})"


class GapSummary(BaseModel):
    """
    Summary of gaps for a material/environment combination.

    Used for rollup reporting and MUA triggering decisions.
    """

    material_id: str
    """Canonical material identifier."""

    environment_id: Optional[str] = None
    """Environment identifier."""

    total_gaps: int = 0
    """Total number of gaps."""

    critical_gaps: int = 0
    """Number of critical-severity gaps."""

    high_gaps: int = 0
    """Number of high-severity gaps."""

    medium_gaps: int = 0
    """Number of medium-severity gaps."""

    low_gaps: int = 0
    """Number of low-severity gaps."""

    hee_gaps: int = 0
    """Number of HEE-related gaps."""

    o2_gaps: int = 0
    """Number of O2-related gaps."""

    requires_mua: bool = False
    """Whether any gap requires MUA generation."""

    gap_ids: list[str] = []
    """List of gap IDs for traceability."""

    model_config = {"extra": "forbid"}

    @classmethod
    def from_gaps(
        cls,
        gaps: list[GapSignal],
        material_id: str,
        environment_id: Optional[str] = None,
    ) -> "GapSummary":
        """Create a summary from a list of gaps."""
        summary = cls(
            material_id=material_id,
            environment_id=environment_id,
            total_gaps=len(gaps),
        )

        for gap in gaps:
            summary.gap_ids.append(gap.gap_id)

            if gap.severity == GapSeverity.CRITICAL:
                summary.critical_gaps += 1
            elif gap.severity == GapSeverity.HIGH:
                summary.high_gaps += 1
            elif gap.severity == GapSeverity.MEDIUM:
                summary.medium_gaps += 1
            else:
                summary.low_gaps += 1

            if gap.is_hee_related():
                summary.hee_gaps += 1

            if gap.is_o2_related():
                summary.o2_gaps += 1

            if gap.requires_mua():
                summary.requires_mua = True

        return summary
