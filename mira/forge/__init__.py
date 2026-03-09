#!/usr/bin/env python3
"""
FORGE package.

Deterministic database compiler for generating BoundState-ready artifacts
without modifying existing MIRA decision paths.
"""

from .compiler import ForgeCompiler
from .differ import build_alembic_stub, diff_schema_manifests
from .models import ForgeCompileRequest, ForgeCompileResponse, ForgeGeneratedBundle

__all__ = [
    "ForgeCompiler",
    "ForgeCompileRequest",
    "ForgeCompileResponse",
    "ForgeGeneratedBundle",
    "diff_schema_manifests",
    "build_alembic_stub",
]
