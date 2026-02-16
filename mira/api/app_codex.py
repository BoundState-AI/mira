#!/usr/bin/env python3
"""
Codex app entrypoint with versioned M&P plan v2 router.

This file preserves the current production app unchanged while providing a
drop-in run target that includes `/mp-plan/v2/*` endpoints.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

from . import routers
from .routers.mp_plan_v2_codex import router as mp_plan_v2_codex_router


def create_app_codex() -> FastAPI:
    app = FastAPI(title="BoundState API (Codex)", version="0.2.0-codex")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8080",
            "http://localhost:8081",
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:8080",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Disposition",
            "X-MIUL-Count",
            "X-DT-Entries",
            "X-DT-Confidence",
            "X-Parts-Found",
            "X-Drawing-Count",
            "X-Materials-Found",
            "X-Pipeline-Version",
            "X-Project",
            "X-NHA-Override-Count",
            "X-Manual-Override-Used",
            "X-Blocker-Count",
            "X-Warning-Count",
            "X-Root-Assembly",
            "X-Package-ID",
            "X-Lineage-ID",
            "X-Confidence-Score",
        ],
    )

    app.include_router(routers.search_router, prefix="/search", tags=["search"])
    app.include_router(routers.mira_router, prefix="/mira", tags=["mira"])
    app.include_router(routers.query_router, prefix="/mira", tags=["query"])
    app.include_router(routers.aegis_router, prefix="/aegis", tags=["aegis"])
    app.include_router(routers.compliance_router, prefix="/compliance", tags=["compliance"])
    app.include_router(routers.o2_router, prefix="/o2", tags=["o2"])
    app.include_router(routers.hybrid_query_router, tags=["hybrid-query"])
    app.include_router(routers.miul_router, prefix="/miul", tags=["miul"])
    app.include_router(routers.bom_router, prefix="/bom", tags=["bom"])
    app.include_router(routers.mua_router, prefix="/mua", tags=["mua"])
    app.include_router(routers.mua_v6_router, prefix="/mua/v6", tags=["mua-v6"])
    app.include_router(routers.mua_v7_router, prefix="/mua/v7", tags=["mua-v7"])
    app.include_router(routers.mp_plan_router, prefix="/mp-plan", tags=["mp-plan"])
    app.include_router(mp_plan_v2_codex_router, prefix="/mp-plan/v2", tags=["mp-plan-v2-codex"])
    app.include_router(routers.mira_v4_router, prefix="/mira/v4", tags=["mira-v4"])
    app.include_router(routers.bsmh_router, prefix="/mira/bsmh", tags=["bsmh-temp"])
    app.include_router(routers.ui_router, tags=["ui"])
    app.include_router(routers.test_classes_router, tags=["test-classes"])

    return app


app = create_app_codex()
