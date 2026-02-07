#!/usr/bin/env python3
"""
Module: Reranker
Purpose: import time

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

import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

import numpy as np

# Try to import sentence-transformers for cross-encoder
try:
    from sentence_transformers import CrossEncoder
    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CrossEncoder = None
    CROSS_ENCODER_AVAILABLE = False

# Import BoundState components
from boundstate.config import CONFIG

logger = logging.getLogger(__name__)

@dataclass
class RerankingResult:
    """Result from cross-encoder reranking."""
    chunks: List[Dict[str, Any]]
    original_scores: List[float]
    reranked_scores: List[float]
    processing_time_ms: float
    method_used: str  # 'cross_encoder', 'cosine_fallback', 'timeout_fallback'
    timeout_occurred: bool = False

@dataclass
class RerankingStats:
    """Statistics for reranking operations."""
    total_requests: int = 0
    cross_encoder_successes: int = 0
    fallback_uses: int = 0
    timeout_count: int = 0
    average_processing_time_ms: float = 0.0
    average_score_improvement: float = 0.0

class CrossEncoderReranker:
    """
    Cross-encoder reranker for improving chunk relevance scoring.

    Uses BERT-style cross-encoder to provide more accurate relevance scores
    compared to simple cosine similarity between embeddings.
    """

    def __init__(self, model_name: str = None, config: Optional[Dict] = None):
        self.config = config or {}

        # Model configuration
        self.model_name = model_name or self.config.get(
            'cross_encoder_model',
            'cross-encoder/ms-marco-MiniLM-L-6-v2'
        )

        # Performance configuration
        self.max_batch_size = self.config.get('max_batch_size', 32)
        self.timeout_seconds = self.config.get('timeout_seconds', 0.3)  # 300ms as recommended by Fran
        self.max_candidates = self.config.get('max_candidates', 50)  # Top-50 only
        self.score_threshold = self.config.get('score_threshold', 0.1)

        # Threading
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='reranker')

        # Model initialization
        self.model = None
        self.model_loaded = False
        self._init_model()

        # Statistics
        self.stats = RerankingStats()

        logger.info(f"Initialized CrossEncoderReranker with model: {self.model_name}")

    def _init_model(self):
        """Initialize the cross-encoder model with error handling."""
        try:
            if not CROSS_ENCODER_AVAILABLE:
                logger.warning("sentence-transformers not available, using fallback scoring")
                return

            # Load model in background to avoid blocking initialization
            def load_model():
                try:
                    self.model = CrossEncoder(
                        self.model_name,
                        max_length=512,  # Reasonable max length for performance
                        device='cpu'  # Start with CPU, can be moved to GPU if available
                    )
                    self.model_loaded = True
                    logger.info(f"Cross-encoder model loaded: {self.model_name}")
                except Exception as e:
                    logger.error(f"Failed to load cross-encoder model: {e}")
                    self.model_loaded = False

            # Load model in background
            self.executor.submit(load_model)

        except Exception as e:
            logger.error(f"Cross-encoder initialization failed: {e}")
            self.model_loaded = False

    def rerank(self, query: str, chunks: List[Dict[str, Any]],
              top_k: Optional[int] = None) -> RerankingResult:
        """
        Rerank chunks using cross-encoder for improved relevance.

        Args:
            query: Query string
            chunks: List of chunk dictionaries with 'text' and 'score' fields
            top_k: Number of top results to return (defaults to len(chunks))

        Returns:
            RerankingResult with reranked chunks and metadata
        """
        start_time = time.time()

        try:
            with self.lock:
                self.stats.total_requests += 1

            if not chunks:
                return RerankingResult(
                    chunks=[],
                    original_scores=[],
                    reranked_scores=[],
                    processing_time_ms=0.0,
                    method_used='empty_input'
                )

            top_k = top_k or len(chunks)
            original_scores = [self._extract_score(chunk) for chunk in chunks]

            # Limit to max candidates for performance
            limited_chunks = chunks[:self.max_candidates]
            limited_scores = original_scores[:self.max_candidates]

            # Try cross-encoder reranking with timeout
            if self.model_loaded and self.model is not None:
                try:
                    reranked_chunks, reranked_scores = self._rerank_with_cross_encoder(
                        query, limited_chunks, limited_scores
                    )
                    method_used = 'cross_encoder'

                    with self.lock:
                        self.stats.cross_encoder_successes += 1

                except TimeoutError:
                    logger.warning("Cross-encoder reranking timed out, falling back to cosine")
                    reranked_chunks, reranked_scores = self._fallback_ranking(limited_chunks, limited_scores)
                    method_used = 'timeout_fallback'

                    with self.lock:
                        self.stats.timeout_count += 1

                except Exception as e:
                    logger.error(f"Cross-encoder reranking failed: {e}")
                    reranked_chunks, reranked_scores = self._fallback_ranking(limited_chunks, limited_scores)
                    method_used = 'error_fallback'

                    with self.lock:
                        self.stats.fallback_uses += 1
            else:
                # Model not available, use fallback
                reranked_chunks, reranked_scores = self._fallback_ranking(limited_chunks, limited_scores)
                method_used = 'cosine_fallback'

                with self.lock:
                    self.stats.fallback_uses += 1

            # Apply top-k filtering
            if top_k < len(reranked_chunks):
                reranked_chunks = reranked_chunks[:top_k]
                reranked_scores = reranked_scores[:top_k]

            processing_time_ms = (time.time() - start_time) * 1000

            # Update statistics
            with self.lock:
                self._update_stats(processing_time_ms, original_scores, reranked_scores)

            result = RerankingResult(
                chunks=reranked_chunks,
                original_scores=limited_scores,
                reranked_scores=reranked_scores,
                processing_time_ms=processing_time_ms,
                method_used=method_used,
                timeout_occurred=(method_used == 'timeout_fallback')
            )

            logger.debug(f"Reranked {len(chunks)} chunks in {processing_time_ms:.1f}ms using {method_used}")
            return result

        except Exception as e:
            logger.error(f"Reranking failed completely: {e}")
            processing_time_ms = (time.time() - start_time) * 1000

            return RerankingResult(
                chunks=chunks[:top_k],
                original_scores=original_scores[:top_k],
                reranked_scores=original_scores[:top_k],
                processing_time_ms=processing_time_ms,
                method_used='error_passthrough'
            )

    def _rerank_with_cross_encoder(self, query: str, chunks: List[Dict[str, Any]],
                                  original_scores: List[float]) -> Tuple[List[Dict], List[float]]:
        """Perform cross-encoder reranking with timeout protection."""

        # Prepare query-chunk pairs
        pairs = []
        for chunk in chunks:
            chunk_text = self._extract_text(chunk)
            pairs.append([query, chunk_text])

        # Submit to executor with timeout
        future = self.executor.submit(self._predict_scores, pairs)

        try:
            cross_encoder_scores = future.result(timeout=self.timeout_seconds)
        except TimeoutError:
            future.cancel()
            raise TimeoutError("Cross-encoder prediction timed out")

        # Combine with original scores (weighted combination)
        combined_scores = []
        for ce_score, orig_score in zip(cross_encoder_scores, original_scores):
            # Weight cross-encoder more heavily but include original score
            combined_score = 0.8 * ce_score + 0.2 * orig_score
            combined_scores.append(combined_score)

        # Sort by combined scores
        sorted_indices = np.argsort(combined_scores)[::-1]

        reranked_chunks = [chunks[i] for i in sorted_indices]
        reranked_scores = [combined_scores[i] for i in sorted_indices]

        # Update chunk scores
        for chunk, score in zip(reranked_chunks, reranked_scores):
            chunk['rerank_score'] = score

        return reranked_chunks, reranked_scores

    def _predict_scores(self, pairs: List[List[str]]) -> List[float]:
        """Predict cross-encoder scores for query-chunk pairs."""
        try:
            # Process in batches for memory efficiency
            all_scores = []

            for i in range(0, len(pairs), self.max_batch_size):
                batch_pairs = pairs[i:i + self.max_batch_size]
                batch_scores = self.model.predict(batch_pairs)
                all_scores.extend(batch_scores.tolist())

            return all_scores

        except Exception as e:
            logger.error(f"Cross-encoder prediction failed: {e}")
            raise

    def _fallback_ranking(self, chunks: List[Dict[str, Any]],
                         original_scores: List[float]) -> Tuple[List[Dict], List[float]]:
        """Fallback ranking using original scores."""
        # Sort by original scores
        sorted_indices = np.argsort(original_scores)[::-1]

        reranked_chunks = [chunks[i] for i in sorted_indices]
        reranked_scores = [original_scores[i] for i in sorted_indices]

        return reranked_chunks, reranked_scores

    def _extract_score(self, chunk: Dict[str, Any]) -> float:
        """Extract score from chunk dictionary."""
        # Try multiple possible score fields
        for field in ['score', 'rerank_score', 'similarity', 'relevance']:
            if field in chunk:
                try:
                    return float(chunk[field])
                except (ValueError, TypeError):
                    continue

        return 0.0

    def _extract_text(self, chunk: Dict[str, Any]) -> str:
        """Extract text content from chunk dictionary."""
        # Try multiple possible text fields
        for field in ['text', 'content', 'chunk_text', 'embed_text']:
            if field in chunk:
                text = chunk[field]
                if isinstance(text, str) and text.strip():
                    return text.strip()

        return ""

    def _update_stats(self, processing_time_ms: float, original_scores: List[float],
                     reranked_scores: List[float]):
        """Update reranking statistics."""
        try:
            # Update average processing time
            total_time = self.stats.average_processing_time_ms * (self.stats.total_requests - 1)
            self.stats.average_processing_time_ms = (total_time + processing_time_ms) / self.stats.total_requests

            # Calculate score improvement (if we have both original and reranked scores)
            if original_scores and reranked_scores and len(original_scores) == len(reranked_scores):
                # Compare top-1 scores as a simple improvement metric
                orig_top = max(original_scores) if original_scores else 0
                rerank_top = max(reranked_scores) if reranked_scores else 0
                improvement = rerank_top - orig_top

                # Update average improvement
                total_improvement = self.stats.average_score_improvement * (self.stats.total_requests - 1)
                self.stats.average_score_improvement = (total_improvement + improvement) / self.stats.total_requests

        except Exception as e:
            logger.debug(f"Stats update failed: {e}")

    def batch_rerank(self, query_chunk_pairs: List[Tuple[str, List[Dict[str, Any]]]],
                    top_k: Optional[int] = None) -> List[RerankingResult]:
        """
        Batch rerank multiple queries for efficiency.

        Args:
            query_chunk_pairs: List of (query, chunks) tuples
            top_k: Number of top results per query

        Returns:
            List of RerankingResult objects
        """
        results = []

        for query, chunks in query_chunk_pairs:
            result = self.rerank(query, chunks, top_k)
            results.append(result)

        return results

    def get_statistics(self) -> RerankingStats:
        """Get current reranking statistics."""
        with self.lock:
            return RerankingStats(
                total_requests=self.stats.total_requests,
                cross_encoder_successes=self.stats.cross_encoder_successes,
                fallback_uses=self.stats.fallback_uses,
                timeout_count=self.stats.timeout_count,
                average_processing_time_ms=round(self.stats.average_processing_time_ms, 2),
                average_score_improvement=round(self.stats.average_score_improvement, 4)
            )

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        return {
            'model_name': self.model_name,
            'model_loaded': self.model_loaded,
            'cross_encoder_available': CROSS_ENCODER_AVAILABLE,
            'config': {
                'max_batch_size': self.max_batch_size,
                'timeout_seconds': self.timeout_seconds,
                'max_candidates': self.max_candidates,
                'score_threshold': self.score_threshold
            }
        }

    def is_available(self) -> bool:
        """Check if cross-encoder reranking is available."""
        return CROSS_ENCODER_AVAILABLE and self.model_loaded

    def close(self):
        """Clean up resources."""
        try:
            self.executor.shutdown(wait=True, timeout=5.0)
            logger.info("CrossEncoderReranker closed")
        except Exception as e:
            logger.error(f"Error closing reranker: {e}")

class EnhancedRetriever:
    """
    Enhanced retriever that integrates cross-encoder reranking.

    This can be used to extend existing BoundState retriever classes.
    """

    def __init__(self, base_retriever, reranker_config: Optional[Dict] = None):
        """
        Args:
            base_retriever: Existing BoundState retriever instance
            reranker_config: Configuration for cross-encoder reranker
        """
        self.base_retriever = base_retriever
        self.reranker = CrossEncoderReranker(config=reranker_config)

        # Configuration
        self.enable_reranking = reranker_config.get('enable_reranking', True) if reranker_config else True
        self.rerank_threshold = reranker_config.get('rerank_threshold', 5) if reranker_config else 5

        logger.info("Initialized EnhancedRetriever with cross-encoder reranking")

    def search(self, query: str, max_results: int = 12, enable_reranking: Optional[bool] = None) -> List[Dict[str, Any]]:
        """
        Enhanced search with cross-encoder reranking.

        Args:
            query: Search query
            max_results: Maximum number of results to return
            enable_reranking: Override global reranking setting

        Returns:
            List of ranked results
        """
        try:
            # Get base results from original retriever
            base_results = self.base_retriever.search(query, max_results * 2)  # Get more for reranking

            if not base_results:
                return []

            # Determine if we should rerank
            should_rerank = (
                (enable_reranking if enable_reranking is not None else self.enable_reranking) and
                len(base_results) >= self.rerank_threshold and
                self.reranker.is_available()
            )

            if should_rerank:
                # Apply cross-encoder reranking
                rerank_result = self.reranker.rerank(query, base_results, max_results)

                # Add reranking metadata to results
                for chunk in rerank_result.chunks:
                    chunk['reranking_method'] = rerank_result.method_used
                    chunk['reranking_time_ms'] = rerank_result.processing_time_ms

                logger.debug(f"Reranked {len(base_results)} results using {rerank_result.method_used}")
                return rerank_result.chunks
            else:
                # Return original results without reranking
                limited_results = base_results[:max_results]

                for chunk in limited_results:
                    chunk['reranking_method'] = 'disabled'
                    chunk['reranking_time_ms'] = 0

                return limited_results

        except Exception as e:
            logger.error(f"Enhanced search failed: {e}")
            # Fallback to base retriever
            return self.base_retriever.search(query, max_results)

    def get_reranking_statistics(self) -> Dict[str, Any]:
        """Get reranking performance statistics."""
        stats = self.reranker.get_statistics()
        model_info = self.reranker.get_model_info()

        return {
            'statistics': stats,
            'model_info': model_info,
            'configuration': {
                'enable_reranking': self.enable_reranking,
                'rerank_threshold': self.rerank_threshold
            }
        }

def enhance_retriever_with_reranking(retriever_instance, config: Optional[Dict] = None):
    """
    Convenience function to enhance any existing retriever with cross-encoder reranking.

    Args:
        retriever_instance: Existing retriever instance
        config: Optional reranker configuration

    Returns:
        EnhancedRetriever instance
    """
    return EnhancedRetriever(retriever_instance, config)