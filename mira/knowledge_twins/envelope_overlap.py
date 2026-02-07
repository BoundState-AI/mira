#!/usr/bin/env python3
"""
Module: Envelope Overlap
Purpose: envelope_overlap

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from pydantic import BaseModel, Field, field_validator

from .compatibility_models import EnvironmentEnvelope, Phase
import uuid


__all__ = [
    "EnvelopeOverlapConfig",
    "DEFAULT_ENVELOPE_CONFIG",
    "calculate_range_overlap",
    "calculate_envelope_overlap",
]


# ---------------------------------------------------------------------------
# Versioned Overlap Configuration
# ---------------------------------------------------------------------------


class EnvelopeOverlapConfig(BaseModel):
    """Versioned envelope overlap weighting configuration.

    Weights determine the relative importance of each envelope component
    in the overall overlap score. Weights must sum to ~1.0.
    """

    model_config = {"extra": "forbid"}

    config_id: str
    version: str
    weights: Dict[str, float]  # temperature, pressure, phase, concentration
    provenance: str
    effective_from: str

    @field_validator("weights")
    @classmethod
    def sum_to_one(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate that weights sum to approximately 1.0."""
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Envelope weights must sum to ~1.0, got {total}")
        return v


DEFAULT_ENVELOPE_CONFIG = EnvelopeOverlapConfig(
    config_id="default_envelope",
    version="1.0.0",
    weights={
        "temperature": 0.35,
        "pressure": 0.35,
        "phase": 0.20,
        "concentration": 0.10,
    },
    provenance=(
        "Initial weights based on engineering judgment. "
        "Temperature and pressure are primary drivers for both H2 and O2 service. "
        "Set by Dr. Wilde + Claude, 2025-12-17. Subject to DOE tuning."
    ),
    effective_from="2025-12-17T00:00:00Z",
)


# ---------------------------------------------------------------------------
# Range Overlap Calculation
# ---------------------------------------------------------------------------


def calculate_range_overlap(
    q_min: float | None,
    q_max: float | None,
    r_min: float | None,
    r_max: float | None,
) -> float:
    """Calculate overlap between two ranges.

    CRITICAL: Returns 0.0 if any value is None (null-safety).

    Args:
        q_min: Query range minimum
        q_max: Query range maximum
        r_min: Record range minimum
        r_max: Record range maximum

    Returns:
        Overlap ratio (0.0 to 1.0)
        - 1.0 if query fully contained in record
        - 0.0 if no overlap or any value is None
    """
    if None in (q_min, q_max, r_min, r_max):
        return 0.0

    overlap_start = max(q_min, r_min)
    overlap_end = min(q_max, r_max)

    if overlap_start > overlap_end:
        return 0.0  # No overlap

    # Query fully contained in record
    if r_min <= q_min and r_max >= q_max:
        return 1.0

    overlap_size = overlap_end - overlap_start
    query_size = max(q_max - q_min, 1.0)  # Avoid division by zero

    return min(1.0, overlap_size / query_size)


# ---------------------------------------------------------------------------
# Envelope Overlap Calculation
# ---------------------------------------------------------------------------


def calculate_envelope_overlap(
    query_env: EnvironmentEnvelope,
    record_env: EnvironmentEnvelope,
    config: EnvelopeOverlapConfig | None = None,
) -> Tuple[float, List[str]]:
    """Calculate envelope overlap with null-safety.

    CRITICAL NULL HANDLING RULES:
    - If a component is missing in either query_env or record_env:
      - That component's overlap score = 0.0
      - A warning is emitted (used downstream for confidence penalty)
      - NO interpolation, NO guessing

    Args:
        query_env: Query environment envelope
        record_env: Record environment envelope
        config: Optional overlap config (uses DEFAULT_ENVELOPE_CONFIG if None)

    Returns:
        Tuple of (overlap_score, warnings)
        - overlap_score: Weighted overlap score (0.0 to 1.0)
        - warnings: List of warning messages for missing data
    """
    if config is None:
        config = DEFAULT_ENVELOPE_CONFIG

    w = config.weights
    warnings: List[str] = []

    # Temperature overlap
    temp_overlap = calculate_range_overlap(
        query_env.temp_min_f,
        query_env.temp_max_f,
        record_env.temp_min_f,
        record_env.temp_max_f,
    )
    if temp_overlap == 0.0:
        if query_env.temp_min_f is None or record_env.temp_min_f is None:
            warnings.append(
                "Temperature overlap unavailable due to missing envelope fields"
            )

    # Pressure overlap
    press_overlap = calculate_range_overlap(
        query_env.pressure_min_psia,
        query_env.pressure_max_psia,
        record_env.pressure_min_psia,
        record_env.pressure_max_psia,
    )
    if press_overlap == 0.0:
        if query_env.pressure_min_psia is None or record_env.pressure_min_psia is None:
            warnings.append(
                "Pressure overlap unavailable due to missing envelope fields"
            )

    # Phase match
    phase_match: float
    if query_env.phase == Phase.UNKNOWN or record_env.phase == Phase.UNKNOWN:
        phase_match = 0.0
        warnings.append("Phase match unavailable (UNKNOWN phase)")
    elif query_env.phase == record_env.phase:
        phase_match = 1.0
    elif {query_env.phase, record_env.phase} <= {Phase.LIQUID, Phase.GASEOUS}:
        # Partial credit for liquid/gaseous mismatch (same substance)
        phase_match = 0.5
    else:
        # Low credit for other phase mismatches (e.g., supercritical)
        phase_match = 0.3

    # Concentration match
    conc_match: float
    if (
        query_env.concentration_pct is None
        or record_env.concentration_pct is None
    ):
        conc_match = 0.0
        warnings.append(
            "Concentration match unavailable due to missing concentration_pct"
        )
    else:
        # For O2: >23.5% is "enriched oxygen" threshold
        q_enriched = query_env.concentration_pct >= 23.5
        r_enriched = record_env.concentration_pct >= 23.5

        if q_enriched == r_enriched:
            conc_match = 1.0
        elif q_enriched and not r_enriched:
            # Query is enriched but record is ambient - lower confidence
            conc_match = 0.3
        else:
            # Query is ambient but record is enriched - reasonable extrapolation
            conc_match = 0.7

    # Calculate weighted score
    score = (
        temp_overlap * w["temperature"]
        + press_overlap * w["pressure"]
        + phase_match * w["phase"]
        + conc_match * w["concentration"]
    )

    return score, warnings


# ---------------------------------------------------------------------------
# Confidence Penalty Calculation
# ---------------------------------------------------------------------------


def calculate_confidence_penalty(warnings: List[str]) -> float:
    """Calculate confidence penalty based on overlap warnings.

    Args:
        warnings: List of warning messages from overlap calculation

    Returns:
        Penalty factor (0.0 to 1.0) to apply to confidence score
        - 1.0 means no penalty
        - Lower values reduce confidence
    """
    if not warnings:
        return 1.0

    # Each missing component reduces confidence
    penalty_per_warning = 0.15
    total_penalty = len(warnings) * penalty_per_warning

    return max(0.5, 1.0 - total_penalty)  # Floor at 0.5 (50% confidence minimum)
