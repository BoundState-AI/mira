#!/usr/bin/env python3
"""
Module:   Init  
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

from mira.precedent_engine.core.embeddings import EmbeddingModel
from mira.precedent_engine.core.storage import VectorStore
from mira.precedent_engine.core.enrichment import (
    split_materials,
    normalize_environment,
    normalize_location,
    derive_min_temperature,
    classify_issue,
    resolve_material_key,
    generate_material_hash_key,
    enrich_mua_record,
    is_valid_material,
)
from mira.precedent_engine.core.precedent_engine import PrecedentEngine
from mira.precedent_engine.core.narrator import NarratorLLM
from mira.precedent_engine.core.runner import MUAPrecedentRunner
import uuid

__all__ = [
    "EmbeddingModel",
    "VectorStore",
    "split_materials",
    "normalize_environment",
    "normalize_location",
    "derive_min_temperature",
    "classify_issue",
    "resolve_material_key",
    "generate_material_hash_key",
    "enrich_mua_record",
    "is_valid_material",
    "PrecedentEngine",
    "NarratorLLM",
    "MUAPrecedentRunner",
]
