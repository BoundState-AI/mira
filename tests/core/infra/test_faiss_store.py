#!/usr/bin/env python3
"""
Module: Test Faiss Store
Purpose: Tests for core.infra.faiss_store module.

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
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.infra.document_store import DocumentHit


class TestFaissDocumentStoreMatching:
    """Tests for FaissDocumentStore._matches_filters method."""

    def test_matches_filters_empty_filters(self):
        """Empty filters match any metadata."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"material_key": "MAT-001", "name": "Test"}
        assert store._matches_filters(meta, {}) is True

    def test_matches_filters_exact_match(self):
        """Exact string match works."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"material_key": "MAT-001"}
        assert store._matches_filters(meta, {"material_key": "MAT-001"}) is True

    def test_matches_filters_case_insensitive(self):
        """String matching is case-insensitive."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"material_key": "MAT-001"}
        assert store._matches_filters(meta, {"material_key": "mat-001"}) is True
        assert store._matches_filters(meta, {"material_key": "Mat-001"}) is True

    def test_matches_filters_missing_field(self):
        """Missing field in metadata doesn't match."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"name": "Test"}
        assert store._matches_filters(meta, {"material_key": "MAT-001"}) is False

    def test_matches_filters_none_expected_skipped(self):
        """None filter value is skipped."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"material_key": "MAT-001"}
        assert store._matches_filters(meta, {"material_key": None}) is True

    def test_matches_filters_multiple_fields(self):
        """Multiple filter fields must all match."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"material_key": "MAT-001", "test_type": "tensile"}
        assert store._matches_filters(meta, {"material_key": "MAT-001", "test_type": "tensile"}) is True
        assert store._matches_filters(meta, {"material_key": "MAT-001", "test_type": "hardness"}) is False

    def test_matches_filters_numeric_values(self):
        """Numeric filter values match exactly."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"count": 42}
        assert store._matches_filters(meta, {"count": 42}) is True
        assert store._matches_filters(meta, {"count": 43}) is False


class TestFaissDocumentStoreBuildSnippet:
    """Tests for FaissDocumentStore._build_snippet method."""

    def test_build_snippet_all_fields(self):
        """Snippet includes all available fields."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {
            "designation": "Inconel 718",
            "material_type": "Nickel Alloy",
            "test_class": "Mechanical",
            "rating": "A",
        }
        snippet = store._build_snippet(meta, "query")
        assert "Inconel 718" in snippet
        assert "Nickel Alloy" in snippet
        assert "Mechanical" in snippet
        assert "Rating: A" in snippet

    def test_build_snippet_partial_fields(self):
        """Snippet handles missing fields gracefully."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"designation": "Steel 304"}
        snippet = store._build_snippet(meta, "query")
        assert "Steel 304" in snippet
        assert "Type:" not in snippet

    def test_build_snippet_empty_metadata(self):
        """Snippet falls back for empty metadata."""
        from core.infra.faiss_store import FaissDocumentStore

        store = FaissDocumentStore(Path("/dummy"))
        meta = {"material_key": "MAT-001"}
        snippet = store._build_snippet(meta, "query")
        assert "MAT-001" in snippet


class TestFaissDocumentStoreSearch:
    """Tests for FaissDocumentStore.search with mocked FAISS."""

    @pytest.fixture
    def mock_faiss_store(self, tmp_path):
        """Create a FaissDocumentStore with mocked dependencies."""
        # Create metadata file
        metadata = [
            {"material_key": "MAT-001", "designation": "Inconel 718", "name": "Inconel"},
            {"material_key": "MAT-002", "designation": "Steel 304", "name": "Stainless Steel"},
            {"material_key": "MAT-003", "designation": "Titanium 6Al-4V", "name": "Ti64"},
        ]
        metadata_file = tmp_path / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))

        # Create mock FAISS index
        mock_index = MagicMock()
        mock_index.ntotal = 3
        # Return indices 0, 1, 2 with distances 0.1, 0.2, 0.3
        mock_index.search.return_value = (
            np.array([[0.1, 0.2, 0.3]]),
            np.array([[0, 1, 2]]),
        )

        # Create mock model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1] * 768])

        # Patch the lazy imports
        with patch("core.infra.faiss_store._ensure_faiss") as mock_ensure:
            mock_faiss = MagicMock()
            mock_faiss.read_index.return_value = mock_index
            mock_ensure.return_value = (mock_faiss, lambda name: mock_model)

            from core.infra.faiss_store import FaissDocumentStore
            store = FaissDocumentStore(tmp_path)

            # Write a dummy index file so _load proceeds
            (tmp_path / "index.faiss").write_bytes(b"dummy")

            yield store, mock_index, mock_model

    def test_search_returns_document_hits(self, mock_faiss_store):
        """Search returns DocumentHit objects."""
        store, mock_index, mock_model = mock_faiss_store
        results = list(store.search("inconel properties"))

        assert len(results) == 3
        assert all(isinstance(r, DocumentHit) for r in results)

    def test_search_respects_top_k(self, mock_faiss_store):
        """Search respects top_k limit."""
        store, mock_index, mock_model = mock_faiss_store
        results = list(store.search("query", top_k=2))

        assert len(results) == 2

    def test_search_applies_filters(self, mock_faiss_store):
        """Search filters results by metadata."""
        store, mock_index, mock_model = mock_faiss_store
        results = list(store.search("query", filters={"material_key": "MAT-001"}))

        # Only MAT-001 should match
        assert len(results) == 1
        assert results[0].metadata["material_key"] == "MAT-001"

    def test_search_no_results_with_strict_filter(self, mock_faiss_store):
        """Search returns empty when filter matches nothing."""
        store, mock_index, mock_model = mock_faiss_store
        results = list(store.search("query", filters={"material_key": "NONEXISTENT"}))

        assert len(results) == 0

    def test_search_keyword_boost(self, mock_faiss_store):
        """Search boosts results with keyword matches."""
        store, mock_index, mock_model = mock_faiss_store
        # Search for "inconel" should boost MAT-001 which has "Inconel" in designation
        results = list(store.search("inconel"))

        # First result should be the one with "Inconel" in designation
        assert results[0].metadata["designation"] == "Inconel 718"
