#!/usr/bin/env python3
"""
Module: Query Pipeline
Purpose: Orchestrator that runs an ordered list of PipelineStages.

Logs timing per stage. Catches and records errors without crashing.
Returns the final QueryContext with all accumulated state.

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
import time
from typing import List

from .context import QueryContext, StageResult
from .stage import PipelineStage

logger = logging.getLogger(__name__)

# Rule 4.5: timing thresholds
WARN_THRESHOLD_MS = 5000
ERROR_THRESHOLD_MS = 15000


class QueryPipeline:
    """
    Orchestrates an ordered list of pipeline stages.

    Usage:
        pipeline = QueryPipeline([
            ParseStage(),
            ClassifyStage(),
            RouterStage(),
            ...
        ])
        ctx = pipeline.run("Is aluminum 6061 compatible with GOX at 200 psi?")
        response = ctx.to_response()
    """

    def __init__(self, stages: List[PipelineStage]):
        self.stages = stages
        stage_names = [s.name for s in stages]
        logger.info(f"[PIPELINE] Initialized with {len(stages)} stages: {stage_names}")

    def run(self, raw_query: str) -> QueryContext:
        """
        Execute all stages in order against a fresh QueryContext.

        Args:
            raw_query: The user's natural language query.

        Returns:
            QueryContext with all accumulated state from all stages.
        """
        ctx = QueryContext(raw_query=raw_query)

        logger.info(f"[PIPELINE] ═══ START: \"{raw_query[:80]}\" ═══")
        pipeline_start = time.time()

        for stage in self.stages:
            # Check skip condition
            if stage.should_skip(ctx):
                logger.info(f"[PIPELINE] ── {stage.name}: SKIPPED")
                ctx.stage_results.append(StageResult(
                    stage_name=stage.name,
                    duration_ms=0.0,
                    skipped=True,
                ))
                continue

            # Execute stage with timing
            stage_start = time.time()
            try:
                ctx = stage.execute(ctx)
                duration_ms = (time.time() - stage_start) * 1000

                # Rule 4.5: log timing warnings
                if duration_ms > ERROR_THRESHOLD_MS:
                    logger.error(
                        f"[PIPELINE] ── {stage.name}: {duration_ms:.0f}ms (SLOW!)"
                    )
                elif duration_ms > WARN_THRESHOLD_MS:
                    logger.warning(
                        f"[PIPELINE] ── {stage.name}: {duration_ms:.0f}ms (slow)"
                    )
                else:
                    logger.info(
                        f"[PIPELINE] ── {stage.name}: {duration_ms:.0f}ms"
                    )

                ctx.stage_results.append(StageResult(
                    stage_name=stage.name,
                    duration_ms=round(duration_ms, 1),
                ))

            except Exception as exc:
                duration_ms = (time.time() - stage_start) * 1000
                error_msg = f"{stage.name} failed: {exc}"
                logger.error(f"[PIPELINE] ── {stage.name}: ERROR ({duration_ms:.0f}ms) — {exc}")

                ctx.errors.append(error_msg)
                ctx.stage_results.append(StageResult(
                    stage_name=stage.name,
                    duration_ms=round(duration_ms, 1),
                    error=str(exc),
                ))

                # If boundary check short-circuited, stop pipeline
                if ctx.boundary_short_circuited:
                    break

        total_ms = (time.time() - pipeline_start) * 1000
        logger.info(
            f"[PIPELINE] ═══ DONE: {total_ms:.0f}ms total, "
            f"{len(ctx.stage_results)} stages, "
            f"{len(ctx.errors)} errors ═══"
        )

        return ctx
