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
GPTL Engine - Main Orchestrator
===============================

Orchestrates the complete GPTL 6-layer pipeline:
    L0: Feature Extraction (handled externally at ingestion)
    L1: Domain Constraints (loaded from DomainPack)
    L2: Intent Framing (IntentFramingEngine)
    L3: Negative Selection (NegativeSelectionEngine)
    L4: Signal Extraction (SignalExtractionEngine)
    L5: Translation/Synthesis (SynthesisEngine)

Philosophy:
    "Subtract the 80% that CANNOT be relevant, then show our work"

Compliance: NASA-STD-8739.8B, SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from gptl.schema import (
    AuditTrail,
    DocFeatures,
    DomainPack,
    GPTLMetrics,
    GPTLRequest,
    GPTLResponse,
    ModelCall,
)
from gptl.config_loader import load_domain_pack, compute_config_hash
from gptl.claude_client import BaseClaudeClient, get_default_client
from gptl.exceptions import (
    GPTLError,
    TransientError,
    ConfigurationError,
    ValidationError,
    ClientError,
    PipelineError,
    StageFailedError,
)
from gptl.prompts import compute_prompts_hash
from gptl.intent_framing import IntentFramingEngine, create_intent_framing_engine
from gptl.negative_selection import (
    Candidate,
    NegativeSelectionEngine,
    create_candidates,
    create_negative_selection_engine,
)
from gptl.signal_extraction import SignalExtractionEngine, create_signal_extraction_engine
from gptl.synthesis import SynthesisEngine, create_synthesis_engine

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# PIPELINE RESULT
# =============================================================================

@dataclass
class PipelineStageResult:
    """Result from a single pipeline stage."""
    stage: str
    success: bool
    duration_ms: int
    output: Any
    error: str | None = None


@dataclass
class PipelineResult:
    """Complete pipeline execution result."""
    response: GPTLResponse
    stages: list[PipelineStageResult] = field(default_factory=list)
    total_duration_ms: int = 0


# =============================================================================
# DOCUMENT PROVIDER PROTOCOL
# =============================================================================

class DocumentProvider:
    """
    Protocol for document retrieval.

    Implementations should provide documents with pre-computed DocFeatures.
    This abstraction allows GPTL to work with any document store.
    """

    def get_candidates(
        self,
        query: str,
        limit: int = 100,
    ) -> list[Candidate]:
        """
        Retrieve candidate documents for a query.

        Args:
            query: The search query
            limit: Maximum candidates to return

        Returns:
            List of Candidate objects with DocFeatures
        """
        raise NotImplementedError("Subclass must implement get_candidates")


class InMemoryDocumentProvider(DocumentProvider):
    """Simple in-memory document provider for testing."""

    def __init__(self, documents: list[tuple[str, DocFeatures, float]]):
        """
        Args:
            documents: List of (doc_id, features, base_score) tuples
        """
        self._candidates = [
            Candidate(doc_id=doc_id, features=features, score=score)
            for doc_id, features, score in documents
        ]

    def get_candidates(
        self,
        query: str,
        limit: int = 100,
    ) -> list[Candidate]:
        return self._candidates[:limit]


# =============================================================================
# GPTL ENGINE
# =============================================================================

class GPTLEngine:
    """
    Main GPTL orchestrator implementing the 6-layer pipeline.

    Usage:
        engine = GPTLEngine.from_domain_pack("mira")
        response = engine.process(request, document_provider)
    """

    def __init__(
        self,
        domain_pack: DomainPack,
        client: BaseClaudeClient | None = None,
        intent_engine: IntentFramingEngine | None = None,
        negative_selection_engine: NegativeSelectionEngine | None = None,
        signal_engine: SignalExtractionEngine | None = None,
        synthesis_engine: SynthesisEngine | None = None,
    ):
        self.domain_pack = domain_pack
        self.client = client or get_default_client()

        # Initialize engines with defaults if not provided
        self.intent_engine = intent_engine or create_intent_framing_engine(
            domain_pack=domain_pack,
            client=self.client,
        )
        self.negative_selection_engine = negative_selection_engine or create_negative_selection_engine(
            domain_pack=domain_pack,
            client=self.client,
        )
        self.signal_engine = signal_engine or create_signal_extraction_engine(
            domain_pack=domain_pack,
            client=self.client,
        )
        self.synthesis_engine = synthesis_engine or create_synthesis_engine(
            domain_pack=domain_pack,
            client=self.client,
        )

        # Compute hashes for determinism
        self._config_hash = compute_config_hash(domain_pack)
        self._prompts_hash = compute_prompts_hash()

    @classmethod
    def from_domain_pack(
        cls,
        domain_name: str,
        config_dir: str | None = None,
        client: BaseClaudeClient | None = None,
    ) -> GPTLEngine:
        """
        Create engine from domain pack name.

        Args:
            domain_name: Name of domain pack (e.g., "mira", "aegis")
            config_dir: Optional config directory path
            client: Optional Claude client

        Returns:
            Configured GPTLEngine
        """
        domain_pack = load_domain_pack(domain_name, config_dir)
        return cls(domain_pack=domain_pack, client=client)

    def process(
        self,
        request: GPTLRequest,
        document_provider: DocumentProvider,
    ) -> PipelineResult:
        """
        Process a GPTL request through the full pipeline.

        Args:
            request: The GPTL request
            document_provider: Provider for candidate documents

        Returns:
            PipelineResult with response and stage details
        """
        start_time = time.perf_counter()
        stages: list[PipelineStageResult] = []
        model_calls: list[ModelCall] = []

        # L2: Intent Framing
        l2_start = time.perf_counter()
        try:
            intent_result = self.intent_engine.classify(request.query)
            model_calls.extend(intent_result.model_calls)
            stages.append(PipelineStageResult(
                stage="L2_intent_framing",
                success=True,
                duration_ms=int((time.perf_counter() - l2_start) * 1000),
                output={
                    "intent": intent_result.classified.frame_id,
                    "confidence": intent_result.classified.confidence,
                    "heuristic_used": intent_result.heuristic_used,
                    "escalated": intent_result.escalated,
                },
            ))
        except ConfigurationError as e:
            # Configuration errors are fatal - fail fast
            logger.error(f"L2 configuration error: {e}")
            raise
        except ValidationError as e:
            # Validation errors - log and use fallback
            logger.warning(f"L2 validation error, using fallback: {e}")
            stages.append(PipelineStageResult(
                stage="L2_intent_framing",
                success=False,
                duration_ms=int((time.perf_counter() - l2_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except (TransientError, ClientError) as e:
            # Transient/Client errors - record and fail (retry handled at client level)
            logger.error(f"L2 API error: {e}")
            stages.append(PipelineStageResult(
                stage="L2_intent_framing",
                success=False,
                duration_ms=int((time.perf_counter() - l2_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except GPTLError as e:
            # Other GPTL errors
            logger.error(f"L2 GPTL error: {e}")
            stages.append(PipelineStageResult(
                stage="L2_intent_framing",
                success=False,
                duration_ms=int((time.perf_counter() - l2_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except Exception as e:
            # Unexpected errors - log with full context
            logger.exception(f"L2 unexpected error: {e}")
            stages.append(PipelineStageResult(
                stage="L2_intent_framing",
                success=False,
                duration_ms=int((time.perf_counter() - l2_start) * 1000),
                output=None,
                error=f"Unexpected error: {e}",
            ))
            return self._create_error_result(request, stages, str(e), start_time)

        # Get candidates from provider
        l3_start = time.perf_counter()
        candidates: list[Candidate] = []
        survivors: list[Candidate] = []
        try:
            candidates = document_provider.get_candidates(
                query=request.query,
                limit=request.max_results * 10 if request.max_results else 100,
            )

            # L3: Negative Selection
            selection_result = self.negative_selection_engine.filter(
                candidates=candidates,
                intent=intent_result.classified,
            )
            model_calls.extend(selection_result.model_calls)

            survivors = selection_result.survivors
            stages.append(PipelineStageResult(
                stage="L3_negative_selection",
                success=True,
                duration_ms=int((time.perf_counter() - l3_start) * 1000),
                output={
                    "input_count": len(candidates),
                    "survivor_count": len(survivors),
                    "elimination_rate": selection_result.elimination_rate,
                    "violations_count": len(selection_result.violations),
                },
            ))
        except ConfigurationError as e:
            # Configuration errors are fatal
            logger.error(f"L3 configuration error: {e}")
            raise
        except ValidationError as e:
            # Validation errors - log and continue with empty results
            logger.warning(f"L3 validation error: {e}")
            stages.append(PipelineStageResult(
                stage="L3_negative_selection",
                success=False,
                duration_ms=int((time.perf_counter() - l3_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except (TransientError, ClientError) as e:
            # Transient/Client errors
            logger.error(f"L3 API error: {e}")
            stages.append(PipelineStageResult(
                stage="L3_negative_selection",
                success=False,
                duration_ms=int((time.perf_counter() - l3_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except GPTLError as e:
            # Other GPTL errors
            logger.error(f"L3 GPTL error: {e}")
            stages.append(PipelineStageResult(
                stage="L3_negative_selection",
                success=False,
                duration_ms=int((time.perf_counter() - l3_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except Exception as e:
            # Unexpected errors
            logger.exception(f"L3 unexpected error: {e}")
            stages.append(PipelineStageResult(
                stage="L3_negative_selection",
                success=False,
                duration_ms=int((time.perf_counter() - l3_start) * 1000),
                output=None,
                error=f"Unexpected error: {e}",
            ))
            return self._create_error_result(request, stages, str(e), start_time)

        # L4: Signal Extraction
        l4_start = time.perf_counter()
        try:
            signal_result = self.signal_engine.extract(survivors)
            model_calls.extend(signal_result.model_calls)
            stages.append(PipelineStageResult(
                stage="L4_signal_extraction",
                success=True,
                duration_ms=int((time.perf_counter() - l4_start) * 1000),
                output={
                    "signal_count": len(signal_result.signals),
                    "anomaly_count": len(signal_result.anomalies),
                    "temporal_count": len(signal_result.temporal_derivatives),
                },
            ))
        except ConfigurationError as e:
            # Configuration errors are fatal
            logger.error(f"L4 configuration error: {e}")
            raise
        except ValidationError as e:
            # Validation errors - log and continue with empty signals
            logger.warning(f"L4 validation error: {e}")
            stages.append(PipelineStageResult(
                stage="L4_signal_extraction",
                success=False,
                duration_ms=int((time.perf_counter() - l4_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except (TransientError, ClientError) as e:
            # Transient/Client errors
            logger.error(f"L4 API error: {e}")
            stages.append(PipelineStageResult(
                stage="L4_signal_extraction",
                success=False,
                duration_ms=int((time.perf_counter() - l4_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except GPTLError as e:
            # Other GPTL errors
            logger.error(f"L4 GPTL error: {e}")
            stages.append(PipelineStageResult(
                stage="L4_signal_extraction",
                success=False,
                duration_ms=int((time.perf_counter() - l4_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except Exception as e:
            # Unexpected errors
            logger.exception(f"L4 unexpected error: {e}")
            stages.append(PipelineStageResult(
                stage="L4_signal_extraction",
                success=False,
                duration_ms=int((time.perf_counter() - l4_start) * 1000),
                output=None,
                error=f"Unexpected error: {e}",
            ))
            return self._create_error_result(request, stages, str(e), start_time)

        # L5: Synthesis
        l5_start = time.perf_counter()
        try:
            synthesis_result = self.synthesis_engine.synthesize(
                query=request.query,
                intent=intent_result.classified,
                evidence=survivors,
                signals=signal_result,
                is_safety_critical=request.safety_critical,
            )
            model_calls.extend(synthesis_result.model_calls)
            stages.append(PipelineStageResult(
                stage="L5_synthesis",
                success=not synthesis_result.refused,
                duration_ms=int((time.perf_counter() - l5_start) * 1000),
                output={
                    "refused": synthesis_result.refused,
                    "refusal_reason": synthesis_result.refusal_reason,
                    "confidence": synthesis_result.intelligence.confidence,
                    "citation_count": len(synthesis_result.intelligence.evidence),
                },
            ))
        except ConfigurationError as e:
            # Configuration errors are fatal
            logger.error(f"L5 configuration error: {e}")
            raise
        except ValidationError as e:
            # Validation errors - log and return error
            logger.warning(f"L5 validation error: {e}")
            stages.append(PipelineStageResult(
                stage="L5_synthesis",
                success=False,
                duration_ms=int((time.perf_counter() - l5_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except (TransientError, ClientError) as e:
            # Transient/Client errors
            logger.error(f"L5 API error: {e}")
            stages.append(PipelineStageResult(
                stage="L5_synthesis",
                success=False,
                duration_ms=int((time.perf_counter() - l5_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except GPTLError as e:
            # Other GPTL errors
            logger.error(f"L5 GPTL error: {e}")
            stages.append(PipelineStageResult(
                stage="L5_synthesis",
                success=False,
                duration_ms=int((time.perf_counter() - l5_start) * 1000),
                output=None,
                error=str(e),
            ))
            return self._create_error_result(request, stages, str(e), start_time)
        except Exception as e:
            # Unexpected errors
            logger.exception(f"L5 unexpected error: {e}")
            stages.append(PipelineStageResult(
                stage="L5_synthesis",
                success=False,
                duration_ms=int((time.perf_counter() - l5_start) * 1000),
                output=None,
                error=f"Unexpected error: {e}",
            ))
            return self._create_error_result(request, stages, str(e), start_time)

        # Build response
        total_duration = int((time.perf_counter() - start_time) * 1000)

        # Calculate metrics
        total_tokens_in = sum(c.tokens_in for c in model_calls)
        total_tokens_out = sum(c.tokens_out for c in model_calls)

        metrics = GPTLMetrics(
            total_latency_ms=total_duration,
            l2_latency_ms=stages[0].duration_ms if stages else 0,
            l3_latency_ms=stages[1].duration_ms if len(stages) > 1 else 0,
            l4_latency_ms=stages[2].duration_ms if len(stages) > 2 else 0,
            l5_latency_ms=stages[3].duration_ms if len(stages) > 3 else 0,
            documents_considered=len(candidates),
            documents_survived=len(survivors),
            model_calls_count=len(model_calls),
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
        )

        audit = AuditTrail(
            request_id=request.request_id,
            domain_pack=self.domain_pack.domain_id,
            config_hash=self._config_hash,
            prompts_hash=self._prompts_hash,
            model_calls=model_calls,
            constraint_violations=selection_result.violations,
            intent_classification=intent_result.classified,
        )

        response = GPTLResponse(
            request_id=request.request_id,
            intelligence=synthesis_result.intelligence,
            audit=audit,
            metrics=metrics,
            success=not synthesis_result.refused,
            error=synthesis_result.refusal_reason,
        )

        return PipelineResult(
            response=response,
            stages=stages,
            total_duration_ms=total_duration,
        )

    def _create_error_result(
        self,
        request: GPTLRequest,
        stages: list[PipelineStageResult],
        error: str,
        start_time: float,
    ) -> PipelineResult:
        """Create error response when pipeline fails."""
        from gptl.schema import IntelligenceOutput

        total_duration = int((time.perf_counter() - start_time) * 1000)

        intelligence = IntelligenceOutput(
            answer="",
            confidence=0.0,
            citations=[],
            caveats=["Pipeline error occurred"],
            follow_up_questions=[],
            metadata={"error": error},
        )

        audit = AuditTrail(
            request_id=request.request_id,
            domain_pack=self.domain_pack.domain_id,
            config_hash=self._config_hash,
            prompts_hash=self._prompts_hash,
            model_calls=[],
            constraint_violations=[],
            intent_classification=None,
        )

        metrics = GPTLMetrics(
            total_latency_ms=total_duration,
            l2_latency_ms=0,
            l3_latency_ms=0,
            l4_latency_ms=0,
            l5_latency_ms=0,
            documents_considered=0,
            documents_survived=0,
            model_calls_count=0,
            total_tokens_in=0,
            total_tokens_out=0,
        )

        response = GPTLResponse(
            request_id=request.request_id,
            intelligence=intelligence,
            audit=audit,
            metrics=metrics,
            success=False,
            error=error,
        )

        return PipelineResult(
            response=response,
            stages=stages,
            total_duration_ms=total_duration,
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_engine(
    domain_name: str,
    config_dir: str | None = None,
    client: BaseClaudeClient | None = None,
) -> GPTLEngine:
    """
    Create a GPTL engine for a domain.

    Args:
        domain_name: Name of domain pack
        config_dir: Optional config directory
        client: Optional Claude client

    Returns:
        Configured GPTLEngine
    """
    return GPTLEngine.from_domain_pack(
        domain_name=domain_name,
        config_dir=config_dir,
        client=client,
    )


__all__ = [
    # Results
    "PipelineStageResult",
    "PipelineResult",
    # Document provider
    "DocumentProvider",
    "InMemoryDocumentProvider",
    # Engine
    "GPTLEngine",
    # Factory
    "create_engine",
]
