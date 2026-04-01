#!/usr/bin/env python3
"""
Module:   Init
Purpose: API routers exposed by the BoundState service.

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

from importlib import import_module
from typing import Any

from fastapi import APIRouter

_ROUTER_MODULES = {
    "search_router": ".search",
    "mira_router": ".mira",
    "aegis_router": ".aegis",
    "miul_router": ".miul",
    "bom_router": ".bom",
    "mua_router": ".mua",
    "mua_v6_router": ".mua_v6",
    "mua_v7_router": ".mua_v7",
    "mua_v10_router": ".mua_v10",
    "hybrid_query_router": ".hybrid_query",
    "ui_router": ".ui_endpoints",
    "test_classes_router": ".test_classes",
    "compliance_router": ".compliance",
    "mp_plan_router": ".mp_plan",
    "mp_plan_v2_codex_router": ".mp_plan_v2_codex",
    "o2_router": ".o2",
    "mira_v4_router": ".mira_v4",
    "matchmaker_router": ".matchmaker",
    "bsmh_router": ".bsmh",
    "query_router": ".query",
    "forge_router": ".forge",
    "galvanic_router": ".galvanic",
    "fracture_router": ".fracture",
    "h2_router": ".h2",
    "guidance_router": ".guidance",
    "oca_router": ".oca",
    "oca_systems_router": ".oca_systems",
    "tocr_router": ".tocr",
}

__all__ = list(_ROUTER_MODULES)
_EMPTY_ROUTER = APIRouter()
_OPTIONAL_EMPTY_ROUTERS = {"forge_router", "mp_plan_v2_codex_router"}
_OPTIONAL_NONE_ROUTERS = {"tocr_router"}


def __getattr__(name: str) -> Any:
    module_name = _ROUTER_MODULES.get(name)
    if not module_name:
        raise AttributeError(name)
    try:
        module = import_module(module_name, __name__)
    except ImportError:
        if name in _OPTIONAL_NONE_ROUTERS:
            value = None
            globals()[name] = value
            return value
        if name in _OPTIONAL_EMPTY_ROUTERS:
            globals()[name] = _EMPTY_ROUTER
            return _EMPTY_ROUTER
        raise
    value = getattr(module, "router")
    globals()[name] = value
    return value


__safety_critical__ = True  # NASA SWE-032 compliance
