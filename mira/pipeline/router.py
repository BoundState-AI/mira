#!/usr/bin/env python3
"""
Module: Pipeline Router
Purpose: Routes classified queries to the correct sub-pipeline.

Implements RULES.md §3 — Intent Routing.
Key principle: When in doubt, route to COMPATIBILITY (Rule 3.3).

BoundState AI 2026
Version: 3.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .context import QueryIntent
from .stage import PipelineStage

if TYPE_CHECKING:
    from .context import QueryContext

logger = logging.getLogger(__name__)

# ── Rule 3.2: Compatibility signals (BINARY — one match = compatibility) ──
# These are checked BEFORE the scored intent classifier.
# Any single match forces the compatibility pipeline.

_COMPATIBILITY_PATTERNS = [
    # Gas service keywords
    re.compile(r"\b(oxygen|O2|O₂|GOX|LOX|hydrogen|H2|H₂|GH2|LH2)\b", re.IGNORECASE),
    # Explicit compatibility language
    re.compile(r"\b(compatible|compatibility|approved|rated for|safe for)\b", re.IGNORECASE),
    # Pressure/temperature constraints (imply compatibility check)
    re.compile(r"\b(?:at|for)\s+\d+\s*(?:psi|psia|bar|Pa|kPa|MPa)\b", re.IGNORECASE),
    # "Can I use X in Y" pattern
    re.compile(r"\bcan\s+(?:I|we)\s+use\b", re.IGNORECASE),
    # "Is X suitable/acceptable for Y"
    re.compile(r"\b(?:is|are)\s+\w+\s+(?:suitable|acceptable|allowed|permitted)\b", re.IGNORECASE),
    # Service context
    re.compile(r"\b(?:service|environment)\b", re.IGNORECASE),
]


def _has_compatibility_signal(query: str) -> bool:
    """Rule 3.2: ANY single compatibility pattern match = compatibility."""
    return any(p.search(query) for p in _COMPATIBILITY_PATTERNS)


class RouteStage(PipelineStage):
    """
    Stage 3: Route query to the correct sub-pipeline.

    Sets ctx.pipeline_name which downstream stages use in should_skip().

    Routing logic (Rule 3.4):
    1. If ANY compatibility signal fires → "compatibility"
    2. Elif materials_search score > 0.4 AND compatibility score == 0 → "materials_search"
    3. Elif document_lookup score > 0.4 → "document_lookup"
    4. Else → "general"
    """

    @property
    def name(self) -> str:
        return "route"

    def execute(self, ctx: QueryContext) -> QueryContext:
        query = ctx.raw_query

        # Rule 3.2: Binary compatibility signal check (highest priority)
        if _has_compatibility_signal(query):
            ctx.intent = QueryIntent.COMPATIBILITY
            ctx.pipeline_name = "compatibility"
            logger.info(f"[ROUTE] → compatibility (binary signal match)")
            return ctx

        # Fall through to scored intent classification
        compat_score = ctx.intent_scores.get("compatibility_query", 0.0)
        materials_score = ctx.intent_scores.get("materials_query", 0.0)
        doc_score = ctx.intent_scores.get("document_lookup", 0.0)
        comparison_score = ctx.intent_scores.get("comparison", 0.0)

        # Rule 3.4: Routing thresholds
        if compat_score > 0:
            # Any nonzero compatibility score from classifier = compatibility
            ctx.intent = QueryIntent.COMPATIBILITY
            ctx.pipeline_name = "compatibility"
            logger.info(f"[ROUTE] → compatibility (classifier score: {compat_score:.2f})")

        elif comparison_score > 0.3:
            ctx.intent = QueryIntent.COMPARISON
            ctx.pipeline_name = "compatibility"  # comparisons need full evidence
            logger.info(f"[ROUTE] → comparison/compatibility (score: {comparison_score:.2f})")

        elif materials_score > 0.4 and compat_score == 0:
            ctx.intent = QueryIntent.MATERIALS_SEARCH
            ctx.pipeline_name = "materials_search"
            logger.info(f"[ROUTE] → materials_search (score: {materials_score:.2f})")

        elif doc_score > 0.4:
            ctx.intent = QueryIntent.DOCUMENT_LOOKUP
            ctx.pipeline_name = "document_lookup"
            logger.info(f"[ROUTE] → document_lookup (score: {doc_score:.2f})")

        else:
            # Rule 3.3: When in doubt → general (NOT compatibility, to avoid
            # running expensive pipeline on "hello" or "what is MIRA")
            ctx.intent = QueryIntent.GENERAL
            ctx.pipeline_name = "general"
            logger.info(f"[ROUTE] → general (no strong signal)")

        return ctx
