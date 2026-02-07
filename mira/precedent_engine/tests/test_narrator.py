#!/usr/bin/env python3
"""
Module: Test Narrator
Purpose: test_narrator

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import pytest

from mira.precedent_engine.core.narrator import MockNarratorLLM
from mira.precedent_engine.models.precedent import PrecedentMatch, PrecedentRetrievalResult, PrecedentStatistics
from mira.precedent_engine.models.enums import DeviationType, PrecedentAdequacyLevel, ProgramFamily
from mira.precedent_engine.tests.conftest import make_enriched_mua
import uuid


def make_precedent_match(
    contract_id: str = "MATCH-001",
    similarity_score: float = 0.9,
    rationale_text: str | None = "Test rationale from precedent.",
) -> PrecedentMatch:
    """Factory function to create PrecedentMatch for testing."""
    return PrecedentMatch(
        contract_id=contract_id,
        material_name="CRES 316L",
        material_key="SS316L",
        tier=1,
        similarity_score=similarity_score,
        material_equivalent=True,
        environment_equivalent=True,
        deviation_equivalent=True,
        program_weight=1.0,
        media="GOX",
        o2_pct=99.5,
        location_class="non_habitable",
        temp_max_f=500.0,
        temp_min_f=70.0,
        pressure_max_psia=3000.0,
        is_rejected=False,
        is_superseded=False,
        available_rationale_types=[DeviationType.FLAMMABILITY],
        rationale_text=rationale_text,
        source_program="Orion",
        source_program_family=ProgramFamily.ORION_ARTEMIS,
        category="I",
    )


def make_retrieval_result(
    tier1_count: int = 3,
    adequacy: PrecedentAdequacyLevel = PrecedentAdequacyLevel.STRONG,
) -> PrecedentRetrievalResult:
    """Factory function to create PrecedentRetrievalResult for testing."""
    return PrecedentRetrievalResult(
        query_material_key="SS316L",
        query_material_name="CRES 316L",
        query_environment_summary="GOX, 500°F max, 3000 psia, Non Habitable",
        statistics=PrecedentStatistics(
            n_total_with_material=100,
            n_approved=98,
            n_rejected=2,
            approval_rate=0.98,
        ),
        n_total_candidates=tier1_count,
        n_tier1=tier1_count,
        n_tier2=0,
        n_tier3=0,
        n_rejected_in_set=0,
        n_superseded_in_set=0,
        n_unique_programs=3,
        n_unique_test_sources=5,
        adequacy=adequacy,
        adequacy_reasoning="Test adequacy reasoning",
        tier1_matches=[make_precedent_match(f"MATCH-{i}") for i in range(tier1_count)],
    )


class TestMockNarrator:
    """Tests for MockNarratorLLM."""

    @pytest.mark.asyncio
    async def test_generates_rationale(self):
        """Mock narrator generates rationale from precedents."""
        query = make_enriched_mua()
        precedents = [
            make_precedent_match("MATCH-1", rationale_text="Rationale from match 1."),
            make_precedent_match("MATCH-2", rationale_text="Rationale from match 2."),
        ]
        retrieval = make_retrieval_result()

        narrator = MockNarratorLLM()
        result = await narrator.generate_rationale(query, precedents, retrieval)

        assert "rationale_text" in result
        assert len(result["rationale_text"]) > 0
        assert "citations" in result
        assert "MATCH-1" in result["citations"]
        assert "MATCH-2" in result["citations"]

    @pytest.mark.asyncio
    async def test_flags_no_precedents(self):
        """Mock narrator flags gap when no precedents."""
        query = make_enriched_mua()
        precedents = []
        retrieval = make_retrieval_result(tier1_count=0, adequacy=PrecedentAdequacyLevel.INSUFFICIENT)

        narrator = MockNarratorLLM()
        result = await narrator.generate_rationale(query, precedents, retrieval)

        assert len(result["gaps"]) > 0
        assert "No precedents" in result["gaps"][0]

    @pytest.mark.asyncio
    async def test_flags_no_tier1(self):
        """Mock narrator flags gap when no Tier 1 matches."""
        query = make_enriched_mua()
        precedents = [make_precedent_match()]

        retrieval = PrecedentRetrievalResult(
            query_material_key="SS316L",
            query_material_name="CRES 316L",
            query_environment_summary="GOX, 500°F max",
            statistics=PrecedentStatistics(),
            n_total_candidates=1,
            n_tier1=0,
            n_tier2=1,
            n_tier3=0,
            n_rejected_in_set=0,
            n_superseded_in_set=0,
            n_unique_programs=1,
            n_unique_test_sources=1,
            adequacy=PrecedentAdequacyLevel.MODERATE,
            adequacy_reasoning="Only Tier 2 matches",
        )

        narrator = MockNarratorLLM()
        result = await narrator.generate_rationale(query, precedents, retrieval)

        assert len(result["gaps"]) > 0
        assert "Tier 1" in result["gaps"][0]

    @pytest.mark.asyncio
    async def test_includes_confidence_note(self):
        """Mock narrator includes confidence note."""
        query = make_enriched_mua()
        precedents = [make_precedent_match()]
        retrieval = make_retrieval_result(tier1_count=1)

        narrator = MockNarratorLLM()
        result = await narrator.generate_rationale(query, precedents, retrieval)

        assert "confidence_note" in result
        assert "1 precedent" in result["confidence_note"]
