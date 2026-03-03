#!/usr/bin/env python3
"""
Module: Envelope Matching
Purpose: Envelope-based environment matching for MUA precedent retrieval.

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
from typing import NamedTuple

from pydantic import BaseModel, Field

__all__ = [
    "OverlapStatus",
    "DimensionCheck",
    "EnvelopeOverlapResult",
    "compute_envelope_overlap",
]

__safety_critical__ = True

LOGGER = logging.getLogger(__name__)


class OverlapStatus(str, Enum):
    """Classification of query vs precedent envelope relationship.

    Safety hierarchy (most to least restrictive):
    - WITHIN: Query completely inside tested bounds (safe)
    - PARTIAL_OVERLAP: Some dimensions within, some unknown (caution)
    - EXTRAPOLATION: Query exceeds tested bounds (requires review)
    - OUTSIDE: No dimension coverage or all exceed (blocked)
    """
    WITHIN = "within"
    PARTIAL_OVERLAP = "partial"
    EXTRAPOLATION = "extrapolation"
    OUTSIDE = "outside"


class DimensionCheck(NamedTuple):
    """Result of checking one envelope dimension.

    Used for detailed per-dimension reporting in extrapolation warnings.
    """
    dimension: str  # "o2_percent", "pressure_psia", "temp_max", "temp_min"
    query_value: float | None
    precedent_bound: float | None
    status: str  # "within", "exceeds", "unknown"
    margin: float | None  # How much query exceeds (if applicable)


class EnvelopeOverlapResult(BaseModel):
    """Result of envelope overlap computation.

    SWE-013: Includes source field for traceability.
    """
    model_config = {"extra": "forbid"}

    status: OverlapStatus = Field(description="Overall overlap classification")
    overlap_ratio: float = Field(
        ge=0.0, le=1.0,
        description="Ratio of dimensions within bounds (dims_within / dims_checked)"
    )
    dimension_checks: list[DimensionCheck] = Field(
        default_factory=list,
        description="Per-dimension check results"
    )
    extrapolation_warnings: list[str] = Field(
        default_factory=list,
        description="Human-readable warnings for exceeded dimensions"
    )
    score_penalty: float = Field(
        ge=0.0, le=1.0, default=0.0,
        description="Penalty to apply to precedent score (higher = worse)"
    )
    source: str = Field(
        default="envelope_matching",
        description="SWE-013: Source for traceability"
    )

    @property
    def is_safe(self) -> bool:
        """True if query is within or has only partial overlap.

        Safe to proceed with generation (possibly with warnings).
        """
        return self.status in (OverlapStatus.WITHIN, OverlapStatus.PARTIAL_OVERLAP)

    @property
    def requires_review(self) -> bool:
        """True if extrapolation detected requiring human review."""
        return self.status == OverlapStatus.EXTRAPOLATION

    @property
    def is_blocked(self) -> bool:
        """True if completely outside tested bounds (cannot proceed)."""
        return self.status == OverlapStatus.OUTSIDE


def compute_envelope_overlap(
    query_o2_percent: float | None = None,
    query_pressure_psia: float | None = None,
    query_temp_f: float | None = None,
    precedent_o2_max: float | None = None,
    precedent_pressure_max: float | None = None,
    precedent_temp_min: float | None = None,
    precedent_temp_max: float | None = None,
) -> EnvelopeOverlapResult:
    """Compute overlap between query environment and precedent envelope.

    For safety-critical applications, query must be WITHIN precedent bounds.
    Exceeding any dimension triggers extrapolation warning requiring review.

    Dimension rules:
    - O2: query must be <= precedent_o2_max (higher O2 = more severe)
    - Pressure: query must be <= precedent_pressure_max (higher pressure = more severe)
    - Temperature: query must be within [temp_min, temp_max] range

    Args:
        query_o2_percent: Query O2 percentage requirement (0-100).
        query_pressure_psia: Query pressure requirement in PSIA.
        query_temp_f: Query temperature requirement in Fahrenheit.
        precedent_o2_max: Max O2% tested in precedent envelope.
        precedent_pressure_max: Max pressure tested in precedent envelope.
        precedent_temp_min: Min temperature tested in precedent envelope.
        precedent_temp_max: Max temperature tested in precedent envelope.

    Returns:
        EnvelopeOverlapResult with dimension-by-dimension breakdown.

    Example:
        >>> result = compute_envelope_overlap(
        ...     query_o2_percent=100.0,
        ...     query_pressure_psia=14.7,
        ...     precedent_o2_max=100.0,
        ...     precedent_pressure_max=20.0,
        ... )
        >>> result.status
        <OverlapStatus.WITHIN: 'within'>
    """
    checks: list[DimensionCheck] = []
    warnings: list[str] = []
    dims_checked = 0
    dims_within = 0

    # === O2 Check ===
    # Query must be <= precedent max (higher O2 = more severe environment)
    if query_o2_percent is not None:
        dims_checked += 1
        if precedent_o2_max is not None:
            if query_o2_percent <= precedent_o2_max:
                checks.append(DimensionCheck(
                    dimension="o2_percent",
                    query_value=query_o2_percent,
                    precedent_bound=precedent_o2_max,
                    status="within",
                    margin=None,
                ))
                dims_within += 1
            else:
                margin = query_o2_percent - precedent_o2_max
                checks.append(DimensionCheck(
                    dimension="o2_percent",
                    query_value=query_o2_percent,
                    precedent_bound=precedent_o2_max,
                    status="exceeds",
                    margin=margin,
                ))
                warnings.append(
                    f"O2 concentration {query_o2_percent:.1f}% exceeds precedent max "
                    f"{precedent_o2_max:.1f}% by {margin:.1f}%"
                )
        else:
            checks.append(DimensionCheck(
                dimension="o2_percent",
                query_value=query_o2_percent,
                precedent_bound=None,
                status="unknown",
                margin=None,
            ))
            warnings.append("Precedent has no O2 envelope data - cannot verify coverage")

    # === Pressure Check ===
    # Query must be <= precedent max (higher pressure = more severe environment)
    if query_pressure_psia is not None:
        dims_checked += 1
        if precedent_pressure_max is not None:
            if query_pressure_psia <= precedent_pressure_max:
                checks.append(DimensionCheck(
                    dimension="pressure_psia",
                    query_value=query_pressure_psia,
                    precedent_bound=precedent_pressure_max,
                    status="within",
                    margin=None,
                ))
                dims_within += 1
            else:
                margin = query_pressure_psia - precedent_pressure_max
                checks.append(DimensionCheck(
                    dimension="pressure_psia",
                    query_value=query_pressure_psia,
                    precedent_bound=precedent_pressure_max,
                    status="exceeds",
                    margin=margin,
                ))
                warnings.append(
                    f"Pressure {query_pressure_psia:.1f} PSIA exceeds precedent max "
                    f"{precedent_pressure_max:.1f} PSIA by {margin:.1f} PSIA"
                )
        else:
            checks.append(DimensionCheck(
                dimension="pressure_psia",
                query_value=query_pressure_psia,
                precedent_bound=None,
                status="unknown",
                margin=None,
            ))
            warnings.append("Precedent has no pressure envelope data - cannot verify coverage")

    # === Temperature Check ===
    # Query must be within [temp_min, temp_max] range
    if query_temp_f is not None:
        dims_checked += 1
        temp_ok = True
        temp_has_data = False

        # Check upper bound
        if precedent_temp_max is not None:
            temp_has_data = True
            if query_temp_f > precedent_temp_max:
                margin = query_temp_f - precedent_temp_max
                checks.append(DimensionCheck(
                    dimension="temp_max",
                    query_value=query_temp_f,
                    precedent_bound=precedent_temp_max,
                    status="exceeds",
                    margin=margin,
                ))
                warnings.append(
                    f"Temperature {query_temp_f:.1f}°F exceeds precedent max "
                    f"{precedent_temp_max:.1f}°F by {margin:.1f}°F"
                )
                temp_ok = False

        # Check lower bound
        if precedent_temp_min is not None:
            temp_has_data = True
            if query_temp_f < precedent_temp_min:
                margin = precedent_temp_min - query_temp_f
                checks.append(DimensionCheck(
                    dimension="temp_min",
                    query_value=query_temp_f,
                    precedent_bound=precedent_temp_min,
                    status="exceeds",
                    margin=margin,
                ))
                warnings.append(
                    f"Temperature {query_temp_f:.1f}°F below precedent min "
                    f"{precedent_temp_min:.1f}°F by {margin:.1f}°F"
                )
                temp_ok = False

        # Record result
        if temp_ok and temp_has_data:
            dims_within += 1
            checks.append(DimensionCheck(
                dimension="temperature",
                query_value=query_temp_f,
                precedent_bound=precedent_temp_max,  # Use max as reference
                status="within",
                margin=None,
            ))
        elif not temp_has_data:
            checks.append(DimensionCheck(
                dimension="temperature",
                query_value=query_temp_f,
                precedent_bound=None,
                status="unknown",
                margin=None,
            ))
            warnings.append("Precedent has no temperature envelope data - cannot verify coverage")

    # === Compute Overall Status ===
    if dims_checked == 0:
        LOGGER.warning("compute_envelope_overlap called with no query dimensions")
        return EnvelopeOverlapResult(
            status=OverlapStatus.OUTSIDE,
            overlap_ratio=0.0,
            dimension_checks=checks,
            extrapolation_warnings=["No query dimensions provided for comparison"],
            score_penalty=1.0,
        )

    overlap_ratio = dims_within / dims_checked

    # Determine status and penalty based on overlap ratio
    # Use precise fraction comparison to avoid floating-point errors (2/3 = 0.6666...)
    if overlap_ratio == 1.0:
        status = OverlapStatus.WITHIN
        penalty = 0.0
    elif dims_within >= (2 * dims_checked) / 3:
        # At least 2/3 dimensions within bounds (e.g., 2/3, 3/4, etc.)
        status = OverlapStatus.PARTIAL_OVERLAP
        penalty = 0.15
    elif overlap_ratio > 0.0:
        # Less than 2/3 but some coverage
        status = OverlapStatus.EXTRAPOLATION
        penalty = 0.4
    else:
        # No dimensions within bounds
        status = OverlapStatus.OUTSIDE
        penalty = 1.0

    LOGGER.debug(
        f"Envelope overlap: {status.value} (ratio={overlap_ratio:.2f}, "
        f"dims_within={dims_within}/{dims_checked})"
    )

    return EnvelopeOverlapResult(
        status=status,
        overlap_ratio=overlap_ratio,
        dimension_checks=checks,
        extrapolation_warnings=warnings,
        score_penalty=penalty,
    )
