"""
Module: MIRA Chat -- AM Knowledge Twin Adapter (PR-E)
Purpose: Bridge the Powder AM Knowledge Twin Demo Track into the MIRA Chat
         EngineEnvelope contract.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
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

_AM_AVAILABLE: Optional[bool] = None


def _ensure_am_imports() -> bool:
    """Lazy-import the Powder AM engine and models."""
    global _AM_AVAILABLE
    if _AM_AVAILABLE is not None:
        return _AM_AVAILABLE

    try:
        from powder.am import (  # noqa: F401
            AMKnowledgeTwinEngine,
            AMPartClass,
            AMRequest,
            ClassificationInput,
            ConsequenceTier,
            HazardFlag,
        )

        _AM_AVAILABLE = True
    except Exception as exc:
        LOGGER.warning("AM Knowledge Twin is not available: %s", exc)
        _AM_AVAILABLE = False
    return _AM_AVAILABLE


_PART_CLASS_ALIASES = {
    "a": "Class A",
    "class a": "Class A",
    "class_a": "Class A",
    "b": "Class B",
    "class b": "Class B",
    "class_b": "Class B",
    "c": "Class C",
    "class c": "Class C",
    "class_c": "Class C",
}

_CONSEQUENCE_ALIASES = {
    "catastrophic": "catastrophic",
    "critical": "critical",
    "major": "major",
    "minor": "minor",
    "negligible": "negligible",
}

_HAZARD_ALIASES = {
    "fracture_critical": "fracture_critical",
    "fracture critical": "fracture_critical",
    "pressure_vessel": "pressure_vessel",
    "pressure vessel": "pressure_vessel",
    "single_point_failure": "single_point_failure",
    "single point failure": "single_point_failure",
    "crewed_flight": "crewed_flight",
    "crewed flight": "crewed_flight",
    "crew": "crewed_flight",
    "in_space_am": "in_space_am",
    "in space am": "in_space_am",
    "lox": "lox_compatible",
    "lox_compatible": "lox_compatible",
    "hydrogen": "hydrogen_compatible",
    "hydrogen_compatible": "hydrogen_compatible",
}


class AMAdapter(EngineAdapter):
    """Adapter for the AM Knowledge Twin Demo Track."""

    engine_id: str = "am_knowledge_twin"
    engine_version: str = __version__
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Build an AMRequest from confirmed parsed input and run the engine."""
        missing = self._missing_inputs(parsed_input)
        safety_confirmed = bool(parsed_input.get("safety_critical_confirmed"))
        if missing or not safety_confirmed:
            missing_inputs = missing[:]
            if not safety_confirmed:
                missing_inputs.append("safety_critical_confirmed")
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "AM evaluation requires confirmed safety-critical classification "
                    "inputs before the engine can run."
                ),
                missing_inputs=missing_inputs,
                authority_basis=["NASA-STD-6030", "NASA-STD-6033"],
                domain_payload={
                    "engine_verdict": "INSUFFICIENT_DATA",
                    "required_confirmation": True,
                },
            )

        if not _ensure_am_imports():
            return self.wrap_error(
                exc=RuntimeError("AM Knowledge Twin is not available on this instance."),
            )

        from powder.am import AMKnowledgeTwinEngine, AMRequest, ClassificationInput

        try:
            classification = ClassificationInput(
                classification_framework=parsed_input.get(
                    "classification_framework",
                    "NASA-STD-6030",
                ),
                intended_class=self._parse_part_class(parsed_input["intended_class"]),
                consequence_of_failure=self._parse_consequence(
                    parsed_input["consequence_of_failure"]
                ),
                hazard_context=self._parse_hazards(parsed_input.get("hazard_context", [])),
                fluid_service=parsed_input.get("fluid_service"),
                redundancy=parsed_input.get("redundancy"),
                safety_critical_confirmed=safety_confirmed,
            )

            request = AMRequest(
                part_description=(
                    parsed_input.get("part_description")
                    or parsed_input.get("query")
                    or "Synthetic GRCop-42 LPBF combustion liner"
                ),
                material_designation=parsed_input.get(
                    "material_designation",
                    "GRCop-42",
                ),
                classification=classification,
                safety_critical_confirmed=safety_confirmed,
            )

            package = AMKnowledgeTwinEngine().evaluate_am_package(request)
        except Exception as exc:
            LOGGER.error("AM Knowledge Twin evaluation failed: %s", exc, exc_info=True)
            return self.wrap_error(exc=exc)

        return self._adapt_package(package)

    def _adapt_package(self, package: Any) -> EngineEnvelope:
        status = self._map_verdict_to_status(package.overall_verdict)
        response_text = self._format_package(package)
        authority_basis = ["NASA-STD-6030", "NASA-STD-6033"]

        evidence = [
            {
                "source_id": "powder.am.demo",
                "location": "classification",
                "summary": package.classification.reason,
            },
            {
                "source_id": "powder.am.demo",
                "location": "coverage",
                "summary": package.applicability.coverage_statement,
            },
        ]

        recommended_actions = [
            "Review all QMP/MPS/document gaps with the responsible M&P engineer.",
            "Use controlled standards only inside a cleared, licensed Product Track boundary.",
        ]
        if package.test_matrix.enrichment_notice:
            recommended_actions.append(package.test_matrix.enrichment_notice)

        return self.wrap_envelope(
            status=status,
            response_text=response_text,
            authority_basis=authority_basis,
            citations=authority_basis,
            evidence=evidence,
            recommended_actions=recommended_actions,
            domain_payload={
                "engine_verdict": package.overall_verdict,
                "classification_verdict": package.classification.verdict,
                "confidence": package.confidence,
                "gap_counts": {
                    "qmp": len(package.gap_analysis.qmp_gaps),
                    "mps": len(package.gap_analysis.mps_gaps),
                    "documents": len(package.gap_analysis.document_gaps),
                },
                "am_package": package.model_dump(mode="json"),
            },
        )

    def _missing_inputs(self, parsed_input: dict[str, Any]) -> list[str]:
        required = [
            "intended_class",
            "consequence_of_failure",
            "hazard_context",
        ]
        return [key for key in required if parsed_input.get(key) in (None, "", [])]

    def _parse_part_class(self, value: Any) -> Any:
        from powder.am import AMPartClass

        normalized = _PART_CLASS_ALIASES.get(str(value).strip().lower(), value)
        return AMPartClass(normalized)

    def _parse_consequence(self, value: Any) -> Any:
        from powder.am import ConsequenceTier

        normalized = _CONSEQUENCE_ALIASES.get(str(value).strip().lower(), value)
        return ConsequenceTier(normalized)

    def _parse_hazards(self, values: Any) -> list[Any]:
        from powder.am import HazardFlag

        if isinstance(values, str):
            values = [part.strip() for part in values.split(",") if part.strip()]
        return [
            HazardFlag(_HAZARD_ALIASES.get(str(value).strip().lower(), value))
            for value in values
        ]

    def _format_package(self, package: Any) -> str:
        lines = [
            f"AM Qualification Package - {package.overall_verdict}",
            f"Mode: {package.mode}",
            f"Authority: {package.authority}",
            f"Coverage: {package.coverage}",
            f"Evidence Depth: {package.evidence_depth}",
            "",
            "Classification",
            f"{package.classification.verdict}: {package.classification.reason}",
            "",
            "Applicability",
            package.applicability.coverage_statement,
            f"Applicable requirements: {len(package.applicability.applicable_requirements)}",
            "",
            "Key Gaps",
        ]

        gaps = (
            package.gap_analysis.qmp_gaps
            + package.gap_analysis.mps_gaps
            + package.gap_analysis.document_gaps
        )
        lines.extend(f"- {gap}" for gap in gaps[:8])
        if len(gaps) > 8:
            lines.append(f"- {len(gaps) - 8} additional gaps omitted from chat view")

        lines.extend(["", "Baseline Test Matrix"])
        lines.extend(
            f"- {item.test_id}: {item.description} ({item.evidence_depth.value})"
            for item in package.test_matrix.items
        )

        if package.test_matrix.enrichment_notice:
            lines.extend(["", f"Enrichment Notice: {package.test_matrix.enrichment_notice}"])

        lines.extend(
            [
                "",
                "Demo Boundary",
                (
                    "Synthetic Demo Track output only. Controlled standards are inert "
                    "name-only placeholders; no controlled clauses, excerpts, mappings, "
                    "or customer data were used."
                ),
            ]
        )
        return "\n".join(lines)

    def _map_verdict_to_status(self, verdict: str) -> Status:
        mapping = {
            "PASS": Status.PASS,
            "CONDITIONAL_PASS_WITH_GAPS": Status.CONDITIONAL_PASS,
            "REQUIRES_ADDITIONAL_EVIDENCE": Status.CONDITIONAL_PASS,
            "BLOCKED": Status.INSUFFICIENT_DATA,
            "CANNOT_VALIDATE": Status.INSUFFICIENT_DATA,
        }
        return mapping.get(verdict, Status.ERROR)
