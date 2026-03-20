"""
Module: MIRA Chat -- GPCM Compliance Adapter
Purpose: Adapter bridging the GPCM (NASA-STD-6016C Compliance Conductor) into
         the MIRA Chat unified envelope per BS-SPEC-MIRA-CHAT-001-REV2.

Routes from ``document_lookup`` intent with compliance-checking context.
Delegates to ``mira.compliance.conductor`` for full NASA-STD-6016C
compliance analysis including O2, H2, and MUA adapter orchestration.

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
# Lazy imports -- avoid hard failures if compliance conductor is not available
# ---------------------------------------------------------------------------

_GPCM_AVAILABLE: Optional[bool] = None


def _ensure_gpcm_imports() -> bool:
    """Lazy-import the compliance conductor and related models."""
    global _GPCM_AVAILABLE
    if _GPCM_AVAILABLE is not None:
        return _GPCM_AVAILABLE
    try:
        from mira.compliance.conductor import ComplianceConductor  # noqa: F401
        from mira.compliance.models.policy import EnvironmentPolicy  # noqa: F401

        _GPCM_AVAILABLE = True
    except Exception as exc:
        LOGGER.warning("GPCM compliance conductor not available: %s", exc)
        _GPCM_AVAILABLE = False
    return _GPCM_AVAILABLE


# ---------------------------------------------------------------------------
# Compliance status -> Chat Status mapping
# ---------------------------------------------------------------------------

_COMPLIANCE_TO_STATUS: dict[str, Status] = {
    "COMPLIANT": Status.PASS,
    "COMPLIANT_WITH_CONTROLS": Status.CONDITIONAL_PASS,
    "CONDITIONAL": Status.CONDITIONAL_PASS,
    "NON_COMPLIANT": Status.FAIL,
    "INSUFFICIENT_DATA": Status.INSUFFICIENT_DATA,
    "NOT_APPLICABLE": Status.PASS,
}


def _map_compliance_status(compliance_status: str) -> Status:
    """Map a compliance analysis status string to a Chat Status."""
    return _COMPLIANCE_TO_STATUS.get(compliance_status, Status.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# GPCM Adapter
# ---------------------------------------------------------------------------


class GPCMAdapter(EngineAdapter):
    """
    Adapter for the GPCM (General Purpose Compliance Module) / NASA-STD-6016C
    Compliance Conductor.

    Routes from ``document_lookup`` intent when compliance-check context is
    detected, or explicitly via ``fine_routing='gpcm'``.

    Expects ``parsed_input`` keys:

    * ``material_designation`` (str, required) -- material to evaluate
    * ``gas_service`` (str, optional) -- 'oxygen' or 'hydrogen'
    * ``pressure_value`` (float, optional) -- operating pressure in psi
    * ``temperature_value`` (float, optional) -- operating temperature
    * ``standard_ref`` (str, optional) -- standard reference (e.g. NASA-STD-6016C)
    * ``raw_query`` (str, optional) -- original natural-language question

    Note: The compliance conductor requires substantial configuration
    (EnvironmentPolicy, MPR index, etc.) that may not be available in all
    deployments. This adapter degrades gracefully when the conductor is
    unavailable.
    """

    engine_id: str = "gpcm"
    engine_version: str = __version__
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Run GPCM compliance analysis and return a normalised envelope."""
        if not _ensure_gpcm_imports():
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "The GPCM compliance module (NASA-STD-6016C analysis) is not "
                    "available in this deployment. The compliance conductor requires "
                    "configured environment policies and MPR index data.\n\n"
                    "For compliance questions, please use the dedicated MIRA Compliance "
                    "module or contact your M&P engineer."
                ),
                domain_payload={
                    "engine_available": False,
                    "reason": "Compliance conductor not importable",
                },
            )

        from mira.compliance.conductor import ComplianceConductor
        from mira.compliance.models.policy import EnvironmentPolicy

        material = (parsed_input.get("material_designation") or "").strip()
        if not material:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "Compliance analysis requires a material designation. "
                    "Which material would you like to check for NASA-STD-6016C compliance? "
                    "For example: 'Is 316L compliant for GOX service at 3000 psi?'"
                ),
                missing_inputs=["material_designation"],
            )

        gas_service = parsed_input.get("gas_service")
        pressure_psi = parsed_input.get("pressure_value")

        # Build environment context for the conductor
        environment_name = "oxygen" if gas_service == "oxygen" else (
            "hydrogen" if gas_service == "hydrogen" else None
        )

        try:
            conductor = ComplianceConductor()

            # Build the analysis request
            analysis_input = {
                "material_name": material,
                "environment": environment_name,
                "pressure_psi": pressure_psi,
                "temperature_value": parsed_input.get("temperature_value"),
                "standard_ref": parsed_input.get("standard_ref"),
                "query": parsed_input.get("raw_query", ""),
            }

            result = await self._run_sync(conductor.analyze, analysis_input)

        except AttributeError:
            # ComplianceConductor.analyze may not exist in all versions
            LOGGER.warning("ComplianceConductor.analyze not available -- using stub response")
            return self._build_stub_response(material, gas_service, pressure_psi)
        except Exception as exc:
            LOGGER.error("GPCM compliance analysis raised: %s", exc, exc_info=True)
            return self.wrap_error(exc=exc)

        return self._adapt_result(result, material, gas_service)

    # ------------------------------------------------------------------
    # Stub response for when conductor exists but analyze() is not wired
    # ------------------------------------------------------------------

    def _build_stub_response(
        self,
        material: str,
        gas_service: str | None,
        pressure_psi: float | None,
    ) -> EngineEnvelope:
        """Return a structured INSUFFICIENT_DATA response with guidance."""
        env_label = gas_service or "unspecified environment"
        pressure_label = f" at {pressure_psi:g} psi" if pressure_psi else ""

        lines = [
            f"**GPCM Compliance Check -- Pending Full Analysis**",
            "",
            f"Material: {material}",
            f"Environment: {env_label}{pressure_label}",
            "",
            "The NASA-STD-6016C compliance conductor is available but requires "
            "full environment policy configuration for automated analysis. ",
            "",
            "**Recommended next steps:**",
            "- Use the dedicated MIRA Compliance module for full MPR-level analysis",
            "- Run OCA (oxygen) or H2 (hydrogen) assessments individually first",
            "- Contact your M&P engineer for manual compliance determination",
        ]

        standard_ref = "NASA-STD-6016C"
        return self.wrap_envelope(
            status=Status.INSUFFICIENT_DATA,
            response_text="\n".join(lines),
            authority_basis=[standard_ref],
            citations=[standard_ref],
            missing_inputs=["environment_policy_configuration"],
            recommended_actions=[
                "Run individual engine assessments (OCA, H2) for material compatibility",
                "Use dedicated Compliance module for full MPR analysis",
            ],
            domain_payload={
                "material": material,
                "gas_service": gas_service,
                "pressure_psi": pressure_psi,
                "analysis_status": "pending_configuration",
            },
        )

    # ------------------------------------------------------------------
    # Full result adaptation
    # ------------------------------------------------------------------

    def _adapt_result(
        self,
        result: Any,  # ComplianceAnalysisResult
        material: str,
        gas_service: str | None,
    ) -> EngineEnvelope:
        """Map a ComplianceAnalysisResult to an EngineEnvelope."""
        # Determine overall status from the result
        try:
            overall_status = str(result.overall_status)
        except AttributeError:
            overall_status = "INSUFFICIENT_DATA"

        status = _map_compliance_status(overall_status)

        # Build response text
        lines = [
            f"**GPCM Compliance Analysis -- {overall_status}**",
            "",
            f"Material: {material}",
        ]
        if gas_service:
            lines.append(f"Environment: {gas_service}")

        # Extract determinations
        try:
            determinations = result.determinations or []
            for det in determinations:
                lines.append(f"- MPR {det.mpr_id}: {det.status} -- {det.rationale}")
        except AttributeError:
            pass

        # Extract gaps
        try:
            gaps = result.gaps or []
            if gaps:
                lines.append("")
                lines.append("**Gaps identified:**")
                for gap in gaps:
                    lines.append(f"- {gap.trigger}: {gap.detail}")
        except AttributeError:
            pass

        response_text = "\n".join(lines)

        # Build evidence from determinations
        evidence: list[dict[str, Any]] = []
        try:
            for det in (result.determinations or []):
                evidence.append({
                    "source_id": det.mpr_id,
                    "status": str(det.status),
                    "summary": det.rationale,
                })
        except AttributeError:
            pass

        return self.wrap_envelope(
            status=status,
            response_text=response_text,
            authority_basis=["NASA-STD-6016C"],
            citations=["NASA-STD-6016C"],
            evidence=evidence,
            domain_payload={
                "material": material,
                "gas_service": gas_service,
                "overall_status": overall_status,
            },
        )

    @staticmethod
    async def _run_sync(func, *args, **kwargs):
        """Run a synchronous function in the default executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
