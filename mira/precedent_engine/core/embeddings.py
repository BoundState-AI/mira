#!/usr/bin/env python3
"""
Module: Embeddings
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import numpy as np
import uuid

if TYPE_CHECKING:
    from mira.precedent_engine.models.enriched import EnrichedMUA


class EmbeddingModel:
    """
    Sentence transformer wrapper for MUA embeddings.

    IMPORTANT: Vector similarity is used ONLY to generate a candidate pool.
    It does not contribute directly to tier assignment, equivalence checking,
    or adequacy scoring. The vector score is DISCARDED after candidate retrieval.

    This class wraps sentence-transformers and provides async interface
    via thread pool executor for non-blocking operation.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L12-v2",
        embed_dim: int = 384,
        max_workers: int = 4,
    ) -> None:
        """
        Initialize the embedding model.

        Args:
            model_name: Name of the sentence-transformers model
            embed_dim: Expected embedding dimension
            max_workers: Thread pool size for async operations
        """
        self.model_name = model_name
        self.embed_dim = embed_dim
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._model = None

    def _load_model(self) -> None:
        """Lazy-load the sentence transformer model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)

    def _build_embed_text(self, mua: "EnrichedMUA") -> str:
        """
        Build the text representation of an MUA for embedding.

        Combines key fields into a single text string that captures
        the semantic essence of the MUA for similarity search.
        """
        parts = []

        # Material information
        if mua.material_name:
            parts.append(f"Material: {mua.material_name}")
        if mua.specification:
            parts.append(f"Spec: {mua.specification}")

        # Environment
        env_parts = []
        if mua.media:
            env_parts.append(mua.media)
        if mua.temp_max_f is not None:
            env_parts.append(f"{mua.temp_max_f}°F max")
        if mua.pressure_max_psia is not None:
            env_parts.append(f"{mua.pressure_max_psia} psia")
        if mua.o2_pct != 21.0:
            env_parts.append(f"{mua.o2_pct}% O2")
        if env_parts:
            parts.append(f"Environment: {', '.join(env_parts)}")

        # Deviation types
        if mua.deviation_types:
            dev_str = ", ".join(d.value for d in mua.deviation_types)
            parts.append(f"Deviations: {dev_str}")

        # Issue text (truncated)
        if mua.issue_text:
            issue = mua.issue_text[:500]
            parts.append(f"Issue: {issue}")

        # Application text (truncated)
        if mua.application_text:
            app = mua.application_text[:300]
            parts.append(f"Application: {app}")

        return " | ".join(parts)

    def embed_sync(self, text: str) -> np.ndarray:
        """
        Synchronously embed a single text string.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as numpy array
        """
        self._load_model()
        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)

    def embed_batch_sync(self, texts: list[str]) -> np.ndarray:
        """
        Synchronously embed a batch of text strings.

        Args:
            texts: List of texts to embed

        Returns:
            2D numpy array of embeddings (n_texts x embed_dim)
        """
        self._load_model()
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.astype(np.float32)

    def embed_mua_sync(self, mua: "EnrichedMUA") -> np.ndarray:
        """
        Synchronously embed an EnrichedMUA record.

        Args:
            mua: EnrichedMUA to embed

        Returns:
            Embedding vector as numpy array
        """
        text = self._build_embed_text(mua)
        return self.embed_sync(text)

    def embed_muas_sync(self, muas: list["EnrichedMUA"]) -> np.ndarray:
        """
        Synchronously embed a batch of EnrichedMUA records.

        Args:
            muas: List of EnrichedMUA records

        Returns:
            2D numpy array of embeddings
        """
        texts = [self._build_embed_text(mua) for mua in muas]
        return self.embed_batch_sync(texts)

    async def embed(self, text: str) -> np.ndarray:
        """
        Asynchronously embed a single text string.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as numpy array
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self.embed_sync, text)

    async def embed_batch(self, texts: list[str]) -> np.ndarray:
        """
        Asynchronously embed a batch of text strings.

        Args:
            texts: List of texts to embed

        Returns:
            2D numpy array of embeddings
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self.embed_batch_sync, texts)

    async def embed_mua(self, mua: "EnrichedMUA") -> np.ndarray:
        """
        Asynchronously embed an EnrichedMUA record.

        Args:
            mua: EnrichedMUA to embed

        Returns:
            Embedding vector as numpy array
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self.embed_mua_sync, mua)

    async def embed_muas(self, muas: list["EnrichedMUA"]) -> np.ndarray:
        """
        Asynchronously embed a batch of EnrichedMUA records.

        Args:
            muas: List of EnrichedMUA records

        Returns:
            2D numpy array of embeddings
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self.embed_muas_sync, muas)

    def close(self) -> None:
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=True)

    def __enter__(self) -> "EmbeddingModel":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.close()
