#!/usr/bin/env python3
"""
Module:   Init  
Purpose: Text chunking modules.

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

from athena.chunking.hybrid import HybridChunker
from athena.chunking.post import PostChunkingEngine
from athena.chunking.semantic import SemanticChunker

__all__ = ["HybridChunker", "PostChunkingEngine", "SemanticChunker"]
