"""Pydantic models for the fracture-control module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MissionClass = Literal["HUMAN_RATED", "CARGO", "EXPERIMENTAL", "GSE", "GROUND_SUPPORT"]
HazardConsequence = Literal["CATASTROPHIC", "CRITICAL", "MARGINAL", "NEGLIGIBLE", "UNKNOWN"]
LoadPathType = Literal["SINGLE", "REDUNDANT", "UNKNOWN"]
StructuralRole = Literal["PRIMARY", "SECONDARY", "NON_STRUCTURAL"]
MaterialSystem = Literal["METALLIC", "COMPOSITE", "BONDED", "CERAMIC", "OTHER"]
LifecyclePhase = Literal["NEW_BUILD", "REFLIGHT"]
SpecificHardwareType = Literal[
    "GENERAL",
    "FASTENER",
    "SHATTERABLE",
    "ROTATING_HARDWARE",
    "SEALED_CONTAINER",
    "TOOLS_TETHERS",
    "BATTERY",
    "PRESSURE_VESSEL",
    "COPV",
    "PRESSURIZED_COMPONENT",
    "HABITABLE_STRUCTURE",
    "PRESSURIZED_STRUCTURE",
]
FractureClassification = Literal[
    "EXEMPT",
    "NFC_METALLIC",
    "NFC_COMPOSITE_BONDED",
    "FC",
    "INDETERMINATE",
]
ConfidenceState = Literal["CONFIDENT", "INDETERMINATE", "CONSERVATIVE_FALLBACK"]
FindingStatus = Literal["PASS", "CAUTION", "FAIL", "INFO", "DATA_GAP"]


class FractureMaterialContext(BaseModel):
    low_risk_candidate: bool = False
    additive_manufactured: bool = False
    kic_fty_ratio: float | None = Field(default=None, gt=0)
    ftu_ksi: float | None = Field(default=None, gt=0)
    short_transverse_dimension_in: float | None = Field(default=None, ge=0)
    chloride_exposure: bool = False
    sustained_load_expected: bool = False
    nasa_std_6016_qualified: bool | None = None
    mua_present: bool = False
    approved_source_data_attached: bool = False


class FractureAssessmentRequest(BaseModel):
    part_name: str = Field(..., min_length=1)
    mission_class: MissionClass = "HUMAN_RATED"
    hazard_consequence: HazardConsequence = "UNKNOWN"
    load_path_type: LoadPathType = "UNKNOWN"
    pressure_boundary: bool = False
    lifecycle_phase: LifecyclePhase = "NEW_BUILD"
    structural_role: StructuralRole = "PRIMARY"
    material_system: MaterialSystem = "METALLIC"
    specific_hardware_type: SpecificHardwareType = "GENERAL"
    material_name: str | None = None
    optional_approach_requested: bool = False
    proof_test_used: bool = False
    process_controls_used: bool = False
    detected_flaw_accepted_for_flight: bool = False
    corrosion_iccp_recommended: bool = False
    material_context: FractureMaterialContext = Field(default_factory=FractureMaterialContext)


class FractureMaterialScreenRequest(BaseModel):
    material_name: str = Field(..., min_length=1)
    material_system: MaterialSystem = "METALLIC"
    lifecycle_phase: LifecyclePhase = "NEW_BUILD"
    classification: FractureClassification | None = None
    specific_hardware_type: SpecificHardwareType = "GENERAL"
    material_context: FractureMaterialContext = Field(default_factory=FractureMaterialContext)


class FractureCitation(BaseModel):
    fcr: int | None = None
    title: str
    section: str
    source_document: str
    source_path: str
    source_pages: list[int] = Field(default_factory=list)
    summary: str


class FractureRequirementSummary(BaseModel):
    fcr: int
    category: str
    title: str
    section: str
    description: str
    phase_1_relevant: bool
    notes: str | None = None
    citation: FractureCitation


class FractureResolvedMaterial(BaseModel):
    query: str
    canonical_name: str
    material_system: MaterialSystem
    family: str
    aliases: list[str] = Field(default_factory=list)


class FractureMaterialFinding(BaseModel):
    finding_id: str
    status: FindingStatus
    title: str
    detail: str
    governing_fcrs: list[int] = Field(default_factory=list)
    source_clauses: list[str] = Field(default_factory=list)
    data_provided: list[str] = Field(default_factory=list)
    citations: list[FractureCitation] = Field(default_factory=list)


class FractureAssessmentResponse(BaseModel):
    classification: FractureClassification
    baseline_key: str
    confidence_state: ConfidenceState
    screening_basis: str
    applicable_fcrs: list[int]
    requirements: list[FractureRequirementSummary]
    required_actions: list[str]
    required_documents: list[str]
    resolved_material: FractureResolvedMaterial | None = None
    material_findings: list[FractureMaterialFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unresolved_inputs: list[str] = Field(default_factory=list)
    conservative_fallback: str | None = None
    citations: list[FractureCitation] = Field(default_factory=list)
    source_manifest_version: str


class FractureMaterialSearchResult(BaseModel):
    canonical_name: str
    material_system: MaterialSystem
    family: str
    aliases: list[str] = Field(default_factory=list)


class FractureAuthorityManifest(BaseModel):
    version: str
    total_fcrs: int
    baseline_count: int
    conditional_extension_count: int
    special_rule_count: int
    sources: list[dict[str, str]]
