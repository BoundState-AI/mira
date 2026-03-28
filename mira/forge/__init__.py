#!/usr/bin/env python3
"""
FORGE package.

MIRA keeps a stable subset of FORGE in-repo, while standalone FORGE ships
additional helpers such as ``database_urls``. Extending the package path lets
``mira.forge.*`` resolve local modules first and fall through to
``boundstate_forge/mira/forge`` for newer shared helpers.
"""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

from .compiler import ForgeCompiler
from .differ import build_alembic_stub, diff_schema_manifests
from .models import ForgeCompileRequest, ForgeCompileResponse, ForgeGeneratedBundle

__path__ = extend_path(__path__, __name__)

_BOUNDSTATE_ROOT = Path(__file__).resolve().parents[3]
_FORGE_SOURCE_CANDIDATES = (
    _BOUNDSTATE_ROOT / "boundstate_forge" / "mira" / "forge",
    _BOUNDSTATE_ROOT / "mira" / "boundstate_forge" / "mira" / "forge",
)
for _forge_source in _FORGE_SOURCE_CANDIDATES:
    if _forge_source.exists():
        __path__.append(str(_forge_source))

__all__ = [
    "ForgeCompiler",
    "ForgeCompileRequest",
    "ForgeCompileResponse",
    "ForgeGeneratedBundle",
    "diff_schema_manifests",
    "build_alembic_stub",
]
