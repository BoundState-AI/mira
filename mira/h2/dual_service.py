#!/usr/bin/env python3
"""
Module: Dual Service
Purpose: Combined LOX/LH2 (or GOX/GH2) compatibility assessment.

Evaluates a material against both oxygen and hydrogen environments in a
single call, producing a unified worst-case verdict.  Designed for
SLS-class systems where the same material may contact both propellants.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from core.models.answer import AnswerSeverity

LOGGER = logging.getLogger(__name__)

# ─── Severity ordering for worst-case merge ─────────────────────────────────

_SEVERITY_RANK = {
    AnswerSeverity.OK: 0,
    AnswerSeverity.CAUTION: 1,
    AnswerSeverity.UNKNOWN: 2,
    AnswerSeverity.PROHIBITED: 3,
}


def _worst_severity(a: AnswerSeverity, b: AnswerSeverity) -> AnswerSeverity:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


# ─── Models ──────────────────────────────────────────────────────────────────

class DualServiceRequest(BaseModel):
    """Request for combined O2 + H2 compatibility assessment."""

    material_key: str = Field(
        description="Material identifier (e.g. 'Inconel 718', '316L').",
    )

    # Hydrogen side
    h2_pressure_psia: float = Field(
        description="Hydrogen service pressure in psia.",
    )
    h2_temperature_k: float = Field(
        description="Hydrogen service temperature in Kelvin.",
    )
    h2_phase: str = Field(
        default="gh2",
        description="Hydrogen phase: 'gh2' or 'lh2'.",
    )
    h2_condition: Optional[str] = Field(
        default=None,
        description="Heat treatment condition for H2 assessment.",
    )
    yield_strength_ksi: Optional[float] = Field(
        default=None,
        description="Yield strength in ksi (for H2 high-strength guardrail).",
    )

    # Oxygen side
    o2_pressure_psia: float = Field(
        description="Oxygen service pressure in psia.",
    )
    o2_temperature_k: float = Field(
        description="Oxygen service temperature in Kelvin.",
    )
    o2_phase: str = Field(
        default="gox",
        description="Oxygen phase: 'gox' or 'lox'.",
    )

    application_id: Optional[str] = Field(
        default=None,
        description="Optional application/component identifier.",
    )


class DualServiceResponse(BaseModel):
    """Combined O2 + H2 assessment result."""

    material_key: str
    combined_verdict: str = Field(
        description="Worst-case verdict across both environments.",
    )
    combined_classification: AnswerSeverity = Field(
        description="Worst-case severity across O2 and H2.",
    )

    # Per-environment results
    h2_classification: AnswerSeverity
    h2_rationale: str
    h2_embrittlement_risk: Optional[str] = None
    h2_envelope_context: Optional[dict] = None
    h2_needs_clarification: bool = False

    o2_classification: AnswerSeverity
    o2_rationale: str

    # Combined assessment
    rationale: str = Field(
        description="Unified rationale covering both environments.",
    )
    warnings: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


# ─── Engine ──────────────────────────────────────────────────────────────────

def assess_dual_service(request: DualServiceRequest) -> DualServiceResponse:
    """Evaluate a material for combined O2 + H2 service.

    Runs both engines independently, then merges to worst-case.
    Neither engine result is suppressed — both are surfaced in full.
    """
    from mira.h2.models import H2CompatibilityRequest, HydrogenPhase
    from mira.o2.models import O2CompatibilityRequest, OxygenPhase
    from mira.h2 import evaluate_h2_compatibility
    from mira.o2 import evaluate_o2_compatibility

    # ── Run H2 engine ────────────────────────────────────────────────
    h2_request = H2CompatibilityRequest(
        question=f"Dual-service H2 assessment for {request.material_key}",
        material_key=request.material_key,
        pressure_psia=request.h2_pressure_psia,
        temperature_k=request.h2_temperature_k,
        phase=HydrogenPhase(request.h2_phase),
        yield_strength_ksi=request.yield_strength_ksi,
        condition=request.h2_condition,
        application_id=request.application_id,
    )

    h2_result = evaluate_h2_compatibility(h2_request)

    # ── Run O2 engine ────────────────────────────────────────────────
    o2_request = O2CompatibilityRequest(
        question=f"Dual-service O2 assessment for {request.material_key}",
        material_key=request.material_key,
        pressure_psia=request.o2_pressure_psia,
        temperature_k=request.o2_temperature_k,
        phase=OxygenPhase(request.o2_phase),
        application_id=request.application_id,
    )

    o2_result = evaluate_o2_compatibility(o2_request)

    # ── Merge ────────────────────────────────────────────────────────
    combined_classification = _worst_severity(
        h2_result.classification, o2_result.classification
    )

    # Build verdict label
    verdict_labels = {
        AnswerSeverity.OK: "acceptable",
        AnswerSeverity.CAUTION: "caution",
        AnswerSeverity.UNKNOWN: "unknown",
        AnswerSeverity.PROHIBITED: "prohibited",
    }
    combined_verdict = verdict_labels.get(combined_classification, "unknown")

    # Unified rationale
    parts = []
    parts.append(f"H2: {h2_result.rationale}")
    parts.append(f"O2: {o2_result.rationale}")
    if combined_classification == AnswerSeverity.PROHIBITED:
        # Identify which environment(s) caused prohibition
        blockers = []
        if h2_result.classification == AnswerSeverity.PROHIBITED:
            blockers.append("hydrogen")
        if o2_result.classification == AnswerSeverity.PROHIBITED:
            blockers.append("oxygen")
        parts.insert(0, f"PROHIBITED for dual service — blocked by {' and '.join(blockers)} assessment.")

    rationale = " | ".join(parts)

    # Warnings
    warnings: list[str] = []
    if h2_result.notes:
        warnings.append(f"[H2] {h2_result.notes}")
    if o2_result.notes:
        warnings.append(f"[O2] {o2_result.notes}")

    # Cross-environment warning: material OK in one but not the other
    if (
        h2_result.classification != o2_result.classification
        and combined_classification != AnswerSeverity.OK
    ):
        warnings.append(
            f"Split verdict: H2={h2_result.classification.value}, "
            f"O2={o2_result.classification.value}. "
            "Review each environment's assessment independently."
        )

    return DualServiceResponse(
        material_key=request.material_key,
        combined_verdict=combined_verdict,
        combined_classification=combined_classification,
        h2_classification=h2_result.classification,
        h2_rationale=h2_result.rationale,
        h2_embrittlement_risk=h2_result.embrittlement_risk,
        h2_envelope_context=h2_result.envelope_context,
        h2_needs_clarification=h2_result.needs_clarification,
        o2_classification=o2_result.classification,
        o2_rationale=o2_result.rationale,
        rationale=rationale,
        warnings=warnings,
    )


__safety_critical__ = True
