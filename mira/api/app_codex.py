#!/usr/bin/env python3
"""
Codex app entrypoint with versioned M&P plan v2 router.

This file preserves the current production app unchanged while providing a
drop-in run target that includes `/mp-plan/v2/*` endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

from . import routers
from .auth import CognitoAuthzMiddleware, validate_auth_configuration
from .routers.mp_plan_v2_codex import router as mp_plan_v2_codex_router


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


def create_app_codex() -> FastAPI:
    app = FastAPI(title="BoundState API (Codex)", version="0.2.0-codex")

    validate_auth_configuration()
    app.add_middleware(CognitoAuthzMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
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
    app.include_router(routers.mira_router, prefix="/api/mira", tags=["mira"])
    app.include_router(routers.query_router, prefix="/mira", tags=["query"])
    app.include_router(routers.aegis_router, prefix="/aegis", tags=["aegis"])
    app.include_router(routers.compliance_router, prefix="/compliance", tags=["compliance"])
    app.include_router(routers.o2_router, prefix="/o2", tags=["o2"])
    app.include_router(routers.o2_router, prefix="/api/o2", tags=["o2"])
    app.include_router(routers.hybrid_query_router, tags=["hybrid-query"])
    app.include_router(routers.miul_router, prefix="/miul", tags=["miul"])
    app.include_router(routers.bom_router, prefix="/bom", tags=["bom"])
    app.include_router(routers.mua_router, prefix="/mua", tags=["mua"])
    app.include_router(routers.mua_v10_router, prefix="/mua/v10", tags=["mua-v10"])
    app.include_router(routers.mua_v10_router, prefix="/api/mua/v10", tags=["mua-v10"])
    app.include_router(routers.matchmaker_router, prefix="/mua/matchmaker", tags=["mua-matchmaker-v8"])
    app.include_router(routers.matchmaker_router, prefix="/api/mua/matchmaker", tags=["mua-matchmaker-v8"])
    app.include_router(routers.mp_plan_router, prefix="/mp-plan", tags=["mp-plan"])
    app.include_router(mp_plan_v2_codex_router, prefix="/mp-plan/v2", tags=["mp-plan-v2-codex"])
    app.include_router(routers.mira_v4_router, prefix="/mira/v4", tags=["mira-v4"])
    app.include_router(routers.mira_v4_router, prefix="/api/mira/v4", tags=["mira-v4"])
    app.include_router(routers.bsmh_router, prefix="/mira/bsmh", tags=["bsmh-temp"])
    app.include_router(routers.h2_router, prefix="/mira", tags=["h2"])
    app.include_router(routers.h2_router, prefix="/api/mira", tags=["h2"])
    if routers.tocr_router:
        app.include_router(routers.tocr_router, prefix="/tocr", tags=["tocr"])
        app.include_router(routers.tocr_router, prefix="/api/tocr", tags=["tocr"])
    app.include_router(routers.oca_router, prefix="/oca", tags=["oca"])
    app.include_router(routers.oca_systems_router, prefix="/oca/systems", tags=["oca-systems"])
    app.include_router(routers.oca_systems_router, prefix="/api/oca/systems", tags=["oca-systems"])
    app.include_router(routers.ui_router, tags=["ui"])
    app.include_router(routers.test_classes_router, tags=["test-classes"])

    return app


app = create_app_codex()
