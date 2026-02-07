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
GPTL Negative Selection Engine - L3 Constraint Cascade
========================================================

The core of GPTL: subtract the 80% that CANNOT be relevant.

Two-Stage Negative Selection:
- Stage A: Pre-Retrieval Gate (O(1), metadata-only) - builds index filters
- Stage B: Post-Retrieval Gate (O(N), feature + LLM) - eliminates/deprioritizes

Cascade Strategy (Quality-Ordered):
1. Metadata filter (O(1)): doc_type, partitions, date bounds
2. Feature filter (O(N)): tags, entity presence, evidence markers
3. Semantic filter (O(N x Haiku)): LLM-assisted ambiguous cases
4. Heuristic text (O(N), last resort): regex

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from gptl.claude_client import BaseClaudeClient, get_default_client
from gptl.evidence_taxonomy import evaluate_condition
from gptl.prompts import L3_SEMANTIC_CHECK_V1
from gptl.schema import (
    BaseCondition,
    CompoundCondition,
    ConditionOperator,
    ConstraintAction,
    ConstraintCondition,
    ConstraintRule,
    ConstraintViolation,
    DocFeatures,
    EvidenceType,
    IntentFrame,
    ModelTier,
    ScoringPolicy,
    SemanticCheckResponse,
    ViolationReport,
)

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# CANDIDATE WRAPPER
# =============================================================================

@dataclass
class Candidate:
    """
    A document candidate with features and score.

    Wraps DocFeatures with retrieval score and penalty tracking.
    """
    features: DocFeatures
    initial_score: float
    current_score: float = 0.0
    eliminated: bool = False
    elimination_reason: str | None = None
    elimination_rule: str | None = None
    penalties_applied: list[tuple[str, float]] = field(default_factory=list)
    semantic_check_used: bool = False
    semantic_check_result: str | None = None
    semantic_check_confidence: float | None = None

    def __post_init__(self):
        if self.current_score == 0.0:
            self.current_score = self.initial_score

    @property
    def doc_id(self) -> str:
        return self.features.doc_id

    @property
    def total_penalty(self) -> float:
        """Total penalty applied."""
        return sum(p for _, p in self.penalties_applied)

    def apply_penalty(self, rule_id: str, penalty: float, policy: ScoringPolicy):
        """Apply a penalty according to scoring policy."""
        # Cap the penalty
        actual_penalty = min(penalty, policy.soft_drop_penalty_cap)

        if policy.soft_drop_penalty_function == "multiplicative":
            self.current_score *= (1.0 - actual_penalty)
        else:  # additive
            self.current_score -= actual_penalty
            self.current_score = max(0.0, self.current_score)

        self.penalties_applied.append((rule_id, actual_penalty))

    def eliminate(self, reason: str, rule_id: str):
        """Mark candidate as eliminated."""
        self.eliminated = True
        self.elimination_reason = reason
        self.elimination_rule = rule_id
        self.current_score = 0.0


# =============================================================================
# CONSTRAINT EVALUATOR (Strategy Pattern)
# =============================================================================

class ConstraintEvaluator(ABC):
    """Base class for constraint evaluation strategies."""

    @abstractmethod
    def evaluate(
        self,
        candidate: Candidate,
        rule: ConstraintRule,
        context: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Evaluate if a candidate violates a constraint.

        Returns:
            Tuple of (violated, reason)
        """
        pass


class FeatureConstraintEvaluator(ConstraintEvaluator):
    """Evaluates constraints based on DocFeatures."""

    def evaluate_compound(
        self,
        compound: CompoundCondition,
        features: DocFeatures,
    ) -> bool:
        """
        Evaluate compound condition with AND/OR logic.

        Args:
            compound: CompoundCondition with nested logic
            features: DocFeatures to evaluate against

        Returns:
            True if the compound condition is satisfied
        """
        results: list[bool] = []

        for cond in compound.conditions:
            if isinstance(cond, CompoundCondition):
                # Recursive evaluation for nested compounds
                result = self.evaluate_compound(cond, features)
            else:
                # Simple ConstraintCondition
                result = evaluate_condition(cond, features)
                if cond.negate:
                    result = not result
            results.append(result)

        # Apply operator
        if compound.operator == ConditionOperator.AND:
            final = all(results)
        else:  # OR
            final = any(results)

        # Apply negation if specified
        return not final if compound.negate else final

    def evaluate(
        self,
        candidate: Candidate,
        rule: ConstraintRule,
        context: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Evaluate feature-based constraint.

        Supports both:
        - list[ConstraintCondition]: Simple list with implicit AND
        - CompoundCondition: Nested AND/OR logic
        """
        features = candidate.features

        # Handle CompoundCondition
        if isinstance(rule.conditions, CompoundCondition):
            violated = self.evaluate_compound(rule.conditions, features)
            if violated:
                reason = f"Compound condition ({rule.conditions.operator.value})"
                return True, reason
            return False, ""

        # Handle list[ConstraintCondition] (backward compatible - implicit AND)
        for condition in rule.conditions:
            result = evaluate_condition(condition, features)

            # Handle negation
            if condition.negate:
                result = not result

            if not result:
                # Condition not met = constraint not violated
                return False, ""

        # All conditions met = constraint violated
        reason = f"Matched conditions: {[c.field for c in rule.conditions]}"
        return True, reason


class SemanticConstraintEvaluator(ConstraintEvaluator):
    """Evaluates constraints using LLM semantic check."""

    def __init__(
        self,
        client: BaseClaudeClient | None = None,
        content_provider: Callable[[str], str] | None = None,
    ):
        self.client = client
        self.content_provider = content_provider

    def evaluate(
        self,
        candidate: Candidate,
        rule: ConstraintRule,
        context: dict[str, Any],
    ) -> tuple[bool, str]:
        """Evaluate using Haiku semantic check."""
        if not self.client:
            # P0 FIX: Semantic check required but client missing is an error, not silent pass
            # For safety-critical systems, we must not silently skip required checks
            error_msg = (
                f"Semantic check required for rule '{rule.rule_id}' but no Claude client "
                f"configured. Cannot evaluate constraint for doc '{candidate.doc_id}'."
            )
            logger.error(error_msg)
            # Record that semantic check was SKIPPED (not passed) in candidate metadata
            candidate.semantic_check_used = True
            candidate.semantic_check_result = "SKIPPED_NO_CLIENT"
            candidate.semantic_check_confidence = 0.0
            # Conservative: treat missing client as violation to avoid false positives
            return True, f"Semantic check skipped (no client): {error_msg}"

        features = candidate.features
        intent_frame: IntentFrame | None = context.get("intent_frame")
        decision_question = intent_frame.decision_question if intent_frame else context.get("query", "")
        required_evidence = intent_frame.evidence_requirements.types if intent_frame else []

        # Get content sample
        content_sample = ""
        if self.content_provider:
            content_sample = self.content_provider(features.doc_id)

        # Format prompt
        prompt = L3_SEMANTIC_CHECK_V1.format(
            decision_question=decision_question,
            required_evidence=[e.value for e in required_evidence],
            doc_id=features.doc_id,
            doc_type=features.doc_type.value,
            evidence_types=[e.value for e in features.derived_evidence_types],
            domain_scores=features.domain_scores,
            tags=features.tags,
            content_sample=content_sample[:500],
        )

        response = self.client.call_json(prompt, ModelTier.HAIKU)

        if not response.parse_success:
            logger.warning(f"Semantic check parse failed: {response.parse_error}")
            return False, ""

        data = response.data
        decision = data.get("decision", "KEEP")
        confidence = data.get("confidence", 0.5)
        reasoning = data.get("reasoning", "")

        # Record semantic check in candidate
        candidate.semantic_check_used = True
        candidate.semantic_check_result = decision
        candidate.semantic_check_confidence = confidence

        if decision == "ELIMINATE":
            return True, f"Semantic check: {reasoning}"
        elif decision == "DEPRIORITIZE":
            # Return special signal for soft penalty
            return False, f"DEPRIORITIZE:{reasoning}"

        return False, ""


# =============================================================================
# FILTER INDEX BUILDER (Pre-Retrieval Gate)
# =============================================================================

@dataclass
class FilterIndex:
    """
    Filter specification for vector index query.

    Used to build pre-retrieval filters (Stage A).
    """
    forbidden_doc_types: list[str] = field(default_factory=list)
    required_doc_types: list[str] = field(default_factory=list)
    min_domain_score: dict[str, float] = field(default_factory=dict)
    exclude_noise_candidates: bool = True
    date_after: str | None = None
    date_before: str | None = None
    required_tags: list[str] = field(default_factory=list)
    forbidden_tags: list[str] = field(default_factory=list)

    def to_faiss_filter(self) -> dict[str, Any]:
        """Convert to FAISS-compatible filter dict."""
        # This would be adapted to the specific vector store implementation
        filters = {}

        if self.forbidden_doc_types:
            filters["doc_type"] = {"$nin": self.forbidden_doc_types}
        elif self.required_doc_types:
            filters["doc_type"] = {"$in": self.required_doc_types}

        if self.exclude_noise_candidates:
            filters["is_noise_candidate"] = {"$ne": True}

        for domain, min_score in self.min_domain_score.items():
            filters[f"domain_scores.{domain}"] = {"$gte": min_score}

        return filters

    def to_milvus_expr(self) -> str:
        """Convert to Milvus filter expression."""
        expressions = []

        if self.forbidden_doc_types:
            types_str = ", ".join(f'"{t}"' for t in self.forbidden_doc_types)
            expressions.append(f"doc_type not in [{types_str}]")

        if self.exclude_noise_candidates:
            expressions.append("is_noise_candidate == false")

        for domain, min_score in self.min_domain_score.items():
            expressions.append(f"domain_scores_{domain} >= {min_score}")

        return " and ".join(expressions) if expressions else ""


class FilterIndexBuilder:
    """
    Builds pre-retrieval filters from constraints and intent.

    Stage A: O(1) metadata-only filtering before vector search.
    """

    def build(
        self,
        constraints: dict[str, list[ConstraintRule]],
        intent_frame: IntentFrame | None = None,
        domain_id: str | None = None,
    ) -> FilterIndex:
        """
        Build a FilterIndex from constraints and intent.

        Args:
            constraints: Dict with "hard_drop" and "soft_drop" lists
            intent_frame: Optional intent frame for context
            domain_id: Optional domain for domain_score filtering

        Returns:
            FilterIndex for pre-retrieval
        """
        filter_index = FilterIndex()

        # Process hard_drop constraints for pre-retrieval eligibility
        for rule in constraints.get("hard_drop", []):
            # Only simple, metadata-only constraints can be pre-retrieval
            if self._is_metadata_only(rule):
                self._apply_to_filter(rule, filter_index)

        # Apply intent-based filters
        if intent_frame:
            # Filter by applicable constraints
            for constraint_id in intent_frame.constraint_ids:
                # Look up constraint in both hard and soft
                for rule_list in constraints.values():
                    for rule in rule_list:
                        if rule.rule_id == constraint_id and self._is_metadata_only(rule):
                            self._apply_to_filter(rule, filter_index)

        # Apply domain score filter
        if domain_id:
            filter_index.min_domain_score[domain_id] = 0.1  # Minimum relevance

        return filter_index

    def _is_metadata_only(self, rule: ConstraintRule) -> bool:
        """Check if rule can be evaluated from metadata only."""
        # CompoundConditions are too complex for pre-retrieval filtering
        if isinstance(rule.conditions, CompoundCondition):
            return False

        metadata_fields = {
            "doc_type",
            "flags.is_noise_candidate",
            "domain_scores",
            "date_value",
            "tags",
        }

        for condition in rule.conditions:
            # Check if field is metadata-accessible
            field_root = condition.field.split(".")[0]
            if field_root not in metadata_fields and not condition.field.startswith("domain_scores."):
                return False

        return True

    def _apply_to_filter(self, rule: ConstraintRule, filter_index: FilterIndex):
        """Apply a rule to the filter index."""
        # Skip CompoundConditions - they're handled in post-retrieval
        if isinstance(rule.conditions, CompoundCondition):
            return

        for condition in rule.conditions:
            if condition.field == "doc_type":
                if condition.operator == "eq":
                    if rule.action == ConstraintAction.HARD_DROP:
                        filter_index.forbidden_doc_types.append(condition.value)
                elif condition.operator == "in":
                    if rule.action == ConstraintAction.HARD_DROP:
                        filter_index.forbidden_doc_types.extend(condition.value)

            elif condition.field == "flags.is_noise_candidate":
                if condition.operator == "eq" and condition.value is True:
                    filter_index.exclude_noise_candidates = True

            elif condition.field.startswith("domain_scores."):
                domain = condition.field.split(".")[1]
                if condition.operator == "lt":
                    # If hard_drop when score < X, require score >= X
                    filter_index.min_domain_score[domain] = condition.value


# =============================================================================
# NEGATIVE SELECTION ENGINE
# =============================================================================

class NegativeSelectionEngine:
    """
    The core negative selection engine.

    Implements the two-stage cascade:
    - Stage A: Pre-retrieval filtering (FilterIndex)
    - Stage B: Post-retrieval elimination/deprioritization

    The goal is NOT cost reduction - it's QUALITY improvement:
    - Fewer docs = less noise in Claude's context
    - Fewer docs = faster response times
    - Fewer docs = more focused, accurate synthesis
    """

    def __init__(
        self,
        constraints: dict[str, list[ConstraintRule]],
        scoring_policy: ScoringPolicy,
        claude_client: BaseClaudeClient | None = None,
        content_provider: Callable[[str], str] | None = None,
    ):
        self.constraints = constraints
        self.scoring_policy = scoring_policy
        self.claude_client = claude_client
        self.content_provider = content_provider

        # Initialize evaluators
        self.feature_evaluator = FeatureConstraintEvaluator()
        self.semantic_evaluator = SemanticConstraintEvaluator(
            client=claude_client,
            content_provider=content_provider,
        )

        # Filter index builder
        self.filter_builder = FilterIndexBuilder()

    def build_pre_retrieval_filter(
        self,
        intent_frame: IntentFrame | None = None,
        domain_id: str | None = None,
    ) -> FilterIndex:
        """
        Build pre-retrieval filter (Stage A).

        Call this BEFORE vector search to exclude candidates early.
        """
        return self.filter_builder.build(
            self.constraints,
            intent_frame,
            domain_id,
        )

    def select(
        self,
        candidates: list[Candidate],
        intent_frame: IntentFrame | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[list[Candidate], ViolationReport]:
        """
        Apply negative selection to candidates (Stage B).

        This is the main entry point for post-retrieval filtering.

        Args:
            candidates: List of candidates with DocFeatures and scores
            intent_frame: Intent frame for context-aware filtering
            context: Additional context (query, user_id, etc.)

        Returns:
            Tuple of (survivors, violation_report)
        """
        context = context or {}
        if intent_frame:
            context["intent_frame"] = intent_frame

        violations: list[ConstraintViolation] = []
        rules_triggered: set[str] = set()

        # Sort rules by priority (lower = higher priority)
        all_rules = []
        for action_type, rules in self.constraints.items():
            for rule in rules:
                all_rules.append((rule.priority, action_type, rule))
        all_rules.sort(key=lambda x: x[0])

        # Apply cascade
        for _, action_type, rule in all_rules:
            # Check if rule applies to this intent
            if intent_frame and rule.applies_to_intents:
                if intent_frame.frame_id not in rule.applies_to_intents:
                    continue

            # Process each non-eliminated candidate
            for candidate in candidates:
                if candidate.eliminated:
                    continue

                # Choose evaluator
                if rule.requires_semantic_check:
                    violated, reason = self.semantic_evaluator.evaluate(
                        candidate, rule, context
                    )

                    # Handle DEPRIORITIZE signal from semantic check
                    if reason.startswith("DEPRIORITIZE:"):
                        self._apply_soft_penalty(candidate, rule, reason[13:])
                        continue
                else:
                    violated, reason = self.feature_evaluator.evaluate(
                        candidate, rule, context
                    )

                if violated:
                    rules_triggered.add(rule.rule_id)

                    if rule.action == ConstraintAction.HARD_DROP:
                        candidate.eliminate(reason, rule.rule_id)
                        violations.append(ConstraintViolation(
                            doc_id=candidate.doc_id,
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            action=ConstraintAction.HARD_DROP,
                            reason=reason,
                            semantic_check_used=candidate.semantic_check_used,
                            semantic_check_confidence=candidate.semantic_check_confidence,
                        ))

                    elif rule.action == ConstraintAction.SOFT_DROP:
                        self._apply_soft_penalty(candidate, rule, reason)
                        violations.append(ConstraintViolation(
                            doc_id=candidate.doc_id,
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            action=ConstraintAction.SOFT_DROP,
                            reason=reason,
                            penalty_applied=rule.penalty_weight or self.scoring_policy.soft_drop_penalty_weight,
                            semantic_check_used=candidate.semantic_check_used,
                            semantic_check_confidence=candidate.semantic_check_confidence,
                        ))

        # Build survivors list (non-eliminated, sorted by score)
        survivors = [c for c in candidates if not c.eliminated]
        survivors.sort(key=lambda c: c.current_score, reverse=True)

        # Build violation report
        eliminated_count = sum(1 for c in candidates if c.eliminated)
        deprioritized_count = sum(1 for c in candidates if not c.eliminated and c.penalties_applied)

        report = ViolationReport(
            total_candidates=len(candidates),
            candidates_eliminated=eliminated_count,
            candidates_deprioritized=deprioritized_count,
            survivors=len(survivors),
            violations=violations,
            rules_triggered=list(rules_triggered),
            post_retrieval_eliminated=eliminated_count,
        )

        logger.info(
            f"Negative selection: {len(candidates)} -> {len(survivors)} "
            f"(eliminated={eliminated_count}, deprioritized={deprioritized_count}, "
            f"reduction={report.reduction_ratio:.1%})"
        )

        return survivors, report

    def _apply_soft_penalty(
        self,
        candidate: Candidate,
        rule: ConstraintRule,
        reason: str,
    ):
        """Apply soft penalty to candidate."""
        penalty = rule.penalty_weight or self.scoring_policy.soft_drop_penalty_weight
        candidate.apply_penalty(rule.rule_id, penalty, self.scoring_policy)

        if self.scoring_policy.log_penalty_in_audit:
            logger.debug(
                f"Applied penalty {penalty:.2f} to {candidate.doc_id} "
                f"for rule {rule.rule_id}: {reason}"
            )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_candidates(
    features_list: list[DocFeatures],
    scores: list[float] | None = None,
) -> list[Candidate]:
    """
    Create Candidate objects from DocFeatures.

    Args:
        features_list: List of DocFeatures
        scores: Optional retrieval scores (defaults to 1.0)

    Returns:
        List of Candidate objects
    """
    if scores is None:
        scores = [1.0] * len(features_list)

    return [
        Candidate(features=f, initial_score=s)
        for f, s in zip(features_list, scores)
    ]


def create_negative_selection_engine(
    constraints: dict[str, list[ConstraintRule]],
    scoring_policy: ScoringPolicy | None = None,
    claude_client: BaseClaudeClient | None = None,
    content_provider: Callable[[str], str] | None = None,
) -> NegativeSelectionEngine:
    """
    Create a configured NegativeSelectionEngine.

    Args:
        constraints: Constraint rules dict
        scoring_policy: Scoring policy (uses default if None)
        claude_client: Claude client for semantic checks
        content_provider: Function to get content for doc_id

    Returns:
        Configured NegativeSelectionEngine
    """
    return NegativeSelectionEngine(
        constraints=constraints,
        scoring_policy=scoring_policy or ScoringPolicy(),
        claude_client=claude_client,
        content_provider=content_provider,
    )


__all__ = [
    # Candidate
    "Candidate",

    # Evaluators
    "ConstraintEvaluator",
    "FeatureConstraintEvaluator",
    "SemanticConstraintEvaluator",

    # Pre-retrieval
    "FilterIndex",
    "FilterIndexBuilder",

    # Main engine
    "NegativeSelectionEngine",

    # Factory
    "create_candidates",
    "create_negative_selection_engine",
]
