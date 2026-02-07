#!/usr/bin/env python3
"""
Module: Api Models
Purpose: MUA API Request/Response Models

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
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from core.models.answer import EvidenceItem
import uuid


RatingClass = Literal["FLAMM", "SCC", "CORR", "TVS", "TOX", "FS"]
RatingValue = Literal["A", "B", "C", "X", "U"]


class EnvironmentSpec(BaseModel):
    """Environmental operating conditions for the material."""

    oxygen_pct: Optional[float] = Field(
        default=None,
        description="Oxygen percentage (0-100)",
    )
    pressure_kpa: Optional[float] = Field(
        default=None,
        description="Operating pressure in kPa",
    )
    temperature_c: Optional[float] = Field(
        default=None,
        description="Operating temperature in Celsius",
    )
    fluid_medium: Optional[str] = Field(
        default=None,
        description="Fluid/gas medium (e.g., 'LOX', 'GH2', 'N2H4')",
    )
    habitable_volume: Optional[bool] = Field(
        default=None,
        description="Whether in habitable volume (drives TVS requirements)",
    )


class MaterialRating(BaseModel):
    """Test rating for a specific test class."""

    test_class: RatingClass = Field(description="Test class (FLAMM, SCC, etc.)")
    rating: RatingValue = Field(description="Rating value (A, B, C, X, U)")
    test_report: Optional[str] = Field(
        default=None,
        description="Test report number",
    )
    test_date: Optional[str] = Field(
        default=None,
        description="Date of test",
    )


class MuaGenerationRequest(BaseModel):
    """Request to generate an MUA for a material.

    An MUA (Material Usage Agreement) documents the rationale for using
    a material that does not have full A-ratings in all test classes.
    """

    material_key: str = Field(
        description="Material identifier (MAPTIS code or designation)",
    )
    material_name: Optional[str] = Field(
        default=None,
        description="Material common name",
    )
    specification: Optional[str] = Field(
        default=None,
        description="Material specification reference",
    )
    program: str = Field(
        description="Program name (e.g., 'Gateway', 'Orion')",
    )
    hardware_name: Optional[str] = Field(
        default=None,
        description="Hardware/component name",
    )
    hardware_class: Optional[str] = Field(
        default=None,
        description="Hardware classification",
    )
    environment: EnvironmentSpec = Field(
        description="Environmental operating conditions",
    )
    known_ratings: List[MaterialRating] = Field(
        default_factory=list,
        description="Known test ratings for this material",
    )
    application_context: Optional[str] = Field(
        default=None,
        description="Application context/notes",
    )


class MitigationClause(BaseModel):
    """A mitigation clause for gap coverage in the MUA."""

    test_class: RatingClass = Field(description="Test class being mitigated")
    rating_gap: RatingValue = Field(description="Rating being mitigated")
    mitigation_text: str = Field(description="Mitigation rationale text")
    source_document: str = Field(description="Source document for mitigation")
    clause_refs: List[str] = Field(description="NASA-STD-6016 clause references")
    confidence_score: float = Field(description="Confidence in this mitigation (0-1)")
    precedent_count: int = Field(
        default=0,
        description="Number of similar precedents found",
    )


class MuaGenerationResponse(BaseModel):
    """Response from MUA generation."""

    success: bool = Field(description="Whether generation completed successfully")
    material_key: str = Field(description="Material identifier")
    material_name: Optional[str] = Field(description="Material common name")
    program: str = Field(description="Program name")
    category: str = Field(
        description="MUA category (I, II, or III per NASA-STD-6016)",
    )
    appendix_b_exemptions: List[str] = Field(
        default_factory=list,
        description="Appendix B exemption codes if applicable",
    )
    gaps_identified: Dict[str, str] = Field(
        description="Test class -> rating for non-A ratings",
    )
    mitigations: List[MitigationClause] = Field(
        description="Mitigation clauses for gaps",
    )
    rationale_summary: str = Field(
        description="Summary rationale for material usage",
    )
    evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items supporting this MUA",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Generation warnings",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Generation timestamp",
    )


class MuaRecord(BaseModel):
    """Complete MUA record for storage/retrieval.

    This is the canonical representation of an MUA, whether generated
    or parsed from a historic PDF.
    """

    mua_id: str = Field(description="Unique MUA identifier")
    material_key: str = Field(description="Material identifier")
    material_name: str = Field(description="Material common name")
    specification: Optional[str] = Field(description="Material specification")
    program: str = Field(description="Program name")
    hardware_name: Optional[str] = Field(description="Hardware/component name")
    category: str = Field(description="MUA category (I, II, III)")

    # Environment
    environment: EnvironmentSpec = Field(description="Operating environment")

    # Ratings and gaps
    ratings: List[MaterialRating] = Field(description="All test ratings")
    gaps: Dict[str, str] = Field(description="Non-A ratings by test class")

    # Mitigations
    mitigations: List[MitigationClause] = Field(description="Mitigation clauses")
    rationale: str = Field(description="Overall rationale")

    # Metadata
    created_at: datetime = Field(description="Creation timestamp")
    approved_by: Optional[str] = Field(default=None, description="Approver name")
    approval_date: Optional[datetime] = Field(default=None, description="Approval date")
    source_document: Optional[str] = Field(
        default=None,
        description="Source PDF path if parsed from historic MUA",
    )
    evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Supporting evidence",
    )


__safety_critical__ = True  # NASA SWE-032 compliance
