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
Query endpoint - the core SENTINEL API.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import time
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from gptl.api.deps import get_settings, get_engine, Settings
from gptl.api.auth import verify_api_key
from gptl.config_loader import compute_config_hash
from gptl.engine import InMemoryDocumentProvider
from gptl.schema import DocFeatures, DocType, EntitySet, DocFlags

__safety_critical__: bool = True

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class QueryOptions(BaseModel):
    """Options for query execution."""
    quality_tier: str = Field(default="standard", pattern="^(standard|critical)$")
    include_eliminated: bool = Field(default=True)
    include_audit: bool = Field(default=True)
    max_candidates: Optional[int] = Field(default=100, ge=1, le=500)
    max_evidence: Optional[int] = Field(default=10, ge=1, le=50)


class QueryRequest(BaseModel):
    """Request body for /api/v1/query."""
    domain_id: str = Field(default="sentinel-demo")
    query: str = Field(..., min_length=3, max_length=2000)
    options: QueryOptions = Field(default_factory=QueryOptions)


class EvidenceCitation(BaseModel):
    """Evidence citation in response."""
    doc_id: str
    chunk_id: str
    evidence_type: str
    snippet: str
    relevance_score: float


class Intelligence(BaseModel):
    """Intelligence output when not refusing."""
    finding: str
    implication: str
    action: str
    timeline: str
    confidence: float
    confidence_interval: List[float]
    confidence_drivers: List[str]
    evidence: List[EvidenceCitation]


class Refusal(BaseModel):
    """Refusal output when refusing."""
    type: str
    reason: str
    missing_evidence: List[str]
    what_would_change_this: List[str]
    confidence: float = 0.0
    confidence_interval: List[float] = [0.0, 0.0]


class Elimination(BaseModel):
    """Single elimination record."""
    chunk_id: str
    doc_id: str
    rule_id: str
    reason: str
    stage: str


class Selection(BaseModel):
    """Selection summary."""
    candidates_evaluated: int
    candidates_eliminated: int
    reduction_ratio: float
    survivors: int
    eliminations: List[Elimination] = []


class ModelCallRecord(BaseModel):
    """Single model call record."""
    tier: str
    layer: str
    purpose: str
    latency_ms: int
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class Audit(BaseModel):
    """Audit trail."""
    l2_intent: Dict[str, Any]
    l3_violations: List[Dict[str, Any]]
    l4_signals: List[Dict[str, Any]]
    l5_calibration: Dict[str, Any]
    model_calls: List[ModelCallRecord]
    total_latency_ms: int


class QueryResponse(BaseModel):
    """Response body for /api/v1/query."""
    trace_id: str
    config_hash: str
    corpus_snapshot_id: str

    intelligence: Optional[Intelligence] = None
    selection: Selection

    refused: bool = False
    refusal: Optional[Refusal] = None

    audit: Optional[Audit] = None


# =============================================================================
# DEMO DATA - Temporary until ingestion is complete
# =============================================================================

def get_demo_documents() -> list:
    """Return demo documents for testing."""
    from gptl.schema import EvidenceType

    demo_docs = [
        (
            "MSFC-STD-3029",
            DocFeatures(
                doc_id="MSFC-STD-3029",
                doc_hash="abc123",
                doc_type=DocType.SPECIFICATION,
                domain_scores={"materials": 0.95, "sentinel-demo": 0.95},
                tags=["LOX", "compatibility", "materials", "cryogenic"],
                entities=EntitySet(
                    materials=["Inconel 718", "Monel 400", "stainless steel"],
                    standards=["NASA-STD-6001", "MSFC-STD-3029"],
                    hazards=["oxygen enrichment", "ignition"],
                ),
                flags=DocFlags(
                    has_measurements=True,
                    has_tables=True,
                    has_spec_references=True,
                ),
                derived_evidence_types=[EvidenceType.SPECIFICATION, EvidenceType.COMPATIBILITY_MATRIX],
            ),
            0.94,
        ),
        (
            "NASA-TM-2023-0142",
            DocFeatures(
                doc_id="NASA-TM-2023-0142",
                doc_hash="def456",
                doc_type=DocType.REPORT,
                domain_scores={"materials": 0.88, "sentinel-demo": 0.88},
                tags=["LOX", "test", "compatibility", "cryogenic"],
                entities=EntitySet(
                    materials=["Inconel 718", "titanium"],
                    standards=["NASA-STD-6001"],
                    hazards=["impact ignition"],
                ),
                flags=DocFlags(
                    has_measurements=True,
                    has_test_conditions=True,
                    has_figures=True,
                ),
                derived_evidence_types=[EvidenceType.TEST_REPORT],
            ),
            0.87,
        ),
        (
            "MAPTIS-MAT-001",
            DocFeatures(
                doc_id="MAPTIS-MAT-001",
                doc_hash="ghi789",
                doc_type=DocType.SPECIFICATION,
                domain_scores={"materials": 0.82, "sentinel-demo": 0.82},
                tags=["materials", "database", "properties"],
                entities=EntitySet(
                    materials=["Inconel 718", "Inconel 625", "Hastelloy X"],
                    standards=["AMS 5662", "AMS 5663"],
                ),
                flags=DocFlags(
                    has_tables=True,
                    has_measurements=True,
                ),
                derived_evidence_types=[EvidenceType.DATASHEET],
            ),
            0.82,
        ),
    ]

    return demo_docs


# =============================================================================
# ENDPOINT
# =============================================================================

@router.post("/query", response_model=QueryResponse)
async def execute_query(
    request: QueryRequest,
    api_key: Optional[str] = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
) -> QueryResponse:
    """
    Execute a SENTINEL query.

    Runs the full GPTL pipeline:
    - L0: Feature extraction (pre-computed)
    - L2: Intent classification
    - L3: Negative selection
    - L4: Signal extraction
    - L5: Synthesis (or refusal)

    Returns bounded, auditable intelligence with full trace.
    """
    start_time = time.time()

    # Generate trace ID
    trace_id = f"sentinel-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    try:
        # Get engine for domain
        engine = get_engine(request.domain_id)
        config_hash = compute_config_hash(engine.domain_pack)

        # For demo, use in-memory documents
        # TODO: Replace with actual vector store retrieval
        demo_docs = get_demo_documents()
        document_provider = InMemoryDocumentProvider(demo_docs)

        # Build GPTL request
        from gptl.schema import GPTLRequest
        gptl_request = GPTLRequest(
            query=request.query,
            domain_id=request.domain_id,
            user_id="api",
            mode="strict",
            quality_tier=request.options.quality_tier,
        )

        # Execute pipeline
        result = engine.process(gptl_request, document_provider)

        total_latency_ms = int((time.time() - start_time) * 1000)

        # Extract data from pipeline result
        response_data = result.response
        audit_data = response_data.audit
        intelligence_data = response_data.intelligence

        # Determine if refused
        refused = intelligence_data.insufficient_evidence if intelligence_data else True

        # Build selection info
        selection = Selection(
            candidates_evaluated=audit_data.candidates_evaluated if audit_data else 0,
            candidates_eliminated=audit_data.candidates_eliminated if audit_data else 0,
            reduction_ratio=audit_data.reduction_ratio if audit_data else 0.0,
            survivors=audit_data.candidates_evaluated - audit_data.candidates_eliminated if audit_data else 0,
            eliminations=[],  # TODO: Extract from violation report
        )

        # Build response
        response = QueryResponse(
            trace_id=trace_id,
            config_hash=config_hash,
            corpus_snapshot_id=settings.corpus_snapshot_id,
            selection=selection,
            refused=refused,
        )

        if refused and intelligence_data:
            response.refusal = Refusal(
                type=intelligence_data.refusal_type or "unknown",
                reason=intelligence_data.refusal_reason or "Insufficient evidence",
                missing_evidence=[],  # TODO: Extract from requirements
                what_would_change_this=["Add more relevant documents to the corpus"],
            )
        elif intelligence_data:
            response.intelligence = Intelligence(
                finding=intelligence_data.finding,
                implication=intelligence_data.implication,
                action=intelligence_data.action,
                timeline=intelligence_data.timeline,
                confidence=intelligence_data.confidence,
                confidence_interval=list(intelligence_data.confidence_interval),
                confidence_drivers=intelligence_data.confidence_drivers,
                evidence=[
                    EvidenceCitation(
                        doc_id=e.doc_id,
                        chunk_id=e.doc_id,  # For now, same as doc_id
                        evidence_type=e.evidence_type.value if hasattr(e.evidence_type, 'value') else str(e.evidence_type),
                        snippet=e.snippet[:500],
                        relevance_score=e.relevance_score,
                    )
                    for e in intelligence_data.evidence[:request.options.max_evidence]
                ],
            )

        if request.options.include_audit and audit_data:
            response.audit = Audit(
                l2_intent={
                    "frame_id": audit_data.intent_classification.frame_id if audit_data.intent_classification else "unknown",
                    "confidence": audit_data.intent_classification.confidence if audit_data.intent_classification else 0.0,
                } if audit_data.intent_classification else {},
                l3_violations=[v.model_dump() for v in audit_data.constraint_violations] if audit_data.constraint_violations else [],
                l4_signals=[],  # TODO: Add signal extraction to audit
                l5_calibration={},  # TODO: Add calibration details
                model_calls=[
                    ModelCallRecord(
                        tier=mc.model.value if hasattr(mc.model, 'value') else str(mc.model),
                        layer=mc.layer,
                        purpose=mc.purpose,
                        latency_ms=mc.latency_ms,
                        tokens_in=mc.tokens_in,
                        tokens_out=mc.tokens_out,
                    )
                    for mc in audit_data.model_calls
                ] if audit_data.model_calls else [],
                total_latency_ms=total_latency_ms,
            )

        return response

    except Exception as e:
        logger.exception(f"Query execution failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline error: {str(e)}",
        )


__all__ = ["router"]
