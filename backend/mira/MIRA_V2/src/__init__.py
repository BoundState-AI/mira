#!/usr/bin/env python3
"""MIRA V2 Source Modules."""

# Import main classes for convenience
try:
    from .query_engine_v2 import EvidenceFirstQueryEngine
except ImportError:
    EvidenceFirstQueryEngine = None

__all__ = ["EvidenceFirstQueryEngine"]
