"""Phase 1 materials findings for fracture assessments."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from mira.fracture.models import FractureAssessmentRequest, FractureMaterialScreenRequest


DATA_DIR = Path(__file__).resolve().parent / "data"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


@lru_cache(maxsize=1)
def _material_reference() -> list[dict[str, Any]]:
    with (DATA_DIR / "material_reference.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["entries"]


def search_materials(query: str) -> list[dict[str, Any]]:
    normalized = _normalize(query)
    matches: list[dict[str, Any]] = []
    for entry in _material_reference():
        terms = [entry["canonical_name"], *entry.get("aliases", [])]
        if any(normalized in _normalize(term) for term in terms):
            matches.append(entry)
    return matches[:10]


def resolve_material(query: str | None) -> dict[str, Any] | None:
    if not query:
        return None
    normalized = _normalize(query)
    exact = None
    partials: list[dict[str, Any]] = []
    for entry in _material_reference():
        terms = [entry["canonical_name"], *entry.get("aliases", [])]
        if any(normalized == _normalize(term) for term in terms):
            exact = entry
            break
        if any(normalized in _normalize(term) or _normalize(term) in normalized for term in terms):
            partials.append(entry)
    return exact or (partials[0] if partials else None)


def _data_fields(material_context: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for key in [
        "kic_fty_ratio",
        "ftu_ksi",
        "short_transverse_dimension_in",
        "nasa_std_6016_qualified",
        "mua_present",
        "approved_source_data_attached",
    ]:
        value = material_context.get(key)
        if value is not None and value is not False:
            fields.append(key)
    return fields


def _screen_material_common(
    *,
    material_name: str | None,
    material_system: str,
    baseline_key: str,
    specific_hardware_type: str,
    material_context: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    resolved = resolve_material(material_name)
    findings: list[dict[str, Any]] = []
    data_provided = _data_fields(material_context)

    applies_fcr22 = baseline_key.startswith("FC_") or baseline_key.startswith("NFC_COMPOSITE_BONDED")
    low_risk_requested = bool(material_context.get("low_risk_candidate"))

    if not material_name:
        if applies_fcr22 or low_risk_requested:
            findings.append(
                {
                    "finding_id": "material_identity_missing",
                    "status": "DATA_GAP",
                    "title": "Material not identified",
                    "detail": "A material selection is required before MIRA can evaluate FCR 22 obligations or NFC low-risk criteria.",
                    "governing_fcrs": [22] if applies_fcr22 else [8],
                    "source_clauses": ["8.3", "6.2.5"],
                    "data_provided": data_provided,
                }
            )
        return None, findings

    if applies_fcr22:
        findings.append(
            {
                "finding_id": "fcr22_scope",
                "status": "INFO",
                "title": "FCR 22 applies to this path",
                "detail": (
                    "Section 8.3 applies to fracture-critical parts and NFC composite/bonded parts. "
                    "Use this module to surface required material evidence, not to replace RFCB judgment."
                ),
                "governing_fcrs": [22],
                "source_clauses": ["8.3"],
                "data_provided": data_provided,
            }
        )

        if material_context.get("approved_source_data_attached"):
            findings.append(
                {
                    "finding_id": "approved_source_data_attached",
                    "status": "PASS",
                    "title": "Approved source data indicated",
                    "detail": "Representative source data is marked as attached. This supports section 8.3.d-e expectations for condition-specific material evidence.",
                    "governing_fcrs": [22],
                    "source_clauses": ["8.3.d", "8.3.e"],
                    "data_provided": data_provided,
                }
            )
        else:
            findings.append(
                {
                    "finding_id": "approved_source_data_missing",
                    "status": "CAUTION",
                    "title": "Representative source data not confirmed",
                    "detail": "FCR 22 expects representative material condition, orientation, thickness treatment, and NASA-approved source data or conservative bounds.",
                    "governing_fcrs": [22],
                    "source_clauses": ["8.3.d", "8.3.e"],
                    "data_provided": data_provided,
                }
            )

        qualified = material_context.get("nasa_std_6016_qualified")
        if qualified is False:
            findings.append(
                {
                    "finding_id": "mua_required",
                    "status": "PASS" if material_context.get("mua_present") else "FAIL",
                    "title": "MUA requirement",
                    "detail": (
                        "Material is marked as not qualified to NASA-STD-6016. "
                        + ("MUA flagged as present." if material_context.get("mua_present") else "Approved MUA is required and must be included in the FCSR.")
                    ),
                    "governing_fcrs": [22],
                    "source_clauses": ["8.3.f", "8.3.g"],
                    "data_provided": data_provided,
                }
            )
        elif qualified is None:
            findings.append(
                {
                    "finding_id": "qualification_status_unknown",
                    "status": "DATA_GAP",
                    "title": "NASA-STD-6016 qualification status unknown",
                    "detail": "MIRA cannot tell whether FCR 22 section 8.3.f-g creates an MUA requirement until qualification status is known.",
                    "governing_fcrs": [22],
                    "source_clauses": ["8.3.f", "8.3.g"],
                    "data_provided": data_provided,
                }
            )

        if material_context.get("chloride_exposure") or material_context.get("sustained_load_expected"):
            findings.append(
                {
                    "finding_id": "operating_conditions_present",
                    "status": "CAUTION",
                    "title": "Operating-condition effects must be accounted for",
                    "detail": "Exposure flags are present. FCR 22 requires operating-condition effects on damage tolerance properties to be included in the assessment package.",
                    "governing_fcrs": [22],
                    "source_clauses": ["8.3.c"],
                    "data_provided": data_provided,
                }
            )

    if low_risk_requested:
        findings.append(
            {
                "finding_id": "low_risk_path_scope",
                "status": "INFO" if baseline_key == "NFC_METALLIC_GENERAL" and material_system == "METALLIC" else "CAUTION",
                "title": "NFC low-risk path scope",
                "detail": (
                    "The KIc/Fty threshold and the related low-risk criteria belong to FCR 8 section 6.2.5 for metallic NFC low-risk parts."
                    if baseline_key == "NFC_METALLIC_GENERAL" and material_system == "METALLIC"
                    else "NFC low-risk screening is only the right model for metallic parts on the FCR 8 general NFC path."
                ),
                "governing_fcrs": [8],
                "source_clauses": ["6.2.5", "6.2.5.a(2)"],
                "data_provided": data_provided,
            }
        )

        ratio = material_context.get("kic_fty_ratio")
        if ratio is None:
            findings.append(
                {
                    "finding_id": "kic_fty_missing",
                    "status": "DATA_GAP",
                    "title": "KIc/Fty ratio not provided",
                    "detail": "MIRA cannot evaluate the 0.33 sqrt(in) metallic low-risk criterion without a KIc/Fty value or an extracted MMPDS record.",
                    "governing_fcrs": [8],
                    "source_clauses": ["6.2.5.a(2)"],
                    "data_provided": data_provided,
                }
            )
        else:
            findings.append(
                {
                    "finding_id": "kic_fty_ratio_check",
                    "status": "PASS" if ratio >= 0.33 else "FAIL",
                    "title": "KIc/Fty low-risk criterion",
                    "detail": (
                        f"Provided KIc/Fty ratio = {ratio:.3f}. "
                        + ("Meets" if ratio >= 0.33 else "Does not meet")
                        + " the 0.33 sqrt(in) criterion for metallic NFC low-risk."
                    ),
                    "governing_fcrs": [8],
                    "source_clauses": ["6.2.5.a(2)"],
                    "data_provided": data_provided,
                }
            )

        if resolved and resolved["family"] == "aluminum":
            st_dimension = material_context.get("short_transverse_dimension_in")
            if st_dimension is None:
                findings.append(
                    {
                        "finding_id": "short_transverse_dimension_missing",
                        "status": "DATA_GAP",
                        "title": "Short-transverse dimension not provided",
                        "detail": "Aluminum low-risk screening requires the short-transverse dimension check when that loading orientation is relevant.",
                        "governing_fcrs": [8],
                        "source_clauses": ["6.2.5.a(3)"],
                        "data_provided": data_provided,
                    }
                )
            elif st_dimension > 3.0:
                findings.append(
                    {
                        "finding_id": "short_transverse_dimension_fail",
                        "status": "FAIL",
                        "title": "Short-transverse aluminum restriction",
                        "detail": "Aluminum parts loaded in the short-transverse direction above 3 inches do not qualify for the metallic NFC low-risk path.",
                        "governing_fcrs": [8],
                        "source_clauses": ["6.2.5.a(3)"],
                        "data_provided": data_provided,
                    }
                )

        if material_context.get("chloride_exposure") or material_context.get("sustained_load_expected"):
            findings.append(
                {
                    "finding_id": "susceptibility_evidence_required",
                    "status": "CAUTION",
                    "title": "Susceptibility evidence required for low-risk claim",
                    "detail": "Metallic NFC low-risk requires no sensitivity to EAC, SLC, or stress-corrosion cracking. This build does not infer that from alloy name alone.",
                    "governing_fcrs": [8],
                    "source_clauses": ["6.2.5.a(2)"],
                    "data_provided": data_provided,
                }
            )

    if resolved and resolved["family"] == "titanium" and material_context.get("sustained_load_expected"):
        findings.append(
            {
                "finding_id": "titanium_slc_watch",
                "status": "INFO",
                "title": "Titanium sustained-load cracking watch",
                "detail": "Titanium alloys require explicit sustained-load-cracking review when sustained stress is expected.",
                "governing_fcrs": [22],
                "source_clauses": ["3.2 definition of SLC", "7.3.2.f"],
                "data_provided": data_provided,
            }
        )

    if (
        resolved
        and resolved["family"] == "steel"
        and specific_hardware_type == "FASTENER"
        and material_context.get("ftu_ksi") is not None
        and material_context["ftu_ksi"] > 180
    ):
        findings.append(
            {
                "finding_id": "steel_fastener_low_toughness_watch",
                "status": "CAUTION",
                "title": "High-strength steel bolt toughness watch",
                "detail": "Steel bolts above 180 ksi with unknown KIc should be treated as low-fracture-toughness until property evidence is established.",
                "governing_fcrs": [8],
                "source_clauses": ["3.2 definition of low-fracture-toughness"],
                "data_provided": data_provided,
            }
        )

    return resolved, findings


def screen_material_for_assessment(request: FractureAssessmentRequest, baseline_key: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    return _screen_material_common(
        material_name=request.material_name,
        material_system=request.material_system,
        baseline_key=baseline_key,
        specific_hardware_type=request.specific_hardware_type,
        material_context=request.material_context.model_dump(mode="python"),
    )


def screen_material_request(request: FractureMaterialScreenRequest) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    baseline_key = "INDETERMINATE"
    if request.classification == "NFC_METALLIC":
        baseline_key = "NFC_METALLIC_GENERAL"
    elif request.classification == "NFC_COMPOSITE_BONDED":
        baseline_key = "NFC_COMPOSITE_BONDED_GENERAL"
    elif request.classification == "FC":
        baseline_key = "FC_METALLIC_GENERAL" if request.material_system == "METALLIC" else "FC_COMPOSITE_BONDED_GENERAL"

    return _screen_material_common(
        material_name=request.material_name,
        material_system=request.material_system,
        baseline_key=baseline_key,
        specific_hardware_type=request.specific_hardware_type,
        material_context=request.material_context.model_dump(mode="python"),
    )

