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

    # Conservative worst-case assumptions used ONLY when the caller provides no
    # value. Any use is logged and surfaced in the rationale (never silent).
    DEFAULT_PRESSURE_PSIA = 1000.0
    DEFAULT_TEMPERATURE_K = 294.26  # ~21 C / 70 F ambient

    @property
    def name(self) -> str:
        return "boundary_check"

    @staticmethod
    def _append_assumptions(rationale: str | None, assumptions: list[str]) -> str | None:
        """Surface any default assumptions in the rationale instead of hiding them."""
        if not assumptions:
            return rationale
        note = "Assumptions: " + "; ".join(assumptions) + "."
        return f"{rationale}\n\n{note}" if rationale else note

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

        # Determine pressure. If the caller gave us nothing we fall back to a
        # conservative worst-case assumption, but we record that it was assumed
        # rather than silently substituting an arbitrary value.
        pressure_psia = constraints.pressure_psi or self._extract_pressure(query_lower)
        assumptions: list[str] = []
        if pressure_psia is None:
            pressure_psia = self.DEFAULT_PRESSURE_PSIA
            assumptions.append(
                f"pressure not specified; assumed worst-case {pressure_psia:.0f} psia"
            )
            logger.warning(
                "[BOUNDARY] O2 pressure not specified for %s; assuming %.0f psia",
                constraints.material, pressure_psia,
            )

        # Determine phase
        phase = OxygenPhase.GAS
        if any(kw in query_lower for kw in ("lox", "liquid oxygen", "cryogenic")):
            phase = OxygenPhase.LIQUID

        # Determine temperature
        if constraints.temp_c_max is not None:
            temp_k = constraints.temp_c_max + 273.15
        else:
            temp_k = self.DEFAULT_TEMPERATURE_K
            assumptions.append(
                f"temperature not specified; assumed ambient {temp_k:.2f} K"
            )
            logger.warning(
                "[BOUNDARY] O2 temperature not specified for %s; assuming %.2f K",
                constraints.material, temp_k,
            )

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
                ctx.boundary_rationale = self._append_assumptions(
                    result.rationale, assumptions
                )
                ctx.boundary_short_circuited = True

        except Exception as exc:
            logger.warning(f"[BOUNDARY] O2 check failed (continuing): {exc}")

        return ctx

    def _check_h2_boundaries(self, ctx: QueryContext) -> QueryContext:
        """Check H2 deterministic rules via mira.h2.engine."""
        try:
            from mira.h2.engine import evaluate_h2_compatibility
            from mira.h2.models import H2CompatibilityRequest, HydrogenPhase
            from core.models.answer import AnswerSeverity
        except ImportError:
            logger.info("[BOUNDARY] H2 engine not available — skipping")
            return ctx

        constraints = ctx.constraints
        query_lower = ctx.raw_query.lower()

        # Determine pressure (record the assumption if we have to fall back).
        pressure_psia = constraints.pressure_psi or self._extract_pressure(query_lower)
        assumptions: list[str] = []
        if pressure_psia is None:
            pressure_psia = self.DEFAULT_PRESSURE_PSIA
            assumptions.append(
                f"pressure not specified; assumed worst-case {pressure_psia:.0f} psia"
            )
            logger.warning(
                "[BOUNDARY] H2 pressure not specified for %s; assuming %.0f psia",
                constraints.material, pressure_psia,
            )

        # Determine phase
        phase = HydrogenPhase.GAS
        if any(kw in query_lower for kw in ("lh2", "liquid hydrogen", "cryogenic")):
            phase = HydrogenPhase.LIQUID

        # Determine temperature
        if constraints.temp_c_max is not None:
            temp_k = constraints.temp_c_max + 273.15
        else:
            temp_k = self.DEFAULT_TEMPERATURE_K
            assumptions.append(
                f"temperature not specified; assumed ambient {temp_k:.2f} K"
            )
            logger.warning(
                "[BOUNDARY] H2 temperature not specified for %s; assuming %.2f K",
                constraints.material, temp_k,
            )

        try:
            request = H2CompatibilityRequest(
                question=ctx.raw_query,
                material_key=constraints.material,
                pressure_psia=pressure_psia,
                temperature_k=temp_k,
                phase=phase,
            )
            result = evaluate_h2_compatibility(request)

            if result.classification == AnswerSeverity.PROHIBITED:
                logger.info(
                    f"[BOUNDARY] PROHIBITED: {constraints.material} "
                    f"in {phase.value} at {pressure_psia} psia"
                )
                ctx.boundary_verdict = Verdict.NO
                ctx.boundary_rationale = self._append_assumptions(
                    result.rationale, assumptions
                )
                ctx.boundary_short_circuited = True

        except Exception as exc:
            logger.warning(f"[BOUNDARY] H2 check failed (continuing): {exc}")

        return ctx

    @staticmethod
    def _extract_pressure(query_lower: str) -> float | None:
        """Fallback pressure extraction from raw query text."""
        match = re.search(r"(\d+(?:\.\d+)?)\s*psi[a]?", query_lower)
        return float(match.group(1)) if match else None
