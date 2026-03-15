#!/usr/bin/env python3
"""
Codex app entrypoint.

This wrapper now delegates to the shared runtime factory so the codex
surface cannot drift from the production app on router wiring,
middleware, or health endpoints.
"""

from __future__ import annotations

from fastapi import FastAPI

from .app_factory import create_app as _create_app


def create_app_codex() -> FastAPI:
    """Create the codex-labelled FastAPI application."""
    return _create_app(
        title="BoundState API (Codex)",
        version="0.2.0-codex",
        app_identity_file=__file__,
    )


app = create_app_codex()
