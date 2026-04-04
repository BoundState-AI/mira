#!/usr/bin/env python3
"""
Shared FastAPI app factory for BoundState runtime surfaces.

This module is the single source of truth for environment loading,
middleware, router registration, health endpoints, and startup
instrumentation so app entrypoints cannot drift.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - lightweight test environments
    def load_dotenv(*args, **kwargs):  # type: ignore[no-redef]
        return False
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)

from . import routers  # noqa: E402
from .auth import CognitoAuthzMiddleware, validate_auth_configuration  # noqa: E402
from .ic_runtime import build_ic_router  # noqa: E402
from .module_controls import disabled_runtime_keys, runtime_key_enabled  # noqa: E402
from .rate_limit import (  # noqa: E402
    ApiRateLimitMiddleware,
    rate_limit_enabled,
    rate_limit_requests,
    rate_limit_window_seconds,
)
from .runtime_assets import validate_required_runtime_assets  # noqa: E402
from mira.core.session_store import validate_session_backend_configuration  # noqa: E402
from mira.providers.llm_provider import validate_provider_configuration  # noqa: E402


_EXPOSE_HEADERS = [
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
]


def _chat_required() -> bool:
    raw = os.getenv("MIRA_REQUIRE_CHAT", "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on"}
    environment = (
        os.getenv("MIRA_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).strip().lower()
    return environment != "test"


def _load_chat_router() -> Optional[APIRouter]:
    try:
        from mira.chat import chat_router
    except Exception as exc:
        if _chat_required():
            raise RuntimeError("MIRA chat failed to import and is required for this runtime.") from exc
        logging.getLogger("mira.startup").warning(
            "Chat router unavailable; continuing without /api/chat because chat is optional in this environment.",
            exc_info=True,
        )
        return None
    return chat_router


def _validate_runtime_environment(*, chat_router: APIRouter | None) -> None:
    validate_auth_configuration()
    validate_provider_configuration()
    validate_session_backend_configuration()
    if chat_router is not None:
        chat_provider = os.environ.get(
            "MIRA_CHAT_LLM_PROVIDER",
            os.environ.get("LLM_PROVIDER", ""),
        ).strip()
        if chat_provider:
            validate_provider_configuration(chat_provider)


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
        for origin in extra_origins.split(","):
            origin = origin.strip()
            # L3: Reject wildcard origins to prevent CORS bypass
            if origin and origin != "*":
                origins.append(origin)
    cognito_ui_origin = os.getenv("COGNITO_HOSTED_UI_ORIGIN", "").strip()
    if cognito_ui_origin:
        origins.append(cognito_ui_origin)
    return sorted(set(origins))


# M1: Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> StarletteResponse:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if os.getenv("MIRA_ENV", "development").lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def _include_with_api_alias(app: FastAPI, router: APIRouter, *, prefix: str, tags: list[str]) -> None:
    """Mount a router at both root and /api for backward compatibility."""
    app.include_router(router, prefix=prefix, tags=tags)
    app.include_router(router, prefix=f"/api{prefix}", tags=tags)


def _register_alias_routers(app: FastAPI) -> None:
    # Core routers
    _include_with_api_alias(app, routers.search_router, prefix="/search", tags=["search"])
    _include_with_api_alias(app, routers.mira_router, prefix="/mira", tags=["mira"])
    _include_with_api_alias(app, routers.query_router, prefix="/mira", tags=["query"])
    _include_with_api_alias(app, routers.aegis_router, prefix="/aegis", tags=["aegis"])
    _include_with_api_alias(app, routers.compliance_router, prefix="/compliance", tags=["compliance"])
    _include_with_api_alias(app, routers.guidance_router, prefix="/guidance", tags=["guidance"])

    # Knowledge twins and decision modules
    _include_with_api_alias(app, routers.o2_router, prefix="/o2", tags=["o2"])
    _include_with_api_alias(app, routers.galvanic_router, prefix="/mira", tags=["galvanic"])
    _include_with_api_alias(app, routers.fracture_router, prefix="/mira", tags=["fracture"])
    _include_with_api_alias(app, routers.h2_router, prefix="/mira", tags=["h2"])

    # OCA
    # The OCA router already owns the /oca prefix, so mount it directly and add
    # only the /api alias here.
    _include_with_api_alias(app, routers.oca_router, prefix="", tags=["oca"])
    _include_with_api_alias(app, routers.oca_systems_router, prefix="/oca/systems", tags=["oca-systems"])
    _include_with_api_alias(app, routers.usage_router, prefix="/usage", tags=["usage"])

    # MIUL/MUA/TOCR/FORGE/MP Plan
    _include_with_api_alias(app, routers.miul_router, prefix="/miul", tags=["miul"])
    _include_with_api_alias(app, routers.bom_router, prefix="/bom", tags=["bom"])
    if runtime_key_enabled("mua"):
        _include_with_api_alias(app, routers.mua_router, prefix="/mua", tags=["mua"])
    if runtime_key_enabled("mua-v6"):
        _include_with_api_alias(app, routers.mua_v6_router, prefix="/mua/v6", tags=["mua-v6"])
    if runtime_key_enabled("mua-v7"):
        _include_with_api_alias(app, routers.mua_v7_router, prefix="/mua/v7", tags=["mua-v7"])
    if runtime_key_enabled("mua-v10"):
        _include_with_api_alias(app, routers.mua_v10_router, prefix="/mua/v10", tags=["mua-v10"])
    if runtime_key_enabled("mua-matchmaker"):
        _include_with_api_alias(
            app,
            routers.matchmaker_router,
            prefix="/mua/matchmaker",
            tags=["mua-matchmaker-v8"],
        )
    _include_with_api_alias(app, routers.forge_router, prefix="/forge", tags=["forge"])
    if getattr(routers, "tocr_router", None) is not None:
        _include_with_api_alias(app, routers.tocr_router, prefix="/tocr", tags=["tocr"])
    _include_with_api_alias(app, routers.mp_plan_router, prefix="/mp-plan", tags=["mp-plan"])
    _include_with_api_alias(
        app,
        routers.mp_plan_v2_codex_router,
        prefix="/mp-plan/v2",
        tags=["mp-plan-v2-codex"],
    )

    # MIRA v4
    _include_with_api_alias(app, routers.mira_v4_router, prefix="/mira/v4", tags=["mira-v4"])
    _include_with_api_alias(app, routers.bsmh_router, prefix="/mira/bsmh", tags=["bsmh-temp"])


def _register_direct_routers(app: FastAPI, chat_router: APIRouter | None) -> None:
    # These routers already own their external prefixes.
    app.include_router(routers.hybrid_query_router, tags=["hybrid-query"])
    app.include_router(routers.ui_router, tags=["ui"])
    if runtime_key_enabled("test-classes"):
        app.include_router(routers.test_classes_router, tags=["test-classes"])
    if chat_router is not None:
        app.include_router(chat_router, tags=["chat"])
    ic_router = build_ic_router()
    app.include_router(ic_router, tags=["ic"])
    app.include_router(ic_router, prefix="/api", tags=["ic"])


def _register_health_routes(app: FastAPI) -> None:
    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """ALB/container health check endpoint."""
        return {"status": "ok"}

    @app.get("/api/health", tags=["system"])
    async def api_health() -> dict[str, str]:
        """Backward-compatible health endpoint for /api clients."""
        return {"status": "ok"}


def _log_startup_identity(app: FastAPI, *, app_identity_file: str) -> None:
    startup_log = logging.getLogger("mira.startup")
    startup_log.warning(
        "APP IDENTITY  python=%s  app_module=%s  routes=%d  disabled_runtime_keys=%s  critical_routes=%s",
        sys.executable,
        app_identity_file,
        len([route for route in app.router.routes if hasattr(route, "path")]),
        sorted(disabled_runtime_keys()),
        [
            route.path
            for route in app.router.routes
            if hasattr(route, "path")
            and (
                "mua/v10" in route.path
                or "mp-plan/v2" in route.path
                or route.path.startswith("/api/chat")
                or route.path.startswith("/api/tocr")
                or route.path.startswith("/mira/h2")
            )
        ],
    )


def create_app(
    *,
    title: str = "BoundState API",
    version: str = "0.1.0",
    app_identity_file: str,
) -> FastAPI:
    """Create the canonical BoundState API application."""
    validate_required_runtime_assets()
    chat_router = _load_chat_router()

    is_production = os.getenv("MIRA_ENV", "development").lower() == "production"

    # M9: Disable interactive docs in production
    app = FastAPI(
        title=title,
        version=version,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    _validate_runtime_environment(chat_router=chat_router)
    app.add_middleware(SecurityHeadersMiddleware)  # M1: Security headers
    app.add_middleware(CognitoAuthzMiddleware)
    if rate_limit_enabled():
        app.add_middleware(
            ApiRateLimitMiddleware,
            max_requests=rate_limit_requests(),
            window_seconds=rate_limit_window_seconds(),
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
        allow_credentials=True,
        # M2: Restrict to specific methods and required headers
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
        expose_headers=_EXPOSE_HEADERS,
    )

    _register_alias_routers(app)
    _register_direct_routers(app, chat_router)
    _register_health_routes(app)
    _log_startup_identity(app, app_identity_file=app_identity_file)
    return app
