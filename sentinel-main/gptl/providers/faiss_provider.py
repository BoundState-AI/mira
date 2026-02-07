# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
FAISS-based vector store with content storage.

Combines VectorStoreProvider and ContentProvider for MVP.
Can be split for scale.

Supports both faiss-gpu (local dev) and faiss-cpu (deployment).

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

import numpy as np

from gptl.providers.base import (
    VectorStoreProvider,
    ContentProvider,
    SearchCandidate,
    StoredChunk,
)

__safety_critical__: bool = True

logger = logging.getLogger(__name__)

# Conditional FAISS import (GPU vs CPU)
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    faiss = None  # type: ignore
    logger.warning("FAISS not available. Install faiss-gpu or faiss-cpu.")


class FaissProvider(VectorStoreProvider, ContentProvider):
    """
    Combined FAISS vector store and content provider.

    For MVP, combines retrieval and content access.
    Can be split later for scale.

    Supports both faiss-gpu (local dev) and faiss-cpu (deployment).
    """

    def __init__(
        self,
        index_path: str = "data/sentinel.faiss",
        store_path: str = "data/sentinel.store",
        dimension: int = 1536,
        use_gpu: bool = False,
    ):
        if not FAISS_AVAILABLE:
            raise RuntimeError("FAISS not installed. Run: pip install faiss-cpu")

        self.index_path = Path(index_path)
        self.store_path = Path(store_path)
        self.dimension = dimension
        self.use_gpu = use_gpu

        self.index: Optional[Any] = None  # faiss.Index
        self.chunks: Dict[str, StoredChunk] = {}
        self.id_map: Dict[int, str] = {}  # faiss_idx -> chunk_id

        self._load()

    def _load(self) -> None:
        """Load index and store from disk."""
        if self.index_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            if self.use_gpu:
                try:
                    res = faiss.StandardGpuResources()
                    self.index = faiss.index_cpu_to_gpu(res, 0, self.index)
                    logger.info("FAISS index loaded to GPU")
                except Exception as e:
                    logger.warning(f"GPU not available, using CPU: {e}")
        else:
            # Use Inner Product for cosine similarity (after normalization)
            self.index = faiss.IndexFlatIP(self.dimension)
            if self.use_gpu:
                try:
                    res = faiss.StandardGpuResources()
                    self.index = faiss.index_cpu_to_gpu(res, 0, self.index)
                    logger.info("Created new FAISS index on GPU")
                except Exception as e:
                    logger.warning(f"GPU not available, using CPU: {e}")

        if self.store_path.exists():
            with open(self.store_path, 'rb') as f:
                data = pickle.load(f)
                self.chunks = data.get('chunks', {})
                self.id_map = data.get('id_map', {})
                logger.info(f"Loaded {len(self.chunks)} chunks from store")

    def save(self) -> None:
        """Persist index and store to disk."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert GPU index to CPU for saving if needed
        if self.use_gpu and hasattr(self.index, 'index'):
            cpu_index = faiss.index_gpu_to_cpu(self.index)
            faiss.write_index(cpu_index, str(self.index_path))
        else:
            faiss.write_index(self.index, str(self.index_path))

        with open(self.store_path, 'wb') as f:
            pickle.dump({
                'chunks': self.chunks,
                'id_map': self.id_map,
            }, f)

        logger.info(f"Saved index ({self.index.ntotal} vectors) and store ({len(self.chunks)} chunks)")

    def add_chunks(
        self,
        chunks: List[StoredChunk],
        embeddings: np.ndarray,
    ) -> None:
        """Add chunks with their embeddings."""
        if len(chunks) != embeddings.shape[0]:
            raise ValueError(f"Chunk count ({len(chunks)}) != embedding count ({embeddings.shape[0]})")

        start_idx = self.index.ntotal

        # Normalize for cosine similarity
        embeddings = embeddings.astype('float32')
        faiss.normalize_L2(embeddings)

        self.index.add(embeddings)

        for i, chunk in enumerate(chunks):
            faiss_idx = start_idx + i
            self.id_map[faiss_idx] = chunk.chunk_id
            self.chunks[chunk.chunk_id] = chunk

        logger.info(f"Added {len(chunks)} chunks. Total: {self.index.ntotal}")

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchCandidate]:
        """Search for similar chunks."""
        if self.index.ntotal == 0:
            return []

        query = np.array([query_embedding], dtype='float32')
        faiss.normalize_L2(query)

        # Search more than top_k if we have filters (we'll filter down)
        search_k = top_k * 3 if filters else top_k
        scores, indices = self.index.search(query, min(search_k, self.index.ntotal))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue

            chunk_id = self.id_map.get(int(idx))
            if not chunk_id or chunk_id not in self.chunks:
                continue

            chunk = self.chunks[chunk_id]

            # Apply filters if provided
            if filters:
                skip = False
                for key, value in filters.items():
                    chunk_value = chunk.metadata.get(key)
                    if isinstance(value, list):
                        if chunk_value not in value:
                            skip = True
                            break
                    elif chunk_value != value:
                        skip = True
                        break
                if skip:
                    continue

            results.append(SearchCandidate(
                chunk_id=chunk_id,
                doc_id=chunk.doc_id,
                score=float(score),
                metadata=chunk.metadata,
            ))

            if len(results) >= top_k:
                break

        return results

    def get_content(self, chunk_id: str) -> Optional[str]:
        """Get content for synthesis and semantic checks."""
        chunk = self.chunks.get(chunk_id)
        return chunk.content if chunk else None

    def get_doc_metadata(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a document."""
        for chunk in self.chunks.values():
            if chunk.doc_id == doc_id:
                return chunk.metadata
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        unique_docs = set(c.doc_id for c in self.chunks.values())
        return {
            "total_chunks": self.index.ntotal,
            "dimension": self.dimension,
            "unique_docs": len(unique_docs),
            "use_gpu": self.use_gpu,
            "index_path": str(self.index_path),
            "store_path": str(self.store_path),
        }

    def clear(self) -> None:
        """Clear all data (for testing)."""
        self.index = faiss.IndexFlatIP(self.dimension)
        self.chunks = {}
        self.id_map = {}


__all__ = ["FaissProvider", "FAISS_AVAILABLE"]
