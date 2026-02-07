#!/usr/bin/env python3
"""
Module: Engine
Purpose: Query Engine for BoundState

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

from typing import Dict, Iterable, List, Optional

from core.infra.document_store import DocumentStore, DocumentHit
from core.models.query import EngineeringQuery
from core.models.answer import EngineAnswer, AnswerSeverity, EvidenceItem


class QueryEngine:
    """Core search engine for BoundState.

    - Takes an EngineeringQuery (question + structured context)
    - Uses a DocumentStore to retrieve candidate docs
    - Returns an EngineAnswer with evidence only (classification UNKNOWN by default)

    Domain-specific engines (O2, H2, etc.) handle classification.
    This engine is for generic document retrieval.
    """

    def __init__(self, document_store: DocumentStore) -> None:
        self._store = document_store

    def search(
        self,
        query: EngineeringQuery,
        *,
        top_k: int = 10,
        score_threshold: Optional[float] = None,
    ) -> EngineAnswer:
        """Run a generic search, returning evidence-only answer.

        Args:
            query: The engineering query with question and context
            top_k: Maximum number of results
            score_threshold: Minimum score to include in results

        Returns:
            EngineAnswer with classification=UNKNOWN and evidence items
        """
        filters = self._build_filters(query)
        hits: Iterable[DocumentHit] = self._store.search(
            query=query.question,
            filters=filters,
            top_k=top_k,
        )

        evidence_items: List[EvidenceItem] = []
        for hit in hits:
            if score_threshold is not None and hit.score < score_threshold:
                continue
            evidence_items.append(
                EvidenceItem(
                    source_id=hit.doc_id,
                    location=hit.metadata.get("location"),
                    summary=hit.snippet,
                )
            )

        if evidence_items:
            rationale = f"Found {len(evidence_items)} relevant document(s). No compatibility classification applied."
        else:
            rationale = "No matching documents found."

        return EngineAnswer(
            classification=AnswerSeverity.UNKNOWN,
            rationale=rationale,
            evidence=evidence_items,
            notes=None,
        )

    def _build_filters(self, query: EngineeringQuery) -> Dict:
        """Translate structured context into document filters.

        NOTE: For material-related queries, this MUST use validated fields
        (material_key, rating tags, etc.), not string matching on names.

        Environment is NOT a direct filter - it influences search strategy
        but doesn't filter on a metadata field (which doesn't exist).
        """
        filters: Dict = {}
        ctx = query.context

        # Filter by material_key if provided (exact match)
        if ctx.material_key is not None:
            filters["material_key"] = ctx.material_key

        # NOTE: environment is NOT a direct filter on metadata
        # It's used to inform domain engines (O2, H2) but not for raw search
        # The metadata has test_type, contract_id, etc. but not "environment"

        # Allow upstream callers to stuff extra structured constraints in metadata
        # Only apply filters that exist in the actual metadata schema
        known_filter_fields = {
            "material_key", "contract_id", "test_type", "material_code",
            "designation", "name", "material_type_key",
        }
        for key, value in ctx.metadata.items():
            if key in known_filter_fields:
                filters[key] = value

        return filters


__all__ = ["QueryEngine"]
