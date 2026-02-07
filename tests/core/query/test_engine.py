#!/usr/bin/env python3
"""
Module: Test Engine
Purpose: Tests for core.query.engine module.

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

from typing import Any, Dict, Iterable, Optional

import pytest

from core.infra.document_store import DocumentHit, DocumentStore
from core.models.query import EngineeringQuery, QueryContext, EnvironmentType
from core.models.answer import AnswerSeverity, EngineAnswer, EvidenceItem
from core.query.engine import QueryEngine


class MockDocumentStore:
    """Mock DocumentStore for testing."""

    def __init__(self, results: list[DocumentHit] | None = None):
        self._results = results or []
        self.last_query: str | None = None
        self.last_filters: Dict[str, Any] | None = None
        self.last_top_k: int | None = None

    def search(
        self,
        query: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> Iterable[DocumentHit]:
        self.last_query = query
        self.last_filters = filters
        self.last_top_k = top_k
        return self._results[:top_k]


class TestQueryEngine:
    """Tests for QueryEngine class."""

    def test_search_with_no_results(self):
        """Search with empty store returns UNKNOWN with no evidence."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(question="Is Inconel 718 compatible with oxygen?")
        answer = engine.search(query)

        assert answer.classification == AnswerSeverity.UNKNOWN
        assert answer.evidence == []
        assert "No matching documents" in answer.rationale

    def test_search_with_results(self):
        """Search with results returns evidence items."""
        hits = [
            DocumentHit(
                doc_id="doc-1",
                title="Inconel 718 Data",
                snippet="Inconel 718 is rated A for oxygen",
                score=0.95,
                metadata={"material_key": "MAT-001", "location": "Section 3.2"},
            ),
            DocumentHit(
                doc_id="doc-2",
                title="Oxygen Compatibility Guide",
                snippet="General oxygen compatibility guidelines",
                score=0.85,
                metadata={"material_key": "MAT-002"},
            ),
        ]
        store = MockDocumentStore(hits)
        engine = QueryEngine(store)

        query = EngineeringQuery(question="Inconel 718 oxygen compatibility")
        answer = engine.search(query)

        assert answer.classification == AnswerSeverity.UNKNOWN
        assert len(answer.evidence) == 2
        assert answer.evidence[0].source_id == "doc-1"
        assert answer.evidence[0].location == "Section 3.2"
        assert answer.evidence[1].source_id == "doc-2"
        assert answer.evidence[1].location is None

    def test_search_respects_top_k(self):
        """Search passes top_k to document store."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(question="test query")
        engine.search(query, top_k=5)

        assert store.last_top_k == 5

    def test_search_respects_score_threshold(self):
        """Search filters out low-score results."""
        hits = [
            DocumentHit(doc_id="doc-1", title="High", snippet="High score", score=0.9, metadata={}),
            DocumentHit(doc_id="doc-2", title="Low", snippet="Low score", score=0.3, metadata={}),
        ]
        store = MockDocumentStore(hits)
        engine = QueryEngine(store)

        query = EngineeringQuery(question="test")
        answer = engine.search(query, score_threshold=0.5)

        assert len(answer.evidence) == 1
        assert answer.evidence[0].source_id == "doc-1"

    def test_search_passes_question_to_store(self):
        """Search passes question text to document store."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(question="What is the tensile strength of Ti-6Al-4V?")
        engine.search(query)

        assert store.last_query == "What is the tensile strength of Ti-6Al-4V?"


class TestQueryEngineBuildFilters:
    """Tests for QueryEngine._build_filters method."""

    def test_build_filters_empty_context(self):
        """Empty context produces empty filters."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(question="test")
        engine.search(query)

        assert store.last_filters == {}

    def test_build_filters_with_material_key(self):
        """material_key from context is passed as filter."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(
            question="test",
            context=QueryContext(material_key="MAT-001"),
        )
        engine.search(query)

        assert store.last_filters == {"material_key": "MAT-001"}

    def test_build_filters_ignores_environment(self):
        """environment is NOT passed as a direct filter."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(
            question="test",
            context=QueryContext(environment=EnvironmentType.OXYGEN),
        )
        engine.search(query)

        # environment should NOT be in filters
        assert "environment" not in store.last_filters

    def test_build_filters_with_known_metadata_fields(self):
        """Known metadata fields are passed as filters."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(
            question="test",
            context=QueryContext(
                metadata={
                    "contract_id": "NAS-123",
                    "test_type": "tensile",
                    "unknown_field": "ignored",
                }
            ),
        )
        engine.search(query)

        assert store.last_filters == {
            "contract_id": "NAS-123",
            "test_type": "tensile",
        }
        assert "unknown_field" not in store.last_filters

    def test_build_filters_combines_material_key_and_metadata(self):
        """material_key and metadata filters are combined."""
        store = MockDocumentStore([])
        engine = QueryEngine(store)

        query = EngineeringQuery(
            question="test",
            context=QueryContext(
                material_key="MAT-001",
                metadata={"designation": "Inconel 718"},
            ),
        )
        engine.search(query)

        assert store.last_filters == {
            "material_key": "MAT-001",
            "designation": "Inconel 718",
        }


class TestQueryEngineIntegration:
    """Integration tests for QueryEngine with NullDocumentStore."""

    def test_with_null_store(self):
        """QueryEngine works with NullDocumentStore."""
        from core.infra.document_store import NullDocumentStore

        store = NullDocumentStore()
        engine = QueryEngine(store)

        query = EngineeringQuery(question="Any question")
        answer = engine.search(query)

        assert answer.classification == AnswerSeverity.UNKNOWN
        assert answer.evidence == []
        assert "No matching documents" in answer.rationale


class TestEvidenceItemFromHit:
    """Tests for evidence item creation from document hits."""

    def test_evidence_includes_snippet_as_summary(self):
        """EvidenceItem.summary comes from DocumentHit.snippet."""
        hit = DocumentHit(
            doc_id="doc-1",
            title="Test",
            snippet="This is the snippet text",
            score=0.9,
            metadata={},
        )
        store = MockDocumentStore([hit])
        engine = QueryEngine(store)

        query = EngineeringQuery(question="test")
        answer = engine.search(query)

        assert answer.evidence[0].summary == "This is the snippet text"

    def test_evidence_source_id_from_doc_id(self):
        """EvidenceItem.source_id comes from DocumentHit.doc_id."""
        hit = DocumentHit(
            doc_id="unique-doc-id-123",
            title="Test",
            snippet="Snippet",
            score=0.9,
            metadata={},
        )
        store = MockDocumentStore([hit])
        engine = QueryEngine(store)

        query = EngineeringQuery(question="test")
        answer = engine.search(query)

        assert answer.evidence[0].source_id == "unique-doc-id-123"

    def test_evidence_location_from_metadata(self):
        """EvidenceItem.location comes from metadata.location."""
        hit = DocumentHit(
            doc_id="doc-1",
            title="Test",
            snippet="Snippet",
            score=0.9,
            metadata={"location": "Page 42, Section 3.1"},
        )
        store = MockDocumentStore([hit])
        engine = QueryEngine(store)

        query = EngineeringQuery(question="test")
        answer = engine.search(query)

        assert answer.evidence[0].location == "Page 42, Section 3.1"
