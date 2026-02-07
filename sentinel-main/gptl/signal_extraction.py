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
GPTL L4 Signal Extraction Engine
================================

Extracts patterns and anomalies from documents that survived L3 filtering.

Philosophy:
    "Find the signal in survivors - temporal derivatives, anomalies, patterns"

Features:
- Temporal derivative analysis (what changed recently)
- Anomaly detection and explanation
- Cross-document pattern extraction
- Signal aggregation for L5 synthesis

Compliance: SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from gptl.schema import (
    DocFeatures,
    DomainPack,
    EvidenceType,
    ModelCall,
    ModelTier,
)
from gptl.claude_client import BaseClaudeClient, get_default_client
from gptl.prompts import get_prompt
from gptl.negative_selection import Candidate

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# SIGNAL TYPES
# =============================================================================

class SignalType(str, Enum):
    """Types of signals extracted from documents."""
    TEMPORAL_CHANGE = "temporal_change"
    ANOMALY = "anomaly"
    PATTERN = "pattern"
    CONTRADICTION = "contradiction"
    CLUSTER = "cluster"
    OUTLIER = "outlier"


class AnomalyType(str, Enum):
    """Types of detected anomalies."""
    MISSING_EXPECTED = "missing_expected"
    UNEXPECTED_VALUE = "unexpected_value"
    TEMPORAL_GAP = "temporal_gap"
    CROSS_DOC_CONFLICT = "cross_doc_conflict"
    STATISTICAL_OUTLIER = "statistical_outlier"


# =============================================================================
# SIGNAL DATA STRUCTURES
# =============================================================================

@dataclass
class Signal:
    """A signal extracted from document analysis."""
    signal_type: SignalType
    description: str
    confidence: float
    source_docs: list[str]  # doc_ids
    evidence: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TemporalDerivative:
    """Represents change over time in a document set."""
    field: str
    old_value: Any
    new_value: Any
    change_date: datetime | None
    doc_ids: list[str]
    significance: float  # 0-1


@dataclass
class Anomaly:
    """Detected anomaly in document set."""
    anomaly_type: AnomalyType
    description: str
    severity: float  # 0-1
    doc_ids: list[str]
    explanation: str | None = None


@dataclass
class SignalExtractionResult:
    """Result from L4 signal extraction."""
    signals: list[Signal]
    temporal_derivatives: list[TemporalDerivative]
    anomalies: list[Anomaly]
    model_calls: list[ModelCall] = field(default_factory=list)
    processing_stats: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# TEMPORAL ANALYSIS
# =============================================================================

class TemporalAnalyzer:
    """Analyzes temporal patterns and changes across documents."""

    def __init__(
        self,
        recency_window_days: int = 90,
        significance_threshold: float = 0.3,
    ):
        self.recency_window_days = recency_window_days
        self.significance_threshold = significance_threshold

    def analyze(
        self,
        candidates: list[Candidate],
    ) -> list[TemporalDerivative]:
        """
        Analyze temporal patterns across candidates.

        Looks for:
        - Recent changes (within recency window)
        - Version progression
        - Superseded documents
        """
        derivatives: list[TemporalDerivative] = []

        # Group by document type or entity
        by_type: dict[str, list[Candidate]] = {}
        for c in candidates:
            doc_type = c.features.doc_type.value if c.features.doc_type else "unknown"
            by_type.setdefault(doc_type, []).append(c)

        # Analyze each group for temporal patterns
        cutoff = datetime.now() - timedelta(days=self.recency_window_days)

        for doc_type, group in by_type.items():
            # Sort by date
            dated = [
                (c, c.features.date_value)
                for c in group
                if c.features.date_value
            ]
            dated.sort(key=lambda x: x[1])

            if len(dated) < 2:
                continue

            # Check for recent changes
            recent = [
                (c, d) for c, d in dated
                if d >= cutoff
            ]

            if recent:
                # Compare most recent to previous
                latest_c, latest_d = dated[-1]
                if len(dated) > 1:
                    prev_c, prev_d = dated[-2]

                    # Check for significant changes
                    if self._has_significant_change(prev_c.features, latest_c.features):
                        derivatives.append(TemporalDerivative(
                            field="document_update",
                            old_value=prev_c.doc_id,
                            new_value=latest_c.doc_id,
                            change_date=latest_d,
                            doc_ids=[prev_c.doc_id, latest_c.doc_id],
                            significance=0.7,
                        ))

        return derivatives

    def _has_significant_change(
        self,
        old_features: DocFeatures,
        new_features: DocFeatures,
    ) -> bool:
        """Check if features changed significantly."""
        # Check flag changes
        if old_features.flags != new_features.flags:
            return True

        # Check entity changes (materials + standards are key entities)
        old_ents = set(old_features.entities.materials + old_features.entities.standards)
        new_ents = set(new_features.entities.materials + new_features.entities.standards)
        if old_ents != new_ents:
            return True

        return False


# =============================================================================
# ANOMALY DETECTION
# =============================================================================

class AnomalyDetector:
    """Detects anomalies in document sets using heuristics and LLM."""

    def __init__(
        self,
        client: BaseClaudeClient | None = None,
        explain_anomalies: bool = True,
    ):
        self.client = client or get_default_client()
        self.explain_anomalies = explain_anomalies

    def detect(
        self,
        candidates: list[Candidate],
        expected_patterns: dict[str, Any] | None = None,
    ) -> tuple[list[Anomaly], list[ModelCall]]:
        """
        Detect anomalies in candidate set.

        Returns:
            Tuple of (anomalies, model_calls)
        """
        anomalies: list[Anomaly] = []
        model_calls: list[ModelCall] = []

        # Heuristic detection
        anomalies.extend(self._detect_heuristic(candidates, expected_patterns))

        # LLM explanation if enabled
        if self.explain_anomalies and anomalies:
            for anomaly in anomalies:
                explanation, call = self._explain_anomaly(anomaly, candidates)
                anomaly.explanation = explanation
                model_calls.append(call)

        return anomalies, model_calls

    def _detect_temporal_gaps(
        self,
        candidates: list[Candidate],
    ) -> list[Anomaly]:
        """Detect temporal gaps in document set."""
        anomalies: list[Anomaly] = []

        # Check for temporal gaps
        dates = [
            (c.doc_id, c.features.date_value)
            for c in candidates
            if c.features.date_value
        ]
        if len(dates) > 2:
            dates.sort(key=lambda x: x[1])
            for i in range(1, len(dates)):
                gap = (dates[i][1] - dates[i-1][1]).days
                if gap > 365:  # More than 1 year gap
                    anomalies.append(Anomaly(
                        anomaly_type=AnomalyType.TEMPORAL_GAP,
                        description=f"Gap of {gap} days between documents",
                        severity=min(1.0, gap / 730),  # Scale by 2 years
                        doc_ids=[dates[i-1][0], dates[i][0]],
                    ))

        return anomalies

    def _detect_cross_doc_conflicts(
        self,
        candidates: list[Candidate],
    ) -> list[Anomaly]:
        """Detect conflicting classifications in document set."""
        anomalies: list[Anomaly] = []

        # Check for conflicting document classifications (noise vs non-noise)
        noise_candidates = [
            c for c in candidates
            if c.features.flags.is_noise_candidate
        ]
        non_noise_candidates = [
            c for c in candidates
            if not c.features.flags.is_noise_candidate
        ]
        if noise_candidates and non_noise_candidates:
            # Potential conflict: noise and non-noise documents in same result set
            anomalies.append(Anomaly(
                anomaly_type=AnomalyType.CROSS_DOC_CONFLICT,
                description="Mixed noise classification in document set - some candidates flagged as noise",
                severity=0.4,
                doc_ids=[c.doc_id for c in noise_candidates[:2] + non_noise_candidates[:2]],
            ))

        return anomalies

    def _detect_missing_expected(
        self,
        candidates: list[Candidate],
        expected_patterns: dict[str, Any] | None,
    ) -> list[Anomaly]:
        """Detect when expected evidence types are missing."""
        if not expected_patterns:
            return []

        required_types = expected_patterns.get("required_evidence_types", [])
        if not required_types:
            return []

        # Collect all evidence types present
        present_types: set[EvidenceType] = set()
        for c in candidates:
            present_types.update(c.features.derived_evidence_types)

        # Check for missing required types
        missing = [t for t in required_types if t not in present_types]
        if missing:
            return [Anomaly(
                anomaly_type=AnomalyType.MISSING_EXPECTED,
                description=f"Missing required evidence types: {[t.value if hasattr(t, 'value') else str(t) for t in missing]}",
                severity=0.8,
                doc_ids=[c.doc_id for c in candidates[:3]],
            )]
        return []

    def _detect_statistical_outliers(
        self,
        candidates: list[Candidate],
    ) -> list[Anomaly]:
        """Detect statistical outliers using Z-score analysis."""
        import statistics

        if len(candidates) < 3:
            return []

        anomalies: list[Anomaly] = []

        # Get common domains across candidates
        common_domains = self._get_common_domains(candidates)

        # Analyze domain score distributions
        for domain in common_domains:
            scores = [c.features.domain_scores.get(domain, 0.5) for c in candidates]
            if len(set(scores)) < 2:
                continue

            try:
                mean = statistics.mean(scores)
                stdev = statistics.stdev(scores)
                if stdev == 0:
                    continue

                # Find outliers using Z-score threshold of 2.5
                outliers = [
                    (c.doc_id, score)
                    for c, score in zip(candidates, scores)
                    if abs((score - mean) / stdev) > 2.5
                ]

                if outliers:
                    anomalies.append(Anomaly(
                        anomaly_type=AnomalyType.STATISTICAL_OUTLIER,
                        description=f"Outliers in '{domain}' domain scores: {[(doc_id, f'{score:.2f}') for doc_id, score in outliers]}",
                        severity=min(1.0, len(outliers) / len(candidates)),
                        doc_ids=[doc_id for doc_id, _ in outliers],
                    ))
            except statistics.StatisticsError:
                # Not enough data for statistics
                continue

        return anomalies

    def _detect_unexpected_value(
        self,
        candidates: list[Candidate],
        expected_patterns: dict[str, Any] | None,
    ) -> list[Anomaly]:
        """Detect values outside expected ranges."""
        if not expected_patterns:
            return []

        bounds = expected_patterns.get("domain_score_bounds", {})
        if not bounds:
            return []

        anomalies: list[Anomaly] = []

        for domain, bound_tuple in bounds.items():
            if not isinstance(bound_tuple, (list, tuple)) or len(bound_tuple) != 2:
                continue

            min_val, max_val = bound_tuple
            violations = [
                (c.doc_id, c.features.domain_scores.get(domain, 0))
                for c in candidates
                if not (min_val <= c.features.domain_scores.get(domain, 0) <= max_val)
            ]

            if violations:
                anomalies.append(Anomaly(
                    anomaly_type=AnomalyType.UNEXPECTED_VALUE,
                    description=f"Domain '{domain}' scores outside [{min_val}, {max_val}]: {[(doc_id, f'{score:.2f}') for doc_id, score in violations]}",
                    severity=len(violations) / len(candidates),
                    doc_ids=[doc_id for doc_id, _ in violations],
                ))

        return anomalies

    def _get_common_domains(self, candidates: list[Candidate]) -> set[str]:
        """Get domains that appear in multiple candidates."""
        domain_counts: dict[str, int] = {}
        for c in candidates:
            for domain in c.features.domain_scores.keys():
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

        # Return domains appearing in at least 50% of candidates
        threshold = len(candidates) / 2
        return {d for d, count in domain_counts.items() if count >= threshold}

    def _detect_heuristic(
        self,
        candidates: list[Candidate],
        expected_patterns: dict[str, Any] | None,
    ) -> list[Anomaly]:
        """Complete heuristic anomaly detection using all detectors."""
        anomalies: list[Anomaly] = []

        # Temporal gaps
        anomalies.extend(self._detect_temporal_gaps(candidates))

        # Cross-doc conflicts
        anomalies.extend(self._detect_cross_doc_conflicts(candidates))

        # Missing expected evidence types
        anomalies.extend(self._detect_missing_expected(candidates, expected_patterns))

        # Statistical outliers
        anomalies.extend(self._detect_statistical_outliers(candidates))

        # Unexpected values
        anomalies.extend(self._detect_unexpected_value(candidates, expected_patterns))

        return anomalies

    def _explain_anomaly(
        self,
        anomaly: Anomaly,
        candidates: list[Candidate],
    ) -> tuple[str, ModelCall]:
        """Use LLM to explain anomaly."""
        prompt_template = get_prompt("L4_ANOMALY_EXPLANATION_V1")

        # Get relevant doc summaries
        relevant_docs = [
            c for c in candidates
            if c.doc_id in anomaly.doc_ids
        ]
        doc_summaries = "\n".join([
            f"- {c.doc_id}: {c.features.doc_type.value if c.features.doc_type else 'unknown'}"
            for c in relevant_docs
        ])

        prompt = prompt_template.template.format(
            anomaly_type=anomaly.anomaly_type.value,
            anomaly_description=anomaly.description,
            doc_summaries=doc_summaries,
        )

        response = self.client.call(
            prompt=prompt,
            tier=ModelTier.SONNET,
            max_tokens=500,
        )

        call = ModelCall(
            model=ModelTier.SONNET,
            layer="L4",
            purpose="anomaly_explanation",
            latency_ms=response.latency_ms,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
        )

        return response.content.strip(), call


# =============================================================================
# PATTERN EXTRACTOR
# =============================================================================

class PatternExtractor:
    """Extracts cross-document patterns from survivors."""

    def extract_patterns(
        self,
        candidates: list[Candidate],
    ) -> list[Signal]:
        """Extract patterns from candidate set."""
        patterns: list[Signal] = []

        # Entity co-occurrence patterns (using actual EntitySet fields)
        entity_docs: dict[str, list[str]] = {}
        for c in candidates:
            for entity in (
                c.features.entities.materials +
                c.features.entities.standards +
                c.features.entities.hazards +
                c.features.entities.systems
            ):
                entity_docs.setdefault(entity, []).append(c.doc_id)

        # Find entities that appear in multiple docs
        for entity, docs in entity_docs.items():
            if len(docs) >= 3:
                patterns.append(Signal(
                    signal_type=SignalType.PATTERN,
                    description=f"Entity '{entity}' appears across {len(docs)} documents",
                    confidence=min(1.0, len(docs) / 5),
                    source_docs=docs[:5],
                    evidence=[f"Entity: {entity}"],
                    metadata={"entity": entity, "doc_count": len(docs)},
                ))

        # Document type clustering
        type_counts: dict[str, int] = {}
        for c in candidates:
            dtype = c.features.doc_type.value if c.features.doc_type else "unknown"
            type_counts[dtype] = type_counts.get(dtype, 0) + 1

        dominant_type = max(type_counts, key=type_counts.get) if type_counts else None
        if dominant_type and type_counts.get(dominant_type, 0) >= len(candidates) * 0.6:
            patterns.append(Signal(
                signal_type=SignalType.CLUSTER,
                description=f"Document set dominated by '{dominant_type}' type ({type_counts[dominant_type]}/{len(candidates)})",
                confidence=type_counts[dominant_type] / len(candidates),
                source_docs=[
                    c.doc_id for c in candidates
                    if (c.features.doc_type.value if c.features.doc_type else "unknown") == dominant_type
                ][:5],
                evidence=[f"Type: {dominant_type}"],
                metadata={"type": dominant_type, "count": type_counts[dominant_type]},
            ))

        return patterns


# =============================================================================
# SIGNAL EXTRACTION ENGINE
# =============================================================================

class SignalExtractionEngine:
    """
    L4 Signal Extraction: Find patterns in L3 survivors.

    Combines:
    - Temporal analysis
    - Anomaly detection
    - Pattern extraction
    """

    def __init__(
        self,
        domain_pack: DomainPack,
        client: BaseClaudeClient | None = None,
        recency_window_days: int = 90,
        explain_anomalies: bool = True,
    ):
        self.domain_pack = domain_pack
        self.client = client or get_default_client()

        self.temporal_analyzer = TemporalAnalyzer(
            recency_window_days=recency_window_days,
        )
        self.anomaly_detector = AnomalyDetector(
            client=self.client,
            explain_anomalies=explain_anomalies,
        )
        self.pattern_extractor = PatternExtractor()

    def extract(
        self,
        candidates: list[Candidate],
    ) -> SignalExtractionResult:
        """
        Extract signals from L3 survivors.

        Args:
            candidates: Documents that passed L3 negative selection

        Returns:
            SignalExtractionResult with all extracted signals
        """
        model_calls: list[ModelCall] = []
        signals: list[Signal] = []

        # Temporal analysis
        temporal_derivatives = self.temporal_analyzer.analyze(candidates)

        # Convert temporal derivatives to signals
        for td in temporal_derivatives:
            signals.append(Signal(
                signal_type=SignalType.TEMPORAL_CHANGE,
                description=f"Change in {td.field}: {td.old_value} -> {td.new_value}",
                confidence=td.significance,
                source_docs=td.doc_ids,
                evidence=[f"Changed on {td.change_date}"],
                metadata={"derivative": td},
            ))

        # Anomaly detection
        anomalies, anomaly_calls = self.anomaly_detector.detect(candidates)
        model_calls.extend(anomaly_calls)

        # Convert anomalies to signals
        for anomaly in anomalies:
            signals.append(Signal(
                signal_type=SignalType.ANOMALY,
                description=anomaly.description,
                # P0 FIX: Severity IS the signal strength - higher severity = more important anomaly
                # Previous code inverted this incorrectly (1.0 - severity)
                confidence=anomaly.severity,
                source_docs=anomaly.doc_ids,
                evidence=[anomaly.explanation] if anomaly.explanation else [],
                metadata={"anomaly": anomaly},
            ))

        # Pattern extraction
        pattern_signals = self.pattern_extractor.extract_patterns(candidates)
        signals.extend(pattern_signals)

        return SignalExtractionResult(
            signals=signals,
            temporal_derivatives=temporal_derivatives,
            anomalies=anomalies,
            model_calls=model_calls,
            processing_stats={
                "candidate_count": len(candidates),
                "signal_count": len(signals),
                "anomaly_count": len(anomalies),
                "temporal_count": len(temporal_derivatives),
            },
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_signal_extraction_engine(
    domain_pack: DomainPack,
    client: BaseClaudeClient | None = None,
    **kwargs,
) -> SignalExtractionEngine:
    """Factory function for SignalExtractionEngine."""
    return SignalExtractionEngine(
        domain_pack=domain_pack,
        client=client,
        **kwargs,
    )


__all__ = [
    # Enums
    "SignalType",
    "AnomalyType",
    # Data structures
    "Signal",
    "TemporalDerivative",
    "Anomaly",
    "SignalExtractionResult",
    # Analyzers
    "TemporalAnalyzer",
    "AnomalyDetector",
    "PatternExtractor",
    # Engine
    "SignalExtractionEngine",
    # Factory
    "create_signal_extraction_engine",
]
