#!/usr/bin/env python3
"""
Module: Semantic Evidence
Purpose: Semantic Evidence Module for MIRA V2

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

from .semantic_search import UnifiedSemanticSearch, SearchResult
from .content_fetcher import ContentFetcher
from .relevance_scorer import (
    classify_relevance,
    RelevanceBand,
    ScoredResult,
    group_by_relevance,
    filter_by_relevance,
    apply_safety_boost
)
from .answer_authority import (
    calculate_answer_authority,
    apply_authority_boost
)

logger = logging.getLogger(__name__)


@dataclass
class SemanticEvidence:
    """
    Complete semantic evidence package for query engine.

    Includes:
    - Search results with scores
    - Full content from database
    - Relevance classifications
    - Grouped by source and confidence
    """
    query: str
    total_results: int

    # Results by source index
    bok_standards: Dict[str, List[ScoredResult]]  # {high: [], medium: [], low: []}
    mua_precedents: Dict[str, List[ScoredResult]]
    maptis_data: Dict[str, List[ScoredResult]]

    # Overall top results
    top_results: List[ScoredResult]

    # Statistics
    stats: Dict

    def to_dict(self) -> Dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)

    def get_high_confidence_only(self) -> List[ScoredResult]:
        """Get only HIGH confidence results across all sources."""
        high_results = []
        high_results.extend(self.bok_standards.get('high', []))
        high_results.extend(self.mua_precedents.get('high', []))
        high_results.extend(self.maptis_data.get('high', []))

        # Sort by score descending
        high_results.sort(key=lambda x: x.score, reverse=True)
        return high_results


class SemanticEvidenceRetriever:
    """
    High-level semantic evidence retrieval for MIRA V2.

    Orchestrates:
    1. Vector search (FAISS)
    2. Content fetching (PostgreSQL)
    3. Relevance scoring (confidence bands)
    """

    def __init__(
        self,
        index_dir: Optional[str] = None,
        db_url: Optional[str] = None
    ):
        """
        Initialize semantic evidence retriever.

        Args:
            index_dir: FAISS index directory
            db_url: Database connection URL
        """
        # Initialize components
        self.semantic_search = UnifiedSemanticSearch(index_dir=index_dir)
        self.content_fetcher = ContentFetcher(db_url=db_url)

        # Load everything
        logger.info("Loading semantic search components...")
        self.semantic_search.load_encoder()
        self.semantic_search.load_all_indexes()
        logger.info("Semantic evidence retriever ready")

    def get_evidence(
        self,
        query: str,
        top_k_per_index: int = 10,
        min_relevance: RelevanceBand = RelevanceBand.LOW,
        fetch_content: bool = True,
        metadata_filters: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> SemanticEvidence:
        """
        Get comprehensive semantic evidence for a query.

        Args:
            query: Natural language query
            top_k_per_index: Number of results to retrieve per index
            min_relevance: Minimum relevance threshold
            fetch_content: Whether to fetch full content from DB
            metadata_filters: Optional metadata filters (e.g., material filtering)

        Returns:
            SemanticEvidence package
        """
        logger.info(f"Getting semantic evidence for: {query}")
        if metadata_filters:
            logger.info(f"  Applying metadata filters: {metadata_filters}")

        # 1. Vector search across all indexes with material filtering
        raw_results = self.semantic_search.search_all(
            query,
            top_k_per_index=top_k_per_index,
            metadata_filters=metadata_filters
        )

        # 2. Classify and score results
        scored_results = []
        for result in raw_results.merged_results:
            relevance = classify_relevance(result.score)

            scored = ScoredResult(
                doc_id=result.doc_id,
                score=result.score,
                relevance=relevance,
                source_index=result.source_index,
                rank=result.rank,
                metadata=result.metadata
            )

            scored_results.append(scored)

        # 3. Filter by minimum relevance
        filtered_results = filter_by_relevance(scored_results, min_relevance)

        logger.info(
            f"Semantic search: {len(scored_results)} total, "
            f"{len(filtered_results)} above {min_relevance.value} threshold"
        )

        # 4. Fetch content if requested
        if fetch_content:
            self._fetch_content_for_results(filtered_results)

            # 4a. Apply safety-aware boosting after content is fetched
            for result in filtered_results:
                if result.content:
                    # Get text content for boosting
                    content_text = result.content.get("text", "") or result.content.get("content", "")

                    # Apply safety boost (Phase 1)
                    safety_boosted = apply_safety_boost(
                        result.score,
                        content_text,
                        result.metadata
                    )

                    # Apply answer authority boost (Phase 2)
                    # This measures the document's ability to definitively answer the query
                    authority = calculate_answer_authority(
                        content=content_text,
                        query=query,
                        metadata=result.metadata
                    )
                    final_score = apply_authority_boost(safety_boosted, authority)

                    # Update score and re-classify if boost was significant
                    if final_score > result.score:
                        old_score = result.score
                        result.score = final_score
                        result.relevance = classify_relevance(final_score)
                        logger.debug(
                            f"Boost applied to {result.doc_id}: "
                            f"{old_score:.3f} -> {final_score:.3f} "
                            f"(authority={authority.authority_score:.2f}, "
                            f"relevance={result.relevance.value})"
                        )

        # 5. Group by source and relevance
        bok_results = [r for r in filtered_results if r.source_index == "bok"]
        mua_results = [r for r in filtered_results if r.source_index == "mua"]
        maptis_results = [r for r in filtered_results if r.source_index == "maptis"]

        # 6. Build evidence package
        evidence = SemanticEvidence(
            query=query,
            total_results=len(filtered_results),
            bok_standards=self._group_by_confidence(bok_results),
            mua_precedents=self._group_by_confidence(mua_results),
            maptis_data=self._group_by_confidence(maptis_results),
            top_results=sorted(filtered_results, key=lambda x: x.score, reverse=True)[:10],
            stats={
                'total_searched': len(scored_results),
                'passed_filter': len(filtered_results),
                'bok_count': len(bok_results),
                'mua_count': len(mua_results),
                'maptis_count': len(maptis_results),
                'high_confidence': len([r for r in filtered_results if r.relevance == RelevanceBand.HIGH]),
                'medium_confidence': len([r for r in filtered_results if r.relevance == RelevanceBand.MEDIUM]),
                'low_confidence': len([r for r in filtered_results if r.relevance == RelevanceBand.LOW])
            }
        )

        return evidence

    def _fetch_content_for_results(self, results: List[ScoredResult]):
        """Fetch database content for all results."""
        for result in results:
            try:
                content = self.content_fetcher.fetch_content(
                    result.source_index,
                    result.doc_id
                )
                result.content = content

            except Exception as e:
                logger.warning(
                    f"Failed to fetch content for {result.source_index}:{result.doc_id}: {e}"
                )
                result.content = None

    def _group_by_confidence(self, results: List[ScoredResult]) -> Dict[str, List[ScoredResult]]:
        """Group results by confidence band."""
        grouped = group_by_relevance(results)

        return {
            'high': grouped[RelevanceBand.HIGH],
            'medium': grouped[RelevanceBand.MEDIUM],
            'low': grouped[RelevanceBand.LOW]
        }

    def close(self):
        """Clean up resources."""
        self.content_fetcher.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Convenience function for quick queries
def get_semantic_evidence(
    query: str,
    top_k: int = 10,
    min_relevance: RelevanceBand = RelevanceBand.LOW
) -> SemanticEvidence:
    """
    Quick semantic evidence retrieval.

    Args:
        query: Natural language query
        top_k: Results per index
        min_relevance: Minimum relevance threshold

    Returns:
        SemanticEvidence package
    """
    with SemanticEvidenceRetriever() as retriever:
        return retriever.get_evidence(query, top_k, min_relevance)
