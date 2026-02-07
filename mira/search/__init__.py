#!/usr/bin/env python3
"""
Module:   Init  
Purpose: MIRA Search Module.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

# Lazy imports to avoid loading heavy deps at import time
__all__ = [
    "UnifiedSemanticSearch",
    "MUASearch",
    "SearchResult",
    "MultiIndexSearchResults",
    # P0 Hybrid Search
    "MIRAHybridSearch",
    "HybridSearchResult",
    "create_hybrid_search_from_mira",
    "patch_semantic_search_engine",
]


def __getattr__(name: str):
    """Lazy import search classes."""
    if name == "UnifiedSemanticSearch":
        from .semantic_search import UnifiedSemanticSearch
        return UnifiedSemanticSearch
    elif name == "MUASearch":
        from .mua_search import MUASearch
        return MUASearch
    elif name == "SearchResult":
        from .semantic_search import SearchResult
        return SearchResult
    elif name == "MultiIndexSearchResults":
        from .semantic_search import MultiIndexSearchResults
        return MultiIndexSearchResults
    # P0 Hybrid Search
    elif name == "MIRAHybridSearch":
        from .hybrid_search import MIRAHybridSearch
        return MIRAHybridSearch
    elif name == "HybridSearchResult":
        from .hybrid_search import HybridSearchResult
        return HybridSearchResult
    elif name == "create_hybrid_search_from_mira":
        from .hybrid_search import create_hybrid_search_from_mira
        return create_hybrid_search_from_mira
    elif name == "patch_semantic_search_engine":
        from .hybrid_search import patch_semantic_search_engine
        return patch_semantic_search_engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
