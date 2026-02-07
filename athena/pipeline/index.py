#!/usr/bin/env python3
"""
Module: Index
Purpose: ATHENA Document Indexing Pipeline.

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

import hashlib
import logging
from datetime import datetime
from typing import Any

from athena.config import AthenaConfig
from athena.models.document import Document, ProcessingEvent
from athena.models.enums import DocumentStatus

logger = logging.getLogger(__name__)


class IndexingStage:
    """Index documents in Qdrant for semantic search.

    Collections are profile-keyed to include embedding model in name.
    This ensures cache invalidation when embedding model changes.
    """

    def __init__(
        self,
        config: AthenaConfig,
        qdrant_url: str | None = None,
    ):
        """Initialize indexing stage.

        Args:
            config: ATHENA configuration
            qdrant_url: Qdrant server URL
        """
        self.config = config
        self.qdrant_url = qdrant_url or config.qdrant_url
        self._client = None
        self._embed_model = None

    @property
    def client(self):
        """Lazy-load Qdrant client."""
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(url=self.qdrant_url)
        return self._client

    @property
    def embed_model(self):
        """Lazy-load embedding model."""
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer
            self._embed_model = SentenceTransformer(self.config.embedding_model)
        return self._embed_model

    @property
    def collection_name(self) -> str:
        """Get collection name with embedding model suffix."""
        # Hash the model name for a short suffix
        model_hash = hashlib.md5(self.config.embedding_model.encode()).hexdigest()[:8]
        return f"{self.config.qdrant_collection}_{model_hash}"

    async def ensure_collection(self) -> None:
        """Ensure collection exists with correct configuration."""
        from qdrant_client.models import Distance, VectorParams

        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name not in collection_names:
            # Get embedding dimension from model
            test_embedding = self.embed_model.encode("test")
            vector_size = len(test_embedding)

            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                f"Created collection {self.collection_name} "
                f"with dimension {vector_size}"
            )

    async def index_document(
        self,
        doc: Document,
        db=None,
    ) -> Document:
        """Index a document for semantic search.

        Args:
            doc: Document to index
            db: Optional database client for status updates

        Returns:
            Updated document
        """
        from qdrant_client.models import PointStruct

        start_time = datetime.utcnow()

        # Ensure collection exists
        await self.ensure_collection()

        # Build text for embedding
        text_parts = []

        # Add document type
        if doc.triage_result:
            text_parts.append(f"Type: {doc.triage_result.document_type}")
            if doc.triage_result.document_subtype:
                text_parts.append(f"Subtype: {doc.triage_result.document_subtype}")

        # Add extracted fields
        if doc.extraction_result:
            for field_name, field_value in doc.extraction_result.fields.items():
                if field_value.value:
                    text_parts.append(f"{field_name}: {field_value.value}")

        # Add entities from triage
        if doc.triage_result and doc.triage_result.entities:
            entities = doc.triage_result.entities
            for entity_list in [
                entities.equipment,
                entities.people,
                entities.locations,
                entities.organizations,
                entities.references,
            ]:
                text_parts.extend(entity_list)

        # Combine and embed
        text = " | ".join(text_parts) if text_parts else doc.source_file
        embedding = self.embed_model.encode(text).tolist()

        # Build payload
        payload = {
            "document_id": str(doc.document_id),
            "tenant_id": doc.tenant_id,
            "batch_id": doc.batch_id,
            "source_file": doc.source_file,
            "page_range": list(doc.page_range),
            "document_type": doc.triage_result.document_type if doc.triage_result else None,
            "date_detected": doc.triage_result.date_detected if doc.triage_result else None,
            "quality_score": doc.quality_score,
            "created_at": doc.created_at.isoformat(),
        }

        # Add to Qdrant
        point = PointStruct(
            id=str(doc.document_id),
            vector=embedding,
            payload=payload,
        )

        self.client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )

        # Update document
        doc.embedding = embedding
        doc.embedding_model = self.config.embedding_model
        doc.status = DocumentStatus.INDEXED
        doc.updated_at = datetime.utcnow()

        # Create processing event
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        event = ProcessingEvent(
            stage="indexing",
            status="completed",
            duration_ms=duration_ms,
            details={
                "collection": self.collection_name,
                "text_length": len(text),
            },
        )
        doc.processing_log.append(event)

        if db:
            await db.update_document(doc)

        logger.debug(f"Indexed document {doc.document_id}")
        return doc

    async def search(
        self,
        query: str,
        tenant_id: str,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Search documents semantically.

        Args:
            query: Search query
            tenant_id: Tenant ID for isolation
            limit: Maximum results
            filters: Optional additional filters

        Returns:
            List of search results
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        # Embed query
        query_embedding = self.embed_model.encode(query).tolist()

        # Build filter
        must_conditions = [
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))
        ]

        if filters:
            for key, value in filters.items():
                must_conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )

        search_filter = Filter(must=must_conditions)

        # Search
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            query_filter=search_filter,
        )

        return [
            {
                "document_id": hit.payload.get("document_id"),
                "score": hit.score,
                "source_file": hit.payload.get("source_file"),
                "document_type": hit.payload.get("document_type"),
                "date_detected": hit.payload.get("date_detected"),
                "page_range": hit.payload.get("page_range"),
                "batch_id": hit.payload.get("batch_id"),
            }
            for hit in results
        ]

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document from the index.

        Args:
            document_id: Document ID to delete

        Returns:
            True if deleted
        """
        from qdrant_client.models import PointIdsList

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[document_id]),
        )
        return True

    async def get_collection_stats(self) -> dict:
        """Get collection statistics.

        Returns:
            Dictionary with collection stats
        """
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "collection_name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value,
            }
        except Exception as e:
            return {
                "collection_name": self.collection_name,
                "error": str(e),
            }
