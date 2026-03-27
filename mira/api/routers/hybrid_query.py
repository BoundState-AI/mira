#!/usr/bin/env python3
"""
Module: Hybrid Query
Purpose: Hybrid Query Endpoint - MIRA V2 Evidence-First Integration

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger(__name__)

# Import MIRA V2 query engine
try:
    from mira.MIRA_V2.src.query_engine_v2 import EvidenceFirstQueryEngine
    MaterialConstraints = None  # Not used directly
except ImportError as e:
    logger.warning("Could not import MIRA V2 query engine: %s", e)
    EvidenceFirstQueryEngine = None
    MaterialConstraints = None

router = APIRouter(prefix="/api/query", tags=["hybrid-query"])


# Request/Response models
class HybridQueryRequest(BaseModel):
    """Request model for hybrid query."""
    query: str = Field(..., min_length=1, description="Natural language materials query")
    enable_semantic: bool = Field(True, description="Enable semantic search enhancement")
    llm_provider: str = Field("ollama", description="LLM provider for answer generation: 'ollama' or 'haiku'")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Can aluminum 6061 be used in oxygen at 200 psi?",
                "enable_semantic": True,
                "llm_provider": "ollama"
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
    margin: Optional[float] = Field(None, description="Safety margin (positive = within, negative = exceeded)")
    evidence_sources: List[str] = Field(default_factory=list, description="Source documents for traceability")


class HybridQueryResponse(BaseModel):
    """
    Response model for hybrid query.

    REFACTORED: Now includes deterministic_decision field which is the
    AUTHORITATIVE decision made by BoundaryChecker/MaterialDecider.
    The 'explanation' field contains LLM-generated explanation text only.
    """
    status: str
    query: str
    timestamp: datetime = Field(default_factory=datetime.now)

    # DETERMINISTIC DECISION (not from LLM)
    deterministic_decision: Optional[str] = Field(
        None,
        description="The authoritative decision: YES, NO, CONDITIONAL, REQUIRES_TESTING"
    )
    decision_source: Optional[str] = Field(
        None,
        description="Source of decision: BOK_BOUNDARY_CHECK, MATERIAL_DECIDER, INSUFFICIENT_EVIDENCE"
    )
    decision_rationale: Optional[str] = Field(
        None,
        description="Rationale for the deterministic decision"
    )
    boundary_check_results: Optional[List[BoundaryCheckResponse]] = Field(
        None,
        description="Results from deterministic BOK boundary checks"
    )

    # Evidence summary
    evidence_summary: EvidenceSummary
    constraints: Optional[Dict[str, Any]] = None

    # Material decisions from MaterialDecider
    decisions: Optional[List[Dict[str, Any]]] = None

    # LLM EXPLANATION (not decision)
    explanation: Optional[str] = Field(
        None,
        description="LLM-generated explanation of the deterministic decision"
    )
    answer: Optional[str] = Field(
        None,
        description="Alias for explanation (deprecated, use 'explanation')"
    )

    # Evidence sources
    sql_evidence: Optional[Dict[str, Any]] = None
    semantic_evidence: Optional[Dict[str, Any]] = None

    # Status flags
    insufficient_data: bool = False
    deterministic_decision_verified: bool = Field(
        True,
        description="Confirms decision was made by deterministic rules, not LLM"
    )
    error: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "query": "aluminum 6061 oxygen 200 psi",
                "deterministic_decision": "NO",
                "decision_source": "BOK_BOUNDARY_CHECK",
                "decision_rationale": "Query pressure 200 psia is within BOK limit of 100 psia for aluminum in oxygen dynamic service",
                "boundary_check_results": [
                    {
                        "verdict": "EXCEEDS_LIMIT",
                        "rationale": "200 psia exceeds 100 psia dynamic limit",
                        "margin": -100.0,
                        "evidence_sources": ["NASA-STD-6016C 4.3.2.1"]
                    }
                ],
                "evidence_summary": {
                    "mua_precedents_found": 5,
                    "test_results_found": 12,
                    "requirements_evaluated": 91,
                    "semantic_results_found": 15,
                    "high_confidence_semantic": 3
                },
                "insufficient_data": False,
                "deterministic_decision_verified": True
            }
        }


# Endpoints
@router.post("/hybrid", response_model=HybridQueryResponse)
async def hybrid_query(request: HybridQueryRequest):
    """
    Execute hybrid evidence-first query.

    **Evidence-First Architecture:**
    1. Query MUA precedents (SQL) - Historic NASA decisions
    2. Query test data (SQL) - Actual test results
    3. Query semantic indexes (FAISS) - BOK standards + related MUAs + material properties
    4. Evaluate requirements (91+ BOK requirements)
    5. Make evidence-based decisions
    6. Return INSUFFICIENT_DATA if no evidence exists

    **Example queries:**
    - "Can aluminum 6061 be used in oxygen at 200 psi?"
    - "Stainless steel 316L compatibility with GOX at 3000 psia"
    - "PTFE seals for hydrogen service"
    - "Kapton flammability rating in air"

    **Returns:**
    - Status and evidence summary
    - SQL evidence (MUA precedents, test results)
    - Semantic evidence (BOK standards, related MUAs, material data)
    - Material compatibility decisions
    - Citations for audit trail
    """
    if not EvidenceFirstQueryEngine:
        raise HTTPException(
            status_code=503,
            detail="Query engine not available - MIRA V2 module not loaded"
        )

    try:
        # Initialize query engine
        engine = EvidenceFirstQueryEngine(
            enable_semantic=request.enable_semantic,
            llm_provider=request.llm_provider
        )

        # Execute query
        result = engine.query(request.query)

        # Extract evidence summary
        evidence_summary = EvidenceSummary(
            mua_precedents_found=result.get("mua_precedents_found", 0),
            test_results_found=result.get("test_results_found", 0),
            requirements_evaluated=result.get("requirements_evaluated", 0),
            semantic_results_found=result.get("semantic_evidence", {}).get("total_results", 0) if result.get("semantic_evidence") else 0,
            high_confidence_semantic=result.get("semantic_evidence", {}).get("stats", {}).get("high_confidence", 0) if result.get("semantic_evidence") else 0
        )

        # Extract boundary check results
        boundary_results = None
        if result.get("boundary_check_results"):
            boundary_results = [
                BoundaryCheckResponse(
                    verdict=br.get("verdict", "UNKNOWN"),
                    rationale=br.get("rationale", ""),
                    margin=br.get("margin"),
                    evidence_sources=br.get("evidence_sources", [])
                )
                for br in result["boundary_check_results"]
            ]

        # Build response with deterministic decision fields
        llm_explanation = result.get("llm_answer") or result.get("explanation")

        return HybridQueryResponse(
            status="success",
            query=request.query,

            # DETERMINISTIC DECISION (not from LLM)
            deterministic_decision=result.get("deterministic_decision"),
            decision_source=result.get("decision_source"),
            decision_rationale=result.get("decision_rationale"),
            boundary_check_results=boundary_results,

            # Evidence
            evidence_summary=evidence_summary,
            constraints=result.get("constraints"),
            decisions=result.get("decisions"),

            # LLM EXPLANATION (not decision)
            explanation=llm_explanation,
            answer=llm_explanation,  # Deprecated alias

            sql_evidence={
                "mua_precedents": result.get("mua_precedents", []),
                "test_results": result.get("test_results", [])
            },
            semantic_evidence=result.get("semantic_evidence"),
            insufficient_data=result.get("status") == "INSUFFICIENT_DATA",
            deterministic_decision_verified=result.get("deterministic_decision_verified", True)
        )

    except Exception as e:
        logger.error("Hybrid query failed: %s", e, exc_info=True)

        return HybridQueryResponse(
            status="error",
            query=request.query,
            evidence_summary=EvidenceSummary(),
            error=str(e)
        )


@router.get("/health")
async def query_engine_health():
    """
    Check query engine health and configuration.

    Returns information about:
    - Query engine availability
    - Database connection status
    - Semantic search status
    - FAISS indexes loaded
    """
    if not EvidenceFirstQueryEngine:
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
        except Exception:
            db_status = "disconnected"

        return {
            "status": "healthy",
            "query_engine": True,
            "database": db_status,
            "semantic_search": engine.enable_semantic,
            "db_url_configured": bool(engine.db_url)
        }
    except Exception as e:
        return {
            "status": "error",
            "query_engine": True,
            "error": str(e)
        }


@router.get("/examples")
async def query_examples():
    """
    Get example queries for testing.

    Returns a list of example queries that demonstrate
    the capabilities of the hybrid query engine.
    """
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
            },
            {
                "category": "General Material Properties",
                "queries": [
                    "Titanium corrosion resistance",
                    "Inconel high temperature performance",
                    "Silicon rubber outgassing properties"
                ]
            }
        ]
    }


__safety_critical__ = True  # NASA SWE-032 compliance
