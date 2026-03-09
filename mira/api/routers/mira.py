#!/usr/bin/env python3
"""
Module: Mira
Purpose: MIRA-related API routes (O2, H2, MAPTIS-backed services).

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

import logging
import os

from fastapi import APIRouter, HTTPException, Query

from mira.o2.models import (
    O2CompatibilityRequest,
    O2CompatibilityResponse,
)
from mira.o2 import evaluate_o2_compatibility

from mira.h2.models import (
    H2CompatibilityRequest,
    H2CompatibilityResponse,
    H2ConditionLookupResponse,
    H2ConditionAliasListResponse,
    H2ConditionAliasRecord,
    H2ConditionAliasVerifyRequest,
    H2ConditionAliasVerifyResponse,
)
from mira.h2 import evaluate_h2_compatibility
from mira.h2.engine import lookup_h2_conditions
from mira.h2.ft_temp import evaluate_h2_temp_compatibility
from mira.h2.runtime_db import list_condition_aliases, verify_condition_alias
from mira.h2.condition_resolver import clear_condition_resolution_cache, normalize_condition_key
import uuid


LOGGER = logging.getLogger(__name__)


router = APIRouter()


def _no_data_runtime_enabled() -> bool:
    return os.getenv("MIRA_NO_DATA_RUNTIME", "").strip().lower() in {"1", "true", "yes"}


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Simple health check for the MIRA endpoint."""

    return {"status": "ok", "domain": "mira"}


@router.post("/o2/compatibility", response_model=O2CompatibilityResponse)
async def o2_compatibility(
    request: O2CompatibilityRequest,
) -> O2CompatibilityResponse:
    """Evaluate oxygen compatibility for a given material and conditions."""

    try:
        return evaluate_o2_compatibility(request)
    except NotImplementedError as exc:
        # Explicit signal during wiring.
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        # Generic safety net; you can refine error handling later.
        raise HTTPException(
            status_code=500,
            detail="Internal O2 engine error",
        ) from exc


@router.post("/h2/compatibility", response_model=H2CompatibilityResponse)
async def h2_compatibility(
    request: H2CompatibilityRequest,
) -> H2CompatibilityResponse:
    """Evaluate hydrogen compatibility for a given material and conditions.

    Key H2-specific concerns evaluated:
    - Hydrogen embrittlement (HE) risk for high-strength steels
    - Hydride formation for titanium at elevated temps
    - Material family-based approval (austenitic SS, nickel alloys, etc.)

    Reference Standards:
    - NSS 1740.16: NASA Safety Standard for Hydrogen
    - SAND2012_7321: Sandia H2 Materials Compatibility
    """

    try:
        return evaluate_h2_compatibility(request)
    except NotImplementedError as exc:
        # Explicit signal during wiring.
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        # Generic safety net; you can refine error handling later.
        raise HTTPException(
            status_code=500,
            detail="Internal H2 engine error",
        ) from exc


@router.post("/h2/compatibility-temp", response_model=H2CompatibilityResponse)
async def h2_compatibility_temp(
    request: H2CompatibilityRequest,
) -> H2CompatibilityResponse:
    """Evaluate hydrogen compatibility through temp FT+guard architecture."""

    try:
        return evaluate_h2_temp_compatibility(request)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=500,
            detail="Internal H2 temp engine error",
        ) from exc


@router.get("/h2/conditions", response_model=H2ConditionLookupResponse)
async def h2_conditions(
    material_key: str = Query(..., min_length=1),
) -> H2ConditionLookupResponse:
    """Lookup known heat-treatment conditions for a material from H2 evidence."""
    try:
        return lookup_h2_conditions(material_key)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=500,
            detail="Internal H2 condition lookup error",
        ) from exc


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


@router.get("/h2/condition-aliases", response_model=H2ConditionAliasListResponse)
async def h2_condition_aliases(
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
            LOGGER.warning(
                "[MIRA/H2] Condition alias review unavailable in no-data runtime: %s",
                exc,
            )
            return H2ConditionAliasListResponse(
                material_key=material_key,
                unresolved_only=unresolved_only,
                count=0,
                aliases=[],
            )
        raise HTTPException(
            status_code=500,
            detail="Internal H2 condition alias listing error",
        ) from exc


@router.post("/h2/condition-aliases/verify", response_model=H2ConditionAliasVerifyResponse)
async def h2_condition_alias_verify(
    request: H2ConditionAliasVerifyRequest,
) -> H2ConditionAliasVerifyResponse:
    """Human-verify/override a condition alias mapping."""
    if _no_data_runtime_enabled():
        raise HTTPException(
            status_code=503,
            detail="H2 condition alias verification unavailable in no-data runtime",
        )

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
        raise HTTPException(
            status_code=500,
            detail="Internal H2 condition alias verify error",
        ) from exc


__safety_critical__ = True  # NASA SWE-032 compliance
