#!/usr/bin/env python3
"""API routes for fracture-control assessment."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from mira.fracture.engine import (
    evaluate_fracture_assessment,
    get_authority_manifest,
    get_fcr_payload,
    screen_material,
    search_materials,
)
from mira.fracture.models import (
    FractureAssessmentRequest,
    FractureAssessmentResponse,
    FractureAuthorityManifest,
    FractureMaterialScreenRequest,
    FractureMaterialSearchResult,
)


router = APIRouter(prefix="/fracture")


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "fracture"}


@router.post("/classify", response_model=FractureAssessmentResponse)
async def classify(request: FractureAssessmentRequest) -> FractureAssessmentResponse:
    try:
        return evaluate_fracture_assessment(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal fracture engine error") from exc


@router.get("/fcrs")
async def fcrs() -> dict:
    return get_fcr_payload()


@router.post("/materials/screen")
async def material_screen(request: FractureMaterialScreenRequest) -> dict:
    try:
        return screen_material(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal fracture materials error") from exc


@router.get("/materials/search", response_model=list[FractureMaterialSearchResult])
async def material_search(q: str = Query(..., min_length=1)) -> list[FractureMaterialSearchResult]:
    return search_materials(q)


@router.get("/authority", response_model=FractureAuthorityManifest)
async def authority() -> FractureAuthorityManifest:
    return get_authority_manifest()
