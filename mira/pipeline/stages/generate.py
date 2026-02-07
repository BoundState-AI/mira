#!/usr/bin/env python3
"""
Stage 10: Generate — LLM answer generation.

Rule 6.1-6.5: LLM guardrails enforced.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)


class GenerateStage(PipelineStage):
    """Stage 10: Generate natural language answer using LLM."""

    def __init__(self, llm_provider: str = "ollama"):
        self._provider = llm_provider
        self._generator = None
        self._loaded = False

    def _get_generator(self):
        """Lazy-load LLM answer generator."""
        if not self._loaded:
            self._loaded = True
            try:
                from mira.MIRA_V2.src.llm_answer_generator import LLMAnswerGenerator
                self._generator = LLMAnswerGenerator(provider=self._provider)
                logger.info(f"[GENERATE] LLM generator loaded (provider={self._provider})")
            except Exception as exc:
                logger.warning(f"[GENERATE] LLM generator unavailable: {exc}")
        return self._generator

    @property
    def name(self) -> str:
        return "generate"

    def should_skip(self, ctx: QueryContext) -> bool:
        if ctx.boundary_short_circuited:
            return True
        if not ctx.has_sufficient_evidence:
            return True
        return ctx.pipeline_name not in ("compatibility",)

    def execute(self, ctx: QueryContext) -> QueryContext:
        generator = self._get_generator()
        if generator is None:
            ctx.llm_answer = "LLM answer generation unavailable."
            return ctx

        try:
            answer = generator.generate_answer(
                query=ctx.raw_query,
                mua_precedents=ctx.mua_precedents[:5],
                semantic_evidence=ctx.semantic_evidence,
                decisions=ctx.decisions,
                requirements=ctx.requirements,
            )
            ctx.llm_answer = answer
            logger.info(f"[GENERATE] Answer generated ({len(answer)} chars)")

        except Exception as exc:
            ctx.llm_answer = f"LLM generation error: {exc}"
            logger.warning(f"[GENERATE] Failed: {exc}")

        return ctx
