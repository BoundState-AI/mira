#!/usr/bin/env python3
"""
Module: Reconcile
Purpose: ATHENA Conservative Entity Reconciliation.

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

import logging
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, Field

from athena.models.entity import Entity, EntityLink, EntityMention, EntityRelation
from athena.models.enums import EntityLinkStatus, EntityType
from athena.models.review import EntityReviewItem

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


class ReconciliationConfig(BaseModel):
    """Configuration for entity reconciliation."""

    embedding_model: str = "all-MiniLM-L12-v2"

    # Match thresholds by entity type
    match_thresholds: dict[EntityType, float] = Field(
        default_factory=lambda: {
            EntityType.EQUIPMENT: 1.0,      # Exact only
            EntityType.REFERENCE: 1.0,      # Exact only
            EntityType.MATERIAL: 1.0,       # Exact only
            EntityType.PERSON: 0.90,        # Fuzzy allowed
            EntityType.ORGANIZATION: 0.85,  # Fuzzy allowed
            EntityType.LOCATION: 0.85,      # Fuzzy allowed
            EntityType.DATE: 1.0,           # Exact only
            EntityType.EVENT: 0.80,         # More fuzzy
            EntityType.PROCEDURE: 0.85,
        }
    )

    # Auto-approve thresholds (None = never auto-approve)
    auto_approve_thresholds: dict[EntityType, float | None] = Field(
        default_factory=lambda: {
            EntityType.EQUIPMENT: None,     # NEVER auto-approve
            EntityType.REFERENCE: None,     # NEVER
            EntityType.MATERIAL: None,      # NEVER
            EntityType.PERSON: 0.95,
            EntityType.ORGANIZATION: 0.95,
            EntityType.LOCATION: 0.95,
            EntityType.DATE: 0.99,
            EntityType.EVENT: 0.90,
            EntityType.PROCEDURE: 0.90,
        }
    )


class ConservativeReconciler:
    """Conservative entity reconciliation with human review.

    Key principle: Propose links, don't auto-merge high-impact entities.
    Equipment IDs, references, and materials NEVER auto-merge.
    """

    def __init__(self, config: ReconciliationConfig | None = None):
        """Initialize reconciler.

        Args:
            config: Reconciliation configuration
        """
        self.config = config or ReconciliationConfig()
        self._embed_model = None

    @property
    def embed_model(self):
        """Lazy-load embedding model."""
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer
            self._embed_model = SentenceTransformer(self.config.embedding_model)
        return self._embed_model

    async def reconcile_entities(
        self,
        mentions: list[EntityMention],
    ) -> list[EntityLink]:
        """Propose entity links - NO automatic merging for critical types.

        Args:
            mentions: List of entity mentions

        Returns:
            List of proposed EntityLinks
        """
        proposed: list[EntityLink] = []

        # Group by entity type
        by_type: dict[EntityType, list[EntityMention]] = defaultdict(list)
        for m in mentions:
            by_type[m.entity_type].append(m)

        for entity_type, type_mentions in by_type.items():
            if len(type_mentions) < 2:
                continue

            threshold = self.config.match_thresholds.get(entity_type, 0.9)
            auto_threshold = self.config.auto_approve_thresholds.get(entity_type)

            # Find matches
            matches = self._find_matches(type_mentions, threshold)

            for group, confidence, evidence_type in matches:
                # Determine status based on auto-approve threshold
                if auto_threshold and confidence >= auto_threshold:
                    status = EntityLinkStatus.AUTO_APPROVED
                else:
                    status = EntityLinkStatus.PROPOSED

                link = EntityLink(
                    mention_ids=[m.mention_id for m in group],
                    confidence=confidence,
                    evidence_type=evidence_type,
                    evidence_details={
                        "entity_type": entity_type.value,
                        "texts": [m.text for m in group],
                        "normalized_texts": [m.normalized_text for m in group],
                    },
                    status=status,
                )
                proposed.append(link)

                logger.debug(
                    f"Proposed {evidence_type} link for {entity_type.value}: "
                    f"{len(group)} mentions, confidence={confidence:.3f}, status={status.value}"
                )

        return proposed

    def _find_matches(
        self,
        mentions: list[EntityMention],
        threshold: float,
    ) -> list[tuple[list[EntityMention], float, str]]:
        """Find matching mentions.

        Args:
            mentions: Mentions to match
            threshold: Similarity threshold

        Returns:
            List of (group, confidence, evidence_type) tuples
        """
        matches = []

        if threshold >= 1.0:
            # Exact matching only
            by_norm = defaultdict(list)
            for m in mentions:
                by_norm[m.normalized_text.lower().strip()].append(m)

            for group in by_norm.values():
                if len(group) > 1:
                    matches.append((group, 1.0, "exact_match"))
        else:
            # Embedding-based fuzzy matching
            texts = [m.normalized_text for m in mentions]
            embeddings = self.embed_model.encode(texts)

            from sklearn.metrics.pairwise import cosine_similarity
            sims = cosine_similarity(embeddings)

            groups = self._cluster_by_similarity(mentions, sims, threshold)
            for group in groups:
                if len(group) > 1:
                    indices = [mentions.index(m) for m in group]
                    group_sims = sims[np.ix_(indices, indices)]
                    # Get minimum similarity in group (excluding diagonal)
                    mask = ~np.eye(len(indices), dtype=bool)
                    if mask.sum() > 0:
                        min_sim = float(group_sims[mask].min())
                    else:
                        min_sim = 1.0
                    matches.append((group, min_sim, "fuzzy_match"))

        return matches

    def _cluster_by_similarity(
        self,
        mentions: list[EntityMention],
        sims: np.ndarray,
        threshold: float,
    ) -> list[list[EntityMention]]:
        """Cluster mentions by similarity using union-find.

        Args:
            mentions: Mentions to cluster
            sims: Similarity matrix
            threshold: Minimum similarity for clustering

        Returns:
            List of mention groups
        """
        n = len(mentions)
        parent = list(range(n))

        def find(x: int) -> int:
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Union mentions with similarity above threshold
        for i in range(n):
            for j in range(i + 1, n):
                if sims[i, j] >= threshold:
                    union(i, j)

        # Group by parent
        groups: dict[int, list[EntityMention]] = defaultdict(list)
        for i, m in enumerate(mentions):
            groups[find(i)].append(m)

        return list(groups.values())

    async def create_review_items(
        self,
        links: list[EntityLink],
        mentions_by_id: dict,
        storage=None,
    ) -> list[EntityReviewItem]:
        """Create review queue items for proposed links.

        Args:
            links: Proposed entity links
            mentions_by_id: Map of mention_id to EntityMention
            storage: Optional file storage for evidence snippets

        Returns:
            List of EntityReviewItem for review queue
        """
        review_items = []

        for link in links:
            if link.status != EntityLinkStatus.PROPOSED:
                continue

            # Get mentions for this link
            link_mentions = []
            for mid in link.mention_ids:
                if mid in mentions_by_id:
                    link_mentions.append(mentions_by_id[mid])

            if not link_mentions:
                continue

            # Get entity type from first mention
            entity_type = link_mentions[0].entity_type

            # Suggest canonical name (most common normalized text)
            texts = [m.normalized_text for m in link_mentions]
            suggested_canonical = max(set(texts), key=texts.count)

            # Get evidence snippet paths
            snippet_paths = []
            for m in link_mentions:
                if m.evidence and m.evidence.snippet_path:
                    snippet_paths.append(m.evidence.snippet_path)

            # Calculate priority based on entity type and confidence
            priority = self._calculate_priority(entity_type, link.confidence)

            item = EntityReviewItem(
                link=link,
                mentions=link_mentions,
                evidence_snippet_paths=snippet_paths,
                entity_type=entity_type,
                suggested_canonical=suggested_canonical,
                priority=priority,
            )
            review_items.append(item)

        return review_items

    def _calculate_priority(self, entity_type: EntityType, confidence: float) -> int:
        """Calculate review priority (higher = more urgent).

        Args:
            entity_type: Type of entity
            confidence: Link confidence

        Returns:
            Priority score (0-100)
        """
        # Base priority by type (high-impact types get higher priority)
        type_priority = {
            EntityType.EQUIPMENT: 90,
            EntityType.REFERENCE: 85,
            EntityType.MATERIAL: 80,
            EntityType.PERSON: 50,
            EntityType.ORGANIZATION: 45,
            EntityType.LOCATION: 40,
            EntityType.EVENT: 30,
            EntityType.PROCEDURE: 35,
            EntityType.DATE: 20,
        }

        base = type_priority.get(entity_type, 50)

        # Reduce priority for high-confidence links (less urgent)
        confidence_adjustment = int((1.0 - confidence) * 20)

        return base + confidence_adjustment

    async def merge_approved_links(
        self,
        approved_links: list[EntityLink],
        mentions_by_id: dict,
        db,
    ) -> list[Entity]:
        """Create canonical entities from approved links.

        Args:
            approved_links: Approved entity links
            mentions_by_id: Map of mention_id to EntityMention
            db: Database client

        Returns:
            List of created Entity records
        """
        entities = []

        for link in approved_links:
            if link.status not in [
                EntityLinkStatus.APPROVED,
                EntityLinkStatus.AUTO_APPROVED,
            ]:
                continue

            # Get mentions
            link_mentions = [
                mentions_by_id[mid]
                for mid in link.mention_ids
                if mid in mentions_by_id
            ]

            if not link_mentions:
                continue

            # Create canonical entity
            entity_type = link_mentions[0].entity_type
            texts = [m.normalized_text for m in link_mentions]
            canonical_name = max(set(texts), key=texts.count)

            # Collect aliases (unique texts that differ from canonical)
            aliases = list(set(t for t in texts if t != canonical_name))

            # Get date range
            first_seen = min(m.evidence.confidence for m in link_mentions if m.evidence)
            last_seen = max(m.evidence.confidence for m in link_mentions if m.evidence)

            entity = Entity(
                entity_type=entity_type,
                canonical_name=canonical_name,
                aliases=aliases,
                mentions=link_mentions,
                mention_count=len(link_mentions),
                first_seen=datetime.utcnow(),  # Would use actual document dates
                last_seen=datetime.utcnow(),
                confidence=link.confidence,
                validation_status="approved" if link.status == EntityLinkStatus.APPROVED else "auto_approved",
                validated_by=link.reviewed_by,
            )

            # Update link with entity ID
            link.canonical_entity_id = entity.entity_id

            await db.insert_entity(entity)
            await db.update_entity_link(link)

            entities.append(entity)

        return entities
