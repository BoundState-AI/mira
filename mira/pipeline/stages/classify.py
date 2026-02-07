#!/usr/bin/env python3
"""
Stage 2: Classify — Score query intent using heuristic patterns.

Populates ctx.intent_scores for the Router (Stage 3) to consume.
Does NOT set ctx.intent directly — that's the Router's job.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)


class ClassifyStage(PipelineStage):
    """
    Stage 2: Run the IntentClassifier and store scores in context.

    This stage is deliberately thin — it calls the existing
    IntentClassifier and stores scores. The Router stage (Stage 3)
    applies the ironclad routing rules from RULES.md §3.
    """

    def __init__(self):
        self._classifier = None

    def _get_classifier(self):
        """Lazy-load the intent classifier."""
        if self._classifier is None:
            try:
                from mira.nlp.intent_classifier import IntentClassifier
                self._classifier = IntentClassifier()
                logger.info("[CLASSIFY] IntentClassifier loaded")
            except ImportError:
                logger.warning("[CLASSIFY] IntentClassifier not available")
        return self._classifier

    @property
    def name(self) -> str:
        return "classify"

    def execute(self, ctx: QueryContext) -> QueryContext:
        classifier = self._get_classifier()

        if classifier is None:
            # No classifier available — scores stay empty.
            # Router will fall through to binary signal check.
            logger.warning("[CLASSIFY] No classifier — relying on binary signals")
            return ctx

        result = classifier.classify(ctx.raw_query)
        ctx.intent_scores = dict(result.scores)
        ctx.intent_evidence = list(result.evidence)

        best_intent, best_score = result.best()
        logger.info(
            f"[CLASSIFY] best='{best_intent}' ({best_score:.2f}), "
            f"scores={ctx.intent_scores}"
        )

        return ctx
