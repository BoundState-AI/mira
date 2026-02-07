#!/usr/bin/env python3
"""
Module: Post
Purpose: Metadata for a document chunk.

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

import os
import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import threading

try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from tinydb import TinyDB, Query
except ImportError as e:
    print(f"Missing dependencies: {e}")
    print("Install with: pip install sentence-transformers tinydb numpy")
    exit(1)

from config_manager import get_config
from document_discovery_index import DocumentMetadata

logger = logging.getLogger(__name__)

@dataclass
class ChunkMetadata:
    """Metadata for a document chunk."""
    chunk_id: str
    doc_id: str
    chunk_index: int
    text: str
    embed_text: str  # Text used for embedding (may include title/context)
    start_pos: int
    end_pos: int
    chunk_type: str  # 'clause', 'section', 'paragraph', 'table', 'page'
    confidence: float
    created_at: str
    query_hash: Optional[str] = None  # Hash of query that triggered this chunk

@dataclass
class ChunkedDocument:
    """Result of post-chunking a document."""
    doc_id: str
    chunks: List[ChunkMetadata]
    chunking_profile: str
    total_processing_time: float
    cached: bool = False

class IntentClassifier:
    """Classifies document type and selects appropriate chunking profile."""

    def __init__(self):
        self.profiles = {
            'spec': {
                'description': 'Technical specifications and standards',
                'chunk_type': 'clause',
                'patterns': [r'\d+\.\d+\s', r'Section\s+\d+', r'Clause\s+\d+'],
                'preserve_structure': True,
                'target_tokens': 420
            },
            'policy': {
                'description': 'Policies and procedural documents',
                'chunk_type': 'paragraph',
                'patterns': [r'\bshall\b', r'\bmust\b', r'\brequired\b', r'\bmandatory\b'],
                'preserve_structure': True,
                'target_tokens': 350
            },
            'report': {
                'description': 'Technical reports and test documents',
                'chunk_type': 'page',
                'patterns': [r'Table\s+\d+', r'Figure\s+\d+', r'Results?', r'Conclusion'],
                'preserve_structure': False,
                'target_tokens': 500
            },
            'manual': {
                'description': 'Handbooks and manuals',
                'chunk_type': 'section',
                'patterns': [r'Chapter\s+\d+', r'Section\s+\d+', r'Appendix\s+[A-Z]'],
                'preserve_structure': True,
                'target_tokens': 400
            },
            'form': {
                'description': 'Forms and checklists',
                'chunk_type': 'section',
                'patterns': [r'\d+\.\d+\s+.*\?', r'Checklist', r'Yes\s*\/\s*No'],
                'preserve_structure': True,
                'target_tokens': 300
            },
            'general': {
                'description': 'General documents',
                'chunk_type': 'paragraph',
                'patterns': [],
                'preserve_structure': False,
                'target_tokens': 420
            }
        }

    def classify_document(self, text: str, filename: str, metadata: DocumentMetadata = None) -> str:
        """Classify document and return appropriate chunking profile."""
        text_lower = text[:3000].lower()  # Sample first 3000 chars
        filename_lower = filename.lower()

        scores = {}

        # Score based on filename patterns
        if any(term in filename_lower for term in ['std', 'spec', 'hdbk', 'handbook']):
            if 'nasa-std' in filename_lower or 'msfc-std' in filename_lower:
                scores['spec'] = scores.get('spec', 0) + 0.8
            elif 'nasa-hdbk' in filename_lower or 'msfc-hdbk' in filename_lower:
                scores['manual'] = scores.get('manual', 0) + 0.8

        if any(term in filename_lower for term in ['npr', 'npd', 'policy', 'procedure']):
            scores['policy'] = scores.get('policy', 0) + 0.9

        if any(term in filename_lower for term in ['report', 'test', 'tm-', 'technical memo']):
            scores['report'] = scores.get('report', 0) + 0.7

        if any(term in filename_lower for term in ['form', 'checklist', 'worksheet']):
            scores['form'] = scores.get('form', 0) + 0.8

        # Score based on content patterns
        for profile_name, profile in self.profiles.items():
            pattern_matches = 0
            for pattern in profile['patterns']:
                import re
                matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
                pattern_matches += matches

            if pattern_matches > 0:
                # Normalize by text length and pattern count
                content_score = min(0.6, pattern_matches / max(1, len(profile['patterns'])) / 10)
                scores[profile_name] = scores.get(profile_name, 0) + content_score

        # Use metadata if available
        if metadata and hasattr(metadata, 'processing_mode'):
            if metadata.processing_mode == 'pre_chunk':
                # Likely a standard or important document
                scores['spec'] = scores.get('spec', 0) + 0.3

        # Determine best profile
        if scores:
            best_profile = max(scores.keys(), key=lambda k: scores[k])
            confidence = scores[best_profile]
            if confidence > 0.3:
                logger.debug(f"Classified {filename} as {best_profile} (confidence: {confidence:.2f})")
                return best_profile

        logger.debug(f"Using general profile for {filename}")
        return 'general'

class SmartChunker:
    """Intelligent document chunker that adapts to document type."""

    def __init__(self):
        self.intent_classifier = IntentClassifier()

    def chunk_document(self, text: str, filename: str, profile: str = None,
                      metadata: DocumentMetadata = None) -> List[Dict[str, Any]]:
        """Chunk document using appropriate strategy."""

        if not profile:
            profile = self.intent_classifier.classify_document(text, filename, metadata)

        profile_config = self.intent_classifier.profiles[profile]
        target_tokens = profile_config['target_tokens']

        if profile == 'spec':
            return self._chunk_specification(text, filename, target_tokens)
        elif profile == 'policy':
            return self._chunk_policy(text, filename, target_tokens)
        elif profile == 'report':
            return self._chunk_report(text, filename, target_tokens)
        elif profile == 'manual':
            return self._chunk_manual(text, filename, target_tokens)
        elif profile == 'form':
            return self._chunk_form(text, filename, target_tokens)
        else:
            return self._chunk_general(text, filename, target_tokens)

    def _chunk_specification(self, text: str, filename: str, target_tokens: int) -> List[Dict[str, Any]]:
        """Chunk technical specifications by clauses and sections."""
        import re

        chunks = []

        # Split by numbered sections (e.g., "3.1", "3.1.1")
        section_pattern = r'(?=\d+\.\d+(?:\.\d+)?\s+[A-Z])'
        sections = re.split(section_pattern, text)

        if len(sections) <= 1:
            # Fallback to paragraph-based chunking
            return self._chunk_general(text, filename, target_tokens)

        title = Path(filename).stem.replace('_', ' ').replace('-', ' ')

        for i, section in enumerate(sections):
            if not section.strip():
                continue

            section_text = section.strip()

            # If section is too long, split it further
            if len(section_text.split()) > target_tokens * 1.5:
                sub_chunks = self._split_large_section(section_text, target_tokens)
                for j, sub_chunk in enumerate(sub_chunks):
                    chunks.append({
                        'text': sub_chunk,
                        'embed_text': f"{title}\n\n{sub_chunk}",
                        'chunk_type': 'clause',
                        'chunk_index': len(chunks),
                        'start_pos': 0,  # Would need proper position tracking
                        'end_pos': len(sub_chunk),
                        'confidence': 0.8
                    })
            else:
                chunks.append({
                    'text': section_text,
                    'embed_text': f"{title}\n\n{section_text}",
                    'chunk_type': 'clause',
                    'chunk_index': len(chunks),
                    'start_pos': 0,
                    'end_pos': len(section_text),
                    'confidence': 0.9
                })

        return chunks if chunks else self._chunk_general(text, filename, target_tokens)

    def _chunk_policy(self, text: str, filename: str, target_tokens: int) -> List[Dict[str, Any]]:
        """Chunk policy documents preserving modal verbs and requirements."""
        import re

        chunks = []
        title = Path(filename).stem.replace('_', ' ').replace('-', ' ')

        # Split by paragraphs, but keep modal verb sentences together
        paragraphs = re.split(r'\n\s*\n', text)

        current_chunk = ""
        current_tokens = 0

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            para_tokens = len(paragraph.split())

            # Check if paragraph contains modal verbs (requirements)
            has_modal = bool(re.search(r'\b(shall|must|should|will|may|required|mandatory)\b', paragraph, re.IGNORECASE))

            if current_tokens + para_tokens <= target_tokens:
                current_chunk += "\n\n" + paragraph if current_chunk else paragraph
                current_tokens += para_tokens
            else:
                # Finish current chunk
                if current_chunk:
                    chunks.append({
                        'text': current_chunk.strip(),
                        'embed_text': f"{title}\n\n{current_chunk.strip()}",
                        'chunk_type': 'paragraph',
                        'chunk_index': len(chunks),
                        'start_pos': 0,
                        'end_pos': len(current_chunk),
                        'confidence': 0.85
                    })

                # Start new chunk
                current_chunk = paragraph
                current_tokens = para_tokens

        # Add final chunk
        if current_chunk:
            chunks.append({
                'text': current_chunk.strip(),
                'embed_text': f"{title}\n\n{current_chunk.strip()}",
                'chunk_type': 'paragraph',
                'chunk_index': len(chunks),
                'start_pos': 0,
                'end_pos': len(current_chunk),
                'confidence': 0.85
            })

        return chunks if chunks else self._chunk_general(text, filename, target_tokens)

    def _chunk_report(self, text: str, filename: str, target_tokens: int) -> List[Dict[str, Any]]:
        """Chunk technical reports keeping tables and figures together."""
        import re

        chunks = []
        title = Path(filename).stem.replace('_', ' ').replace('-', ' ')

        # Try to split by sections first
        section_headers = re.findall(r'\n([A-Z][A-Za-z\s]{5,50})\n', text)

        if len(section_headers) > 2:
            # Split by sections
            for header in section_headers:
                pattern = f'\n{re.escape(header)}\n'
                sections = re.split(pattern, text, 1)
                if len(sections) == 2:
                    section_text = sections[1].split('\n' + section_headers[section_headers.index(header) + 1] + '\n')[0] if header != section_headers[-1] else sections[1]

                    if section_text.strip():
                        chunks.append({
                            'text': f"{header}\n{section_text.strip()}",
                            'embed_text': f"{title}\n\n{header}\n{section_text.strip()}",
                            'chunk_type': 'section',
                            'chunk_index': len(chunks),
                            'start_pos': 0,
                            'end_pos': len(section_text),
                            'confidence': 0.8
                        })
        else:
            # Fallback to general chunking
            return self._chunk_general(text, filename, target_tokens)

        return chunks if chunks else self._chunk_general(text, filename, target_tokens)

    def _chunk_manual(self, text: str, filename: str, target_tokens: int) -> List[Dict[str, Any]]:
        """Chunk handbooks and manuals by chapters and sections."""
        return self._chunk_specification(text, filename, target_tokens)  # Similar approach

    def _chunk_form(self, text: str, filename: str, target_tokens: int) -> List[Dict[str, Any]]:
        """Chunk forms and checklists by question groups."""
        import re

        chunks = []
        title = Path(filename).stem.replace('_', ' ').replace('-', ' ')

        # Split by question patterns
        questions = re.split(r'\n(?=\d+\.\d+\s)', text)

        current_chunk = ""
        current_tokens = 0

        for question in questions:
            question = question.strip()
            if not question:
                continue

            q_tokens = len(question.split())

            if current_tokens + q_tokens <= target_tokens:
                current_chunk += "\n\n" + question if current_chunk else question
                current_tokens += q_tokens
            else:
                if current_chunk:
                    chunks.append({
                        'text': current_chunk.strip(),
                        'embed_text': f"{title}\n\n{current_chunk.strip()}",
                        'chunk_type': 'section',
                        'chunk_index': len(chunks),
                        'start_pos': 0,
                        'end_pos': len(current_chunk),
                        'confidence': 0.8
                    })

                current_chunk = question
                current_tokens = q_tokens

        if current_chunk:
            chunks.append({
                'text': current_chunk.strip(),
                'embed_text': f"{title}\n\n{current_chunk.strip()}",
                'chunk_type': 'section',
                'chunk_index': len(chunks),
                'start_pos': 0,
                'end_pos': len(current_chunk),
                'confidence': 0.8
            })

        return chunks if chunks else self._chunk_general(text, filename, target_tokens)

    def _chunk_general(self, text: str, filename: str, target_tokens: int) -> List[Dict[str, Any]]:
        """General chunking strategy using sliding window."""
        words = text.split()
        if not words:
            return []

        chunks = []
        title = Path(filename).stem.replace('_', ' ').replace('-', ' ')

        chunk_size = target_tokens
        overlap = target_tokens // 7  # ~60 tokens overlap

        i = 0
        chunk_index = 0

        while i < len(words):
            end_pos = min(len(words), i + chunk_size)
            chunk_words = words[i:end_pos]
            chunk_text = " ".join(chunk_words)

            chunks.append({
                'text': chunk_text,
                'embed_text': f"{title}\n\n{chunk_text}",
                'chunk_type': 'paragraph',
                'chunk_index': chunk_index,
                'start_pos': i,
                'end_pos': end_pos,
                'confidence': 0.7
            })

            chunk_index += 1

            # Move window
            if end_pos >= len(words):
                break
            i = max(i + 1, i + chunk_size - overlap)

        return chunks

    def _split_large_section(self, text: str, target_tokens: int) -> List[str]:
        """Split a large section into smaller chunks."""
        import re

        # Try to split by sub-sections or sentences
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)

        chunks = []
        current_chunk = ""
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = len(sentence.split())

            if current_tokens + sentence_tokens <= target_tokens:
                current_chunk += " " + sentence if current_chunk else sentence
                current_tokens += sentence_tokens
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence
                current_tokens = sentence_tokens

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

class PostChunkingEngine:
    """Main engine for on-demand document post-chunking with caching."""

    def __init__(self, cache_dir: str = "post_chunk_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        self.config = get_config()
        self.chunker = SmartChunker()
        self.cache_db = TinyDB(self.cache_dir / "cache_metadata.json")

        # Thread safety
        self._lock = threading.RLock()

        # Initialize embedder
        self.embedder = None
        self._initialize_embedder()

        # Statistics
        self.stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'total_chunks_created': 0,
            'average_processing_time': 0.0,
            'documents_processed': 0
        }

    def _initialize_embedder(self):
        """Initialize embedding model."""
        try:
            model_name = "nomic-ai/nomic-embed-text-v1.5"
            device = self.config.performance.embedding_device

            self.embedder = SentenceTransformer(
                model_name,
                device=device,
                trust_remote_code=True
            )
            logger.info(f"Post-chunking embedder initialized: {model_name} on {device}")

        except Exception as e:
            logger.error(f"Failed to initialize post-chunking embedder: {e}")
            raise

    def _generate_cache_key(self, doc_id: str, query: str = None) -> str:
        """Generate cache key for document/query combination."""
        if query:
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]
            return f"{doc_id}_{query_hash}"
        return doc_id

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached chunks are still valid."""
        cache_entry = self.cache_db.search(Query().cache_key == cache_key)
        if not cache_entry:
            return False

        entry = cache_entry[0]
        cache_age_hours = (time.time() - entry['created_at']) / 3600

        return cache_age_hours < (self.config.retrieval.cache_ttl_days * 24)

    def _load_cached_chunks(self, cache_key: str) -> Optional[ChunkedDocument]:
        """Load chunks from cache."""
        try:
            cache_file = self.cache_dir / f"{cache_key}.json"
            if not cache_file.exists():
                return None

            with open(cache_file, 'r') as f:
                data = json.load(f)

            chunks = [ChunkMetadata(**chunk) for chunk in data['chunks']]

            return ChunkedDocument(
                doc_id=data['doc_id'],
                chunks=chunks,
                chunking_profile=data['chunking_profile'],
                total_processing_time=data['total_processing_time'],
                cached=True
            )

        except Exception as e:
            logger.error(f"Error loading cached chunks for {cache_key}: {e}")
            return None

    def _save_to_cache(self, cache_key: str, chunked_doc: ChunkedDocument, query: str = None):
        """Save chunks to cache."""
        try:
            cache_file = self.cache_dir / f"{cache_key}.json"

            data = {
                'doc_id': chunked_doc.doc_id,
                'chunks': [asdict(chunk) for chunk in chunked_doc.chunks],
                'chunking_profile': chunked_doc.chunking_profile,
                'total_processing_time': chunked_doc.total_processing_time,
                'query_context': query
            }

            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)

            # Update cache metadata
            self.cache_db.upsert({
                'cache_key': cache_key,
                'doc_id': chunked_doc.doc_id,
                'created_at': time.time(),
                'chunk_count': len(chunked_doc.chunks),
                'profile_used': chunked_doc.chunking_profile
            }, Query().cache_key == cache_key)

        except Exception as e:
            logger.error(f"Error saving to cache {cache_key}: {e}")

    def post_chunk_document(self, doc_id: str, file_path: str, query: str = None,
                          metadata: DocumentMetadata = None) -> Optional[ChunkedDocument]:
        """Post-chunk a document with caching."""

        with self._lock:
            start_time = time.time()

            # Generate cache key
            cache_key = self._generate_cache_key(doc_id, query)

            # Check cache first
            if self._is_cache_valid(cache_key):
                cached_result = self._load_cached_chunks(cache_key)
                if cached_result:
                    self.stats['cache_hits'] += 1
                    logger.debug(f"Cache hit for {doc_id}")
                    return cached_result

            self.stats['cache_misses'] += 1

            try:
                # Extract document text
                text = self._extract_document_text(file_path)
                if not text:
                    logger.warning(f"No text extracted from {file_path}")
                    return None

                # Determine chunking profile
                filename = os.path.basename(file_path)
                profile = self.chunker.intent_classifier.classify_document(text, filename, metadata)

                logger.debug(f"Post-chunking {filename} using {profile} profile")

                # Chunk the document
                chunk_data = self.chunker.chunk_document(text, filename, profile, metadata)

                # Create chunk metadata objects
                chunks = []
                for i, chunk in enumerate(chunk_data):
                    chunk_id = f"{doc_id}_{i:04d}"

                    chunk_meta = ChunkMetadata(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        chunk_index=i,
                        text=chunk['text'],
                        embed_text=chunk['embed_text'],
                        start_pos=chunk.get('start_pos', 0),
                        end_pos=chunk.get('end_pos', len(chunk['text'])),
                        chunk_type=chunk['chunk_type'],
                        confidence=chunk['confidence'],
                        created_at=time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        query_hash=hashlib.sha256(query.encode()).hexdigest()[:8] if query else None
                    )
                    chunks.append(chunk_meta)

                processing_time = time.time() - start_time

                # Create result
                chunked_doc = ChunkedDocument(
                    doc_id=doc_id,
                    chunks=chunks,
                    chunking_profile=profile,
                    total_processing_time=processing_time,
                    cached=False
                )

                # Save to cache
                self._save_to_cache(cache_key, chunked_doc, query)

                # Update statistics
                self.stats['total_chunks_created'] += len(chunks)
                self.stats['documents_processed'] += 1
                self.stats['average_processing_time'] = (
                    (self.stats['average_processing_time'] * (self.stats['documents_processed'] - 1) + processing_time)
                    / self.stats['documents_processed']
                )

                logger.debug(f"Post-chunked {filename} into {len(chunks)} chunks in {processing_time:.2f}s")
                return chunked_doc

            except Exception as e:
                logger.error(f"Error post-chunking document {doc_id}: {e}")
                return None

    def _extract_document_text(self, file_path: str) -> str:
        """Extract text from document."""
        try:
            # Import here to avoid circular imports
            import sys
            sys.path.append('..')
            from boundstate.parsers import get_parser

            with open(file_path, 'rb') as f:
                file_bytes = f.read()

            parser = get_parser(file_path, file_bytes=file_bytes)
            sections = parser.parse()

            if not sections:
                return ""

            # Combine all text
            full_text = "\n\n".join(section.get('text', '') for section in sections)
            return full_text

        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
            return ""

    def generate_chunk_embeddings(self, chunks: List[ChunkMetadata]) -> List[np.ndarray]:
        """Generate embeddings for chunks."""
        if not chunks:
            return []

        try:
            # Prepare texts with Nomic prefix
            texts = [f"search_document: {chunk.embed_text}" for chunk in chunks]

            # Generate embeddings in batch
            embeddings = self.embedder.encode(
                texts,
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=self.config.performance.chunk_batch_size,
                show_progress_bar=False
            )

            return embeddings

        except Exception as e:
            logger.error(f"Error generating chunk embeddings: {e}")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """Get post-chunking statistics."""
        cache_total = self.stats['cache_hits'] + self.stats['cache_misses']
        cache_hit_rate = (self.stats['cache_hits'] / cache_total * 100) if cache_total > 0 else 0

        return {
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'cache_hit_rate_percent': round(cache_hit_rate, 1),
            'total_chunks_created': self.stats['total_chunks_created'],
            'documents_processed': self.stats['documents_processed'],
            'average_processing_time_seconds': round(self.stats['average_processing_time'], 2),
            'cache_entries': len(self.cache_db.all())
        }

    def cleanup_expired_cache(self):
        """Remove expired cache entries."""
        current_time = time.time()
        ttl_seconds = self.config.retrieval.cache_ttl_days * 24 * 3600

        expired_entries = []
        for entry in self.cache_db.all():
            if current_time - entry['created_at'] > ttl_seconds:
                expired_entries.append(entry)

        for entry in expired_entries:
            # Remove cache file
            cache_file = self.cache_dir / f"{entry['cache_key']}.json"
            if cache_file.exists():
                cache_file.unlink()

            # Remove from database
            self.cache_db.remove(Query().cache_key == entry['cache_key'])

        if expired_entries:
            logger.info(f"Cleaned up {len(expired_entries)} expired cache entries")

if __name__ == "__main__":
    # Test the post-chunking engine
    logging.basicConfig(level=logging.DEBUG)

    engine = PostChunkingEngine("test_post_chunk_cache")
    stats = engine.get_statistics()
    print(f"Post-chunking engine statistics: {stats}")

    # Test intent classification
    classifier = IntentClassifier()
    test_files = [
        ("NASA-STD-6001B_Flammability_Requirements.pdf", "This document establishes flammability requirements..."),
        ("NPR-8715.3C_Safety_Risk_Management.pdf", "This NPR establishes requirements for safety risk management shall be implemented..."),
        ("Technical_Report_Oxygen_Compatibility.pdf", "This report presents the results of oxygen compatibility testing...")
    ]

    for filename, sample_text in test_files:
        profile = classifier.classify_document(sample_text, filename)
        print(f"{filename} -> {profile} profile")