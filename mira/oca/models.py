#!/usr/bin/env python3
"""
Module: OCA Models
Purpose: Pydantic data models for the OCA engine per BS-SPEC-OCA-001-REV1.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6001B, NASA-STD-6016C, SWE-013
Safety Critical: True
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RuleTier(str, Enum):
    """Four-tier rule architecture. Tiers never blend."""
    A = "A"  # Governing requirements (MPRs, FOCRs)
    B = "B"  # Assessment method (TM-2007-213740)
    C = "C"  # Evidence layer (test data, MAPTIS)
    D = "D"  # Expert overlay (center practice, heuristics)


class OxidizerType(str, Enum):
    LOX = "lox"
    GOX = "gox"
    ENRICHED_AIR = "enriched_air"
    COMPRESSED_AIR = "compressed_air"


class OxygenPhase(str, Enum):
    LIQUID = "liquid"
    GAS = "gas"


class FlowRegime(str, Enum):
    STATIC = "static"
    LAMINAR = "laminar"
    TURBULENT = "turbulent"


class MissionPhase(str, Enum):
    GROUND_TEST = "ground_test"
    ASCENT = "ascent"
    ON_ORBIT = "on_orbit"
    SERVICING = "servicing"


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


class SealType(str, Enum):
    METAL = "metal"
    POLYMER = "polymer"
    COMPOSITE = "composite"


class FlammabilityRating(str, Enum):
    """NASA-STD-6001B flammability rating."""
    A = "A"  # Nonflammable in configuration
    B = "B"  # Self-extinguishing
    C = "C"  # Flammable, burns slowly
    D = "D"  # Flammable, burns rapidly
    X = "X"  # Not tested / unknown
    UNKNOWN = "unknown"


class IgnitionMechanismName(str, Enum):
    """12 ignition mechanisms per TM-2007-213740 Section 4.3.1."""
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
    OTHER = "other"


class CredibleStatus(str, Enum):
    CREDIBLE = "credible"
    NOT_CREDIBLE = "not_credible"
    INDETERMINATE = "indeterminate"


class ReactionEffect(str, Enum):
    """TM Table 3 reaction effect severity."""
    A = "A"  # Negligible
    B = "B"  # Marginal
    C = "C"  # Critical
    D = "D"  # Catastrophic


class HistoryOfUse(str, Enum):
    POSITIVE = "+"
    NEGATIVE = "-"
    UNKNOWN = "?"


class ApplicabilityClass(str, Enum):
    DIRECT = "directly_applicable"
    PARTIAL = "partially_applicable"
    WEAK_ANALOG = "weak_analog"
    NOT_APPLICABLE = "not_applicable"


class BlockedStateType(str, Enum):
    MATERIAL_IDENTITY_UNRESOLVED = "material_identity_unresolved"
    SERVICE_ENVELOPE_INCOMPLETE = "service_envelope_incomplete"
    DESIGN_FUNCTION_UNKNOWN = "design_function_unknown"


class OCADisposition(str, Enum):
    COMPATIBLE_AS_CONFIGURED = "compatible_as_configured"
    COMPATIBLE_WITH_CONTROLS = "compatible_with_controls"
    REQUIRES_MUA = "requires_mua"
    REQUIRES_ACCEPTANCE_TEST = "requires_acceptance_test"
    REQUIRES_SUPPLEMENTAL_TESTING = "requires_supplemental_testing"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RecommendationClass(str, Enum):
    STANDARDS_DERIVED = "standards_derived"
    PRECEDENT_DERIVED = "precedent_derived"
    HEURISTIC = "heuristic"
    REVIEWER_ENTERED = "reviewer_entered"


# ---------------------------------------------------------------------------
# Domain Models — per Spec §9
# ---------------------------------------------------------------------------

class OxygenServiceContext(BaseModel):
    """Service context for the OCA case (Spec §9)."""
    case_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    oxidizer_type: OxidizerType = OxidizerType.GOX
    o2_fraction: float = Field(default=1.0, ge=0.21, le=1.0)
    total_pressure_min_psia: float = Field(default=14.7, ge=0)
    total_pressure_max_psia: float = Field(default=14.7, ge=0)
    oxygen_partial_pressure_psia: Optional[float] = None
    phase: OxygenPhase = OxygenPhase.GAS
    temp_min_c: Optional[float] = None
    temp_max_c: Optional[float] = None
    flow_regime: FlowRegime = FlowRegime.STATIC
    velocity_m_s: Optional[float] = None
    cleanliness_verified: bool = False
    contamination_notes: Optional[str] = None
    mission_phase: MissionPhase = MissionPhase.GROUND_TEST

    def compute_o2_partial_pressure(self) -> float:
        """Auto-compute O2 partial pressure from max total pressure * fraction."""
        return self.total_pressure_max_psia * self.o2_fraction


class ComponentInfo(BaseModel):
    """Component descriptor with MPR 53 exemption fields (Spec §9)."""
    component_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    component_class: ComponentClass = ComponentClass.OTHER
    geometry_class: GeometryClass = GeometryClass.BULK
    dynamic_contact_flag: bool = False
    is_rigid_metallic_tubing: bool = False
    is_metallic_flex_hose: bool = False
    is_all_metal_seal: bool = False
    is_metallic_pressure_vessel: bool = False
    seal_type: Optional[SealType] = None
    pressure_boundary_material: Optional[str] = None
    acceptance_test_exemption_class: Optional[str] = None


class MaterialInstance(BaseModel):
    """Material identity with alias resolution (Spec §9)."""
    material_instance_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    material_name: str
    canonical_name: Optional[str] = None
    spec: Optional[str] = None
    grade: Optional[str] = None
    temper: Optional[str] = None
    product_form: Optional[str] = None
    coating: Optional[str] = None
    surface_condition: Optional[str] = None
    role_in_component: Optional[str] = None
    identity_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    synonym_list: list[str] = Field(default_factory=list)
    flammability_rating: FlammabilityRating = FlammabilityRating.UNKNOWN
    is_titanium: bool = False
    is_nonmetal: bool = False


class EvidenceApplicabilityScore(BaseModel):
    """Applicability scoring for a single evidence object (Spec §7)."""
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    exact_material_match: bool = False
    spec_match: bool = False
    form_match: bool = False
    geometry_match: bool = False
    pressure_match: bool = False
    o2_match: bool = False
    phase_match: bool = False
    temperature_match: bool = False
    coating_match: bool = False
    method_relevance: bool = False
    aggregate_score: float = 0.0
    applicability_class: ApplicabilityClass = ApplicabilityClass.NOT_APPLICABLE


class TestEvidence(BaseModel):
    """A piece of test evidence from the evidence database."""
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    test_method: str = ""
    specimen_description: str = ""
    test_conditions: str = ""
    result_summary: str = ""
    citation: str = ""
    source_document: str = ""
    applicability: Optional[EvidenceApplicabilityScore] = None


class MechanismTrace(BaseModel):
    """Structured trace for one ignition mechanism (Spec §6 Step 3)."""
    mechanism_name: IgnitionMechanismName
    source_ref: str = ""
    credible_status: CredibleStatus = CredibleStatus.INDETERMINATE
    rating: int = Field(default=0, ge=0, le=4)
    required_elements: list[str] = Field(default_factory=list)
    observed_elements: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    rating_formula_version: str = "TM-2007-213740-Table2-v1"
    linked_evidence_ids: list[str] = Field(default_factory=list)
    controls_required: list[str] = Field(default_factory=list)
    reviewer_override: Optional[str] = None
    reviewer_comments: list[str] = Field(default_factory=list)


class KindlingChainResult(BaseModel):
    """Kindling chain and reaction effect (Spec §6 Steps 4-5)."""
    kindling_chain_present: bool = False
    propagation_path: list[str] = Field(default_factory=list)
    reaction_effect: ReactionEffect = ReactionEffect.A
    rationale: str = ""


class HazardControlEntry(BaseModel):
    """One row in the Hazard Control Table per TM Table 4."""
    component_ref: str = ""
    schematic_ref: Optional[str] = None
    ignition_hazard: str = ""
    probability_rating: int = Field(default=0, ge=0, le=4)
    reaction_effect: ReactionEffect = ReactionEffect.A
    recommendation: str = ""
    recommendation_class: RecommendationClass = RecommendationClass.HEURISTIC
    mitigated_reaction_effect: Optional[ReactionEffect] = None
    status: str = "open"
    affected_mechanisms: list[IgnitionMechanismName] = Field(default_factory=list)
    evidence_basis: str = ""
    confidence: str = "medium"


class TriggeredRequirement(BaseModel):
    """A governing requirement triggered by the assessment."""
    requirement_id: str
    source_standard: str
    section: str
    title: str
    tier: RuleTier = RuleTier.A
    satisfied: bool = False
    satisfaction_basis: str = ""
    is_prohibition: bool = False
    prohibition_detail: Optional[str] = None


class BlockedState(BaseModel):
    """A blocked state preventing full assessment."""
    state_type: BlockedStateType
    description: str
    missing_fields: list[str] = Field(default_factory=list)
    resolution_hint: str = ""


class MUASeed(BaseModel):
    """Structured MUA pre-population packet (Spec §13)."""
    material_identity: str = ""
    service_conditions: str = ""
    trigger_reason: str = ""
    mechanism_summary: str = ""
    applicable_evidence: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    rationale_draft: str = ""
    assumptions: list[str] = Field(default_factory=list)


class OCADecisionPacket(BaseModel):
    """Final OCA decision packet (Spec §9)."""
    case_id: str
    final_disposition: OCADisposition = OCADisposition.INSUFFICIENT_EVIDENCE
    triggered_requirements: list[TriggeredRequirement] = Field(default_factory=list)
    blocked_states: list[BlockedState] = Field(default_factory=list)
    unresolved_gaps: list[str] = Field(default_factory=list)
    kindling_chain_present: bool = False
    reaction_effect: ReactionEffect = ReactionEffect.A
    history_of_use: HistoryOfUse = HistoryOfUse.UNKNOWN
    mua_seed: Optional[MUASeed] = None
    acceptance_test_required: bool = False
    reviewer_required: bool = False
    summary_rationale: str = ""
    mechanism_assessments: list[MechanismTrace] = Field(default_factory=list)
    evidence: list[TestEvidence] = Field(default_factory=list)
    hazard_controls: list[HazardControlEntry] = Field(default_factory=list)
    kindling_chain: Optional[KindlingChainResult] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# API Request/Response Models
# ---------------------------------------------------------------------------

class OCACreateCaseRequest(BaseModel):
    """Request to create a new OCA case."""
    service_context: OxygenServiceContext
    component: ComponentInfo
    materials: list[MaterialInstance]


class OCACreateCaseResponse(BaseModel):
    """Response after creating a case."""
    case_id: str
    blocked_states: list[BlockedState] = Field(default_factory=list)
    precheck_warnings: list[str] = Field(default_factory=list)
    normalized_context: OxygenServiceContext
    normalized_materials: list[MaterialInstance] = Field(default_factory=list)


class OCAPrecheckResponse(BaseModel):
    """Requirement trigger precheck result."""
    case_id: str
    triggered_requirements: list[TriggeredRequirement] = Field(default_factory=list)
    prohibitions: list[TriggeredRequirement] = Field(default_factory=list)
    acceptance_test_required: bool = False
    acceptance_test_exempt: bool = False
    exemption_reason: Optional[str] = None


class OCAEvidenceResponse(BaseModel):
    """Evidence retrieval and scoring result."""
    case_id: str
    evidence: list[TestEvidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    total_evidence: int = 0


class OCAMechanismResponse(BaseModel):
    """Mechanism assessment result."""
    case_id: str
    mechanism_assessments: list[MechanismTrace] = Field(default_factory=list)
    credible_count: int = 0
    indeterminate_count: int = 0


class OCAKindlingResponse(BaseModel):
    """Kindling chain and reaction effect result."""
    case_id: str
    kindling_chain: KindlingChainResult


class OCADecisionResponse(BaseModel):
    """Final disposition response."""
    case_id: str
    decision: OCADecisionPacket


class OCAExportRequest(BaseModel):
    """Export artifact request."""
    case_id: str
    format: str = "json"  # json, summary
    include_evidence: bool = True
    include_mua_seed: bool = True


class OCAReviewActionRequest(BaseModel):
    """Reviewer action request."""
    case_id: str
    action: str  # approve, override, comment, request-info
    mechanism_name: Optional[IgnitionMechanismName] = None
    comment: str = ""
    reviewer_name: str = ""


__safety_critical__ = True
