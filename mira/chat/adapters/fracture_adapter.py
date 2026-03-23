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
from pathlib import Path
from typing import Any, Optional

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode
from ._guidance_utils import format_guidance_lines, guidance_entry_source, lookup_guidance_entries, search_guidance

LOGGER = logging.getLogger(__name__)
_GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "fracture" / "data" / "guidance.json"
_AUTHORITY = ["Fracture guidance pack", "NASA-STD-5019A w/Change 4"]

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


def _module_context(session_context: dict[str, Any]) -> dict[str, Any]:
    context = session_context.get("module_context") or {}
    return context if isinstance(context, dict) else {}


def _classify_query(text: str) -> str:
    query = (text or "").lower()
    if any(
        phrase in query
        for phrase in (
            "what's a fracture control plan",
            "what is a fracture control plan",
            "what's fracture control",
            "what is fracture control",
            "define fracture control",
            "define fracture control plan",
            "explain fracture control",
            "what does this module do",
            "what does this page do",
        )
    ):
        return "definition"
    if (
        any(token in query for token in ("start", "begin", "set up", "setup", "kick off"))
        and "fracture" in query
    ):
        return "getting_started"
    if any(token in query for token in ("what should", "do next", "next step", "what do i do next")):
        return "next_step"
    if any(
        token in query
        for token in (
            "mission class",
            "hazard consequence",
            "load path",
            "pressure boundary",
            "material system",
            "hardware type",
            "fracture-critical",
            "damage tolerance",
            "safe-life",
            "safe life",
            "rfcb",
            "fcr",
            "kic",
            "nde",
        )
    ) and any(token in query for token in ("what", "why", "explain", "define", "when", "how")):
        return "guidance"
    return "assessment"


def _guidance_hits(query_kind: str, raw_query: str) -> list[dict[str, Any]]:
    query = raw_query.lower()
    keys: list[str] = []
    sections: list[str] = []

    if query_kind == "definition":
        keys = ["fracture_critical_definition", "fcr_requirements", "mission_class"]
    elif query_kind == "getting_started":
        keys = [
            "part_name",
            "mission_class",
            "hazard_consequence",
            "load_path_type",
            "material_system",
            "specific_hardware_type",
        ]
    elif query_kind == "next_step":
        keys = ["mission_class", "hazard_consequence", "load_path_type", "material_name", "fcr_requirements"]
    else:
        sections = ["inputs", "concepts", "classifications", "findings"]
        key_map = {
            "mission class": "mission_class",
            "hazard consequence": "hazard_consequence",
            "load path": "load_path_type",
            "pressure boundary": "pressure_boundary",
            "material system": "material_system",
            "hardware type": "specific_hardware_type",
            "material name": "material_name",
            "kic": "kic_fty_ratio",
            "safe-life": "safe_life_vs_damage_tolerance",
            "safe life": "safe_life_vs_damage_tolerance",
            "damage tolerance": "safe_life_vs_damage_tolerance",
            "nde": "nde_methods",
            "crack size": "critical_crack_size",
            "da/dn": "da_dn_curves",
            "rfcb": "rfcb_review",
            "fcr": "fcr_requirements",
            "fracture-critical": "fracture_critical_definition",
        }
        for token, key in key_map.items():
            if token in query:
                keys.append(key)

    hits = lookup_guidance_entries(_GUIDANCE_PATH, keys)
    if hits:
        return hits[:3]
    return search_guidance(_GUIDANCE_PATH, raw_query, limit=3, sections=sections)


def _guidance_recommended_actions(query_kind: str, ctx: dict[str, Any]) -> list[str]:
    if query_kind == "definition":
        return [
            "If you want the current hardware screened, ask what the current fracture path is.",
            "If you want to start the workflow, provide the part context and run the classifier from the page.",
        ]

    actions: list[str] = []
    if not str(ctx.get("part_name") or "").strip():
        actions.append("Identify the part or drawing number first.")
    if not str(ctx.get("mission_class") or "").strip():
        actions.append("Set the mission class before you trust the fracture path.")
    if not str(ctx.get("hazard_consequence") or "").strip():
        actions.append("Choose the hazard consequence so the classifier can tell whether a single crack is critical.")
    if not str(ctx.get("load_path_type") or "").strip():
        actions.append("Set the load-path type so the classifier knows whether a backup path exists.")
    if not str(ctx.get("material_name") or "").strip():
        actions.append("Enter the material so the engine can apply FCR 22 and material-specific fracture watches.")
    if not actions:
        actions.append("Run the classifier with the current page inputs, then review the applicable FCRs and required documents.")
    return actions[:4]


def _definition_response() -> tuple[list[str], list[dict[str, Any]], list[str]]:
    hits = _guidance_hits("definition", "what is fracture control")
    lines = [
        "A fracture control plan is the program-level package that shows how hardware with crack-like flaws will be classified, analyzed, inspected, documented, and accepted for flight.",
        "In this module, the workflow starts by classifying the part as exempt, non-fracture-critical, fracture-critical, or indeterminate, then maps the applicable FCR requirements and material findings that the plan must cover.",
    ]
    return lines, hits, _guidance_recommended_actions("definition", {})


def _getting_started_response(ctx: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    hits = _guidance_hits("getting_started", "how do i start a fracture control plan")
    lines = [
        "You start a fracture control plan by grounding the hardware context before you ask for analysis:",
        "1. Identify the part or drawing number.",
        "2. Set the mission class, hazard consequence, and load-path type.",
        "3. Define the material system, hardware type, and whether the part is a pressure boundary.",
        "4. Add the material name and any special fracture-control conditions, such as proof test, process controls, AM status, or sustained-load exposure.",
        "5. Run the classifier, then use the returned classification, FCR list, required documents, and material findings to build the plan and the review package.",
    ]
    return lines, hits, _guidance_recommended_actions("getting_started", ctx)


def _guidance_lines(query_kind: str, raw_query: str, ctx: dict[str, Any], hits: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    if query_kind == "next_step":
        part_name = str(ctx.get("part_name") or "the active part").strip()
        lines.append(f"The current fracture page is centered on {part_name}.")
        lines.append("Best next steps:")
        lines.extend(f"- {action}" for action in _guidance_recommended_actions(query_kind, ctx))
    else:
        lines.append(f"Your question was: {raw_query.strip() or 'fracture guidance'}.")
    lines.extend(format_guidance_lines(hits, heading="Relevant fracture guidance:"))
    return lines


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
        raw_query = (parsed_input.get("raw_query") or "").strip()
        query_kind = _classify_query(raw_query)
        module_context = _module_context(session_context)

        if query_kind == "definition":
            response_lines, hits, recommended_actions = _definition_response()
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="\n".join(response_lines + format_guidance_lines(hits, heading="Relevant fracture guidance:")),
                authority_basis=_AUTHORITY,
                citations=[source for source in (guidance_entry_source(entry) for entry in hits) if source],
                recommended_actions=recommended_actions,
                domain_payload={"query_kind": query_kind, "guidance_only": True},
            )

        if query_kind == "getting_started":
            response_lines, hits, recommended_actions = _getting_started_response(module_context)
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="\n".join(response_lines + format_guidance_lines(hits, heading="Relevant fracture guidance:")),
                authority_basis=_AUTHORITY,
                citations=[source for source in (guidance_entry_source(entry) for entry in hits) if source],
                recommended_actions=recommended_actions,
                domain_payload={"query_kind": query_kind, "guidance_only": True},
            )

        if query_kind == "next_step" or (
            query_kind == "guidance"
            and not any(
                str(parsed_input.get(field) or "").strip()
                for field in ("part_name", "material_designation")
            )
        ):
            hits = _guidance_hits(query_kind, raw_query)
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="\n".join(_guidance_lines(query_kind, raw_query, module_context, hits)),
                authority_basis=_AUTHORITY,
                citations=[source for source in (guidance_entry_source(entry) for entry in hits) if source],
                recommended_actions=_guidance_recommended_actions(query_kind, module_context),
                domain_payload={"query_kind": query_kind, "guidance_only": True},
            )

        if not _ensure_fracture_imports():
            return self.wrap_error(
                exc=RuntimeError("Fracture assessment engine is not available on this instance."),
            )

        from mira.fracture.engine import evaluate_fracture_assessment
        from mira.fracture.models import FractureAssessmentRequest, FractureMaterialContext

        # Part name is required -- derive from material or raw query if absent
        part_name = (parsed_input.get("part_name") or module_context.get("part_name") or "").strip()
        material = (parsed_input.get("material_designation") or module_context.get("material") or "").strip()

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
            low_risk_candidate=bool(parsed_input.get("low_risk_candidate", module_context.get("low_risk_candidate", False))),
            additive_manufactured=bool(parsed_input.get("additive_manufactured", module_context.get("additive_manufactured", False))),
            kic_fty_ratio=parsed_input.get("kic_fty_ratio", module_context.get("kic_fty_ratio")),
            ftu_ksi=parsed_input.get("ftu_ksi", module_context.get("ftu_ksi")),
            short_transverse_dimension_in=parsed_input.get(
                "short_transverse_dimension_in",
                module_context.get("short_transverse_dimension_in"),
            ),
            chloride_exposure=bool(parsed_input.get("chloride_exposure", module_context.get("chloride_exposure", False))),
            sustained_load_expected=bool(parsed_input.get("sustained_load_expected", module_context.get("sustained_load_expected", False))),
            nasa_std_6016_qualified=parsed_input.get(
                "nasa_std_6016_qualified",
                module_context.get("nasa_std_6016_qualified"),
            ),
            mua_present=bool(parsed_input.get("mua_present", module_context.get("mua_present", False))),
            approved_source_data_attached=bool(
                parsed_input.get(
                    "approved_source_data_attached",
                    module_context.get("approved_source_data_attached", False),
                )
            ),
        )

        try:
            request = FractureAssessmentRequest(
                part_name=part_name,
                mission_class=parsed_input.get("mission_class") or module_context.get("mission_class") or _DEFAULT_MISSION_CLASS,
                hazard_consequence=parsed_input.get("hazard_consequence") or module_context.get("hazard_consequence") or "UNKNOWN",
                load_path_type=parsed_input.get("load_path_type") or module_context.get("load_path_type") or "UNKNOWN",
                pressure_boundary=bool(parsed_input.get("pressure_boundary", module_context.get("pressure_boundary", False))),
                lifecycle_phase=parsed_input.get("lifecycle_phase") or module_context.get("lifecycle_phase") or "NEW_BUILD",
                structural_role=parsed_input.get("structural_role") or module_context.get("structural_role") or _DEFAULT_STRUCTURAL_ROLE,
                material_system=parsed_input.get("material_system") or module_context.get("material_system") or _DEFAULT_MATERIAL_SYSTEM,
                specific_hardware_type=parsed_input.get("specific_hardware_type") or module_context.get("specific_hardware_type") or "GENERAL",
                material_name=material or None,
                optional_approach_requested=bool(parsed_input.get("optional_approach_requested", module_context.get("optional_approach_requested", False))),
                proof_test_used=bool(parsed_input.get("proof_test_used", module_context.get("proof_test_used", False))),
                process_controls_used=bool(parsed_input.get("process_controls_used", module_context.get("process_controls_used", False))),
                detected_flaw_accepted_for_flight=bool(parsed_input.get("detected_flaw_accepted_for_flight", module_context.get("detected_flaw_accepted_for_flight", False))),
                corrosion_iccp_recommended=bool(parsed_input.get("corrosion_iccp_recommended", module_context.get("corrosion_iccp_recommended", False))),
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
