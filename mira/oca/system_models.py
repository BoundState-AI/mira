#!/usr/bin/env python3
"""
Module: OCA System Models (Phase 2)
Purpose: Pydantic models for the Visual System Builder per BS-SPEC-OCA-002-REV0.

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
from typing import Any, Optional

from pydantic import BaseModel, Field

from .models import (
    BlockedState,
    BlockedStateType,
    FlammabilityRating,
    HazardControlEntry,
    IgnitionMechanismName,
    KindlingChainResult,
    MaterialInstance,
    MechanismAssessment,
    MechanismTrace,
    MissionPhase,
    MUASeed,
    OCADecisionPacket,
    OCADisposition,
    OxidizerType,
    OxygenPhase,
    ReactionEffect,
    RuleTier,
    TriggeredRequirement,
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ComponentArchetype(str, Enum):
    VALVE = "valve"
    REGULATOR = "regulator"
    LINE = "line"
    FILTER = "filter"
    FITTING = "fitting"
    PRESSURE_VESSEL = "pressure_vessel"
    RELIEF_VALVE = "relief_valve"
    CHECK_VALVE = "check_valve"
    ORIFICE = "orifice"
    HEAT_EXCHANGER = "heat_exchanger"
    GASKET = "gasket"
    FLEX_HOSE = "flex_hose"


class ValveType(str, Enum):
    BALL = "ball"
    GATE = "gate"
    GLOBE = "globe"
    NEEDLE = "needle"


class ActuationType(str, Enum):
    MANUAL = "manual"
    PNEUMATIC = "pneumatic"
    SOLENOID = "solenoid"


class OpeningProfile(str, Enum):
    FAST = "fast"
    SLOW = "slow"


class SeatContactMode(str, Enum):
    METAL_TO_METAL = "metal_to_metal"
    METAL_TO_POLYMER = "metal_to_polymer"
    POLYMER_TO_POLYMER = "polymer_to_polymer"


class SAVolumeRatio(str, Enum):
    HIGH = "high"
    MEDIUM = "med"
    LOW = "low"


class InferenceSource(str, Enum):
    USER_ENTERED = "user_entered"
    INFERRED = "inferred"
    CALCULATED = "calculated"
    IMPORTED = "imported"


class InferenceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SystemZoneType(str, Enum):
    UNFILTERED = "unfiltered"
    FILTERED = "filtered"
    DEAD_LEG = "dead_leg"
    DYNAMIC = "dynamic"
    CAVITY_RESONANCE = "cavity_resonance"
    ACCEPTANCE_TEST = "acceptance_test"


# ---------------------------------------------------------------------------
# Feature Flags (per Spec §4.2)
# ---------------------------------------------------------------------------

class ComponentFeatureFlags(BaseModel):
    """Normalized feature flags derived from component configuration."""
    has_moving_contact: bool = False
    has_polymer_seal: bool = False
    has_dead_volume: bool = False
    creates_particles: bool = False
    has_cavity_downstream: bool = False
    wetted_surface_flag: bool = True
    porous_media_flag: bool = False
    electrical_energy_present: bool = False
    dynamic_contact_flag: bool = False
    contamination_trap_flag: bool = False
    filter_integrity_assumed: bool = False
    metal_pair_contact: bool = False
    reactive_metal_present: bool = False
    seat_contact_mode: Optional[SeatContactMode] = None
    sa_to_volume_ratio: SAVolumeRatio = SAVolumeRatio.LOW


# ---------------------------------------------------------------------------
# Assumption Drawer (per Spec §5.3)
# ---------------------------------------------------------------------------

class InferredFact(BaseModel):
    """A single inferred fact with full provenance."""
    fact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fact_name: str
    value: Any
    source: InferenceSource = InferenceSource.INFERRED
    confidence: InferenceConfidence = InferenceConfidence.MEDIUM
    rule_id: str = ""
    missing_assumptions: list[str] = Field(default_factory=list)
    explanation: str = ""


# ---------------------------------------------------------------------------
# System Component Instance (on canvas)
# ---------------------------------------------------------------------------

class MaterialSlotValue(BaseModel):
    """A material assigned to a component slot."""
    slot_name: str
    material: MaterialInstance


class ComponentConfig(BaseModel):
    """Configuration values for a specific component archetype."""
    valve_type: Optional[ValveType] = None
    actuation_type: Optional[ActuationType] = None
    opening_profile: Optional[OpeningProfile] = None
    regulator_type: Optional[str] = None
    chatter_susceptible: Optional[bool] = None
    soft_seat_creep_flag: Optional[bool] = None
    wall_thickness_mm: Optional[float] = None
    inner_diameter_mm: Optional[float] = None
    length_m: Optional[float] = None
    is_flex: Optional[bool] = None
    micron_rating: Optional[float] = None
    element_type: Optional[str] = None
    bypass_path_exists: Optional[bool] = None
    seal_type: Optional[str] = None
    connection_type: Optional[str] = None
    volume_liters: Optional[float] = None
    mawp_psia: Optional[float] = None
    set_pressure_psia: Optional[float] = None
    bore_diameter_mm: Optional[float] = None
    exposed_to_flow: Optional[bool] = None


class SystemComponent(BaseModel):
    """A component instance on the canvas."""
    component_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    archetype: ComponentArchetype
    label: str = ""
    position_x: float = 0.0
    position_y: float = 0.0

    # Material slots
    materials: list[MaterialSlotValue] = Field(default_factory=list)

    # Config
    config: ComponentConfig = Field(default_factory=ComponentConfig)

    # Computed features
    features: ComponentFeatureFlags = Field(default_factory=ComponentFeatureFlags)

    # Inferred facts (assumption drawer)
    inferred_facts: list[InferredFact] = Field(default_factory=list)

    # Zone membership
    zones: list[SystemZoneType] = Field(default_factory=list)

    # Assessment results (per-component)
    mechanism_assessments: list[MechanismAssessment] = Field(default_factory=list)
    overall_status: str = "pending"  # green / yellow / red / pending
    highest_rating: int = 0
    credible_mechanisms: list[str] = Field(default_factory=list)

    # Topology state
    connected: bool = False
    is_provisional: bool = False
    human_confirmed: bool = True

    # MPR 53 exemption fields
    is_rigid_metallic_tubing: bool = False
    is_metallic_flex_hose: bool = False
    is_all_metal_seal: bool = False
    is_metallic_pressure_vessel: bool = False


# ---------------------------------------------------------------------------
# Connection (edge on canvas)
# ---------------------------------------------------------------------------

class SystemConnection(BaseModel):
    """A flow path connection between two component ports."""
    connection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_component_id: str
    source_port: str = "output"
    target_component_id: str
    target_port: str = "input"
    label: Optional[str] = None


# ---------------------------------------------------------------------------
# System-Level Inputs (Top Bar per Spec §3)
# ---------------------------------------------------------------------------

class SystemInputs(BaseModel):
    """System-level inputs that propagate to every component."""
    o2_fraction: float = Field(default=1.0, ge=0.21, le=1.0)
    system_pressure_min_psia: float = Field(default=14.7, ge=0)
    system_pressure_max_psia: float = Field(default=14.7, ge=0)
    phase: OxidizerType = OxidizerType.GOX
    oxygen_phase: OxygenPhase = OxygenPhase.GAS
    temp_min_c: Optional[float] = None
    temp_max_c: Optional[float] = None
    design_flow_rate_m3_s: Optional[float] = None
    cleanliness_spec: Optional[str] = None
    mission_phase: MissionPhase = MissionPhase.GROUND_TEST
    project_name: str = ""
    hardware_name: str = ""
    reviewer_name: str = ""
    bi_directional_flow_risk: bool = False


# ---------------------------------------------------------------------------
# Topology Inference Results
# ---------------------------------------------------------------------------

class VelocityEstimate(BaseModel):
    """Velocity estimate for a line/tube component."""
    component_id: str
    velocity_m_s: float
    inner_diameter_mm: float
    flow_rate_m3_s: float
    source: InferenceSource = InferenceSource.CALCULATED
    confidence: InferenceConfidence = InferenceConfidence.MEDIUM


class SonicFlowPoint(BaseModel):
    """Detected sonic flow point at an orifice."""
    component_id: str
    pressure_ratio: float
    bore_diameter_mm: float
    downstream_component_ids: list[str] = Field(default_factory=list)


class TopologyInferenceResult(BaseModel):
    """Complete topology inference output."""
    dead_end_component_ids: list[str] = Field(default_factory=list)
    flow_direction: list[tuple[str, str]] = Field(default_factory=list)  # (from_id, to_id)
    velocity_estimates: list[VelocityEstimate] = Field(default_factory=list)
    sonic_flow_points: list[SonicFlowPoint] = Field(default_factory=list)
    filter_protected_ids: list[str] = Field(default_factory=list)
    chatter_candidate_ids: list[str] = Field(default_factory=list)
    upstream_volumes: dict[str, float] = Field(default_factory=dict)  # valve_id -> liters
    zone_assignments: dict[str, list[SystemZoneType]] = Field(default_factory=dict)
    inferred_facts: list[InferredFact] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Kindling Chain (System-Level)
# ---------------------------------------------------------------------------

class SystemKindlingChain(BaseModel):
    """System-level kindling chain across multiple components."""
    chain_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    propagation_path: list[str] = Field(default_factory=list)  # component_ids in order
    materials_in_path: list[str] = Field(default_factory=list)
    chain_broken_at: Optional[str] = None  # component_id where chain breaks
    break_reason: Optional[str] = None
    longest_continuous_length: int = 0
    reaction_effect: ReactionEffect = ReactionEffect.A


# ---------------------------------------------------------------------------
# Path Inspector (per Spec §7.2)
# ---------------------------------------------------------------------------

class PathInspectorResult(BaseModel):
    """Path inspector output for a single component."""
    component_id: str
    upstream_contributors: list[dict[str, str]] = Field(default_factory=list)
    local_mechanism_triggers: list[dict[str, str]] = Field(default_factory=list)
    downstream_propagation_risk: list[str] = Field(default_factory=list)
    controls_that_would_change: list[dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# System Assembly (root model)
# ---------------------------------------------------------------------------

class OCASystemAssembly(BaseModel):
    """Root model for a complete OCA system assembly."""
    system_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled System"
    description: str = ""
    spec_id: str = "BS-SPEC-OCA-002-REV0"

    # System-level inputs
    inputs: SystemInputs = Field(default_factory=SystemInputs)

    # Components and connections (the graph)
    components: list[SystemComponent] = Field(default_factory=list)
    connections: list[SystemConnection] = Field(default_factory=list)

    # Topology inference results
    topology: Optional[TopologyInferenceResult] = None

    # System-level assessment
    system_disposition: Optional[OCADisposition] = None
    system_reaction_effect: Optional[ReactionEffect] = None
    kindling_chains: list[SystemKindlingChain] = Field(default_factory=list)
    system_triggered_requirements: list[TriggeredRequirement] = Field(default_factory=list)
    system_blocked_states: list[BlockedState] = Field(default_factory=list)
    system_hazard_controls: list[HazardControlEntry] = Field(default_factory=list)
    mua_seeds: list[MUASeed] = Field(default_factory=list)

    # Flags
    has_titanium: bool = False
    mpr67_active: bool = False

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    audit_log: list[dict[str, Any]] = Field(default_factory=list)
    locked: bool = False


# ---------------------------------------------------------------------------
# API Request/Response Models (Phase 2)
# ---------------------------------------------------------------------------

class CreateSystemRequest(BaseModel):
    """Request to create a new system assembly."""
    name: str = "Untitled System"
    description: str = ""
    inputs: SystemInputs = Field(default_factory=SystemInputs)


class CreateSystemResponse(BaseModel):
    """Response after creating a system."""
    system_id: str
    name: str
    blocked_states: list[BlockedState] = Field(default_factory=list)


class AddComponentRequest(BaseModel):
    """Request to add a component to the canvas."""
    archetype: ComponentArchetype
    label: str = ""
    position_x: float = 0.0
    position_y: float = 0.0
    materials: list[MaterialSlotValue] = Field(default_factory=list)
    config: ComponentConfig = Field(default_factory=ComponentConfig)


class AddComponentResponse(BaseModel):
    """Response after adding a component."""
    component_id: str
    features: ComponentFeatureFlags
    zones: list[SystemZoneType] = Field(default_factory=list)
    inferred_facts: list[InferredFact] = Field(default_factory=list)


class AddConnectionRequest(BaseModel):
    """Request to connect two components."""
    source_component_id: str
    source_port: str = "output"
    target_component_id: str
    target_port: str = "input"


class AddConnectionResponse(BaseModel):
    """Response after connecting two components."""
    connection_id: str
    topology_changed: bool = True
    affected_component_ids: list[str] = Field(default_factory=list)


class SystemAssessmentResponse(BaseModel):
    """Full system assessment result."""
    system_id: str
    system_disposition: OCADisposition
    system_reaction_effect: ReactionEffect
    components: list[SystemComponent]
    kindling_chains: list[SystemKindlingChain]
    triggered_requirements: list[TriggeredRequirement]
    blocked_states: list[BlockedState]
    hazard_controls: list[HazardControlEntry]
    has_titanium: bool
    mpr67_active: bool


class TopologyResponse(BaseModel):
    """Topology inference result with zones and assumptions."""
    system_id: str
    topology: TopologyInferenceResult
    zones: dict[str, list[SystemZoneType]]


class SystemKindlingChainResponse(BaseModel):
    """System propagation map."""
    system_id: str
    chains: list[SystemKindlingChain]
    worst_case_effect: ReactionEffect


class SystemExportResponse(BaseModel):
    """System-level export artifacts."""
    system_id: str
    system_name: str
    generated_at: str
    system_oca_report: dict[str, Any] = Field(default_factory=dict)
    component_cards: list[dict[str, Any]] = Field(default_factory=list)
    kindling_chain_map: list[dict[str, Any]] = Field(default_factory=list)
    hazard_control_table: list[dict[str, Any]] = Field(default_factory=list)
    bill_of_materials: list[dict[str, Any]] = Field(default_factory=list)
    miul_seeds: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_test_schedule: list[dict[str, Any]] = Field(default_factory=list)
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)


__safety_critical__ = True
