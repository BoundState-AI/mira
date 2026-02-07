#!/usr/bin/env python3
"""
Module:   Init  
Purpose: MIUL (Materials and Inspection Usage List) Module

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

# v1 imports (from archive) - for backward compatibility
try:
    from .v1_archive.miul_builder import MIULBuilder, MIULExporter
except ImportError:
    MIULBuilder = None
    MIULExporter = None

# v2 imports - new clean sheet architecture
from . import v2

# MUA remarks generator for populating rationale on non-A ratings
try:
    from .mua_remarks_generator import (
        generate_remark,
        generate_remarks_bulk,
        populate_miul_remarks,
        RemarkResult,
    )
except ImportError:
    generate_remark = None
    generate_remarks_bulk = None
    populate_miul_remarks = None
    RemarkResult = None

__all__ = [
    'MIULBuilder',
    'MIULExporter',
    'v2',
    'generate_remark',
    'generate_remarks_bulk',
    'populate_miul_remarks',
    'RemarkResult',
]
