#!/usr/bin/env python3
"""
Module: Api Models
Purpose: MIUL API Request/Response Models

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

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.models.answer import EvidenceItem
import uuid


class MiulBuildRequest(BaseModel):
    """Request to build a MIUL from input data.

    The MIUL (Material Identification and Usage List) is generated from
    a Bill of Materials (BOM) combined with material specifications.
    """

    program_name: str = Field(
        description="Program/project name (e.g., 'Gateway', 'Orion')",
    )
    bom_items: List[Dict[str, Any]] = Field(
        description="List of BOM items as dictionaries with part_number, quantity, etc.",
    )
    material_mappings: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional mapping of part_number -> material_code",
    )
    include_audit_trail: bool = Field(
        default=True,
        description="Include detailed audit trail in response",
    )
    strict_mode: bool = Field(
        default=False,
        description="Fail on missing material mappings",
    )


class MiulEntry(BaseModel):
    """Single entry in the MIUL output."""

    line_number: int = Field(description="Line number in MIUL")
    part_number: str = Field(description="Part number from BOM")
    material_code: Optional[str] = Field(description="Resolved material code")
    material_name: Optional[str] = Field(description="Material common name")
    quantity: float = Field(description="Quantity from BOM")
    specification: Optional[str] = Field(description="Material specification reference")
    drawing_number: Optional[str] = Field(description="Associated drawing")
    usage_notes: Optional[str] = Field(default=None, description="Usage notes")
    nasa_6016_class: Optional[str] = Field(default=None, description="NASA-STD-6016 classification")
    warnings: List[str] = Field(default_factory=list, description="Warnings for this entry")


class MiulBuildResponse(BaseModel):
    """Response from MIUL build operation."""

    success: bool = Field(description="Whether build completed successfully")
    program_name: str = Field(description="Program name from request")
    build_id: str = Field(description="Unique build identifier")
    build_timestamp: datetime = Field(description="When build was executed")
    entries: List[MiulEntry] = Field(description="Generated MIUL entries")
    total_entries: int = Field(description="Total number of MIUL entries")
    material_coverage_percent: float = Field(
        description="Percentage of parts with material mapping"
    )
    warnings: List[str] = Field(default_factory=list, description="Build warnings")
    errors: List[str] = Field(default_factory=list, description="Build errors")
    evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items supporting this build",
    )
    audit_trail: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Detailed audit trail if requested",
    )


__safety_critical__ = True  # NASA SWE-032 compliance
