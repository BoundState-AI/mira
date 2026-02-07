#!/usr/bin/env python3
"""
Module:   Init  
Purpose: Infrastructure adapters (DB, graph, config, logging, cache).

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

from .document_store import DocumentStore, DocumentHit, NullDocumentStore

# Lazy import for FaissDocumentStore (requires optional deps)
def get_faiss_store():
    """Get FaissDocumentStore class (lazy import)."""
    from .faiss_store import FaissDocumentStore
    return FaissDocumentStore

__all__ = [
    "DocumentStore",
    "DocumentHit",
    "NullDocumentStore",
    "get_faiss_store",
]
