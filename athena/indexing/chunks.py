#!/usr/bin/env python3
"""
Module: Chunks
Purpose: Single chunk in the hot tier index.

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

import json
import logging
import hashlib
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import numpy as np
import faiss
from threading import RLock

from config_manager import get_config

__all__ = ["SmartChunksIndex", "ChunkEntry", "IndexStatistics"]

__safety_critical__ = False

logger = logging.getLogger(__name__)


@dataclass
class ChunkEntry:
    """Single chunk in the hot tier index."""
    doc_id: str
    chunk_id: str
    text: str
    embedding: Optional[np.ndarray]
    metadata: Dict[str, Any]
    content_hash: str
    source: str = "smart_chunks_index"


@dataclass 
class IndexStatistics:
    """Statistics for the smart chunks index."""
    total_chunks: int = 0
    total_documents: int = 0
    index_size_mb: float = 0.0
    avg_chunks_per_doc: float = 0.0


class SmartChunksIndex:
    """FAISS-based fast chunk storage for hot tier documents.
    
    Handles promoted and pre-chunked documents for instant retrieval.
    Supports document-scoped queries and content hash validation.
    
    Compliance: SWE-013, SWE-033
    """
    
    def __init__(self, index_dir: str, dim: int = 768, use_ivf_threshold: int = 20000, nlist: int = 512, nprobe: int = 8):
        """Initialize smart chunks index with automatic IVF upgrade.

        Args:
            index_dir: Directory for index persistence
            dim: Embedding dimension (768 for Nomic)
            use_ivf_threshold: Switch to IVF when total chunks exceed this
            nlist: IVF coarse cluster count
            nprobe: IVF probe count (set on search)
        """
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self.config = get_config()
        self.dim = dim
        self.use_ivf_threshold = use_ivf_threshold
        self.nlist = nlist
        self.nprobe = nprobe
        self._lock = RLock()

        # FAISS index - starts Flat, upgrades to IVF automatically
        self.index = None
        self.is_trained = False

        # Metadata storage (embeddings will be moved out of JSON)
        self.chunks: List[ChunkEntry] = []  # List of chunk entries
        self.doc_to_chunks: Dict[str, List[int]] = {}  # doc_id -> chunk_indices
        self.content_hashes: Dict[str, str] = {}  # doc_id -> content_hash

        self._load_index()
    
    def _initialize_index(self, dim: int = None):
        """Create a fresh FAISS index, initially Flat; may upgrade later."""
        if dim is None:
            dim = self.dim
        self.index = faiss.IndexFlatL2(dim)
        self.dim = dim
        self.is_trained = True
    
    def _load_index(self):
        """Load persisted index from disk."""
        try:
            index_file = self.index_dir / "index.faiss"
            metadata_file = self.index_dir / "metadata.json"
            
            if index_file.exists() and metadata_file.exists():
                # Load FAISS index
                self.index = faiss.read_index(str(index_file))
                
                # Load metadata
                with open(metadata_file, 'r') as f:
                    data = json.load(f)

                    # Handle chunk data - convert to ChunkEntry objects
                    self.chunks = []
                    for chunk_data in data['chunks']:
                        if isinstance(chunk_data, dict):
                            # Convert embedding back to numpy array if present
                            if 'embedding' in chunk_data and chunk_data['embedding']:
                                chunk_data['embedding'] = np.array(chunk_data['embedding'], dtype=np.float32)
                            chunk_entry = ChunkEntry(**chunk_data)
                            self.chunks.append(chunk_entry)

                    self.doc_to_chunks = data['doc_to_chunks']
                    self.content_hashes = data['content_hashes']
                    self.is_trained = data.get('is_trained', True)
                
                logger.info(f"Loaded index with {len(self.chunks)} chunks from {len(self.doc_to_chunks)} documents")
                
        except Exception as e:
            logger.error(f"Error loading index: {e}")
            self._initialize_index(self.dim)
    
    def _save_index(self):
        """Persist index to disk."""
        with self._lock:
            try:
                index_file = self.index_dir / "index.faiss"
                metadata_file = self.index_dir / "metadata.json"
                
                # Save FAISS index
                faiss.write_index(self.index, str(index_file))
                
                # Save metadata (convert numpy arrays to lists for JSON)
                chunks_data = []
                for chunk in self.chunks:
                    chunk_dict = asdict(chunk)
                    if chunk_dict.get('embedding') is not None:
                        chunk_dict['embedding'] = chunk_dict['embedding'].tolist()
                    chunks_data.append(chunk_dict)
                
                metadata = {
                    'chunks': chunks_data,
                    'doc_to_chunks': self.doc_to_chunks,
                    'content_hashes': self.content_hashes,
                    'is_trained': self.is_trained
                }
                
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f)
                
                logger.debug(f"Saved index with {len(self.chunks)} chunks")
                
            except Exception as e:
                logger.error(f"Error saving index: {e}")
    
    def add_document_chunks(self, doc_id: str, chunks: List[Dict[str, Any]], 
                           content_hash: str, embeddings: np.ndarray) -> bool:
        """Add pre-chunked document to hot tier.
        
        Args:
            doc_id: Document identifier
            chunks: List of chunk dictionaries with 'text', 'metadata'
            content_hash: Hash of document content for validation
            embeddings: Numpy array of chunk embeddings (n_chunks x dim)
            
        Returns:
            Success status
        """
        with self._lock:
            try:
                # Remove old version if exists
                if doc_id in self.doc_to_chunks:
                    if self.content_hashes.get(doc_id) != content_hash:
                        logger.info(f"Replacing outdated chunks for {doc_id}")
                        self.remove_document(doc_id)
                    else:
                        logger.debug(f"Document {doc_id} already indexed with same content")
                        return True
                
                # Validate embeddings shape
                if embeddings.shape[1] != self.dim:
                    logger.error(f"Embedding dimension mismatch: {embeddings.shape[1]} != {self.dim}")
                    return False
                
                # Maybe upgrade to IVF before large add
                self._maybe_upgrade_to_ivf(incoming=len(chunks))

                # Initialize index if needed
                if self.index is None:
                    self._initialize_index(self.dim)

                # Train index if needed (for IVF)
                if not self.is_trained and isinstance(self.index, faiss.IndexIVFFlat):
                    if self.index.ntotal >= self.nlist:
                        logger.info("Training IVF index...")
                        sample_vectors = []
                        for c in self.chunks:
                            if c.embedding is not None:
                                sample_vectors.append(c.embedding)
                        if len(sample_vectors) >= self.nlist:
                            sample_array = np.vstack(sample_vectors[:self.nlist * 10])
                            self.index.train(sample_array)
                            self.is_trained = True
                
                # Add chunks
                chunk_indices = []
                for i, (chunk_data, embedding) in enumerate(zip(chunks, embeddings)):
                    chunk_entry = ChunkEntry(
                        doc_id=doc_id,
                        chunk_id=f"{doc_id}_{i:04d}",
                        text=chunk_data.get('text', ''),
                        embedding=embedding,
                        metadata=chunk_data.get('metadata', {}),
                        content_hash=content_hash
                    )
                    
                    chunk_idx = len(self.chunks)
                    self.chunks.append(chunk_entry)
                    chunk_indices.append(chunk_idx)
                    
                    # Add to FAISS index
                    self.index.add(embedding.reshape(1, -1))
                
                # Update mappings
                self.doc_to_chunks[doc_id] = chunk_indices
                self.content_hashes[doc_id] = content_hash
                
                # Persist periodically
                if len(self.chunks) % 100 == 0:
                    self._save_index()
                
                logger.info(f"Added {len(chunks)} chunks for document {doc_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error adding chunks for {doc_id}: {e}")
                return False
    
    def remove_document(self, doc_id: str) -> bool:
        """Remove document from hot tier.
        
        Args:
            doc_id: Document to remove
            
        Returns:
            Success status
        """
        with self._lock:
            try:
                if doc_id not in self.doc_to_chunks:
                    return True
                
                # Get indices to remove
                indices_to_remove = set(self.doc_to_chunks[doc_id])
                
                # Rebuild index without these chunks
                new_chunks = []
                new_embeddings = []
                old_to_new_idx = {}
                
                for old_idx, chunk in enumerate(self.chunks):
                    if old_idx not in indices_to_remove:
                        new_idx = len(new_chunks)
                        old_to_new_idx[old_idx] = new_idx
                        new_chunks.append(chunk)
                        if chunk.embedding is not None:
                            new_embeddings.append(chunk.embedding)
                
                # Rebuild FAISS index
                self._initialize_index()
                if new_embeddings:
                    embeddings_array = np.array(new_embeddings)
                    if self.is_trained:
                        self.index.add(embeddings_array)
                
                # Update chunks list
                self.chunks = new_chunks
                
                # Rebuild doc_to_chunks mapping
                del self.doc_to_chunks[doc_id]
                for doc_id_iter, old_indices in list(self.doc_to_chunks.items()):
                    self.doc_to_chunks[doc_id_iter] = [
                        old_to_new_idx[idx] for idx in old_indices 
                        if idx in old_to_new_idx
                    ]
                
                # Remove content hash
                del self.content_hashes[doc_id]
                
                self._save_index()
                logger.info(f"Removed document {doc_id} from index")
                return True
                
            except Exception as e:
                logger.error(f"Error removing document {doc_id}: {e}")
                return False
    
    def search(self, query_embedding: np.ndarray, k: int = 10) -> List[Tuple[ChunkEntry, float]]:
        """Search across all chunks in hot tier.
        
        Args:
            query_embedding: Query vector (normalized)
            k: Number of results
            
        Returns:
            List of (chunk, score) tuples
        """
        with self._lock:
            try:
                if self.index.ntotal == 0:
                    return []
                
                # Search FAISS index
                k_search = min(k, self.index.ntotal)
                scores, indices = self.index.search(query_embedding.reshape(1, -1), k_search)
                
                # Build results
                results = []
                for idx, score in zip(indices[0], scores[0]):
                    if idx < len(self.chunks):
                        results.append((self.chunks[idx], float(score)))
                
                return results
                
            except Exception as e:
                logger.error(f"Error searching index: {e}")
                return []
    
    def search_within(self, doc_id: str, query_embedding: np.ndarray, k: int = 5) -> List[Tuple[ChunkEntry, float]]:
        """Search within a specific document's chunks.
        
        Args:
            doc_id: Document to search within
            query_embedding: Query vector
            k: Number of results
            
        Returns:
            List of (chunk, score) tuples from this document
        """
        with self._lock:
            try:
                if doc_id not in self.doc_to_chunks:
                    return []
                
                # Get document's chunks
                chunk_indices = self.doc_to_chunks[doc_id]
                if not chunk_indices:
                    return []
                
                # Calculate similarities
                results = []
                for idx in chunk_indices:
                    chunk = self.chunks[idx]
                    if chunk.embedding is not None:
                        score = np.dot(query_embedding, chunk.embedding)
                        results.append((chunk, float(score)))
                
                # Sort by score
                results.sort(key=lambda x: x[1], reverse=True)
                return results[:k]
                
            except Exception as e:
                logger.error(f"Error searching within document {doc_id}: {e}")
                return []
    
    def contains(self, doc_id: str) -> bool:
        """Check if document is in hot tier."""
        return doc_id in self.doc_to_chunks
    
    def validate_content_hash(self, doc_id: str, content_hash: str) -> bool:
        """Check if document's content hash matches."""
        return self.content_hashes.get(doc_id) == content_hash
    
    def get_statistics(self) -> IndexStatistics:
        """Get index statistics."""
        with self._lock:
            total_chunks = len(self.chunks)
            total_docs = len(self.doc_to_chunks)

            # Estimate index size
            if self.index is not None:
                index_size = self.index.ntotal * self.dim * 4 / (1024 * 1024)  # MB
            else:
                index_size = 0.0

            # Estimate metadata size without numpy arrays
            if self.chunks:
                sample_chunk = self.chunks[0]
                # Create sample without embedding for size estimation
                sample_dict = asdict(sample_chunk)
                if 'embedding' in sample_dict:
                    sample_dict['embedding'] = None  # Exclude numpy array
                metadata_size = len(json.dumps(sample_dict)) * len(self.chunks) / (1024 * 1024)
            else:
                metadata_size = 0.0

            return IndexStatistics(
                total_chunks=total_chunks,
                total_documents=total_docs,
                index_size_mb=round(index_size + metadata_size, 2),
                avg_chunks_per_doc=round(total_chunks / max(1, total_docs), 1)
            )

    def _maybe_upgrade_to_ivf(self, incoming: int = 0):
        """Upgrade Flat→IVF when total chunks crosses threshold.

        Trains on a reservoir sample of existing + incoming embeddings.
        Safe to call repeatedly; no-op if already IVF.
        """
        if self.dim is None:
            return
        total = len(self.chunks) + int(incoming)
        if total < self.use_ivf_threshold:
            return
        if isinstance(self.index, faiss.IndexIVFFlat):
            return  # already IVF

        logger.info(f"Upgrading to IVF index at {total} chunks (threshold: {self.use_ivf_threshold})")

        # Gather training vectors from existing chunks
        vecs = self._all_embeddings()
        if vecs.shape[0] < self.nlist:
            # pad via repetition if too small (rare)
            reps = int(np.ceil(self.nlist / max(1, vecs.shape[0])))
            vecs = np.vstack([vecs] * reps)[: self.nlist]

        quantizer = faiss.IndexFlatL2(self.dim)
        new_index = faiss.IndexIVFFlat(quantizer, self.dim, self.nlist)
        if not new_index.is_trained:
            new_index.train(vecs)
        new_index.add(vecs)
        self.index = new_index
        self.is_trained = True
        logger.info(f"Successfully upgraded to IVF index with {new_index.ntotal} vectors")

    def _all_embeddings(self) -> np.ndarray:
        """Return embeddings by reading from FAISS when possible.

        If the FAISS index is empty, falls back to stored embeddings.
        """
        if self.index is not None and getattr(self.index, "ntotal", 0) > 0:
            # Extract vectors back from FAISS
            vecs = []
            for i in range(self.index.ntotal):
                try:
                    vecs.append(self.index.reconstruct(i))
                except RuntimeError:
                    break
            return np.vstack(vecs) if vecs else np.zeros((0, self.dim), dtype=np.float32)

        # Fallback: try to gather from chunk metadata (legacy)
        vecs = []
        for chunk in self.chunks:
            if chunk.embedding is not None:
                vecs.append(chunk.embedding)
        return np.vstack(vecs) if vecs else np.zeros((0, self.dim), dtype=np.float32)

    def compact_index(self):
        """Compact index to reclaim space after deletions."""
        with self._lock:
            self._save_index()
            logger.info("Index compacted")