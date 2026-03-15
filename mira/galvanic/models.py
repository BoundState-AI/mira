"""Pydantic models for the galvanic corrosion module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


EnvironmentKey = Literal[
    "seawater_proxy",
    "coastal_condensing",
    "industrial_atm",
    "rural_atm",
    "crew_condensing",
    "dry_indoor",
    "cryogenic_ops",
    "space_vacuum",
]

ApplicationType = Literal[
    "FLIGHT_HARDWARE",
    "SPACECRAFT_STRUCTURE",
    "GROUND_SUPPORT_EQUIPMENT",
    "LAUNCH_STRUCTURE",
    "FIXED_INSTALLATION",
]

JointType = Literal[
    "FAYING_SURFACE",
    "FASTENER",
    "LAP_JOINT",
    "CREVICE_PRONE",
    "IMMERSED",
    "GENERAL",
]

ElectricalContact = Literal["YES", "NO", "UNKNOWN"]


class CoupleContext(BaseModel):
    electrical_contact: ElectricalContact = "YES"
    electrolyte_pooling: bool = False
    joint_type: JointType = "GENERAL"
    cathode_to_anode_area_ratio: float | None = Field(default=None, gt=0)


class GalvanicAssessmentRequest(BaseModel):
    material_a: str = Field(..., min_length=1)
    material_b: str = Field(..., min_length=1)
    environment: EnvironmentKey = "seawater_proxy"
    application_type: ApplicationType = "FLIGHT_HARDWARE"
    surface_condition_a: str | None = None
    surface_condition_b: str | None = None
    couple_context: CoupleContext = Field(default_factory=CoupleContext)


class MaterialStateBand(BaseModel):
    state: str
    representative_potential_mv_sce: float


class ResolvedMaterial(BaseModel):
    query: str
    canonical_name: str
    family: str
    chosen_state: str
    representative_potential_mv_sce: float
    potential_range_mv_sce: tuple[float, float]
    possible_states: list[MaterialStateBand] = Field(default_factory=list)
    source_type: str


class MitigationRecommendation(BaseModel):
    mitigation_id: str
    name: str
    mechanism: str
    mitigation_class: str
    boundstate_priority: int
    description: str
    source_clauses: list[str]
    standards: list[str]
    restrictions: list[str]
    notes: list[str]
    coat_cathode_warning: bool
    trigger_reason: str


class GalvanicAssessmentResponse(BaseModel):
    severity: Literal["COMPATIBLE", "CAUTION", "INCOMPATIBLE"]
    raw_delta_mv: float
    effective_delta_mv: float
    decision_basis: Literal["NASA_STD_6012A_CPR39", "BOUNDSTATE_SYNTHESIZED", "NO_ELECTRICAL_CONTACT", "NO_ELECTROLYTE"]
    screening_disclaimer: str
    environment: EnvironmentKey
    environment_modifier: float
    application_type: ApplicationType
    anode: str
    cathode: str
    material_a: ResolvedMaterial
    material_b: ResolvedMaterial
    warnings: list[str] = Field(default_factory=list)
    mitigations: list[MitigationRecommendation] = Field(default_factory=list)
    source_manifest_version: str


class MaterialSearchResult(BaseModel):
    canonical_name: str
    family: str
    aliases: list[str]


class EnvironmentDescriptor(BaseModel):
    key: EnvironmentKey
    label: str
    modifier: float
    notes: str
