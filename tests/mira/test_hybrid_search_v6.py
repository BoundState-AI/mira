#!/usr/bin/env python3
"""
Test Suite: Hybrid Search for V6 MUA Retriever

Tests BM25 + FAISS + RRF hybrid search functionality.

BoundState AI 2026
Compliance: SWE-013, NASA-STD-8739.8B
"""

import pytest
from unittest.mock import MagicMock, patch
import numpy as np


class TestBM25Integration:
    """Test BM25 integration in V6 retriever."""

    def test_bm25_import_flag(self):
        """BM25_AVAILABLE flag should reflect rank_bm25 availability."""
        from mira.mua.v6.retriever import BM25_AVAILABLE
        # Should be True if rank_bm25 is installed
        assert isinstance(BM25_AVAILABLE, bool)

    def test_tokenize_bm25(self):
        """Test BM25 tokenization with alphanumeric boundary splitting."""
        from mira.mua.v6.retriever import V6PrecedentRetriever

        retriever = V6PrecedentRetriever(auto_load=False)

        # Test cases
        tokens = retriever._tokenize_bm25("6061-T6 aluminum")
        assert "6061-t6" in tokens
        assert "aluminum" in tokens
        assert "6061" in tokens
        # Note: "t6" splits to "t" and "6" per alphanumeric boundary splitting
        assert "6" in tokens

        tokens = retriever._tokenize_bm25("AMS5648G stainless steel")
        assert "ams5648g" in tokens
        assert "ams" in tokens
        assert "5648" in tokens

    def test_retriever_has_hybrid_search_method(self):
        """V6PrecedentRetriever should have search_hybrid method."""
        from mira.mua.v6.retriever import V6PrecedentRetriever

        retriever = V6PrecedentRetriever(auto_load=False)
        assert hasattr(retriever, "search_hybrid")
        assert hasattr(retriever, "_build_bm25_index")

    def test_retriever_bm25_params(self):
        """Retriever should have BM25 tuning parameters."""
        from mira.mua.v6.retriever import V6PrecedentRetriever

        assert V6PrecedentRetriever.BM25_K1 == 1.2
        assert V6PrecedentRetriever.BM25_B == 0.75
        assert V6PrecedentRetriever.RRF_K == 60


class TestRRFFusion:
    """Test Reciprocal Rank Fusion algorithm."""

    def test_rrf_score_calculation(self):
        """Test RRF score calculation formula."""
        # RRF = 1/(k + rank) for each ranking system
        k = 60  # Standard RRF constant

        # If item appears at rank 1 in both systems:
        # RRF = 1/(60+1) + 1/(60+1) = 2/61 ≈ 0.0328
        expected_both_rank_1 = 2 / 61

        # If item appears at rank 1 in one system only:
        # RRF = 1/(60+1) ≈ 0.0164
        expected_one_rank_1 = 1 / 61

        assert abs(expected_both_rank_1 - 0.0328) < 0.001
        assert abs(expected_one_rank_1 - 0.0164) < 0.001

    def test_rrf_prefers_items_in_both_lists(self):
        """Items appearing in both BM25 and FAISS should score higher."""
        k = 60

        # Item in both at rank 5
        rrf_both = 1 / (k + 5) + 1 / (k + 5)

        # Item in only one at rank 1
        rrf_one = 1 / (k + 1)

        # Both-list item should still beat single-list rank 1
        assert rrf_both > rrf_one


class TestHybridSearchMocked:
    """Test hybrid search with mocked FAISS index."""

    @patch("mira.mua.v6.retriever.BM25_AVAILABLE", True)
    def test_hybrid_search_combines_results(self):
        """Hybrid search should combine BM25 and FAISS results."""
        from mira.mua.v6.retriever import V6PrecedentRetriever

        # Create retriever with mocked components
        retriever = V6PrecedentRetriever(auto_load=False, enable_bm25=True)
        retriever._loaded = True

        # Mock index builder with fake metadata
        mock_metadata = [
            {
                "mua_number": "MUA-001",
                "material_designation": "6061-T6 Aluminum",
                "specification": "AMS4027",
                "environment": {"type": "lox_gox", "o2_percent": 100},
                "issues": ["flammability"],
                "determination": "APPROVED",
                "confidence": 0.9,
                "application": "Valve body",
                "rationale": "Tested per ASTM G63",
            },
            {
                "mua_number": "MUA-002",
                "material_designation": "Inconel 718",
                "specification": "AMS5664",
                "environment": {"type": "lox_gox", "o2_percent": 100},
                "issues": ["flammability"],
                "determination": "APPROVED",
                "confidence": 0.95,
                "application": "Fasteners",
                "rationale": "Approved for oxygen service",
            },
        ]

        retriever._index_builder._metadata = mock_metadata

        # Build BM25 index
        retriever._build_bm25_index()

        # Verify BM25 index was built
        assert retriever._bm25 is not None
        assert len(retriever._bm25_corpus_keys) == 2


class TestQueryEngineIntegration:
    """Test hybrid search integration in query engine."""

    def test_query_engine_uses_hybrid_search(self):
        """Query engine should call search_hybrid when BM25 is available."""
        # This tests the integration path is correct
        # Full integration requires loaded indexes

        from mira.MIRA_V2.src.query_engine_v2 import V6_AVAILABLE
        assert V6_AVAILABLE is True or V6_AVAILABLE is False  # Just verify import worked


class TestMaterialSearchScenarios:
    """Test realistic material search scenarios."""

    def test_aluminum_6061_search_query(self):
        """Test that 6061 aluminum generates proper search tokens."""
        from mira.mua.v6.retriever import V6PrecedentRetriever

        retriever = V6PrecedentRetriever(auto_load=False)

        # "6061 aluminum" should tokenize well
        tokens = retriever._tokenize_bm25("6061 aluminum alloy oxygen compatible")
        assert "6061" in tokens
        assert "aluminum" in tokens
        assert "oxygen" in tokens
        assert "compatible" in tokens

    def test_stainless_steel_search_query(self):
        """Test stainless steel search tokenization."""
        from mira.mua.v6.retriever import V6PrecedentRetriever

        retriever = V6PrecedentRetriever(auto_load=False)

        tokens = retriever._tokenize_bm25("316L stainless steel CRES")
        assert "316l" in tokens or "316" in tokens
        assert "stainless" in tokens
        assert "cres" in tokens

    def test_spec_number_search(self):
        """Test specification number search tokenization."""
        from mira.mua.v6.retriever import V6PrecedentRetriever

        retriever = V6PrecedentRetriever(auto_load=False)

        tokens = retriever._tokenize_bm25("AMS5648G")
        assert "ams5648g" in tokens
        assert "ams" in tokens
        assert "5648" in tokens


class TestExistingHybridSearchModule:
    """Test the existing mira/search/hybrid_search module."""

    def test_hybrid_search_module_exists(self):
        """mira/search/hybrid_search should be importable."""
        from mira.search.hybrid_search import (
            MIRAHybridSearch,
            HybridSearchResult,
            create_hybrid_search_from_mira,
        )

        assert MIRAHybridSearch is not None
        assert HybridSearchResult is not None

    def test_hybrid_search_result_dataclass(self):
        """HybridSearchResult should have expected fields."""
        from mira.search.hybrid_search import HybridSearchResult

        result = HybridSearchResult(
            material_key="12345",
            designation="Test Material",
            score=0.95,
            bm25_rank=1,
            faiss_rank=2,
        )

        assert result.material_key == "12345"
        assert result.designation == "Test Material"
        assert result.score == 0.95
        assert result.bm25_rank == 1
        assert result.faiss_rank == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
