"""
M&P Plan Generator - Core Session Models V2.

Implements Fran's corrections:
- Multi-environment support
- Deficiency vs Nonconformance split
- Decision graph for dependency tracking
- Computation context with full hashes
- Evidence refs (structured, not free-text)

Compliance: SWE-013 (traceability), SWE-033 (data persistence).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "SourceType",
    "EvidenceRef",
    "EnvironmentDefinition",
    "MaterialEnvironmentUsage",
    "HardwareContext",
    "MaterialEntry",
    "MaterialResolutionResult",
    "COTSItem",
    "OrgChart",
    "DeficiencySignal",
    "NonconformanceSignal",
    "GapSeverity",
    "FailureMode",
    "OperationalConstraint",
    "ClosureDecision",
    "AcceptedOpenGap",
    "DraftTextBox",
    "DecisionNode",
    "DecisionEdge",
    "DecisionGraph",
    "ComputationContext",
    "BlockingQuestion",
    "BlockingQuestionType",
    "UserDecision",
    "GeneratedArtifact",
    "ArtifactType",
    "PlanGeneratorSession",
]

__safety_critical__ = False


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class SourceType(str, Enum):
    """Evidence source types."""
    STANDARD = "standard"
    MAPTIS = "maptis"
    TEST_REPORT = "test_report"
    ANALYSIS = "analysis"
    BOK = "bok"
    PRECEDENT = "precedent"
    POLICY_PACK = "policy_pack"


class GapSeverity(str, Enum):
    """Gap severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FailureMode(str, Enum):
    """Failure mode types."""
    FLAM = "flam"
    HEE = "hee"
    TVS = "tvs"
    TOX = "tox"
    SCC = "scc"
    GALVANIC = "galvanic"
    OFFGAS = "offgas"


class BlockingQuestionType(str, Enum):
    """Blocking question types."""
    MATERIAL_AMBIGUOUS = "material_ambiguous"
    ENVIRONMENT_MISSING = "environment_missing"
    QUANTITY_MISSING = "quantity_missing"
    STRUCTURAL_UNCLEAR = "structural_unclear"
    COTS_CRITICALITY = "cots_criticality"
    CLOSURE_SELECTION = "closure_selection"
    TAILORING_APPROVAL = "tailoring_approval"
    PRECEDENT_VALIDATION = "precedent_validation"
    GROUPING_CONFIRMATION = "grouping_confirmation"


class ArtifactType(str, Enum):
    """Output artifact types."""
    MP_PLAN_DOCX = "mp_plan_docx"
    MIUL_XLSX = "miul_xlsx"
    APPLICABILITY_MATRIX_XLSX = "applicability_matrix_xlsx"
    MUA_DOCX = "mua_docx"
    GAP_REPORT_JSON = "gap_report_json"
    RUN_MANIFEST_JSON = "run_manifest_json"
    AUDIT_TRAIL_JSON = "audit_trail_json"
    REVIEW_PACKET_JSON = "review_packet_json"


# -----------------------------------------------------------------------------
# Evidence Reference (Fran Fix #3)
# -----------------------------------------------------------------------------

class EvidenceRef(BaseModel):
    """
    Structured evidence reference for auditability.

    Not free text - must resolve to authoritative source.

    Compliance: SWE-033 (evidence traceability).
    """
    source_type: SourceType
    document_id: str
    revision: str

    section: Optional[str] = None
    paragraph_id: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None
    table_id: Optional[str] = None
    figure_id: Optional[str] = None

    extracted_text: Optional[str] = None
    extracted_text_hash: Optional[str] = None

    url_or_path: Optional[str] = None

    retrieved_at: datetime = Field(default_factory=datetime.now)
    retrieval_method: str = "manual"

    model_config = {"extra": "forbid", "populate_by_name": True}

    def to_citation(self) -> str:
        """Generate citation string for display."""
        parts = [self.document_id]
        if self.revision:
            parts.append(self.revision)
        if self.section:
            parts.append(f"§{self.section}")
        if self.paragraph_id:
            parts.append(self.paragraph_id)
        return ", ".join(parts)


# -----------------------------------------------------------------------------
# Environment (Fran Fix #2 - Multi-environment)
# -----------------------------------------------------------------------------

class EnvironmentDefinition(BaseModel):
    """
    Single environment zone.

    V2: Session has list of environments, not single environment.

    Compliance: SWE-033 (environmental requirements).
    """
    environment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str

    o2_pct: float = Field(..., gt=0, le=100)
    pressure_psia: float = Field(..., gt=0)
    temp_range_c: tuple[float, float]
    habitable: bool
    vacuum_exposure: bool = False
    lunar_dust: bool = False

    phase: str = "nominal"

    source_evidence: Optional[EvidenceRef] = None
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def validate_temp_range(self) -> EnvironmentDefinition:
        """Ensure min temp < max temp."""
        if self.temp_range_c[0] >= self.temp_range_c[1]:
            raise ValueError("Min temp must be less than max temp")
        return self


class MaterialEnvironmentUsage(BaseModel):
    """
    Material usage in specific environment.

    V2: Links material to environment with adjacency info for aggregation.

    Compliance: SWE-033 (usage context).
    """
    material_id: str
    environment_id: str

    location: str

    continuous_exposure: bool = True
    exposure_duration_hours: Optional[float] = None

    adjacency_group: Optional[str] = None
    ignition_source_proximity: Optional[str] = None

    model_config = {"extra": "forbid", "populate_by_name": True}


# -----------------------------------------------------------------------------
# Hardware and Materials
# -----------------------------------------------------------------------------

class HardwareContext(BaseModel):
    """Hardware specifics driving applicability."""
    hardware_type: str
    crew_contact: bool
    ignition_sources: list[str] = Field(default_factory=list)
    cots_flags: dict[str, bool] = Field(default_factory=dict)
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class MaterialEntry(BaseModel):
    """Canonical material entry."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    application: str
    quantity: int
    mass_g: Optional[float] = None
    surface_area_cm2: Optional[float] = None
    spec: Optional[str] = None
    maptis_code: Optional[str] = None
    location: Optional[str] = None
    function: Optional[str] = None
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class MaterialResolutionResult(BaseModel):
    """MAPTIS resolution output."""
    material_id: str
    maptis_code: str
    flam_rating: str
    tvs_rating: str
    tox_rating: str
    test_o2_pct: float
    test_pressure_psia: Optional[float] = None
    test_temp_c: Optional[float] = None
    test_report_ref: Optional[str] = None
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class COTSItem(BaseModel):
    """COTS component details."""
    name: str
    is_mission_critical: bool
    rationale: str
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class OrgChart(BaseModel):
    """Organization structure."""
    lead_org: str
    technical_authority: str
    panel_members: list[dict[str, str]]
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


# -----------------------------------------------------------------------------
# Gap Types (Fran Fix #7 - Split Deficiency vs Nonconformance)
# -----------------------------------------------------------------------------

class DeficiencySignal(BaseModel):
    """
    Missing input or evidence that blocks a decision.

    Not a compliance failure - we just can't determine compliance yet.

    Compliance: SWE-013 (gap tracking).
    """
    deficiency_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    deficiency_type: str

    missing_field: str
    missing_for: str

    material_id: Optional[str] = None
    environment_id: Optional[str] = None

    blocked_decision_ids: list[str] = Field(default_factory=list)

    conservative_default_available: bool = False
    conservative_default_value: Optional[Any] = None
    conservative_default_rationale: Optional[str] = None

    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class NonconformanceSignal(BaseModel):
    """
    Evidence indicates material/process doesn't meet requirement.

    Requires closure path selection.

    Compliance: SWE-013 (nonconformance tracking).
    """
    nonconformance_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    gap_type: FailureMode

    failing_requirement: str
    failing_value: Optional[str] = None
    required_value: Optional[str] = None

    material_id: str
    environment_id: str

    affected_mprs: list[str] = Field(default_factory=list)

    severity: GapSeverity
    confidence: float = Field(..., ge=0, le=1)

    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    source_adapter: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class OperationalConstraint(BaseModel):
    """Derived constraint from evaluation."""
    constraint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    affected_material: Optional[str] = None
    source_gap: Optional[str] = None
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


# -----------------------------------------------------------------------------
# Closure (Fran Fix #8 - Accepted Open Gaps)
# -----------------------------------------------------------------------------

class ClosureDecision(BaseModel):
    """User closure choice."""
    gap_id: str
    selected_path: str
    provided_inputs: dict[str, Any]
    decision_rationale: str
    decided_by: str
    decided_at: datetime
    available_options: list[dict[str, Any]]
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class AcceptedOpenGap(BaseModel):
    """
    Gap accepted as open for generation.

    V2: Allows plan generation with known open items.

    Compliance: SWE-013 (acceptance tracking).
    """
    gap_id: str
    gap_type: str

    accepted_by: str
    accepted_at: datetime
    acceptance_rationale: str

    owner: str
    due_date: date
    risk_statement: str

    flag_in_output: bool = True

    model_config = {"extra": "forbid", "populate_by_name": True}


# -----------------------------------------------------------------------------
# LLM Output Isolation (Fran Fix #11)
# -----------------------------------------------------------------------------

class DraftTextBox(BaseModel):
    """
    LLM-generated text in isolated container.

    This type is NEVER used as input to any decision logic.

    Compliance: SWE-013 (LLM isolation).
    """
    box_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    draft_type: str
    content: str

    prompt_template_id: str
    prompt_hash: str
    model_id: str
    inputs_hash: str

    generated_at: datetime = Field(default_factory=datetime.now)

    is_authoritative: bool = False
    requires_human_review: bool = True

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def enforce_non_authoritative(self) -> DraftTextBox:
        """Enforce that drafts are never authoritative."""
        if self.is_authoritative:
            raise ValueError("DraftTextBox can never be authoritative")
        if not self.requires_human_review:
            raise ValueError("DraftTextBox always requires human review")
        return self


# -----------------------------------------------------------------------------
# Decision Graph (Fran Fix #5, #12)
# -----------------------------------------------------------------------------

class DecisionNode(BaseModel):
    """Node in decision graph."""
    node_id: str
    node_type: str
    object_id: str
    object_type: str

    depends_on: list[str] = Field(default_factory=list)
    derived_from_fields: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid", "populate_by_name": True}


class DecisionEdge(BaseModel):
    """Edge in decision graph."""
    from_node: str
    to_node: str
    edge_type: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class DecisionGraph(BaseModel):
    """
    Explicit dependency graph for recompute.

    Fran: 'This is what makes recompute correct and explainable.'

    Compliance: SWE-013 (dependency tracking).
    """
    nodes: dict[str, DecisionNode] = Field(default_factory=dict)
    edges: list[DecisionEdge] = Field(default_factory=list)

    model_config = {"extra": "forbid", "populate_by_name": True}

    def get_invalidated_by(self, changed_field: str) -> list[str]:
        """Get all nodes invalidated by a field change."""
        affected = []
        for node_id, node in self.nodes.items():
            if changed_field in node.derived_from_fields:
                affected.append(node_id)
                affected.extend(self._get_dependents(node_id))
        return list(set(affected))

    def _get_dependents(self, node_id: str) -> list[str]:
        """Get all nodes that depend on this node."""
        dependents = []
        for edge in self.edges:
            if edge.from_node == node_id and edge.edge_type == "depends_on":
                dependents.append(edge.to_node)
                dependents.extend(self._get_dependents(edge.to_node))
        return dependents

    def add_node(
        self,
        node_type: str,
        object_id: str,
        object_type: str,
        depends_on: Optional[list[str]] = None,
        derived_from_fields: Optional[list[str]] = None,
    ) -> str:
        """Add a node to the graph."""
        node_id = f"{node_type}:{object_id}"
        self.nodes[node_id] = DecisionNode(
            node_id=node_id,
            node_type=node_type,
            object_id=object_id,
            object_type=object_type,
            depends_on=depends_on or [],
            derived_from_fields=derived_from_fields or [],
        )
        return node_id

    def add_edge(self, from_node: str, to_node: str, edge_type: str) -> None:
        """Add an edge to the graph."""
        self.edges.append(DecisionEdge(
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_type,
        ))


# -----------------------------------------------------------------------------
# Computation Context (Fran Fix #10)
# -----------------------------------------------------------------------------

class ComputationContext(BaseModel):
    """
    All version information needed for cache validation.

    Compliance: SWE-013 (reproducibility).
    """
    mpr_index_hash: str
    mpr_index_version: str
    mpr_count: int

    policy_pack_hash: str
    policy_pack_version: str

    maptis_dataset_version: str
    maptis_dataset_hash: str

    code_version: str
    code_branch: str

    computed_at: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "forbid", "populate_by_name": True}

    def compute_cache_key(self) -> str:
        """Compute cache key from all components."""
        components = [
            self.mpr_index_hash,
            self.policy_pack_hash,
            self.maptis_dataset_hash,
            self.code_version,
        ]
        return hashlib.sha256("|".join(components).encode()).hexdigest()


# -----------------------------------------------------------------------------
# Blocking Questions and Decisions
# -----------------------------------------------------------------------------

class BlockingQuestion(BaseModel):
    """Blocking question."""
    question_id: str
    question_type: BlockingQuestionType
    question_text: str
    context: str

    blocked_decisions: list[str]

    options: list[str] = Field(default_factory=list)
    default_option: Optional[str] = None
    required: bool = True
    validator: Optional[str] = None

    source_gap_id: Optional[str] = None
    source_mpr: Optional[str] = None

    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class UserDecision(BaseModel):
    """Logged user decision."""
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_id: str
    decision: str
    rationale: str
    decided_by: str
    decided_at: datetime = Field(default_factory=datetime.now)
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


class GeneratedArtifact(BaseModel):
    """Generated file record."""
    artifact_type: ArtifactType
    filename: str
    filepath: str
    generated_at: datetime
    content_hash: str
    source_session_hash: str
    material_id: Optional[str] = None
    mua_category: Optional[str] = None
    source: str

    model_config = {"extra": "forbid", "populate_by_name": True}


# -----------------------------------------------------------------------------
# Main Session Model
# -----------------------------------------------------------------------------

class PlanGeneratorSession(BaseModel):
    """
    Complete session state V2.

    Changes from V1:
    - Multi-environment support
    - Split gap types (deficiency vs nonconformance)
    - Accepted open gaps
    - Decision graph
    - Policy pack reference
    - Computation context with full hashes

    Compliance: SWE-013 (traceability), SWE-033 (persistence).
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    # Identity
    session_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    source: str = "interactive_session"

    # Program context
    program_name: Optional[str] = None
    program_phase: Optional[str] = None
    lead_organization: Optional[str] = None

    # Policy pack (V2)
    policy_pack_id: Optional[str] = None

    # Environments (V2 - list, not single)
    environments: list[EnvironmentDefinition] = Field(default_factory=list)

    # Hardware context
    hardware_context: Optional[HardwareContext] = None

    # Materials
    materials: list[MaterialEntry] = Field(default_factory=list)
    maptis_resolutions: list[MaterialResolutionResult] = Field(default_factory=list)

    # Material-environment mappings (V2)
    material_environment_usages: list[MaterialEnvironmentUsage] = Field(default_factory=list)

    # COTS assessment
    cots_items: list[COTSItem] = Field(default_factory=list)

    # Organization
    org_chart: Optional[OrgChart] = None

    # Applicability (dict: mpr_id -> decision dict)
    applicability_matrix: Optional[dict[str, dict[str, Any]]] = None

    # Compliance
    mpr_determinations: list[dict[str, Any]] = Field(default_factory=list)

    # Gaps (V2 - split types)
    deficiencies: list[DeficiencySignal] = Field(default_factory=list)
    nonconformances: list[NonconformanceSignal] = Field(default_factory=list)

    # Constraints
    constraints: list[OperationalConstraint] = Field(default_factory=list)

    # Closure
    closure_decisions: list[ClosureDecision] = Field(default_factory=list)

    # Accepted open gaps (V2)
    accepted_open_gaps: list[AcceptedOpenGap] = Field(default_factory=list)

    # Draft text boxes (V2 - isolated from decisions)
    draft_text_boxes: list[DraftTextBox] = Field(default_factory=list)

    # Blocking questions
    blocking_questions: list[BlockingQuestion] = Field(default_factory=list)

    # User decisions
    user_decisions: list[UserDecision] = Field(default_factory=list)

    # Decision graph (V2)
    decision_graph: Optional[DecisionGraph] = None

    # Computation context (V2)
    computation_context: Optional[ComputationContext] = None

    # Generated artifacts
    generated_artifacts: list[GeneratedArtifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_session(self) -> PlanGeneratorSession:
        """Validate session consistency."""
        # Check closure decisions reference valid gaps
        nonconformance_ids = {n.nonconformance_id for n in self.nonconformances}
        for decision in self.closure_decisions:
            if decision.gap_id not in nonconformance_ids:
                raise ValueError(f"Closure decision for unknown gap: {decision.gap_id}")

        # Check accepted open gaps reference valid gaps
        deficiency_ids = {d.deficiency_id for d in self.deficiencies}
        all_gap_ids = nonconformance_ids | deficiency_ids
        for accepted in self.accepted_open_gaps:
            if accepted.gap_id not in all_gap_ids:
                raise ValueError(f"Accepted open gap unknown: {accepted.gap_id}")

        return self

    def can_generate(self) -> tuple[bool, list[str]]:
        """
        Check if session is ready for artifact generation.

        V2: Allows generation with accepted open gaps.

        Returns:
            Tuple of (can_generate, list of blockers).
        """
        blockers = []

        if not self.environments:
            blockers.append("No environments defined")

        if not self.materials:
            blockers.append("No materials entered")

        # Check for unresolved materials
        resolved_ids = {r.material_id for r in self.maptis_resolutions}
        unresolved = [m for m in self.materials if m.id not in resolved_ids]
        if unresolved:
            blockers.append(f"{len(unresolved)} materials not resolved in MAPTIS")

        # Check for blocking deficiencies (without conservative default)
        blocking_deficiencies = [
            d for d in self.deficiencies if not d.conservative_default_available
        ]
        if blocking_deficiencies:
            blockers.append(f"{len(blocking_deficiencies)} blocking deficiencies")

        # V2: Nonconformances need closure OR acceptance
        closed_ids = {d.gap_id for d in self.closure_decisions}
        accepted_ids = {a.gap_id for a in self.accepted_open_gaps}
        open_nonconformances = [
            n
            for n in self.nonconformances
            if n.nonconformance_id not in closed_ids
            and n.nonconformance_id not in accepted_ids
        ]
        if open_nonconformances:
            blockers.append(
                f"{len(open_nonconformances)} nonconformances without closure or acceptance"
            )

        return len(blockers) == 0, blockers

    def get_environment(self, environment_id: str) -> Optional[EnvironmentDefinition]:
        """Get environment by ID."""
        for env in self.environments:
            if env.environment_id == environment_id:
                return env
        return None

    def get_material(self, material_id: str) -> Optional[MaterialEntry]:
        """Get material by ID."""
        for mat in self.materials:
            if mat.id == material_id:
                return mat
        return None
