"""
Module: MIRA Chat -- Fracture Mechanics Adapter
Purpose: Adapter bridging the Fracture Assessment engine (NASA-STD-5019A) into
         the MIRA Chat unified envelope per BS-SPEC-MIRA-CHAT-001-REV2.

Calls ``mira.fracture.engine.evaluate_fracture_assessment`` with a
``FractureAssessmentRequest`` and maps the ``FractureAssessmentResponse``
to a standard ``EngineEnvelope``.

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

import asyncio
import logging
from typing import Any, Optional

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports -- avoid hard failures if fracture engine is not available
# ---------------------------------------------------------------------------

_FRACTURE_AVAILABLE: Optional[bool] = None


def _ensure_fracture_imports() -> bool:
    """Lazy-import the fracture engine and request/response models."""
    global _FRACTURE_AVAILABLE
    if _FRACTURE_AVAILABLE is not None:
        return _FRACTURE_AVAILABLE
    try:
        from mira.fracture.engine import evaluate_fracture_assessment  # noqa: F401
        from mira.fracture.models import (  # noqa: F401
            FractureAssessmentRequest,
            FractureAssessmentResponse,
        )

        _FRACTURE_AVAILABLE = True
    except Exception as exc:
        LOGGER.warning("Fracture engine not available: %s", exc)
        _FRACTURE_AVAILABLE = False
    return _FRACTURE_AVAILABLE


# ---------------------------------------------------------------------------
# Classification -> Chat Status mapping
# ---------------------------------------------------------------------------

_CLASSIFICATION_TO_STATUS = {
    "EXEMPT": Status.PASS,
    "NFC_METALLIC": Status.PASS,
    "NFC_COMPOSITE_BONDED": Status.PASS,
    "FC": Status.CONDITIONAL_PASS,
    "INDETERMINATE": Status.INSUFFICIENT_DATA,
}


def _map_classification(classification: str) -> Status:
    """Map a FractureClassification value to a Chat Status."""
    return _CLASSIFICATION_TO_STATUS.get(classification, Status.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Input defaults
# ---------------------------------------------------------------------------

_DEFAULT_MISSION_CLASS = "HUMAN_RATED"
_DEFAULT_MATERIAL_SYSTEM = "METALLIC"
_DEFAULT_STRUCTURAL_ROLE = "PRIMARY"


# ---------------------------------------------------------------------------
# Fracture Adapter
# ---------------------------------------------------------------------------


class FractureAdapter(EngineAdapter):
    """
    Adapter for the Fracture Assessment engine (NASA-STD-5019A).

    Expects ``parsed_input`` keys:

    * ``part_name`` (str, required) -- name of the part being assessed
    * ``material_designation`` (str, optional) -- material name for screening
    * ``mission_class`` (str, optional) -- HUMAN_RATED, CARGO, etc.
    * ``material_system`` (str, optional) -- METALLIC, COMPOSITE, BONDED, etc.
    * ``hazard_consequence`` (str, optional) -- CATASTROPHIC, CRITICAL, etc.
    * ``load_path_type`` (str, optional) -- SINGLE, REDUNDANT, UNKNOWN
    * ``structural_role`` (str, optional) -- PRIMARY, SECONDARY, NON_STRUCTURAL
    * ``specific_hardware_type`` (str, optional) -- FASTENER, PRESSURE_VESSEL, etc.
    * ``pressure_boundary`` (bool, optional) -- is this a pressure boundary?
    * ``proof_test_used`` (bool, optional)
    * ``process_controls_used`` (bool, optional)
    * ``raw_query`` (str, optional) -- original natural-language question
    """

    engine_id: str = "fracture"
    engine_version: str = __version__
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Evaluate fracture classification and return a normalised envelope."""
        if not _ensure_fracture_imports():
            return self.wrap_error(
                exc=RuntimeError("Fracture assessment engine is not available on this instance."),
            )

        from mira.fracture.engine import evaluate_fracture_assessment
        from mira.fracture.models import FractureAssessmentRequest, FractureMaterialContext

        # Part name is required -- derive from material or raw query if absent
        part_name = (parsed_input.get("part_name") or "").strip()
        material = (parsed_input.get("material_designation") or "").strip()

        if not part_name:
            if material:
                part_name = f"{material} component"
            else:
                raw = (parsed_input.get("raw_query") or "").strip()
                if raw:
                    part_name = f"Chat query: {raw[:80]}"
                else:
                    return self.wrap_envelope(
                        status=Status.INSUFFICIENT_DATA,
                        response_text=(
                            "Fracture assessment requires at least a part name and material. "
                            "For example: 'Evaluate fracture requirements for a 7075-T6 bracket "
                            "on a human-rated spacecraft.'"
                        ),
                        missing_inputs=["part_name", "material_name"],
                    )

        # Build the material context
        material_context = FractureMaterialContext(
            low_risk_candidate=bool(parsed_input.get("low_risk_candidate", False)),
            additive_manufactured=bool(parsed_input.get("additive_manufactured", False)),
            kic_fty_ratio=parsed_input.get("kic_fty_ratio"),
            ftu_ksi=parsed_input.get("ftu_ksi"),
            chloride_exposure=bool(parsed_input.get("chloride_exposure", False)),
            sustained_load_expected=bool(parsed_input.get("sustained_load_expected", False)),
            mua_present=bool(parsed_input.get("mua_present", False)),
        )

        try:
            request = FractureAssessmentRequest(
                part_name=part_name,
                mission_class=parsed_input.get("mission_class", _DEFAULT_MISSION_CLASS),
                hazard_consequence=parsed_input.get("hazard_consequence", "UNKNOWN"),
                load_path_type=parsed_input.get("load_path_type", "UNKNOWN"),
                pressure_boundary=bool(parsed_input.get("pressure_boundary", False)),
                lifecycle_phase=parsed_input.get("lifecycle_phase", "NEW_BUILD"),
                structural_role=parsed_input.get("structural_role", _DEFAULT_STRUCTURAL_ROLE),
                material_system=parsed_input.get("material_system", _DEFAULT_MATERIAL_SYSTEM),
                specific_hardware_type=parsed_input.get("specific_hardware_type", "GENERAL"),
                material_name=material or None,
                optional_approach_requested=bool(parsed_input.get("optional_approach_requested", False)),
                proof_test_used=bool(parsed_input.get("proof_test_used", False)),
                process_controls_used=bool(parsed_input.get("process_controls_used", False)),
                detected_flaw_accepted_for_flight=bool(parsed_input.get("detected_flaw_accepted_for_flight", False)),
                corrosion_iccp_recommended=bool(parsed_input.get("corrosion_iccp_recommended", False)),
                material_context=material_context,
            )
        except Exception as exc:
            LOGGER.error("Failed to build FractureAssessmentRequest: %s", exc)
            return self.wrap_error(exc=exc)

        try:
            response = await self._run_sync(evaluate_fracture_assessment, request)
        except Exception as exc:
            LOGGER.error("evaluate_fracture_assessment raised: %s", exc, exc_info=True)
            return self.wrap_error(exc=exc)

        # Persist for follow-ups
        session_context["fracture_part_name"] = part_name
        session_context["fracture_classification"] = response.classification

        return self._adapt_response(response, request)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapt_response(
        self,
        response: Any,  # FractureAssessmentResponse
        request: Any,   # FractureAssessmentRequest
    ) -> EngineEnvelope:
        """Map FractureAssessmentResponse fields to an EngineEnvelope."""
        status = _map_classification(response.classification)

        # Build human-readable response
        lines: list[str] = [
            f"**Fracture Assessment -- {response.classification}**",
            "",
            f"Baseline: {response.baseline_key}",
            f"Confidence: {response.confidence_state}",
            f"Screening basis: {response.screening_basis}",
        ]

        # Resolved material
        if response.resolved_material:
            rm = response.resolved_material
            lines.append("")
            lines.append(f"Material: {rm.canonical_name} ({rm.material_system}, {rm.family})")

        # Applicable FCRs
        if response.applicable_fcrs:
            lines.append("")
            lines.append(f"Applicable FCRs: {', '.join(str(f) for f in response.applicable_fcrs)}")

        # Requirements summary
        if response.requirements:
            lines.append("")
            lines.append("**Requirements:**")
            for req in response.requirements[:10]:  # Cap display
                lines.append(f"- FCR {req.fcr}: {req.title} ({req.section})")

        # Required actions
        if response.required_actions:
            lines.append("")
            lines.append("**Required actions:**")
            for action in response.required_actions[:10]:
                lines.append(f"- {action}")

        # Required documents
        if response.required_documents:
            lines.append("")
            lines.append("**Required documents:**")
            for doc in response.required_documents:
                lines.append(f"- {doc}")

        # Material findings
        if response.material_findings:
            lines.append("")
            lines.append("**Material findings:**")
            for finding in response.material_findings:
                lines.append(f"- [{finding.status}] {finding.title}: {finding.detail}")

        # Warnings
        if response.warnings:
            lines.append("")
            lines.append("**Warnings:**")
            for w in response.warnings:
                lines.append(f"- {w}")

        # Unresolved inputs
        if response.unresolved_inputs:
            lines.append("")
            lines.append("**Unresolved inputs (additional data needed):**")
            for ui in response.unresolved_inputs:
                lines.append(f"- {ui}")

        response_text = "\n".join(lines)

        # Authority basis
        authority_basis = ["NASA-STD-5019A w/Change 4"]

        # Citations from FCR citations
        citations: list[str] = []
        for citation in response.citations:
            citations.append(
                f"FCR {citation.fcr}: {citation.title} ({citation.section}) -- {citation.source_document}"
            )

        # Evidence from material findings
        evidence: list[dict[str, Any]] = []
        for finding in response.material_findings:
            evidence.append({
                "source_id": finding.finding_id,
                "status": finding.status,
                "summary": f"{finding.title}: {finding.detail}",
                "governing_fcrs": finding.governing_fcrs,
            })

        # Recommended actions
        actions = list(response.required_actions)

        # Domain payload
        domain_payload: dict[str, Any] = {
            "classification": response.classification,
            "baseline_key": response.baseline_key,
            "confidence_state": response.confidence_state,
            "applicable_fcrs": response.applicable_fcrs,
            "required_documents": response.required_documents,
            "unresolved_inputs": response.unresolved_inputs,
            "conservative_fallback": response.conservative_fallback,
            "source_manifest_version": response.source_manifest_version,
        }

        if response.resolved_material:
            domain_payload["resolved_material"] = response.resolved_material.model_dump(mode="json")

        return self.wrap_envelope(
            status=status,
            response_text=response_text,
            authority_basis=authority_basis,
            citations=citations,
            evidence=evidence,
            assumptions=[
                f"Mission class: {request.mission_class}",
                f"Material system: {request.material_system}",
                f"Structural role: {request.structural_role}",
            ],
            missing_inputs=response.unresolved_inputs,
            recommended_actions=actions,
            domain_payload=domain_payload,
        )

    @staticmethod
    async def _run_sync(func, *args, **kwargs):
        """Run a synchronous engine function in the default executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
