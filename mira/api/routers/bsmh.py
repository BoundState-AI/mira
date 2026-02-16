#!/usr/bin/env python3
"""
Temporary BSMH API router.

This endpoint is intentionally additive and does not modify existing v4 behavior.
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter

from mira.bsmh.models import BSMHQueryRequest, BSMHQueryResponse
from mira.bsmh.service import run_bsmh_query

router = APIRouter()


@router.get("/ping")
async def ping() -> Dict[str, str]:
    """Health check for temporary BSMH endpoint."""
    return {"status": "ok", "domain": "bsmh", "pipeline": "B-S-M-S", "version": "0.1.0-temp"}


@router.post("/query", response_model=BSMHQueryResponse)
async def query_bsmh(request: BSMHQueryRequest) -> BSMHQueryResponse:
    """Execute temporary BSMH pipeline."""
    return await run_bsmh_query(request)
