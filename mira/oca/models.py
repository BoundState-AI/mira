"""Pydantic models for the OCA workbench."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class OcaTier(str, Enum):
    TIER_A = "tier_a"
    TIER_B = "tier_b"
    TIER_C = "tier_c"
    TIER_D = "tier_d"


class RequirementStatus(str, Enum):
    NOT_TRIGGERED = "not_triggered"
    SATISFIED = "satisfied"
    ACTION_REQUIRED = "action_required"
    PROHIBITED = "prohibited"


class BlockedStateCode(str, Enum):
    MATERIAL_IDENTITY_UNRESOLVED = "MATERIAL_IDENTITY_UNRESOLVED"
    SERVICE_ENVELOPE_INCOMPLETE = "SERVICE_ENVELOPE_INCOMPLETE"
    DESIGN_FUNCTION_UNKNOWN = "DESIGN_FUNCTION_UNKNOWN"


class OxidizerType(str, Enum):
    LOX = "lox"
    GOX = "gox"
    ENRICHED_AIR = "enriched_air"
    COMPRESSED_AIR = "compressed_air"


class ServicePhase(str, Enum):
    LIQUID = "liquid"
    GAS = "gas"


class ComponentClass(str, Enum):
    VALVE = "valve"
    REGULATOR = "regulator"
    LINE = "line"
    VESSEL = "vessel"
    SEAL = "seal"
    FILTER = "filter"
    SENSOR = "sensor"
    FITTING = "fitting"
    FLEX_HOSE = "flex_hose"
    OTHER = "other"


class GeometryClass(str, Enum):
    BULK = "bulk"
    THIN_WALL = "thin_wall"
    MESH = "mesh"
    POROUS = "porous"
    SINTERED = "sintered"
    SEAL = "seal"
    OTHER = "other"


class FlowRegime(str, Enum):
    STATIC = "static"
    LAMINAR = "laminar"
    TURBULENT = "turbulent"


class FlammabilityRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    X = "X"
    U = "U"
    UNKNOWN = "unknown"


class IgnitionMechanismName(str, Enum):
    PARTICLE_IMPACT = "particle_impact"
    RAPID_PRESSURIZATION = "rapid_pressurization"
    FLOW_FRICTION = "flow_friction"
    RESONANCE = "resonance"
    MECHANICAL_IMPACT = "mechanical_impact"
    GALLING_FRICTION = "galling_friction"
    FRESH_METAL_EXPOSURE = "fresh_metal_exposure"
    STATIC_DISCHARGE = "static_discharge"
    ELECTRICAL_ARC = "electrical_arc"
    CHEMICAL_REACTION = "chemical_reaction"
    THERMAL_RUNAWAY = "thermal_runaway"
    LIGHTNING = "lightning"
    EXPLOSIVE_CHARGES = "explosive_charges"
    PERSONNEL_SMOKING_OPEN_FLAMES = "personnel_smoking_open_flames"
    FRAGMENTS_FROM_BURSTING_VESSELS = "fragments_from_bursting_vessels"
    WELDING = "welding"
    ENGINE_EXHAUST = "engine_exhaust"
    OTHER = "other"


class EvidenceApplicabilityClass(str, Enum):
    DIRECT = "DIRECT"
    PARTIAL = "PARTIAL"
    WEAK_ANALOG = "WEAK_ANALOG"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CredibleStatus(str, Enum):
    CREDIBLE = "CREDIBLE"
    NOT_CREDIBLE = "NOT_CREDIBLE"
    INDETERMINATE = "INDETERMINATE"


class FinalDisposition(str, Enum):
    COMPATIBLE_AS_CONFIGURED = "compatible_as_configured"
    COMPATIBLE_WITH_CONTROLS = "compatible_with_controls"
    REQUIRES_MUA = "requires_mua"
    REQUIRES_ACCEPTANCE_TEST = "requires_acceptance_test"
    REQUIRES_SUPPLEMENTAL_TESTING = "requires_supplemental_testing"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    PROHIBITED = "prohibited"


class ReactionEffect(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class MissionPhase(str, Enum):
    GROUND_TEST = "ground_test"
    FLIGHT = "flight"
    LAUNCH = "launch"
    OPERATIONS = "operations"


BlockedStateType = BlockedStateCode
OxygenPhase = ServicePhase
RuleTier = OcaTier
OCADisposition = FinalDisposition


def _default_blocked_state_resolution_hint(code: Optional[BlockedStateCode]) -> str:
    if code == BlockedStateCode.MATERIAL_IDENTITY_UNRESOLVED:
        return "Confirm canonical material identity before final disposition."
    if code == BlockedStateCode.SERVICE_ENVELOPE_INCOMPLETE:
        return "Populate all required service-envelope fields before assessment."
    if code == BlockedStateCode.DESIGN_FUNCTION_UNKNOWN:
        return "Provide component class, geometry, and design function for each assessed part."
    return "Resolve the blocked state before releasing the assessment."


def _default_blocked_state_severity(code: Optional[BlockedStateCode]) -> str:
    if code == BlockedStateCode.SERVICE_ENVELOPE_INCOMPLETE:
        return "red"
    return "amber"


def _normalize_ignition_mechanism_name(value: Any) -> Any:
    if isinstance(value, IgnitionMechanismName):
        return value
    if isinstance(value, str):
        normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        try:
            return IgnitionMechanismName(normalized)
        except ValueError:
            return IgnitionMechanismName.OTHER
    return value


class AuthoritySource(BaseModel):
    source_id: str
    title: str
    edition: str
    change_number: Optional[str] = None
    publication_date: str
    checksum: str
    ingest_date: str


class OcaAuthorityManifest(BaseModel):
    spec_id: str
    approved_on: str
    sources: list[AuthoritySource]


class OxygenServiceContextInput(BaseModel):
    oxidizer_type: OxidizerType = OxidizerType.GOX
    o2_fraction: Optional[float] = Field(default=None, ge=0.21, le=1.0)
    total_pressure_min_psia: Optional[float] = Field(default=None, ge=0.0)
    total_pressure_max_psia: Optional[float] = Field(default=None, ge=0.0)
    oxygen_partial_pressure_psia: Optional[float] = Field(default=None, ge=0.0)
    phase: Optional[ServicePhase] = None
    temp_min_c: Optional[float] = None
    temp_max_c: Optional[float] = None
    flow_regime: FlowRegime = FlowRegime.STATIC
    velocity_m_s: Optional[float] = Field(default=None, ge=0.0)
    cleanliness_verified: Optional[bool] = None
    contamination_notes: Optional[str] = None
    mission_phase: Optional[str] = None
    application: Optional[str] = None

    model_config = {"extra": "forbid"}


class OxygenServiceContext(OxygenServiceContextInput):
    case_id: str = ""


class ComponentInput(BaseModel):
    component_id: Optional[str] = None
    component_class: Optional[str] = None
    geometry_class: Optional[str] = None
    design_function: Optional[str] = None
    dynamic_contact_flag: bool = False
    is_rigid_metallic_tubing: bool = False
    is_metallic_flex_hose: bool = False
    is_all_metal_seal: bool = False
    is_metallic_pressure_vessel: bool = False
    seal_type: Optional[str] = None
    pressure_boundary_material: Optional[str] = None

    model_config = {"extra": "forbid"}


class ComponentInfo(ComponentInput):
    pass


class MaterialInput(BaseModel):
    material_name: str = Field(min_length=1)
    spec: Optional[str] = None
    grade: Optional[str] = None
    temper: Optional[str] = None
    product_form: Optional[str] = None
    coating: Optional[str] = None
    surface_condition: Optional[str] = None
    role_in_component: Optional[str] = None

    model_config = {"extra": "forbid"}


class MaterialInstance(BaseModel):
    material_name: str = Field(min_length=1)
    canonical_name: Optional[str] = None
    family: Optional[str] = None
    spec: Optional[str] = None
    grade: Optional[str] = None
    temper: Optional[str] = None
    product_form: Optional[str] = None
    coating: Optional[str] = None
    surface_condition: Optional[str] = None
    role_in_component: Optional[str] = None
    identity_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    flammability_rating: FlammabilityRating = FlammabilityRating.UNKNOWN
    is_titanium: bool = False
    is_nonmetal: bool = False
    o2_test_count: int = 0
    max_tested_pressure_psia: Optional[float] = None
    data_source: str = "legacy_phase2_input"


class IgnitionContextInput(BaseModel):
    entrainable_particles_present: Optional[bool] = None
    rapid_pressurization_time_ms: Optional[float] = Field(default=None, ge=0.0)
    dead_end_configuration: Optional[bool] = None
    nonmetal_exposed_to_flow: Optional[bool] = None
    vibration_or_erosion_present: Optional[bool] = None
    acoustic_cavity_present: Optional[bool] = None
    mechanical_impact_risk: Optional[bool] = None
    isolated_surface_present: Optional[bool] = None
    dry_gas_environment: Optional[bool] = None
    electrical_power_present: Optional[bool] = None
    reactive_chemical_pair_present: Optional[bool] = None
    porous_media_present: Optional[bool] = None
    open_flame_or_hot_work_present: Optional[bool] = None

    model_config = {"extra": "forbid"}


class CreateOcaCaseRequest(BaseModel):
    case_name: Optional[str] = None
    free_text_intake: Optional[str] = None
    service_context: OxygenServiceContextInput
    materials: list[MaterialInput] = Field(min_length=1)
    components: list[ComponentInput] = Field(default_factory=list)
    ignition_context: IgnitionContextInput = Field(default_factory=IgnitionContextInput)

    model_config = {"extra": "forbid"}


class ResolvedMaterial(BaseModel):
    material_name: str
    canonical_name: str
    family: str
    spec: Optional[str] = None
    grade: Optional[str] = None
    temper: Optional[str] = None
    product_form: Optional[str] = None
    coating: Optional[str] = None
    surface_condition: Optional[str] = None
    role_in_component: Optional[str] = None
    identity_confidence: float = Field(ge=0.0, le=1.0)
    synonym_list: list[str] = Field(default_factory=list)
    rating_flam: Optional[str] = None
    auto_ignition_temp_c: Optional[float] = None
    o2_test_count: int = 0
    max_tested_pressure_psia: Optional[float] = None
    data_source: str
    provenance_tier: str = "not_available"


class BlockedState(BaseModel):
    code: Optional[BlockedStateCode] = None
    detail: Optional[str] = None
    resolution_hint: Optional[str] = None
    severity: Optional[str] = None
    state_type: Optional[BlockedStateCode] = None
    description: Optional[str] = None
    missing_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_legacy_fields(self) -> "BlockedState":
        code = self.code or self.state_type
        detail = self.detail or self.description
        if code is None:
            raise ValueError("BlockedState requires code or state_type")
        if not detail:
            raise ValueError("BlockedState requires detail or description")
        self.code = code
        self.state_type = code
        self.detail = detail
        self.description = detail
        self.resolution_hint = self.resolution_hint or _default_blocked_state_resolution_hint(code)
        self.severity = self.severity or _default_blocked_state_severity(code)
        return self


class PrecheckWarning(BaseModel):
    code: str
    message: str


class NormalizedInput(BaseModel):
    service_context: OxygenServiceContextInput
    materials: list[ResolvedMaterial]
    components: list[ComponentInput]
    ignition_context: IgnitionContextInput


class TriggeredRequirement(BaseModel):
    requirement_id: str
    title: str
    citation: str
    tier: OcaTier
    triggered: bool
    status: RequirementStatus
    reasoning: str
    evidence_links: list[str] = Field(default_factory=list)
    downstream_actions: list[str] = Field(default_factory=list)
    satisfied: bool = False
    is_prohibition: bool = False
    prohibition_detail: Optional[str] = None

    @model_validator(mode="after")
    def _sync_legacy_flags(self) -> "TriggeredRequirement":
        self.satisfied = self.status == RequirementStatus.SATISFIED
        self.is_prohibition = self.status == RequirementStatus.PROHIBITED
        self.prohibition_detail = self.reasoning if self.is_prohibition else None
        return self


class EvidenceApplicabilityScore(BaseModel):
    exact_material_match: bool
    spec_match: bool
    form_match: bool
    geometry_match: bool
    pressure_match: bool
    o2_fraction_match: bool
    phase_match: bool
    temperature_match: bool
    coating_match: bool
    method_relevance: bool
    aggregate_score: float = Field(ge=0.0, le=1.0)
    applicability_class: EvidenceApplicabilityClass


class EvidenceCard(BaseModel):
    evidence_id: str
    material_name: str
    source_id: str
    title: str
    citation: str
    tier: OcaTier
    summary: str
    test_method: Optional[str] = None
    specimen_description: Optional[str] = None
    test_conditions: Optional[str] = None
    result: Optional[str] = None
    applicability: EvidenceApplicabilityScore
    gaps: list[str] = Field(default_factory=list)


class MechanismTrace(BaseModel):
    mechanism_name: IgnitionMechanismName
    source_ref: str
    required_elements: list[str]
    observed_elements: list[str]
    missing_elements: list[str]
    rating_formula_version: str
    rating_result: int = Field(ge=0, le=4)
    reviewer_comments: list[str] = Field(default_factory=list)

    @field_validator("mechanism_name", mode="before")
    @classmethod
    def _validate_mechanism_name(cls, value: Any) -> Any:
        return _normalize_ignition_mechanism_name(value)


class MechanismAssessment(BaseModel):
    mechanism_name: IgnitionMechanismName
    credible_status: CredibleStatus
    rating: int = Field(ge=0, le=4)
    source_ref: str
    required_elements: list[str]
    observed_elements: list[str]
    missing_elements: list[str]
    linked_evidence_ids: list[str] = Field(default_factory=list)
    gaps_identified: list[str] = Field(default_factory=list)
    reviewer_comments: list[str] = Field(default_factory=list)
    mechanism_trace: MechanismTrace

    @field_validator("mechanism_name", mode="before")
    @classmethod
    def _validate_mechanism_name(cls, value: Any) -> Any:
        return _normalize_ignition_mechanism_name(value)


class HazardControlEntry(BaseModel):
    component_ref: str = ""
    ignition_hazard: str
    probability_rating: int = Field(default=1, ge=1, le=4)
    recommendation: str
    confidence: str = "medium"


class KindlingChainResult(BaseModel):
    kindling_chain_present: bool = False
    reaction_effect: ReactionEffect = ReactionEffect.A
    history_of_use: str = "unknown"
    propagation_notes: list[str] = Field(default_factory=list)


class MUASeed(BaseModel):
    material_names: list[str] = Field(default_factory=list)
    service_conditions: dict[str, Any] = Field(default_factory=dict)
    mechanism_summary: list[dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    recommended_disposition: Optional[OCADisposition] = None
    notes: list[str] = Field(default_factory=list)


class DecisionAction(BaseModel):
    action_id: str
    label: str
    rationale: str


class OcaDecisionPacket(BaseModel):
    case_id: str
    final_disposition: FinalDisposition
    triggered_requirements: list[TriggeredRequirement]
    blocked_states: list[BlockedState]
    unresolved_gaps: list[str]
    kindling_chain_present: bool = False
    reaction_effect: Optional[str] = None
    history_of_use: str = "?"
    mua_seed: dict[str, Any] = Field(default_factory=dict)
    acceptance_test_required: bool = False
    reviewer_required: bool = False
    overall_confidence: str
    authority_level: OcaTier
    governing_prohibition: Optional[str] = None
    summary_rationale: str
    actions: list[DecisionAction] = Field(default_factory=list)
    provenance_warning: Optional[str] = None


OCADecisionPacket = OcaDecisionPacket


class RuleTraceEvent(BaseModel):
    stage: str
    rule_id: str
    tier: OcaTier
    outcome: str
    detail: str
    recorded_at: datetime = Field(default_factory=datetime.utcnow)


class OcaRevision(BaseModel):
    revision: int
    created_at: datetime
    note: str


class AssessmentSnapshot(BaseModel):
    case_id: str
    revision: int
    created_at: datetime
    normalized_input: NormalizedInput
    blocked_states: list[BlockedState]
    precheck_warnings: list[PrecheckWarning]
    requirements: list[TriggeredRequirement]
    evidence: list[EvidenceCard]
    mechanisms: list[MechanismAssessment]
    decision: OcaDecisionPacket
    decision_lineage: list[RuleTraceEvent]
    revisions: list[OcaRevision]


class CreateOcaCaseResponse(BaseModel):
    case_id: str
    revision: int
    normalized_input: NormalizedInput
    blocked_states: list[BlockedState]
    precheck_warnings: list[PrecheckWarning]


class OcaPrecheckResponse(BaseModel):
    case_id: str
    revision: int
    blocked_states: list[BlockedState]
    triggered_requirements: list[TriggeredRequirement]
    precheck_warnings: list[PrecheckWarning]


class OcaEvidenceResponse(BaseModel):
    case_id: str
    revision: int
    evidence: list[EvidenceCard]
    gaps: list[str]


class OcaMechanismsResponse(BaseModel):
    case_id: str
    revision: int
    mechanisms: list[MechanismAssessment]


class OcaDecisionResponse(BaseModel):
    case_id: str
    revision: int
    decision: OcaDecisionPacket


class OcaRequirementsResponse(BaseModel):
    case_id: str
    revision: int
    requirements: list[TriggeredRequirement]


class OcaLineageResponse(BaseModel):
    case_id: str
    revision: int
    revisions: list[OcaRevision]
    decision_lineage: list[RuleTraceEvent]


class OcaExportArtifact(BaseModel):
    artifact_type: str
    filename: str
    content_type: str
    generated_text: str


class OcaExportResponse(BaseModel):
    case_id: str
    revision: int
    artifacts: list[OcaExportArtifact]
