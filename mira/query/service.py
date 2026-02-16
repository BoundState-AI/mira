#!/usr/bin/env python3
"""
Canonical query orchestration service.

Delegates to BSMH while we keep `mira.bsmh` as an explicit test path.
"""

from __future__ import annotations

from mira.bsmh.service import run_bsmh_query
from .models import QueryRequest, QueryResponse


async def run_query(request: QueryRequest) -> QueryResponse:
    return await run_bsmh_query(request)


__all__ = [
    "run_query",
]

