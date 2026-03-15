#!/usr/bin/env python3
"""Minimal fracture-only backend for local Playwright smoke tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_fracture_router():
    module_path = Path(__file__).resolve().parents[1] / "mira" / "api" / "routers" / "fracture.py"
    spec = importlib.util.spec_from_file_location("fracture_router_module", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load fracture router from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.router


def create_app() -> FastAPI:
    app = FastAPI(title="MIRA Fracture Playwright Backend")
    router = _load_fracture_router()
    app.include_router(router, prefix="/mira", tags=["fracture"])
    app.include_router(router, prefix="/api/mira", tags=["fracture"])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8001, log_level="warning")
