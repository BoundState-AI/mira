#!/usr/bin/env python3
"""
Module: Hybrid
Purpose: [Automatically migrated - needs manual review]

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

import re
import uuid
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib

# Import existing BoundState chunkers
from boundstate.hierarchical_chunker import HierarchicalChunker, Chunk as HierarchicalChunk
from boundstate.rtx2070_chunker import RTX2070OptimizedChunker
from boundstate.structured_parser import DocumentStructure, Section, Table, Figure

logger = logging.getLogger(__name__)

class ChunkingStrategy(Enum):
    """Available chunking strategies."""
    HIERARCHICAL = "hierarchical"
    TOKEN_OPTIMIZED = "token_optimized"
    HYBRID = "hybrid"
    QUERY_AWARE = "query_aware"

@dataclass
class HybridChunk:
    """Unified chunk format for hybrid chunking system."""
    chunk_id: str
    doc_id: str
    text: str
    embed_text: str  # Text optimized for embedding (with title/context)

    # Positioning and structure
    start_pos: int
    end_pos: int
    chunk_index: int

    # Structure information (from hierarchical chunker)
    section_path: Optional[str] = None
    chunk_type: Optional[str] = None  # "section", "paragraph", "table", "figure"
    parent_section: Optional[str] = None

    # Token information (from RTX2070 chunker)
    token_count: Optional[int] = None
    overlap_tokens: Optional[int] = None

    # Metadata
    metadata: Dict[str, Any] = None
    content_hash: Optional[str] = None
    created_at: Optional[float] = None

    # Query-specific (for query-aware chunking)
    query_relevance_score: Optional[float] = None
    query_context: Optional[str] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.created_at is None:
            import time
            self.created_at = time.time()

class DocumentTypeClassifier:
    """Classifies documents to determine optimal chunking strategy."""

    def __init__(self):
        # Document type patterns
        self.type_patterns = {
            'nasa_standard': [
                r'nasa-std-\d+',
                r'nasa\s+standard',
                r'technical\s+standard'
            ],
            'specification': [
                r'specification',
                r'spec\b',
                r'requirement.*document',
                r'shall\b.*requirement'
            ],
            'policy': [
                r'policy',
                r'procedure',
                r'directive',
                r'instruction',
                r'npr-\d+'
            ],
            'handbook': [
                r'handbook',
                r'manual',
                r'guide',
                r'nasa-hdbk-\d+'
            ],
            'report': [
                r'report',
                r'analysis',
                r'test\s+result',
                r'study',
                r'investigation'
            ],
            'form': [
                r'form\s+\d+',
                r'questionnaire',
                r'checklist',
                r'worksheet'
            ]
        }

        # Strategy mapping
        self.strategy_mapping = {
            'nasa_standard': ChunkingStrategy.HIERARCHICAL,
            'specification': ChunkingStrategy.HIERARCHICAL,
            'policy': ChunkingStrategy.HIERARCHICAL,
            'handbook': ChunkingStrategy.HYBRID,
            'report': ChunkingStrategy.TOKEN_OPTIMIZED,
            'form': ChunkingStrategy.TOKEN_OPTIMIZED
        }

    def classify_document(self, content: str, filename: str = "") -> Tuple[str, ChunkingStrategy, float]:
        """
        Classify document and recommend chunking strategy.

        Returns:
            (document_type, recommended_strategy, confidence)
        """
        content_lower = content.lower()
        filename_lower = filename.lower()

        scores = {}

        for doc_type, patterns in self.type_patterns.items():
            score = 0
            for pattern in patterns:
                # Check content
                content_matches = len(re.findall(pattern, content_lower))
                filename_matches = len(re.findall(pattern, filename_lower))

                # Weight filename matches higher
                score += content_matches + (filename_matches * 2)

            if score > 0:
                scores[doc_type] = score

        if not scores:
            return 'general', ChunkingStrategy.TOKEN_OPTIMIZED, 0.5

        # Get best match
        best_type = max(scores, key=scores.get)
        max_score = scores[best_type]

        # Calculate confidence (normalize by content length and patterns)
        confidence = min(0.95, 0.6 + (max_score / max(1, len(content) // 1000)))

        strategy = self.strategy_mapping.get(best_type, ChunkingStrategy.TOKEN_OPTIMIZED)

        return best_type, strategy, confidence

class HybridChunkerEngine:
    """
    Main hybrid chunking engine that integrates multiple chunking strategies.

    Combines:
    - HierarchicalChunker for structured documents
    - RTX2070OptimizedChunker for token optimization
    - Query-aware chunking for specific queries
    - Content hash tracking
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        # Initialize component chunkers
        self.hierarchical_chunker = HierarchicalChunker(
            max_section_tokens=self.config.get('max_section_tokens', 800),
            max_paragraph_tokens=self.config.get('max_paragraph_tokens', 400),
            overlap_ratio=self.config.get('overlap_ratio', 0.15),
            min_chunk_tokens=self.config.get('min_chunk_tokens', 50)
        )

        self.token_chunker = RTX2070OptimizedChunker()

        # Document classifier
        self.classifier = DocumentTypeClassifier()

        # Chunking configuration
        self.target_token_count = self.config.get('target_tokens', 420)
        self.max_token_count = self.config.get('max_tokens', 512)
        self.overlap_tokens = self.config.get('overlap_tokens', 60)

        logger.info("Initialized HybridChunkerEngine")

    def chunk_document(self, doc_id: str, content: str, filename: str = "",
                      query: Optional[str] = None, strategy: Optional[ChunkingStrategy] = None,
                      content_hash: Optional[str] = None) -> List[HybridChunk]:
        """
        Main chunking method that selects and applies the optimal strategy.

        Args:
            doc_id: Document identifier
            content: Document text content
            filename: Original filename for classification hints
            query: Optional query for query-aware chunking
            strategy: Force specific strategy (overrides classification)
            content_hash: Content hash for cache invalidation

        Returns:
            List of HybridChunk objects
        """
        try:
            # Classify document if strategy not specified
            if strategy is None:
                doc_type, strategy, confidence = self.classifier.classify_document(content, filename)
                logger.debug(f"Classified {doc_id} as {doc_type} (confidence: {confidence:.2f}) -> {strategy}")
            else:
                doc_type = "manual"
                confidence = 1.0

            # Generate content hash if not provided
            if content_hash is None:
                content_hash = self._compute_content_hash(content)

            # Apply chunking strategy
            if strategy == ChunkingStrategy.HIERARCHICAL:
                chunks = self._chunk_hierarchical(doc_id, content, doc_type, content_hash)
            elif strategy == ChunkingStrategy.TOKEN_OPTIMIZED:
                chunks = self._chunk_token_optimized(doc_id, content, doc_type, content_hash)
            elif strategy == ChunkingStrategy.HYBRID:
                chunks = self._chunk_hybrid(doc_id, content, doc_type, content_hash)
            elif strategy == ChunkingStrategy.QUERY_AWARE:
                chunks = self._chunk_query_aware(doc_id, content, query, doc_type, content_hash)
            else:
                # Fallback to token optimized
                chunks = self._chunk_token_optimized(doc_id, content, doc_type, content_hash)

            # Post-process chunks
            chunks = self._post_process_chunks(chunks, query)

            logger.debug(f"Generated {len(chunks)} chunks for {doc_id} using {strategy}")
            return chunks

        except Exception as e:
            logger.error(f"Chunking failed for {doc_id}: {e}")
            # Fallback to simple token chunking
            return self._chunk_token_optimized(doc_id, content, "fallback", content_hash)

    def _chunk_hierarchical(self, doc_id: str, content: str, doc_type: str,
                           content_hash: str) -> List[HybridChunk]:
        """Apply hierarchical chunking strategy."""
        try:
            # Use the existing hierarchical chunker
            hierarchical_chunks = self.hierarchical_chunker.chunk_by_structure(content)

            # Convert to HybridChunk format
            hybrid_chunks = []
            for i, chunk in enumerate(hierarchical_chunks):
                hybrid_chunk = HybridChunk(
                    chunk_id=f"{doc_id}_hier_{i}",
                    doc_id=doc_id,
                    text=chunk.text,
                    embed_text=self._create_embed_text(chunk.text, chunk.section_path),
                    start_pos=getattr(chunk, 'start_pos', 0),
                    end_pos=getattr(chunk, 'end_pos', len(chunk.text)),
                    chunk_index=i,
                    section_path=chunk.section_path,
                    chunk_type=chunk.chunk_type,
                    parent_section=chunk.parent_section,
                    token_count=chunk.token_count,
                    metadata={
                        'strategy': 'hierarchical',
                        'doc_type': doc_type,
                        'page_span': getattr(chunk, 'page_span', (0, 0)),
                        'overlap_with': getattr(chunk, 'overlap_with', [])
                    },
                    content_hash=content_hash
                )
                hybrid_chunks.append(hybrid_chunk)

            return hybrid_chunks

        except Exception as e:
            logger.error(f"Hierarchical chunking failed: {e}")
            # Fallback to token chunking
            return self._chunk_token_optimized(doc_id, content, doc_type, content_hash)

    def _chunk_token_optimized(self, doc_id: str, content: str, doc_type: str,
                              content_hash: str) -> List[HybridChunk]:
        """Apply token-optimized chunking strategy."""
        try:
            # Use the existing RTX2070 chunker
            token_chunks = self.token_chunker.chunk_document(content, doc_id)

            # Convert to HybridChunk format
            hybrid_chunks = []
            for i, chunk in enumerate(token_chunks):
                hybrid_chunk = HybridChunk(
                    chunk_id=chunk.get('chunk_id', f"{doc_id}_token_{i}"),
                    doc_id=doc_id,
                    text=chunk.get('text', ''),
                    embed_text=chunk.get('embed_text', chunk.get('text', '')),
                    start_pos=chunk.get('start_pos', 0),
                    end_pos=chunk.get('end_pos', len(chunk.get('text', ''))),
                    chunk_index=i,
                    token_count=chunk.get('token_count'),
                    overlap_tokens=chunk.get('overlap_tokens'),
                    metadata={
                        'strategy': 'token_optimized',
                        'doc_type': doc_type,
                        'original_metadata': chunk.get('metadata', {})
                    },
                    content_hash=content_hash
                )
                hybrid_chunks.append(hybrid_chunk)

            return hybrid_chunks

        except Exception as e:
            logger.error(f"Token-optimized chunking failed: {e}")
            # Ultimate fallback: simple text splitting
            return self._chunk_simple_fallback(doc_id, content, doc_type, content_hash)

    def _chunk_hybrid(self, doc_id: str, content: str, doc_type: str,
                     content_hash: str) -> List[HybridChunk]:
        """Apply hybrid chunking strategy (combines hierarchical and token optimization)."""
        try:
            # Try hierarchical chunking first
            try:
                hierarchical_chunks = self._chunk_hierarchical(doc_id, content, doc_type, content_hash)

                # If hierarchical chunks are too large, apply token optimization
                optimized_chunks = []
                for chunk in hierarchical_chunks:
                    if chunk.token_count and chunk.token_count > self.max_token_count:
                        # Split large chunks using token chunker
                        sub_chunks = self._split_large_chunk(chunk, doc_type, content_hash)
                        optimized_chunks.extend(sub_chunks)
                    else:
                        optimized_chunks.append(chunk)

                return optimized_chunks

            except Exception:
                # Fallback to token chunking
                return self._chunk_token_optimized(doc_id, content, doc_type, content_hash)

        except Exception as e:
            logger.error(f"Hybrid chunking failed: {e}")
            return self._chunk_token_optimized(doc_id, content, doc_type, content_hash)

    def _chunk_query_aware(self, doc_id: str, content: str, query: Optional[str],
                          doc_type: str, content_hash: str) -> List[HybridChunk]:
        """Apply query-aware chunking strategy."""
        try:
            if not query:
                # No query provided, fall back to standard chunking
                return self._chunk_token_optimized(doc_id, content, doc_type, content_hash)

            # Extract query terms for relevance scoring
            query_terms = self._extract_query_terms(query)

            # Start with token-optimized chunks
            base_chunks = self._chunk_token_optimized(doc_id, content, doc_type, content_hash)

            # Score chunks based on query relevance
            for chunk in base_chunks:
                relevance_score = self._calculate_query_relevance(chunk.text, query_terms)
                chunk.query_relevance_score = relevance_score
                chunk.query_context = query
                chunk.metadata['strategy'] = 'query_aware'
                chunk.metadata['query_terms'] = query_terms

            # Optionally adjust chunk boundaries based on query terms
            adjusted_chunks = self._adjust_chunk_boundaries_for_query(base_chunks, query_terms)

            return adjusted_chunks

        except Exception as e:
            logger.error(f"Query-aware chunking failed: {e}")
            return self._chunk_token_optimized(doc_id, content, doc_type, content_hash)

    def _split_large_chunk(self, chunk: HybridChunk, doc_type: str, content_hash: str) -> List[HybridChunk]:
        """Split a large hierarchical chunk using token optimization."""
        try:
            # Use token chunker to split the text
            sub_chunks_data = self.token_chunker.chunk_document(chunk.text, chunk.doc_id)

            sub_chunks = []
            for i, sub_data in enumerate(sub_chunks_data):
                sub_chunk = HybridChunk(
                    chunk_id=f"{chunk.chunk_id}_sub_{i}",
                    doc_id=chunk.doc_id,
                    text=sub_data.get('text', ''),
                    embed_text=self._create_embed_text(
                        sub_data.get('text', ''),
                        chunk.section_path
                    ),
                    start_pos=chunk.start_pos + sub_data.get('start_pos', 0),
                    end_pos=chunk.start_pos + sub_data.get('end_pos', len(sub_data.get('text', ''))),
                    chunk_index=chunk.chunk_index * 1000 + i,  # Maintain ordering
                    section_path=chunk.section_path,
                    chunk_type=chunk.chunk_type,
                    parent_section=chunk.parent_section,
                    token_count=sub_data.get('token_count'),
                    overlap_tokens=sub_data.get('overlap_tokens'),
                    metadata={
                        'strategy': 'hybrid',
                        'doc_type': doc_type,
                        'parent_chunk_id': chunk.chunk_id,
                        'sub_chunk_index': i
                    },
                    content_hash=content_hash
                )
                sub_chunks.append(sub_chunk)

            return sub_chunks

        except Exception as e:
            logger.error(f"Failed to split large chunk: {e}")
            return [chunk]  # Return original chunk if splitting fails

    def _chunk_simple_fallback(self, doc_id: str, content: str, doc_type: str,
                              content_hash: str) -> List[HybridChunk]:
        """Simple fallback chunking when all else fails."""
        try:
            # Simple sentence-based chunking
            sentences = re.split(r'[.!?]+', content)
            chunks = []
            current_chunk = ""
            chunk_index = 0

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                # Rough token estimation (1 token ≈ 4 characters)
                potential_length = len(current_chunk + " " + sentence)

                if potential_length > self.target_token_count * 4 and current_chunk:
                    # Create chunk
                    chunk = HybridChunk(
                        chunk_id=f"{doc_id}_fallback_{chunk_index}",
                        doc_id=doc_id,
                        text=current_chunk.strip(),
                        embed_text=current_chunk.strip(),
                        start_pos=0,  # Approximate
                        end_pos=len(current_chunk.strip()),
                        chunk_index=chunk_index,
                        token_count=len(current_chunk) // 4,  # Rough estimate
                        metadata={
                            'strategy': 'simple_fallback',
                            'doc_type': doc_type
                        },
                        content_hash=content_hash
                    )
                    chunks.append(chunk)

                    current_chunk = sentence
                    chunk_index += 1
                else:
                    current_chunk += " " + sentence if current_chunk else sentence

            # Add final chunk
            if current_chunk.strip():
                chunk = HybridChunk(
                    chunk_id=f"{doc_id}_fallback_{chunk_index}",
                    doc_id=doc_id,
                    text=current_chunk.strip(),
                    embed_text=current_chunk.strip(),
                    start_pos=0,
                    end_pos=len(current_chunk.strip()),
                    chunk_index=chunk_index,
                    token_count=len(current_chunk) // 4,
                    metadata={
                        'strategy': 'simple_fallback',
                        'doc_type': doc_type
                    },
                    content_hash=content_hash
                )
                chunks.append(chunk)

            return chunks

        except Exception as e:
            logger.error(f"Simple fallback chunking failed: {e}")
            return []

    def _create_embed_text(self, text: str, section_path: Optional[str] = None) -> str:
        """Create optimized text for embedding with context."""
        # Add section context if available
        if section_path:
            return f"{section_path}: {text}"
        return text

    def _extract_query_terms(self, query: str) -> List[str]:
        """Extract important terms from query for relevance scoring."""
        # Simple term extraction (could be enhanced with NLP)
        terms = re.findall(r'\b\w+\b', query.lower())

        # Filter out common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        terms = [term for term in terms if term not in stop_words and len(term) > 2]

        return terms

    def _calculate_query_relevance(self, text: str, query_terms: List[str]) -> float:
        """Calculate relevance score between text and query terms."""
        if not query_terms:
            return 0.0

        text_lower = text.lower()
        matches = 0

        for term in query_terms:
            if term in text_lower:
                matches += 1

        return matches / len(query_terms)

    def _adjust_chunk_boundaries_for_query(self, chunks: List[HybridChunk],
                                          query_terms: List[str]) -> List[HybridChunk]:
        """Adjust chunk boundaries to preserve query-relevant contexts."""
        # For now, return chunks as-is
        # This could be enhanced to merge/split chunks based on query term distribution
        return chunks

    def _post_process_chunks(self, chunks: List[HybridChunk], query: Optional[str] = None) -> List[HybridChunk]:
        """Post-process chunks for consistency and optimization."""
        try:
            # Filter out very small chunks
            min_length = 50  # Minimum characters
            filtered_chunks = [chunk for chunk in chunks if len(chunk.text.strip()) >= min_length]

            # Ensure embed_text is populated
            for chunk in filtered_chunks:
                if not chunk.embed_text:
                    chunk.embed_text = self._create_embed_text(chunk.text, chunk.section_path)

            # Add query context if provided
            if query:
                for chunk in filtered_chunks:
                    if chunk.query_context is None:
                        chunk.query_context = query

            return filtered_chunks

        except Exception as e:
            logger.error(f"Post-processing failed: {e}")
            return chunks

    def _compute_content_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

    def get_chunking_statistics(self) -> Dict[str, Any]:
        """Get statistics about chunking operations."""
        # This would be enhanced with actual usage tracking
        return {
            'strategies_available': [strategy.value for strategy in ChunkingStrategy],
            'target_token_count': self.target_token_count,
            'max_token_count': self.max_token_count,
            'overlap_tokens': self.overlap_tokens,
            'hierarchical_chunker_config': {
                'max_section_tokens': self.hierarchical_chunker.max_section_tokens,
                'max_paragraph_tokens': self.hierarchical_chunker.max_paragraph_tokens,
                'overlap_ratio': self.hierarchical_chunker.overlap_ratio
            },
            'token_chunker_config': {
                'chunk_size_tokens': self.token_chunker.chunk_size_tokens,
                'overlap_tokens': self.token_chunker.overlap_tokens
            }
        }

# Convenience function for backwards compatibility
def chunk_document_hybrid(doc_id: str, content: str, **kwargs) -> List[Dict]:
    """Convenience function that returns chunks as dictionaries."""
    chunker = HybridChunkerEngine()
    chunks = chunker.chunk_document(doc_id, content, **kwargs)

    # Convert to dictionary format
    return [asdict(chunk) for chunk in chunks]