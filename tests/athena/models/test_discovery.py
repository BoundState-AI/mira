#!/usr/bin/env python3
"""
Module: Test Discovery
Purpose: Tests for athena.models.discovery module.

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from datetime import datetime

import pytest

from athena.models.discovery import (
    BatchDiscoveryState,
    CorpusProfile,
    DiscoveryAggregator,
    DiscoveryResult,
)


class TestDiscoveryResult:
    """Tests for DiscoveryResult model."""

    def test_minimal_discovery_result(self):
        """Create DiscoveryResult with minimal fields."""
        result = DiscoveryResult(page=1, document_type="unknown")

        assert result.page == 1
        assert result.document_type == "unknown"
        assert result.era_estimate is None
        assert result.entities_found == {}
        assert result.vocabulary_notes == []

    def test_full_discovery_result(self, sample_discovery_result):
        """Create DiscoveryResult with all fields."""
        assert sample_discovery_result.page == 1
        assert sample_discovery_result.document_type == "memorandum"
        assert sample_discovery_result.era_estimate == "1980s"
        assert "equipment" in sample_discovery_result.entities_found
        assert "Apollo CSM" in sample_discovery_result.entities_found["equipment"]
        assert sample_discovery_result.form_number == "NASA-1234"

    def test_discovery_result_serialization(self, sample_discovery_result):
        """DiscoveryResult can be serialized to dict."""
        data = sample_discovery_result.model_dump()

        assert isinstance(data, dict)
        assert data["page"] == 1
        assert data["document_type"] == "memorandum"
        assert "entities_found" in data


class TestCorpusProfile:
    """Tests for CorpusProfile dataclass."""

    def test_corpus_profile_defaults(self):
        """CorpusProfile has sensible defaults."""
        profile = CorpusProfile()

        assert profile.document_types == {}
        assert profile.entity_patterns == {}
        assert profile.vocabulary == {}
        assert profile.form_numbers == {}
        assert profile.date_range == (None, None)
        assert profile.condition_breakdown == {}
        assert profile.total_pages == 0

    def test_corpus_profile_with_data(self):
        """CorpusProfile stores aggregated data."""
        profile = CorpusProfile(
            document_types={"memorandum": 50, "report": 30},
            entity_patterns={"equipment": ["Apollo CSM", "LM-5"]},
            vocabulary={"EVA": 100, "CSM": 80},
            total_pages=100,
        )

        assert profile.document_types["memorandum"] == 50
        assert "Apollo CSM" in profile.entity_patterns["equipment"]
        assert profile.vocabulary["EVA"] == 100
        assert profile.total_pages == 100


class TestDiscoveryAggregator:
    """Tests for DiscoveryAggregator incremental aggregation."""

    def test_aggregator_initialization(self):
        """Aggregator initializes with empty state."""
        agg = DiscoveryAggregator()

        assert agg.total_pages == 0
        assert len(agg.document_types) == 0
        assert len(agg.vocabulary) == 0

    def test_add_discovery_result_incremental(self, sample_discovery_result):
        """Results accumulate correctly."""
        agg = DiscoveryAggregator()

        agg.add_discovery_result(sample_discovery_result)

        assert agg.total_pages == 1
        assert agg.document_types["memorandum"] == 1

    def test_add_discovery_result_from_dict(self):
        """Can add result from dict (LLM output)."""
        agg = DiscoveryAggregator()

        result_dict = {
            "page": 1,
            "document_type": "report",
            "entities_found": {"people": ["J. Smith"]},
            "vocabulary_notes": ["technical", "engineering"],
        }

        agg.add_discovery_result(result_dict)

        assert agg.total_pages == 1
        assert agg.document_types["report"] == 1
        assert "technical" in agg.vocabulary

    def test_add_multiple_results(self, sample_discovery_result):
        """Multiple results aggregate counts."""
        agg = DiscoveryAggregator()

        # Add same type twice
        agg.add_discovery_result(sample_discovery_result)
        agg.add_discovery_result(sample_discovery_result)

        assert agg.total_pages == 2
        assert agg.document_types["memorandum"] == 2

    def test_stop_word_filtering(self):
        """Common words excluded from vocabulary."""
        agg = DiscoveryAggregator()

        result = {
            "page": 1,
            "document_type": "memo",
            "vocabulary_notes": ["the", "and", "technical", "CSM"],
        }

        agg.add_discovery_result(result)

        # "the" and "and" should be filtered
        assert "the" not in agg.vocabulary
        assert "and" not in agg.vocabulary
        # Technical terms should remain
        assert "technical" in agg.vocabulary or "csm" in agg.vocabulary

    def test_vocabulary_normalized_lowercase(self):
        """Vocabulary terms are normalized to lowercase."""
        agg = DiscoveryAggregator()

        result = {
            "page": 1,
            "document_type": "memo",
            "vocabulary_notes": ["NASA", "Apollo"],
        }

        agg.add_discovery_result(result)

        assert "nasa" in agg.vocabulary
        assert "apollo" in agg.vocabulary

    def test_build_profile_from_aggregated(self, sample_discovery_result):
        """Profile construction from multiple results."""
        agg = DiscoveryAggregator()

        agg.add_discovery_result(sample_discovery_result)
        agg.add_discovery_result({
            "page": 2,
            "document_type": "report",
            "entities_found": {"equipment": ["LM-5"]},
            "vocabulary_notes": ["test"],
        })

        profile = agg.build_profile()

        assert isinstance(profile, CorpusProfile)
        assert profile.total_pages == 2
        assert "memorandum" in profile.document_types
        assert "report" in profile.document_types

    def test_empty_aggregator_produces_valid_profile(self):
        """Empty aggregator produces valid but empty profile."""
        agg = DiscoveryAggregator()

        profile = agg.build_profile()

        assert isinstance(profile, CorpusProfile)
        assert profile.total_pages == 0
        assert profile.document_types == {}
        assert profile.date_range == (None, None)

    def test_entity_patterns_extraction(self):
        """Entity patterns are extracted and deduplicated."""
        agg = DiscoveryAggregator()

        # Add same entity multiple times
        for i in range(3):
            agg.add_discovery_result({
                "page": i + 1,
                "document_type": "memo",
                "entities_found": {"equipment": ["Apollo CSM", "LM-5"]},
            })

        profile = agg.build_profile()

        assert "equipment" in profile.entity_patterns
        # Should include Apollo CSM and LM-5
        assert len(profile.entity_patterns["equipment"]) <= 2

    def test_date_range_extraction(self):
        """Date range is extracted from dates entities."""
        agg = DiscoveryAggregator()

        agg.add_discovery_result({
            "page": 1,
            "document_type": "memo",
            "entities_found": {"dates": ["1980-01-15", "1982-06-20"]},
        })
        agg.add_discovery_result({
            "page": 2,
            "document_type": "memo",
            "entities_found": {"dates": ["1979-03-01"]},
        })

        profile = agg.build_profile()

        # Should have min and max dates
        earliest, latest = profile.date_range
        assert earliest == "1979-03-01"
        assert latest == "1982-06-20"

    def test_condition_notes_aggregation(self):
        """Condition notes are counted."""
        agg = DiscoveryAggregator()

        agg.add_discovery_result({
            "page": 1,
            "document_type": "memo",
            "condition_notes": ["typed", "clear"],
        })
        agg.add_discovery_result({
            "page": 2,
            "document_type": "memo",
            "condition_notes": ["typed", "faded"],
        })

        profile = agg.build_profile()

        assert profile.condition_breakdown["typed"] == 2
        assert profile.condition_breakdown["clear"] == 1
        assert profile.condition_breakdown["faded"] == 1


class TestBatchDiscoveryState:
    """Tests for BatchDiscoveryState incremental state."""

    def test_batch_discovery_state_creation(self):
        """Create BatchDiscoveryState."""
        state = BatchDiscoveryState(batch_id="batch-001")

        assert state.batch_id == "batch-001"
        assert state.total_pages == 0
        assert state.pages_discovered == 0
        assert state.results == []
        assert state.profile is None
        assert state.processing_complete is False

    def test_add_result_updates_counter(self, sample_discovery_result):
        """add_result updates pages_discovered."""
        state = BatchDiscoveryState(batch_id="batch-001", total_pages=10)

        state.add_result(sample_discovery_result)

        assert state.pages_discovered == 1
        assert len(state.results) == 1

    def test_add_multiple_results(self, sample_discovery_result):
        """Multiple results accumulate."""
        state = BatchDiscoveryState(batch_id="batch-001", total_pages=5)

        for _ in range(3):
            state.add_result(sample_discovery_result)

        assert state.pages_discovered == 3
        assert len(state.results) == 3

    def test_batch_discovery_state_serialization(self, sample_discovery_result):
        """BatchDiscoveryState can be serialized."""
        state = BatchDiscoveryState(batch_id="batch-001")
        state.add_result(sample_discovery_result)

        data = state.model_dump()

        assert isinstance(data, dict)
        assert data["batch_id"] == "batch-001"
        assert data["pages_discovered"] == 1

    def test_batch_discovery_state_timestamps(self):
        """BatchDiscoveryState has timestamps."""
        state = BatchDiscoveryState(batch_id="batch-001")

        assert isinstance(state.started_at, datetime)
        assert state.completed_at is None

        state.completed_at = datetime.utcnow()
        assert isinstance(state.completed_at, datetime)
