#!/usr/bin/env python3
"""
Module: O2 Router
Purpose: Oxygen (O2) compatibility API endpoints

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True

This router exposes O2 compatibility evaluation endpoints for:
1. Direct material compatibility assessment (via O2 Knowledge Twin)
2. Search within O2 Body of Knowledge (BOK)
3. Integration with MUA generation for non-A rated materials
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.models.answer import AnswerSeverity, EvidenceItem

LOGGER = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class O2CompatibilityRequest(BaseModel):
    """Request model for O2 compatibility evaluation."""

    material_key: str = Field(
        ...,
        description="Material identifier (name, spec, or MAPTIS code)",
        json_schema_extra={"examples": ["316L", "INCONEL 718", "AL 6061-T6"]},
    )
    pressure_psia: float = Field(
        default=14.7,
        description="Operating pressure in PSIA",
        ge=0,
    )
    temperature_f: float = Field(
        default=70.0,
        description="Operating temperature in Fahrenheit",
    )
    phase: str = Field(
        default="gox",
        description="Oxygen phase: 'gox' (gaseous) or 'lox' (liquid/cryogenic)",
    )
    application_id: Optional[str] = Field(
        default=None,
        description="Optional application/component identifier for traceability",
    )

    model_config = {"extra": "forbid"}


class EvidenceItemResponse(BaseModel):
    """Evidence item in response."""

    source_id: str
    location: Optional[str] = None
    summary: str


class O2CompatibilityResponse(BaseModel):
    """Response model for O2 compatibility evaluation."""

    classification: str = Field(
        description="Compatibility classification: OK, CAUTION, PROHIBITED, or UNKNOWN",
    )
    rationale: str = Field(
        description="Explanation of the classification decision",
    )
    evidence: list[EvidenceItemResponse] = Field(
        default_factory=list,
        description="Supporting evidence from BOK, standards, and test data",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional context (environment details, etc.)",
    )
    material_key: str = Field(
        description="Input material identifier",
    )
    pressure_psia: float = Field(
        description="Evaluated pressure",
    )
    temperature_f: float = Field(
        description="Evaluated temperature",
    )
    phase: str = Field(
        description="Evaluated oxygen phase",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Evaluation timestamp",
    )

    model_config = {"extra": "forbid"}


class O2BOKSearchRequest(BaseModel):
    """Request model for O2 BOK search."""

    query: str = Field(
        ...,
        description="Natural language query for O2 BOK search",
        min_length=3,
    )
    k: int = Field(
        default=5,
        description="Number of results to return",
        ge=1,
        le=20,
    )
    use_hybrid: bool = Field(
        default=True,
        description="Use hybrid search (BM25 + semantic). If False, semantic only.",
    )

    model_config = {"extra": "forbid"}


class O2BOKSearchResult(BaseModel):
    """Single result from O2 BOK search."""

    doc_id: str
    text: str
    source: str
    section: Optional[str] = None
    relevance_score: float
    semantic_rank: Optional[int] = None
    bm25_rank: Optional[int] = None


class O2BOKSearchResponse(BaseModel):
    """Response model for O2 BOK search."""

    query: str
    results: list[O2BOKSearchResult]
    total_results: int
    search_type: str  # "hybrid" or "semantic"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"extra": "forbid"}


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Health check for O2 endpoint."""
    return {"status": "ok", "domain": "o2"}


@router.post("/evaluate", response_model=O2CompatibilityResponse)
async def evaluate_o2_compatibility(
    request: O2CompatibilityRequest,
) -> O2CompatibilityResponse:
    """
    Evaluate material compatibility with oxygen service.

    Uses the O2 Knowledge Twin to:
    1. Look up material family from MAPTIS repository
    2. Apply family-based classification rules (per NASA-STD-6016)
    3. Return classification with evidence from BOK and test data

    Classification values:
    - OK: Material is approved for specified O2 environment
    - CAUTION: Material is conditionally approved with restrictions
    - PROHIBITED: Material is not permitted in specified O2 environment
    - UNKNOWN: Insufficient data for classification

    Returns O2CompatibilityResponse with classification, rationale, and evidence.
    """
    try:
        # Import O2 engine
        from mira.o2.models import O2CompatibilityRequest as O2Request, OxygenPhase
        from mira.o2.engine import evaluate_o2_compatibility as _evaluate

        # Convert temperature to Kelvin
        temp_k = (request.temperature_f - 32) * 5 / 9 + 273.15

        # Parse phase
        phase = OxygenPhase.LIQUID if request.phase.lower() == "lox" else OxygenPhase.GAS

        # Build internal request
        internal_request = O2Request(
            question=f"Is {request.material_key} compatible with oxygen?",
            material_key=request.material_key,
            pressure_psia=request.pressure_psia,
            temperature_k=temp_k,
            phase=phase,
            application_id=request.application_id,
        )

        # Call O2 Knowledge Twin
        LOGGER.info(f"[O2 API] Evaluating: {request.material_key} at {request.pressure_psia} psia, {request.temperature_f}°F, {request.phase}")
        result = await asyncio.to_thread(_evaluate, internal_request)

        # Convert evidence items
        evidence_items = [
            EvidenceItemResponse(
                source_id=e.source_id,
                location=e.location if hasattr(e, "location") else None,
                summary=e.summary,
            )
            for e in result.evidence
        ]

        return O2CompatibilityResponse(
            classification=result.classification.value.upper(),
            rationale=result.rationale,
            evidence=evidence_items,
            notes=result.notes,
            material_key=request.material_key,
            pressure_psia=request.pressure_psia,
            temperature_f=request.temperature_f,
            phase=request.phase,
        )

    except ImportError as exc:
        LOGGER.error(f"[O2 API] Import error: {exc}")
        raise HTTPException(
            status_code=503,
            detail="O2 Knowledge Twin not available",
        ) from exc
    except Exception as exc:
        LOGGER.error(f"[O2 API] Evaluation error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"O2 evaluation error: {str(exc)}",
        ) from exc


@router.post("/search", response_model=O2BOKSearchResponse)
async def search_o2_bok(request: O2BOKSearchRequest) -> O2BOKSearchResponse:
    """
    Search the O2 Body of Knowledge (BOK).

    Performs hybrid search (BM25 keyword + semantic) against NASA standards
    and guidance documents including:
    - NASA-STD-6016 (Materials & Processes)
    - NASA-STD-6001B (Flammability requirements)
    - JSC-27301F (Materials Usage Agreement)
    - KSC-KTI-5210C (Oxygen Compatibility)
    - NASA/TM-2007-213740 (O2 Compatibility Guide)

    Returns ranked results with text excerpts and source citations.
    """
    try:
        from mira.o2.engine import get_o2_engine

        # Get O2 engine (singleton pattern)
        engine = await asyncio.to_thread(get_o2_engine)

        if not engine.o2_bok_index:
            raise HTTPException(
                status_code=503,
                detail=(
                    "O2 BOK index not loaded. Ensure the dedicated O2 assets are packaged at "
                    "mira/databases/o2_bok."
                ),
            )

        # Perform search
        LOGGER.info(f"[O2 API] BOK search: '{request.query}', k={request.k}, hybrid={request.use_hybrid}")
        results = await asyncio.to_thread(
            engine.search_o2_bok,
            query=request.query,
            k=request.k,
            use_hybrid=request.use_hybrid,
        )

        # Convert to response format
        search_results = [
            O2BOKSearchResult(
                doc_id=r.get("doc_id", ""),
                text=r.get("text", "")[:2000],  # Truncate for API response
                source=r.get("source", "Unknown"),
                section=r.get("section"),
                relevance_score=r.get("relevance_score", 0.0),
                semantic_rank=r.get("semantic_rank"),
                bm25_rank=r.get("bm25_rank"),
            )
            for r in results
        ]

        return O2BOKSearchResponse(
            query=request.query,
            results=search_results,
            total_results=len(search_results),
            search_type="hybrid" if request.use_hybrid else "semantic",
        )

    except ImportError as exc:
        LOGGER.error(f"[O2 API] Import error: {exc}")
        raise HTTPException(
            status_code=503,
            detail="O2 engine not available",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[O2 API] Search error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"O2 BOK search error: {str(exc)}",
        ) from exc


@router.get("/families")
async def get_o2_material_families() -> dict[str, Any]:
    """
    Get O2 compatibility classification by material family.

    Returns the family-based rules from NASA-STD-6016 that govern
    which materials are approved, restricted, or prohibited for O2 service.

    This is useful for understanding why a material received a particular
    classification without running a full evaluation.
    """
    try:
        from mira.maptis.repository import (
            O2_PROHIBITED_FAMILIES,
            O2_RESTRICTED_FAMILIES,
            get_o2_family_rule,
            MaterialFamily,
        )

        prohibited = []
        for family in O2_PROHIBITED_FAMILIES:
            rule = get_o2_family_rule(family)
            prohibited.append({
                "family": family.value,
                "reason": rule.get("reason", ""),
                "bok_ref": rule.get("bok_ref", ""),
            })

        restricted = []
        for family in O2_RESTRICTED_FAMILIES:
            rule = get_o2_family_rule(family)
            restricted.append({
                "family": family.value,
                "reason": rule.get("reason", ""),
                "bok_ref": rule.get("bok_ref", ""),
            })

        approved = []
        approved_families = [
            MaterialFamily.NICKEL_ALLOY,
            MaterialFamily.COPPER,
            MaterialFamily.AUSTENITIC_STEEL,
        ]
        for family in approved_families:
            rule = get_o2_family_rule(family)
            approved.append({
                "family": family.value,
                "reason": rule.get("reason", ""),
                "bok_ref": rule.get("bok_ref", ""),
            })

        return {
            "prohibited_families": prohibited,
            "restricted_families": restricted,
            "approved_families": approved,
            "note": "Classification is based on material family from MAPTIS repository, not string matching.",
        }

    except ImportError as exc:
        LOGGER.error(f"[O2 API] Import error: {exc}")
        raise HTTPException(
            status_code=503,
            detail="MAPTIS repository not available",
        ) from exc
    except Exception as exc:
        LOGGER.error(f"[O2 API] Families error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching O2 family rules: {str(exc)}",
        ) from exc


__safety_critical__ = True  # NASA SWE-032 compliance
