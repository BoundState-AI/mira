"""Canonical data models for MUA Matchmaker v8.

These models enforce the addendum lock-downs:
- Canonical issue codes only at all boundaries.
- Export mode contract for draft vs board-ready behavior.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IssueCode(str, Enum):
    """Canonical issue codes for v8."""

    FLAM = "FLAM"
    TOX = "TOX"
    O2 = "O2"
    HEE = "HEE"
    SCC = "SCC"
    CORR = "CORR"
    TVS = "TVS"
    FLUID = "FLUID"


class IssueStatus(str, Enum):
    """Per-issue work state in a matchmaker session."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    MANUAL_REQUIRED = "manual_required"


class MaterialResolutionStatus(str, Enum):
    """Material resolution state for Appendix D gating."""

    RESOLVED = "resolved"
    FUZZY = "fuzzy"
    UNRESOLVED = "unresolved"


class ExportMode(str, Enum):
    """Explicit export contract mode."""

    DRAFT = "draft"
    BOARD_READY = "board_ready"


class IssueOutcome(str, Enum):
    """Resolved disposition for a single issue."""

    PASS = "PASS"
    CAT_III = "CAT_III"
    CAT_I_II = "CAT_I_II"


class MUACategory(str, Enum):
    """Overall MUA category header label."""

    CAT_I = "I"
    CAT_II = "II"


ISSUE_CODE_ALIASES: dict[str, IssueCode] = {
    "FLAM": IssueCode.FLAM,
    "FLAMMABILITY": IssueCode.FLAM,
    "FLAMM": IssueCode.FLAM,
    "FL": IssueCode.FLAM,
    "TOX": IssueCode.TOX,
    "TOXICITY": IssueCode.TOX,
    "OFFGAS": IssueCode.TOX,
    "OG": IssueCode.TOX,
    "O2": IssueCode.O2,
    "O2_COMPAT": IssueCode.O2,
    "OXY": IssueCode.O2,
    "OXYGEN": IssueCode.O2,
    "HEE": IssueCode.HEE,
    "H2": IssueCode.HEE,
    "HYDROGEN": IssueCode.HEE,
    "HE": IssueCode.HEE,
    "SCC": IssueCode.SCC,
    "STRESS_CORROSION": IssueCode.SCC,
    "SC": IssueCode.SCC,
    "CORR": IssueCode.CORR,
    "CORROSION": IssueCode.CORR,
    "CR": IssueCode.CORR,
    "TVS": IssueCode.TVS,
    "THERMAL_VAC": IssueCode.TVS,
    "TV": IssueCode.TVS,
    "FLUID": IssueCode.FLUID,
    "FLUID_COMPAT": IssueCode.FLUID,
    "FS": IssueCode.FLUID,
    "FC": IssueCode.FLUID,
}


def normalize_issue_code(value: str | IssueCode) -> IssueCode:
    """Normalize external issue labels to canonical issue codes."""

    if isinstance(value, IssueCode):
        return value
    normalized = ISSUE_CODE_ALIASES.get(str(value or "").strip().upper())
    if normalized is None:
        valid = ", ".join(code.value for code in IssueCode)
        raise ValueError(f"Invalid issue code '{value}'. Valid codes: {valid}")
    return normalized


class MaterialResolution(BaseModel):
    """Adapter-stable material resolution payload."""

    input_text: str
    status: MaterialResolutionStatus
    material_code: Optional[str] = None
    material_key: Optional[int] = None
    resolved_name: Optional[str] = None
    family: Optional[str] = None
    material_class: Optional[str] = None
    is_process_sensitive: bool = False
    selection_method: Optional[str] = None
    selection_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class EnvironmentSpec(BaseModel):
    """Environment contract used by matchmaker adapters and search."""

    o2_percent: float = Field(..., ge=0.0, le=100.0)
    pressure_psia: float = Field(..., ge=0.0)
    temp_min_f: float
    temp_max_f: float
    medium: str
    location: str
    application: str = ""


class PrecedentMatch(BaseModel):
    """Minimal precedent shape consumed by v8 issue workbench."""

    mua_number: str
    determination: str
    rationale_text: Optional[str] = None
    material_designation: Optional[str] = None
    material_family: Optional[str] = None
    environment: str = ""
    o2_percent: Optional[float] = None
    pressure_psia: Optional[float] = None
    temp_min_f: Optional[float] = None
    temp_max_f: Optional[float] = None
    issue_codes: list[IssueCode] = Field(default_factory=list)
    source_issue_codes: list[str] = Field(default_factory=list)
    relevance_score: float = Field(0.0, ge=0.0, le=1.0)
    category_label: Optional[str] = None


class RationalePhrase(BaseModel):
    """Distilled rationale phrase from precedent text."""

    phrase: str
    mua_number: str
    score: float = Field(0.0, ge=0.0)


class ConflictPair(BaseModel):
    """Conflicting precedent pair for engineer visibility."""

    approved: PrecedentMatch
    negative: PrecedentMatch
    overlap_description: str


class IssueState(BaseModel):
    """Mutable issue work state persisted per session."""

    issue: str
    status: IssueStatus = IssueStatus.PENDING
    outcome: Optional[IssueOutcome] = None
    selected_code: Optional[str] = None
    candidate_codes: list[str] = Field(default_factory=list)
    answers: dict[str, Any] = Field(default_factory=dict)
    rationale: Optional[str] = None
    manual_disposition: Optional[str] = None
    out_of_scope: bool = False
    requirement_ref: Optional[str] = None
    matches: list[PrecedentMatch] = Field(default_factory=list)
    phrases: list[RationalePhrase] = Field(default_factory=list)
    conflicts: list[ConflictPair] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    last_question_id: Optional[str] = None


class MatchmakerEvent(BaseModel):
    """Immutable session event for audit traceability."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: str
    issue: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[Any] = None
    code: Optional[str] = None
    note: Optional[str] = None
    rule_pack_version: Optional[str] = None


class MatchmakerSession(BaseModel):
    """Matchmaker v8 session state persisted to disk."""

    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    rule_pack_version: str

    material_input: str
    material_resolution: MaterialResolution
    environment: EnvironmentSpec
    application_description: str = ""

    issues: dict[str, IssueState] = Field(default_factory=dict)
    banners: list[str] = Field(default_factory=list)
    category: Optional[MUACategory] = None
    category_reasons: list[str] = Field(default_factory=list)
    nonconformance_redirected: bool = False
    redirect_reason: Optional[str] = None

    events: list[MatchmakerEvent] = Field(default_factory=list)


class SessionSummary(BaseModel):
    """Compact session list payload."""

    session_id: str
    material_input: str
    updated_at: datetime
    issue_count: int = 0
    done_count: int = 0
    manual_count: int = 0
    category: Optional[MUACategory] = None


class ExportMissingField(BaseModel):
    """Single missing field reason for export validation."""

    field: str
    reason: str
    issue: Optional[IssueCode] = None


class ExportBlocker(BaseModel):
    """Single blocker for board-ready export mode."""

    status: IssueStatus | str
    reason: str
    issue: Optional[str] = None


class ExportValidationResponse(BaseModel):
    """Response model for `/export` mode gating."""

    export_ready: bool
    mode: ExportMode
    blockers: list[ExportBlocker] = Field(default_factory=list)
    missing_fields: list[ExportMissingField] = Field(default_factory=list)
    suggestion: Optional[str] = None
