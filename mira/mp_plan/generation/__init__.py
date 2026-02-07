#!/usr/bin/env python3
"""
Module: Generation Package
Purpose: Document generation for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from .section_builder import (
    SectionContent,
    SectionBuilder,
    build_all_sections,
)
from .template_renderer import (
    TemplateRenderer,
    render_section,
)
from .mp_plan_docx import (
    MPPlanDocxGenerator,
    generate_mp_plan_docx,
)
from .miul_xlsx import (
    MIULExcelGenerator,
    generate_miul_xlsx,
)
from .review_packet import (
    ReviewPacket,
    ReviewPacketGenerator,
    generate_review_packet,
)
from .export_artifacts import (
    generate_applicability_matrix_xlsx,
    generate_gap_register_xlsx,
    generate_session_manifest,
    generate_manifest_json,
)

__all__ = [
    # Section builder
    "SectionContent",
    "SectionBuilder",
    "build_all_sections",
    # Template renderer
    "TemplateRenderer",
    "render_section",
    # DOCX generator
    "MPPlanDocxGenerator",
    "generate_mp_plan_docx",
    # Excel generator
    "MIULExcelGenerator",
    "generate_miul_xlsx",
    # Review packet
    "ReviewPacket",
    "ReviewPacketGenerator",
    "generate_review_packet",
    # Export artifacts
    "generate_applicability_matrix_xlsx",
    "generate_gap_register_xlsx",
    "generate_session_manifest",
    "generate_manifest_json",
]

__version__ = "2.0.0"
__safety_critical__ = False
