#!/usr/bin/env python3
"""
Module: Search
Purpose: Search Router for BoundState API

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

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.models.query import EngineeringQuery, QueryContext, EnvironmentType
from core.models.answer import EngineAnswer
from core.query.engine import QueryEngine
from core.infra.document_store import NullDocumentStore

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Global query engine instance (will be replaced with proper DI)
_query_engine: Optional[QueryEngine] = None


def _try_load_faiss_store():
    """Try to load FAISS store from default locations."""
    try:
        from core.infra.faiss_store import FaissDocumentStore

        # Try common database paths
        possible_paths = [
            Path(__file__).parent.parent.parent / "mira" / "databases" / "maptis_faiss_db",
            Path("mira/databases/maptis_faiss_db"),
            Path("C:/BoundState/mira/databases/maptis_faiss_db"),
        ]

        for path in possible_paths:
            if path.exists() and (path / "metadata.json").exists():
                LOGGER.info(f"Loading FAISS store from: {path}")
                return FaissDocumentStore(index_dir=path)

        LOGGER.info("No FAISS index found, using NullDocumentStore")
        return None
    except ImportError as e:
        LOGGER.warning(f"FAISS not available: {e}")
        return None
    except Exception as e:
        LOGGER.warning(f"Failed to load FAISS store: {e}")
        return None


def get_query_engine() -> QueryEngine:
    """Dependency to get the QueryEngine instance."""
    global _query_engine
    if _query_engine is None:
        # Try to load FAISS, fall back to NullDocumentStore
        store = _try_load_faiss_store()
        if store is None:
            store = NullDocumentStore()
        _query_engine = QueryEngine(document_store=store)
    return _query_engine


def set_query_engine(engine: QueryEngine) -> None:
    """Set the global QueryEngine instance (for testing/configuration)."""
    global _query_engine
    _query_engine = engine


router = APIRouter()


class SearchRequest(BaseModel):
    """API-level search request model."""

    question: str = Field(description="Natural-language question.")
    environment: Optional[EnvironmentType] = Field(
        default=None,
        description="Optional environment hint for filtering (oxygen, hydrogen).",
    )
    material_key: Optional[str] = Field(
        default=None,
        description="Canonical material identifier, if known.",
    )
    application_id: Optional[str] = Field(
        default=None,
        description="Optional application or subsystem identifier.",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Extra structured filters (program, spec set, etc.).",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of results to return.",
    )


class SearchResponse(BaseModel):
    """Wrapper around EngineAnswer for the search API."""

    answer: EngineAnswer


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Simple health check for the search endpoint."""
    return {"status": "ok"}


@router.post("/query", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    engine: QueryEngine = Depends(get_query_engine),
) -> SearchResponse:
    """Generic search endpoint backed by QueryEngine.

    Takes a natural-language question with optional structured filters
    and returns matching documents with evidence.

    Note: This endpoint returns classification=UNKNOWN. For compatibility
    assessments, use the domain-specific endpoints (/mira/o2, /mira/h2).
    """
    context = QueryContext(
        application_id=request.application_id,
        material_key=request.material_key,
        environment=request.environment,
        metadata=request.metadata,
    )

    eng_query = EngineeringQuery(question=request.question, context=context)
    result = engine.search(eng_query, top_k=request.top_k)

    return SearchResponse(answer=result)


__safety_critical__ = True  # NASA SWE-032 compliance
