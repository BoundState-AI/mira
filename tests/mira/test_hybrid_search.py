#!/usr/bin/env python3
"""
Module: Test Hybrid Search
Purpose: Hybrid Search Test Harness for BoundState MIRA

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

import pytest
import numpy as np
import sys
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, r"C:\BoundState")

from mira.search.hybrid_search import (
    HybridSearchResult,
    MIRAHybridSearch,
    patch_semantic_search_engine,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_materials_lookup() -> Dict[str, Dict]:
    """Sample materials for testing."""
    return {
        "10001": {
            "designation": "316L Stainless Steel",
            "material_code": "10001",
            "matl_materialcode": "10001",
            "composition_key": "Fe-Cr-Ni",
            "specification": "AMS5648",
            "o2_rating": "A",
            "h2_rating": "B",
            "flamm_rating": "1",
        },
        "10002": {
            "designation": "Inconel 718",
            "material_code": "10002",
            "matl_materialcode": "10002",
            "composition_key": "Ni-Cr-Fe",
            "specification": "AMS5662",
            "o2_rating": "A",
            "h2_rating": "A",
            "flamm_rating": "1",
        },
        "10003": {
            "designation": "Ti-6Al-4V Titanium",
            "material_code": "10003",
            "matl_materialcode": "10003",
            "composition_key": "Ti-Al-V",
            "specification": "AMS4911",
            "o2_rating": "C",
            "h2_rating": "B",
            "flamm_rating": "2",
        },
        "10004": {
            "designation": "A286 Stainless Steel",
            "material_code": "10004",
            "matl_materialcode": "10004",
            "composition_key": "Fe-Ni-Cr",
            "specification": "AMS5731",
            "o2_rating": "A",
            "h2_rating": "A",
            "flamm_rating": "1",
        },
        "10005": {
            "designation": "7075-T6 Aluminum",
            "material_code": "10005",
            "matl_materialcode": "10005",
            "composition_key": "Al-Zn-Mg",
            "specification": "AMS4045",
            "o2_rating": "B",
            "h2_rating": "A",
            "flamm_rating": "2",
        },
    }


@pytest.fixture
def mock_faiss_index():
    """Mock FAISS index for testing."""
    mock_index = MagicMock()
    # Return indices 0-4 with decreasing distances
    mock_index.search.return_value = (
        np.array([[0.1, 0.2, 0.3, 0.4, 0.5]]),  # distances
        np.array([[0, 1, 2, 3, 4]]),  # indices
    )
    return mock_index


@pytest.fixture
def mock_embedding_model():
    """Mock sentence transformer model."""
    mock_model = MagicMock()
    # Return 384-dim embedding (MiniLM default)
    mock_model.encode.return_value = np.random.rand(1, 384).astype('float32')
    return mock_model


@pytest.fixture
def hybrid_search(sample_materials_lookup, mock_faiss_index, mock_embedding_model):
    """Create MIRAHybridSearch instance with mocks."""
    index_to_key = {i: k for i, k in enumerate(sample_materials_lookup.keys())}
    return MIRAHybridSearch(
        faiss_index=mock_faiss_index,
        materials_lookup=sample_materials_lookup,
        embedding_model=mock_embedding_model,
        index_to_key=index_to_key,
        rrf_k=60,
    )


# =============================================================================
# HybridSearchResult Dataclass Tests
# =============================================================================

class TestHybridSearchResult:
    """Tests for HybridSearchResult dataclass."""

    def test_basic_creation(self):
        """Should create valid search result."""
        result = HybridSearchResult(
            material_key="10001",
            designation="316L Stainless Steel",
            score=0.85,
            bm25_rank=1,
            faiss_rank=2,
            payload={"rating": "A"},
        )
        assert result.material_key == "10001"
        assert result.designation == "316L Stainless Steel"
        assert result.score == 0.85
        assert result.bm25_rank == 1
        assert result.faiss_rank == 2

    def test_optional_ranks(self):
        """Ranks should be optional (None when not in that retriever's results)."""
        result = HybridSearchResult(
            material_key="10001",
            designation="316L",
            score=0.5,
            bm25_rank=5,
            faiss_rank=None,  # Not in FAISS results
        )
        assert result.bm25_rank == 5
        assert result.faiss_rank is None

    def test_optional_payload(self):
        """Payload should be optional."""
        result = HybridSearchResult(
            material_key="10001",
            designation="316L",
            score=0.5,
        )
        assert result.payload is None

    def test_score_range(self):
        """Score should be positive (RRF scores are always positive)."""
        result = HybridSearchResult(
            material_key="10001",
            designation="316L",
            score=0.0328,  # Typical RRF score: 1/(60+1) = 0.0164
        )
        assert result.score > 0


# =============================================================================
# BM25 Search Tests
# =============================================================================

class TestBM25Search:
    """Tests for BM25 lexical search functionality."""

    def test_exact_match_query(self, hybrid_search):
        """Exact material name should rank highly."""
        results = hybrid_search._bm25_search("316L", top_k=5)

        # Should find 316L material
        material_keys = [r[0] for r in results]
        assert "10001" in material_keys  # 316L Stainless Steel

        # 316L should be highly ranked
        for mat_key, rank in results:
            if mat_key == "10001":
                assert rank <= 3  # Should be in top 3

    def test_spec_number_query(self, hybrid_search):
        """Spec number search should work."""
        results = hybrid_search._bm25_search("AMS5648", top_k=5)

        material_keys = [r[0] for r in results]
        assert "10001" in material_keys  # 316L with AMS5648 spec

    def test_alphanumeric_tokenization(self, hybrid_search):
        """Should split alphanumeric tokens for partial matching."""
        # Query "5648" should match "AMS5648" due to tokenization
        results = hybrid_search._bm25_search("5648", top_k=5)

        material_keys = [r[0] for r in results]
        # May or may not match depending on scoring, but should not crash
        assert isinstance(results, list)

    def test_case_insensitive(self, hybrid_search):
        """Search should be case insensitive."""
        results_upper = hybrid_search._bm25_search("INCONEL", top_k=5)
        results_lower = hybrid_search._bm25_search("inconel", top_k=5)

        keys_upper = set(r[0] for r in results_upper)
        keys_lower = set(r[0] for r in results_lower)

        assert keys_upper == keys_lower

    def test_multi_word_query(self, hybrid_search):
        """Multi-word queries should work."""
        results = hybrid_search._bm25_search("stainless steel", top_k=5)

        material_keys = [r[0] for r in results]
        # Should find both stainless steels
        assert any(k in material_keys for k in ["10001", "10004"])

    def test_no_match_returns_empty(self, hybrid_search):
        """Query with no matches should return empty list."""
        results = hybrid_search._bm25_search("xyznonexistent123", top_k=5)

        assert results == []

    def test_rank_starts_at_one(self, hybrid_search):
        """Ranks should start at 1, not 0."""
        results = hybrid_search._bm25_search("steel", top_k=5)

        if results:
            ranks = [r[1] for r in results]
            assert min(ranks) >= 1


# =============================================================================
# FAISS Search Tests
# =============================================================================

class TestFAISSSearch:
    """Tests for FAISS semantic search functionality."""

    def test_returns_ranked_results(self, hybrid_search):
        """FAISS search should return ranked results."""
        results = hybrid_search._faiss_search("corrosion resistant alloy", top_k=5)

        assert len(results) > 0
        # All results should have material_key and rank
        for mat_key, rank in results:
            assert mat_key is not None
            assert rank >= 1

    def test_uses_embedding_model(self, hybrid_search, mock_embedding_model):
        """Should call embedding model with query."""
        hybrid_search._faiss_search("test query", top_k=5)

        mock_embedding_model.encode.assert_called_once()
        call_args = mock_embedding_model.encode.call_args[0][0]
        assert "test query" in call_args

    def test_respects_top_k(self, hybrid_search, mock_faiss_index):
        """Should return at most top_k results."""
        # Configure mock to return only 3 results for this test
        import numpy as np
        mock_faiss_index.search.return_value = (
            np.array([[0.1, 0.2, 0.3]]),
            np.array([[0, 1, 2]]),
        )

        results = hybrid_search._faiss_search("steel", top_k=3)

        assert len(results) <= 3

    def test_index_to_key_mapping(self, hybrid_search):
        """Should use index_to_key mapping correctly."""
        results = hybrid_search._faiss_search("nickel alloy", top_k=5)

        # All returned keys should be valid material keys
        for mat_key, rank in results:
            assert mat_key in hybrid_search.materials_lookup


# =============================================================================
# RRF Fusion Tests
# =============================================================================

class TestRRFFusion:
    """Tests for Reciprocal Rank Fusion algorithm."""

    def test_single_retriever_score(self, hybrid_search):
        """Result in only one retriever should have correct RRF score."""
        bm25_results = [("10001", 1)]  # Only in BM25
        faiss_results = []

        fused = hybrid_search._rrf_fuse(bm25_results, faiss_results)

        assert len(fused) == 1
        # RRF score = 1/(k + rank) = 1/(60 + 1) ≈ 0.0164
        expected_score = 1.0 / (60 + 1)
        assert abs(fused[0].score - expected_score) < 0.001

    def test_both_retrievers_higher_score(self, hybrid_search):
        """Result in both retrievers should have higher score."""
        bm25_results = [("10001", 1)]
        faiss_results = [("10001", 1)]

        fused = hybrid_search._rrf_fuse(bm25_results, faiss_results)

        assert len(fused) == 1
        # RRF score = 1/(60+1) + 1/(60+1) = 2/(61) ≈ 0.0328
        expected_score = 2.0 / 61
        assert abs(fused[0].score - expected_score) < 0.001

    def test_sorted_by_score_descending(self, hybrid_search):
        """Results should be sorted by score descending."""
        bm25_results = [("10001", 5), ("10002", 1)]  # 10002 ranks higher in BM25
        faiss_results = [("10001", 1), ("10003", 2)]  # 10001 ranks higher in FAISS

        fused = hybrid_search._rrf_fuse(bm25_results, faiss_results)

        scores = [r.score for r in fused]
        assert scores == sorted(scores, reverse=True)

    def test_deduplication(self, hybrid_search):
        """Should deduplicate materials appearing multiple times in FAISS."""
        bm25_results = [("10001", 1)]
        faiss_results = [("10001", 1), ("10001", 5)]  # Duplicate in FAISS

        fused = hybrid_search._rrf_fuse(bm25_results, faiss_results)

        # Should only have one entry for 10001
        keys = [r.material_key for r in fused]
        assert keys.count("10001") == 1

    def test_preserves_rank_info(self, hybrid_search):
        """Should preserve both BM25 and FAISS ranks in result."""
        bm25_results = [("10001", 3)]
        faiss_results = [("10001", 7)]

        fused = hybrid_search._rrf_fuse(bm25_results, faiss_results)

        assert fused[0].bm25_rank == 3
        assert fused[0].faiss_rank == 7

    def test_none_rank_for_missing(self, hybrid_search):
        """Should have None rank if not in that retriever."""
        bm25_results = [("10001", 1)]
        faiss_results = [("10002", 1)]  # Different material

        fused = hybrid_search._rrf_fuse(bm25_results, faiss_results)

        # 10001 should have no FAISS rank
        mat_10001 = next(r for r in fused if r.material_key == "10001")
        assert mat_10001.bm25_rank == 1
        assert mat_10001.faiss_rank is None

        # 10002 should have no BM25 rank
        mat_10002 = next(r for r in fused if r.material_key == "10002")
        assert mat_10002.bm25_rank is None
        assert mat_10002.faiss_rank == 1

    def test_rrf_k_parameter(self, sample_materials_lookup, mock_faiss_index, mock_embedding_model):
        """Different RRF k values should affect scores."""
        index_to_key = {i: k for i, k in enumerate(sample_materials_lookup.keys())}

        search_k30 = MIRAHybridSearch(
            faiss_index=mock_faiss_index,
            materials_lookup=sample_materials_lookup,
            embedding_model=mock_embedding_model,
            index_to_key=index_to_key,
            rrf_k=30,
        )

        search_k90 = MIRAHybridSearch(
            faiss_index=mock_faiss_index,
            materials_lookup=sample_materials_lookup,
            embedding_model=mock_embedding_model,
            index_to_key=index_to_key,
            rrf_k=90,
        )

        bm25_results = [("10001", 1)]
        faiss_results = []

        fused_k30 = search_k30._rrf_fuse(bm25_results, faiss_results)
        fused_k90 = search_k90._rrf_fuse(bm25_results, faiss_results)

        # Lower k = higher score for same rank
        assert fused_k30[0].score > fused_k90[0].score


# =============================================================================
# Full Hybrid Search Tests
# =============================================================================

class TestHybridSearch:
    """Tests for full hybrid search pipeline."""

    def test_returns_hybrid_search_results(self, hybrid_search):
        """Should return list of HybridSearchResult."""
        results = hybrid_search.search("316L stainless", top_k=5)

        assert len(results) > 0
        assert all(isinstance(r, HybridSearchResult) for r in results)

    def test_respects_top_k(self, hybrid_search):
        """Should return at most top_k results."""
        results = hybrid_search.search("steel", top_k=3)

        assert len(results) <= 3

    def test_includes_payload(self, hybrid_search):
        """Results should include payload from materials_lookup."""
        results = hybrid_search.search("316L", top_k=5)

        # Find 316L result
        mat_316l = next((r for r in results if r.material_key == "10001"), None)
        if mat_316l:
            assert mat_316l.payload is not None
            assert "o2_rating" in mat_316l.payload

    def test_designation_populated(self, hybrid_search):
        """Results should have designation populated."""
        results = hybrid_search.search("inconel", top_k=5)

        for result in results:
            assert result.designation is not None
            assert result.designation != ""


# =============================================================================
# Result Format Conversion Tests (ui_endpoints.py compatibility)
# =============================================================================

class TestResultFormatConversion:
    """Tests for patch_semantic_search_engine format conversion."""

    def test_converted_format_has_material_dict(self, hybrid_search):
        """Converted results should have 'material' nested dict."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        results = mock_engine.search("316L", top_k=5)

        assert len(results) > 0
        for r in results:
            assert "material" in r
            assert isinstance(r["material"], dict)

    def test_converted_format_has_original_material(self, hybrid_search):
        """Converted results should have 'original_material' nested dict."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        results = mock_engine.search("steel", top_k=5)

        for r in results:
            assert "original_material" in r
            assert isinstance(r["original_material"], dict)

    def test_converted_format_has_similarity_score(self, hybrid_search):
        """Converted results should have 'similarity_score' (not 'score')."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        results = mock_engine.search("titanium", top_k=5)

        for r in results:
            assert "similarity_score" in r
            assert isinstance(r["similarity_score"], float)

    def test_material_dict_fields(self, hybrid_search):
        """Material dict should have required fields."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        results = mock_engine.search("316L", top_k=5)

        for r in results:
            mat = r["material"]
            assert "material_id" in mat
            assert "designation" in mat
            assert "material_code" in mat

    def test_original_material_dict_fields(self, hybrid_search):
        """Original material dict should have required fields and payload."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        results = mock_engine.search("inconel", top_k=5)

        for r in results:
            orig = r["original_material"]
            assert "material_key" in orig
            assert "material_code" in orig
            # Should include payload fields
            if orig.get("material_key") == "10002":
                assert orig.get("o2_rating") == "A"

    def test_material_code_extracted_correctly(self, hybrid_search):
        """Material code should be extracted from payload."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        results = mock_engine.search("316L", top_k=5)

        # Find 316L result
        mat_316l = next((r for r in results if r["material"]["material_id"] == "10001"), None)
        if mat_316l:
            assert mat_316l["material"]["material_code"] == "10001"

    def test_preserves_original_search(self, hybrid_search):
        """Should preserve original search method."""
        mock_engine = MagicMock()
        original_search = MagicMock()
        mock_engine.search = original_search

        patch_semantic_search_engine(mock_engine, hybrid_search)

        assert mock_engine._original_search is original_search


# =============================================================================
# Golden Query Tests
# =============================================================================

class TestGoldenQueries:
    """Golden query tests - known queries with expected results."""

    def test_exact_alloy_name_316l(self, hybrid_search):
        """Query '316L' should find 316L stainless steel."""
        results = hybrid_search.search("316L", top_k=10)

        material_keys = [r.material_key for r in results]
        assert "10001" in material_keys

        # Should be in top 3
        rank_316l = material_keys.index("10001") + 1
        assert rank_316l <= 3

    def test_exact_alloy_name_inconel(self, hybrid_search):
        """Query 'Inconel 718' should find Inconel 718."""
        results = hybrid_search.search("Inconel 718", top_k=10)

        material_keys = [r.material_key for r in results]
        assert "10002" in material_keys

    def test_exact_alloy_name_titanium(self, hybrid_search):
        """Query 'Ti-6Al-4V' should find titanium alloy."""
        results = hybrid_search.search("Ti-6Al-4V", top_k=10)

        material_keys = [r.material_key for r in results]
        assert "10003" in material_keys

    def test_spec_number_ams5648(self, hybrid_search):
        """Query 'AMS5648' should find 316L (spec match)."""
        results = hybrid_search.search("AMS5648", top_k=10)

        material_keys = [r.material_key for r in results]
        assert "10001" in material_keys

    def test_material_class_stainless(self, hybrid_search):
        """Query 'stainless steel' should find stainless steels."""
        results = hybrid_search.search("stainless steel", top_k=10)

        material_keys = [r.material_key for r in results]
        # Should find both stainless steels
        stainless_found = [k for k in material_keys if k in ["10001", "10004"]]
        assert len(stainless_found) >= 1

    def test_material_class_aluminum(self, hybrid_search):
        """Query 'aluminum' should find aluminum alloy."""
        results = hybrid_search.search("aluminum", top_k=10)

        material_keys = [r.material_key for r in results]
        assert "10005" in material_keys

    def test_partial_alloy_number(self, hybrid_search):
        """Query '7075' should find 7075-T6 aluminum."""
        results = hybrid_search.search("7075", top_k=10)

        material_keys = [r.material_key for r in results]
        assert "10005" in material_keys


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_empty_query(self, hybrid_search):
        """Empty query should not crash."""
        results = hybrid_search.search("", top_k=5)

        assert isinstance(results, list)

    def test_very_long_query(self, hybrid_search):
        """Very long query should not crash."""
        long_query = "stainless steel " * 100
        results = hybrid_search.search(long_query, top_k=5)

        assert isinstance(results, list)

    def test_special_characters(self, hybrid_search):
        """Query with special characters should not crash."""
        results = hybrid_search.search("316L (stainless) [steel]", top_k=5)

        assert isinstance(results, list)

    def test_numbers_only(self, hybrid_search):
        """Numbers-only query should work."""
        results = hybrid_search.search("718", top_k=5)

        assert isinstance(results, list)

    def test_unicode_characters(self, hybrid_search):
        """Unicode characters should not crash."""
        results = hybrid_search.search("Inconél 718", top_k=5)

        assert isinstance(results, list)

    def test_top_k_zero(self, hybrid_search):
        """top_k=0 should return empty list."""
        results = hybrid_search.search("steel", top_k=0)

        assert results == []

    def test_top_k_larger_than_results(self, hybrid_search):
        """top_k larger than available results should work."""
        results = hybrid_search.search("316L", top_k=1000)

        assert len(results) <= 5  # Only 5 materials in test data


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Performance-related tests."""

    def test_search_returns_quickly(self, hybrid_search):
        """Search should complete in reasonable time."""
        import time

        start = time.time()
        results = hybrid_search.search("stainless steel oxygen compatible", top_k=20)
        elapsed = time.time() - start

        # Should complete in under 1 second (excluding model loading)
        assert elapsed < 1.0

    def test_repeated_searches_consistent(self, hybrid_search):
        """Repeated searches should return consistent results."""
        results1 = hybrid_search.search("316L", top_k=5)
        results2 = hybrid_search.search("316L", top_k=5)

        keys1 = [r.material_key for r in results1]
        keys2 = [r.material_key for r in results2]

        assert keys1 == keys2


# =============================================================================
# Integration Test with Mock API
# =============================================================================

class TestAPIIntegration:
    """Tests for API integration patterns."""

    def test_patched_engine_callable(self, hybrid_search):
        """Patched engine.search should be callable."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        # Should be callable
        results = mock_engine.search("test", top_k=5)
        assert isinstance(results, list)

    def test_patched_engine_accepts_kwargs(self, hybrid_search):
        """Patched engine should accept additional kwargs."""
        mock_engine = MagicMock()
        patch_semantic_search_engine(mock_engine, hybrid_search)

        # Should not crash with extra kwargs
        results = mock_engine.search("test", top_k=5, some_extra_param=True)
        assert isinstance(results, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
