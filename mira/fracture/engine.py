"""Authority-backed fracture assessment engine."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from mira.fracture.classifier import classify_request
from mira.fracture.materials_checker import (
    resolve_material,
    screen_material_for_assessment,
    screen_material_request,
    search_materials as search_material_reference,
)
from mira.fracture.models import (
    FractureAssessmentRequest,
    FractureAssessmentResponse,
    FractureAuthorityManifest,
    FractureCitation,
    FractureMaterialFinding,
    FractureMaterialScreenRequest,
    FractureMaterialSearchResult,
    FractureRequirementSummary,
    FractureResolvedMaterial,
)


DATA_DIR = Path(__file__).resolve().parent / "data"
MANIFEST_VERSION = "2026.03.09-phase1"
SOURCE_DOC = "NASA-STD-5019A w/Change 4"
SOURCE_PATH = "/mnt/d/BoundState/BoundState_other/BoundState/docs/NASA-STD-5019A.pdf"
CROSS_MODULE_ALERT = (
    "CrossModuleAlert: corrosion indicates ICCP consideration while this part is fracture-critical. "
    "This is a BoundState product alert, not an FCR."
)


def _load_json(name: str) -> dict[str, Any]:
    with (DATA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _fcr_payload() -> dict[str, Any]:
    return _load_json("fcr_definitions.json")


@lru_cache(maxsize=1)
def _fcr_seed_payload() -> dict[str, Any]:
    return _load_json("fcr_definitions_seed_verified_5019A.json")


@lru_cache(maxsize=1)
def _applicability_payload() -> dict[str, Any]:
    return _load_json("fcr_applicability.json")


@lru_cache(maxsize=1)
def _citation_index() -> dict[int, dict[str, Any]]:
    return {entry["id"]: entry for entry in _fcr_seed_payload()["fcrs"]}


@lru_cache(maxsize=1)
def _definition_index() -> dict[int, dict[str, Any]]:
    return {entry["fcr"]: entry for entry in _fcr_payload()["fcrs"]}


def _citation_for_fcr(fcr: int) -> FractureCitation:
    seed_entry = _citation_index()[fcr]
    definition_entry = _definition_index()[fcr]
    return FractureCitation(
        fcr=fcr,
        title=definition_entry["title"],
        section=definition_entry["section"],
        source_document=SOURCE_DOC,
        source_path=SOURCE_PATH,
        source_pages=list(seed_entry.get("source_pages", [])),
        summary=seed_entry["summary"],
    )


def _requirement_summary(fcr: int) -> FractureRequirementSummary:
    entry = _definition_index()[fcr]
    return FractureRequirementSummary(
        fcr=fcr,
        category=str(entry["category"]),
        title=str(entry["title"]),
        section=str(entry["section"]),
        description=str(entry["description"]),
        phase_1_relevant=bool(entry.get("phase_1_relevant", True)),
        notes=entry.get("notes"),
        citation=_citation_for_fcr(fcr),
    )


def _resolve_baseline_fcrs(baseline_key: str) -> list[int]:
    baselines = _applicability_payload()["classification_baselines"]
    return list(baselines.get(baseline_key, {}).get("required_fcrs", []))


def _conservative_fallback_baseline(request: FractureAssessmentRequest) -> str:
    if request.material_system in {"COMPOSITE", "BONDED"}:
        return "FC_COMPOSITE_BONDED_GENERAL"
    return "FC_METALLIC_GENERAL"


def _conditional_fcrs(request: FractureAssessmentRequest, baseline_key: str) -> list[int]:
    extras: list[int] = []
    if baseline_key == "FC_SPECIFIC_HARDWARE":
        if request.material_system == "METALLIC":
            extras.append(16)
        elif request.material_system in {"COMPOSITE", "BONDED"}:
            extras.append(17)
    elif baseline_key == "FC_OPTIONAL_APPROACH":
        if request.material_system == "METALLIC":
            extras.append(16)
        elif request.material_system in {"COMPOSITE", "BONDED"}:
            extras.append(17)

    if baseline_key.startswith("FC_"):
        if request.proof_test_used:
            extras.append(18)
        if request.process_controls_used:
            extras.append(19)
        if request.detected_flaw_accepted_for_flight:
            extras.append(20)
    return extras


def _required_documents(request: FractureAssessmentRequest, applicable_fcrs: list[int]) -> list[str]:
    documents: list[str] = []
    if request.mission_class == "HUMAN_RATED":
        documents.append("Fracture Control Plan (FCP)")
    if 23 in applicable_fcrs:
        documents.append("Engineering drawing notes for fracture-control identification")
    if 24 in applicable_fcrs or request.mission_class == "HUMAN_RATED":
        documents.append("Fracture Control Summary Report (FCSR)")
    if 25 in applicable_fcrs:
        documents.append("Verification evidence package")
    return list(dict.fromkeys(documents))


def _required_actions(requirements: list[FractureRequirementSummary]) -> list[str]:
    actions: list[str] = []
    for requirement in requirements:
        actions.append(f"Meet FCR {requirement.fcr}: {requirement.title} ({requirement.section})")
    return actions


def _convert_material_findings(findings: list[dict[str, Any]]) -> list[FractureMaterialFinding]:
    converted: list[FractureMaterialFinding] = []
    for item in findings:
        citations = [_citation_for_fcr(fcr) for fcr in item.get("governing_fcrs", []) if fcr in _definition_index()]
        converted.append(
            FractureMaterialFinding(
                finding_id=item["finding_id"],
                status=item["status"],
                title=item["title"],
                detail=item["detail"],
                governing_fcrs=item.get("governing_fcrs", []),
                source_clauses=item.get("source_clauses", []),
                data_provided=item.get("data_provided", []),
                citations=citations,
            )
        )
    return converted


def _resolved_material_response(query: str | None, resolved: dict[str, Any] | None) -> FractureResolvedMaterial | None:
    if not query or not resolved:
        return None
    return FractureResolvedMaterial(
        query=query,
        canonical_name=resolved["canonical_name"],
        material_system=resolved["material_system"],
        family=resolved["family"],
        aliases=list(resolved.get("aliases", [])),
    )


def evaluate_fracture_assessment(request: FractureAssessmentRequest) -> FractureAssessmentResponse:
    classification_packet = classify_request(request)
    baseline_key = str(classification_packet["baseline_key"])
    effective_baseline_key = baseline_key

    if classification_packet["classification"] == "INDETERMINATE" and classification_packet.get("conservative_fallback"):
        effective_baseline_key = _conservative_fallback_baseline(request)

    applicable_fcrs = sorted(
        set(
            _resolve_baseline_fcrs(effective_baseline_key)
            + _conditional_fcrs(request, effective_baseline_key)
        )
    )

    requirements = [_requirement_summary(fcr) for fcr in applicable_fcrs]
    resolved_material, material_findings_raw = screen_material_for_assessment(request, effective_baseline_key)
    material_findings = _convert_material_findings(material_findings_raw)

    warnings = list(classification_packet["warnings"])
    if request.lifecycle_phase == "REFLIGHT":
        warnings.append(
            "Reflight hardware selected. Review prior flight history, inspection evidence, and traceability before reuse."
        )
    if request.corrosion_iccp_recommended and classification_packet["classification"] == "FC":
        warnings.append(CROSS_MODULE_ALERT)

    return FractureAssessmentResponse(
        classification=classification_packet["classification"],
        baseline_key=effective_baseline_key,
        confidence_state=(
            "CONSERVATIVE_FALLBACK"
            if classification_packet["classification"] == "INDETERMINATE" and classification_packet.get("conservative_fallback")
            else classification_packet["confidence_state"]
        ),
        screening_basis=(
            "Conservative fracture-critical fallback from verified FCR authority JSON because required classification inputs remain unresolved."
            if classification_packet["classification"] == "INDETERMINATE" and classification_packet.get("conservative_fallback")
            else "Deterministic NASA-STD-5019A classification with explicit applicability mapping from verified FCR authority JSON."
        ),
        applicable_fcrs=applicable_fcrs,
        requirements=requirements,
        required_actions=_required_actions(requirements),
        required_documents=_required_documents(request, applicable_fcrs),
        resolved_material=_resolved_material_response(request.material_name, resolved_material),
        material_findings=material_findings,
        warnings=warnings,
        unresolved_inputs=list(classification_packet["unresolved_inputs"]),
        conservative_fallback=classification_packet.get("conservative_fallback"),
        citations=[_citation_for_fcr(fcr) for fcr in applicable_fcrs],
        source_manifest_version=MANIFEST_VERSION,
    )


def screen_material(request: FractureMaterialScreenRequest) -> dict[str, Any]:
    resolved, findings_raw = screen_material_request(request)
    findings = _convert_material_findings(findings_raw)
    return {
        "resolved_material": _resolved_material_response(request.material_name, resolved),
        "findings": [item.model_dump(mode="json") for item in findings],
        "source_manifest_version": MANIFEST_VERSION,
    }


def search_materials(query: str) -> list[FractureMaterialSearchResult]:
    return [
        FractureMaterialSearchResult(
            canonical_name=item["canonical_name"],
            material_system=item["material_system"],
            family=item["family"],
            aliases=item.get("aliases", []),
        )
        for item in search_material_reference(query)
    ]


def get_fcr_payload() -> dict[str, Any]:
    return _fcr_payload()


def get_authority_manifest() -> FractureAuthorityManifest:
    applicability = _applicability_payload()
    return FractureAuthorityManifest(
        version=MANIFEST_VERSION,
        total_fcrs=len(_fcr_payload()["fcrs"]),
        baseline_count=len(applicability["classification_baselines"]),
        conditional_extension_count=len(applicability["conditional_extensions"]),
        special_rule_count=len(applicability["special_rules"]),
        sources=[
            {
                "document": SOURCE_DOC,
                "path": SOURCE_PATH,
            },
            {
                "document": "FCR definitions JSON",
                "path": str(DATA_DIR / "fcr_definitions.json"),
            },
            {
                "document": "FCR applicability JSON",
                "path": str(DATA_DIR / "fcr_applicability.json"),
            },
        ],
    )
