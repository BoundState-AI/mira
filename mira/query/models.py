#!/usr/bin/env python3
"""
Canonical query models.

Delegates to BSMH model contracts so `/mira/query` and `/mira/bsmh/query`
remain wire-compatible.
"""

from __future__ import annotations

from mira.bsmh.models import (
    BSMHQueryRequest,
    BSMHQueryResponse,
)

QueryRequest = BSMHQueryRequest
QueryResponse = BSMHQueryResponse

__all__ = [
    "QueryRequest",
    "QueryResponse",
]

