#!/usr/bin/env python3
"""
Module: Retriever
Purpose: Simple retrieval module with embedding and keyword fallback.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Safety Critical: False
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence
import re
import logging
import math

try:  # numpy is optional; code falls back to pure Python math
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

from .hierarchical_chunker import Chunk
from .keyword_gate import KeywordGate

logger = logging.getLogger(__name__)

try:  # pragma: no cover - heavy dependency, optional for tests
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover
    SentenceTransformer = None  # type: ignore


@dataclass
class SearchResult:
    """Container for a ranked chunk.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

    chunk: Chunk
    emb_score: float
    kw_score: Optional[float] = None


class Retriever:
    """Embedding‑based retriever with keyword fallback.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

    def __init__(
        self,
        embedding_model: str | None = "BAAI/bge-base-en-v1.5",
        embedding_fn: Optional[Callable[[List[str]], Sequence[Sequence[float]]]] = None,
        keyword_gate: Optional[KeywordGate] = None,
    ) -> None:
        """Create a new retriever.

        Parameters
        ----------
        embedding_model:
            Name of the sentence-transformers model to load. Ignored if
            ``embedding_fn`` is provided.
        embedding_fn:
            Optional custom embedding function returning ``np.ndarray`` with
            shape ``(len(texts), dim)``. Useful for tests where a heavy model
            is undesirable.
        keyword_gate:
            Optional ``KeywordGate`` instance applied after retrieval.
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

        self.keyword_gate = keyword_gate

        if embedding_fn is not None:
            self._embed = embedding_fn
        else:
            if SentenceTransformer is None:
                raise ImportError(
                    "sentence-transformers is required when no embedding_fn is provided"
                )
            logger.info("Loading embedding model %s", embedding_model)
            self.model = SentenceTransformer(embedding_model)  # pragma: no cover
            self._embed = self.model.encode  # pragma: no cover

        self._chunks: List[Chunk] = []
        self._embeddings: Optional[List[List[float]]] = None

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------
    def embed_chunks(self, chunks: List[Chunk]) -> List[List[float]]:
        """Embed and index a list of chunks.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

        texts = [c.text for c in chunks]
        raw_embeddings = self._embed(texts)
        
        # Convert to list of lists and normalize
        if np is not None and hasattr(raw_embeddings, "tolist"):
            embeddings = []
            for vec in raw_embeddings:
                # L2 normalize
                vec_array = np.array(vec)
                norm = np.linalg.norm(vec_array)
                if norm > 0:
                    vec_array = vec_array / norm
                embeddings.append(vec_array.tolist())
        else:
            embeddings = []
            for vec in raw_embeddings:
                # Pure Python L2 normalization
                vec_list = list(map(float, vec))
                norm = math.sqrt(sum(x*x for x in vec_list))
                if norm > 0:
                    vec_list = [x/norm for x in vec_list]
                embeddings.append(vec_list)

        self._chunks = chunks
        self._embeddings = embeddings
        logger.info("Indexed %d chunks", len(chunks))
        return embeddings

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def search(self, query: str, k: int = 5) -> List[SearchResult]:
        """Return top ``k`` relevant chunks for ``query``.

        The method first performs embedding similarity search. If the best
        score is low or the query looks lexical (contains digits or explicit
        section patterns), a simple keyword search is used instead.
        

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

        if self._embeddings is None:
            raise ValueError("No embeddings available. Call embed_chunks first")

        raw_query = self._embed([query])
        
        # Normalize query embedding
        if np is not None and hasattr(raw_query, "tolist"):
            query_vec = raw_query[0]
            norm = np.linalg.norm(query_vec)
            if norm > 0:
                query_vec = query_vec / norm
            query_vec = query_vec.tolist()
        else:
            query_vec = list(map(float, raw_query[0]))
            norm = math.sqrt(sum(x*x for x in query_vec))
            if norm > 0:
                query_vec = [x/norm for x in query_vec]

        sims: List[float] = []
        for emb in self._embeddings:
            sims.append(self._cosine_similarity(emb, query_vec))

        ranked = [SearchResult(self._chunks[i], float(score)) for i, score in enumerate(sims)]
        ranked.sort(key=lambda r: r.emb_score, reverse=True)

        top = ranked[:k]
        max_score = top[0].emb_score if top else 0.0

        # Fixed regex pattern - matches document IDs like POL1901, section numbers like 3.1.9
        lexical_pattern = r'(?:\b[A-Z]+\d+\b|\b\d+(?:\.\d+)*\b)'
        lexical = max_score < 0.3 or re.search(lexical_pattern, query)
        
        if lexical:
            logger.info("Using keyword fallback for query: %s (max_score: %.3f)", query, max_score)
            top = self._keyword_search(query, k)

        if self.keyword_gate and top:
            gate_input = [{"text": r.chunk.text, "score": r.emb_score, "chunk": r.chunk} for r in top]
            gated = self.keyword_gate.apply_gate(query, gate_input)
            top = [SearchResult(r["chunk"], r.get("score", 0.0)) for r in gated][:k]

        return top

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _keyword_search(self, query: str, k: int) -> List[SearchResult]:
        """Very small lexical fallback used when embeddings are unreliable.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""

        q = query.lower()
        terms = q.split()
        results: List[SearchResult] = []

        for chunk in self._chunks:
            text = chunk.text.lower()
            if q in text or any(t in text for t in terms):
                kw_score = sum(text.count(t) for t in terms)
                results.append(SearchResult(chunk, emb_score=0.0, kw_score=float(kw_score)))

        results.sort(key=lambda r: r.kw_score or 0.0, reverse=True)
        return results[:k]

    def _cosine_similarity(self, v1: Sequence[float], v2: Sequence[float]) -> float:
        """Compute cosine similarity between normalized vectors.

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
        # Since vectors are already normalized, cosine similarity is just dot product
        dot = sum(a * b for a, b in zip(v1, v2))
        return dot


__all__ = ["Retriever", "SearchResult"]