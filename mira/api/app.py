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

from pathlib import Path

# Load .env BEFORE importing routers (they check env vars at import time)
from dotenv import load_dotenv
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import routers
import uuid


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="BoundState API", version="0.1.0")

    # CORS middleware for frontend development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://localhost:8081", "http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-MIUL-Count", "X-DT-Entries", "X-DT-Confidence", "X-Parts-Found", "X-Drawing-Count", "X-Materials-Found", "X-Pipeline-Version", "X-Project", "X-NHA-Override-Count", "X-Manual-Override-Used", "X-Blocker-Count", "X-Warning-Count", "X-Root-Assembly", "X-Package-ID", "X-Lineage-ID", "X-Confidence-Score"],
    )

    # Core routers (MIRA domain, AEGIS, etc.)
    app.include_router(routers.search_router, prefix="/search", tags=["search"])
    app.include_router(routers.mira_router, prefix="/mira", tags=["mira"])
    app.include_router(routers.query_router, prefix="/mira", tags=["query"])
    app.include_router(routers.aegis_router, prefix="/aegis", tags=["aegis"])
    app.include_router(routers.compliance_router, prefix="/compliance", tags=["compliance"])

    # O2 Knowledge Twin router (oxygen compatibility)
    app.include_router(routers.o2_router, prefix="/o2", tags=["o2"])

    # Hybrid query router (evidence-first query engine)
    # Note: hybrid_query router has its own /api/query prefix
    app.include_router(routers.hybrid_query_router, tags=["hybrid-query"])

    # MIUL/MUA workflow routers
    app.include_router(routers.miul_router, prefix="/miul", tags=["miul"])
    app.include_router(routers.bom_router, prefix="/bom", tags=["bom"])
    app.include_router(routers.mua_router, prefix="/mua", tags=["mua"])
    app.include_router(routers.mua_v6_router, prefix="/mua/v6", tags=["mua-v6"])
    app.include_router(routers.mua_v7_router, prefix="/mua/v7", tags=["mua-v7"])

    # M&P Plan Generator V1 + V2 (Codex)
    app.include_router(routers.mp_plan_router, prefix="/mp-plan", tags=["mp-plan"])
    app.include_router(routers.mp_plan_v2_codex_router, prefix="/mp-plan/v2", tags=["mp-plan-v2-codex"])

    # MIRA v4 Decision Lineage pipeline
    app.include_router(routers.mira_v4_router, prefix="/mira/v4", tags=["mira-v4"])
    app.include_router(routers.bsmh_router, prefix="/mira/bsmh", tags=["bsmh-temp"])

    # UI endpoints (semantic search, BOK search)
    # Note: ui_router has its own /api prefix on routes
    app.include_router(routers.ui_router, tags=["ui"])

    # Test classes browser (PostgreSQL-backed)
    # Note: test_classes_router has its own /api prefix on routes
    app.include_router(routers.test_classes_router, tags=["test-classes"])

    return app


app = create_app()


__safety_critical__ = True  # NASA SWE-032 compliance
