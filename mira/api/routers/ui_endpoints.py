#!/usr/bin/env python3
"""
Module: Ui Endpoints
Purpose: UI Endpoints Router for BoundState Frontend.

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

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging

LOGGER = logging.getLogger(__name__)

# Semantic search - lazy loaded on first use
_semantic_search = None
_hybrid_search = None
_semantic_search_attempted = False
SEMANTIC_AVAILABLE = False
HYBRID_AVAILABLE = False
MAPTIS_SEARCH_COMING_SOON_MESSAGE = (
    "MAPTIS material search is coming soon and is currently unavailable in this environment."
)

try:
    from mira.core.search_engine import SemanticSearchEngine
    SEMANTIC_AVAILABLE = True
except ImportError as e:
    LOGGER.warning(f"Semantic search unavailable: {e}")

try:
    from mira.search.hybrid_search import create_hybrid_search_from_mira, patch_semantic_search_engine
    HYBRID_AVAILABLE = True
except ImportError as e:
    LOGGER.warning(f"Hybrid search unavailable: {e}")


def get_semantic_search():
    """Get the semantic search instance (lazy loaded).

    P0 Fix: Now includes hybrid BM25+FAISS+RRF search for improved exact-match retrieval.
    """
    global _semantic_search, _hybrid_search, _semantic_search_attempted

    if not SEMANTIC_AVAILABLE:
        return None

    if _semantic_search is None and not _semantic_search_attempted:
        _semantic_search_attempted = True
        try:
            _semantic_search = SemanticSearchEngine()
            LOGGER.info("SemanticSearchEngine initialized")

            # P0 FIX: Wire in hybrid search (BM25 + FAISS + RRF fusion)
            if HYBRID_AVAILABLE and _hybrid_search is None:
                try:
                    # Find the FAISS index and metadata paths
                    faiss_dir = Path(__file__).parent.parent.parent / "databases" / "mira_v2_faiss"
                    faiss_index_path = faiss_dir / "maptis_faiss_index.bin"
                    metadata_path = faiss_dir / "maptis_index_metadata.json"

                    if faiss_index_path.exists() and metadata_path.exists():
                        LOGGER.info(f"Initializing hybrid search from: {faiss_dir}")
                        _hybrid_search = create_hybrid_search_from_mira(
                            faiss_index_path=str(faiss_index_path),
                            materials_metadata_path=str(metadata_path),
                        )
                        patch_semantic_search_engine(_semantic_search, _hybrid_search)
                        LOGGER.info("Hybrid BM25+FAISS+RRF search enabled (P0 fix)")
                    else:
                        LOGGER.warning(f"Hybrid search files not found at {faiss_dir}, using semantic-only")
                except Exception as e:
                    LOGGER.warning(f"Failed to initialize hybrid search (non-critical): {e}")
                    LOGGER.info("Continuing with semantic-only search")

        except Exception as e:
            LOGGER.error(f"Failed to initialize semantic search: {e}")
            return None

    return _semantic_search


router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class MaterialSearchRequest(BaseModel):
    """Request for material semantic search."""
    query: str = Field(..., min_length=1, description="Search query")
    top_k: int = Field(25, ge=1, le=100, description="Max results")


class MaterialSearchResult(BaseModel):
    """Single material search result."""
    material_key: str
    material_designation: Optional[str] = None
    material_code: Optional[str] = None
    preview: Optional[str] = None
    score: float
    o2_rating: Optional[str] = None
    h2_rating: Optional[str] = None
    flamm_rating: Optional[str] = None
    corr_rating: Optional[str] = None
    scc_rating: Optional[str] = None
    tvs_rating: Optional[str] = None
    tox_rating: Optional[str] = None
    row_uid: Optional[str] = None


class MaterialSearchResponse(BaseModel):
    """Response for material search."""
    results: List[MaterialSearchResult]
    total: int
    served_path: str = "/api/search"
    pipeline: str = "semantic"
    message: Optional[str] = None


class BOKSearchRequest(BaseModel):
    """Request for BOK search."""
    query: str = Field(..., min_length=1, description="Search query")
    k: int = Field(10, ge=1, le=50, description="Max results")


class BOKSearchResult(BaseModel):
    """Single BOK search result."""
    rank: int
    relevance_score: float
    text: str
    source: str
    section: str
    page: Optional[int] = None
    tags: List[str] = []


class BOKSearchResponse(BaseModel):
    """Response for BOK search."""
    results: List[BOKSearchResult]
    query: str


class TestClassCounts(BaseModel):
    """Test class counts response."""
    pass  # Dynamic dict


# ============================================================================
# Material Search Endpoint
# ============================================================================

@router.post("/api/search", response_model=MaterialSearchResponse)
async def material_search(request: MaterialSearchRequest):
    """
    Semantic search across MAPTIS materials.

    Uses FAISS index with sentence-transformers embeddings.
    """
    search = get_semantic_search()

    if search is None:
        LOGGER.warning("Semantic search not available, returning coming-soon response")
        return MaterialSearchResponse(
            results=[],
            total=0,
            pipeline="coming_soon",
            message=MAPTIS_SEARCH_COMING_SOON_MESSAGE,
        )

    try:
        # Search using SemanticSearchEngine
        results = search.search(
            query=request.query,
            top_k=request.top_k
        )

        # Transform to response format
        # SemanticSearchEngine returns: [{"material": {...}, "similarity_score": float, "original_material": {...}}]
        material_results = []
        for r in results:
            mat = r.get("material", {})
            orig = r.get("original_material", {})

            # Get material designation from material dict or original_material
            designation = (
                mat.get("designation") or
                mat.get("name") or
                orig.get("designation") or
                orig.get("name") or
                ""
            )

            # Get material code
            material_code = (
                mat.get("material_code") or
                orig.get("material_code") or
                str(orig.get("material_key", ""))
            )

            # Get material key (for lookup)
            material_key = str(orig.get("material_key", mat.get("material_id", "")))

            # Get preview text
            preview = mat.get("composition") or orig.get("composition") or ""
            if preview and len(preview) > 200:
                preview = preview[:200] + "..."

            material_results.append(MaterialSearchResult(
                material_key=material_key,
                material_designation=designation,
                material_code=material_code,
                preview=preview,
                score=r.get("similarity_score", 0.0),
                o2_rating=orig.get("o2_rating"),
                h2_rating=orig.get("h2_rating"),
                flamm_rating=orig.get("flamm_rating"),
                corr_rating=orig.get("corr_rating"),
                scc_rating=orig.get("scc_rating"),
                tvs_rating=orig.get("tvs_rating"),
                tox_rating=orig.get("tox_rating"),
                row_uid=orig.get("row_uid", material_key),
            ))

        return MaterialSearchResponse(
            results=material_results,
            total=len(material_results),
        )

    except Exception as e:
        LOGGER.error(f"Material search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# BOK Search Endpoints
# ============================================================================

@router.post("/api/v1/o2/search-bok", response_model=BOKSearchResponse)
async def o2_bok_search(request: BOKSearchRequest):
    """
    Search O2 Body of Knowledge (BOK) standards.

    Returns relevant standards sections for oxygen compatibility.
    """
    return await _bok_search(request, environment="oxygen")


@router.post("/api/v1/h2/search-bok", response_model=BOKSearchResponse)
async def h2_bok_search(request: BOKSearchRequest):
    """
    Search H2 Body of Knowledge (BOK) standards.

    Returns relevant standards sections for hydrogen compatibility.
    """
    return await _bok_search(request, environment="hydrogen")


async def _bok_search(request: BOKSearchRequest, environment: str) -> BOKSearchResponse:
    """Internal BOK search implementation."""
    search = get_semantic_search()

    if search is None:
        return BOKSearchResponse(
            results=[],
            query=request.query
        )

    # Check if BOK search method exists
    if not hasattr(search, 'search_index'):
        # BOK index not available - return empty results
        LOGGER.warning(f"BOK search not available (search_index method missing)")
        return BOKSearchResponse(
            results=[],
            query=request.query
        )

    try:
        # Search BOK index with environment filter
        results = search.search_index(
            index_name="bok",
            query=f"{request.query} {environment}",
            top_k=request.k,
        )

        # Transform to response format
        bok_results = []
        for rank, r in enumerate(results):
            meta = r.metadata
            bok_results.append(BOKSearchResult(
                rank=rank + 1,
                relevance_score=r.score,
                text=r.content[:500] if r.content else "",
                source=meta.get("source", meta.get("doc_id", "Unknown")),
                section=meta.get("section", meta.get("section_number", "")),
                page=meta.get("page"),
                tags=meta.get("tags", [environment]),
            ))

        return BOKSearchResponse(
            results=bok_results,
            query=request.query
        )

    except Exception as e:
        LOGGER.error(f"BOK search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health Check
# ============================================================================

@router.get("/api/ui/health")
async def ui_health():
    """Health check for UI endpoints."""
    search = get_semantic_search()

    return {
        "status": "ok",
        "semantic_search": search is not None and getattr(search, 'initialized', False),
        "h2_engine": search.h2_engine is not None if search else False,
        "o2_engine": search.o2_engine is not None if search else False,
    }


__safety_critical__ = True  # NASA SWE-032 compliance
