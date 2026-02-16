#!/usr/bin/env python3
"""
Canonical MIRA query router.

Primary query endpoint:
- POST /mira/query

Testing endpoint remains:
- POST /mira/bsmh/query
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter

from mira.query.models import QueryRequest, QueryResponse
from mira.query.service import run_query

router = APIRouter()


@router.get("/query/ping")
async def ping() -> Dict[str, str]:
    return {"status": "ok", "domain": "mira-query", "pipeline": "B-S-M-S", "version": "1.0.0"}


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    return await run_query(request)

