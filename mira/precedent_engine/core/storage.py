#!/usr/bin/env python3
"""
Module: Storage
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
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from mira.precedent_engine.models.config import EngineConfig
    from mira.precedent_engine.models.enriched import EnrichedMUA

from mira.precedent_engine.core.embeddings import EmbeddingModel


class VectorStore:
    """
    Qdrant vector store for MUA precedent retrieval.

    IMPORTANT: Vector similarity is used ONLY to generate a candidate pool.
    It does not contribute directly to tier assignment, equivalence checking,
    or adequacy scoring. The vector score from Qdrant is DISCARDED after
    candidate retrieval. All downstream scoring is computed deterministically
    by PrecedentEngine.

    This class provides async interface via thread pool executor for
    non-blocking operation.
    """

    def __init__(
        self,
        config: "EngineConfig",
        embedding_model: EmbeddingModel | None = None,
        max_workers: int = 4,
    ) -> None:
        """
        Initialize the vector store.

        Args:
            config: Engine configuration
            embedding_model: Optional pre-initialized embedding model
            max_workers: Thread pool size for async operations
        """
        self.config = config
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._client = None
        self._embedding_model = embedding_model or EmbeddingModel(
            model_name=config.embed_model_name,
            embed_dim=config.embed_dim,
        )
        # In-memory cache of EnrichedMUA objects by ID
        self._mua_cache: dict[str, "EnrichedMUA"] = {}

    def _get_client(self):
        """Lazy-load the Qdrant client."""
        if self._client is None:
            from qdrant_client import QdrantClient

            # Use local file-based storage
            path = Path(self.config.qdrant_path)
            path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(path))

        return self._client

    def ensure_collection_sync(self) -> None:
        """
        Ensure the collection exists with proper configuration.

        Creates the collection if it doesn't exist.
        """
        from qdrant_client.models import Distance, VectorParams

        client = self._get_client()

        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.config.collection_name not in collection_names:
            client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.embed_dim,
                    distance=Distance.COSINE,
                ),
            )

    async def ensure_collection(self) -> None:
        """Async wrapper for ensure_collection_sync."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self.ensure_collection_sync)

    def upsert_sync(
        self,
        muas: list["EnrichedMUA"],
        embeddings: np.ndarray | None = None,
    ) -> int:
        """
        Synchronously upsert MUAs into the vector store.

        Args:
            muas: List of EnrichedMUA records to insert
            embeddings: Optional pre-computed embeddings (n_muas x embed_dim)

        Returns:
            Number of records upserted
        """
        from qdrant_client.models import PointStruct

        if not muas:
            return 0

        # Compute embeddings if not provided
        if embeddings is None:
            embeddings = self._embedding_model.embed_muas_sync(muas)

        client = self._get_client()

        points = []
        for i, mua in enumerate(muas):
            # Generate unique ID
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, mua.contract_id + str(mua.source_material_index)))

            # Store in cache
            self._mua_cache[point_id] = mua

            # Build payload with key fields for filtering
            payload = {
                "contract_id": mua.contract_id,
                "material_name": mua.material_name,
                "material_key": mua.material_key,
                "media": mua.media,
                "o2_pct": mua.o2_pct,
                "location_class": mua.location_class,
                "temp_max_f": mua.temp_max_f,
                "temp_min_f": mua.temp_min_f,
                "pressure_max_psia": mua.pressure_max_psia,
                "category": mua.category,
                "is_rejected": mua.is_rejected,
                "is_usable_precedent": mua.is_usable_precedent,
                "deviation_types": [d.value for d in mua.deviation_types],
                "program": mua.program,
                "program_family": mua.program_family.value,
                "precedent_family": mua.precedent_family,
                "source_material_index": mua.source_material_index,
                # Supersession tracking
                "is_superseded": mua.is_superseded,
                "superseded_by": mua.superseded_by,
                "supersedes": mua.supersedes,
                "revision_number": mua.revision_number,
            }

            points.append(
                PointStruct(
                    id=point_id,
                    vector=embeddings[i].tolist(),
                    payload=payload,
                )
            )

        # Batch upsert
        client.upsert(
            collection_name=self.config.collection_name,
            points=points,
        )

        return len(points)

    async def upsert(
        self,
        muas: list["EnrichedMUA"],
        embeddings: np.ndarray | None = None,
    ) -> int:
        """
        Asynchronously upsert MUAs into the vector store.

        Args:
            muas: List of EnrichedMUA records to insert
            embeddings: Optional pre-computed embeddings

        Returns:
            Number of records upserted
        """
        # Compute embeddings async if needed
        if embeddings is None:
            embeddings = await self._embedding_model.embed_muas(muas)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self.upsert_sync,
            muas,
            embeddings,
        )

    def search_sync(
        self,
        query: "EnrichedMUA",
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list["EnrichedMUA"]:
        """
        Synchronously search for candidate MUAs.

        IMPORTANT: Vector similarity scores are DISCARDED after this function.
        Only the EnrichedMUA objects are returned for downstream processing
        by PrecedentEngine.

        Args:
            query: Query MUA to find precedents for
            top_k: Maximum number of candidates to return
            score_threshold: Minimum similarity score (0-1)

        Returns:
            List of candidate EnrichedMUA objects (scores discarded)
        """
        top_k = top_k or self.config.top_k_initial
        score_threshold = score_threshold or self.config.score_threshold_initial

        client = self._get_client()

        # Embed the query
        query_embedding = self._embedding_model.embed_mua_sync(query)

        # Search
        results = client.search(
            collection_name=self.config.collection_name,
            query_vector=query_embedding.tolist(),
            limit=top_k,
            score_threshold=score_threshold,
        )

        # Convert results to EnrichedMUA objects
        # IMPORTANT: Vector scores are DISCARDED here
        candidates = []
        for hit in results:
            point_id = str(hit.id)

            # Try to get from cache first
            if point_id in self._mua_cache:
                candidates.append(self._mua_cache[point_id])
            else:
                # Reconstruct from payload (limited fields)
                # In production, this should load from full storage
                candidates.append(self._reconstruct_mua_from_payload(hit.payload))

        return candidates

    async def search(
        self,
        query: "EnrichedMUA",
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list["EnrichedMUA"]:
        """
        Asynchronously search for candidate MUAs.

        IMPORTANT: Vector similarity scores are DISCARDED after retrieval.
        All downstream scoring is computed deterministically by PrecedentEngine.

        Args:
            query: Query MUA to find precedents for
            top_k: Maximum number of candidates to return
            score_threshold: Minimum similarity score (0-1)

        Returns:
            List of candidate EnrichedMUA objects (scores discarded)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self.search_sync,
            query,
            top_k,
            score_threshold,
        )

    def _reconstruct_mua_from_payload(self, payload: dict) -> "EnrichedMUA":
        """
        Reconstruct an EnrichedMUA from Qdrant payload.

        Note: This is a partial reconstruction for candidate pool generation.
        Full MUA data should be loaded from persistent storage in production.
        """
        from mira.precedent_engine.models.enriched import EnrichedMUA
        from mira.precedent_engine.models.enums import DeviationType, ProgramFamily

        return EnrichedMUA(
            contract_id=payload.get("contract_id", ""),
            source_file="",  # Not stored in payload
            material_name=payload.get("material_name", ""),
            material_key=payload.get("material_key"),
            media=payload.get("media"),
            o2_pct=payload.get("o2_pct", 21.0),
            location_class=payload.get("location_class", "non_habitable"),
            temp_max_f=payload.get("temp_max_f"),
            temp_min_f=payload.get("temp_min_f", 70.0),
            pressure_max_psia=payload.get("pressure_max_psia"),
            category=payload.get("category"),
            is_rejected=payload.get("is_rejected", False),
            is_usable_precedent=payload.get("is_usable_precedent", True),
            deviation_types=[
                DeviationType(d) for d in payload.get("deviation_types", [])
            ],
            program=payload.get("program"),
            program_family=ProgramFamily(payload.get("program_family", "other")),
            precedent_family=payload.get("precedent_family"),
            source_material_index=payload.get("source_material_index", 0),
            # Supersession tracking
            is_superseded=payload.get("is_superseded", False),
            superseded_by=payload.get("superseded_by"),
            supersedes=payload.get("supersedes", []),
            revision_number=payload.get("revision_number"),
        )

    def get_collection_count_sync(self) -> int:
        """Get the number of points in the collection."""
        client = self._get_client()
        info = client.get_collection(self.config.collection_name)
        return info.points_count

    async def get_collection_count(self) -> int:
        """Async wrapper for get_collection_count_sync."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self.get_collection_count_sync)

    def delete_collection_sync(self) -> None:
        """Delete the collection."""
        client = self._get_client()
        client.delete_collection(self.config.collection_name)

    async def delete_collection(self) -> None:
        """Async wrapper for delete_collection_sync."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self.delete_collection_sync)

    def close(self) -> None:
        """Shutdown resources."""
        self._executor.shutdown(wait=True)
        if hasattr(self._embedding_model, "close"):
            self._embedding_model.close()

    def __enter__(self) -> "VectorStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
