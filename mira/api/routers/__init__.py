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

from .search import router as search_router
from .mira import router as mira_router
from .aegis import router as aegis_router
from .miul import router as miul_router
from .bom import router as bom_router
from .mua import router as mua_router
from .mua_v6 import router as mua_v6_router
from .mua_v10 import router as mua_v10_router
from .hybrid_query import router as hybrid_query_router
from .ui_endpoints import router as ui_router
from .test_classes import router as test_classes_router
from .compliance import router as compliance_router
from .mp_plan import router as mp_plan_router
from .mp_plan_v2_codex import router as mp_plan_v2_codex_router
from .o2 import router as o2_router
from .mira_v4 import router as mira_v4_router
from .mua_v7 import router as mua_v7_router
from .matchmaker import router as matchmaker_router
from .bsmh import router as bsmh_router
from .query import router as query_router
from .forge import router as forge_router
from .galvanic import router as galvanic_router
from .fracture import router as fracture_router
from .h2 import router as h2_router
from .guidance import router as guidance_router
from .oca import router as oca_router
from .oca_systems import router as oca_systems_router
try:
    from .tocr import router as tocr_router
except ImportError:
    tocr_router = None

__all__ = [
    "search_router",
    "mira_router",
    "aegis_router",
    "miul_router",
    "bom_router",
    "mua_router",
    "mua_v6_router",
    "mua_v7_router",
    "mua_v10_router",
    "hybrid_query_router",
    "ui_router",
    "test_classes_router",
    "compliance_router",
    "mp_plan_router",
    "mp_plan_v2_codex_router",
    "o2_router",
    "mira_v4_router",
    "matchmaker_router",
    "bsmh_router",
    "query_router",
    "forge_router",
    "galvanic_router",
    "fracture_router",
    "h2_router",
    "guidance_router",
    "oca_router",
    "oca_systems_router",
    "tocr_router",
]


__safety_critical__ = True  # NASA SWE-032 compliance
