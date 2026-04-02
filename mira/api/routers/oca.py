#!/usr/bin/env python3
"""API routes for the OCA workbench."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from mira.oca import (
    create_case,
    export_case_artifacts,
    get_authority_manifest,
    get_case_decision,
    get_case_evidence,
    get_case_lineage,
    get_case_mechanisms,
    get_case_precheck,
    get_case_requirements,
)
from mira.oca.models import (
    CreateOcaCaseRequest,
    CreateOcaCaseResponse,
    OcaAuthorityManifest,
    OcaDecisionResponse,
    OcaEvidenceResponse,
    OcaExportResponse,
    OcaLineageResponse,
    OcaMechanismsResponse,
    OcaPrecheckResponse,
    OcaRequirementsResponse,
)
from mira.oca.reference_pack import get_material_catalog


router = APIRouter()


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "oca"}


@router.get("/materials/suggest")
async def suggest_materials(
    q: str = Query("", min_length=0, max_length=200),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict[str, str]]:
    """Fuzzy material name search against the OCA reference pack."""
    materials = get_material_catalog()
    if not q.strip():
        return [_material_suggestion(item) for item in materials[:limit]]

    needle = re.sub(r"[^a-z0-9]", "", q.lower())
    scored: list[tuple[int, dict]] = []
    for material in materials:
        name = str(material.get("material_name", ""))
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        if needle in normalized:
            score = 0 if normalized.startswith(needle) else 1
            scored.append((score, material))

    scored.sort(key=lambda item: item[0])
    return [_material_suggestion(item) for _, item in scored[:limit]]


def _material_suggestion(material: dict) -> dict[str, str]:
    return {
        "material_name": str(material.get("material_name", "")),
        "family": str(material.get("family", "unknown")),
        "flammability_rating": str(material.get("flammability_rating", "U")),
        "source_ref": str(material.get("source_ref", "")),
    }


@router.get("/authority", response_model=OcaAuthorityManifest)
async def authority() -> OcaAuthorityManifest:
    return get_authority_manifest()


@router.post("/cases", response_model=CreateOcaCaseResponse)
async def cases(request: CreateOcaCaseRequest) -> CreateOcaCaseResponse:
    return create_case(request)


@router.post("/cases/{case_id}/precheck", response_model=OcaPrecheckResponse)
async def precheck(case_id: str) -> OcaPrecheckResponse:
    try:
        return get_case_precheck(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCA case not found") from exc


@router.post("/cases/{case_id}/evidence", response_model=OcaEvidenceResponse)
async def evidence(case_id: str) -> OcaEvidenceResponse:
    try:
        return get_case_evidence(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCA case not found") from exc


@router.post("/cases/{case_id}/mechanisms", response_model=OcaMechanismsResponse)
async def mechanisms(case_id: str) -> OcaMechanismsResponse:
    try:
        return get_case_mechanisms(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCA case not found") from exc


@router.post("/cases/{case_id}/decision", response_model=OcaDecisionResponse)
async def decision(case_id: str) -> OcaDecisionResponse:
    try:
        return get_case_decision(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCA case not found") from exc


@router.post("/cases/{case_id}/export", response_model=OcaExportResponse)
async def export(case_id: str) -> OcaExportResponse:
    try:
        return export_case_artifacts(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCA case not found") from exc


@router.get("/cases/{case_id}/requirements", response_model=OcaRequirementsResponse)
async def requirements(case_id: str) -> OcaRequirementsResponse:
    try:
        return get_case_requirements(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCA case not found") from exc


@router.get("/cases/{case_id}/lineage", response_model=OcaLineageResponse)
async def lineage(case_id: str) -> OcaLineageResponse:
    try:
        return get_case_lineage(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCA case not found") from exc
