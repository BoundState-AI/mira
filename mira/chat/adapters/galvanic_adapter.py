"""
Module: MIRA Chat -- Galvanic Corrosion Adapter
Purpose: Adapter bridging the Galvanic Corrosion Assessment engine into the
         MIRA Chat unified envelope per BS-SPEC-MIRA-CHAT-001-REV2.

Calls ``mira.galvanic.engine.evaluate_galvanic_assessment`` with a
``GalvanicAssessmentRequest`` and maps the ``GalvanicAssessmentResponse``
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
# Lazy imports -- avoid hard failures if galvanic engine is not available
# ---------------------------------------------------------------------------

_GALVANIC_AVAILABLE: Optional[bool] = None


def _ensure_galvanic_imports() -> bool:
    """Lazy-import the galvanic engine and request/response models."""
    global _GALVANIC_AVAILABLE
    if _GALVANIC_AVAILABLE is not None:
        return _GALVANIC_AVAILABLE
    try:
        from mira.galvanic.engine import evaluate_galvanic_assessment  # noqa: F401
        from mira.galvanic.models import (  # noqa: F401
            CoupleContext,
            GalvanicAssessmentRequest,
            GalvanicAssessmentResponse,
        )

        _GALVANIC_AVAILABLE = True
    except Exception as exc:
        LOGGER.warning("Galvanic engine not available: %s", exc)
        _GALVANIC_AVAILABLE = False
    return _GALVANIC_AVAILABLE


# ---------------------------------------------------------------------------
# Severity -> Chat Status mapping
# ---------------------------------------------------------------------------

_SEVERITY_TO_STATUS = {
    "COMPATIBLE": Status.PASS,
    "CAUTION": Status.CONDITIONAL_PASS,
    "INCOMPATIBLE": Status.FAIL,
}


def _map_severity(severity: str) -> Status:
    """Map a galvanic severity string to a Chat Status."""
    return _SEVERITY_TO_STATUS.get(severity, Status.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Environment key normalization
# ---------------------------------------------------------------------------

_ENVIRONMENT_ALIAS_MAP: dict[str, str] = {
    "seawater": "seawater_proxy",
    "salt fog": "seawater_proxy",
    "salt_fog": "seawater_proxy",
    "coastal": "coastal_condensing",
    "industrial": "industrial_atm",
    "rural": "rural_atm",
    "indoor": "dry_indoor",
    "dry": "dry_indoor",
    "crew": "crew_condensing",
    "interior": "crew_condensing",
    "cryogenic": "cryogenic_ops",
    "cryo": "cryogenic_ops",
    "space": "space_vacuum",
    "vacuum": "space_vacuum",
}

_VALID_ENVIRONMENTS = {
    "seawater_proxy",
    "coastal_condensing",
    "industrial_atm",
    "rural_atm",
    "crew_condensing",
    "dry_indoor",
    "cryogenic_ops",
    "space_vacuum",
}


def _normalize_environment(raw: str | None) -> str:
    """Map user-facing environment text to a valid EnvironmentKey."""
    if not raw:
        return "seawater_proxy"  # Conservative default
    normalized = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _VALID_ENVIRONMENTS:
        return normalized
    return _ENVIRONMENT_ALIAS_MAP.get(normalized, "seawater_proxy")


# ---------------------------------------------------------------------------
# Two-material extraction helpers
# ---------------------------------------------------------------------------

def _extract_material_pair(parsed_input: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract material A and material B from the parsed input.

    The query interpreter sets ``material_designation`` (first material) and
    the full text may contain a second material in ``second_material`` or
    embedded in the raw query with "and", "vs", "versus", "against" delimiters.
    """
    material_a = (parsed_input.get("material_designation") or "").strip() or None
    material_b = (parsed_input.get("second_material") or "").strip() or None

    # If we have material_a but not material_b, try to split from raw query
    if material_a and not material_b:
        import re
        raw = parsed_input.get("raw_query", "")
        # Patterns like "7075 vs 316L", "7075 and 316L", "7075 against 316L"
        split_match = re.search(
            r"(\S+)\s+(?:vs\.?|versus|against|and|with|to|coupled\s+(?:to|with))\s+(\S+)",
            raw,
            re.IGNORECASE,
        )
        if split_match:
            candidate_a = split_match.group(1).strip(".,;:!?()")
            candidate_b = split_match.group(2).strip(".,;:!?()")
            # Only override if both look like material designations
            if len(candidate_a) >= 2 and len(candidate_b) >= 2:
                material_a = candidate_a
                material_b = candidate_b

    return material_a, material_b


# ---------------------------------------------------------------------------
# Galvanic Adapter
# ---------------------------------------------------------------------------


class GalvanicAdapter(EngineAdapter):
    """
    Adapter for the Galvanic Corrosion Assessment engine.

    Expects ``parsed_input`` keys:

    * ``material_designation`` (str, required) -- first material (Material A)
    * ``second_material`` (str, optional) -- second material (Material B)
    * ``raw_query`` (str, optional) -- raw query for pair extraction fallback
    * ``environment`` (str, optional) -- service environment
    * ``application_type`` (str, optional) -- application classification
    * ``joint_type`` (str, optional) -- joint geometry
    * ``electrical_contact`` (str, optional) -- YES / NO / UNKNOWN
    * ``surface_condition_a`` (str, optional)
    * ``surface_condition_b`` (str, optional)
    * ``cathode_to_anode_area_ratio`` (float, optional)
    * ``electrolyte_pooling`` (bool, optional)
    """

    engine_id: str = "galvanic"
    engine_version: str = __version__
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Evaluate galvanic corrosion risk and return a normalised envelope."""
        if not _ensure_galvanic_imports():
            return self.wrap_error(
                exc=RuntimeError("Galvanic corrosion engine is not available on this instance."),
            )

        from mira.galvanic.engine import evaluate_galvanic_assessment
        from mira.galvanic.models import CoupleContext, GalvanicAssessmentRequest

        material_a, material_b = _extract_material_pair(parsed_input)

        if not material_a:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "Galvanic corrosion assessment requires two materials. "
                    "Which materials are you evaluating? "
                    "For example: 'Is 7075-T6 compatible with 316L in seawater?'"
                ),
                missing_inputs=["material_a", "material_b"],
            )

        if not material_b:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    f"I have {material_a} as the first material. "
                    "What is the second material in this dissimilar couple? "
                    "For example: '7075-T6 vs 316L' or '7075 and titanium'"
                ),
                missing_inputs=["material_b"],
            )

        # Build the request
        environment = _normalize_environment(parsed_input.get("environment"))
        application_type = (
            parsed_input.get("application_type", "FLIGHT_HARDWARE") or "FLIGHT_HARDWARE"
        )

        couple_context = CoupleContext(
            electrical_contact=parsed_input.get("electrical_contact", "YES"),
            electrolyte_pooling=bool(parsed_input.get("electrolyte_pooling", False)),
            joint_type=parsed_input.get("joint_type", "GENERAL"),
            cathode_to_anode_area_ratio=parsed_input.get("cathode_to_anode_area_ratio"),
        )

        try:
            request = GalvanicAssessmentRequest(
                material_a=material_a,
                material_b=material_b,
                environment=environment,
                application_type=application_type,
                surface_condition_a=parsed_input.get("surface_condition_a"),
                surface_condition_b=parsed_input.get("surface_condition_b"),
                couple_context=couple_context,
            )
        except Exception as exc:
            LOGGER.error("Failed to build GalvanicAssessmentRequest: %s", exc)
            return self.wrap_error(exc=exc)

        try:
            response = await self._run_sync(evaluate_galvanic_assessment, request)
        except ValueError as exc:
            # Material not found in the galvanic series
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=str(exc),
                missing_inputs=[str(exc)],
            )
        except Exception as exc:
            LOGGER.error("evaluate_galvanic_assessment raised: %s", exc, exc_info=True)
            return self.wrap_error(exc=exc)

        # Store couple context for follow-ups
        session_context["galvanic_material_a"] = material_a
        session_context["galvanic_material_b"] = material_b
        session_context["galvanic_environment"] = environment

        return self._adapt_response(response, request)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapt_response(
        self,
        response: Any,  # GalvanicAssessmentResponse
        request: Any,   # GalvanicAssessmentRequest
    ) -> EngineEnvelope:
        """Map GalvanicAssessmentResponse fields to an EngineEnvelope."""
        status = _map_severity(response.severity)

        # Build human-readable response
        mat_a = response.material_a
        mat_b = response.material_b

        lines: list[str] = [
            f"**Galvanic Assessment -- {response.severity}**",
            "",
            f"Material A: {mat_a.canonical_name} ({mat_a.family}, {mat_a.chosen_state})",
            f"  Potential: {mat_a.representative_potential_mv_sce:.0f} mV SCE",
            f"Material B: {mat_b.canonical_name} ({mat_b.family}, {mat_b.chosen_state})",
            f"  Potential: {mat_b.representative_potential_mv_sce:.0f} mV SCE",
            "",
            f"Raw delta: {response.raw_delta_mv:.0f} mV",
            f"Effective delta: {response.effective_delta_mv:.0f} mV "
            f"(env modifier {response.environment_modifier:.2f})",
            f"Decision basis: {response.decision_basis}",
            f"Anode (corrodes first): {response.anode}",
            f"Cathode: {response.cathode}",
        ]

        if response.warnings:
            lines.append("")
            lines.append("**Warnings:**")
            for w in response.warnings:
                lines.append(f"- {w}")

        if response.mitigations:
            lines.append("")
            lines.append("**Recommended mitigations:**")
            for m in response.mitigations:
                lines.append(f"- [{m.mitigation_id}] {m.name}: {m.description}")

        response_text = "\n".join(lines)

        # Authority basis
        authority_basis = [
            "NASA-STD-6012A",
            "MIL-STD-889D",
        ]

        # Evidence
        evidence: list[dict[str, Any]] = [
            {
                "source_id": "galvanic_series",
                "location": f"version {response.source_manifest_version}",
                "summary": f"{mat_a.canonical_name} vs {mat_b.canonical_name}: "
                           f"delta={response.raw_delta_mv:.0f} mV, "
                           f"effective={response.effective_delta_mv:.0f} mV",
            }
        ]

        # Recommended actions
        actions: list[str] = []
        if response.severity == "INCOMPATIBLE":
            actions.append(
                "Consider alternative material combinations or implement full galvanic isolation."
            )
        elif response.severity == "CAUTION":
            actions.append(
                "Review mitigation options; may proceed with appropriate protective measures."
            )

        for m in response.mitigations:
            actions.append(f"{m.name}: {m.description}")

        # Domain payload
        domain_payload: dict[str, Any] = {
            "severity": response.severity,
            "raw_delta_mv": response.raw_delta_mv,
            "effective_delta_mv": response.effective_delta_mv,
            "decision_basis": response.decision_basis,
            "environment": response.environment,
            "environment_modifier": response.environment_modifier,
            "anode": response.anode,
            "cathode": response.cathode,
            "material_a": response.material_a.model_dump(mode="json"),
            "material_b": response.material_b.model_dump(mode="json"),
            "mitigations": [m.model_dump(mode="json") for m in response.mitigations],
            "source_manifest_version": response.source_manifest_version,
        }

        return self.wrap_envelope(
            status=status,
            response_text=response_text,
            authority_basis=authority_basis,
            citations=authority_basis,
            evidence=evidence,
            assumptions=[
                f"Environment: {response.environment} (modifier {response.environment_modifier})",
                f"Application: {response.application_type}",
                response.screening_disclaimer,
            ],
            recommended_actions=actions,
            domain_payload=domain_payload,
        )

    @staticmethod
    async def _run_sync(func, *args, **kwargs):
        """Run a synchronous engine function in the default executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
