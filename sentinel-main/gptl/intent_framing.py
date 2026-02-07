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
GPTL L2 Intent Framing Engine
=============================

Maps surface queries to real questions using domain-specific intent frames.
Reuses patterns from boundstate_core.nlp.intent_classifier.

Philosophy:
    "Surface question -> Real question -> Evidence requirements"

Features:
- Sonnet-first classification with Opus escalation
- Domain-specific intent frames from DomainPack
- Heuristic pre-classification to reduce LLM calls
- Disambiguation for ambiguous intents

Compliance: SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from gptl.schema import (
    DomainPack,
    EvidenceRequirements,
    EvidenceType,
    IntentCategory,
    IntentClassificationResult,
    IntentFrame,
    ModelCall,
    ModelTier,
)
from gptl.claude_client import BaseClaudeClient, get_default_client
from gptl.prompts import (
    get_prompt,
    format_intent_frames_for_classification,
)

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# HEURISTIC PATTERNS (from boundstate_core.nlp.intent_classifier)
# =============================================================================

HEURISTIC_PATTERNS: dict[str, list[tuple[re.Pattern, float]]] = {
    "specification_lookup": [
        (re.compile(r"\b(shall|must|requirement|tolerance|conform)\b", re.IGNORECASE), 3.0),
        (re.compile(r"\bNASA-STD-\d+\b", re.IGNORECASE), 4.0),
        (re.compile(r"\bMIL-STD-\d+\b", re.IGNORECASE), 4.0),
        (re.compile(r"\b(spec|specification|standard)\b", re.IGNORECASE), 2.5),
    ],
    "material_selection": [
        (re.compile(r"\b(material|alloy|metal|polymer|composite)\b", re.IGNORECASE), 3.0),
        (re.compile(r"\b(tml|cvcm|outgassing|hydrogen|cryogenic)\b", re.IGNORECASE), 2.5),
        (re.compile(r"\b(select|choose|which|best)\b", re.IGNORECASE), 2.0),
    ],
    "test_result_query": [
        (re.compile(r"\b(test|result|pass|fail|data)\b", re.IGNORECASE), 2.5),
        (re.compile(r"\bASTM|E595|6001\b", re.IGNORECASE), 3.0),
        (re.compile(r"\b(specimen|method|report)\b", re.IGNORECASE), 2.0),
    ],
    "comparison": [
        (re.compile(r"\bcompare|versus|vs\.?\b", re.IGNORECASE), 4.0),
        (re.compile(r"\bbetter than|difference|similar to\b", re.IGNORECASE), 3.0),
    ],
    "procedural": [
        (re.compile(r"\bhow (do|to|can)\b", re.IGNORECASE), 3.0),
        (re.compile(r"\b(procedure|step|instruction|process)\b", re.IGNORECASE), 2.5),
    ],
    "compliance_check": [
        (re.compile(r"\b(comply|compliance|conform|meet)\b", re.IGNORECASE), 3.0),
        (re.compile(r"\b(requirement|regulation|standard)\b", re.IGNORECASE), 2.0),
    ],
}

NEGATIVE_PATTERNS: dict[str, list[tuple[re.Pattern, float]]] = {
    "specification_lookup": [
        (re.compile(r"\binvoice|payment|contract\b", re.IGNORECASE), -3.0),
    ],
    "material_selection": [
        (re.compile(r"\binvoice|billing|payment\b", re.IGNORECASE), -2.0),
    ],
}


# =============================================================================
# HEURISTIC CLASSIFIER
# =============================================================================

@dataclass
class HeuristicResult:
    """Result from heuristic pre-classification."""
    scores: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    high_confidence: bool = False
    best_intent: str | None = None
    best_score: float = 0.0


def heuristic_classify(query: str) -> HeuristicResult:
    """
    Fast heuristic classification to reduce LLM calls.

    Returns high_confidence=True if score > 0.8, allowing LLM skip.
    """
    scores: dict[str, float] = {}
    evidence: list[str] = []

    query_lower = query.lower()

    for intent, patterns in HEURISTIC_PATTERNS.items():
        score = 0.0
        max_possible = sum(weight for _, weight in patterns)

        for pattern, weight in patterns:
            match = pattern.search(query)
            if match:
                score += weight
                snippet = query[max(0, match.start() - 10):match.end() + 10]
                evidence.append(f"{intent}:{snippet.strip()}")

        # Apply negatives
        for pattern, weight in NEGATIVE_PATTERNS.get(intent, []):
            if pattern.search(query):
                score += weight  # weight is negative

        if score > 0:
            normalized = min(1.0, score / max_possible)
            scores[intent] = normalized

    # Find best
    best_intent = None
    best_score = 0.0
    if scores:
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]

    return HeuristicResult(
        scores=scores,
        evidence=evidence[:5],
        high_confidence=best_score > 0.8,
        best_intent=best_intent,
        best_score=best_score,
    )


# =============================================================================
# INTENT FRAMING ENGINE
# =============================================================================

@dataclass
class IntentFramingResult:
    """Result from L2 intent framing."""
    classified: IntentClassificationResult
    matched_frame: IntentFrame | None
    model_calls: list[ModelCall] = field(default_factory=list)
    heuristic_used: bool = False
    escalated: bool = False


class IntentFramingEngine:
    """
    L2 Intent Framing: Surface query -> Real question.

    Uses:
    1. Heuristic pre-classification for speed
    2. Sonnet for standard classification
    3. Opus escalation for ambiguous cases
    """

    def __init__(
        self,
        domain_pack: DomainPack,
        client: BaseClaudeClient | None = None,
        skip_llm_on_high_confidence: bool = True,
        ambiguity_threshold: float = 0.15,
    ):
        self.domain_pack = domain_pack
        self.client = client or get_default_client()
        self.skip_llm_on_high_confidence = skip_llm_on_high_confidence
        self.ambiguity_threshold = ambiguity_threshold

        # Build intent frame lookup by frame_id
        self._intent_frames: dict[str, IntentFrame] = {
            frame.frame_id: frame for frame in domain_pack.intent_frames
        }

    def classify(self, query: str) -> IntentFramingResult:
        """
        Classify query intent and match to domain intent frame.

        Returns:
            IntentFramingResult with classification and matched frame
        """
        model_calls: list[ModelCall] = []

        # Step 1: Heuristic pre-classification
        heuristic = heuristic_classify(query)

        if self.skip_llm_on_high_confidence and heuristic.high_confidence:
            # High confidence heuristic - skip LLM
            logger.info(
                f"Heuristic high-confidence: {heuristic.best_intent} "
                f"({heuristic.best_score:.2f})"
            )

            matched_frame = self._match_frame(heuristic.best_intent)

            # Use matched frame or create default values
            frame_id = matched_frame.frame_id if matched_frame else "heuristic_unknown"
            category = matched_frame.category if matched_frame else IntentCategory.GENERAL_QUERY
            decision_question = matched_frame.decision_question if matched_frame else "Unable to determine question"
            evidence_reqs = matched_frame.evidence_requirements if matched_frame else EvidenceRequirements()

            classification = IntentClassificationResult(
                frame_id=frame_id,
                category=category,
                decision_question=decision_question,
                confidence=heuristic.best_score,
                reasoning=f"Heuristic match: {', '.join(heuristic.evidence)}",
                evidence_requirements=evidence_reqs,
                model_used=ModelTier.HAIKU,  # Heuristic, no model used but need value
            )

            return IntentFramingResult(
                classified=classification,
                matched_frame=matched_frame,
                model_calls=model_calls,
                heuristic_used=True,
                escalated=False,
            )

        # Step 2: Sonnet classification
        classification, call = self._llm_classify(query, ModelTier.SONNET)
        model_calls.append(call)

        # Step 3: Check for ambiguity -> Opus escalation
        escalated = False
        if self._is_ambiguous(classification):
            logger.info("Ambiguous classification, escalating to Opus")
            classification, call = self._llm_classify(
                query,
                ModelTier.OPUS,
                escalated_from=ModelTier.SONNET,
            )
            model_calls.append(call)
            escalated = True

        # Match to domain frame
        matched_frame = self._match_frame(classification.frame_id)

        # Apply frame evidence requirements if not set
        if matched_frame and classification.evidence_requirements is None:
            classification.evidence_requirements = matched_frame.evidence_requirements

        return IntentFramingResult(
            classified=classification,
            matched_frame=matched_frame,
            model_calls=model_calls,
            heuristic_used=False,
            escalated=escalated,
        )

    def _llm_classify(
        self,
        query: str,
        tier: ModelTier,
        escalated_from: ModelTier | None = None,
    ) -> tuple[IntentClassificationResult, ModelCall]:
        """Call LLM for classification."""
        prompt_template = get_prompt("L2_INTENT_CLASSIFICATION_V1")

        # Format intent frames for prompt
        frames_text = format_intent_frames_for_classification(
            self.domain_pack.intent_frames
        )

        prompt = prompt_template.template.format(
            query=query,
            intent_frames=frames_text,
            domain_name=self.domain_pack.domain_id,
        )

        response = self.client.call_json(
            prompt=prompt,
            tier=tier,
            system=f"You are an intent classifier for the {self.domain_pack.domain_id} domain.",
        )

        # Parse response
        data = response.data if response.parse_success else {}

        # Parse evidence requirements from LLM response
        evidence_reqs = self._parse_evidence_requirements(
            data.get("evidence_requirements")
        ) or EvidenceRequirements()

        classification = IntentClassificationResult(
            frame_id=data.get("frame_id", data.get("primary_intent", "unknown")),
            category=IntentCategory(data.get("category", "general_query")),
            decision_question=data.get("decision_question", "Unable to determine"),
            confidence=data.get("confidence", 0.5),
            reasoning=data.get("reasoning", ""),
            evidence_requirements=evidence_reqs,
            escalate_to_opus=data.get("escalate_to_opus", False),
            model_used=tier,
        )

        call = ModelCall(
            model=tier,
            layer="L2",
            purpose="intent_classification",
            latency_ms=response.raw.latency_ms,
            tokens_in=response.raw.tokens_in,
            tokens_out=response.raw.tokens_out,
            escalated_from=escalated_from,
        )

        return classification, call

    def _is_ambiguous(self, result: IntentClassificationResult) -> bool:
        """Check if classification is ambiguous (needs Opus)."""
        # Low confidence
        if result.confidence < 0.6:
            return True

        # Multiple strong secondary intents close to primary
        # (Would need secondary confidence scores to implement fully)

        return False

    def _match_frame(self, intent_name: str) -> IntentFrame | None:
        """Match intent to domain frame."""
        # Direct match
        if intent_name in self._intent_frames:
            return self._intent_frames[intent_name]

        # Fuzzy match (contains)
        for frame_name, frame in self._intent_frames.items():
            if intent_name.lower() in frame_name.lower():
                return frame
            if frame_name.lower() in intent_name.lower():
                return frame

        return None

    def _parse_evidence_requirements(
        self, data: dict[str, Any] | None
    ) -> EvidenceRequirements | None:
        """Parse evidence requirements from LLM response."""
        if not data:
            return None

        try:
            # Parse evidence types from strings
            raw_types = data.get("types", data.get("required_types", []))
            evidence_types = []
            for t in raw_types:
                try:
                    evidence_types.append(EvidenceType(t))
                except ValueError:
                    logger.warning(f"Unknown evidence type: {t}")

            return EvidenceRequirements(
                types=evidence_types,
                min_count=data.get("min_count", data.get("min_sources", 1)),
                required_entity_classes=data.get("required_entity_classes", []),
            )
        except Exception as e:
            logger.warning(f"Failed to parse evidence requirements: {e}")
            return None


# =============================================================================
# DISAMBIGUATION ENGINE
# =============================================================================

class DisambiguationEngine:
    """
    Handles ambiguous queries by generating clarifying questions.

    Used when:
    - Multiple intent frames match with similar confidence
    - Query is underspecified
    - Domain requires additional context
    """

    def __init__(
        self,
        domain_pack: DomainPack,
        client: BaseClaudeClient | None = None,
    ):
        self.domain_pack = domain_pack
        self.client = client or get_default_client()

    def generate_clarification(
        self,
        query: str,
        candidate_intents: list[str],
    ) -> tuple[str, ModelCall]:
        """
        Generate a clarifying question for ambiguous query.

        Returns:
            Tuple of (clarifying_question, model_call)
        """
        prompt_template = get_prompt("L2_INTENT_DISAMBIGUATION_V1")

        prompt = prompt_template.template.format(
            query=query,
            candidate_intents=", ".join(candidate_intents),
            domain_name=self.domain_pack.domain_id,
        )

        response = self.client.call(
            prompt=prompt,
            tier=ModelTier.SONNET,
            system="Generate a concise clarifying question.",
        )

        # Response from call() is RawResponse, not JSONResponse
        call = ModelCall(
            model=ModelTier.SONNET,
            layer="L2",
            purpose="disambiguation",
            latency_ms=response.latency_ms,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
        )

        return response.content.strip(), call


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_intent_framing_engine(
    domain_pack: DomainPack,
    client: BaseClaudeClient | None = None,
    **kwargs,
) -> IntentFramingEngine:
    """Factory function for IntentFramingEngine."""
    return IntentFramingEngine(
        domain_pack=domain_pack,
        client=client,
        **kwargs,
    )


__all__ = [
    # Types
    "HeuristicResult",
    "IntentFramingResult",
    # Functions
    "heuristic_classify",
    # Engines
    "IntentFramingEngine",
    "DisambiguationEngine",
    # Factory
    "create_intent_framing_engine",
]
