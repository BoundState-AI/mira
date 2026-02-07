#!/usr/bin/env python3
"""
Module: Test Document Store
Purpose: Tests for core.infra.document_store module.

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

import pytest

from core.infra.document_store import DocumentHit, NullDocumentStore


class TestDocumentHit:
    """Tests for DocumentHit dataclass."""

    def test_create_document_hit(self):
        """DocumentHit can be created with required fields."""
        hit = DocumentHit(
            doc_id="doc-123",
            title="Test Document",
            snippet="This is a test snippet",
            score=0.95,
            metadata={"material_key": "MAT-001"},
        )
        assert hit.doc_id == "doc-123"
        assert hit.title == "Test Document"
        assert hit.snippet == "This is a test snippet"
        assert hit.score == 0.95
        assert hit.metadata == {"material_key": "MAT-001"}

    def test_document_hit_is_frozen(self):
        """DocumentHit is immutable (frozen dataclass)."""
        hit = DocumentHit(
            doc_id="doc-123",
            title="Test",
            snippet="Snippet",
            score=0.5,
            metadata={},
        )
        with pytest.raises(AttributeError):
            hit.doc_id = "new-id"

    def test_document_hit_with_empty_metadata(self):
        """DocumentHit works with empty metadata."""
        hit = DocumentHit(
            doc_id="doc-456",
            title="Empty Meta Doc",
            snippet="No metadata here",
            score=0.75,
            metadata={},
        )
        assert hit.metadata == {}

    def test_document_hit_with_complex_metadata(self):
        """DocumentHit handles complex nested metadata."""
        metadata = {
            "material_key": "MAT-002",
            "environment": "oxygen",
            "ratings": ["A", "B"],
            "nested": {"key": "value"},
        }
        hit = DocumentHit(
            doc_id="doc-789",
            title="Complex Doc",
            snippet="Complex metadata",
            score=0.88,
            metadata=metadata,
        )
        assert hit.metadata["ratings"] == ["A", "B"]
        assert hit.metadata["nested"]["key"] == "value"


class TestNullDocumentStore:
    """Tests for NullDocumentStore stub implementation."""

    def test_search_returns_empty_list(self):
        """NullDocumentStore.search always returns empty list."""
        store = NullDocumentStore()
        results = list(store.search("any query"))
        assert results == []

    def test_search_with_filters_returns_empty(self):
        """NullDocumentStore.search ignores filters and returns empty."""
        store = NullDocumentStore()
        results = list(store.search(
            "test query",
            filters={"material_key": "MAT-001"},
            top_k=100,
        ))
        assert results == []

    def test_search_with_top_k_returns_empty(self):
        """NullDocumentStore.search ignores top_k and returns empty."""
        store = NullDocumentStore()
        results = list(store.search("query", top_k=1000))
        assert results == []

    def test_multiple_searches_all_empty(self):
        """Multiple searches on NullDocumentStore all return empty."""
        store = NullDocumentStore()
        for query in ["query1", "query2", "query3"]:
            assert list(store.search(query)) == []
