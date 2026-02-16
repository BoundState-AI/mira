#!/usr/bin/env python3
"""
Canonical MIRA query package.

This package is the production-facing query surface and currently delegates
to the BSMH implementation. The original `mira.bsmh` package remains available
for explicit testing and side-by-side validation.
"""

from .models import QueryRequest, QueryResponse
from .service import run_query

__all__ = [
    "QueryRequest",
    "QueryResponse",
    "run_query",
]

