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

from fastapi import FastAPI

from .app_factory import create_app as _create_app


def create_app() -> FastAPI:
    """Create and configure the canonical FastAPI application."""
    return _create_app(app_identity_file=__file__)


app = create_app()


__safety_critical__ = True  # NASA SWE-032 compliance
