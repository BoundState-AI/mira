#!/usr/bin/env python3
"""
Tests: Data Laundering Pipeline Models
Purpose: Schema validation tests for all pipeline-level Pydantic models.

BoundState AI 2026
Classification: BoundState Proprietary

Tests that:
  - All models enforce extra="forbid"
  - Required fields are validated
  - Enum values are constrained
  - Hash fields have correct length
  - Unknown fields cause rejection
"""

import hashlib
import uuid

import pytest

from data_laundering.models import (
    CandidateRecord,
    Citation,
    EnvironmentFilter,
    LayerTiming,
    PipelineEnvelope,
    PipelineStatus,
    PresentedResponse,
    QueryIntent,
    QueryType,
    ReasonerOutput,
    RejectionReason,
    SanitizedQuery,
    ValidatedRecord,
    ValidatedResults,
)


# =============================================================================
# SanitizedQuery Tests
# =============================================================================


class TestSanitizedQuery:
    """Tests for the Layer 1 output model."""

    def _make_hash(self, text: str = "test query") -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_valid_sanitized_query(self):
        q = SanitizedQuery(
            input_hash=self._make_hash(),
            query_type=QueryType.LOOKUP,
            intent=QueryIntent.MATERIAL_SEARCH,
            material_name="Inconel 718",
        )
        assert q.query_type == QueryType.LOOKUP
        assert q.intent == QueryIntent.MATERIAL_SEARCH
        assert q.material_name == "Inconel 718"

    def test_extra_fields_rejected(self):
        """extra='forbid' must kill queries with unknown fields."""
        with pytest.raises(Exception):
            SanitizedQuery(
                input_hash=self._make_hash(),
                query_type=QueryType.LOOKUP,
                intent=QueryIntent.MATERIAL_SEARCH,
                unknown_field="injection attempt",
            )

    def test_input_hash_length(self):
        """SHA-256 hash must be exactly 64 characters."""
        with pytest.raises(Exception):
            SanitizedQuery(
                input_hash="tooshort",
                query_type=QueryType.LOOKUP,
                intent=QueryIntent.GENERAL,
            )

    def test_hash_input_static_method(self):
        h = SanitizedQuery.hash_input("test query")
        assert len(h) == 64
        # Deterministic
        assert h == SanitizedQuery.hash_input("test query")
        # Different input -> different hash
        assert h != SanitizedQuery.hash_input("different query")

    def test_environment_filter_fluid_normalization(self):
        env = EnvironmentFilter(fluid_medium="  lox  ")
        assert env.fluid_medium == "LOX"

    def test_environment_filter_extra_rejected(self):
        with pytest.raises(Exception):
            EnvironmentFilter(temperature_c=25.0, rogue_field=True)

    def test_all_query_types_valid(self):
        for qt in QueryType:
            q = SanitizedQuery(
                input_hash=self._make_hash(),
                query_type=qt,
                intent=QueryIntent.GENERAL,
            )
            assert q.query_type == qt

    def test_all_intents_valid(self):
        for intent in QueryIntent:
            q = SanitizedQuery(
                input_hash=self._make_hash(),
                query_type=QueryType.LOOKUP,
                intent=intent,
            )
            assert q.intent == intent


# =============================================================================
# ReasonerOutput Tests
# =============================================================================


class TestReasonerOutput:
    """Tests for the Layer 2 output model."""

    def test_valid_reasoner_output(self):
        r = ReasonerOutput(
            candidates=[
                CandidateRecord(
                    material_key="INCONEL-718",
                    reasoning="High strength nickel alloy",
                    relevance_score=0.95,
                ),
            ],
            search_strategy="alloy family match",
        )
        assert len(r.candidates) == 1
        assert r.candidates[0].relevance_score == 0.95

    def test_empty_candidates_rejected(self):
        """At least one candidate is required."""
        with pytest.raises(Exception):
            ReasonerOutput(
                candidates=[],
                search_strategy="none",
            )

    def test_candidate_extra_rejected(self):
        with pytest.raises(Exception):
            CandidateRecord(
                material_key="TEST",
                reasoning="test",
                relevance_score=0.5,
                evil_field="injection",
            )

    def test_relevance_score_bounds(self):
        with pytest.raises(Exception):
            CandidateRecord(
                material_key="TEST",
                reasoning="test",
                relevance_score=1.5,
            )
        with pytest.raises(Exception):
            CandidateRecord(
                material_key="TEST",
                reasoning="test",
                relevance_score=-0.1,
            )


# =============================================================================
# ValidatedResults Tests
# =============================================================================


class TestValidatedResults:
    """Tests for the Layer 3 output model."""

    def _make_hash(self) -> str:
        return hashlib.sha256(b"test").hexdigest()

    def test_valid_validated_results(self):
        v = ValidatedResults(
            records=[
                ValidatedRecord(
                    material_key="INCONEL-718",
                    record_id="granta-001",
                    source="GRANTA",
                    confidence_score=0.87,
                ),
            ],
            query_hash=self._make_hash(),
            snapshot_hash=self._make_hash(),
            total_candidates=3,
            candidates_validated=1,
            candidates_rejected=2,
        )
        assert v.candidates_validated == 1
        assert v.candidates_rejected == 2

    def test_empty_records_allowed(self):
        """Zero validated records is valid (all candidates rejected)."""
        v = ValidatedResults(
            records=[],
            query_hash=self._make_hash(),
            snapshot_hash=self._make_hash(),
        )
        assert len(v.records) == 0

    def test_validated_record_extra_rejected(self):
        with pytest.raises(Exception):
            ValidatedRecord(
                material_key="TEST",
                record_id="r1",
                source="GRANTA",
                confidence_score=0.5,
                rogue="injection",
            )


# =============================================================================
# PresentedResponse Tests
# =============================================================================


class TestPresentedResponse:
    """Tests for the Layer 4 output model."""

    def test_valid_presented_response(self):
        p = PresentedResponse(
            response_text="Inconel 718 is suitable for LOX service.",
            citations=[
                Citation(
                    record_id="granta-001",
                    source="GRANTA",
                    claim="Compatible with LOX at 500 psi",
                ),
            ],
            warnings=["Record contains non-typed data"],
        )
        assert len(p.citations) == 1
        assert len(p.warnings) == 1

    def test_empty_response_rejected(self):
        with pytest.raises(Exception):
            PresentedResponse(response_text="")

    def test_citation_extra_rejected(self):
        with pytest.raises(Exception):
            Citation(
                record_id="r1",
                source="GRANTA",
                claim="test",
                evil="injection",
            )


# =============================================================================
# PipelineEnvelope Tests
# =============================================================================


class TestPipelineEnvelope:
    """Tests for the root audit artifact."""

    def _make_hash(self) -> str:
        return hashlib.sha256(b"test").hexdigest()

    def test_valid_envelope(self):
        e = PipelineEnvelope(
            domain="mira",
            input_hash=self._make_hash(),
        )
        assert e.domain == "mira"
        assert e.status == PipelineStatus.ERROR  # default
        assert e.layer_1_output is None

    def test_mark_completed(self):
        e = PipelineEnvelope(
            domain="mira",
            input_hash=self._make_hash(),
        )
        e.mark_completed(PipelineStatus.COMPLETED)
        assert e.status == PipelineStatus.COMPLETED
        assert e.pipeline_completed_at is not None
        assert e.total_duration_ms is not None
        assert e.total_duration_ms >= 0

    def test_add_layer_timing(self):
        e = PipelineEnvelope(
            domain="mira",
            input_hash=self._make_hash(),
        )
        t = LayerTiming(
            layer=1,
            layer_name="sanitize",
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:01+00:00",
            duration_ms=1000.0,
        )
        e.add_layer_timing(t)
        assert len(e.layer_timings) == 1
        assert e.layer_timings[0].layer == 1

    def test_envelope_extra_rejected(self):
        with pytest.raises(Exception):
            PipelineEnvelope(
                domain="mira",
                input_hash=self._make_hash(),
                evil_field="injection",
            )

    def test_all_pipeline_statuses(self):
        for status in PipelineStatus:
            e = PipelineEnvelope(
                domain="mira",
                input_hash=self._make_hash(),
                status=status,
            )
            assert e.status == status

    def test_all_rejection_reasons(self):
        for reason in RejectionReason:
            e = PipelineEnvelope(
                domain="mira",
                input_hash=self._make_hash(),
                rejection_reason=reason,
            )
            assert e.rejection_reason == reason
