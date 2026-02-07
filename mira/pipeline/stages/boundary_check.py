#!/usr/bin/env python3
"""
Stage 4: Boundary Check — Deterministic O2/H2 hard rules.

Rule 2.1: Executes BEFORE any LLM involvement.
Rule 2.2: BOK prohibitions OVERRIDE MUA precedents.

If a hard prohibition fires, sets ctx.boundary_short_circuited = True
and the pipeline stops.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ..context import EnvironmentClass, Verdict
from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)


class BoundaryCheckStage(PipelineStage):
    """
    Stage 4: Check deterministic O2/H2 boundaries.

    Only runs for compatibility pipeline queries with oxygen or hydrogen
    environment. Calls the O2/H2 engine if available.
    """

    @property
    def name(self) -> str:
        return "boundary_check"

    def should_skip(self, ctx: QueryContext) -> bool:
        # Only runs for compatibility pipeline
        if ctx.pipeline_name != "compatibility":
            return True
        # Only runs when we have a material and an O2/H2 environment
        if not ctx.constraints or not ctx.constraints.material:
            return True
        env_class = ctx.constraints.environment_class
        if env_class not in (EnvironmentClass.OXYGEN, EnvironmentClass.HYDROGEN):
            return True
        return False

    def execute(self, ctx: QueryContext) -> QueryContext:
        constraints = ctx.constraints
        query = ctx.raw_query

        if constraints.environment_class == EnvironmentClass.OXYGEN:
            return self._check_o2_boundaries(ctx)
        elif constraints.environment_class == EnvironmentClass.HYDROGEN:
            return self._check_h2_boundaries(ctx)

        return ctx

    def _check_o2_boundaries(self, ctx: QueryContext) -> QueryContext:
        """Check O2 deterministic rules via mira.o2.engine."""
        try:
            from mira.o2.engine import evaluate_o2_compatibility
            from mira.o2.models import O2CompatibilityRequest, OxygenPhase
            from core.models.answer import AnswerSeverity
        except ImportError:
            logger.info("[BOUNDARY] O2 engine not available — skipping")
            return ctx

        constraints = ctx.constraints
        query_lower = ctx.raw_query.lower()

        # Determine pressure
        pressure_psia = constraints.pressure_psi or self._extract_pressure(query_lower) or 1000.0

        # Determine phase
        phase = OxygenPhase.GAS
        if any(kw in query_lower for kw in ("lox", "liquid oxygen", "cryogenic")):
            phase = OxygenPhase.LIQUID

        # Determine temperature (default room temp)
        temp_k = (constraints.temp_c_max + 273.15) if constraints.temp_c_max else 294.26

        try:
            request = O2CompatibilityRequest(
                question=ctx.raw_query,
                material_key=constraints.material,
                pressure_psia=pressure_psia,
                temperature_k=temp_k,
                phase=phase,
            )
            result = evaluate_o2_compatibility(request)

            if result.classification == AnswerSeverity.PROHIBITED:
                logger.info(
                    f"[BOUNDARY] PROHIBITED: {constraints.material} "
                    f"in {phase.value} at {pressure_psia} psia"
                )
                ctx.boundary_verdict = Verdict.NO
                ctx.boundary_rationale = result.rationale
                ctx.boundary_short_circuited = True

        except Exception as exc:
            logger.warning(f"[BOUNDARY] O2 check failed (continuing): {exc}")

        return ctx

    def _check_h2_boundaries(self, ctx: QueryContext) -> QueryContext:
        """Check H2 deterministic rules via mira.h2.engine."""
        try:
            from mira.h2.engine import evaluate_h2_compatibility
            from mira.h2.models import H2CompatibilityRequest
        except ImportError:
            logger.info("[BOUNDARY] H2 engine not available — skipping")
            return ctx

        # H2 boundary checks follow similar pattern to O2
        # Placeholder for H2-specific logic
        logger.info("[BOUNDARY] H2 boundary check — not yet implemented")
        return ctx

    @staticmethod
    def _extract_pressure(query_lower: str) -> float | None:
        """Fallback pressure extraction from raw query text."""
        match = re.search(r"(\d+(?:\.\d+)?)\s*psi[a]?", query_lower)
        return float(match.group(1)) if match else None
