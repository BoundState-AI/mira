#!/usr/bin/env python3
"""
Module:   Init  
Purpose: Document indexing modules.

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

from athena.indexing.document import DocumentDiscoveryIndex
from athena.indexing.chunks import SmartChunksIndex
from athena.indexing.smart import SmartIndexer
from athena.indexing.enhanced import EnhancedSmartIndexer
from athena.indexing.image import ImageIndexer
from athena.indexing.incremental import IncrementalIndexer

__all__ = [
    "DocumentDiscoveryIndex",
    "SmartChunksIndex",
    "SmartIndexer",
    "EnhancedSmartIndexer",
    "ImageIndexer",
    "IncrementalIndexer",
]
