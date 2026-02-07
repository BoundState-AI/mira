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
GPTL Evidence Taxonomy - Evidence types, derivation rules, and validation
==========================================================================

Implements the evidence taxonomy system for GPTL:
- Evidence type classification by signal strength
- Declarative derivation rules (rule-based + LLM validation)
- Integration point for Haiku derivation validation

The evidence taxonomy ensures:
1. Documents are classified by their evidence value
2. Derivation rules are transparent and auditable
3. LLM validation catches edge cases

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from gptl.schema import (
    DerivationCondition,
    DerivationRule,
    DerivationValidationResponse,
    DocFeatures,
    DocFlags,
    DocType,
    EvidenceTaxonomy,
    EvidenceType,
)

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# EVIDENCE TYPE METADATA
# =============================================================================

@dataclass
class EvidenceTypeInfo:
    """Metadata about an evidence type."""
    evidence_type: EvidenceType
    signal_tier: str  # "primary", "supporting", "contextual", "noise"
    signal_weight: float  # 0.0 to 1.0
    description: str
    typical_characteristics: list[str] = field(default_factory=list)


# Global registry of evidence type metadata
EVIDENCE_TYPE_REGISTRY: dict[EvidenceType, EvidenceTypeInfo] = {
    # Primary (high signal)
    EvidenceType.TEST_REPORT: EvidenceTypeInfo(
        evidence_type=EvidenceType.TEST_REPORT,
        signal_tier="primary",
        signal_weight=1.0,
        description="Document containing test results with measurements and conditions",
        typical_characteristics=[
            "has_measurements",
            "has_test_conditions",
            "has_tables",
            "has_figures",
        ],
    ),
    EvidenceType.SPECIFICATION: EvidenceTypeInfo(
        evidence_type=EvidenceType.SPECIFICATION,
        signal_tier="primary",
        signal_weight=1.0,
        description="Technical specification defining requirements or properties",
        typical_characteristics=[
            "has_spec_references",
            "has_tables",
            "doc_type == specification",
        ],
    ),
    EvidenceType.FAILURE_ANALYSIS: EvidenceTypeInfo(
        evidence_type=EvidenceType.FAILURE_ANALYSIS,
        signal_tier="primary",
        signal_weight=1.0,
        description="Document analyzing failure modes or incidents",
        typical_characteristics=[
            "has_figures",
            "has_measurements",
            "entities.hazards not empty",
        ],
    ),
    EvidenceType.COMPATIBILITY_MATRIX: EvidenceTypeInfo(
        evidence_type=EvidenceType.COMPATIBILITY_MATRIX,
        signal_tier="primary",
        signal_weight=1.0,
        description="Matrix showing material or component compatibility",
        typical_characteristics=[
            "has_tables",
            "entities.materials not empty",
        ],
    ),
    EvidenceType.CERTIFICATION: EvidenceTypeInfo(
        evidence_type=EvidenceType.CERTIFICATION,
        signal_tier="primary",
        signal_weight=0.95,
        description="Certification or qualification document",
        typical_characteristics=[
            "has_spec_references",
            "entities.standards not empty",
        ],
    ),

    # Supporting (medium signal)
    EvidenceType.TECHNICAL_MANUAL: EvidenceTypeInfo(
        evidence_type=EvidenceType.TECHNICAL_MANUAL,
        signal_tier="supporting",
        signal_weight=0.7,
        description="Technical manual with procedures or specifications",
        typical_characteristics=[
            "doc_type == manual",
            "has_figures",
        ],
    ),
    EvidenceType.WORK_ORDER: EvidenceTypeInfo(
        evidence_type=EvidenceType.WORK_ORDER,
        signal_tier="supporting",
        signal_weight=0.6,
        description="Work order or manufacturing instruction",
        typical_characteristics=[
            "entities.processes not empty",
        ],
    ),
    EvidenceType.DRAWING: EvidenceTypeInfo(
        evidence_type=EvidenceType.DRAWING,
        signal_tier="supporting",
        signal_weight=0.7,
        description="Technical drawing or CAD document",
        typical_characteristics=[
            "doc_type == drawing",
            "has_figures",
        ],
    ),
    EvidenceType.DATASHEET: EvidenceTypeInfo(
        evidence_type=EvidenceType.DATASHEET,
        signal_tier="supporting",
        signal_weight=0.75,
        description="Product or material datasheet",
        typical_characteristics=[
            "has_tables",
            "has_measurements",
            "entities.materials not empty",
        ],
    ),

    # Contextual (lower signal)
    EvidenceType.INTERNAL_MEMO: EvidenceTypeInfo(
        evidence_type=EvidenceType.INTERNAL_MEMO,
        signal_tier="contextual",
        signal_weight=0.4,
        description="Internal communication or memo",
        typical_characteristics=[
            "doc_type == memo",
        ],
    ),
    EvidenceType.MEETING_NOTES: EvidenceTypeInfo(
        evidence_type=EvidenceType.MEETING_NOTES,
        signal_tier="contextual",
        signal_weight=0.3,
        description="Notes from meetings or discussions",
        typical_characteristics=[],
    ),
    EvidenceType.EMAIL: EvidenceTypeInfo(
        evidence_type=EvidenceType.EMAIL,
        signal_tier="contextual",
        signal_weight=0.25,
        description="Email correspondence",
        typical_characteristics=[
            "doc_type == email",
        ],
    ),

    # Noise candidates
    EvidenceType.MARKETING_BROCHURE: EvidenceTypeInfo(
        evidence_type=EvidenceType.MARKETING_BROCHURE,
        signal_tier="noise",
        signal_weight=0.1,
        description="Marketing or promotional material",
        typical_characteristics=[
            "doc_type == marketing",
            "is_noise_candidate",
        ],
    ),
    EvidenceType.NEWS_ARTICLE: EvidenceTypeInfo(
        evidence_type=EvidenceType.NEWS_ARTICLE,
        signal_tier="noise",
        signal_weight=0.1,
        description="News or press article",
        typical_characteristics=[
            "is_noise_candidate",
        ],
    ),
    EvidenceType.WEB_CONTENT: EvidenceTypeInfo(
        evidence_type=EvidenceType.WEB_CONTENT,
        signal_tier="noise",
        signal_weight=0.05,
        description="Generic web content",
        typical_characteristics=[
            "is_noise_candidate",
        ],
    ),
    EvidenceType.UNKNOWN: EvidenceTypeInfo(
        evidence_type=EvidenceType.UNKNOWN,
        signal_tier="contextual",
        signal_weight=0.2,
        description="Document type could not be determined",
        typical_characteristics=[],
    ),
}


def get_evidence_type_info(evidence_type: EvidenceType) -> EvidenceTypeInfo:
    """Get metadata for an evidence type."""
    return EVIDENCE_TYPE_REGISTRY.get(
        evidence_type,
        EVIDENCE_TYPE_REGISTRY[EvidenceType.UNKNOWN]
    )


def get_signal_weight(evidence_type: EvidenceType) -> float:
    """Get the signal weight for an evidence type."""
    return get_evidence_type_info(evidence_type).signal_weight


def get_signal_tier(evidence_type: EvidenceType) -> str:
    """Get the signal tier for an evidence type."""
    return get_evidence_type_info(evidence_type).signal_tier


def is_noise_type(evidence_type: EvidenceType) -> bool:
    """Check if an evidence type is considered noise."""
    return get_signal_tier(evidence_type) == "noise"


def is_primary_type(evidence_type: EvidenceType) -> bool:
    """Check if an evidence type is a primary signal."""
    return get_signal_tier(evidence_type) == "primary"


# =============================================================================
# CONDITION EVALUATORS
# =============================================================================

def _get_nested_value(obj: Any, path: str) -> Any:
    """
    Get a nested value from an object using dot notation.

    Examples:
        _get_nested_value(doc_features, "flags.has_measurements")
        _get_nested_value(doc_features, "doc_type")
        _get_nested_value(doc_features, "entities.materials")
    """
    parts = path.split(".")
    current = obj

    for part in parts:
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None

    return current


def evaluate_condition(condition: DerivationCondition, features: DocFeatures) -> bool:
    """
    Evaluate a single derivation condition against document features.

    Operators:
        - eq: Equal
        - neq: Not equal
        - in: Value is in list
        - contains: List contains value
        - lt: Less than
        - gt: Greater than
        - lte: Less than or equal
        - gte: Greater than or equal
        - regex: Regex match
        - exists: Value is not None
        - empty: List is empty
    """
    actual_value = _get_nested_value(features, condition.field)
    expected_value = condition.value
    operator = condition.operator.lower()

    result = False

    if operator == "eq":
        # Handle enum comparison
        if hasattr(actual_value, "value"):
            result = actual_value.value == expected_value
        else:
            result = actual_value == expected_value

    elif operator == "neq":
        if hasattr(actual_value, "value"):
            result = actual_value.value != expected_value
        else:
            result = actual_value != expected_value

    elif operator == "in":
        # actual_value should be in expected_value (a list)
        if hasattr(actual_value, "value"):
            result = actual_value.value in expected_value
        else:
            result = actual_value in expected_value

    elif operator == "contains":
        # expected_value should be in actual_value (a list)
        if isinstance(actual_value, (list, tuple, set)):
            result = expected_value in actual_value
        elif isinstance(actual_value, str):
            result = expected_value in actual_value
        else:
            result = False

    elif operator == "lt":
        result = actual_value is not None and actual_value < expected_value

    elif operator == "gt":
        result = actual_value is not None and actual_value > expected_value

    elif operator == "lte":
        result = actual_value is not None and actual_value <= expected_value

    elif operator == "gte":
        result = actual_value is not None and actual_value >= expected_value

    elif operator == "regex":
        if isinstance(actual_value, str):
            result = bool(re.search(expected_value, actual_value, re.IGNORECASE))
        else:
            result = False

    elif operator == "exists":
        result = actual_value is not None

    elif operator == "empty":
        if isinstance(actual_value, (list, tuple, set, dict)):
            result = len(actual_value) == 0
        elif actual_value is None:
            result = True
        elif isinstance(actual_value, str):
            result = len(actual_value.strip()) == 0
        else:
            result = False

    elif operator == "not_empty":
        if isinstance(actual_value, (list, tuple, set, dict)):
            result = len(actual_value) > 0
        elif actual_value is None:
            result = False
        elif isinstance(actual_value, str):
            result = len(actual_value.strip()) > 0
        else:
            result = True

    else:
        logger.warning(f"Unknown operator: {operator}")
        result = False

    return result


# =============================================================================
# DERIVATION ENGINE
# =============================================================================

class DerivationEngine:
    """
    Engine for deriving evidence types from document features.

    The derivation process:
    1. Apply declarative rules to DocFeatures
    2. Optionally validate with LLM (Haiku)
    3. Return final evidence types

    Compliance: SWE-032, SWE-033
    """

    def __init__(
        self,
        rules: list[DerivationRule],
        taxonomy: EvidenceTaxonomy | None = None,
        llm_validator: Callable[[DocFeatures, list[EvidenceType], str], DerivationValidationResponse] | None = None,
    ):
        """
        Initialize the derivation engine.

        Args:
            rules: List of derivation rules to apply
            taxonomy: Evidence taxonomy for the domain
            llm_validator: Optional callback for LLM validation
        """
        self.rules = rules
        self.taxonomy = taxonomy
        self.llm_validator = llm_validator
        logger.info(f"DerivationEngine initialized with {len(rules)} rules")

    def derive(
        self,
        features: DocFeatures,
        content_sample: str = "",
        validate_with_llm: bool = True,
    ) -> tuple[list[EvidenceType], float]:
        """
        Derive evidence types for a document.

        Args:
            features: Document features
            content_sample: Sample of document content for LLM validation
            validate_with_llm: Whether to use LLM validation

        Returns:
            Tuple of (evidence_types, confidence)
        """
        # Step 1: Apply declarative rules
        derived_types = self._apply_rules(features)

        if not derived_types:
            derived_types = [EvidenceType.UNKNOWN]

        confidence = 0.8  # Base confidence for rule-based derivation

        # Step 2: LLM validation if enabled and validator provided
        if validate_with_llm and self.llm_validator and content_sample:
            rules_requiring_validation = [
                r for r in self.rules if r.validate_with_llm
            ]

            if rules_requiring_validation:
                validation_result = self.llm_validator(
                    features, derived_types, content_sample
                )

                if validation_result.valid:
                    confidence = max(confidence, validation_result.confidence)
                else:
                    # Use corrected types from LLM
                    if validation_result.corrected_types:
                        derived_types = validation_result.corrected_types
                        confidence = validation_result.confidence
                        logger.info(
                            f"LLM corrected derivation for {features.doc_id}: "
                            f"{[t.value for t in derived_types]}"
                        )

        # Step 3: Filter to known taxonomy if available
        if self.taxonomy:
            all_known = (
                set(self.taxonomy.primary) |
                set(self.taxonomy.supporting) |
                set(self.taxonomy.contextual) |
                set(self.taxonomy.noise)
            )
            derived_types = [t for t in derived_types if t in all_known]

            if not derived_types:
                derived_types = [EvidenceType.UNKNOWN]

        return derived_types, confidence

    def _apply_rules(self, features: DocFeatures) -> list[EvidenceType]:
        """Apply derivation rules and return matched evidence types."""
        matched_types: set[EvidenceType] = set()

        for rule in self.rules:
            if self._rule_matches(rule, features):
                matched_types.update(rule.result)
                logger.debug(
                    f"Rule {rule.rule_id} matched for {features.doc_id}: "
                    f"{[t.value for t in rule.result]}"
                )

        return list(matched_types)

    def _rule_matches(self, rule: DerivationRule, features: DocFeatures) -> bool:
        """Check if a derivation rule matches the document features."""
        # All main conditions must match
        conditions_match = all(
            evaluate_condition(c, features) for c in rule.conditions
        )

        if not conditions_match:
            return False

        # If any_of is specified, at least one must match
        if rule.any_of:
            any_match = any(
                evaluate_condition(c, features) for c in rule.any_of
            )
            return any_match

        return True

    def explain_derivation(
        self,
        features: DocFeatures
    ) -> list[dict[str, Any]]:
        """
        Explain why specific evidence types were derived.

        Returns a list of explanations for each matched rule.
        """
        explanations = []

        for rule in self.rules:
            condition_results = []
            all_match = True

            for c in rule.conditions:
                result = evaluate_condition(c, features)
                condition_results.append({
                    "field": c.field,
                    "operator": c.operator,
                    "expected": c.value,
                    "actual": _get_nested_value(features, c.field),
                    "matched": result,
                })
                if not result:
                    all_match = False

            any_of_results = []
            if rule.any_of and all_match:
                any_matched = False
                for c in rule.any_of:
                    result = evaluate_condition(c, features)
                    any_of_results.append({
                        "field": c.field,
                        "operator": c.operator,
                        "expected": c.value,
                        "actual": _get_nested_value(features, c.field),
                        "matched": result,
                    })
                    if result:
                        any_matched = True
                all_match = any_matched

            if all_match:
                explanations.append({
                    "rule_id": rule.rule_id,
                    "result": [t.value for t in rule.result],
                    "conditions": condition_results,
                    "any_of": any_of_results if rule.any_of else None,
                    "validate_with_llm": rule.validate_with_llm,
                })

        return explanations


# =============================================================================
# DEFAULT DERIVATION RULES
# =============================================================================

def get_default_derivation_rules() -> list[DerivationRule]:
    """
    Get the default derivation rules.

    These rules are used when no domain-specific rules are provided.
    """
    return [
        # Test Report: has measurements + test conditions
        DerivationRule(
            rule_id="derive_test_report",
            conditions=[
                DerivationCondition(field="flags.has_measurements", operator="eq", value=True),
                DerivationCondition(field="flags.has_test_conditions", operator="eq", value=True),
            ],
            result=[EvidenceType.TEST_REPORT],
            validate_with_llm=True,
        ),

        # Specification: doc_type is specification + has spec references
        DerivationRule(
            rule_id="derive_specification",
            conditions=[
                DerivationCondition(field="doc_type", operator="eq", value="specification"),
                DerivationCondition(field="flags.has_spec_references", operator="eq", value=True),
            ],
            result=[EvidenceType.SPECIFICATION],
            validate_with_llm=True,
        ),

        # Datasheet: has tables + has measurements + has materials
        DerivationRule(
            rule_id="derive_datasheet",
            conditions=[
                DerivationCondition(field="flags.has_tables", operator="eq", value=True),
                DerivationCondition(field="flags.has_measurements", operator="eq", value=True),
            ],
            any_of=[
                DerivationCondition(field="entities.materials", operator="not_empty", value=True),
            ],
            result=[EvidenceType.DATASHEET],
            validate_with_llm=True,
        ),

        # Drawing: doc_type is drawing
        DerivationRule(
            rule_id="derive_drawing",
            conditions=[
                DerivationCondition(field="doc_type", operator="eq", value="drawing"),
            ],
            result=[EvidenceType.DRAWING],
            validate_with_llm=False,
        ),

        # Technical Manual: doc_type is manual
        DerivationRule(
            rule_id="derive_technical_manual",
            conditions=[
                DerivationCondition(field="doc_type", operator="eq", value="manual"),
            ],
            result=[EvidenceType.TECHNICAL_MANUAL],
            validate_with_llm=False,
        ),

        # Marketing/Noise: doc_type is marketing OR noise candidate
        DerivationRule(
            rule_id="derive_marketing_noise",
            conditions=[],
            any_of=[
                DerivationCondition(field="doc_type", operator="eq", value="marketing"),
                DerivationCondition(field="flags.is_noise_candidate", operator="eq", value=True),
                DerivationCondition(field="noise_markers", operator="contains", value="cta_detected"),
            ],
            result=[EvidenceType.MARKETING_BROCHURE],
            validate_with_llm=False,  # Clear-cut, no LLM needed
        ),

        # Email
        DerivationRule(
            rule_id="derive_email",
            conditions=[
                DerivationCondition(field="doc_type", operator="eq", value="email"),
            ],
            result=[EvidenceType.EMAIL],
            validate_with_llm=False,
        ),

        # Memo
        DerivationRule(
            rule_id="derive_memo",
            conditions=[
                DerivationCondition(field="doc_type", operator="eq", value="memo"),
            ],
            result=[EvidenceType.INTERNAL_MEMO],
            validate_with_llm=False,
        ),

        # Compatibility Matrix: has tables + has materials (plural)
        DerivationRule(
            rule_id="derive_compatibility_matrix",
            conditions=[
                DerivationCondition(field="flags.has_tables", operator="eq", value=True),
            ],
            any_of=[
                DerivationCondition(field="entities.materials", operator="gte", value=2),
            ],
            result=[EvidenceType.COMPATIBILITY_MATRIX],
            validate_with_llm=True,
        ),

        # Failure Analysis: has hazards entities
        DerivationRule(
            rule_id="derive_failure_analysis",
            conditions=[
                DerivationCondition(field="entities.hazards", operator="not_empty", value=True),
            ],
            any_of=[
                DerivationCondition(field="flags.has_figures", operator="eq", value=True),
                DerivationCondition(field="flags.has_measurements", operator="eq", value=True),
            ],
            result=[EvidenceType.FAILURE_ANALYSIS],
            validate_with_llm=True,
        ),

        # Certification: has standards entities + has spec references
        DerivationRule(
            rule_id="derive_certification",
            conditions=[
                DerivationCondition(field="entities.standards", operator="not_empty", value=True),
                DerivationCondition(field="flags.has_spec_references", operator="eq", value=True),
            ],
            result=[EvidenceType.CERTIFICATION],
            validate_with_llm=True,
        ),
    ]


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_derivation_engine(
    rules: list[DerivationRule] | None = None,
    taxonomy: EvidenceTaxonomy | None = None,
    llm_validator: Callable | None = None,
) -> DerivationEngine:
    """
    Create a derivation engine with the specified configuration.

    Args:
        rules: Derivation rules (uses defaults if None)
        taxonomy: Evidence taxonomy
        llm_validator: Optional LLM validation callback

    Returns:
        Configured DerivationEngine
    """
    if rules is None:
        rules = get_default_derivation_rules()

    return DerivationEngine(
        rules=rules,
        taxonomy=taxonomy,
        llm_validator=llm_validator,
    )


__all__ = [
    # Types and metadata
    "EvidenceTypeInfo",
    "EVIDENCE_TYPE_REGISTRY",
    "get_evidence_type_info",
    "get_signal_weight",
    "get_signal_tier",
    "is_noise_type",
    "is_primary_type",

    # Condition evaluation
    "evaluate_condition",

    # Derivation engine
    "DerivationEngine",
    "get_default_derivation_rules",
    "create_derivation_engine",
]
