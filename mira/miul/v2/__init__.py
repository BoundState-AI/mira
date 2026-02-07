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

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

__version__ = "2.3.0"

# Core models
from .models import (
    # Enums
    Zone,
    BindingMethod,
    BindingConfidence,
    ExplosionPolicy,
    NodeType,
    IssueSeverity,
    IssueType,
    # Data classes
    PageExtract,
    DrawingEntity,
    DrawingKey,
    DrawingGraph,
    GraphEdge,
    MIULEntry,
    Issue,
    PackageExtract,
    # Constants
    ZONE_WEIGHTS,
    THRESHOLD_PRIMARY,
    THRESHOLD_SUPPORTING,
    THRESHOLD_AMBIGUOUS,
)

# Configuration
from .config import PipelineConfig

# Pipeline functions
from .cli import run_pipeline

# Phase modules (for advanced usage)
from . import extract
from . import assemble
from . import graph
from . import miul

__all__ = [
    # Version
    "__version__",
    # Enums
    "Zone",
    "BindingMethod",
    "BindingConfidence",
    "ExplosionPolicy",
    "NodeType",
    "IssueSeverity",
    "IssueType",
    # Data classes
    "PageExtract",
    "DrawingEntity",
    "DrawingKey",
    "DrawingGraph",
    "GraphEdge",
    "MIULEntry",
    "Issue",
    "PackageExtract",
    # Constants
    "ZONE_WEIGHTS",
    "THRESHOLD_PRIMARY",
    "THRESHOLD_SUPPORTING",
    "THRESHOLD_AMBIGUOUS",
    # Configuration
    "PipelineConfig",
    # Pipeline
    "run_pipeline",
    # Modules
    "extract",
    "assemble",
    "graph",
    "miul",
]
