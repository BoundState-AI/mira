#!/usr/bin/env python3
"""
Module: MUA Rationale
Purpose: Generate NASA-STD-6016C §4.2.6.4 hydrogen embrittlement rationale
         from an H2 compatibility assessment result.

Produces Form 551-ready rationale text suitable for the MUA hydrogen
embrittlement section. Follows the rationale engine conventions from
mira.mua.classifier.rationale (state the gap, close the gap, cite the
standard, be terse).

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, SWE-013
Safety Critical: True
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from core.models.answer import AnswerSeverity

LOGGER = logging.getLogger(__name__)

# Standard references
_SECTION_REF = "NASA-STD-6016C §4.2.6.4"
_MPR_REF = "MPR 192/193"
_DATA_SOURCES = {
    "NASA/TM-2016-218602": "NASA H2 embrittlement test data compendium",
    "Sandia": "Sandia National Laboratories hydrogen compatibility database",
    "NSS 1740.16": "NASA Safety Standard for Hydrogen and Hydrogen Systems",
}


# ─── Models ──────────────────────────────────────────────────────────────────

class H2MUARationaleRequest(BaseModel):
    """Request to generate MUA rationale from an H2 assessment."""
    material_key: str = Field(description="Material identifier used in the H2 assessment.")
    pressure_psia: float = Field(description="Service pressure in psia.")
    temperature_k: float = Field(description="Service temperature in Kelvin.")
    phase: str = Field(description="Hydrogen phase: 'gh2' or 'lh2'.")
    condition: Optional[str] = Field(default=None, description="Heat treatment condition if specified.")
    yield_strength_ksi: Optional[float] = Field(default=None, description="Yield strength in ksi.")
    application_id: Optional[str] = Field(default=None, description="Application/component identifier.")


class H2MUARationaleResponse(BaseModel):
    """Generated MUA rationale for hydrogen embrittlement section."""
    material_key: str
    section: str = Field(default=_SECTION_REF, description="Standard section reference.")
    rationale_text: str = Field(description="Form 551-ready rationale text.")
    disposition: str = Field(description="Disposition recommendation (ACCEPTABLE / USE-AS-IS / NOT ACCEPTABLE).")
    classification: AnswerSeverity
    citations: list[str] = Field(default_factory=list, description="Standards cited in the rationale.")
    notes: Optional[str] = None


# ─── Generator ───────────────────────────────────────────────────────────────

def generate_h2_mua_rationale(request: H2MUARationaleRequest) -> H2MUARationaleResponse:
    """Generate §4.2.6.4 hydrogen embrittlement MUA rationale.

    Runs the H2 engine to get the verdict, then renders the rationale
    in Form 551 language.
    """
    from mira.h2.models import H2CompatibilityRequest, HydrogenPhase
    from mira.h2 import evaluate_h2_compatibility

    # Run the H2 assessment
    h2_request = H2CompatibilityRequest(
        question=f"MUA rationale generation for {request.material_key}",
        material_key=request.material_key,
        pressure_psia=request.pressure_psia,
        temperature_k=request.temperature_k,
        phase=HydrogenPhase(request.phase),
        yield_strength_ksi=request.yield_strength_ksi,
        condition=request.condition,
        application_id=request.application_id,
    )
    result = evaluate_h2_compatibility(h2_request)

    # Convert temperature for display
    temp_f = (request.temperature_k - 273.15) * 9 / 5 + 32
    phase_display = "GH2" if request.phase == "gh2" else "LH2"

    # Build rationale based on verdict
    citations = [_SECTION_REF]
    parts: list[str] = []

    # Opening: state the requirement
    parts.append(
        f"Per {_SECTION_REF} [{_MPR_REF}], materials in hydrogen service "
        f"shall be evaluated for hydrogen embrittlement susceptibility."
    )

    # State the service conditions
    condition_text = f" ({request.condition})" if request.condition else ""
    parts.append(
        f"{request.material_key}{condition_text} is assessed for "
        f"{phase_display} service at {request.pressure_psia:,.0f} psia, "
        f"{temp_f:,.0f}°F ({request.temperature_k:.0f} K)."
    )

    if result.classification == AnswerSeverity.OK:
        # ACCEPTABLE
        parts.append(
            f"Assessment: {result.rationale}"
        )
        if result.embrittlement_risk:
            parts.append(
                f"Hydrogen embrittlement risk is {result.embrittlement_risk}."
            )
        parts.append(
            f"Material is acceptable for use in hydrogen service at the "
            f"specified conditions per the evidence base."
        )
        disposition = "ACCEPTABLE"

        # Add evidence source citations
        if result.evidence:
            for ev in result.evidence[:2]:
                src = ev.source_id
                if src in _DATA_SOURCES:
                    citations.append(f"{src}: {_DATA_SOURCES[src]}")
                else:
                    citations.append(src)

    elif result.classification == AnswerSeverity.CAUTION:
        # USE-AS-IS with constraints
        parts.append(
            f"Assessment: {result.rationale}"
        )
        parts.append(
            "Material shows moderate hydrogen embrittlement susceptibility. "
            "Use is acceptable with engineering evaluation of service conditions "
            "against available test data."
        )
        if result.notes:
            parts.append(f"Note: {result.notes}")
        disposition = "USE-AS-IS"

    elif result.classification == AnswerSeverity.PROHIBITED:
        # NOT ACCEPTABLE
        parts.append(
            f"Assessment: {result.rationale}"
        )
        if result.embrittlement_risk:
            parts.append(
                f"Hydrogen embrittlement risk is {result.embrittlement_risk}."
            )
        parts.append(
            "Material is NOT acceptable for hydrogen service at the specified conditions. "
            "Select an alternative material with demonstrated hydrogen compatibility."
        )
        if request.yield_strength_ksi and request.yield_strength_ksi > 150:
            parts.append(
                f"Yield strength ({request.yield_strength_ksi:.0f} ksi) exceeds the "
                f"150 ksi hydrogen embrittlement threshold per NSS 1740.16 §4.3.2."
            )
            citations.append("NSS 1740.16 §4.3.2")
        disposition = "NOT ACCEPTABLE"

    elif result.needs_clarification:
        # Clarification needed — can't write final rationale
        parts.append(
            f"Assessment: {result.rationale}"
        )
        parts.append(
            "RATIONALE INCOMPLETE: Heat treatment condition must be specified "
            "before a definitive hydrogen embrittlement assessment can be made. "
        )
        if result.available_conditions:
            cond_list = ", ".join(
                f"{c.condition_name} ({c.hee_band})"
                for c in result.available_conditions
            )
            parts.append(f"Available conditions: {cond_list}.")
        disposition = "INCOMPLETE — SPECIFY CONDITION"

    else:
        # UNKNOWN
        parts.append(
            f"Assessment: {result.rationale}"
        )
        parts.append(
            "Insufficient hydrogen compatibility data exists for this material "
            "in the evidence database. Testing per ASTM G142 or ASTM E1681 "
            "is required before acceptance for hydrogen service."
        )
        citations.append("ASTM G142")
        citations.append("ASTM E1681")
        disposition = "NOT ACCEPTABLE — TESTING REQUIRED"

    # Envelope context warning
    envelope = getattr(result, "envelope_context", None)
    if envelope and isinstance(envelope, dict):
        if envelope.get("pressure_match") == "extrapolation":
            parts.append(
                "WARNING: Service pressure is outside the range of available "
                "test evidence. Extrapolation risk must be addressed."
            )
        if envelope.get("regime_match") == "mismatch":
            parts.append(
                "WARNING: Service temperature regime differs from evidence "
                "regime (cryogenic vs ambient). Additional evaluation required."
            )

    rationale_text = " ".join(parts)

    return H2MUARationaleResponse(
        material_key=request.material_key,
        rationale_text=rationale_text,
        disposition=disposition,
        classification=result.classification,
        citations=citations,
        notes=result.notes,
    )


__safety_critical__ = True
