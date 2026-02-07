#!/usr/bin/env python3
"""
Stage 7: Semantic Search — FAISS-based semantic evidence retrieval.

Rule 1.3: Semantic evidence ENHANCES but never REPLACES structured evidence.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)


class SemanticSearchStage(PipelineStage):
    """Stage 7: FAISS semantic evidence retrieval + content fetching + scoring."""

    def __init__(self, db_url: Optional[str] = None, index_dir: Optional[str] = None):
        self._db_url = db_url
        self._index_dir = index_dir
        self._retriever = None
        self._loaded = False

    def _get_retriever(self):
        """Lazy-load SemanticEvidenceRetriever."""
        if not self._loaded:
            self._loaded = True
            try:
                from mira.MIRA_V2.src.semantic_evidence import SemanticEvidenceRetriever
                from mira.MIRA_V2.src.relevance_scorer import RelevanceBand

                index_dir = self._index_dir or os.getenv("MIRA_INDEX_DIR")
                if not index_dir:
                    base = os.path.dirname(os.path.abspath(__file__))
                    index_dir = os.path.join(base, "..", "..", "MIRA_V2", "data", "faiss_indexes")

                self._retriever = SemanticEvidenceRetriever(
                    db_url=self._db_url or os.environ.get("MIRA_DB_URL"),
                    index_dir=index_dir,
                )
                self._RelevanceBand = RelevanceBand
                logger.info("[SEMANTIC] Retriever initialized")
            except Exception as exc:
                logger.warning(f"[SEMANTIC] Retriever unavailable: {exc}")
        return self._retriever

    @property
    def name(self) -> str:
        return "semantic_search"

    def should_skip(self, ctx: QueryContext) -> bool:
        if ctx.boundary_short_circuited:
            return True
        return ctx.pipeline_name not in ("compatibility", "general")

    def execute(self, ctx: QueryContext) -> QueryContext:
        retriever = self._get_retriever()
        if retriever is None:
            logger.warning("[SEMANTIC] No retriever — skipping")
            return ctx

        try:
            evidence = retriever.get_evidence(
                query=ctx.raw_query,
                top_k_per_index=10,
                min_relevance=self._RelevanceBand.LOW,
                fetch_content=True,
            )

            ctx.semantic_evidence = {
                "total_results": evidence.total_results,
                "stats": evidence.stats,
                "bok_standards": evidence.bok_standards,
                "mua_precedents": evidence.mua_precedents,
                "maptis_data": evidence.maptis_data,
                "top_results": evidence.top_results[:10],
            }

            logger.info(
                f"[SEMANTIC] {evidence.total_results} results "
                f"(high={evidence.stats.get('high_confidence', 0)}, "
                f"medium={evidence.stats.get('medium_confidence', 0)})"
            )

        except Exception as exc:
            logger.warning(f"[SEMANTIC] Search failed: {exc}")

        return ctx
