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
Provider protocols for SENTINEL.

Three distinct capabilities - do not conflate:
1. VectorStoreProvider: retrieval (vector search)
2. ContentProvider: content access (text retrieval)
3. FeatureCache: feature access (DocFeatures)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

from typing import Protocol, List, Dict, Any, Optional, runtime_checkable
from dataclasses import dataclass, field

from gptl.schema import DocFeatures

__safety_critical__: bool = True


@dataclass
class SearchCandidate:
    """Result from vector search."""
    chunk_id: str
    doc_id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredChunk:
    """Chunk stored in the provider."""
    chunk_id: str
    doc_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


@runtime_checkable
class VectorStoreProvider(Protocol):
    """Protocol for vector store implementations."""

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchCandidate]:
        """Search for similar documents."""
        ...

    def add_chunks(
        self,
        chunks: List[StoredChunk],
        embeddings: Any,  # np.ndarray
    ) -> None:
        """Add chunks with their embeddings."""
        ...

    def get_stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        ...

    def save(self) -> None:
        """Persist index to storage."""
        ...


@runtime_checkable
class ContentProvider(Protocol):
    """Protocol for content retrieval."""

    def get_content(self, chunk_id: str) -> Optional[str]:
        """Get text content for a chunk."""
        ...

    def get_doc_metadata(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get document metadata."""
        ...


@runtime_checkable
class FeatureCache(Protocol):
    """Protocol for DocFeatures caching."""

    def get_features(self, chunk_id: str) -> Optional[DocFeatures]:
        """Get pre-computed features for a chunk."""
        ...

    def put_features(self, chunk_id: str, features: DocFeatures) -> None:
        """Store features for a chunk."""
        ...

    def bulk_get(self, chunk_ids: List[str]) -> Dict[str, DocFeatures]:
        """Bulk retrieve features."""
        ...


__all__ = [
    "SearchCandidate",
    "StoredChunk",
    "VectorStoreProvider",
    "ContentProvider",
    "FeatureCache",
]
