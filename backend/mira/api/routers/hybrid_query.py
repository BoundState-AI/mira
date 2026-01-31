#!/usr/bin/env python3
"""
Module: Hybrid Query Router (Railway Deployment)
Purpose: Hybrid Query Endpoint - MIRA V2 Evidence-First Integration

BoundState AI 2025
"""

from fastapi import APIRouter, HTTPException
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

# Import MIRA V2 query engine
try:
    from mira.MIRA_V2.src.query_engine_v2 import EvidenceFirstQueryEngine
    QUERY_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"WARNING: Could not import MIRA V2 query engine: {e}")
    EvidenceFirstQueryEngine = None
    QUERY_ENGINE_AVAILABLE = False

router = APIRouter(prefix="/api/query", tags=["hybrid-query"])


# Request/Response models
class HybridQueryRequest(BaseModel):
    """Request model for hybrid query."""
    query: str = Field(..., min_length=1, description="Natural language materials query")
    enable_semantic: bool = Field(False, description="Enable semantic search (disabled on Railway)")
    llm_provider: str = Field("haiku", description="LLM provider: 'haiku' (default) or 'ollama'")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Can aluminum 6061 be used in oxygen at 200 psi?",
                "enable_semantic": False,
                "llm_provider": "haiku"
            }
        }


class EvidenceSummary(BaseModel):
    """Summary of evidence sources."""
    mua_precedents_found: int = 0
    test_results_found: int = 0
    requirements_evaluated: int = 0
    semantic_results_found: int = 0
    high_confidence_semantic: int = 0


class BoundaryCheckResponse(BaseModel):
    """Response for deterministic boundary check."""
    verdict: str = Field(..., description="Verdict: WITHIN_LIMITS, EXCEEDS_LIMIT, NO_DATA, etc.")
    rationale: str = Field(..., description="Human-readable rationale for verdict")
    margin: Optional[float] = Field(None, description="Safety margin")
    evidence_sources: List[str] = Field(default_factory=list, description="Source documents")


class HybridQueryResponse(BaseModel):
    """Response model for hybrid query."""
    status: str
    query: str
    timestamp: datetime = Field(default_factory=datetime.now)

    # DETERMINISTIC DECISION
    deterministic_decision: Optional[str] = Field(None, description="YES, NO, CONDITIONAL, REQUIRES_TESTING")
    decision_source: Optional[str] = Field(None, description="Source of decision")
    decision_rationale: Optional[str] = Field(None, description="Rationale for decision")
    boundary_check_results: Optional[List[BoundaryCheckResponse]] = Field(None)

    # Evidence summary
    evidence_summary: EvidenceSummary
    constraints: Optional[Dict[str, Any]] = None

    # Material decisions
    decisions: Optional[List[Dict[str, Any]]] = None

    # LLM EXPLANATION
    explanation: Optional[str] = Field(None, description="LLM-generated explanation")
    answer: Optional[str] = Field(None, description="Alias for explanation")

    # Evidence sources
    sql_evidence: Optional[Dict[str, Any]] = None
    semantic_evidence: Optional[Dict[str, Any]] = None

    # Status flags
    insufficient_data: bool = False
    deterministic_decision_verified: bool = True
    error: Optional[str] = None


@router.post("/hybrid", response_model=HybridQueryResponse)
async def hybrid_query(request: HybridQueryRequest):
    """
    Execute hybrid evidence-first query.

    **Evidence-First Architecture:**
    1. Query MUA precedents (SQL) - Historic NASA decisions
    2. Query test data (SQL) - Actual test results
    3. Evaluate requirements (91+ BOK requirements)
    4. Make evidence-based decisions
    5. Return INSUFFICIENT_DATA if no evidence exists

    **Example queries:**
    - "Can aluminum 6061 be used in oxygen at 200 psi?"
    - "Stainless steel 316L compatibility with GOX at 3000 psia"
    - "PTFE seals for hydrogen service"
    """
    if not QUERY_ENGINE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Query engine not available - check DATABASE_URL configuration"
        )

    try:
        # Initialize query engine
        engine = EvidenceFirstQueryEngine(
            enable_semantic=False,  # Disabled on Railway
            llm_provider=request.llm_provider
        )

        # Execute query
        result = engine.query(request.query)

        # Extract evidence summary
        evidence_summary = EvidenceSummary(
            mua_precedents_found=result.get("mua_precedents_found", 0),
            test_results_found=result.get("test_results_found", 0),
            requirements_evaluated=result.get("requirements_evaluated", 0),
            semantic_results_found=0,
            high_confidence_semantic=0
        )

        # Extract decisions
        decisions = result.get("decisions", [])

        # Determine deterministic decision from first decision
        det_decision = None
        det_source = None
        det_rationale = None

        if decisions:
            first_decision = decisions[0]
            det_decision = first_decision.get("decision", "REQUIRES_TESTING")
            det_source = first_decision.get("source", "MATERIAL_DECIDER")
            det_rationale = first_decision.get("rationale", "")

        # Build response
        llm_explanation = result.get("llm_answer") or result.get("explanation")

        response = HybridQueryResponse(
            status=result.get("status", "success"),
            query=request.query,

            # DETERMINISTIC DECISION
            deterministic_decision=det_decision,
            decision_source=det_source,
            decision_rationale=det_rationale,
            boundary_check_results=None,

            # Evidence
            evidence_summary=evidence_summary,
            constraints=result.get("constraints"),
            decisions=decisions,

            # LLM EXPLANATION
            explanation=llm_explanation,
            answer=llm_explanation,

            sql_evidence={
                "mua_precedents": result.get("mua_precedents", []),
                "test_results": []
            },
            semantic_evidence=None,
            insufficient_data=result.get("status") == "INSUFFICIENT_DATA",
            deterministic_decision_verified=True
        )

        engine.close()
        return response

    except Exception as e:
        print(f"[ERROR] Hybrid query failed: {e}")
        import traceback
        traceback.print_exc()

        return HybridQueryResponse(
            status="error",
            query=request.query,
            evidence_summary=EvidenceSummary(),
            error=str(e)
        )


@router.get("/health")
async def query_engine_health():
    """Check query engine health."""
    if not QUERY_ENGINE_AVAILABLE:
        return {
            "status": "unavailable",
            "query_engine": False,
            "error": "MIRA V2 module not loaded"
        }

    try:
        engine = EvidenceFirstQueryEngine(enable_semantic=False)

        # Try to connect to database
        try:
            engine.conn.cursor().execute("SELECT 1")
            db_status = "connected"
        except:
            db_status = "disconnected"

        engine.close()

        return {
            "status": "healthy",
            "query_engine": True,
            "database": db_status,
            "semantic_search": False,
            "note": "Running in SQL-only mode (Railway deployment)"
        }
    except Exception as e:
        return {
            "status": "error",
            "query_engine": False,
            "error": str(e)
        }


@router.get("/examples")
async def query_examples():
    """Get example queries for testing."""
    return {
        "examples": [
            {
                "category": "Oxygen Compatibility",
                "queries": [
                    "Can aluminum 6061 be used in oxygen at 200 psi?",
                    "Stainless steel 316L compatibility with GOX at 3000 psia",
                    "PTFE seals for oxygen service at 150F"
                ]
            },
            {
                "category": "Hydrogen Compatibility",
                "queries": [
                    "Stainless steel hydrogen embrittlement at 5000 psi",
                    "Aluminum compatibility with liquid hydrogen",
                    "CRES 316 for GH2 service"
                ]
            },
            {
                "category": "Flammability",
                "queries": [
                    "Kapton flammability rating in air",
                    "Teflon NASA 6001B rating",
                    "Nomex flammability test results"
                ]
            }
        ]
    }
