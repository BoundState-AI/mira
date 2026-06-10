"""
Module: MIRA Chat -- AM Knowledge Twin Adapter
Purpose: Bridge the Powder AM Knowledge Twin (BoundState-AI/powder, consumed
         as an installed package dependency -- never via path imports) into
         the MIRA Chat EngineEnvelope contract.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True

Notes:
- powder runs its own server-side demo AccessContext and a PUBLIC-only
  content store (deny-by-default enforced store-side); chat input never
  selects an access boundary.
- AM_DEMO_PROGRAM=1 attaches powder's seeded synthetic GRCop-42 registry
  (assessed mode, labeled NON_AUTHORITATIVE). Default: checklist mode.
- No confidence score: removed everywhere by owner decision (2026-06-09);
  verdict_basis carries the named caps instead.
"""

from __future__ import annotations

__version__ = "2.0.0"
__safety_critical__ = True

import logging
import os
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
    except ImportError as exc:
        LOGGER.warning("AM Knowledge Twin (powder) is not installed: %s", exc)
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
    "exempt": "Exempt",
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

# Chat phrasing -> powder AMProcess enum values.
_PROCESS_ALIASES = {
    "l-pbf": "laser_powder_bed_fusion",
    "lpbf": "laser_powder_bed_fusion",
    "l_pbf": "laser_powder_bed_fusion",
    "laser_powder_bed_fusion": "laser_powder_bed_fusion",
    "eb-pbf": "electron_beam_powder_bed_fusion",
    "eb_pbf": "electron_beam_powder_bed_fusion",
    "electron_beam_powder_bed_fusion": "electron_beam_powder_bed_fusion",
    "ded": "directed_energy_deposition",
    "directed_energy_deposition": "directed_energy_deposition",
    "binder_jet": "binder_jet",
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
        """Build a powder AMRequest from confirmed parsed input and run it."""
        missing = self._missing_inputs(parsed_input)
        safety_confirmed = bool(parsed_input.get("safety_critical_confirmed"))
        if missing or not safety_confirmed:
            missing_inputs = missing[:]
            if not safety_confirmed:
                missing_inputs.append("safety_critical_confirmed")
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "AM evaluation requires confirmed safety-critical "
                    "classification inputs before the engine can run."
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
                exc=RuntimeError(
                    "AM Knowledge Twin is not available: the 'powder' package "
                    "is not installed on this instance."
                ),
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
                mission_critical=parsed_input.get("mission_critical"),
                class_c_criteria_confirmed=parsed_input.get(
                    "class_c_criteria_confirmed"
                ),
                safety_critical_confirmed=safety_confirmed,
            )

            request_kwargs: dict[str, Any] = {
                "part_description": (
                    parsed_input.get("part_description")
                    or parsed_input.get("query")
                    or "Synthetic GRCop-42 LPBF combustion liner"
                ),
                "material_designation": parsed_input.get(
                    "material_designation",
                    "GRCop-42",
                ),
                "classification": classification,
                "safety_critical_confirmed": safety_confirmed,
            }
            am_process = self._parse_process(parsed_input.get("am_process"))
            if am_process is not None:
                request_kwargs["am_process"] = am_process
            material_type = self._parse_material_type(
                parsed_input.get("material_type")
            )
            if material_type is not None:
                request_kwargs["material_type"] = material_type
            program = self._demo_program_if_enabled()
            if program is not None:
                request_kwargs["program_context"] = program

            request = AMRequest(**request_kwargs)
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
                "source_id": "powder.am",
                "location": "classification",
                "summary": package.classification.reason,
            },
            {
                "source_id": "powder.am",
                "location": "coverage",
                "summary": package.applicability.coverage_statement,
            },
        ]

        recommended_actions = [
            "Review all QMP/MPS/document gaps with the responsible M&P engineer.",
            "Use controlled standards only inside a cleared, licensed Product "
            "Track boundary.",
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
                "verdict_basis": list(package.verdict_basis),
                "classification_verdict": package.classification.verdict,
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

    def _parse_process(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        from powder.am import AMProcess

        normalized = _PROCESS_ALIASES.get(str(value).strip().lower(), value)
        return AMProcess(normalized)

    def _parse_material_type(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        from powder.am import MaterialType

        return MaterialType(str(value).strip().lower())

    def _demo_program_if_enabled(self) -> Any:
        """Attach powder's seeded synthetic GRCop-42 registry when the demo
        flag is set (assessed mode, labeled NON_AUTHORITATIVE). Default: off."""
        if os.environ.get("AM_DEMO_PROGRAM", "").strip() not in ("1", "true", "True"):
            return None
        from powder.am.synthetic_demo import demo_program_context

        return demo_program_context()

    def _format_package(self, package: Any) -> str:
        if package.overall_verdict.startswith("BLOCKED"):
            # A gate block is not a classification failure; render it as
            # what it is instead of echoing CANNOT_VALIDATE.
            return "\n".join(
                [
                    f"AM Qualification Package - {package.overall_verdict}",
                    *package.verdict_basis,
                    "",
                    package.classification.reason,
                ]
            )
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
            for item in package.test_matrix.items[:10]
        )
        if len(package.test_matrix.items) > 10:
            lines.append(
                f"- {len(package.test_matrix.items) - 10} additional matrix "
                "items omitted from chat view"
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
        if verdict.startswith("BLOCKED"):
            return Status.INSUFFICIENT_DATA
        mapping = {
            "PASS": Status.PASS,
            "CONDITIONAL_PASS_WITH_GAPS": Status.CONDITIONAL_PASS,
            "INSUFFICIENT_DATA": Status.INSUFFICIENT_DATA,
            "CANNOT_VALIDATE": Status.INSUFFICIENT_DATA,
        }
        return mapping.get(verdict, Status.ERROR)
