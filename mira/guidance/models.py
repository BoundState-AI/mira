"""
BS-SPEC-GUIDANCE-001-REV2.1 — Universal Guidance Schema Pydantic Models

Mirror of the TypeScript type definitions in frontend/src/lib/guidance/types.ts.
Used for backend validation, serving, and authoring of guidance packs.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Section 3.5 — Authority Model
# ---------------------------------------------------------------------------


class AuthoritySourceType(str, Enum):
    OFFICIAL_PDF = "official_pdf"
    INTERNAL_CONTROLLED_COPY = "internal_controlled_copy"
    EXTERNAL_REFERENCE = "external_reference"
    DERIVED_SUMMARY = "derived_summary"


class AuthorityType(str, Enum):
    REQUIREMENT = "requirement"
    GUIDANCE = "guidance"
    BEST_PRACTICE = "best_practice"
    LOCAL_POLICY = "local_policy"


class AuthorityRelationship(str, Enum):
    PRIMARY = "primary"
    SUPPLEMENTARY = "supplementary"
    OVERLAY = "overlay"


class RequirementType(str, Enum):
    SHALL = "shall"
    SHOULD = "should"
    MAY = "may"


class VerificationMethod(str, Enum):
    MANUAL_REVIEW = "manual_review"
    AUTOMATED_HASH = "automated_hash"


class AuthorityStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class AuthorityRegistryEntry(BaseModel):
    """Section 3.5.1 — Authority Registry Entry."""

    authority_id: str
    document_id: str
    revision: str
    section: str
    requirement_id: Optional[str] = None
    requirement_type: Optional[RequirementType] = None
    verbatim_excerpt: Optional[str] = None
    boundstate_summary: str
    interpretation: Optional[str] = None
    source_type: AuthoritySourceType
    source_url: Optional[str] = None
    internal_doc_handle: Optional[str] = None
    page_ref: Optional[str] = None
    document_hash: Optional[str] = None
    verification_method: Optional[VerificationMethod] = None
    last_verified: str
    status: AuthorityStatus = AuthorityStatus.ACTIVE
    legal_disclaimer: str


class AuthorityRef(BaseModel):
    """Section 3.5.3 — Authority Reference in Field Schema."""

    authority_ref: str
    type: AuthorityType
    relationship: AuthorityRelationship
    applies_when: Optional[dict[str, str | list[str]]] = None
    presentation_order: Optional[int] = None
    overlay_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Section 3.6 — Validation Model
# ---------------------------------------------------------------------------


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class WarningSeverity(str, Enum):
    CAUTION = "caution"
    INFO = "info"


class ValidationType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"


class ValidationRule(BaseModel):
    """Section 3.6 — UI-level input validation only."""

    type: ValidationType
    severity: ValidationSeverity
    required: bool
    pattern: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    min: Optional[float] = None
    max: Optional[float] = None
    unit: Optional[str] = None
    unit_alternatives: Optional[list[str]] = None
    auto_convert: Optional[bool] = None
    precision: Optional[int] = None
    enum_values: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Section 3.8 — Heritage Model
# ---------------------------------------------------------------------------


class HeritageModel(BaseModel):
    auto_extracted_from: Optional[str] = None
    extraction_method: Optional[str] = None
    extraction_confidence: Optional[float] = None
    extraction_timestamp: Optional[str] = None
    user_confirmed: bool = False
    display_when_present: str


# ---------------------------------------------------------------------------
# Section 3.9 — Escalation Model
# ---------------------------------------------------------------------------


class EscalationActionType(str, Enum):
    FLAG_FOR_REVIEW = "flag_for_review"
    DISPLAY_BLOCK_REASON = "display_block_reason"
    SUGGEST_ALTERNATIVE = "suggest_alternative"
    LINK_TO_RESOURCE = "link_to_resource"


class EscalationAction(BaseModel):
    action_type: EscalationActionType
    target_role: Optional[str] = None
    message_template: str
    target_url: Optional[str] = None
    available_when: Optional[dict[str, str | list[str]]] = None


class EscalationModel(BaseModel):
    type: str = "recommendation"
    on_unresolved_warning: Optional[EscalationAction] = None
    on_validation_failure: Optional[EscalationAction] = None


# ---------------------------------------------------------------------------
# Warnings, Actions, Lookup
# ---------------------------------------------------------------------------


class WarningSourceType(str, Enum):
    HEURISTIC = "heuristic"
    SYSTEM = "system"
    ENGINE = "engine"


class GuidanceWarning(BaseModel):
    condition_ref: str
    severity: WarningSeverity
    message: str
    source_type: WarningSourceType


class GuidanceActionType(str, Enum):
    LOOKUP = "lookup"
    NAVIGATE = "navigate"
    LINK = "link"
    RUN = "run"


class GuidanceAction(BaseModel):
    action: GuidanceActionType
    target: str
    prompt: str
    available_when: Optional[dict[str, str | list[str]]] = None


class LookupAssist(BaseModel):
    source: str
    fuzzy_match: bool = False
    fuzzy_threshold: Optional[float] = None
    user_must_confirm: bool = True


# ---------------------------------------------------------------------------
# Section 4.4/4.5 — Policy and Rule Engine Hooks
# ---------------------------------------------------------------------------


class PolicyHook(BaseModel):
    hook_ref: str
    description: str
    source_engine: str
    display_as: str
    severity: WarningSeverity
    message_template: str
    engine_blocking_state_ref: str
    display_when_blocked: str


class RuleEngineHook(BaseModel):
    rule_ref: str
    version: str
    input_contract: list[str]
    output_contract: dict[str, str]
    registry: str
    display_result_as: str
    on_fail_message: str


# ---------------------------------------------------------------------------
# Section 3.7 — Applicability
# ---------------------------------------------------------------------------


class FieldApplicability(BaseModel):
    visible_when: Optional[dict[str, str | list[str]]] = None
    required_when: Optional[dict[str, str | list[str]]] = None
    enhanced_when: Optional[dict[str, str | list[str]]] = None


# ---------------------------------------------------------------------------
# Section 3.3/3.4 — Field Definition
# ---------------------------------------------------------------------------


class GuidanceFieldDefinition(BaseModel):
    """Complete field guidance definition per Section 3.3/3.4."""

    label: str
    what: str
    why: str
    how: Optional[str] = None
    common_errors: Optional[list[str]] = None
    examples: Optional[list[str]] = None
    authorities: Optional[list[AuthorityRef]] = None
    applicability: Optional[FieldApplicability] = None
    validation: ValidationRule
    lookup_assist: Optional[LookupAssist] = None
    heritage: Optional[HeritageModel] = None
    actions: Optional[list[GuidanceAction]] = None
    warnings: Optional[list[GuidanceWarning]] = None
    escalation: Optional[EscalationModel] = None
    related_fields: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    policy_hooks: Optional[list[PolicyHook]] = None
    rule_engine_hooks: Optional[list[RuleEngineHook]] = None


# ---------------------------------------------------------------------------
# Section 7 — Workflow Model
# ---------------------------------------------------------------------------


class WorkflowStep(BaseModel):
    step_id: str
    title: str
    description: str
    fields: list[str]
    prerequisites: list[str] = Field(default_factory=list)
    completion_conditions: dict[str, bool] = Field(default_factory=dict)
    guidance_on_entry: str
    next_best_action: str
    missing_evidence: Optional[dict[str, str]] = None
    document_checklist: Optional[list[dict[str, Any]]] = None
    generation: Optional[int] = None
    side: Optional[str] = None


class WorkflowDefinition(BaseModel):
    workflow_id: str
    type: Optional[str] = None
    steps: list[WorkflowStep]
    tree_rules: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Section 6 — GuidanceMode
# ---------------------------------------------------------------------------


class GuidanceModeName(str, Enum):
    TRAINING = "training"
    LIVE = "live"
    EXPERT = "expert"


class ModuleModeOverride(BaseModel):
    expert_mode_minimum_severity: WarningSeverity
    rationale: str


class ModeTransitionRule(BaseModel):
    conditions: dict[str, str]
    prompt: str
    user_must_confirm: bool = True
    mode_floor: Optional[dict[str, Any]] = None


class ModeRules(BaseModel):
    recommend_promotion: dict[str, ModeTransitionRule] = Field(default_factory=dict)
    recommend_demotion: dict[str, ModeTransitionRule] = Field(default_factory=dict)
    overrides: dict[str, bool] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section 8 — Locale
# ---------------------------------------------------------------------------


class LocaleFieldOverride(BaseModel):
    what: Optional[str] = None
    why: Optional[str] = None
    how: Optional[str] = None
    common_errors: Optional[list[str]] = None


class LocaleOverrides(BaseModel):
    fields: Optional[dict[str, LocaleFieldOverride]] = None


# ---------------------------------------------------------------------------
# Section 3.1 — Schema Envelope (Guidance Pack)
# ---------------------------------------------------------------------------


class ChangeLogEntry(BaseModel):
    version: str
    date: str
    notes: str


class GuidancePackStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class GuidancePack(BaseModel):
    """Section 3.1 — Top-level guidance pack envelope."""

    guidance_pack_id: str
    schema_version: str
    platform: str
    module: str
    locale: str = "en"
    status: GuidancePackStatus
    authored_by: str
    reviewed_by: list[str] = Field(default_factory=list)
    approved_by: str
    effective_date: str
    supersedes: Optional[str] = None
    change_log: list[ChangeLogEntry] = Field(default_factory=list)
    fields: dict[str, GuidanceFieldDefinition]
    workflows: Optional[dict[str, WorkflowDefinition]] = None
    contexts: Optional[dict[str, Any]] = None
    module_mode_overrides: Optional[dict[str, ModuleModeOverride]] = None
    mode_rules: Optional[ModeRules] = None
    locale_overrides: Optional[dict[str, LocaleOverrides]] = None
