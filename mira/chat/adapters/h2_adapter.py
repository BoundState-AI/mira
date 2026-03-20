"""
Module: MIRA Chat -- H2 Adapter
Purpose: Adapter bridging the Hydrogen Compatibility Knowledge Twin (H2 engine)
         into the MIRA Chat unified envelope per BS-SPEC-MIRA-CHAT-001-REV2.

Calls ``mira.h2.engine.evaluate_h2_compatibility`` with an
``H2CompatibilityRequest`` and maps the ``H2CompatibilityResponse`` to a
standard ``EngineEnvelope``.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

__version__ = "1.0.0"
__safety_critical__ = True

import logging
from typing import Any, Optional

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports -- avoid hard failures if H2 twin is not available
# ---------------------------------------------------------------------------

_H2_AVAILABLE: Optional[bool] = None


def _ensure_h2_imports():
    """Lazy-import the H2 engine and request/response models."""
    global _H2_AVAILABLE
    if _H2_AVAILABLE is not None:
        return _H2_AVAILABLE
    try:
        from mira.h2.engine import evaluate_h2_compatibility  # noqa: F401
        from mira.h2.models import (  # noqa: F401
            H2CompatibilityRequest,
            H2CompatibilityResponse,
            HydrogenPhase,
        )

        _H2_AVAILABLE = True
    except Exception as exc:
        LOGGER.warning("H2 Knowledge Twin not available: %s", exc)
        _H2_AVAILABLE = False
    return _H2_AVAILABLE


# ---------------------------------------------------------------------------
# Severity -> Chat Status mapping
# ---------------------------------------------------------------------------

_SEVERITY_TO_STATUS = {
    "ok": Status.PASS,
    "caution": Status.CONDITIONAL_PASS,
    "prohibited": Status.FAIL,
    "unknown": Status.INSUFFICIENT_DATA,
}


def _map_severity(classification_value: str) -> Status:
    """Map an AnswerSeverity value string to a Chat Status."""
    return _SEVERITY_TO_STATUS.get(classification_value, Status.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Default operating conditions when the user omits them
# ---------------------------------------------------------------------------

_DEFAULT_PRESSURE_PSIA = 14.7  # 1 atm
_DEFAULT_TEMPERATURE_K = 293.15  # ~20 C / ~68 F
_DEFAULT_PHASE = "gh2"


# ---------------------------------------------------------------------------
# H2 Adapter
# ---------------------------------------------------------------------------


class H2Adapter(EngineAdapter):
    """
    Adapter for the Hydrogen Compatibility Knowledge Twin.

    Expects ``parsed_input`` keys:

    * ``material`` (str, required) -- canonical material name or spec key
    * ``pressure_psia`` (float, optional) -- operating pressure in psia
    * ``temperature_k`` (float, optional) -- operating temperature in Kelvin
    * ``phase`` (str, optional) -- ``"gh2"`` or ``"lh2"``
    * ``question`` (str, optional) -- original natural-language question
    * ``yield_strength_ksi`` (float, optional)
    * ``condition`` (str, optional) -- heat-treatment condition
    """

    engine_id: str = "h2"
    engine_version: str = __version__
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Evaluate hydrogen compatibility and return a normalised envelope."""
        if not _ensure_h2_imports():
            return self.wrap_error(
                exc=RuntimeError("H2 Knowledge Twin is not available on this instance."),
            )

        # Late imports (guaranteed safe after _ensure_h2_imports succeeds)
        from mira.h2.engine import evaluate_h2_compatibility
        from mira.h2.models import H2CompatibilityRequest, HydrogenPhase

        material = (parsed_input.get("material") or "").strip()
        if not material:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text="Which material would you like to assess for hydrogen service?",
                missing_inputs=["material designation"],
            )

        # Build the H2 request from parsed_input
        phase_str = (parsed_input.get("phase") or _DEFAULT_PHASE).strip().lower()
        try:
            phase = HydrogenPhase(phase_str)
        except ValueError:
            phase = HydrogenPhase.GAS

        question = parsed_input.get("question") or f"Is {material} compatible with hydrogen?"

        request = H2CompatibilityRequest(
            question=question,
            material_key=material,
            pressure_psia=float(parsed_input.get("pressure_psia") or _DEFAULT_PRESSURE_PSIA),
            temperature_k=float(parsed_input.get("temperature_k") or _DEFAULT_TEMPERATURE_K),
            phase=phase,
            yield_strength_ksi=(
                float(parsed_input["yield_strength_ksi"])
                if parsed_input.get("yield_strength_ksi") is not None
                else None
            ),
            condition=parsed_input.get("condition"),
        )

        try:
            response = evaluate_h2_compatibility(request)
        except Exception as exc:
            LOGGER.error("H2 evaluate_h2_compatibility raised: %s", exc, exc_info=True)
            return self.wrap_error(exc=exc)

        return self._adapt_response(response, request)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapt_response(
        self,
        response: Any,  # H2CompatibilityResponse
        request: Any,  # H2CompatibilityRequest
    ) -> EngineEnvelope:
        """Map H2CompatibilityResponse fields to an EngineEnvelope."""
        classification_val = response.classification.value  # e.g. "ok", "caution"
        status = _map_severity(classification_val)

        # Build evidence list (serialised dicts)
        evidence: list[dict[str, Any]] = []
        for ev in response.evidence or []:
            evidence.append(
                {
                    "source_id": ev.source_id,
                    "location": ev.location,
                    "summary": ev.summary,
                }
            )

        # Authority basis from evidence source IDs
        authority_basis = list(
            {ev.source_id for ev in (response.evidence or []) if ev.source_id}
        )
        if not authority_basis:
            authority_basis = ["NASA/TM-2016-218602", "NSS 1740.16"]

        # Recommended actions
        actions: list[str] = []
        if response.needs_clarification and response.clarification_prompt:
            actions.append(response.clarification_prompt)
        if response.notes:
            actions.append(response.notes)

        # Assumptions
        assumptions: list[str] = []
        if request.pressure_psia == _DEFAULT_PRESSURE_PSIA:
            assumptions.append(f"Pressure defaulted to {_DEFAULT_PRESSURE_PSIA} psia (1 atm).")
        if request.temperature_k == _DEFAULT_TEMPERATURE_K:
            assumptions.append(f"Temperature defaulted to {_DEFAULT_TEMPERATURE_K} K (~68 F).")

        # Domain-specific extras
        domain_payload: dict[str, Any] = {
            "classification": classification_val,
            "embrittlement_risk": response.embrittlement_risk,
            "h2_score": response.h2_score,
            "needs_clarification": response.needs_clarification,
        }
        if response.band_distribution:
            domain_payload["band_distribution"] = response.band_distribution
        if response.envelope_context:
            domain_payload["envelope_context"] = response.envelope_context
        if response.available_conditions:
            domain_payload["available_conditions"] = [
                {
                    "condition_name": c.condition_name,
                    "hee_band": c.hee_band,
                    "verdict_if_selected": c.verdict_if_selected,
                    "evidence_count": c.evidence_count,
                    "source": c.source,
                }
                for c in response.available_conditions
            ]

        return self.wrap_envelope(
            status=status,
            response_text=response.rationale,
            authority_basis=authority_basis,
            citations=authority_basis,
            evidence=evidence,
            assumptions=assumptions,
            recommended_actions=actions,
            domain_payload=domain_payload,
        )
