#!/usr/bin/env python3
"""
Module: H2
Purpose: First-class API routes for hydrogen compatibility assessment.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from mira.h2 import evaluate_h2_compatibility
from mira.h2.engine import lookup_h2_conditions
from mira.h2.ft_temp import evaluate_h2_temp_compatibility
from mira.h2.dual_service import assess_dual_service, DualServiceRequest, DualServiceResponse
from mira.h2.mua_rationale import generate_h2_mua_rationale, H2MUARationaleRequest, H2MUARationaleResponse
from mira.h2.runtime_db import list_condition_aliases, verify_condition_alias
from mira.h2.condition_resolver import clear_condition_resolution_cache, normalize_condition_key
from mira.h2.models import (
    H2CompatibilityRequest,
    H2CompatibilityResponse,
    H2ConditionLookupResponse,
    H2ConditionAliasListResponse,
    H2ConditionAliasRecord,
    H2ConditionAliasVerifyRequest,
    H2ConditionAliasVerifyResponse,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/h2")

# Guidance JSON — loaded once at import time from the backend-packaged copy.
_GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "h2" / "data" / "guidance.json"
_GUIDANCE_CACHE: dict | None = None


def _no_data_runtime_enabled() -> bool:
    return os.getenv("MIRA_NO_DATA_RUNTIME", "").strip().lower() in {"1", "true", "yes"}


# ─── Health ───────────────────────────────────────────────────────────────────

@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "h2"}


# ─── Core Assessment ─────────────────────────────────────────────────────────

@router.post("/compatibility", response_model=H2CompatibilityResponse)
@router.post("/evaluate", response_model=H2CompatibilityResponse)
async def evaluate(request: H2CompatibilityRequest) -> H2CompatibilityResponse:
    """Evaluate hydrogen compatibility for a material and conditions.

    Deterministic guardrails (high-strength block, titanium hydride block)
    fire before evidence lookup.  Evidence-first assessment uses the H2
    Knowledge Twin v3 with 371 NASA/Sandia HEE test records.

    Reference Standards:
    - NSS 1740.16: NASA Safety Standard for Hydrogen
    - NASA/TM-2016-218602: Hydrogen embrittlement test data
    - SAND2012-7321: Sandia H2 materials compatibility
    """
    try:
        return evaluate_h2_compatibility(request)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal H2 engine error") from exc


@router.post("/compatibility-temp", response_model=H2CompatibilityResponse)
@router.post("/evaluate-ft", response_model=H2CompatibilityResponse)
async def evaluate_ft(request: H2CompatibilityRequest) -> H2CompatibilityResponse:
    """Evaluate hydrogen compatibility through fine-tuned model + guard architecture."""
    try:
        return evaluate_h2_temp_compatibility(request)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal H2 FT engine error") from exc


# ─── Dual Service (O2 + H2) ──────────────────────────────────────────────────

@router.post("/dual-service", response_model=DualServiceResponse)
async def dual_service(request: DualServiceRequest) -> DualServiceResponse:
    """Evaluate a material for combined O2 + H2 service (e.g., LOX/LH2 systems).

    Runs the H2 Knowledge Twin and O2 engine independently, then merges
    to worst-case verdict.  Both per-environment results are surfaced in full.

    Use case: SLS-class propulsion systems where a seal, valve body, or
    turbopump component contacts both liquid oxygen and liquid/gaseous hydrogen.
    """
    try:
        return assess_dual_service(request)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal dual-service engine error") from exc


# ─── MUA Rationale Export ─────────────────────────────────────────────────────

@router.post("/mua-rationale", response_model=H2MUARationaleResponse)
async def mua_rationale(request: H2MUARationaleRequest) -> H2MUARationaleResponse:
    """Generate NASA-STD-6016C §4.2.6.4 hydrogen embrittlement MUA rationale.

    Runs the H2 engine and renders the verdict as Form 551-ready rationale
    text suitable for the hydrogen embrittlement section of a Material Usage
    Agreement.  Includes disposition recommendation and standard citations.
    """
    try:
        return generate_h2_mua_rationale(request)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal MUA rationale error") from exc


# ─── Condition Lookup & Alias Management ──────────────────────────────────────

@router.get("/conditions", response_model=H2ConditionLookupResponse)
async def conditions(
    material_key: str = Query(..., min_length=1),
) -> H2ConditionLookupResponse:
    """Lookup known heat-treatment conditions for a material from H2 evidence."""
    try:
        return lookup_h2_conditions(material_key)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal H2 condition lookup error") from exc


@router.get("/conditions/suggest")
async def conditions_suggest(
    material_key: str = Query(..., min_length=1),
) -> dict:
    """Lightweight condition auto-suggest for UI dropdowns.

    Returns just the condition names and their HEE bands — designed for
    typeahead/select components that don't need the full lookup payload.
    """
    try:
        response = lookup_h2_conditions(material_key)
        return {
            "material": response.canonical_material or material_key,
            "conditions": [
                {
                    "label": opt.condition_name,
                    "hee_band": opt.hee_band,
                    "verdict": opt.verdict_if_selected,
                    "count": opt.evidence_count,
                }
                for opt in response.available_conditions
            ],
            "requires_selection": response.requires_clarification,
        }
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal H2 condition suggest error") from exc


@router.get("/condition-aliases", response_model=H2ConditionAliasListResponse)
async def condition_aliases(
    material_key: str | None = Query(default=None),
    unresolved_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> H2ConditionAliasListResponse:
    """List condition alias records for human review."""
    try:
        rows = list_condition_aliases(
            material_name=material_key,
            unresolved_only=unresolved_only,
            limit=limit,
        )
        aliases = [_alias_record_from_row(r) for r in rows]
        return H2ConditionAliasListResponse(
            material_key=material_key,
            unresolved_only=unresolved_only,
            count=len(aliases),
            aliases=aliases,
        )
    except Exception as exc:  # pragma: no cover
        if _no_data_runtime_enabled():
            LOGGER.warning("[H2] Condition alias review unavailable in no-data runtime: %s", exc)
            return H2ConditionAliasListResponse(
                material_key=material_key,
                unresolved_only=unresolved_only,
                count=0,
                aliases=[],
            )
        raise HTTPException(status_code=500, detail="Internal H2 condition alias listing error") from exc


@router.post("/condition-aliases/verify", response_model=H2ConditionAliasVerifyResponse)
async def condition_alias_verify(
    request: H2ConditionAliasVerifyRequest,
) -> H2ConditionAliasVerifyResponse:
    """Human-verify/override a condition alias mapping."""
    if _no_data_runtime_enabled():
        raise HTTPException(status_code=503, detail="H2 condition alias verification unavailable in no-data runtime")

    raw_for_key = request.raw_key or request.raw_text or request.display_label
    raw_key = normalize_condition_key(raw_for_key)
    if not raw_key:
        raise HTTPException(status_code=400, detail="raw_key (or raw_text/display_label) is required")
    try:
        row = verify_condition_alias(
            raw_key=raw_key,
            display_label=request.display_label,
            canonical_condition=request.canonical_condition,
            is_condition=request.is_condition,
            raw_text=request.raw_text or request.display_label,
            source_document=request.source_document,
            material_name=request.material_name,
        )
        if not row:
            raise HTTPException(status_code=404, detail="alias row not found")
        cleared = clear_condition_resolution_cache(raw_key)
        return H2ConditionAliasVerifyResponse(
            status="ok",
            cache_entries_cleared=cleared,
            alias=_alias_record_from_row(row),
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal H2 condition alias verify error") from exc


# ─── Materials Catalog ────────────────────────────────────────────────────────

@router.get("/materials")
async def materials() -> dict:
    """Return all materials in the H2 evidence database with stats.

    Derives the material list from the 371 evidence records —
    no hardcoded lists.
    """
    try:
        from mira.knowledge_twins.h2.engine_simple import H2Engine

        engine = H2Engine()
        stats = engine.get_evidence_stats()
        all_materials = engine.get_all_materials()
        return {
            "materials": all_materials,
            "count": len(all_materials),
            "total_evidence_records": stats["total_records"],
            "band_distribution": stats["band_distribution"],
            "family_distribution": stats["family_distribution"],
        }
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal H2 materials error") from exc


# ─── Guidance ─────────────────────────────────────────────────────────────────

@router.get("/guidance")
async def guidance() -> dict:
    """Return the H2 guidance JSON for the frontend.

    Provides field-level guidance, verdict explanations, concept
    definitions, and flag descriptions — all with NASA source citations.
    """
    global _GUIDANCE_CACHE
    if _GUIDANCE_CACHE is not None:
        return _GUIDANCE_CACHE

    if _GUIDANCE_PATH.exists():
        with open(_GUIDANCE_PATH, "r", encoding="utf-8") as f:
            _GUIDANCE_CACHE = json.load(f)
        return _GUIDANCE_CACHE

    raise HTTPException(status_code=404, detail="H2 guidance data not found")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _alias_record_from_row(row: dict) -> H2ConditionAliasRecord:
    details = row.get("details_jsonb") or {}
    needs_review = bool(
        details.get("needs_review")
        or (not bool(row.get("human_verified")))
        or (row.get("display_label") == "Generic/Unknown")
        or ((row.get("confidence") or 0.0) < 0.75)
    )
    return H2ConditionAliasRecord(
        raw_key=str(row.get("raw_key") or ""),
        raw_text=str(row.get("raw_text") or ""),
        canonical_condition=str(row.get("canonical_condition") or ""),
        display_label=str(row.get("display_label") or ""),
        is_condition=bool(row.get("is_condition")),
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        resolver_provider=row.get("resolver_provider"),
        resolver_model=row.get("resolver_model"),
        source_document=row.get("source_document"),
        material_name=row.get("material_name"),
        needs_review=needs_review,
        human_verified=bool(row.get("human_verified")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


__safety_critical__ = True  # NASA SWE-032 compliance
