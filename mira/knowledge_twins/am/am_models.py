"""
Module: AM Knowledge Twin -- intake contracts (Rev 5 §5.1)
Purpose: Validated request models for the AM Qualification Package engine.
         Conversational intake is NOT the authoritative API -- these models are.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032 (Data Validation), SWE-033, NASA-STD-8739.8B
Safety Critical: True

Design invariants (BS-SPEC-MIRA-AMTWIN-001-REV5):
- extra="forbid" on every model: unknown fields are rejected, never ignored.
- No silent defaults for safety-critical or classification-bearing fields.
  ``data_classification`` defaults to None (= UNKNOWN), which downstream
  code MUST treat as quarantine per Rev 5 §4.5 (deny-by-default), never
  as PUBLIC.
- Optional process/material fields stay None when unknown; engines respond
  with INSUFFICIENT_DATA naming the missing input -- they never guess.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AMProcess(str, Enum):
    """AM process families recognized by the intake contract.

    NASA-STD-6030 QMP methodology assumes fixed parameter sets; adaptive
    processes (typical EB-PBF and feedback DED implementations) are out of
    QMP scope per NASA-STD-6030 commentary (PDF p. 76) and are evaluated
    under a point-design philosophy.
    """

    L_PBF = "L-PBF"
    EB_PBF = "EB-PBF"
    DED = "DED"


class MaterialType(str, Enum):
    """Feedstock material family.

    Drives which structural-demand table (NASA-STD-6030 Table 2 vs Table 3)
    and which AM-risk applicability column (Table 4) governs.
    """

    METALLIC = "metallic"
    POLYMERIC = "polymeric"


class AMPartClass(str, Enum):
    """Primary AM part classification per NASA-STD-6030 [AMR-5], Figure 4."""

    CLASS_A = "Class A"
    CLASS_B = "Class B"
    CLASS_C = "Class C"
    EXEMPT = "Exempt"


class ConsequenceTier(str, Enum):
    """Consequence-of-failure tier supplied by the engineer.

    ``catastrophic``/``critical`` follow NPR 8715.3D definitions referenced
    by NASA-STD-6030 [AMR-6] note (PDF p. 35). Lower tiers exist for intake
    completeness; they never map to Class A.
    """

    CATASTROPHIC = "catastrophic"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    NEGLIGIBLE = "negligible"


class HazardFlag(str, Enum):
    """Structured hazard-context flags from intake.

    The first group mirrors conditions named in NASA-STD-6030 §4.3.1
    classification criteria; the second group carries service-environment
    context used by other MIRA twins (LOX/H2 compatibility routing).
    """

    FRACTURE_CRITICAL = "fracture_critical"
    PRESSURE_VESSEL = "pressure_vessel"
    SINGLE_POINT_FAILURE = "single_point_failure"
    CREWED_FLIGHT = "crewed_flight"
    IN_SPACE_AM = "in_space_am"
    PRIMARY_CONTAINMENT = "primary_containment"
    CRITICAL_REDUNDANCY = "critical_redundancy"
    DEBRIS_CONTAMINATION = "debris_contamination"
    LOX_COMPATIBLE = "lox_compatible"
    HYDROGEN_COMPATIBLE = "hydrogen_compatible"


class DataClassification(str, Enum):
    """Data classification regimes per Rev 5 §4.5."""

    PUBLIC = "PUBLIC"
    CUI = "CUI"
    EAR = "EAR"
    ITAR = "ITAR"


class RulePackRef(BaseModel):
    """Pinned reference to a frozen rule pack (Rev 5 §5.1)."""

    model_config = ConfigDict(extra="forbid")

    standard_id: str
    version: str
    rule_pack_id: str


class ClassificationPolicy(BaseModel):
    """Per-regime access policy (Rev 5 §4.5). Product Track mechanism;
    carried in the contract now so demo code paths exercise the same shape."""

    model_config = ConfigDict(extra="forbid")

    regime: DataClassification
    us_person_required: bool
    program_scope: list[str] = Field(default_factory=list)
    end_use_constraints: list[str] = Field(default_factory=list)
    license_or_exception_ref: Optional[str] = None


class AccessContext(BaseModel):
    """Authorization context -- part of the engine contract, not session state.

    Retrieval anywhere in the AM twin is deny-by-default against this
    context (Rev 5 §4.5, §8). Absence of an AccessContext means *no access*,
    not open access.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    program_ids: list[str] = Field(default_factory=list)
    permitted_source_classes: list[str] = Field(default_factory=list)
    deployment_boundary: str
    max_data_classification: DataClassification
    policies: list[ClassificationPolicy] = Field(default_factory=list)
    subject_is_us_person: Optional[bool] = None


class ClassificationInput(BaseModel):
    """Engineer-declared classification inputs (Rev 5 §5.1).

    ``intended_class`` is validated, never generated. Safety-critical fields
    require explicit engineer confirmation before evaluation.
    """

    model_config = ConfigDict(extra="forbid")

    classification_framework: str
    intended_class: Optional[AMPartClass] = None
    consequence_of_failure: ConsequenceTier
    hazard_context: list[HazardFlag] = Field(default_factory=list)
    fluid_service: Optional[str] = None
    redundancy: Optional[str] = None
    mission_critical: Optional[bool] = None
    class_c_criteria_confirmed: Optional[bool] = None
    safety_critical_confirmed: bool = False


class FeedstockInput(BaseModel):
    """Feedstock traceability inputs (Rev 5 §5.1)."""

    model_config = ConfigDict(extra="forbid")

    powder_spec: Optional[str] = None
    lot_id: Optional[str] = None
    reuse_count: Optional[int] = None
    reuse_history_available: bool = False
    powder_mfg_spec: Optional[str] = None


class ProcessQualStatus(BaseModel):
    """Machine/process qualification STATUS (never calibration physics)."""

    model_config = ConfigDict(extra="forbid")

    machine_id: Optional[str] = None
    process_spec: Optional[str] = None
    machine_qualified: Optional[bool] = None
    qmp_reference: Optional[str] = None


class DesignPartInput(BaseModel):
    """Optional design enrichment; absence limits output to baseline matrix."""

    model_config = ConfigDict(extra="forbid")

    geometry_class: Optional[str] = None
    critical_features: list[str] = Field(default_factory=list)
    build_orientation: Optional[str] = None
    post_process_route: Optional[str] = None
    service_conditions: Optional[str] = None
    load_case: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    sampling_strategy: Optional[str] = None
    inspection_access: Optional[str] = None


class ControlledArtifact(BaseModel):
    """Controlled-document reference for assessed-readiness mode (Rev 5 §5.3)."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    artifact_id: Optional[str] = None
    state: str = "missing"
    version: Optional[str] = None
    file_hash: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    approval_authority: Optional[str] = None
    approval_timestamp: Optional[str] = None
    referenced_standard_version: Optional[str] = None
    applicability_scope: Optional[str] = None
    data_classification: DataClassification = DataClassification.PUBLIC
    linked_equipment_process_material: list[str] = Field(default_factory=list)
    governing_clauses: list[str] = Field(default_factory=list)


class EvidenceRecord(BaseModel):
    """Digital-thread evidence record with explicit depth (Rev 5 §5.3).

    evidence_depth: 1 = exists, 2 = linked to build/lot, 3 = full trace.
    Readiness claims are never inflated above this depth.
    """

    model_config = ConfigDict(extra="forbid")

    record_id: str
    artifact_ref: str
    evidence_depth: int = Field(ge=1, le=3)
    powder_lot_id: Optional[str] = None
    build_id: Optional[str] = None
    machine_id: Optional[str] = None
    coupon_ids: list[str] = Field(default_factory=list)
    part_serials: list[str] = Field(default_factory=list)


class ProgramContext(BaseModel):
    """Program/artifact state for assessed-readiness mode (Rev 5 §5.1).

    ``registry_source`` None means manual entry: output is labeled
    NON_AUTHORITATIVE and system-sourced labels are withheld.
    ``recorded_conflicts`` carries requirement conflicts identified for this
    program (Rev 5 §4.2); unresolved high-impact conflicts cap the verdict.
    Stored as dicts validated into ConflictSet at evaluation time to avoid a
    circular import with crosswalk_models.
    """

    model_config = ConfigDict(extra="forbid")

    program_id: Optional[str] = None
    artifact_registry: list[ControlledArtifact] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    applicable_standards: list[str] = Field(default_factory=list)
    registry_source: Optional[str] = None
    recorded_conflicts: list[dict] = Field(default_factory=list)


class AMRequest(BaseModel):
    """The authoritative, validated evaluation request (Rev 5 §5.1).

    Invariants:
    - ``safety_critical_confirmed`` False blocks evaluation (engine returns
      INSUFFICIENT_DATA requesting confirmation; it never proceeds).
    - ``access`` None means retrieval is denied everywhere (deny-by-default).
    - ``data_classification`` None means UNKNOWN -> quarantine (Rev 5 §4.5);
      callers must declare PUBLIC explicitly. Never inferred.
    - ``am_process``/``material_type`` None: process- or material-dependent
      assessments report what is missing instead of assuming.
    """

    model_config = ConfigDict(extra="forbid")

    part_description: str
    material_designation: str
    classification: ClassificationInput
    am_process: Optional[AMProcess] = None
    material_type: Optional[MaterialType] = None
    feedstock: Optional[FeedstockInput] = None
    process_qual: Optional[ProcessQualStatus] = None
    rule_pack_set: list[RulePackRef] = Field(default_factory=list)
    access: Optional[AccessContext] = None
    data_classification: Optional[DataClassification] = None
    safety_critical_confirmed: bool = False
    design: Optional[DesignPartInput] = None
    program: Optional[ProgramContext] = None
    design_file_hashes: list[str] = Field(default_factory=list)
