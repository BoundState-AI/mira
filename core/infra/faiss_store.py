#!/usr/bin/env python3
"""
Module: Faiss Store
Purpose: FAISS Document Store Implementation

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

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .document_store import DocumentStore, DocumentHit

LOGGER = logging.getLogger(__name__)

# Lazy imports for optional dependencies
_faiss = None
_SentenceTransformer = None


def _ensure_faiss():
    """Lazy import FAISS and sentence-transformers."""
    global _faiss, _SentenceTransformer
    if _faiss is None:
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
            _faiss = faiss
            _SentenceTransformer = SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "FAISS and sentence-transformers required. "
                "Install with: pip install faiss-cpu sentence-transformers"
            ) from e
    return _faiss, _SentenceTransformer


class FaissDocumentStore(DocumentStore):
    """FAISS-backed document store with structured metadata filters.

    This is a CLEAN implementation that:
    - Loads FAISS index + metadata from a directory
    - Applies filters on validated metadata fields
    - Returns DocumentHit objects
    """

    def __init__(
        self,
        index_dir: Path,
        model_name: str = "all-mpnet-base-v2",
    ) -> None:
        """Initialize FAISS document store.

        Args:
            index_dir: Directory containing index.faiss and metadata.json
            model_name: Sentence transformer model for query embedding
        """
        self._index_dir = Path(index_dir)
        self._model_name = model_name
        self._index = None
        self._metadata: List[Dict[str, Any]] = []
        self._model = None
        self._loaded = False

    def _load(self) -> None:
        """Lazy load the FAISS index and metadata."""
        if self._loaded:
            return

        faiss, SentenceTransformer = _ensure_faiss()

        # Load FAISS index
        index_file = self._index_dir / "index.faiss"
        if not index_file.exists():
            # Try alternate name
            index_file = self._index_dir / "maptis_faiss.index"

        if index_file.exists():
            self._index = faiss.read_index(str(index_file))
            LOGGER.info(f"Loaded FAISS index with {self._index.ntotal} vectors")
        else:
            LOGGER.warning(f"FAISS index not found in {self._index_dir}")
            self._loaded = True
            return

        # Load metadata
        metadata_file = self._index_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Handle wrapped format: {"metadata": [...]}
            if isinstance(data, dict) and "metadata" in data:
                self._metadata = data["metadata"]
            elif isinstance(data, list):
                self._metadata = data
            else:
                self._metadata = []

            LOGGER.info(f"Loaded {len(self._metadata)} metadata entries")
        else:
            LOGGER.warning(f"Metadata not found: {metadata_file}")

        # Load embedding model
        self._model = SentenceTransformer(self._model_name)
        LOGGER.info(f"Loaded embedding model: {self._model_name}")

        self._loaded = True

    def search(
        self,
        query: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> Iterable[DocumentHit]:
        """Search documents using FAISS similarity.

        Args:
            query: The search query string
            filters: Structured filters (material_key, environment, etc.)
            top_k: Maximum results to return

        Returns:
            DocumentHit objects ordered by relevance
        """
        self._load()

        if self._index is None or self._model is None:
            LOGGER.warning("FAISS store not properly loaded")
            return []

        # Embed the query
        query_embedding = self._model.encode([query], convert_to_numpy=True)

        # Search FAISS - get more results to allow for filtering
        search_k = min(top_k * 3, self._index.ntotal)
        distances, indices = self._index.search(query_embedding, search_k)

        results: List[DocumentHit] = []
        filters = filters or {}

        # First pass: collect all candidate results with semantic scores
        candidates: List[tuple] = []  # (idx, dist, meta, keyword_boost)

        query_lower = query.lower().strip()
        query_terms = query_lower.split()

        for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx < 0 or idx >= len(self._metadata):
                continue

            meta = self._metadata[idx]

            # Apply structured filters
            if not self._matches_filters(meta, filters):
                continue

            # Calculate keyword match boost for exact/substring matches
            keyword_boost = 0.0
            designation = str(meta.get("designation", "")).lower()
            name = str(meta.get("name", "")).lower()
            material_code = str(meta.get("material_code", "")).lower()
            material_key = str(meta.get("material_key", "")).lower()

            # Check for exact or substring keyword matches
            for term in query_terms:
                if len(term) >= 3:  # Only boost for meaningful terms
                    # Exact match in designation is huge boost
                    if term in designation:
                        keyword_boost += 0.5
                    if term in name:
                        keyword_boost += 0.3
                    if term in material_code:
                        keyword_boost += 0.4
                    if term in material_key:
                        keyword_boost += 0.3

            candidates.append((idx, dist, meta, keyword_boost))

        # Sort by combined score: keyword boost first, then semantic similarity
        # Higher keyword_boost is better, lower distance is better
        candidates.sort(key=lambda x: (-x[3], x[1]))

        for idx, dist, meta, keyword_boost in candidates:
            # Build DocumentHit - use FAISS index (idx) for unique doc_id
            base_id = str(meta.get("material_key", meta.get("material_id", "unk")))
            doc_id = f"{base_id}-{idx}"  # Unique per FAISS index
            title = meta.get("designation", meta.get("name", f"Document {idx}"))
            snippet = self._build_snippet(meta, query)
            # Combine semantic relevance (0-1) with keyword matches (0-unbounded).
            # WHY 1/(1+dist): Sigmoid-like transform — dist=0 → score=1, dist→∞ → 0.
            # WHY keyword_boost * 0.3: Keyword matches contribute up to 30% of final
            # score. Tuned empirically — higher weight causes single exact-match
            # keywords to dominate over strong semantic similarity.
            semantic_score = float(1.0 / (1.0 + dist))
            combined_score = min(1.0, semantic_score + keyword_boost * 0.3)

            results.append(DocumentHit(
                doc_id=doc_id,
                title=title,
                snippet=snippet,
                score=combined_score,
                metadata=meta,
            ))

            if len(results) >= top_k:
                break

        return results

    def _matches_filters(self, meta: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if metadata matches all filters.

        Filters are applied on structured fields only.
        Missing values in metadata are treated as non-matching.
        """
        for field, expected in filters.items():
            if expected is None:
                continue

            actual = meta.get(field)
            if actual is None:
                # Field not present - doesn't match
                return False

            # Case-insensitive string comparison
            if isinstance(expected, str) and isinstance(actual, str):
                if expected.lower() != actual.lower():
                    return False
            elif actual != expected:
                return False

        return True

    def _build_snippet(self, meta: Dict[str, Any], query: str) -> str:
        """Build a snippet from metadata for display."""
        parts = []

        designation = meta.get("designation", "")
        if designation:
            parts.append(designation)

        material_type = meta.get("material_type", "")
        if material_type:
            parts.append(f"Type: {material_type}")

        test_class = meta.get("test_class", "")
        if test_class:
            parts.append(f"Test: {test_class}")

        rating = meta.get("rating", "")
        if rating:
            parts.append(f"Rating: {rating}")

        return " | ".join(parts) if parts else f"Material record {meta.get('material_key', 'unknown')}"


__all__ = ["FaissDocumentStore"]
