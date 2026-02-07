#!/usr/bin/env python3
"""
Module: Material Metrics
Purpose: Prometheus metrics for material resolution operations.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B:
Safety Critical: True
"""

from __future__ import annotations

import uuid

try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    # Graceful degradation if prometheus_client not installed
    PROMETHEUS_AVAILABLE = False

    # No-op stub classes
    class Counter:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, *args, **kwargs):
            return self
        def inc(self, *args, **kwargs):
            pass

    class Histogram:
        def __init__(self, *args, **kwargs):
            pass
        def observe(self, *args, **kwargs):
            pass

    class Gauge:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, *args, **kwargs):
            return self
        def set(self, *args, **kwargs):
            pass


__all__ = [
    'resolution_total',
    'conflict_total',
    'fallback_used_total',
    'resolution_duration',
    'match_strength_distribution',
    'PROMETHEUS_AVAILABLE',
]

__safety_critical__ = True


# Total resolutions by status and mode
resolution_total = Counter(
    'material_resolution_total',
    'Total material identifier resolutions',
    ['status', 'mode'],
)

# Conflict counter
conflict_total = Counter(
    'material_resolution_conflicts',
    'Total resolution conflicts detected (key→A, code→B)',
)

# Legacy fallback usage (numeric key-only)
fallback_used_total = Counter(
    'material_resolution_fallback_used',
    'Times a numeric key-only legacy fallback was used',
)

# Duration histogram
resolution_duration = Histogram(
    'material_resolution_duration_seconds',
    'Duration of material resolution operations',
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2),
)

# Match strength gauge (last observed)
match_strength_distribution = Gauge(
    'material_match_strength',
    'Last observed match strength (0/1/2)',
    ['strength_level'],
)


# Pre-initialize labels to avoid cardinality surprises
def _initialize_metrics() -> None:
    """Initialize metric labels to prevent runtime cardinality issues.

    This pre-creates all expected label combinations so Prometheus
    has a stable cardinality from the start.

    Compliance:
        SWE-055: Performance monitoring best practices
    """
    if not PROMETHEUS_AVAILABLE:
        return

    # Initialize match strength levels
    for lvl in ('0', '1', '2'):
        match_strength_distribution.labels(lvl).set(0)

    # Initialize resolution status/mode combinations
    for status in ('and_match', 'or_fallback', 'conflict', 'no_match'):
        for mode in ('AND_THEN_OR', 'AND_ONLY', 'OR_ONLY'):
            resolution_total.labels(status=status, mode=mode).inc(0)


# Auto-initialize on module import
_initialize_metrics()
