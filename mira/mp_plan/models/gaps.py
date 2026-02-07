#!/usr/bin/env python3
"""
Module: Gap Models (V2 Split)
Purpose: Deficiency vs Nonconformance split for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #7: Split gap types
- DeficiencySignal: Missing input/evidence (blocks decision)
- NonconformanceSignal: Evidence indicates failure (requires closure)

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from mira.compliance.models.enums import FailureMode, GapSeverity, GapTrigger
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal

__version__ = "2.0.0"
__safety_critical__ = False


class DeficiencySignal(BaseModel):
    """
    Missing input or evidence that blocks a decision.

    NOT a compliance failure - we just cannot determine compliance yet.
    This is distinct from NonconformanceSignal which indicates actual failure.

    Fran Fix #7: "Mixed gap types" -> split into Deficiency vs Nonconformance.

    Compliance: SWE-013 (gap tracking).
    """

    deficiency_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this deficiency."""

    deficiency_type: str
    """Type of deficiency: 'missing_maptis_code', 'missing_mass', 'missing_test_report', etc."""

    # What's missing
    missing_field: str
    """The specific field that is missing."""

    missing_for: str
    """What decision is blocked by this missing data."""

    # Material/environment context
    material_id: Optional[str] = None
    """Material ID if deficiency is material-specific."""

    environment_id: Optional[str] = None
    """Environment ID if deficiency is environment-specific."""

    # Blocked decisions
    blocked_decision_ids: list[str] = Field(default_factory=list)
    """List of decision node IDs blocked by this deficiency."""

    # Conservative default handling
    conservative_default_available: bool = False
    """Whether a conservative default can be applied."""

    conservative_default_value: Optional[Any] = None
    """The conservative default value if available."""

    conservative_default_rationale: Optional[str] = None
    """Rationale for the conservative default."""

    source: str
    """Source that detected this deficiency."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    @classmethod
    def from_gap_signal(cls, gap: GapSignal) -> DeficiencySignal:
        """
        Create a DeficiencySignal from an existing GapSignal.

        Only call this for gaps with trigger == MISSING_DATA.
        """
        if gap.trigger != GapTrigger.MISSING_DATA:
            raise ValueError(f"Cannot convert non-MISSING_DATA gap to DeficiencySignal: {gap.trigger}")

        return cls(
            deficiency_id=gap.gap_id,
            deficiency_type=gap.trigger_parameter,
            missing_field=gap.trigger_parameter,
            missing_for=gap.summary,
            material_id=gap.material_id,
            environment_id=gap.environment_id,
            source=gap.source_adapter,
        )


class NonconformanceSignal(BaseModel):
    """
    Evidence indicates material/process does not meet requirement.

    Requires closure path selection (minor quantity, substitution, MUA, etc.).

    Fran Fix #7: "Mixed gap types" -> split into Deficiency vs Nonconformance.

    Compliance: SWE-013 (nonconformance tracking).
    """

    nonconformance_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this nonconformance."""

    gap_type: FailureMode
    """Type of failure mode: FLAM, HEE, TVS, TOX, SCC, etc."""

    # What failed
    failing_requirement: str
    """The requirement that was not met."""

    failing_value: Optional[str] = None
    """The actual value that failed (e.g., 'B', 'C', 'X')."""

    required_value: Optional[str] = None
    """The required value (e.g., 'A')."""

    # Material/environment context
    material_id: str
    """Material ID that has the nonconformance."""

    environment_id: str
    """Environment ID where nonconformance applies."""

    # Affected MPRs
    affected_mprs: list[str] = Field(default_factory=list)
    """List of MPR IDs affected by this nonconformance."""

    # Severity and confidence
    severity: GapSeverity
    """Severity level: CRITICAL, HIGH, MEDIUM, LOW."""

    confidence: float = Field(..., ge=0, le=1)
    """Confidence in this nonconformance (0.0-1.0)."""

    # Evidence
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    """Evidence supporting this nonconformance."""

    # Source
    source_adapter: str
    """Adapter that emitted this nonconformance."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    @classmethod
    def from_gap_signal(cls, gap: GapSignal, environment_id: str) -> NonconformanceSignal:
        """
        Create a NonconformanceSignal from an existing GapSignal.

        Do NOT call this for gaps with trigger == MISSING_DATA.
        """
        if gap.trigger == GapTrigger.MISSING_DATA:
            raise ValueError("Cannot convert MISSING_DATA gap to NonconformanceSignal")

        return cls(
            nonconformance_id=gap.gap_id,
            gap_type=gap.gap_type,
            failing_requirement=gap.summary,
            failing_value=gap.failing_rating or gap.hee_band,
            required_value="A" if gap.failing_rating else None,
            material_id=gap.material_id,
            environment_id=environment_id or gap.environment_id or "",
            severity=gap.severity,
            confidence=gap.confidence,
            evidence_refs=gap.evidence_refs,
            source_adapter=gap.source_adapter,
        )

    def requires_mua(self) -> bool:
        """Check if this nonconformance requires MUA generation."""
        return self.severity in {GapSeverity.CRITICAL, GapSeverity.HIGH}


def split_gap_signals(
    gaps: list[GapSignal],
    default_environment_id: str = "",
) -> tuple[list[DeficiencySignal], list[NonconformanceSignal]]:
    """
    Split GapSignal list into V2 types based on trigger.

    Args:
        gaps: List of GapSignal from compliance adapters.
        default_environment_id: Default environment ID for nonconformances.

    Returns:
        Tuple of (deficiencies, nonconformances).
    """
    deficiencies = []
    nonconformances = []

    for gap in gaps:
        if gap.trigger == GapTrigger.MISSING_DATA:
            deficiencies.append(DeficiencySignal.from_gap_signal(gap))
        else:
            nonconformances.append(
                NonconformanceSignal.from_gap_signal(gap, default_environment_id)
            )

    return deficiencies, nonconformances
