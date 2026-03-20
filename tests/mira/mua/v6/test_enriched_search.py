#!/usr/bin/env python3
"""
Module: Test Enriched Search
Purpose: Tests for Enriched MUA Search (MUA v6).

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

import pytest
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.enriched_search import (
    FAMILY_MAP,
    FAMILY_MAP_REVERSE,
    SUPPORTING_DETERMINATIONS,
    CONFLICTING_DETERMINATIONS,
    EnrichedMUAResult,
    EnrichedSearchResults,
    EnrichedMUASearch,
    search_enriched_precedents,
)


class TestFamilyMap:
    """Tests for family mapping constants."""

    def test_family_map_stainless(self):
        """STAINLESS should map to stainless_steel."""
        assert FAMILY_MAP["STAINLESS"] == "stainless_steel"

    def test_family_map_titanium(self):
        """TITANIUM should map to titanium."""
        assert FAMILY_MAP["TITANIUM"] == "titanium"

    def test_family_map_nickel(self):
        """NICKEL should map to nickel."""
        assert FAMILY_MAP["NICKEL"] == "nickel"

    def test_family_map_reverse_stainless(self):
        """stainless_steel should reverse to STAINLESS."""
        assert FAMILY_MAP_REVERSE["stainless_steel"] == "STAINLESS"

    def test_family_map_reverse_inconel(self):
        """inconel should reverse to NICKEL (nickel alloy family)."""
        assert FAMILY_MAP_REVERSE["inconel"] == "NICKEL"

    def test_all_forward_maps_have_reverse(self):
        """All forward map values should have reverse entries."""
        for k, v in FAMILY_MAP.items():
            assert v in FAMILY_MAP_REVERSE, f"Missing reverse for {k} -> {v}"


class TestDeterminationSets:
    """Tests for determination classification sets."""

    def test_approved_is_supporting(self):
        """APPROVED should be in supporting set."""
        assert "APPROVED" in SUPPORTING_DETERMINATIONS

    def test_approved_with_limits_is_supporting(self):
        """APPROVED_WITH_LIMITS should be in supporting set."""
        assert "APPROVED_WITH_LIMITS" in SUPPORTING_DETERMINATIONS

    def test_rejected_is_conflicting(self):
        """REJECTED should be in conflicting set."""
        assert "REJECTED" in CONFLICTING_DETERMINATIONS

    def test_no_overlap(self):
        """Supporting and conflicting should not overlap."""
        overlap = SUPPORTING_DETERMINATIONS & CONFLICTING_DETERMINATIONS
        assert len(overlap) == 0, f"Unexpected overlap: {overlap}"


class TestEnrichedMUAResult:
    """Tests for EnrichedMUAResult dataclass."""

    def _make_mock_search_result(self, determination="APPROVED", material_family="inconel"):
        """Create a mock MUASearchResult."""
        from mira.miul.mua_faiss_search import MUASearchResult

        return MUASearchResult(
            rank=1,
            score=0.5,
            semantic_score=0.3,
            string_score=0.7,
            file="test.pdf",
            mua_number="MUA-001",
            material_designation="INCONEL 625",
            material_family=material_family,
            is_umbrella=False,
            environment="Oxygen",
            category="I",
            determination=determination,
            rationale="Test rationale",
            application="Test application",
        )

    def test_from_approved_result(self):
        """APPROVED result should be marked supporting."""
        base = self._make_mock_search_result(determination="APPROVED")
        enriched = EnrichedMUAResult.from_search_result(base, rank=1)

        assert enriched.is_supporting
        assert not enriched.is_conflicting
        assert enriched.determination == "APPROVED"

    def test_from_approved_with_limits_result(self):
        """APPROVED_WITH_LIMITS should be marked supporting."""
        base = self._make_mock_search_result(determination="APPROVED_WITH_LIMITS")
        enriched = EnrichedMUAResult.from_search_result(base, rank=1)

        assert enriched.is_supporting
        assert not enriched.is_conflicting

    def test_from_rejected_result(self):
        """REJECTED result should be marked conflicting."""
        base = self._make_mock_search_result(determination="REJECTED")
        enriched = EnrichedMUAResult.from_search_result(base, rank=1)

        assert not enriched.is_supporting
        assert enriched.is_conflicting

    def test_from_unknown_result(self):
        """UNKNOWN/other determination should be neither."""
        base = self._make_mock_search_result(determination="DEFERRED")
        enriched = EnrichedMUAResult.from_search_result(base, rank=1)

        assert not enriched.is_supporting
        assert not enriched.is_conflicting

    def test_family_normalized_to_uppercase(self):
        """Material family should be normalized to uppercase."""
        base = self._make_mock_search_result(material_family="inconel")
        enriched = EnrichedMUAResult.from_search_result(base, rank=1)

        assert enriched.material_family == "NICKEL"  # inconel -> NICKEL
        assert enriched.material_family_raw == "inconel"

    def test_family_stainless_normalized(self):
        """stainless_steel should normalize to STAINLESS."""
        base = self._make_mock_search_result(material_family="stainless_steel")
        enriched = EnrichedMUAResult.from_search_result(base, rank=1)

        assert enriched.material_family == "STAINLESS"
        assert enriched.material_family_raw == "stainless_steel"

    def test_source_includes_file(self):
        """Source field should include the file for traceability."""
        base = self._make_mock_search_result()
        enriched = EnrichedMUAResult.from_search_result(base, rank=1)

        assert "MUAFAISSSearch" in enriched.source
        assert "test.pdf" in enriched.source


class TestEnrichedSearchResults:
    """Tests for EnrichedSearchResults collection."""

    def test_empty_results(self):
        """Empty results should have correct defaults."""
        results = EnrichedSearchResults(
            query_material="INCONEL 625",
            query_environment="Oxygen",
            query_family="NICKEL",
        )

        assert not results.has_supporting_precedent
        assert not results.has_conflicting_precedent
        assert results.supporting_count == 0
        assert results.conflicting_count == 0
        assert results.total_count == 0

    def test_with_supporting(self):
        """Should correctly report supporting precedent."""
        results = EnrichedSearchResults(
            query_material="INCONEL 625",
            query_environment="Oxygen",
            query_family=None,
        )

        # Add a mock supporting result
        supporting = EnrichedMUAResult(
            rank=1, score=0.5, semantic_score=0.3, string_score=0.7,
            file="test.pdf", mua_number="MUA-001",
            material_designation="INCONEL 625", material_family="NICKEL",
            material_family_raw="inconel", is_umbrella=False,
            environment="Oxygen", category="I", determination="APPROVED",
            rationale=None, application=None, is_supporting=True, is_conflicting=False,
        )
        results.all_results.append(supporting)
        results.supporting.append(supporting)

        assert results.has_supporting_precedent
        assert not results.has_conflicting_precedent
        assert results.supporting_count == 1
        assert results.total_count == 1

    def test_get_best_supporting(self):
        """get_best_supporting should return first (best) result."""
        results = EnrichedSearchResults(
            query_material="TEST",
            query_environment=None,
            query_family=None,
        )

        result1 = EnrichedMUAResult(
            rank=1, score=0.3, semantic_score=0.2, string_score=0.8,
            file="best.pdf", mua_number="MUA-BEST",
            material_designation="TEST", material_family=None,
            material_family_raw=None, is_umbrella=False,
            environment=None, category=None, determination="APPROVED",
            rationale=None, application=None, is_supporting=True, is_conflicting=False,
        )
        result2 = EnrichedMUAResult(
            rank=2, score=0.6, semantic_score=0.4, string_score=0.5,
            file="second.pdf", mua_number="MUA-SECOND",
            material_designation="TEST", material_family=None,
            material_family_raw=None, is_umbrella=False,
            environment=None, category=None, determination="APPROVED",
            rationale=None, application=None, is_supporting=True, is_conflicting=False,
        )
        results.supporting.extend([result1, result2])

        best = results.get_best_supporting()
        assert best is not None
        assert best.mua_number == "MUA-BEST"

    def test_get_best_supporting_none(self):
        """get_best_supporting should return None if no supporting."""
        results = EnrichedSearchResults(
            query_material="TEST",
            query_environment=None,
            query_family=None,
        )
        assert results.get_best_supporting() is None


class TestEnrichedMUASearch:
    """Tests for EnrichedMUASearch class."""

    def test_normalize_family_uppercase(self):
        """Should normalize uppercase family names to FAISS format."""
        search = EnrichedMUASearch(search=MagicMock())

        assert search.normalize_family("STAINLESS") == "stainless_steel"
        assert search.normalize_family("TITANIUM") == "titanium"
        assert search.normalize_family("NICKEL") == "nickel"

    def test_normalize_family_none(self):
        """Should handle None family."""
        search = EnrichedMUASearch(search=MagicMock())
        assert search.normalize_family(None) is None

    def test_normalize_family_unknown(self):
        """Unknown family should be lowercased."""
        search = EnrichedMUASearch(search=MagicMock())
        assert search.normalize_family("UNKNOWN") == "unknown"

    def test_normalize_family_to_lookup(self):
        """Should normalize to lookup service format."""
        search = EnrichedMUASearch(search=MagicMock())

        assert search.normalize_family_to_lookup("stainless_steel") == "STAINLESS"
        assert search.normalize_family_to_lookup("inconel") == "NICKEL"

    @patch("mira.mua.v6.enriched_search.MUAFAISSSearch")
    def test_search_splits_results(self, mock_faiss_class):
        """Search should split results by determination."""
        from mira.miul.mua_faiss_search import MUASearchResult

        # Create mock search results
        approved = MUASearchResult(
            rank=1, score=0.3, semantic_score=0.2, string_score=0.8,
            file="approved.pdf", mua_number="MUA-APPROVED",
            material_designation="INC 625", material_family="inconel",
            is_umbrella=False, environment="O2", category="I",
            determination="APPROVED", rationale=None, application=None,
        )
        rejected = MUASearchResult(
            rank=2, score=0.5, semantic_score=0.4, string_score=0.6,
            file="rejected.pdf", mua_number="MUA-REJECTED",
            material_designation="INC 625", material_family="inconel",
            is_umbrella=False, environment="O2", category="III",
            determination="REJECTED", rationale=None, application=None,
        )
        deferred = MUASearchResult(
            rank=3, score=0.7, semantic_score=0.6, string_score=0.4,
            file="deferred.pdf", mua_number="MUA-DEFERRED",
            material_designation="INC 625", material_family="inconel",
            is_umbrella=False, environment="O2", category="II",
            determination="DEFERRED", rationale=None, application=None,
        )

        mock_search = MagicMock()
        mock_search.search.return_value = [approved, rejected, deferred]

        enriched_search = EnrichedMUASearch(search=mock_search)
        results = enriched_search.search("INCONEL 625", "Oxygen")

        assert results.has_supporting_precedent
        assert results.has_conflicting_precedent
        assert results.supporting_count == 1
        assert results.conflicting_count == 1
        assert len(results.other) == 1

    @patch("mira.mua.v6.enriched_search.MUAFAISSSearch")
    def test_search_with_family_filter(self, mock_faiss_class):
        """Search should normalize and pass family filter."""
        mock_search = MagicMock()
        mock_search.search.return_value = []

        enriched_search = EnrichedMUASearch(search=mock_search)
        enriched_search.search("316L SST", family_filter="STAINLESS")

        # Should have normalized STAINLESS -> stainless_steel
        call_kwargs = mock_search.search.call_args[1]
        assert call_kwargs["family_filter"] == "stainless_steel"


class TestSearchEnrichedPrecedents:
    """Tests for convenience function."""

    @patch("mira.mua.v6.enriched_search.EnrichedMUASearch")
    def test_creates_search_and_calls(self, mock_search_class):
        """Convenience function should create search and call it."""
        mock_instance = MagicMock()
        mock_instance.search.return_value = EnrichedSearchResults(
            query_material="TEST",
            query_environment=None,
            query_family=None,
        )
        mock_search_class.return_value = mock_instance

        result = search_enriched_precedents("TEST", k=5)

        mock_search_class.assert_called_once()
        mock_instance.search.assert_called_once()
        assert isinstance(result, EnrichedSearchResults)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
