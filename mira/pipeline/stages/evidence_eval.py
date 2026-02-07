#!/usr/bin/env python3
"""
Stage 8: Evidence Evaluation — Is there enough data to make a decision?

Rule 1.4: No evidence → REQUIRES_TESTING or INSUFFICIENT_DATA. Never YES/NO.
Rule 1.3: Semantic evidence alone cannot produce YES/NO for specific material.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)


def _materials_match(query_material: str, db_material: str) -> bool:
    """
    Flexible material name matching.

    Rule 5.2: This should eventually call the shared utility in
    mira.core.material_name_normalizer. For now, inline implementation.
    """
    if not query_material or not db_material:
        return False

    q = query_material.lower().strip()
    d = db_material.lower().strip()

    if q in d or d in q:
        return True

    q_numbers = set(re.findall(r"\b(\d{3,4})[A-Za-z]?\b", q))
    d_numbers = set(re.findall(r"\b(\d{3,4})[A-Za-z]?\b", d))

    families = {
        "aluminum": ("al", "aluminium"),
        "stainless": ("ss", "cres", "stainless steel"),
        "inconel": ("in", "inconel"),
        "titanium": ("ti", "titanium"),
        "hastelloy": ("ha", "hastelloy"),
        "monel": ("monel",),
        "copper": ("cu", "copper"),
        "nickel": ("ni", "nickel"),
    }

    if q_numbers and d_numbers and q_numbers & d_numbers:
        for family, aliases in families.items():
            q_match = family in q or any(a in q for a in aliases)
            d_match = family in d or any(a in d for a in aliases)
            if q_match and d_match:
                return True
            if q_match and q_numbers & d_numbers:
                return True

    return False


class EvidenceEvalStage(PipelineStage):
    """
    Stage 8: Determine if sufficient evidence exists to make a decision.

    Sets ctx.has_sufficient_evidence and ctx.evidence_eval_reason.
    """

    @property
    def name(self) -> str:
        return "evidence_eval"

    def should_skip(self, ctx: QueryContext) -> bool:
        if ctx.boundary_short_circuited:
            return True
        return ctx.pipeline_name not in ("compatibility",)

    def execute(self, ctx: QueryContext) -> QueryContext:
        has_structured = bool(ctx.mua_precedents or ctx.test_results)
        has_semantic = bool(
            ctx.semantic_evidence and ctx.semantic_evidence.get("total_results", 0) > 0
        )

        # If no material specified, general query — allow semantic evidence
        if not ctx.constraints or not ctx.constraints.material:
            ctx.has_sufficient_evidence = has_structured or has_semantic
            if not ctx.has_sufficient_evidence:
                ctx.evidence_eval_reason = "No evidence found for this query"
            return ctx

        # Material-specific query: Rule 1.3
        material = ctx.constraints.material

        if has_structured:
            ctx.has_sufficient_evidence = True
            logger.info(f"[EVIDENCE] Sufficient structured data for '{material}'")
            return ctx

        # Check if semantic evidence mentions the actual material
        if has_semantic:
            if self._semantic_mentions_material(material, ctx.semantic_evidence):
                ctx.has_sufficient_evidence = True
                logger.info(f"[EVIDENCE] Semantic evidence confirms '{material}'")
                return ctx

        # No matching evidence at all
        ctx.has_sufficient_evidence = False
        ctx.evidence_eval_reason = (
            f"Material '{material}' not found in MAPTIS, MUA precedents, or BOK. "
            f"This may be an unknown material or require different search terms."
        )
        logger.info(f"[EVIDENCE] INSUFFICIENT for '{material}'")

        return ctx

    @staticmethod
    def _semantic_mentions_material(material: str, semantic: dict) -> bool:
        """Check if semantic evidence actually mentions the queried material."""
        for source_key in ("maptis_data", "mua_precedents"):
            source = semantic.get(source_key, {})
            if not isinstance(source, dict):
                continue
            for band in ("high", "medium"):
                for hit in source.get(band, []):
                    # Handle both dict and ScoredResult objects
                    content = None
                    if hasattr(hit, "content"):
                        content = hit.content
                    elif isinstance(hit, dict):
                        content = hit.get("content")

                    if not content or not isinstance(content, dict):
                        continue

                    mat_name = (
                        content.get("material_designation")
                        or content.get("material_name")
                        or ""
                    )
                    if mat_name and _materials_match(material, mat_name):
                        return True

        return False
