#!/usr/bin/env python3
"""
Module: Rag Engine
Purpose: Result of hybrid RAG query.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
import numpy as np
import re

from config_manager import get_config
from document_discovery_index import DocumentDiscoveryIndex
from smart_chunks_index import SmartChunksIndex
from post_chunking_engine import PostChunkingEngine
from promotion_manager import PromotionManager

__all__ = ["HybridRAGEngine", "QueryResult", "RetrievalStrategy"]

__safety_critical__ = False

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of hybrid RAG query."""
    answer: str
    chunks: List[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    strategy_used: str
    processing_time: float
    confidence: float
    source: str = "hybrid_rag"


class QueryClassifier:
    """Classify query intent to optimize retrieval strategy."""
    
    @staticmethod
    def classify(query: str) -> str:
        """Enhanced query classification with more categories.

        Returns one of:
        - 'lookup': Direct document/standard lookup
        - 'requirement': Requirements search (SHALL/MUST)
        - 'comparison': Cross-document comparison
        - 'count': Counting queries
        - 'enumeration': List all queries
        - 'hr_policy': HR/travel policy queries
        - 'exploration': General exploration
        """
        query_lower = query.lower()

        # Count queries (highest priority)
        if any(pattern in query_lower for pattern in [
            'how many', 'count', 'total number', 'number of'
        ]):
            return 'count'

        # List/enumeration queries
        if any(pattern in query_lower for pattern in [
            'list all', 'which documents', 'show me all', 'what documents'
        ]):
            return 'enumeration'

        # HR/Policy queries (specific domain)
        if 'policy' in query_lower and any(term in query_lower for term in [
            'travel', 'leave', 'timecard', 'telework', 'overtime', 'vacation'
        ]):
            return 'hr_policy'

        # Direct lookup patterns
        if any(pattern in query_lower for pattern in [
            'nasa-std', 'msfc-std', 'npr-', 'what does', 'show me',
            'find document', 'get standard', 'retrieve'
        ]):
            return 'lookup'

        # Requirements search
        if any(word in query_lower for word in [
            'shall', 'must', 'requirement', 'comply', 'mandatory', 'required'
        ]):
            return 'requirement'

        # Procedure/How-to queries
        if any(pattern in query_lower for pattern in [
            'how to', 'steps', 'procedure', 'process', 'workflow'
        ]):
            return 'procedure'

        # Comparison queries
        if any(word in query_lower for word in ['compare', 'difference', 'versus', 'vs', 'better']):
            return 'comparison'

        # Default to exploration
        return 'exploration'


class RetrievalStrategy:
    """Configurable retrieval strategy based on query type."""
    
    def __init__(self, query_type: str):
        self.query_type = query_type
        self.config = get_config()
        
        # Adjust parameters based on query type
        if query_type == 'lookup':
            self.k_docs = 3
            self.k_chunks = 5
            self.max_postchunk = 1
            self.use_cross_encoder = False
        elif query_type == 'count' or query_type == 'enumeration':
            # Don't use semantic search for count/list queries
            self.k_docs = 0
            self.k_chunks = 0
            self.max_postchunk = 0
            self.use_cross_encoder = False
        elif query_type == 'hr_policy':
            # Policy questions need more context
            self.k_docs = 8
            self.k_chunks = 10
            self.max_postchunk = 2
            self.use_cross_encoder = True
        elif query_type == 'procedure':
            # Procedural questions can be more focused
            self.k_docs = 5
            self.k_chunks = 8
            self.max_postchunk = 2
            self.use_cross_encoder = False
        elif query_type == 'requirement':
            self.k_docs = 10
            self.k_chunks = 15
            self.max_postchunk = 3
            self.use_cross_encoder = True
        elif query_type == 'comparison':
            self.k_docs = 8
            self.k_chunks = 12
            self.max_postchunk = 2
            self.use_cross_encoder = True
        else:  # exploration
            self.k_docs = self.config.retrieval.k_docs_discovery
            self.k_chunks = self.config.retrieval.k_chunks_final
            self.max_postchunk = self.config.retrieval.max_postchunk_docs_per_query
            self.use_cross_encoder = False


class HybridRAGEngine:
    """Orchestrates hybrid two-tier retrieval for 400K+ documents.
    
    Integrates document discovery, smart chunks (hot tier), and 
    on-demand post-chunking with intelligent query routing.
    
    Compliance: SWE-013, SWE-033
    """
    
    def __init__(
        self,
        discovery_index: DocumentDiscoveryIndex,
        smart_index: SmartChunksIndex,
        post_chunk_engine: PostChunkingEngine,
        promotion_manager: Optional[PromotionManager] = None
    ):
        """Initialize hybrid RAG engine.
        
        Args:
            discovery_index: Document-level search index
            smart_index: Hot tier chunk storage
            post_chunk_engine: On-demand chunking engine
            promotion_manager: Optional promotion system
        """
        self.discovery = discovery_index
        self.smart = smart_index
        self.post = post_chunk_engine
        self.promotion = promotion_manager
        
        self.config = get_config()
        self.classifier = QueryClassifier()
        
        # Concurrency control
        self.post_chunk_semaphore = Semaphore(
            self.config.performance.max_concurrent_postchunk
        )
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Optional cross-encoder
        self.cross_encoder = None
        
        # Statistics
        self.stats = {
            'queries_processed': 0,
            'hot_tier_hits': 0,
            'post_chunk_triggers': 0,
            'avg_response_time': 0.0
        }
    
    def set_cross_encoder(self, cross_encoder):
        """Set optional cross-encoder for reranking."""
        self.cross_encoder = cross_encoder
        logger.info("Cross-encoder configured for reranking")
    
    def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        top_k: Optional[int] = None
    ) -> QueryResult:
        """Execute hybrid search across all tiers.
        
        Args:
            query: User query
            user_id: Optional user identifier for tracking
            top_k: Override number of results
            
        Returns:
            QueryResult with ranked chunks and metadata
        """
        start_time = time.time()
        
        try:
            # Classify query
            query_type = self.classifier.classify(query)
            strategy = RetrievalStrategy(query_type)
            
            logger.debug(f"Query classified as '{query_type}'")
            
            # Generate query embedding
            query_embed = self._embed_query(query)
            
            # Phase 1: Try hot tier first for known documents
            hot_chunks = self._search_hot_tier(query_embed, strategy)
            
            # Early exit if high-confidence hot tier results
            if hot_chunks and self._should_early_exit(hot_chunks):
                return self._build_result(
                    chunks=hot_chunks[:strategy.k_chunks],
                    query=query,
                    strategy=f"{query_type}_hot_only",
                    start_time=start_time
                )
            
            # Phase 2: Document discovery
            doc_candidates = self.discovery.search(
                query_embed,
                k=strategy.k_docs
            )
            
            if not doc_candidates and not hot_chunks:
                return self._build_empty_result(query, query_type, start_time)
            
            # Phase 3: Selective post-chunking with budget
            post_chunked = self._selective_post_chunk(
                doc_candidates,
                query,
                query_embed,
                strategy,
                user_id
            )
            
            # Phase 4: Merge and rerank all chunks
            all_chunks = self._merge_and_rerank(
                hot_chunks,
                post_chunked,
                query_embed,
                strategy
            )
            
            # Phase 5: Record access for learning
            if self.promotion and all_chunks:
                self._record_access_patterns(all_chunks[:3], query, user_id)
            
            # Update statistics
            self._update_stats(start_time, hot_chunks, post_chunked)
            
            return self._build_result(
                chunks=all_chunks[:strategy.k_chunks],
                query=query,
                strategy=query_type,
                start_time=start_time
            )
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return self._build_error_result(query, str(e), start_time)
    
    def _embed_query(self, query: str) -> np.ndarray:
        """Generate query embedding."""
        # Use same embedder as post-chunking engine
        texts = [f"search_query: {query}"]
        embeddings = self.post.embedder.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False
        )
        return embeddings[0]
    
    def _search_hot_tier(
        self,
        query_embed: np.ndarray,
        strategy: RetrievalStrategy
    ) -> List[Dict[str, Any]]:
        """Search pre-chunked hot tier documents."""
        try:
            results = self.smart.search(query_embed, k=strategy.k_chunks * 2)
            
            chunks = []
            for chunk_entry, score in results:
                chunks.append({
                    'doc_id': chunk_entry.doc_id,
                    'chunk_id': chunk_entry.chunk_id,
                    'text': chunk_entry.text,
                    'score': float(score),
                    'tier': 'hot',
                    'metadata': chunk_entry.metadata
                })
            
            if chunks:
                self.stats['hot_tier_hits'] += 1
                logger.debug(f"Found {len(chunks)} chunks in hot tier")
            
            return chunks
            
        except Exception as e:
            logger.error(f"Hot tier search failed: {e}")
            return []
    
    def _should_early_exit(self, chunks: List[Dict[str, Any]]) -> bool:
        """Determine if hot tier results are sufficient."""
        if not chunks:
            return False
        
        # Check if top scores exceed threshold
        top_scores = [c['score'] for c in chunks[:3]]
        avg_top_score = sum(top_scores) / len(top_scores)
        
        return avg_top_score >= self.config.retrieval.early_exit_chunk_score
    
    def _selective_post_chunk(
        self,
        doc_candidates: List[Dict[str, Any]],
        query: str,
        query_embed: np.ndarray,
        strategy: RetrievalStrategy,
        user_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Selectively post-chunk documents with budget control."""
        chunks = []
        post_chunk_budget = strategy.max_postchunk
        
        # Sort candidates by score
        candidates = sorted(doc_candidates, key=lambda x: x.get('score', 0), reverse=True)
        
        # Process top candidates within budget
        futures = []
        with self.executor as executor:
            for doc in candidates[:post_chunk_budget * 2]:  # Consider more than budget
                if post_chunk_budget <= 0:
                    break
                
                # Skip if already in hot tier
                if self.smart.contains(doc['doc_id']):
                    continue
                
                # Skip very large files on first touch
                if doc.get('file_size_mb', 0) > self.config.limits.skip_if_mb_gt:
                    logger.debug(f"Skipping large file {doc['doc_id']} ({doc['file_size_mb']}MB)")
                    continue
                
                # Submit post-chunking task
                if self.post_chunk_semaphore.acquire(blocking=False):
                    future = executor.submit(
                        self._post_chunk_document,
                        doc,
                        query,
                        query_embed,
                        user_id
                    )
                    futures.append((future, doc['doc_id']))
                    post_chunk_budget -= 1
                    self.stats['post_chunk_triggers'] += 1
            
            # Collect results
            for future, doc_id in futures:
                try:
                    result = future.result(timeout=10)
                    if result:
                        chunks.extend(result)
                except Exception as e:
                    logger.error(f"Post-chunk failed for {doc_id}: {e}")
                finally:
                    self.post_chunk_semaphore.release()
        
        return chunks
    
    def _post_chunk_document(
        self,
        doc: Dict[str, Any],
        query: str,
        query_embed: np.ndarray,
        user_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Post-chunk a single document."""
        try:
            # Get content hash if available
            content_hash = doc.get('content_hash', '')
            
            # Generate cache key with content hash
            cache_key = f"{doc['doc_id']}_{content_hash[:8]}_{hashlib.md5(query.encode()).hexdigest()[:8]}"
            
            # Post-chunk the document
            chunked_doc = self.post.post_chunk_document(
                doc['doc_id'],
                doc['file_path'],
                query=query,
                metadata=None
            )
            
            if not chunked_doc:
                return []
            
            # Generate embeddings for chunks
            embeddings = self.post.generate_chunk_embeddings(chunked_doc.chunks)
            
            # Score chunks
            chunks = []
            for chunk_meta, embedding in zip(chunked_doc.chunks, embeddings):
                score = float(np.dot(query_embed, embedding))
                chunks.append({
                    'doc_id': doc['doc_id'],
                    'chunk_id': chunk_meta.chunk_id,
                    'text': chunk_meta.text,
                    'score': score,
                    'tier': 'cold',
                    'metadata': {
                        'chunk_type': chunk_meta.chunk_type,
                        'title': doc.get('title', ''),
                        'chunking_profile': chunked_doc.chunking_profile
                    }
                })
            
            # Sort by score and return top chunks
            chunks.sort(key=lambda x: x['score'], reverse=True)
            return chunks[:10]
            
        except Exception as e:
            logger.error(f"Error post-chunking {doc['doc_id']}: {e}")
            return []
    
    def _merge_and_rerank(
        self,
        hot_chunks: List[Dict[str, Any]],
        cold_chunks: List[Dict[str, Any]],
        query_embed: np.ndarray,
        strategy: RetrievalStrategy
    ) -> List[Dict[str, Any]]:
        """Merge and rerank chunks from all sources."""
        # Combine all chunks
        all_chunks = hot_chunks + cold_chunks
        
        if not all_chunks:
            return []
        
        # Remove duplicates (same doc_id + chunk_id)
        seen = set()
        unique_chunks = []
        for chunk in all_chunks:
            key = (chunk['doc_id'], chunk['chunk_id'])
            if key not in seen:
                seen.add(key)
                unique_chunks.append(chunk)
        
        # Sort by initial score
        unique_chunks.sort(key=lambda x: x['score'], reverse=True)
        
        # Apply cross-encoder if available and requested
        if strategy.use_cross_encoder and self.cross_encoder and len(unique_chunks) > 0:
            top_n = min(50, len(unique_chunks))
            top_chunks = unique_chunks[:top_n]
            
            try:
                # Rerank with cross-encoder
                reranked = self._cross_encoder_rerank(query, top_chunks)
                unique_chunks = reranked + unique_chunks[top_n:]
            except Exception as e:
                logger.error(f"Cross-encoder reranking failed: {e}")
        
        return unique_chunks
    
    def _cross_encoder_rerank(self, query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply cross-encoder reranking."""
        pairs = [(query, chunk['text']) for chunk in chunks]
        scores = self.cross_encoder.predict(pairs)
        
        for chunk, score in zip(chunks, scores):
            chunk['cross_encoder_score'] = float(score)
            chunk['final_score'] = 0.7 * chunk['score'] + 0.3 * float(score)
        
        chunks.sort(key=lambda x: x['final_score'], reverse=True)
        return chunks
    
    def _record_access_patterns(
        self,
        top_chunks: List[Dict[str, Any]],
        query: str,
        user_id: Optional[str]
    ):
        """Record access for promotion decisions."""
        if not self.promotion:
            return
        
        for chunk in top_chunks:
            try:
                self.promotion.record_access(
                    chunk['doc_id'],
                    user_id,
                    query
                )
            except Exception as e:
                logger.error(f"Failed to record access: {e}")
    
    def _update_stats(self, start_time: float, hot_chunks: List, cold_chunks: List):
        """Update engine statistics."""
        response_time = time.time() - start_time
        self.stats['queries_processed'] += 1
        
        # Update average response time
        prev_avg = self.stats['avg_response_time']
        n = self.stats['queries_processed']
        self.stats['avg_response_time'] = (prev_avg * (n - 1) + response_time) / n
    
    def _build_result(
        self,
        chunks: List[Dict[str, Any]],
        query: str,
        strategy: str,
        start_time: float
    ) -> QueryResult:
        """Build final query result."""
        processing_time = time.time() - start_time
        
        # Extract unique sources
        sources = []
        seen_docs = set()
        for chunk in chunks:
            doc_id = chunk['doc_id']
            if doc_id not in seen_docs:
                seen_docs.add(doc_id)
                sources.append({
                    'doc_id': doc_id,
                    'title': chunk['metadata'].get('title', doc_id),
                    'tier': chunk['tier']
                })
        
        # Calculate confidence
        confidence = 0.0
        if chunks:
            top_scores = [c['score'] for c in chunks[:3]]
            confidence = sum(top_scores) / len(top_scores)
        
        return QueryResult(
            answer="[Generated answer would go here]",  # Placeholder for LLM integration
            chunks=chunks,
            sources=sources,
            strategy_used=strategy,
            processing_time=round(processing_time, 2),
            confidence=float(confidence)
        )
    
    def _build_empty_result(self, query: str, strategy: str, start_time: float) -> QueryResult:
        """Build empty result when no matches found."""
        return QueryResult(
            answer="No relevant documents found for your query.",
            chunks=[],
            sources=[],
            strategy_used=strategy,
            processing_time=round(time.time() - start_time, 2),
            confidence=0.0
        )
    
    def _build_error_result(self, query: str, error: str, start_time: float) -> QueryResult:
        """Build error result."""
        return QueryResult(
            answer=f"An error occurred while processing your query: {error}",
            chunks=[],
            sources=[],
            strategy_used="error",
            processing_time=round(time.time() - start_time, 2),
            confidence=0.0
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            **self.stats,
            'smart_index': self.smart.get_statistics(),
            'post_chunk': self.post.get_statistics()
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize components
    from document_discovery_index import DocumentDiscoveryIndex
    from smart_chunks_index import SmartChunksIndex
    from post_chunking_engine import PostChunkingEngine
    
    discovery = DocumentDiscoveryIndex("discovery_index")
    smart = SmartChunksIndex("smart_chunks", dim=768)
    post = PostChunkingEngine("post_chunk_cache")
    
    # Create engine
    engine = HybridRAGEngine(discovery, smart, post)
    
    # Test query
    result = engine.search("What are the flammability requirements for NASA spacecraft?")
    print(f"Found {len(result.chunks)} chunks in {result.processing_time}s")
    print(f"Strategy: {result.strategy_used}, Confidence: {result.confidence:.2f}")