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
GPTL L5 Synthesis Engine
========================

Produces actionable intelligence from L3 survivors and L4 signals.

Philosophy:
    "Translate evidence into bounded, auditable intelligence"

Features:
- Sonnet-first synthesis with Opus escalation for safety-critical
- Confidence calibration with explicit uncertainty
- Evidence citation with source tracing
- Refusal on insufficient evidence

Compliance: SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from gptl.schema import (
    DomainPack,
    EvidenceCitation,
    EvidenceType,
    IntelligenceOutput,
    IntentClassificationResult,
    ModelCall,
    ModelTier,
)
from gptl.claude_client import BaseClaudeClient, get_default_client
from gptl.prompts import get_prompt, format_evidence_for_synthesis
from gptl.negative_selection import Candidate
from gptl.signal_extraction import Signal, SignalExtractionResult, SignalType

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIDENCE CALIBRATION
# =============================================================================

@dataclass
class CalibrationResult:
    """Result of confidence calibration."""
    calibrated_confidence: float
    uncertainty_factors: list[str]
    evidence_quality: float  # 0-1
    source_diversity: float  # 0-1
    temporal_relevance: float  # 0-1


class ConfidenceCalibrator:
    """
    Calibrates confidence based on evidence quality.

    Factors:
    - Number and quality of sources
    - Source diversity (types, dates, authorities)
    - Temporal relevance
    - Contradiction presence
    """

    def __init__(
        self,
        min_sources: int = 2,
        max_confidence_single_source: float = 0.7,
    ):
        self.min_sources = min_sources
        self.max_confidence_single_source = max_confidence_single_source

    def calibrate(
        self,
        raw_confidence: float,
        evidence: list[Candidate],
        signals: list[Signal],
    ) -> CalibrationResult:
        """
        Calibrate confidence based on evidence.

        Returns:
            CalibrationResult with adjusted confidence
        """
        uncertainty_factors: list[str] = []

        # Source count factor
        source_count = len(evidence)
        if source_count < self.min_sources:
            uncertainty_factors.append(f"Only {source_count} source(s)")
            source_factor = self.max_confidence_single_source
        else:
            source_factor = min(1.0, 0.6 + 0.1 * source_count)

        # Source diversity (unique doc types)
        doc_types = set(
            c.features.doc_type.value if c.features.doc_type else "unknown"
            for c in evidence
        )
        source_diversity = min(1.0, len(doc_types) / 3)
        if source_diversity < 0.5:
            uncertainty_factors.append("Low source diversity")

        # Temporal relevance
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=365)
        recent_count = sum(
            1 for c in evidence
            if c.features.primary_date and c.features.primary_date >= cutoff
        )
        temporal_relevance = recent_count / max(1, source_count)
        if temporal_relevance < 0.5:
            uncertainty_factors.append("Sources may be outdated")

        # Contradiction detection from signals
        contradictions = [
            s for s in signals
            if s.signal_type.value in ("contradiction", "anomaly")
        ]
        if contradictions:
            uncertainty_factors.append("Conflicting evidence detected")
            contradiction_penalty = 0.2 * len(contradictions)
        else:
            contradiction_penalty = 0.0

        # Calculate calibrated confidence
        evidence_quality = (source_factor + source_diversity + temporal_relevance) / 3
        calibrated = raw_confidence * evidence_quality * (1 - contradiction_penalty)
        calibrated = max(0.0, min(1.0, calibrated))

        return CalibrationResult(
            calibrated_confidence=calibrated,
            uncertainty_factors=uncertainty_factors,
            evidence_quality=evidence_quality,
            source_diversity=source_diversity,
            temporal_relevance=temporal_relevance,
        )


# =============================================================================
# CITATION BUILDER
# =============================================================================

# Type alias for content provider function
ContentProvider = Callable[[str], str | None]


class CitationBuilder:
    """Builds evidence citations for intelligence output.

    Can optionally use a content_provider to extract real document excerpts.
    """

    def __init__(self, content_provider: ContentProvider | None = None):
        """
        Args:
            content_provider: Optional function that takes doc_id and returns content
        """
        self.content_provider = content_provider

    def build_citations(
        self,
        evidence: list[Candidate],
        query_context: str,
    ) -> list[EvidenceCitation]:
        """
        Build citations from evidence candidates.

        Returns:
            List of EvidenceCitation objects
        """
        citations: list[EvidenceCitation] = []

        for i, candidate in enumerate(evidence):
            # Determine evidence type from doc features
            evidence_type = self._infer_evidence_type(candidate)

            citation = EvidenceCitation(
                doc_id=candidate.doc_id,
                evidence_type=evidence_type,
                snippet=self._extract_excerpt(candidate, query_context),
                relevance_score=candidate.current_score,  # P0 FIX: Use current_score, not .score
            )
            citations.append(citation)

        return citations

    def _infer_evidence_type(self, candidate: Candidate) -> EvidenceType:
        """Infer evidence type from document features."""
        # First check derived evidence types from features
        if candidate.features.derived_evidence_types:
            # Return the first (most relevant) derived type
            return candidate.features.derived_evidence_types[0]

        if not candidate.features.doc_type:
            return EvidenceType.UNKNOWN

        doc_type = candidate.features.doc_type.value.lower()

        # Map doc_type to evidence type
        type_mapping = {
            "specification": EvidenceType.SPECIFICATION,
            "standard": EvidenceType.SPECIFICATION,
            "requirement": EvidenceType.SPECIFICATION,
            "report": EvidenceType.TEST_REPORT,
            "test_report": EvidenceType.TEST_REPORT,
            "data": EvidenceType.DATASHEET,
            "datasheet": EvidenceType.DATASHEET,
            "memo": EvidenceType.INTERNAL_MEMO,
            "email": EvidenceType.EMAIL,
            "drawing": EvidenceType.DRAWING,
            "manual": EvidenceType.TECHNICAL_MANUAL,
            "procedure": EvidenceType.TECHNICAL_MANUAL,
            "marketing": EvidenceType.MARKETING_BROCHURE,
        }

        return type_mapping.get(doc_type, EvidenceType.UNKNOWN)

    def _extract_excerpt(
        self,
        candidate: Candidate,
        query_context: str,
        max_length: int = 300,
    ) -> str:
        """Extract relevant excerpt from candidate using entity anchoring.

        Strategies (in order of preference):
        1. Entity-anchored: Find entity mention and extract surrounding context
        2. Query keyword matching: Find query keywords and extract context
        3. Fallback: Return first N characters of content

        Args:
            candidate: The evidence candidate
            query_context: The query for keyword matching
            max_length: Maximum excerpt length

        Returns:
            Relevant excerpt from document or placeholder
        """
        # If no content provider, return placeholder
        if not self.content_provider:
            return f"[Evidence from {candidate.doc_id}]"

        content = self.content_provider(candidate.doc_id)
        if not content:
            return f"[Content unavailable for {candidate.doc_id}]"

        # Strategy 1: Entity-anchored extraction
        all_entities = (
            candidate.features.entities.materials +
            candidate.features.entities.standards +
            candidate.features.entities.hazards +
            candidate.features.entities.systems
        )

        for entity in all_entities:
            idx = content.lower().find(entity.lower())
            if idx != -1:
                start = max(0, idx - 150)
                end = min(len(content), idx + 150)
                excerpt = content[start:end].strip()
                prefix = "..." if start > 0 else ""
                suffix = "..." if end < len(content) else ""
                return f"{prefix}{excerpt}{suffix}"

        # Strategy 2: Query keyword matching
        keywords = [w for w in query_context.split() if len(w) >= 4][:5]
        for keyword in keywords:
            idx = content.lower().find(keyword.lower())
            if idx != -1:
                start = max(0, idx - 150)
                end = min(len(content), idx + 150)
                excerpt = content[start:end].strip()
                prefix = "..." if start > 0 else ""
                suffix = "..." if end < len(content) else ""
                return f"{prefix}{excerpt}{suffix}"

        # Strategy 3: Fallback - first N characters
        if len(content) > max_length:
            return content[:max_length].strip() + "..."
        return content.strip()


# =============================================================================
# SYNTHESIS ENGINE
# =============================================================================

@dataclass
class SynthesisResult:
    """Result from L5 synthesis."""
    intelligence: IntelligenceOutput
    calibration: CalibrationResult
    model_calls: list[ModelCall] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None


class SynthesisEngine:
    """
    L5 Synthesis: Evidence -> Actionable Intelligence.

    Uses:
    1. Confidence calibration
    2. Sonnet synthesis (or Opus for safety-critical)
    3. Citation building with real excerpt extraction
    4. Comprehensive refusal on insufficient/low-quality evidence
    """

    # Keywords that indicate time-sensitive queries
    TIME_SENSITIVE_KEYWORDS = frozenset([
        "current", "latest", "now", "recent", "today",
        "2024", "2025", "this year", "updated",
    ])

    # Critical evidence types that require diverse sources
    CRITICAL_EVIDENCE_TYPES = frozenset([
        EvidenceType.FAILURE_ANALYSIS,
        EvidenceType.CERTIFICATION,
    ])

    def __init__(
        self,
        domain_pack: DomainPack,
        client: BaseClaudeClient | None = None,
        content_provider: ContentProvider | None = None,
        min_evidence_count: int = 2,  # P0 FIX: Require at least 2 sources for reliability
        min_confidence: float = 0.5,  # P0 FIX: Raise threshold from 0.3 to 0.5
        use_opus_for_critical: bool = True,
        # Refusal thresholds
        min_source_diversity_critical: float = 0.5,
        max_contradiction_ratio: float = 0.5,
        min_temporal_relevance_for_time_sensitive: float = 0.3,
    ):
        self.domain_pack = domain_pack
        self.client = client or get_default_client()
        self.content_provider = content_provider
        self.min_evidence_count = min_evidence_count
        self.min_confidence = min_confidence
        self.use_opus_for_critical = use_opus_for_critical

        # Refusal thresholds
        self.min_source_diversity_critical = min_source_diversity_critical
        self.max_contradiction_ratio = max_contradiction_ratio
        self.min_temporal_relevance_for_time_sensitive = min_temporal_relevance_for_time_sensitive

        self.calibrator = ConfidenceCalibrator()
        self.citation_builder = CitationBuilder(content_provider=content_provider)

    def synthesize(
        self,
        query: str,
        intent: IntentClassificationResult,
        evidence: list[Candidate],
        signals: SignalExtractionResult,
        is_safety_critical: bool = False,
    ) -> SynthesisResult:
        """
        Synthesize intelligence from evidence and signals.

        Args:
            query: Original user query
            intent: Classified intent from L2
            evidence: L3 survivors
            signals: L4 extracted signals
            is_safety_critical: Force Opus usage

        Returns:
            SynthesisResult with intelligence or refusal
        """
        model_calls: list[ModelCall] = []

        # =================================================================
        # REFUSAL CONDITION 1: Evidence Count
        # =================================================================
        if len(evidence) < self.min_evidence_count:
            return SynthesisResult(
                intelligence=self._create_refusal_intelligence(
                    query,
                    refusal_type="evidence_count",
                    reason=f"Insufficient evidence: {len(evidence)} documents found, minimum {self.min_evidence_count} required",
                ),
                calibration=CalibrationResult(
                    calibrated_confidence=0.0,
                    uncertainty_factors=["Insufficient evidence"],
                    evidence_quality=0.0,
                    source_diversity=0.0,
                    temporal_relevance=0.0,
                ),
                refused=True,
                refusal_reason=f"Insufficient evidence: {len(evidence)} documents found, minimum {self.min_evidence_count} required",
            )

        # Calibrate confidence
        raw_confidence = intent.confidence
        calibration = self.calibrator.calibrate(
            raw_confidence=raw_confidence,
            evidence=evidence,
            signals=signals.signals,
        )

        # =================================================================
        # REFUSAL CONDITION 2: Low Confidence
        # =================================================================
        if calibration.calibrated_confidence < self.min_confidence:
            return SynthesisResult(
                intelligence=self._create_refusal_intelligence(
                    query,
                    refusal_type="confidence",
                    reason=f"Confidence too low: {calibration.calibrated_confidence:.2f} < {self.min_confidence}",
                ),
                calibration=calibration,
                refused=True,
                refusal_reason=f"Confidence too low: {calibration.calibrated_confidence:.2f} < {self.min_confidence}",
            )

        # =================================================================
        # REFUSAL CONDITION 3: High Contradiction Rate
        # =================================================================
        contradiction_signals = [
            s for s in signals.signals
            if s.signal_type == SignalType.CONTRADICTION or s.signal_type == SignalType.ANOMALY
        ]
        contradiction_ratio = len(contradiction_signals) / max(1, len(evidence))

        if contradiction_ratio > self.max_contradiction_ratio:
            # High contradiction with low confidence = refuse
            if calibration.calibrated_confidence < 0.6:
                return SynthesisResult(
                    intelligence=self._create_refusal_intelligence(
                        query,
                        refusal_type="contradiction",
                        reason=f"Cannot synthesize: {len(contradiction_signals)} contradictions detected with low confidence ({calibration.calibrated_confidence:.2f})",
                    ),
                    calibration=calibration,
                    refused=True,
                    refusal_reason=f"High contradiction rate ({contradiction_ratio:.0%}) with low confidence",
                )

        # =================================================================
        # REFUSAL CONDITION 4: Stale Data for Time-Sensitive Queries
        # =================================================================
        if self._is_time_sensitive_query(query):
            if calibration.temporal_relevance < self.min_temporal_relevance_for_time_sensitive:
                return SynthesisResult(
                    intelligence=self._create_refusal_intelligence(
                        query,
                        refusal_type="stale_data",
                        reason=f"Evidence too old for time-sensitive query: only {calibration.temporal_relevance:.0%} of sources are recent",
                    ),
                    calibration=calibration,
                    refused=True,
                    refusal_reason=f"Time-sensitive query with stale evidence ({calibration.temporal_relevance:.0%} recent)",
                )

        # =================================================================
        # REFUSAL CONDITION 5: Missing Critical Evidence Types
        # =================================================================
        if intent.evidence_requirements and intent.evidence_requirements.types:
            missing_critical = self._check_missing_critical_types(
                evidence=evidence,
                required_types=intent.evidence_requirements.types,
            )
            if missing_critical:
                return SynthesisResult(
                    intelligence=self._create_refusal_intelligence(
                        query,
                        refusal_type="missing_critical_type",
                        reason=f"Missing required evidence types: {[t.value for t in missing_critical]}",
                    ),
                    calibration=calibration,
                    refused=True,
                    refusal_reason=f"Missing critical evidence types: {[t.value for t in missing_critical]}",
                )

        # =================================================================
        # REFUSAL CONDITION 6: Low Source Diversity for Safety-Critical
        # =================================================================
        if is_safety_critical and calibration.source_diversity < self.min_source_diversity_critical:
            return SynthesisResult(
                intelligence=self._create_refusal_intelligence(
                    query,
                    refusal_type="source_diversity",
                    reason=f"Safety-critical query requires diverse sources (got {calibration.source_diversity:.0%}, need {self.min_source_diversity_critical:.0%})",
                ),
                calibration=calibration,
                refused=True,
                refusal_reason=f"Insufficient source diversity for safety-critical query ({calibration.source_diversity:.0%} < {self.min_source_diversity_critical:.0%})",
            )

        # Determine model tier
        tier = ModelTier.SONNET
        if is_safety_critical and self.use_opus_for_critical:
            tier = ModelTier.OPUS
        # P0 FIX: Check for critical evidence types instead of non-existent safety_critical flag
        elif any(
            EvidenceType.FAILURE_ANALYSIS in c.features.derived_evidence_types
            or EvidenceType.CERTIFICATION in c.features.derived_evidence_types
            for c in evidence
        ):
            tier = ModelTier.OPUS

        # Build citations
        citations = self.citation_builder.build_citations(evidence, query)

        # LLM synthesis
        intelligence, call = self._llm_synthesize(
            query=query,
            intent=intent,
            evidence=evidence,
            signals=signals,
            tier=tier,
            calibration=calibration,
        )
        model_calls.append(call)

        # Update intelligence with citations (field is 'evidence' per schema)
        intelligence.evidence = citations
        intelligence.confidence = calibration.calibrated_confidence

        return SynthesisResult(
            intelligence=intelligence,
            calibration=calibration,
            model_calls=model_calls,
            refused=False,
        )

    def _llm_synthesize(
        self,
        query: str,
        intent: IntentClassificationResult,
        evidence: list[Candidate],
        signals: SignalExtractionResult,
        tier: ModelTier,
        calibration: CalibrationResult,
    ) -> tuple[IntelligenceOutput, ModelCall]:
        """Call LLM for synthesis."""
        # Choose prompt based on safety criticality
        if tier == ModelTier.OPUS:
            prompt_template = get_prompt("L5_SYNTHESIS_CRITICAL_V1")
        else:
            prompt_template = get_prompt("L5_SYNTHESIS_V1")

        # Format evidence for prompt
        evidence_text = format_evidence_for_synthesis(evidence)

        # Format signals
        signal_text = "\n".join([
            f"- {s.signal_type.value}: {s.description} (confidence: {s.confidence:.2f})"
            for s in signals.signals[:5]
        ])

        # Format uncertainty
        uncertainty_text = "\n".join([
            f"- {factor}" for factor in calibration.uncertainty_factors
        ]) or "None identified"

        prompt = prompt_template.template.format(
            query=query,
            intent=intent.frame_id,  # P0 FIX: Use frame_id, not primary_intent
            evidence=evidence_text,
            signals=signal_text,
            uncertainty_factors=uncertainty_text,
            evidence_quality=f"{calibration.evidence_quality:.2f}",
            domain_name=self.domain_pack.domain_id,  # P0 FIX: Use domain_id, not name
        )

        response = self.client.call_json(
            prompt=prompt,
            tier=tier,
            system=f"You are synthesizing intelligence for the {self.domain_pack.domain_id} domain. Be precise, cite sources, express uncertainty.",
        )

        # Parse response
        data = response.data if response.parse_success else {}

        # Build IntelligenceOutput matching schema (finding, implication, action, timeline)
        intelligence = IntelligenceOutput(
            finding=data.get("finding", data.get("answer", "Unable to synthesize answer")),
            implication=data.get("implication", ""),
            action=data.get("action", ""),
            timeline=data.get("timeline", ""),
            confidence=calibration.calibrated_confidence,
            confidence_drivers=data.get("confidence_drivers", calibration.uncertainty_factors),
            evidence=[],  # Will be set by caller via citations
        )

        call = ModelCall(
            model=tier,
            layer="L5",
            purpose="synthesis",
            latency_ms=response.raw.latency_ms,
            tokens_in=response.raw.tokens_in,
            tokens_out=response.raw.tokens_out,
        )

        return intelligence, call

    def _is_time_sensitive_query(self, query: str) -> bool:
        """Detect if query cares about recency.

        Args:
            query: The user query

        Returns:
            True if query contains time-sensitive keywords
        """
        query_lower = query.lower()
        return any(kw in query_lower for kw in self.TIME_SENSITIVE_KEYWORDS)

    def _check_missing_critical_types(
        self,
        evidence: list[Candidate],
        required_types: list[EvidenceType],
    ) -> list[EvidenceType]:
        """Check if required critical evidence types are present.

        Args:
            evidence: List of evidence candidates
            required_types: Required evidence types from intent

        Returns:
            List of missing critical evidence types
        """
        # Only check for critical types that are both required AND critical
        required_critical = [
            t for t in required_types
            if t in self.CRITICAL_EVIDENCE_TYPES
        ]

        if not required_critical:
            return []

        # Collect all evidence types present
        present_types: set[EvidenceType] = set()
        for c in evidence:
            present_types.update(c.features.derived_evidence_types)

        # Return missing critical types
        return [t for t in required_critical if t not in present_types]

    def _create_refusal_intelligence(
        self,
        query: str,
        refusal_type: Literal[
            "evidence_count",
            "confidence",
            "contradiction",
            "stale_data",
            "missing_critical_type",
            "source_diversity",
        ],
        reason: str,
    ) -> IntelligenceOutput:
        """Create intelligence output for refusal.

        Args:
            query: The original query
            refusal_type: Type of refusal condition triggered
            reason: Human-readable reason for refusal

        Returns:
            IntelligenceOutput with refusal information
        """
        return IntelligenceOutput(
            finding="",
            implication="",
            action="",
            timeline="",
            confidence=0.0,
            evidence=[],
            confidence_drivers=[reason],
            insufficient_evidence=True,
            refusal_reason=reason,
            refusal_type=refusal_type,
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_synthesis_engine(
    domain_pack: DomainPack,
    client: BaseClaudeClient | None = None,
    **kwargs,
) -> SynthesisEngine:
    """Factory function for SynthesisEngine."""
    return SynthesisEngine(
        domain_pack=domain_pack,
        client=client,
        **kwargs,
    )


__all__ = [
    # Types
    "ContentProvider",
    # Calibration
    "CalibrationResult",
    "ConfidenceCalibrator",
    # Citation
    "CitationBuilder",
    # Synthesis
    "SynthesisResult",
    "SynthesisEngine",
    # Factory
    "create_synthesis_engine",
]
