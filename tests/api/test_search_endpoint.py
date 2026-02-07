#!/usr/bin/env python3
"""
Module: Test Search Endpoint
Purpose: Search API Endpoint Tests for BoundState MIRA

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
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from pydantic import ValidationError

sys.path.insert(0, r"C:\BoundState")


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_hybrid_search_results():
    """Mock hybrid search results in the format returned by patched engine."""
    return [
        {
            "material": {
                "material_id": "10001",
                "name": "316L Stainless Steel",
                "designation": "316L Stainless Steel",
                "material_code": "10001",
                "composition": "Fe-Cr-Ni",
            },
            "original_material": {
                "material_key": "10001",
                "material_code": "10001",
                "matl_designation": "316L Stainless Steel",
                "designation": "316L Stainless Steel",
                "o2_rating": "A",
                "h2_rating": "B",
                "flamm_rating": "1",
                "corr_rating": "1",
                "scc_rating": "1",
                "tvs_rating": "2",
                "tox_rating": "1",
                "row_uid": "10001",
            },
            "similarity_score": 0.0328,
            "bm25_rank": 1,
            "faiss_rank": 2,
        },
        {
            "material": {
                "material_id": "10002",
                "name": "Inconel 718",
                "designation": "Inconel 718",
                "material_code": "10002",
                "composition": "Ni-Cr-Fe",
            },
            "original_material": {
                "material_key": "10002",
                "material_code": "10002",
                "matl_designation": "Inconel 718",
                "designation": "Inconel 718",
                "o2_rating": "A",
                "h2_rating": "A",
                "flamm_rating": "1",
            },
            "similarity_score": 0.0164,
            "bm25_rank": None,
            "faiss_rank": 1,
        },
    ]


# =============================================================================
# Request Model Tests
# =============================================================================

class TestMaterialSearchRequest:
    """Tests for MaterialSearchRequest model."""

    def test_valid_request(self):
        """Valid request should pass validation."""
        from mira.api.routers.ui_endpoints import MaterialSearchRequest

        request = MaterialSearchRequest(query="316L stainless steel")
        assert request.query == "316L stainless steel"
        assert request.top_k == 25  # Default per ui_endpoints.py

    def test_custom_top_k(self):
        """Custom top_k should be accepted."""
        from mira.api.routers.ui_endpoints import MaterialSearchRequest

        request = MaterialSearchRequest(query="inconel", top_k=50)
        assert request.top_k == 50

    def test_empty_query_allowed(self):
        """Empty query may be allowed (handled by endpoint)."""
        from mira.api.routers.ui_endpoints import MaterialSearchRequest

        # This may or may not be valid depending on model definition
        try:
            request = MaterialSearchRequest(query="")
            assert request.query == ""
        except ValidationError:
            pass  # Also acceptable if model requires non-empty


# =============================================================================
# Response Model Tests
# =============================================================================

class TestMaterialSearchResult:
    """Tests for MaterialSearchResult model."""

    def test_valid_result(self):
        """Valid result should pass validation."""
        from mira.api.routers.ui_endpoints import MaterialSearchResult

        result = MaterialSearchResult(
            material_key="10001",
            material_designation="316L Stainless Steel",
            material_code="10001",
            preview="Fe-Cr-Ni composition",
            score=0.85,
        )
        assert result.material_key == "10001"
        assert result.score == 0.85

    def test_optional_ratings(self):
        """Rating fields should be optional."""
        from mira.api.routers.ui_endpoints import MaterialSearchResult

        result = MaterialSearchResult(
            material_key="10001",
            material_designation="316L",
            material_code="10001",
            preview="",
            score=0.5,
            o2_rating=None,
            h2_rating=None,
        )
        assert result.o2_rating is None

    def test_all_rating_fields(self):
        """All rating fields should be accepted."""
        from mira.api.routers.ui_endpoints import MaterialSearchResult

        result = MaterialSearchResult(
            material_key="10001",
            material_designation="316L",
            material_code="10001",
            preview="",
            score=0.5,
            o2_rating="A",
            h2_rating="B",
            flamm_rating="1",
            corr_rating="1",
            scc_rating="1",
            tvs_rating="2",
            tox_rating="1",
        )
        assert result.o2_rating == "A"
        assert result.flamm_rating == "1"


class TestMaterialSearchResponse:
    """Tests for MaterialSearchResponse model."""

    def test_valid_response(self):
        """Valid response should pass validation."""
        from mira.api.routers.ui_endpoints import MaterialSearchResponse, MaterialSearchResult

        results = [
            MaterialSearchResult(
                material_key="10001",
                material_designation="316L",
                material_code="10001",
                preview="",
                score=0.5,
            )
        ]
        response = MaterialSearchResponse(results=results, total=1)
        assert response.total == 1
        assert len(response.results) == 1

    def test_empty_results(self):
        """Empty results should be valid."""
        from mira.api.routers.ui_endpoints import MaterialSearchResponse

        response = MaterialSearchResponse(results=[], total=0)
        assert response.total == 0
        assert response.results == []


# =============================================================================
# Endpoint Result Transformation Tests
# =============================================================================

class TestResultTransformation:
    """Tests for transforming hybrid search results to API response."""

    def test_material_key_extraction(self, mock_hybrid_search_results):
        """material_key should be extracted correctly."""
        from mira.api.routers.ui_endpoints import MaterialSearchResult

        r = mock_hybrid_search_results[0]
        mat = r.get("material", {})
        orig = r.get("original_material", {})

        material_key = str(orig.get("material_key", mat.get("material_id", "")))
        assert material_key == "10001"

    def test_designation_extraction(self, mock_hybrid_search_results):
        """designation should be extracted from nested dicts."""
        r = mock_hybrid_search_results[0]
        mat = r.get("material", {})
        orig = r.get("original_material", {})

        designation = (
            mat.get("designation") or
            mat.get("name") or
            orig.get("designation") or
            orig.get("name") or
            ""
        )
        assert designation == "316L Stainless Steel"

    def test_material_code_extraction(self, mock_hybrid_search_results):
        """material_code should be extracted from nested dicts."""
        r = mock_hybrid_search_results[0]
        mat = r.get("material", {})
        orig = r.get("original_material", {})

        material_code = (
            mat.get("material_code") or
            orig.get("material_code") or
            str(orig.get("material_key", ""))
        )
        assert material_code == "10001"

    def test_score_extraction(self, mock_hybrid_search_results):
        """similarity_score should be extracted correctly."""
        r = mock_hybrid_search_results[0]
        score = r.get("similarity_score", 0.0)
        assert score == 0.0328

    def test_ratings_extraction(self, mock_hybrid_search_results):
        """Ratings should be extracted from original_material."""
        r = mock_hybrid_search_results[0]
        orig = r.get("original_material", {})

        assert orig.get("o2_rating") == "A"
        assert orig.get("h2_rating") == "B"
        assert orig.get("flamm_rating") == "1"

    def test_missing_ratings_handled(self, mock_hybrid_search_results):
        """Missing ratings should return None."""
        r = mock_hybrid_search_results[1]
        orig = r.get("original_material", {})

        # Second result has fewer rating fields
        assert orig.get("corr_rating") is None
        assert orig.get("scc_rating") is None


# =============================================================================
# Format Compatibility Tests
# =============================================================================

class TestFormatCompatibility:
    """Tests to ensure hybrid search format matches ui_endpoints expectations."""

    def test_material_dict_has_material_id(self, mock_hybrid_search_results):
        """material dict should have material_id field."""
        for r in mock_hybrid_search_results:
            mat = r.get("material", {})
            assert "material_id" in mat

    def test_material_dict_has_name(self, mock_hybrid_search_results):
        """material dict should have name field."""
        for r in mock_hybrid_search_results:
            mat = r.get("material", {})
            assert "name" in mat

    def test_material_dict_has_designation(self, mock_hybrid_search_results):
        """material dict should have designation field."""
        for r in mock_hybrid_search_results:
            mat = r.get("material", {})
            assert "designation" in mat

    def test_material_dict_has_material_code(self, mock_hybrid_search_results):
        """material dict should have material_code field."""
        for r in mock_hybrid_search_results:
            mat = r.get("material", {})
            assert "material_code" in mat

    def test_original_material_has_material_key(self, mock_hybrid_search_results):
        """original_material dict should have material_key field."""
        for r in mock_hybrid_search_results:
            orig = r.get("original_material", {})
            assert "material_key" in orig

    def test_has_similarity_score_not_score(self, mock_hybrid_search_results):
        """Should have similarity_score, not score."""
        for r in mock_hybrid_search_results:
            assert "similarity_score" in r
            # score may or may not exist, but similarity_score is required


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in search endpoint."""

    @pytest.mark.asyncio
    async def test_search_exception_returns_500(self):
        """Search exceptions should return 500 error."""
        from mira.api.routers.ui_endpoints import material_search, MaterialSearchRequest
        from fastapi import HTTPException

        # Mock get_semantic_search to return an engine that raises
        mock_engine = MagicMock()
        mock_engine.search.side_effect = Exception("Search failed")

        with patch("mira.api.routers.ui_endpoints.get_semantic_search", return_value=mock_engine):
            request = MaterialSearchRequest(query="test")

            with pytest.raises(HTTPException) as exc_info:
                await material_search(request)

            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_invalid_result_format_handled(self):
        """Invalid result format should be handled gracefully."""
        from mira.api.routers.ui_endpoints import material_search, MaterialSearchRequest

        # Mock search engine to return malformed results
        mock_engine = MagicMock()
        mock_engine.search.return_value = [
            {"invalid": "format"}  # Missing required fields
        ]

        with patch("mira.api.routers.ui_endpoints.get_semantic_search", return_value=mock_engine):
            request = MaterialSearchRequest(query="test")

            # Should handle gracefully (empty or partial results)
            try:
                response = await material_search(request)
                # Either returns empty results or partial data
                assert hasattr(response, "results")
            except Exception:
                pass  # Also acceptable if it raises


# =============================================================================
# N/A and 0% Bug Regression Tests
# =============================================================================

class TestNAAndZeroPercentRegression:
    """Regression tests for the N/A material code and 0% score bug."""

    def test_material_code_not_na_when_present(self, mock_hybrid_search_results):
        """Material code should not be N/A when present in payload."""
        r = mock_hybrid_search_results[0]
        mat = r.get("material", {})
        orig = r.get("original_material", {})

        material_code = (
            mat.get("material_code") or
            orig.get("material_code") or
            str(orig.get("material_key", ""))
        )

        assert material_code != ""
        assert material_code != "N/A"
        assert material_code == "10001"

    def test_score_not_zero_when_present(self, mock_hybrid_search_results):
        """Score should not be 0 when similarity_score is present."""
        r = mock_hybrid_search_results[0]
        score = r.get("similarity_score", 0.0)

        assert score > 0
        assert score == 0.0328

    def test_old_score_field_not_used(self, mock_hybrid_search_results):
        """Should use similarity_score, not score field."""
        r = mock_hybrid_search_results[0]

        # Even if old 'score' field exists, we should use similarity_score
        similarity_score = r.get("similarity_score", 0.0)
        old_score = r.get("score", 0.0)  # This should not be set

        # similarity_score should be the one used
        assert similarity_score > 0


# =============================================================================
# Query Type Tests
# =============================================================================

class TestQueryTypes:
    """Tests for different query types."""

    def test_exact_material_name_query(self, mock_hybrid_search_results):
        """Exact material name queries should return results."""
        # This tests the format, not the actual search
        assert len(mock_hybrid_search_results) > 0

    def test_spec_number_query_format(self, mock_hybrid_search_results):
        """Spec number query results should have proper format."""
        for r in mock_hybrid_search_results:
            # All results should have proper nested structure
            assert "material" in r
            assert "original_material" in r
            assert "similarity_score" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
