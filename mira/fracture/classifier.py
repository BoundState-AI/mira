"""Deterministic fracture classification and applicability routing."""

from __future__ import annotations

from mira.fracture.models import FractureAssessmentRequest


NFC_SPECIFIC_HARDWARE_TYPES = {
    "FASTENER",
    "SHATTERABLE",
    "ROTATING_HARDWARE",
    "SEALED_CONTAINER",
    "TOOLS_TETHERS",
    "BATTERY",
}

FC_SPECIFIC_HARDWARE_TYPES = {
    "PRESSURE_VESSEL",
    "COPV",
    "PRESSURIZED_COMPONENT",
    "HABITABLE_STRUCTURE",
    "PRESSURIZED_STRUCTURE",
    "ROTATING_HARDWARE",
    "FASTENER",
    "SHATTERABLE",
    "TOOLS_TETHERS",
    "BATTERY",
}

ALWAYS_FC_HARDWARE_TYPES = {
    "PRESSURE_VESSEL",
    "COPV",
    "PRESSURIZED_COMPONENT",
    "HABITABLE_STRUCTURE",
    "PRESSURIZED_STRUCTURE",
}


def classify_request(request: FractureAssessmentRequest) -> dict[str, object]:
    warnings: list[str] = []
    unresolved_inputs: list[str] = []

    if request.mission_class != "HUMAN_RATED":
        warnings.append(
            "NASA-STD-5019A is mandatory for human-rated spaceflight hardware. "
            "For this mission class, MIRA is providing best-practice fracture guidance."
        )

    if request.structural_role != "NON_STRUCTURAL":
        if request.hazard_consequence == "UNKNOWN":
            unresolved_inputs.append("hazard_consequence")
        if request.load_path_type == "UNKNOWN":
            unresolved_inputs.append("load_path_type")

    if unresolved_inputs:
        return {
            "classification": "INDETERMINATE",
            "baseline_key": "INDETERMINATE",
            "confidence_state": "INDETERMINATE",
            "warnings": warnings,
            "unresolved_inputs": unresolved_inputs,
            "conservative_fallback": "Treat as FC pending review",
        }

    if request.specific_hardware_type in ALWAYS_FC_HARDWARE_TYPES:
        return {
            "classification": "FC",
            "baseline_key": "FC_SPECIFIC_HARDWARE",
            "confidence_state": "CONFIDENT",
            "warnings": warnings,
            "unresolved_inputs": [],
            "conservative_fallback": None,
        }

    if (
        request.structural_role == "NON_STRUCTURAL"
        and request.hazard_consequence in {"NEGLIGIBLE", "MARGINAL"}
    ):
        return {
            "classification": "EXEMPT",
            "baseline_key": "EXEMPT",
            "confidence_state": "CONFIDENT",
            "warnings": warnings,
            "unresolved_inputs": [],
            "conservative_fallback": None,
        }

    nfc_candidate = (
        request.hazard_consequence != "CATASTROPHIC"
        and request.load_path_type != "SINGLE"
    )

    if nfc_candidate:
        if request.material_system in {"COMPOSITE", "BONDED"}:
            baseline_key = (
                "NFC_COMPOSITE_BONDED_SPECIFIC"
                if request.specific_hardware_type in NFC_SPECIFIC_HARDWARE_TYPES
                else "NFC_COMPOSITE_BONDED_GENERAL"
            )
            classification = "NFC_COMPOSITE_BONDED"
        else:
            baseline_key = (
                "NFC_METALLIC_SPECIFIC"
                if request.specific_hardware_type in NFC_SPECIFIC_HARDWARE_TYPES
                else "NFC_METALLIC_GENERAL"
            )
            classification = "NFC_METALLIC"

        if request.material_system in {"CERAMIC", "OTHER"}:
            warnings.append(
                "Non-metallic/non-composite material system selected. "
                "Verify the NFC path with RFCB review if the standard hardware paths do not fit cleanly."
            )

        return {
            "classification": classification,
            "baseline_key": baseline_key,
            "confidence_state": "CONFIDENT",
            "warnings": warnings,
            "unresolved_inputs": [],
            "conservative_fallback": None,
        }

    classification = "FC"
    if request.optional_approach_requested:
        baseline_key = "FC_OPTIONAL_APPROACH"
    elif request.specific_hardware_type in FC_SPECIFIC_HARDWARE_TYPES:
        baseline_key = "FC_SPECIFIC_HARDWARE"
    elif request.material_system in {"COMPOSITE", "BONDED"}:
        baseline_key = "FC_COMPOSITE_BONDED_GENERAL"
    elif request.material_system in {"CERAMIC", "OTHER"}:
        baseline_key = "FC_OPTIONAL_APPROACH"
        warnings.append(
            "Material system is outside the standard metallic/composite general paths. "
            "Route through an RFCB-approved optional approach unless a specific hardware path exists."
        )
    else:
        baseline_key = "FC_METALLIC_GENERAL"

    return {
        "classification": classification,
        "baseline_key": baseline_key,
        "confidence_state": "CONFIDENT",
        "warnings": warnings,
        "unresolved_inputs": [],
        "conservative_fallback": None,
    }
