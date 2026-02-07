# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
GPTL Schema - Pydantic models for Grounded Precision Translation Layer
=====================================================================

All Pydantic models for the GPTL system, implementing the v4.1 specification.

Features:
- Type-safe request/response contracts
- DocFeatures for ingestion-time feature extraction
- Evidence taxonomy with derivation support
- Intent frames and constraint rules
- Audit trail with full traceability

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class EvidenceType(str, Enum):
    """
    Evidence type taxonomy for document classification.

    Evidence types are ordered by signal strength:
    - Primary: High signal, directly answers questions
    - Supporting: Medium signal, provides context
    - Contextual: Lower signal, background information
    - Noise: Candidates for elimination
    """
    # Primary (high signal)
    TEST_REPORT = "test_report"
    SPECIFICATION = "specification"
    FAILURE_ANALYSIS = "failure_analysis"
    COMPATIBILITY_MATRIX = "compatibility_matrix"
    CERTIFICATION = "certification"

    # Supporting (medium signal)
    TECHNICAL_MANUAL = "technical_manual"
    WORK_ORDER = "work_order"
    DRAWING = "drawing"
    DATASHEET = "datasheet"

    # Contextual (lower signal)
    INTERNAL_MEMO = "internal_memo"
    MEETING_NOTES = "meeting_notes"
    EMAIL = "email"

    # Noise candidates
    MARKETING_BROCHURE = "marketing_brochure"
    NEWS_ARTICLE = "news_article"
    WEB_CONTENT = "web_content"

    # Unknown/fallback
    UNKNOWN = "unknown"


class DocType(str, Enum):
    """
    Document type classification.

    Used for pre-retrieval filtering and constraint enforcement.
    """
    SPECIFICATION = "specification"
    PROCEDURE = "procedure"
    POLICY = "policy"
    REPORT = "report"
    DRAWING = "drawing"
    FORM = "form"
    MEMO = "memo"
    EMAIL = "email"
    PRESENTATION = "presentation"
    MANUAL = "manual"
    MARKETING = "marketing"
    UNKNOWN = "unknown"


class DateSource(str, Enum):
    """Source of date extraction."""
    METADATA = "metadata"
    CONTENT = "content"
    FILENAME = "filename"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class ConstraintAction(str, Enum):
    """Action to take when a constraint is violated."""
    HARD_DROP = "hard_drop"      # Eliminate from results
    SOFT_DROP = "soft_drop"      # Deprioritize with penalty
    WARN = "warn"                # Include with warning
    PASS = "pass"                # No action


class IntentCategory(str, Enum):
    """High-level intent categories for query classification."""
    MATERIAL_LOOKUP = "material_lookup"
    COMPATIBILITY_CHECK = "compatibility_check"
    FAILURE_PREDICTION = "failure_prediction"
    SUBSTITUTION_ANALYSIS = "substitution_analysis"
    COMPLIANCE_CHECK = "compliance_check"
    LIABILITY_ASSESSMENT = "liability_assessment"
    PROPERTY_COMPARISON = "property_comparison"
    PROCESS_GUIDANCE = "process_guidance"
    GENERAL_QUERY = "general_query"


class ModelTier(str, Enum):
    """Claude model tiers for escalation policy."""
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


class ConditionOperator(str, Enum):
    """Logical operators for compound conditions."""
    AND = "and"
    OR = "or"


# =============================================================================
# DOCFEATURES - The Core Data Model
# =============================================================================

class EntitySet(BaseModel):
    """Extracted entities by category."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    materials: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    hazards: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    processes: list[str] = Field(default_factory=list)


class DocFlags(BaseModel):
    """Boolean flags for document characteristics."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    has_measurements: bool = False
    has_tables: bool = False
    has_test_conditions: bool = False
    has_spec_references: bool = False
    has_figures: bool = False
    has_equations: bool = False
    is_noise_candidate: bool = False


class DocFeatures(BaseModel):
    """
    Feature signature for a document, computed at ingestion time.

    CRITICAL REQUIREMENT: DocFeatures MUST be computed BEFORE the document
    is searchable. Constraints operate on validated DocFeatures, not raw text.

    Compliance: SWE-032, SWE-033
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    # Identity
    doc_id: str
    doc_hash: str
    feature_schema_version: str = "1.0"
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    extractor_config_hash: str = ""

    # Extraction Metadata
    extraction_model: str = "haiku-3.5"
    derivation_validated: bool = False
    derivation_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Classification
    doc_type: DocType = DocType.UNKNOWN
    domain_scores: dict[str, float] = Field(default_factory=dict)

    # Semantic Content
    tags: list[str] = Field(default_factory=list)
    entities: EntitySet = Field(default_factory=EntitySet)

    # Evidence Markers
    flags: DocFlags = Field(default_factory=DocFlags)

    # Derived Evidence Types (LLM-validated)
    derived_evidence_types: list[EvidenceType] = Field(default_factory=list)

    # Reference Density
    spec_ref_count: int = Field(default=0, ge=0)
    drawing_ref_count: int = Field(default=0, ge=0)
    internal_ref_count: int = Field(default=0, ge=0)

    # Temporal
    date_value: datetime | None = None
    date_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    date_source: DateSource = DateSource.UNKNOWN

    # Noise Detection
    noise_markers: list[str] = Field(default_factory=list)

    # Traceability
    source: str = "gptl_feature_extractor"

    @field_validator("domain_scores")
    @classmethod
    def validate_domain_scores(cls, v: dict[str, float]) -> dict[str, float]:
        """Ensure domain scores are in valid range."""
        for domain, score in v.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"Domain score for '{domain}' must be between 0.0 and 1.0")
        return v

    def compute_feature_hash(self) -> str:
        """Compute a hash of the features for determinism verification."""
        # Serialize key fields for hashing
        key_fields = {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type.value,
            "derived_evidence_types": [e.value for e in self.derived_evidence_types],
            "tags": sorted(self.tags),
            "entities": self.entities.model_dump(),
            "flags": self.flags.model_dump(),
        }
        content = str(sorted(key_fields.items()))
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# =============================================================================
# INTENT FRAMING
# =============================================================================

class EvidenceRequirements(BaseModel):
    """Evidence requirements for an intent frame."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    types: list[EvidenceType] = Field(default_factory=list)
    min_count: int = Field(default=1, ge=1)
    required_entity_classes: list[str] = Field(default_factory=list)


class IntentFrame(BaseModel):
    """
    Intent frame mapping surface question to decision question.

    The intent frame defines:
    - What the user is really asking (decision_question)
    - What evidence is needed to answer (evidence_requirements)
    - What constraints apply (constraint_ids)
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    frame_id: str
    category: IntentCategory
    decision_question: str
    surface_patterns: list[str] = Field(default_factory=list)
    evidence_requirements: EvidenceRequirements = Field(default_factory=EvidenceRequirements)
    constraint_ids: list[str] = Field(default_factory=list)
    quality_tier_default: Literal["standard", "critical"] = "standard"

    # Traceability
    source: str = "gptl_intent_frame"


class IntentClassificationResult(BaseModel):
    """Result of intent classification by Claude."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    frame_id: str
    category: IntentCategory
    decision_question: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence_requirements: EvidenceRequirements
    escalate_to_opus: bool = False
    model_used: ModelTier

    # Traceability
    source: str = "gptl_intent_classifier"


# =============================================================================
# SHARED CONDITION BASE (SOLID: DRY principle)
# =============================================================================

class BaseCondition(BaseModel):
    """
    Base class for declarative conditions.

    Used by both constraint rules and derivation rules.
    Operators: eq, neq, in, contains, lt, gt, lte, gte, regex, exists, empty, not_empty
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    field: str                              # e.g., "doc_type", "flags.has_measurements"
    operator: str                           # e.g., "eq", "in", "contains", "lt", "gt"
    value: Any                              # Value to compare against


# =============================================================================
# CONSTRAINT RULES
# =============================================================================

class ConstraintCondition(BaseCondition):
    """A condition for a constraint rule, with optional negation."""
    negate: bool = False                    # If true, inverts the condition


class CompoundCondition(BaseModel):
    """
    Compound condition with nested AND/OR logic.

    Allows complex constraint rules with boolean combinations:
    - AND: All nested conditions must be true
    - OR: At least one nested condition must be true
    - negate: Inverts the final result

    Example:
        CompoundCondition(
            operator=ConditionOperator.OR,
            conditions=[
                ConstraintCondition(field="doc_type", operator="eq", value="marketing"),
                ConstraintCondition(field="flags.is_noise_candidate", operator="eq", value=True),
            ]
        )
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    operator: ConditionOperator
    conditions: list["ConstraintCondition | CompoundCondition"]
    negate: bool = False


class ConstraintRule(BaseModel):
    """
    Constraint rule for negative selection.

    Constraints define what CANNOT be true for valid results.
    They operate on DocFeatures, not raw document text.

    Conditions can be:
    - list[ConstraintCondition]: Simple list with implicit AND (backward compatible)
    - CompoundCondition: Complex nested AND/OR logic
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    rule_id: str
    name: str
    description: str
    action: ConstraintAction
    conditions: list[ConstraintCondition] | CompoundCondition
    applies_to_intents: list[str] = Field(default_factory=list)  # Empty = all intents
    priority: int = Field(default=100, ge=0)  # Lower = higher priority

    # For soft_drop, the penalty configuration
    penalty_weight: float | None = Field(default=None, ge=0.0, le=1.0)

    # Semantic check - if True, use LLM to verify ambiguous cases
    requires_semantic_check: bool = False
    semantic_check_prompt: str | None = None

    # Traceability
    source: str = "gptl_constraint_rule"


# =============================================================================
# VIOLATION REPORTING
# =============================================================================

class ConstraintViolation(BaseModel):
    """Record of a single constraint violation."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    doc_id: str
    rule_id: str
    rule_name: str
    action: ConstraintAction
    reason: str
    penalty_applied: float | None = None
    semantic_check_used: bool = False
    semantic_check_confidence: float | None = None


class ViolationReport(BaseModel):
    """
    Complete violation report for a query.

    This is a key audit artifact - it explains WHY documents were eliminated.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    total_candidates: int = 0
    candidates_eliminated: int = 0
    candidates_deprioritized: int = 0
    survivors: int = 0
    reduction_ratio: float = 0.0

    violations: list[ConstraintViolation] = Field(default_factory=list)
    rules_triggered: list[str] = Field(default_factory=list)

    # Stage breakdown
    pre_retrieval_eliminated: int = 0
    post_retrieval_eliminated: int = 0

    # Traceability
    source: str = "gptl_negative_selection"

    @model_validator(mode="after")
    def compute_reduction_ratio(self) -> "ViolationReport":
        """Compute reduction ratio after validation."""
        if self.total_candidates > 0:
            self.reduction_ratio = self.candidates_eliminated / self.total_candidates
        return self


# =============================================================================
# INTELLIGENCE OUTPUT
# =============================================================================

class EvidenceCitation(BaseModel):
    """Citation for a piece of evidence."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    doc_id: str
    doc_title: str | None = None
    section: str | None = None
    page: int | None = None
    snippet: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    evidence_type: EvidenceType


class IntelligenceOutput(BaseModel):
    """
    Actionable intelligence output from GPTL synthesis.

    This is the structured output format for all GPTL queries.
    Every claim must cite a source document.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    # Core intelligence
    finding: str
    implication: str
    action: str
    timeline: str

    # Confidence with calibration
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_interval: tuple[float, float] = Field(default=(0.0, 1.0))
    confidence_drivers: list[str] = Field(default_factory=list)

    # Evidence with citations
    evidence: list[EvidenceCitation] = Field(default_factory=list)

    # Conflict detection
    evidence_conflicts_detected: bool = False
    conflict_description: str | None = None

    # Refusal on missing evidence (bounded outputs)
    insufficient_evidence: bool = False
    refusal_reason: str | None = None
    refusal_type: Literal[
        "evidence_count",
        "confidence",
        "contradiction",
        "stale_data",
        "missing_critical_type",
        "source_diversity",
    ] | None = None

    # Traceability
    source: str = "gptl_intelligence_output"

    @field_validator("confidence_interval")
    @classmethod
    def validate_confidence_interval(cls, v: tuple[float, float]) -> tuple[float, float]:
        """Ensure confidence interval is valid."""
        lower, upper = v
        if not (0.0 <= lower <= upper <= 1.0):
            raise ValueError("Confidence interval must be [lower, upper] with 0 <= lower <= upper <= 1")
        return v


# =============================================================================
# AUDIT TRAIL
# =============================================================================

class ModelCall(BaseModel):
    """Record of a single model call."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    model: ModelTier
    layer: str  # L0, L2, L3, L4, L5
    purpose: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    escalated_from: ModelTier | None = None


class AuditTrail(BaseModel):
    """
    Complete audit trail for a GPTL query.

    This is the key artifact for reproducibility and explainability.
    Every GPTL output MUST have a complete audit trail.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    # Identity
    trace_id: str
    query_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Configuration
    config_version: str
    config_hash: str
    engine_version: str
    domain_id: str

    # Mode
    mode: Literal["strict", "shadow", "bypass"]
    quality_tier: Literal["standard", "critical"]

    # Intent
    intent_frame_used: str
    intent_confidence: float = Field(ge=0.0, le=1.0)

    # Negative Selection
    candidates_evaluated: int = 0
    candidates_eliminated: int = 0
    reduction_ratio: float = 0.0
    rules_triggered: list[str] = Field(default_factory=list)

    # Model Usage
    models_used: list[str] = Field(default_factory=list)
    model_calls: list[ModelCall] = Field(default_factory=list)
    total_model_calls: int = 0
    escalations: list[str] = Field(default_factory=list)

    # Timing
    total_latency_ms: int = 0
    l2_intent_latency_ms: int = 0
    l3_selection_latency_ms: int = 0
    l5_synthesis_latency_ms: int = 0

    # Determinism
    retrieval_determinism_verified: bool = False

    # Traceability
    source: str = "gptl_engine"


# =============================================================================
# METRICS
# =============================================================================

class GPTLMetrics(BaseModel):
    """Metrics for a single GPTL query execution."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    # Reduction
    reduction_ratio: float = Field(ge=0.0, le=1.0)

    # Timing
    total_latency_ms: int
    l2_latency_ms: int = 0
    l3_latency_ms: int = 0
    l5_latency_ms: int = 0

    # Quality
    intent_confidence: float = Field(ge=0.0, le=1.0)
    synthesis_confidence: float = Field(ge=0.0, le=1.0)

    # Coverage
    evidence_count: int
    citation_count: int

    # Model usage
    model_calls: int
    escalation_count: int

    # Traceability
    source: str = "gptl_metrics"


# =============================================================================
# REQUEST / RESPONSE
# =============================================================================

class GPTLRequest(BaseModel):
    """
    Input contract for GPTL queries.

    This is the primary API input type.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    query: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    mode: Literal["strict", "shadow", "bypass"] = "shadow"
    quality_tier: Literal["standard", "critical"] = "standard"
    config_overrides: dict[str, Any] | None = None

    # Traceability
    source: str = "api"


class GPTLResponse(BaseModel):
    """
    Output contract for GPTL queries.

    This is the primary API output type.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    intelligence: IntelligenceOutput
    violation_report: ViolationReport
    metrics: GPTLMetrics
    audit: AuditTrail
    models_used: list[str]

    # Traceability
    source: str = "gptl_engine"


# =============================================================================
# RETRIEVAL DETERMINISM CONFIG (Amendment 1)
# =============================================================================

class RetrievalDeterminismConfig(BaseModel):
    """
    Configuration for ensuring retrieval determinism.

    Per Amendment 1: FAISS with HNSW or IVF can return different results
    without locked parameters. This config ensures reproducibility.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    index_snapshot_required: bool = True
    search_params_locked: bool = True
    tie_breaking: Literal["doc_id_ascending", "score_descending", "timestamp_descending"] = "doc_id_ascending"
    random_seed: int | None = None  # For HNSW
    nprobe: int | None = None       # For IVF
    ef_search: int | None = None    # For HNSW


# =============================================================================
# SCORING POLICY (Amendment 2)
# =============================================================================

class ScoringPolicy(BaseModel):
    """
    Scoring policy for constraint penalties.

    Per Amendment 2: Soft-drop penalty is configurable, not hardcoded at 0.1.
    Different domains may need different penalties.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    soft_drop_penalty_weight: float = Field(default=0.1, ge=0.0, le=1.0)
    soft_drop_penalty_function: Literal["multiplicative", "additive"] = "multiplicative"
    soft_drop_penalty_cap: float = Field(default=0.5, ge=0.0, le=1.0)
    log_penalty_in_audit: bool = True


# =============================================================================
# DERIVATION RULES
# =============================================================================

class DerivationCondition(BaseCondition):
    """Condition for evidence type derivation. Inherits from BaseCondition."""
    pass


class DerivationRule(BaseModel):
    """
    Rule for deriving evidence types from document features.

    Derivation rules are declarative + LLM validated.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    rule_id: str
    conditions: list[DerivationCondition]
    any_of: list[DerivationCondition] | None = None  # Alternative conditions
    result: list[EvidenceType]
    validate_with_llm: bool = True

    # Traceability
    source: str = "gptl_derivation_rule"


# =============================================================================
# MODEL POLICY
# =============================================================================

class EscalationTrigger(BaseModel):
    """Trigger conditions for model escalation."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    confidence_lt: float | None = None
    query_complexity: Literal["low", "medium", "high"] | None = None
    intent_categories: list[IntentCategory] | None = None
    evidence_conflict_detected: bool | None = None


class ModelPolicyEntry(BaseModel):
    """Model policy for a specific task."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    primary: ModelTier
    escalate_to: ModelTier | None = None
    escalation_trigger: EscalationTrigger | None = None


class ModelPolicy(BaseModel):
    """
    Complete model selection policy.

    Defines which Claude model to use for each task type.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    intent_classification: ModelPolicyEntry = Field(
        default_factory=lambda: ModelPolicyEntry(
            primary=ModelTier.SONNET,
            escalate_to=ModelTier.OPUS,
            escalation_trigger=EscalationTrigger(confidence_lt=0.7)
        )
    )

    synthesis: ModelPolicyEntry = Field(
        default_factory=lambda: ModelPolicyEntry(
            primary=ModelTier.SONNET,
            escalate_to=ModelTier.OPUS,
            escalation_trigger=EscalationTrigger(
                intent_categories=[IntentCategory.FAILURE_PREDICTION, IntentCategory.LIABILITY_ASSESSMENT],
                evidence_conflict_detected=True
            )
        )
    )

    feature_extraction: ModelPolicyEntry = Field(
        default_factory=lambda: ModelPolicyEntry(primary=ModelTier.HAIKU, escalate_to=None)
    )

    semantic_checks: ModelPolicyEntry = Field(
        default_factory=lambda: ModelPolicyEntry(
            primary=ModelTier.HAIKU,
            escalate_to=ModelTier.SONNET,
            escalation_trigger=EscalationTrigger()
        )
    )

    anomaly_explanation: ModelPolicyEntry = Field(
        default_factory=lambda: ModelPolicyEntry(primary=ModelTier.SONNET, escalate_to=None)
    )

    confidence_calibration: ModelPolicyEntry = Field(
        default_factory=lambda: ModelPolicyEntry(primary=ModelTier.SONNET, escalate_to=None)
    )


# =============================================================================
# DOMAIN PACK
# =============================================================================

class EvidenceTaxonomy(BaseModel):
    """Evidence type taxonomy for a domain."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    primary: list[EvidenceType] = Field(default_factory=list)
    supporting: list[EvidenceType] = Field(default_factory=list)
    contextual: list[EvidenceType] = Field(default_factory=list)
    noise: list[EvidenceType] = Field(default_factory=list)


class LLMPolicies(BaseModel):
    """LLM usage policies for a domain."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    l0_derivation_validation: bool = True
    l2_intent_always_llm: bool = True
    l3_semantic_checks_enabled: bool = True
    l4_anomaly_explanation: bool = True
    l5_confidence_calibration: bool = True


class DomainPack(BaseModel):
    """
    Domain-specific configuration pack.

    GPTL core is domain-agnostic. All domain knowledge lives in Domain Packs.
    """
    model_config = {"extra": "forbid", "populate_by_name": True}

    domain_id: str
    version: str
    config_hash: str = ""  # Computed from content

    model_policy: ModelPolicy = Field(default_factory=ModelPolicy)
    evidence_taxonomy: EvidenceTaxonomy = Field(default_factory=EvidenceTaxonomy)
    evidence_derivation: list[DerivationRule] = Field(default_factory=list)

    constraints: dict[str, list[ConstraintRule]] = Field(
        default_factory=lambda: {"hard_drop": [], "soft_drop": []}
    )

    intent_frames: list[IntentFrame] = Field(default_factory=list)
    scoring_policy: ScoringPolicy = Field(default_factory=ScoringPolicy)
    llm_policies: LLMPolicies = Field(default_factory=LLMPolicies)
    retrieval_determinism: RetrievalDeterminismConfig = Field(
        default_factory=RetrievalDeterminismConfig
    )

    # Traceability
    source: str = "gptl_domain_pack"

    def compute_config_hash(self) -> str:
        """Compute hash of the domain pack for determinism."""
        # Serialize for hashing (exclude hash field itself)
        content = self.model_dump_json(exclude={"config_hash"})
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @model_validator(mode="after")
    def set_config_hash(self) -> "DomainPack":
        """Set config_hash after validation."""
        if not self.config_hash:
            self.config_hash = self.compute_config_hash()
        return self


# =============================================================================
# HAIKU VALIDATION RESPONSES
# =============================================================================

class DerivationValidationResponse(BaseModel):
    """Response from Haiku derivation validation."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    valid: bool
    corrected_types: list[EvidenceType] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class SemanticCheckResponse(BaseModel):
    """Response from Haiku semantic constraint check."""
    model_config = {"extra": "forbid", "populate_by_name": True}

    decision: Literal["KEEP", "ELIMINATE", "DEPRIORITIZE"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "EvidenceType",
    "DocType",
    "DateSource",
    "ConstraintAction",
    "IntentCategory",
    "ModelTier",
    "ConditionOperator",

    # DocFeatures
    "EntitySet",
    "DocFlags",
    "DocFeatures",

    # Intent
    "EvidenceRequirements",
    "IntentFrame",
    "IntentClassificationResult",

    # Shared Condition Base
    "BaseCondition",

    # Constraints
    "ConstraintCondition",
    "CompoundCondition",
    "ConstraintRule",
    "ConstraintViolation",
    "ViolationReport",

    # Intelligence
    "EvidenceCitation",
    "IntelligenceOutput",

    # Audit
    "ModelCall",
    "AuditTrail",
    "GPTLMetrics",

    # API
    "GPTLRequest",
    "GPTLResponse",

    # Determinism & Scoring
    "RetrievalDeterminismConfig",
    "ScoringPolicy",

    # Derivation
    "DerivationCondition",
    "DerivationRule",

    # Model Policy
    "EscalationTrigger",
    "ModelPolicyEntry",
    "ModelPolicy",

    # Domain Pack
    "EvidenceTaxonomy",
    "LLMPolicies",
    "DomainPack",

    # Validation Responses
    "DerivationValidationResponse",
    "SemanticCheckResponse",
]
