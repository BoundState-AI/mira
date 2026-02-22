"""MUA v7 Data Model Layer.

Core data models for the NASA Material Usage Agreement (MUA) v7 generation
pipeline, per the Final Specification.

Design decisions
----------------
- Pydantic ``BaseModel`` throughout (not dataclasses) for API serialization.
- "Evidence Strength" naming, never "Confidence" -- this distinction is
  safety-critical.
- Missing data defaults to ``0.0`` (unknown), never ``0.5`` (neutral).
- Language uses "may be applicable", never "is approved".
- Two-tier evidence identity:
    Tier A -- SHA-256 of canonical JSON payload (full content available).
    Tier B -- SHA-256 of ``"{source_type}:{primary_id}:{locator}:{span}"``
              (deterministic fallback).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Enums
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    """Kind of evidence source feeding the MUA pipeline."""

    MAPTIS_TEST = "maptis_test"
    MUA_CORPUS = "mua_corpus"
    BOK_REQUIREMENT = "bok_requirement"
    STANDARD_SECTION = "standard_section"
    REPORT_PDF = "report_pdf"
    USER_NOTE = "user_note"


class ClaimType(str, Enum):
    """Type of assertion an atomic claim can express."""

    RATING = "rating"
    ENVELOPE = "envelope"
    DETERMINATION = "determination"
    MITIGATION = "mitigation"
    CONSTRAINT = "constraint"
    APPLICABILITY = "applicability"
    PROHIBITION = "prohibition"


class EvidenceStrengthBand(str, Enum):
    """Discrete band for evidence strength.

    Deliberately named *Strength* rather than *Confidence* --
    the distinction is safety-critical.
    """

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    INSUFFICIENT = "insufficient"


class StepName(str, Enum):
    """Pipeline step identifiers."""

    DEFINE = "define"
    INVESTIGATE = "investigate"
    REVIEW = "review"
    DRAFT = "draft"
    FINALIZE = "finalize"


class SessionStatus(str, Enum):
    """Lifecycle state of an MUA session."""

    ACTIVE = "active"
    DRAFT_SAVED = "draft_saved"
    FINALIZED = "finalized"
    ABANDONED = "abandoned"


class MUACategory(str, Enum):
    """NASA MUA category routing (I / II / III)."""

    I = "I"
    II = "II"
    III = "III"


class ReviewDecisionType(str, Enum):
    """Engineer review decision for a precedent or conflict."""

    INCLUDE_SUPPORTING = "include_supporting"
    INCLUDE_CONTEXT = "include_context"
    EXCLUDE = "exclude"


class GapDecisionType(str, Enum):
    """Engineer decision for an identified gap."""

    ACCEPT_WITH_RATIONALE = "accept_with_rationale"
    FLAG_FOR_TESTING = "flag_for_testing"


class IssueCode(str, Enum):
    """MAPTIS issue codes that can trigger an MUA.

    These map to the canonical test families in NASA-STD-6016C.
    An engineer can specify which issues drove the MUA request,
    or the system can auto-derive them from environment parameters.
    """

    FLAM = "FLAM"           # Flammability
    TVS = "TVS"             # Thermal Vacuum Stability
    FS = "FS"               # Fluid Susceptibility
    TOX = "TOX"             # Toxicity / Offgassing
    SCC = "SCC"             # Stress Corrosion Cracking
    CORR = "CORR"           # Corrosion
    O2_COMPAT = "O2_COMPAT" # Oxygen Compatibility
    HEE = "HEE"             # Hydrogen Embrittlement
    OFFGAS = "OFFGAS"       # Offgassing (habitable)
    FRACTURE = "FRACTURE"   # Cryogenic Fracture


class MaterialClass(str, Enum):
    """High-level material classification."""

    METAL = "metal"
    ALLOY = "alloy"
    POLYMER = "polymer"
    ELASTOMER = "elastomer"
    ADHESIVE = "adhesive"
    COMPOSITE = "composite"
    POTTING = "potting"
    SEALANT = "sealant"
    CERAMIC = "ceramic"
    COATING = "coating"
    LUBRICANT = "lubricant"
    OTHER = "other"


class ResolutionStatus(str, Enum):
    """Material resolution status.

    RESOLVED   -- Green checkmark: unambiguous match.
    FUZZY      -- Yellow: engineer confirmation required.
    UNRESOLVED -- Red: manual input needed.
    """

    RESOLVED = "resolved"
    FUZZY = "fuzzy"
    UNRESOLVED = "unresolved"


class RelationshipType(str, Enum):
    """Relationship between query material identity and MAPTIS candidate."""

    EXACT_MATCH = "exact_match"
    SAME_ALLOY_DIFFERENT_FORM = "same_alloy_different_form"
    SAME_ALLOY_DIFFERENT_TEMPER = "same_alloy_different_temper"
    FAMILY_MATCH = "family_match"


class DeterminationStatus(str, Enum):
    """Outcome determination for an MUA or precedent."""

    APPROVED = "approved"
    CONDITIONAL = "conditional"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class OverlapStatus(str, Enum):
    """Envelope overlap status for a single dimension or overall."""

    WITHIN = "within"
    PARTIAL = "partial_overlap"
    EXTRAPOLATION = "extrapolation"
    OUTSIDE = "outside"
    INSUFFICIENT_DATA = "insufficient_data"


class ConflictSeverity(str, Enum):
    """Severity of a conflict between evidence sources.

    HARD -- e.g. COMPATIBLE vs INCOMPATIBLE in the same query.
    SOFT -- Different ratings but same general direction.
    NONE -- No meaningful conflict.
    """

    HARD = "hard"
    SOFT = "soft"
    NONE = "none"


class Center(str, Enum):
    """NASA center identifier."""

    MSFC = "MSFC"
    JSC = "JSC"
    GRC = "GRC"
    KSC = "KSC"


# ---------------------------------------------------------------------------
# 2. Core Evidence Models
# ---------------------------------------------------------------------------


class SourceLocator(BaseModel):
    """Typed source location -- varies by ``source_type``.

    All fields are optional because different source types populate
    different subsets (e.g. a PDF has ``page`` and ``bbox``, a MAPTIS
    record has ``document_id`` and ``table``).
    """

    document_id: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None
    table: Optional[str] = None
    bbox: Optional[list[float]] = None  # [x0, y0, x1, y1]
    url: Optional[str] = None


class Excerpt(BaseModel):
    """Extracted text with optional character-span information."""

    text: str
    span_start: Optional[int] = None
    span_end: Optional[int] = None


class AtomicClaim(BaseModel):
    """Structured assertion anchored to evidence.

    Used by the fact checker to verify individual claims within a draft.
    ``qualifiers`` carries units, bounds, conditions, etc.
    """

    claim_type: ClaimType
    subject: str  # material_key / property / environment dimension
    value: Any  # typed per claim_type
    qualifiers: dict = Field(default_factory=dict)  # units, bounds, conditions


class EvidenceQuality(BaseModel):
    """Split quality scores for physics vs regulatory relevance.

    All scores default to ``0.0`` (unknown) rather than ``0.5`` (neutral)
    to ensure conservative treatment of missing information.
    """

    relevance_score: float = Field(0.0, ge=0.0, le=1.0)
    physics_relevance: float = Field(0.0, ge=0.0, le=1.0)
    regulatory_relevance: float = Field(0.0, ge=0.0, le=1.0)
    # ADDED Feb 2026: Fields from mua_precedents_v7 PG schema
    appendix_b_code: Optional[str] = None   # Legacy field name: stores Cat III rationale code (JSC 27301F Appendix E)
    closure_path: Optional[str] = None      # How this MUA was closed
    issues: list[str] = Field(default_factory=list)  # Issue codes (FLAM, SCC, HEE...)
    category_label: Optional[str] = None    # Cat I/II/III of the precedent itself
    search_tier: int = 0                    # Which PG search tier found this (0=best)
    authority_score: float = Field(0.0, ge=0.0, le=1.0)
    data_currency: float = Field(
        0.0, ge=0.0, le=1.0
    )  # current=1.0, expired=0.4, unknown=0.2
    regulatory_currency: float = Field(0.0, ge=0.0, le=1.0)
    completeness_score: float = Field(0.0, ge=0.0, le=1.0)
    conflicts_with: list[str] = Field(
        default_factory=list
    )  # evidence_ids of conflicting evidence


class EvidenceRef(BaseModel):
    """Unified evidence reference with two-tier identity.

    Tier A
        SHA-256 of canonical JSON payload (when full content is available).
    Tier B
        SHA-256 of ``"{source_type}:{primary_id}:{locator}:{span}"``
        (deterministic fallback when content is unavailable).
    """

    evidence_id: str  # Tier A or Tier B hash
    source_type: SourceType
    source_locator: SourceLocator
    excerpt: Optional[Excerpt] = None
    assertions: list[AtomicClaim] = Field(default_factory=list)
    quality: EvidenceQuality = Field(default_factory=EvidenceQuality)
    provenance_chain: Optional[list[str]] = None  # parent evidence_ids
    retrieved_at: Optional[datetime] = None

    @classmethod
    def compute_tier_a_id(cls, payload: dict) -> str:
        """Compute a content-addressed ID from a canonical JSON payload.

        Parameters
        ----------
        payload:
            Arbitrary dict whose canonical JSON will be hashed.

        Returns
        -------
        str
            Hex-encoded SHA-256 digest.
        """
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def compute_tier_b_id(
        cls,
        source_type: str,
        primary_id: str,
        locator: str = "",
        span: str = "",
    ) -> str:
        """Compute a deterministic ID from source metadata.

        Parameters
        ----------
        source_type:
            One of :class:`SourceType` values.
        primary_id:
            Primary identifier within the source (document number, etc.).
        locator:
            Optional locator string (section, page, etc.).
        span:
            Optional span information (character offsets, etc.).

        Returns
        -------
        str
            Hex-encoded SHA-256 digest.
        """
        key = f"{source_type}:{primary_id}:{locator}:{span}"
        return hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 3. Material & Environment Models
# ---------------------------------------------------------------------------


class MaterialResolution(BaseModel):
    """Result of material lookup resolution.

    ``status`` indicates the outcome of the resolution attempt:
    - RESOLVED: unambiguous match to a known MAPTIS code.
    - FUZZY: close match(es) found; engineer must confirm.
    - UNRESOLVED: no match; manual input required.

    ``is_process_sensitive`` triggers Step 1b (process parameter collection)
    for materials like adhesives, composites, potting compounds, and sealants.
    """

    input_text: str
    status: ResolutionStatus
    material_code: Optional[str] = None  # MAPTIS code as stored in DB (e.g. "10095")
    material_key: Optional[int] = None  # materials.material_key (integer PK)
    resolved_name: Optional[str] = None  # Canonical name e.g. "6061-T6 Aluminum"
    material_class: Optional[MaterialClass] = None
    family: Optional[str] = None  # e.g. "aluminum", "nickel_superalloy"
    suggestions: list[dict] = Field(default_factory=list)  # For fuzzy matches
    is_process_sensitive: bool = False  # Triggers Step 1b
    selection_method: Optional[str] = None  # lookup provenance (exact/uns/fuzzy/manual)
    selection_confidence: Optional[float] = None  # 0..1 score, if available


class MaterialCodeCandidate(BaseModel):
    """A MAPTIS candidate code associated with a canonical material identity."""

    material_code: str
    material_key: Optional[int] = None
    designation: str
    form: Optional[str] = None
    condition: Optional[str] = None
    relationship: RelationshipType = RelationshipType.FAMILY_MATCH
    match_score: float = Field(0.0, ge=0.0, le=1.0)
    rank: int = Field(0, ge=0)


class MaterialIdentity(BaseModel):
    """Step 1 material identity without forcing MAPTIS code selection."""

    input_text: str
    canonical_name: str
    family: Optional[str] = None
    material_class: Optional[MaterialClass] = None
    is_process_sensitive: bool = False
    form: Optional[str] = None
    condition: Optional[str] = None
    all_maptis_codes: list[MaterialCodeCandidate] = Field(default_factory=list)
    truncated: bool = False
    truncation_note: Optional[str] = None


class MaptisCodeRecommendation(BaseModel):
    """Evidence-based recommended MAPTIS code from Step 2 investigation."""

    recommended_code: str
    recommended_key: Optional[int] = None
    recommended_designation: str
    precedent_count: int = 0
    test_data_count: int = 0
    evidence_density_score: float = Field(0.0, ge=0.0, le=1.0)
    rationale: str = ""
    alternatives: list[dict] = Field(default_factory=list)


class EnvironmentSpec(BaseModel):
    """Environment definition with all required fields.

    Provides computed properties for common environment classifications
    used in routing and banner logic.
    """

    o2_percent: float = Field(..., ge=0.0, le=100.0)
    pressure_psia: float = Field(..., ge=0.0)
    temp_min_f: float = Field(...)
    temp_max_f: float = Field(...)
    medium: str  # Air, GOX, LOX, GH2, LH2, GN2, etc.
    location: str  # habitable, non_habitable, external
    application: str  # Free text describing use case

    @property
    def is_enriched_o2(self) -> bool:
        """True if oxygen concentration is at or above the enriched threshold (23.5 %)."""
        return self.o2_percent >= 23.5

    @property
    def is_cryogenic(self) -> bool:
        """True if minimum temperature qualifies as cryogenic (<= -150 degF)."""
        return self.temp_min_f <= -150.0

    @property
    def is_hydrogen_service(self) -> bool:
        """True if the medium is a hydrogen variant (GH2, LH2, or HYDROGEN)."""
        return self.medium.upper() in ("GH2", "LH2", "HYDROGEN")


class ProcessParams(BaseModel):
    """Process parameters for adhesives / composites / potting / sealants.

    Collected during Step 1b when ``MaterialResolution.is_process_sensitive``
    is ``True``.
    """

    cure_temp_f: Optional[float] = None
    cure_time_min: Optional[float] = None
    cure_pressure_psi: Optional[float] = None
    mix_ratio: Optional[str] = None
    layup_orientation: Optional[str] = None


# ---------------------------------------------------------------------------
# 4. Investigation Result Models
# ---------------------------------------------------------------------------


class PrecedentMatch(BaseModel):
    """A matched historic MUA with a relationship explanation.

    ``relationship_explanation`` is a plain-English description of how this
    precedent relates to the current query, intended for display to the
    reviewing engineer.
    """

    mua_number: str
    material_designation: str
    material_family: Optional[str] = None
    determination: DeterminationStatus
    environment_description: str
    o2_percent: Optional[float] = None
    pressure_psia: Optional[float] = None
    temp_min_f: Optional[float] = None
    temp_max_f: Optional[float] = None
    program: Optional[str] = None
    center: Optional[str] = None
    rationale_excerpt: Optional[str] = None
    relevance_score: float = Field(0.0, ge=0.0, le=1.0)
    is_supporting: bool = True
    is_conflicting: bool = False
    evidence_ref: Optional[EvidenceRef] = None
    relationship_explanation: str = ""  # Plain-English explanation of fit
    supporting_rationale: str = ""     # Why this precedent supports the case
    non_applicability_caveat: str = "" # Limitations / gaps / conflicting aspects
    physics_relevance: float = Field(0.0, ge=0.0, le=1.0)
    regulatory_relevance: float = Field(0.0, ge=0.0, le=1.0)

    # ADDED Feb 2026: PG search fields from mua_precedents_v7
    appendix_b_code: Optional[str] = None   # Legacy field name: stores Cat III rationale code (JSC 27301F Appendix E)
    closure_path: Optional[str] = None      # How this MUA was closed
    issues: list[str] = Field(default_factory=list)  # Issue codes (FLAM, SCC, HEE...)
    category_label: Optional[str] = None    # Cat I/II/III of the precedent itself
    search_tier: int = 0                    # Which PG search tier found this (0=best)
    relationship_type: Optional[RelationshipType] = None
    source_maptis_code: Optional[str] = None


class TestDataRecord(BaseModel):
    """MAPTIS test data record with currency information.

    ``is_current`` tri-state:
    - True: current (test data is valid).
    - False: expired (test data has been superseded or aged out).
    - None: unknown (currency cannot be determined).
    """

    test_class: str  # FLAMM, CORR, SCC, TVS, TOX, FS
    rating: Optional[str] = None  # A, B, C, D, U
    test_number: Optional[int] = None
    report_number: Optional[str] = None
    is_current: Optional[bool] = None  # True=current, False=expired, None=unknown
    test_date: Optional[str] = None
    test_medium: Optional[str] = None
    medium_match: Optional[bool] = None


class BOKFinding(BaseModel):
    """Body-of-Knowledge evidence hit for domain-specific safety context."""

    domain: str  # hydrogen | oxygen
    source: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None
    relevance_score: float = Field(0.0, ge=0.0, le=1.0)
    excerpt: str = ""


class EnvelopeResult(BaseModel):
    """Envelope overlap analysis result.

    Compares the queried environment against the tested envelope of a
    material across oxygen, pressure, and temperature dimensions.
    """

    overall_status: OverlapStatus
    o2_status: OverlapStatus = OverlapStatus.INSUFFICIENT_DATA
    pressure_status: OverlapStatus = OverlapStatus.INSUFFICIENT_DATA
    temp_status: OverlapStatus = OverlapStatus.INSUFFICIENT_DATA
    coverage_ratio: float = Field(0.0, ge=0.0, le=1.0)
    details: list[str] = Field(default_factory=list)


class GapIdentified(BaseModel):
    """A gap found during investigation.

    Represents a dimension (temperature, pressure, O2, toxicity, etc.)
    where available data does not cover the queried environment.
    """

    gap_id: str
    dimension: str  # temperature, pressure, o2, toxicity, etc.
    description: str
    severity: str  # critical, high, medium, low
    query_value: Optional[str] = None
    nearest_data: Optional[str] = None
    requires_review: bool = True


class ConflictFound(BaseModel):
    """A conflict between evidence sources.

    ``recommendation`` contains a plain-English suggestion for the
    reviewing engineer.
    """

    conflict_id: str
    severity: ConflictSeverity
    source_a: str  # evidence_id or description
    source_b: str
    description: str
    recommendation: str  # Plain-English recommendation


class DependencyWarning(BaseModel):
    """Warning about cited MUA dependencies.

    Alerts the engineer when a referenced MUA depends on another
    MUA whose status may affect the current determination.
    """

    cited_mua: str
    depends_on: str
    warning: str


class EvidenceStrengthResult(BaseModel):
    """Calculated evidence strength with component breakdown.

    ``band`` is the discrete band (strong / moderate / weak / insufficient).
    ``components`` provides the breakdown by scoring component.
    ``penalties`` records any applied penalty adjustments and their reasons.
    """

    score: float = Field(0.0, ge=0.0, le=1.0)
    band: EvidenceStrengthBand = EvidenceStrengthBand.INSUFFICIENT
    components: dict = Field(default_factory=dict)  # Breakdown by component
    penalties: dict = Field(default_factory=dict)  # Applied penalties
    explanation: str = ""


class InvestigationResult(BaseModel):
    """Complete result from Step 2: Investigate.

    Aggregates all evidence gathered, analysis results, and preliminary
    routing for the reviewing engineer.
    """

    material: MaterialResolution
    environment: EnvironmentSpec
    process_params: Optional[ProcessParams] = None

    # Evidence gathered
    supporting_precedents: list[PrecedentMatch] = Field(default_factory=list)
    conflicting_precedents: list[PrecedentMatch] = Field(default_factory=list)
    test_data: list[TestDataRecord] = Field(default_factory=list)
    bok_findings: list[BOKFinding] = Field(default_factory=list)
    envelope: Optional[EnvelopeResult] = None

    # Analysis
    conflicts: list[ConflictFound] = Field(default_factory=list)
    gaps: list[GapIdentified] = Field(default_factory=list)
    dependency_warnings: list[DependencyWarning] = Field(default_factory=list)
    evidence_strength: EvidenceStrengthResult = Field(
        default_factory=EvidenceStrengthResult
    )

    # Preliminary routing
    preliminary_category: Optional[MUACategory] = None
    banners: list[str] = Field(default_factory=list)  # Enriched O2, cryogenic, etc.

    # Novel material flag
    is_novel_material: bool = False
    material_identity: Optional[MaterialIdentity] = None
    code_recommendation: Optional[MaptisCodeRecommendation] = None


# ---------------------------------------------------------------------------
# 5. Review Decision Models
# ---------------------------------------------------------------------------


class PrecedentDecision(BaseModel):
    """Engineer's decision on a single precedent.

    ``rationale`` is required when the engineer diverges from the
    AI-suggested evidence strength band.
    """

    mua_number: str
    decision: ReviewDecisionType
    rationale: Optional[str] = None  # Required when diverging from AI band


class GapDecision(BaseModel):
    """Engineer's decision on a gap.

    ``rationale`` is always required for gap decisions since accepting
    or flagging a gap is a safety-significant judgment.
    """

    gap_id: str
    decision: GapDecisionType
    rationale: str  # Always required for gaps


class ConflictDecision(BaseModel):
    """Engineer's decision on a conflict."""

    conflict_id: str
    decision: ReviewDecisionType
    rationale: Optional[str] = None


class ReviewDecisions(BaseModel):
    """All engineer decisions from Step 3: Review.

    Divergence tracking fields are populated silently by the system
    when the engineer's selections differ materially from the
    AI-suggested rankings.
    """

    precedent_decisions: list[PrecedentDecision] = Field(default_factory=list)
    gap_decisions: list[GapDecision] = Field(default_factory=list)
    conflict_decisions: list[ConflictDecision] = Field(default_factory=list)
    all_items_reviewed: bool = False

    # Divergence tracking (silent)
    divergence_detected: bool = False
    divergence_rationale: Optional[str] = None
    confirmed_maptis_code: Optional[str] = None
    confirmed_maptis_key: Optional[int] = None
    confirmed_maptis_designation: Optional[str] = None
    override_justification: Optional[str] = None


# ---------------------------------------------------------------------------
# 6. Draft Models
# ---------------------------------------------------------------------------


class FactCheckResult(BaseModel):
    """Result of fact-checking a single claim in the draft.

    ``status`` values:
    - ``"verified"``: claim matches cited evidence.
    - ``"judgment"``: claim requires engineering judgment.
    - ``"unverified"``: claim could not be matched to evidence.
    - ``"error"``: fact-check process encountered an error.
    """

    claim_text: str
    claim_type: ClaimType
    status: str  # "verified", "judgment", "unverified", "error"
    evidence_id: Optional[str] = None
    note: Optional[str] = None


class DraftSection(BaseModel):
    """A single section of the MUA document.

    ``editable`` controls whether the engineer may modify this section
    (some boilerplate sections are read-only).
    """

    section_number: int
    title: str
    content: str
    editable: bool = True


class MUADraft(BaseModel):
    """Complete MUA draft from Step 4: Draft.

    ``full_text`` contains the rendered full document text suitable for
    export or display.
    """

    mua_id: str
    sections: list[DraftSection] = Field(default_factory=list)
    category: MUACategory
    evidence_strength: EvidenceStrengthResult
    fact_check_results: list[FactCheckResult] = Field(default_factory=list)
    cited_precedents: list[str] = Field(default_factory=list)
    full_text: str = ""  # Rendered full document text


class DraftEdit(BaseModel):
    """A single edit made to the draft by the engineer."""

    section_number: int
    original_text: str
    new_text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 7. Finalization Models
# ---------------------------------------------------------------------------


class CategoryRoutingResult(BaseModel):
    """Category routing result with full audit trail.

    ``routing_basis`` records each rule that fired during routing.
    ``authority_pack`` identifies the governing standard.
    """

    category: MUACategory
    routing_basis: list[dict] = Field(default_factory=list)  # rule hits
    required_approvals: list[str] = Field(default_factory=list)
    required_verifications: list[str] = Field(default_factory=list)
    authority_pack: str = "NASA-STD-6016C"
    authority_pack_version: str = ""
    # ADDED Feb 2026: Corrected 6016C output type routing
    output_type: Optional[dict] = None          # MUAOutputType: full_mua vs miul_rationale_code
    appendix_b_evaluation: Optional[dict] = None # Legacy field name: Cat III rationale-code evaluation (JSC 27301F Appendix E)


class FinalizedMUA(BaseModel):
    """Finalized MUA with full metadata.

    Represents the completed, immutable MUA record after engineer
    sign-off in Step 5: Finalize.
    """

    session_id: str
    mua_id: str
    material: MaterialResolution
    environment: EnvironmentSpec
    category: CategoryRoutingResult
    evidence_strength: EvidenceStrengthResult
    draft: MUADraft
    reviewer: str
    finalized_at: datetime
    applied_standard_version: str = "NASA-STD-6016C"
    dependency_links: list[str] = Field(default_factory=list)
    center: Center = Center.MSFC
    audit_trail: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 8. API Request / Response Models
# ---------------------------------------------------------------------------


class ResolveMaterialRequest(BaseModel):
    """Request to resolve a free-text material string."""

    material: str
    form: Optional[str] = None
    condition: Optional[str] = None


class ResolveMaterialResponse(BaseModel):
    """Response containing the material resolution result."""

    resolution: MaterialResolution
    identity: Optional[MaterialIdentity] = None


class InvestigateRequest(BaseModel):
    """Request to initiate Step 2: Investigate."""

    session_id: Optional[str] = None  # Auto-created if not provided
    material: str
    material_code: Optional[str] = None  # Optional explicit MAPTIS code chosen in HITL
    material_key: Optional[int] = None  # Optional explicit materials.material_key
    resolved_name: Optional[str] = None  # Optional explicit designation chosen in HITL
    form: Optional[str] = None
    condition: Optional[str] = None
    environment: EnvironmentSpec
    process_params: Optional[ProcessParams] = None
    issue_codes: Optional[list[str]] = None  # Engineer-selected MAPTIS issue codes (override auto-detection)
    approved_cat3_codes: Optional[list[str]] = None  # Category III rationale codes approved in the M&P plan (JSC 27301F Appendix E)
    program: Optional[str] = None
    hardware: Optional[str] = None
    miul_ref: Optional[str] = None
    center: Center = Center.MSFC


class InvestigateResponse(BaseModel):
    """Response containing the full investigation result."""

    session_id: str
    investigation: InvestigationResult


class SaveReviewRequest(BaseModel):
    """Request to save engineer review decisions (Step 3)."""

    session_id: str
    decisions: ReviewDecisions


class SaveReviewResponse(BaseModel):
    """Response confirming review save and draft readiness."""

    session_id: str
    can_generate_draft: bool
    unreviewed_count: int


class GenerateDraftRequest(BaseModel):
    """Request to generate the MUA draft (Step 4)."""

    session_id: str


class GenerateDraftResponse(BaseModel):
    """Response containing the generated MUA draft."""

    session_id: str
    draft: MUADraft


class FinalizeRequest(BaseModel):
    """Request to finalize the MUA (Step 5)."""

    session_id: str
    reviewer: str
    export_format: str = "text"


class FinalizeResponse(BaseModel):
    """Response containing the finalized MUA and optional export text."""

    session_id: str
    mua: FinalizedMUA
    export_text: Optional[str] = None


class QualificationPlanRequest(BaseModel):
    """Request to generate a qualification test plan for a novel material."""

    material: str
    environment: EnvironmentSpec


class QualificationPlanResponse(BaseModel):
    """Response containing the qualification test plan."""

    material: str
    required_tests: list[dict]
    recommended_conditions: list[dict]
    applicable_standards: list[str]
    output_text: str
