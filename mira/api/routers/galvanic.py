#!/usr/bin/env python3
"""API routes for galvanic corrosion assessment."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from mira.galvanic.engine import evaluate_galvanic_assessment, get_series_payload, list_environments, search_materials
from mira.galvanic.models import (
    EnvironmentDescriptor,
    GalvanicAssessmentRequest,
    GalvanicAssessmentResponse,
    MaterialSearchResult,
)


router = APIRouter(prefix="/galvanic")


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "galvanic"}


@router.post("/evaluate", response_model=GalvanicAssessmentResponse)
async def evaluate(request: GalvanicAssessmentRequest) -> GalvanicAssessmentResponse:
    try:
        return evaluate_galvanic_assessment(request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal galvanic engine error") from exc


@router.get("/series")
async def series() -> dict:
    return get_series_payload()


@router.get("/materials/search", response_model=list[MaterialSearchResult])
async def material_search(q: str = Query(..., min_length=1)) -> list[MaterialSearchResult]:
    return search_materials(q)


@router.get("/environments", response_model=list[EnvironmentDescriptor])
async def environments() -> list[EnvironmentDescriptor]:
    return list_environments()
