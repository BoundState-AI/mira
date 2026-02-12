#!/usr/bin/env python3
"""
Module: Mua V6
Purpose: MUA v6 API router - precedent-based MUA generation.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from mira.mua.v6 import (
    DecisionResult,
    EnrichedSearchResults,
    EnvelopeOverlapResult,
    GenerationDecision,
    LogicValidator,
    MUADecisionEngine,
    OverlapStatus,
    RationaleValidationResult,
    TestDataStatus,
    compute_envelope_overlap,
    query_maptis_test_data,
    resolve_material_identity,
    search_enriched_precedents,
)
from mira.mua.v6.retriever import V6PrecedentRetriever, get_retriever
from mira.mua.v6.precedent_models import (
    NormalizedEnvironment,
    EnvironmentType,
    IssueCategory,
    MaterialFamily,
)

__all__ = ["router"]
__safety_critical__ = True

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class EnvironmentSpec(BaseModel):
    """Environment specification for MUA query."""

    model_config = {"extra": "forbid"}

    description: str = Field(..., description="Free-text environment description")
    o2_percent: float | None = Field(None, ge=0, le=100)
    pressure_psia: float | None = Field(None, ge=0)
    temperature_f: float | None = None
    is_habitable: bool = False


class PrecedentSearchRequest(BaseModel):
    """Request to search for MUA precedents."""

    model_config = {"extra": "forbid"}

    material: str = Field(..., min_length=1, description="Material designation")
    environment: EnvironmentSpec | None = None
    k: int = Field(10, ge=1, le=50, description="Number of results")
    family_filter: str | None = Field(None, description="Restrict to material family")


class PrecedentSummary(BaseModel):
    """Summary of a precedent MUA for API response."""

    model_config = {"extra": "forbid"}

    mua_number: str | None
    material_designation: str
    material_family: str | None
    environment: str | None
    determination: str
    rationale_preview: str = Field(..., description="First 300 chars of rationale")
    similarity_score: float
    is_supporting: bool
    is_conflicting: bool


class PrecedentSearchResponse(BaseModel):
    """Response from precedent search."""

    model_config = {"extra": "forbid"}

    request_id: str
    material_resolved: bool
    material_code: str | None
    supporting_count: int
    conflicting_count: int
    supporting_precedents: list[PrecedentSummary]
    conflicting_precedents: list[PrecedentSummary]


class GenerateRequest(BaseModel):
    """Request to generate MUA draft."""

    model_config = {"extra": "forbid"}

    material: str = Field(..., min_length=1)
    environment: EnvironmentSpec
    k: int = Field(10, ge=1, le=50)
    mode: Literal["auto", "evaluate_only"] = Field(
        "evaluate_only",
        description="auto=generate if PROCEED, evaluate_only=return decision without generating",
    )


class GenerateResponse(BaseModel):
    """Response from MUA generation."""

    model_config = {"extra": "forbid"}

    request_id: str
    decision: GenerationDecision
    confidence_score: float
    envelope_status: OverlapStatus | None = None
    test_data_currency: str | None = None
    draft_text: str | None = Field(None, description="Generated MUA draft if mode=auto and PROCEED")
    precedents_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review_factors: list[str] = Field(default_factory=list)
    blocking_factors: list[str] = Field(default_factory=list)


class V6StatsResponse(BaseModel):
    """Statistics about the v6 system."""

    model_config = {"extra": "forbid"}

    faiss_index_size: int
    material_resolver_available: bool
    logic_validator_available: bool


# ============================================================================
# Dependency Injection
# ============================================================================


def get_logic_validator() -> LogicValidator | None:
    """Get LogicValidator instance with API key from environment.

    Returns None if ANTHROPIC_API_KEY is not set (allows evaluate_only mode).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return LogicValidator(api_key=api_key)


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/ping")
async def ping() -> dict:
    """Health check for MUA v6 endpoint."""
    return {"status": "ok", "domain": "mua-v6", "version": "6.0.0"}


@router.post("/precedents/search", response_model=PrecedentSearchResponse)
async def search_precedents(request: PrecedentSearchRequest) -> PrecedentSearchResponse:
    """Search for MUA precedents matching material and environment.

    Returns supporting (APPROVED) and conflicting (REJECTED/CANCELLED) precedents
    separately, with material resolution status.
    """
    req_id = str(uuid.uuid4())[:8]
    logger.info(
        "Precedent search request",
        extra={"req_id": req_id, "material": request.material},
    )

    # Resolve material first
    identity = resolve_material_identity(request.material)

    # Search with enrichment
    results = search_enriched_precedents(
        material=request.material,
        environment=request.environment.description if request.environment else None,
        k=request.k,
        family_filter=request.family_filter,
    )

    def to_summary(enriched) -> PrecedentSummary:
        rationale = enriched.rationale or ""
        return PrecedentSummary(
            mua_number=enriched.mua_number,
            material_designation=enriched.material_designation,
            material_family=enriched.material_family,
            environment=enriched.environment,
            determination=enriched.determination,
            rationale_preview=rationale[:300] + "..." if len(rationale) > 300 else rationale,
            similarity_score=enriched.score,
            is_supporting=enriched.is_supporting,
            is_conflicting=enriched.is_conflicting,
        )

    supporting = [to_summary(p) for p in results.supporting]
    conflicting = [to_summary(p) for p in results.conflicting]

    return PrecedentSearchResponse(
        request_id=req_id,
        material_resolved=identity.is_resolved,
        material_code=identity.material_code,
        supporting_count=results.supporting_count,
        conflicting_count=results.conflicting_count,
        supporting_precedents=supporting,
        conflicting_precedents=conflicting,
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate_mua(
    request: GenerateRequest,
    validator: LogicValidator | None = Depends(get_logic_validator),
) -> GenerateResponse:
    """Evaluate and optionally generate MUA draft.

    Pipeline:
    1. Resolve material designation
    2. Search precedents
    3. Query MAPTIS test data
    4. Compute envelope overlap
    5. Evaluate decision
    6. If mode=auto and PROCEED: validate logic and generate draft
    """
    req_id = str(uuid.uuid4())[:8]
    logger.info(
        "MUA generation request",
        extra={"req_id": req_id, "material": request.material, "mode": request.mode},
    )

    warnings: list[str] = []
    review_factors: list[str] = []
    block_reasons: list[str] = []

    # Step 1: Resolve material
    identity = resolve_material_identity(request.material)
    if not identity.is_resolved:
        warnings.append(f"Material '{request.material}' could not be resolved to canonical code")

    # Step 2: Search precedents
    results = search_enriched_precedents(
        material=request.material,
        environment=request.environment.description,
        k=request.k,
    )

    # Step 3: Query MAPTIS test data (if material resolved)
    test_data_status: TestDataStatus | None = None
    test_data_currency: str | None = None
    if identity.material_code:
        try:
            test_data_status = await query_maptis_test_data(
                material_code=identity.material_code,
            )
            # Determine currency string
            if test_data_status.has_current_data:
                test_data_currency = "current"
            elif test_data_status.has_expired_data:
                test_data_currency = "expired"
            else:
                test_data_currency = "not_found"
                warnings.append(f"No MAPTIS test data found for {identity.material_code}")
        except Exception as e:
            logger.warning(f"MAPTIS query failed: {e}", extra={"req_id": req_id})
            warnings.append(f"MAPTIS query failed: {e}")

    # Step 4: Compute envelope overlap
    envelope_result: EnvelopeOverlapResult | None = None
    envelope_status: OverlapStatus | None = None
    if test_data_status and test_data_status.envelope:
        env = test_data_status.envelope
        envelope_result = compute_envelope_overlap(
            query_o2_percent=request.environment.o2_percent,
            query_pressure_psia=request.environment.pressure_psia,
            query_temp_f=request.environment.temperature_f,
            precedent_o2_max=env.moc_o2_pct,
            precedent_pressure_max=env.pressure_psia,
            precedent_temp_min=env.temperature_f,
            precedent_temp_max=env.temperature_f,
        )
        envelope_status = envelope_result.status
        warnings.extend(envelope_result.extrapolation_warnings)

    # Step 5: Evaluate decision
    engine = MUADecisionEngine()

    # Calculate average score from supporting precedents
    avg_score = 0.0
    if results.supporting:
        avg_score = sum(p.score for p in results.supporting) / len(results.supporting)

    decision_result = engine.evaluate(
        supporting_count=results.supporting_count,
        conflicting_count=results.conflicting_count,
        envelope_result=envelope_result,
        test_data_status=test_data_status,
        material_resolved=identity.is_resolved,
        avg_precedent_score=avg_score,
    )

    review_factors = decision_result.review_factors.copy()
    blocking_factors = decision_result.blocking_factors.copy()

    # Step 6: Generate draft if auto mode and PROCEED/WARN
    draft_text: str | None = None
    precedents_used: list[str] = []

    if request.mode == "auto" and decision_result.decision in (
        GenerationDecision.PROCEED,
        GenerationDecision.WARN,
    ):
        if validator is None:
            warnings.append("ANTHROPIC_API_KEY not set - cannot validate rationale logic")
            review_factors.append("Logic validation unavailable")
        else:
            # Validate logic before generating
            try:
                rationale_validation = validator.validate(
                    material=request.material,
                    environment_desc=request.environment.description,
                    precedents=results.supporting[:5],  # Top 5 only
                    req_id=req_id,
                )

                if rationale_validation.is_valid:
                    precedents_used = rationale_validation.citations
                    draft_text = _render_draft(
                        material=request.material,
                        environment=request.environment,
                        rationale=rationale_validation.synthesized_rationale,
                        citations=precedents_used,
                    )
                else:
                    warnings.append(
                        f"Logic validation failed: {rationale_validation.reasoning[:200]}"
                    )
                    # Downgrade decision if validation failed
                    decision_result = DecisionResult(
                        decision=GenerationDecision.REVIEW_REQUIRED,
                        confidence_score=decision_result.confidence_score * 0.5,
                        review_factors=review_factors + ["Rationale logic validation failed"],
                        blocking_factors=blocking_factors,
                        source=decision_result.source,
                    )
            except Exception as e:
                logger.error(f"Logic validation error: {e}", extra={"req_id": req_id})
                warnings.append(f"Logic validation error: {str(e)}")

    return GenerateResponse(
        request_id=req_id,
        decision=decision_result.decision,
        confidence_score=decision_result.confidence_score,
        envelope_status=envelope_status,
        test_data_currency=test_data_currency,
        draft_text=draft_text,
        precedents_used=precedents_used,
        warnings=warnings,
        review_factors=decision_result.review_factors,
        blocking_factors=decision_result.blocking_factors,
    )


@router.get("/stats", response_model=V6StatsResponse)
async def get_v6_stats() -> V6StatsResponse:
    """Get statistics about MUA v6 system health."""
    # Check FAISS index
    try:
        from mira.miul.mua_faiss_search import MUAFAISSSearch
        search = MUAFAISSSearch()
        index_size = len(search.metadata) if hasattr(search, "metadata") and search.metadata else 0
    except Exception:
        index_size = 0

    return V6StatsResponse(
        faiss_index_size=index_size,
        material_resolver_available=True,  # Always available
        logic_validator_available=bool(os.environ.get("ANTHROPIC_API_KEY")),
    )


# ============================================================================
# Internal Helpers
# ============================================================================


def _render_draft(
    material: str,
    environment: EnvironmentSpec,
    rationale: str,
    citations: list[str],
) -> str:
    """Render MUA draft from validated rationale.

    This is a simple template. The real MUA format is more complex
    and should be replaced with proper template rendering.
    """
    env_parts = [environment.description]
    if environment.o2_percent is not None:
        env_parts.append(f"{environment.o2_percent}% O2")
    if environment.pressure_psia is not None:
        env_parts.append(f"{environment.pressure_psia} PSIA")
    if environment.temperature_f is not None:
        env_parts.append(f"{environment.temperature_f}°F")

    env_str = ", ".join(env_parts)
    location = "Habitable" if environment.is_habitable else "Nonhabitable"

    return f"""MATERIAL USAGE AGREEMENT - DRAFT
Generated by MIRA v6 Precedent System

================================================================================
MATERIAL DESIGNATION: {material}
ENVIRONMENT: {env_str}
LOCATION: {location}
================================================================================

RATIONALE:

{rationale}

================================================================================
PRECEDENT CITATIONS:

This determination is based on the following approved MUAs:
{chr(10).join(f'  - {c}' for c in citations)}

================================================================================
NOTE: This is a system-generated draft requiring engineering review.
"""


# ============================================================================
# Corpus-Based Draft Generation (New MUA Parsed Corpus)
# ============================================================================


class CorpusSearchRequest(BaseModel):
    """Request to search the parsed MUA corpus."""

    model_config = {"extra": "forbid"}

    material: str = Field(..., min_length=1, description="Material designation")
    environment: str = Field("", description="Environment description")
    application: str = Field("", description="Application context")
    k: int = Field(15, ge=1, le=50, description="Number of results")


class CorpusPrecedent(BaseModel):
    """Precedent from the parsed MUA corpus."""

    model_config = {"extra": "forbid"}

    mua_number: str
    material_designation: str
    material_family: str
    environment: str
    determination: str
    issues: list[str]
    rationale_preview: str
    score: float


class CorpusSearchResponse(BaseModel):
    """Response from corpus search."""

    model_config = {"extra": "forbid"}

    request_id: str
    total_found: int
    precedents: list[CorpusPrecedent]


class CorpusDraftRequest(BaseModel):
    """Request to generate MUA draft from corpus."""

    model_config = {"extra": "forbid"}

    material: str = Field(..., min_length=1)
    environment: str = Field(..., min_length=1)
    application: str = Field("", description="Application context")
    o2_percent: float | None = Field(None, ge=0, le=100)
    pressure_psia: float | None = Field(None, ge=0)
    temperature_f: float | None = None
    is_habitable: bool = False
    issues: list[str] = Field(default_factory=list)
    k: int = Field(15, ge=1, le=50)


class CorpusCitation(BaseModel):
    """Citation of a precedent in the draft."""

    model_config = {"extra": "forbid"}

    mua_number: str
    material: str
    environment: str
    determination: str
    relevance_score: float
    rationale_excerpt: str


class CorpusDraftResponse(BaseModel):
    """Response with generated MUA draft."""

    model_config = {"extra": "forbid"}

    request_id: str
    material: str
    environment: str
    application: str
    recommended_determination: str
    confidence: float
    coverage_assessment: str
    issues_addressed: list[str]
    gaps_identified: list[str]
    warnings: list[str]
    precedents_cited: list[CorpusCitation]
    rationale: str


# Global singleton for precedent retriever (lazy loaded)
_retriever: V6PrecedentRetriever | None = None


def _get_retriever() -> V6PrecedentRetriever | None:
    """Get or create retriever singleton with filtering/ranking capabilities."""
    global _retriever
    if _retriever is None:
        try:
            _retriever = get_retriever()
            logger.info(f"Loaded V6PrecedentRetriever with {_retriever._index_builder._index.ntotal} records")
        except FileNotFoundError:
            logger.warning("Corpus index not found - build with data_cleaner + index_builder")
            _retriever = None
    return _retriever


@router.post("/corpus/search", response_model=CorpusSearchResponse)
async def search_corpus(request: CorpusSearchRequest) -> CorpusSearchResponse:
    """Search the parsed MUA corpus for precedents.

    Uses V6PrecedentRetriever with FAISS semantic search over 6,370+
    cleaned and normalized historic MUA records from the parsed corpus.
    """
    req_id = str(uuid.uuid4())[:8]
    logger.info(
        "Corpus search request",
        extra={"req_id": req_id, "material": request.material},
    )

    retriever = _get_retriever()
    if retriever is None:
        raise HTTPException(
            status_code=503,
            detail="Corpus index not available. Run index_builder to create it.",
        )

    # Build search query
    query_parts = [request.material]
    if request.environment:
        query_parts.append(request.environment)
    if request.application:
        query_parts.append(request.application)
    query = " ".join(query_parts)

    # Search using retriever's raw search
    results = retriever.search_raw(query, top_k=request.k)

    precedents = []
    for record, score in results:
        rationale = record.rationale or ""
        precedents.append(CorpusPrecedent(
            mua_number=record.mua_number,
            material_designation=record.material_designation,
            material_family=record.material_family.value,
            environment=record.environment.envelope_str(),
            determination=record.determination,
            issues=[i.value for i in record.issues],
            rationale_preview=rationale[:300] + "..." if len(rationale) > 300 else rationale,
            score=score,
        ))

    return CorpusSearchResponse(
        request_id=req_id,
        total_found=len(precedents),
        precedents=precedents,
    )


@router.post("/corpus/draft", response_model=CorpusDraftResponse)
async def generate_corpus_draft(request: CorpusDraftRequest) -> CorpusDraftResponse:
    """Generate MUA draft from corpus precedents.

    Pipeline:
    1. Build NormalizedEnvironment from request
    2. Use V6PrecedentRetriever with structured filtering + ranking
    3. Convert PrecedentMatch to tuples for draft_generator
    4. Generate draft with provenance tracking
    """
    req_id = str(uuid.uuid4())[:8]
    logger.info(
        "Corpus draft request",
        extra={"req_id": req_id, "material": request.material},
    )

    retriever = _get_retriever()
    if retriever is None:
        raise HTTPException(
            status_code=503,
            detail="Corpus index not available. Run index_builder to create it.",
        )

    # Build NormalizedEnvironment for structured matching
    env_type = _detect_environment_type(request.environment)
    normalized_env = NormalizedEnvironment(
        type=env_type,
        o2_percent=request.o2_percent,
        pressure_psia=request.pressure_psia,
        temperature_f=request.temperature_f,
        is_habitable=request.is_habitable,
        raw_text=request.environment,
    )

    # Convert issue strings to IssueCategory enums
    issue_categories = []
    if request.issues:
        for issue_str in request.issues:
            try:
                issue_categories.append(IssueCategory(issue_str.lower()))
            except ValueError:
                logger.warning(f"Unknown issue category: {issue_str}")

    # Use retriever with filtering and ranking
    if issue_categories:
        # Gap-driven workflow: find precedents that address specific issues
        matches = retriever.retrieve_by_gaps(
            material=request.material,
            gaps=issue_categories,
            environment=normalized_env,
            top_k=request.k,
            approved_only=False,  # Include all for analysis
            min_confidence=0.5,
        )
        logger.info(
            f"Gap-driven retrieval: {len(matches)} matches for {len(issue_categories)} issues",
            extra={"req_id": req_id},
        )
    else:
        # Material+environment workflow
        matches = retriever.retrieve_by_material_env(
            material=request.material,
            environment=normalized_env,
            top_k=request.k,
            approved_only=False,  # Include all for analysis
            min_confidence=0.5,
        )
        logger.info(
            f"Material+env retrieval: {len(matches)} matches",
            extra={"req_id": req_id},
        )

    # Convert PrecedentMatch to (record, score) tuples for draft_generator
    # Use composite_score which combines semantic + structured matching
    results = [(m.record, m.composite_score) for m in matches]

    # Generate draft
    from mira.mua.v6.draft_generator import generate_mua_draft

    draft = generate_mua_draft(
        material=request.material,
        environment=request.environment,
        application=request.application,
        precedents=results,
        o2_percent=request.o2_percent,
        pressure_psia=request.pressure_psia,
        temperature_f=request.temperature_f,
        is_habitable=request.is_habitable,
        issues=request.issues,
    )

    # Convert citations
    citations = [
        CorpusCitation(
            mua_number=c.mua_number,
            material=c.material,
            environment=c.environment,
            determination=c.determination,
            relevance_score=c.relevance_score,
            rationale_excerpt=c.rationale_excerpt,
        )
        for c in draft.precedents_cited
    ]

    return CorpusDraftResponse(
        request_id=req_id,
        material=draft.material,
        environment=draft.environment,
        application=draft.application,
        recommended_determination=draft.recommended_determination,
        confidence=draft.confidence,
        coverage_assessment=draft.coverage_assessment,
        issues_addressed=draft.issues_addressed,
        gaps_identified=draft.gaps_identified,
        warnings=draft.warnings,
        precedents_cited=citations,
        rationale=draft.rationale,
    )


def _detect_environment_type(env_text: str) -> EnvironmentType:
    """Detect environment type from description text."""
    env_lower = env_text.lower()

    if "vacuum" in env_lower:
        return EnvironmentType.VACUUM
    if "lox" in env_lower or "gox" in env_lower or "liquid oxygen" in env_lower:
        return EnvironmentType.LOX_GOX
    if "100%" in env_lower and ("o2" in env_lower or "oxygen" in env_lower):
        return EnvironmentType.PURE_O2
    if any(x in env_lower for x in ["enriched", "high oxygen", ">21%"]):
        return EnvironmentType.ENRICHED_O2
    if "cabin" in env_lower or "habitable" in env_lower:
        return EnvironmentType.CABIN_AIR
    if "cryo" in env_lower:
        return EnvironmentType.CRYOGENIC
    if "water" in env_lower or "aqueous" in env_lower:
        return EnvironmentType.WATER
    if "co2" in env_lower or "carbon dioxide" in env_lower:
        return EnvironmentType.CO2
    if "high pressure" in env_lower or "hpgas" in env_lower:
        return EnvironmentType.HIGH_PRESSURE

    return EnvironmentType.UNKNOWN


@router.get("/corpus/stats")
async def get_corpus_stats() -> dict:
    """Get statistics about the parsed MUA corpus."""
    retriever = _get_retriever()
    if retriever is None:
        return {
            "status": "unavailable",
            "message": "Corpus index not built. Run index_builder.py",
        }

    stats = retriever.get_stats()
    return {
        "status": "available",
        "total_records": stats.get("total_records", 0),
        "index_vectors": stats.get("index_vectors", 0),
        "embedding_model": stats.get("embedding_model", "unknown"),
        "by_determination": stats.get("by_determination", {}),
        "by_environment_type": stats.get("by_environment_type", {}),
        "by_material_family": stats.get("by_material_family", {}),
        "by_issue_category": stats.get("by_issue_category", {}),
    }
