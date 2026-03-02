#!/usr/bin/env python3
"""
Module: App
Purpose: FastAPI application for the BoundState HTTP surface.

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

import os
from pathlib import Path

# Load .env BEFORE importing routers (they check env vars at import time)
from dotenv import load_dotenv
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import routers  # noqa: E402
from .auth import CognitoAuthzMiddleware, validate_auth_configuration  # noqa: E402


def _build_cors_origins() -> list[str]:
    origins = [
        "http://localhost:8080",
        "http://localhost:8081",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
    ]
    extra_origins = os.getenv("CORS_EXTRA_ORIGINS", "")
    if extra_origins:
        origins.extend([o.strip() for o in extra_origins.split(",") if o.strip()])
    cognito_ui_origin = os.getenv("COGNITO_HOSTED_UI_ORIGIN", "").strip()
    if cognito_ui_origin:
        origins.append(cognito_ui_origin)
    return sorted(set(origins))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="BoundState API", version="0.1.0")

    validate_auth_configuration()
    app.add_middleware(CognitoAuthzMiddleware)

    # CORS middleware for frontend development and Cognito-authenticated clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-MIUL-Count", "X-DT-Entries", "X-DT-Confidence", "X-Parts-Found", "X-Drawing-Count", "X-Materials-Found", "X-Pipeline-Version", "X-Project", "X-NHA-Override-Count", "X-Manual-Override-Used", "X-Blocker-Count", "X-Warning-Count", "X-Root-Assembly", "X-Package-ID", "X-Lineage-ID", "X-Confidence-Score"],
    )

    def include_with_api_alias(router: APIRouter, *, prefix: str, tags: list[str]) -> None:
        """Mount a router at both root and /api for backward compatibility."""
        app.include_router(router, prefix=prefix, tags=tags)
        app.include_router(router, prefix=f"/api{prefix}", tags=tags)

    # Core routers (MIRA domain, AEGIS, etc.)
    include_with_api_alias(routers.search_router, prefix="/search", tags=["search"])
    include_with_api_alias(routers.mira_router, prefix="/mira", tags=["mira"])
    include_with_api_alias(routers.query_router, prefix="/mira", tags=["query"])
    include_with_api_alias(routers.aegis_router, prefix="/aegis", tags=["aegis"])
    include_with_api_alias(routers.compliance_router, prefix="/compliance", tags=["compliance"])

    # O2 Knowledge Twin router (oxygen compatibility)
    include_with_api_alias(routers.o2_router, prefix="/o2", tags=["o2"])

    # Hybrid query router (evidence-first query engine)
    # Note: hybrid_query router has its own /api/query prefix
    app.include_router(routers.hybrid_query_router, tags=["hybrid-query"])

    # MIUL/MUA workflow routers
    include_with_api_alias(routers.miul_router, prefix="/miul", tags=["miul"])
    include_with_api_alias(routers.bom_router, prefix="/bom", tags=["bom"])
    include_with_api_alias(routers.mua_router, prefix="/mua", tags=["mua"])
    include_with_api_alias(routers.mua_v6_router, prefix="/mua/v6", tags=["mua-v6"])
    include_with_api_alias(routers.mua_v7_router, prefix="/mua/v7", tags=["mua-v7"])
    include_with_api_alias(routers.mua_v10_router, prefix="/mua/v10", tags=["mua-v10"])
    include_with_api_alias(routers.matchmaker_router, prefix="/mua/matchmaker", tags=["mua-matchmaker-v8"])

    # M&P Plan Generator V1 + V2 (Codex)
    include_with_api_alias(routers.mp_plan_router, prefix="/mp-plan", tags=["mp-plan"])
    include_with_api_alias(routers.mp_plan_v2_codex_router, prefix="/mp-plan/v2", tags=["mp-plan-v2-codex"])

    # MIRA v4 Decision Lineage pipeline
    include_with_api_alias(routers.mira_v4_router, prefix="/mira/v4", tags=["mira-v4"])
    include_with_api_alias(routers.bsmh_router, prefix="/mira/bsmh", tags=["bsmh-temp"])

    # UI endpoints (semantic search, BOK search)
    # Note: ui_router has its own /api prefix on routes
    app.include_router(routers.ui_router, tags=["ui"])

    # Test classes browser (PostgreSQL-backed)
    # Note: test_classes_router has its own /api prefix on routes
    app.include_router(routers.test_classes_router, tags=["test-classes"])

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """ALB/container health check endpoint."""
        return {"status": "ok"}

    @app.get("/api/health", tags=["system"])
    async def api_health() -> dict[str, str]:
        """Backward-compatible health endpoint for /api clients."""
        return {"status": "ok"}

    # Startup instrumentation: prove which Python + app is serving
    import logging as _logging
    _startup_log = _logging.getLogger("mira.startup")
    import sys as _sys
    _startup_log.warning(
        "APP IDENTITY  python=%s  app_module=%s  routes=%d  mua_v10_routes=%s",
        _sys.executable,
        __file__,
        len([r for r in app.router.routes if hasattr(r, "path")]),
        [r.path for r in app.router.routes if hasattr(r, "path") and "mua/v10" in r.path],
    )

    return app


app = create_app()


__safety_critical__ = True  # NASA SWE-032 compliance
