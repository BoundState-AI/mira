#!/usr/bin/env python3
"""
Module: Document Store
Purpose: Document Store Abstraction for BoundState

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol


@dataclass(frozen=True)
class DocumentHit:
    """Single search hit returned from the document store."""

    doc_id: str
    title: str
    snippet: str
    score: float
    metadata: Dict[str, Any]


class DocumentStore(Protocol):
    """Abstract interface for document search backends.

    Implementations must provide a search method that returns
    DocumentHit objects. The actual backend (FAISS, Postgres, etc.)
    is hidden behind this interface.
    """

    def search(
        self,
        query: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> Iterable[DocumentHit]:
        """Search documents and return top_k hits.

        Args:
            query: The search query string
            filters: Optional structured filters (material_key, environment, etc.)
            top_k: Maximum number of results to return

        Returns:
            Iterable of DocumentHit objects, ordered by score descending
        """
        ...


class NullDocumentStore:
    """Stub implementation that returns no results.

    Use this for testing or when no backend is configured.
    """

    def search(
        self,
        query: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> Iterable[DocumentHit]:
        """Return empty results."""
        return []


__all__ = ["DocumentHit", "DocumentStore", "NullDocumentStore"]
