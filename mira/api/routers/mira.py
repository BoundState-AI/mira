#!/usr/bin/env python3
"""
Module: Mira
Purpose: MIRA-related API routes (O2, MAPTIS-backed services).

H2 endpoints have been moved to mira/api/routers/h2.py for first-class routing.

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

from fastapi import APIRouter, HTTPException

from mira.o2.models import (
    O2CompatibilityRequest,
    O2CompatibilityResponse,
)
from mira.o2 import evaluate_o2_compatibility


LOGGER = logging.getLogger(__name__)


router = APIRouter()


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
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Internal O2 engine error") from exc


__safety_critical__ = True  # NASA SWE-032 compliance
