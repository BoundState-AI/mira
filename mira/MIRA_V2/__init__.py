#!/usr/bin/env python3
"""
Module:   Init  
Purpose: MIRA V2 Integration Module.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from pathlib import Path

# Module root directory
MIRA_V2_ROOT = Path(__file__).parent

# Default paths for FAISS indexes
FAISS_INDEX_DIR = MIRA_V2_ROOT.parent / "databases" / "mira_v2_faiss"

# Data directories
DATA_DIR = MIRA_V2_ROOT / "data"
MUA_EMBEDDINGS_DIR = DATA_DIR / "mua_embeddings"
BOK_EMBEDDINGS_DIR = DATA_DIR / "bok_embeddings"

__all__ = [
    "MIRA_V2_ROOT",
    "FAISS_INDEX_DIR",
    "DATA_DIR",
]
