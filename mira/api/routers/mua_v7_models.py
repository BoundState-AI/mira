"""MUA v7 API Router — Response and Request Models.

Pydantic models used exclusively by the mua_v7 router endpoints.
Extracted from mua_v7.py to keep the router file focused on route
handlers and reduce the god-class footprint.

Co-Authored-By: Claude "Atlas" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from mira.mua.v7.models import (
    CategoryRoutingResult,
    Center,
    EvidenceStrengthBand,
    FinalizedMUA,
    InvestigationResult,
    MaterialResolution,
    MUADraft,
    ReviewDecisions,
    SessionStatus,
    StepName,
)


# ---------------------------------------------------------------------------
# Session management models
# ---------------------------------------------------------------------------


class SessionSummary(BaseModel):
    """Lightweight session summary returned by the list endpoint.

    Omits bulky investigation data and draft content to keep the
    response compact for dashboard views.
    """

    session_id: str
    current_step: StepName
    status: SessionStatus
    material_input: Optional[str] = None
    center: Optional[Center] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionListResponse(BaseModel):
    """Response for the session list endpoint."""

    sessions: list[SessionSummary]
    total: int


class SessionDetailResponse(BaseModel):
    """Full session state for the resume endpoint."""

    session_id: str
    current_step: StepName
    status: SessionStatus
    material_input: Optional[str] = None
    center: Optional[Center] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    approved_cat3_codes: Optional[list[str]] = None
    investigation: Optional[InvestigationResult] = None
    review_decisions: Optional[ReviewDecisions] = None
    draft: Optional[MUADraft] = None
    finalized_mua: Optional[FinalizedMUA] = None


class DeleteSessionResponse(BaseModel):
    """Confirmation that a session was abandoned."""

    session_id: str
    status: SessionStatus


class StatsResponse(BaseModel):
    """Usage analytics response."""

    total_sessions: int = 0
    sessions_by_status: dict[str, int] = Field(default_factory=dict)
    avg_completion_time_seconds: Optional[float] = None
    sessions_finalized_last_30d: int = 0
    most_common_materials: list[dict] = Field(default_factory=list)
    most_common_centers: list[dict] = Field(default_factory=list)


class InvestigateKickoffResponse(BaseModel):
    """Async kickoff response -- returned immediately when investigation starts."""

    session_id: str
    status: str = "investigating"


class InvestigationStatusResponse(BaseModel):
    """Lightweight polling response for investigation progress."""

    session_id: str
    status: str  # investigating | complete | failed | idle
    progress: int = 0
    current_step: Optional[StepName] = None
    session_status: Optional[SessionStatus] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# MIUL import models
# ---------------------------------------------------------------------------


class MIULImportBucket(BaseModel):
    bucket_id: str
    material_code: str
    suggested_material: str
    trigger_signature: str
    issue_codes: list[str] = Field(default_factory=list)
    environment_raw: str = ""
    part_count: int = 0
    risk_band: str = "low"
    likely_category: str = "II_or_III"
    category_reasons: list[str] = Field(default_factory=list)
    fluid_types: list[str] = Field(default_factory=list)
    sample_part_numbers: list[str] = Field(default_factory=list)
    sample_part_descriptions: list[str] = Field(default_factory=list)
    suggested_environment: dict = Field(default_factory=dict)


class MIULImportResponse(BaseModel):
    filename: str
    total_parts: int
    non_a_parts: int
    bucket_count: int
    buckets: list[MIULImportBucket]


# ---------------------------------------------------------------------------
# Material intelligence models
# ---------------------------------------------------------------------------


class MaterialIntelRequest(BaseModel):
    """Request richer candidate intelligence for HITL material selection."""

    material: Optional[str] = None
    material_code: Optional[str] = None
    top_n: int = Field(8, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)


class MaterialStatsItem(BaseModel):
    label: str
    count: int


class MaterialCoverageStats(BaseModel):
    """Estimated precedent coverage for a material candidate."""

    query_mode: str = "token_estimate"
    total_muas: int = 0
    approved: int = 0
    conditional: int = 0
    rejected: int = 0
    deferred: int = 0
    top_issues: list[MaterialStatsItem] = Field(default_factory=list)
    top_env_types: list[MaterialStatsItem] = Field(default_factory=list)
    sample_muas: list[str] = Field(default_factory=list)


class MaterialIntelCandidate(BaseModel):
    material_code: str
    material_key: Optional[int] = None
    designation: str
    score: float = 0.0
    family: Optional[str] = None
    form: Optional[str] = None
    condition: Optional[str] = None
    is_mixed_record: bool = False
    differences: list[str] = Field(default_factory=list)
    coverage: MaterialCoverageStats = Field(default_factory=MaterialCoverageStats)


class MaterialDisambiguationOption(BaseModel):
    value: str
    label: str
    candidate_count: int = 0


class MaterialDisambiguationQuestion(BaseModel):
    key: str
    prompt: str
    options: list[MaterialDisambiguationOption] = Field(default_factory=list)
    selected_value: Optional[str] = None


class MaterialIntelResponse(BaseModel):
    resolution: MaterialResolution
    mixed_input: bool = False
    initial_candidate_count: int = 0
    candidate_count: int = 0
    candidates: list[MaterialIntelCandidate] = Field(default_factory=list)
    active_filters: dict[str, str] = Field(default_factory=dict)
    disambiguation_questions: list[MaterialDisambiguationQuestion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Preview issues models
# ---------------------------------------------------------------------------


class PreviewIssuesRequest(BaseModel):
    """Lightweight request to preview auto-detected issue codes."""
    o2_percent: float = 21.0
    pressure_psia: float = 14.7
    temp_min_f: float = 60.0
    temp_max_f: float = 85.0
    medium: str = "Air"
    location: str = "habitable"


class IssueCodeInfo(BaseModel):
    code: str
    label: str
    auto_detected: bool = True


class PreviewIssuesResponse(BaseModel):
    issues: list[IssueCodeInfo]


# ---------------------------------------------------------------------------
# Compiled regex patterns for material intel helpers
# ---------------------------------------------------------------------------

_FORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("tube", re.compile(r"\b(TUBE|TUBING|PIPE)\b", re.IGNORECASE)),
    ("wire", re.compile(r"\b(WIRE|CABLE|SPRING WIRE)\b", re.IGNORECASE)),
    ("sheet", re.compile(r"\b(SHEET|FOIL|STRIP)\b", re.IGNORECASE)),
    ("plate", re.compile(r"\bPLATE\b", re.IGNORECASE)),
    ("bar", re.compile(r"\b(BAR|ROD)\b", re.IGNORECASE)),
    ("forging", re.compile(r"\b(FORGING|FORGED)\b", re.IGNORECASE)),
    ("casting", re.compile(r"\bCASTING\b", re.IGNORECASE)),
]

_CONDITION_PATTERN = re.compile(
    r"\b(CONDITION\s+[A-Z0-9]+|ANNEALED|COLD\s+ROLLED|COLD\s+DRAWN|TEMPER|HARD)\b",
    re.IGNORECASE,
)
_TEMPER_PATTERN = re.compile(r"\b(T\d{1,4}|H\d{1,2}|O|F)\b", re.IGNORECASE)
_MATERIAL_KEYWORD_PATTERN = re.compile(
    r"\b(STEEL|STAINLESS|CRES|SST|ALUMINUM|ALUMINIUM|ALLOY|TITANIUM|INCONEL|NICKEL)\b",
    re.IGNORECASE,
)

_ISSUE_LABELS: dict[str, str] = {
    "FLAM": "Flammability",
    "TVS": "Thermal Vacuum Stability",
    "FS": "Fluid Susceptibility",
    "TOX": "Toxicity",
    "OFFGAS": "Offgassing",
    "O2_COMPAT": "O2 Compatibility",
    "HEE": "Hydrogen Embrittlement",
    "SCC": "Stress Corrosion",
    "CORR": "Corrosion",
    "FRACTURE": "Cryogenic Fracture",
}
