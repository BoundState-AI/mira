#!/usr/bin/env python3
"""
Module: Test Precedent Engine
Purpose: test_precedent_engine

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import pytest

from mira.precedent_engine.core.precedent_engine import PrecedentEngine
from mira.precedent_engine.models.config import (
    PrecedentAdequacyConfig,
    PrecedentEquivalenceConfig,
)
from mira.precedent_engine.models.enums import DeviationType, PrecedentAdequacyLevel, ProgramFamily
from mira.precedent_engine.tests.conftest import make_enriched_mua
import uuid


class TestTierAssignment:
    """Tests for tier assignment logic."""

    def test_tier1_exact_match(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Exact material + environment + deviation = Tier 1."""
        query = make_enriched_mua(
            material_key="SS316L",
            media="GOX",
            deviation_types=[DeviationType.FLAMMABILITY],
        )
        cand = make_enriched_mua(
            material_key="SS316L",
            media="GOX",
            deviation_types=[DeviationType.FLAMMABILITY],
        )

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.n_tier1 == 1
        assert result.tier1_matches[0].tier == 1

    def test_tier2_different_temperature(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Same material, significantly different temperature = Tier 2."""
        query = make_enriched_mua(material_key="SS316L", temp_max_f=500.0)
        cand = make_enriched_mua(material_key="SS316L", temp_max_f=300.0)

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        # With default config (0% tier1 temp tolerance), this should be tier 2
        assert result.n_tier1 == 0
        assert result.n_tier2 == 1

    def test_tier2_different_pressure(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Same material, different pressure = Tier 2."""
        query = make_enriched_mua(material_key="SS316L", pressure_max_psia=3000.0)
        cand = make_enriched_mua(material_key="SS316L", pressure_max_psia=1000.0)

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.n_tier1 == 0
        assert result.n_tier2 == 1

    def test_tier3_different_material(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Different material = Tier 3 (analog)."""
        query = make_enriched_mua(material_key="SS316L")
        cand = make_enriched_mua(material_key="SS304L")

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.n_tier1 == 0
        assert result.n_tier2 == 0
        assert result.n_tier3 == 1

    def test_rejected_mua_tier3_max(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Rejected MUAs are Tier 3 at best."""
        query = make_enriched_mua(material_key="SS316L")
        cand = make_enriched_mua(material_key="SS316L", is_rejected=True)

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.n_tier1 == 0
        assert result.n_tier2 == 0
        assert result.n_tier3 == 1
        assert result.tier3_matches[0].is_rejected is True


class TestNameBasedMatching:
    """Tests for Addendum B: Name-based matching restrictions."""

    def test_name_match_no_tier1(
        self, default_equivalence_config, default_adequacy_config
    ):
        """
        Name-based matching SHALL NOT produce Tier 1 matches.
        Per Addendum B, Tier 1 requires validated material_key match.
        """
        query = make_enriched_mua(
            material_name="316L CRES",
            material_key=None,  # No validated key
        )
        cand = make_enriched_mua(
            material_name="316L CRES",
            material_key=None,  # No validated key
        )

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        # Should NOT be Tier 1 per Addendum B
        assert result.n_tier1 == 0
        # May be Tier 2 or 3 based on name fallback
        assert result.n_tier2 + result.n_tier3 >= 1

    def test_key_match_allows_tier1(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Validated key match allows Tier 1."""
        query = make_enriched_mua(
            material_name="316L CRES",
            material_key="SS316L",
        )
        cand = make_enriched_mua(
            material_name="CRES 316L",  # Different name format
            material_key="SS316L",  # Same key
        )

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.n_tier1 == 1


class TestAdequacyClassification:
    """Tests for adequacy classification logic."""

    def test_adequacy_strong(self, default_equivalence_config, default_adequacy_config):
        """Many Tier 1 matches = STRONG adequacy."""
        query = make_enriched_mua(material_key="SS316L")
        candidates = [
            make_enriched_mua(
                contract_id=f"CAND-{i}",
                material_key="SS316L",
                program=f"Program-{i % 3}",  # 3 unique programs
            )
            for i in range(10)
        ]

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, candidates)

        assert result.adequacy == PrecedentAdequacyLevel.STRONG
        assert result.n_tier1 == 10

    def test_adequacy_moderate_tier2_only(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Tier 2 matches cap at MODERATE per config."""
        query = make_enriched_mua(material_key="SS316L", temp_max_f=500.0)
        candidates = [
            make_enriched_mua(
                contract_id=f"CAND-{i}",
                material_key="SS316L",
                temp_max_f=300.0,  # Tier 2
                program=f"Program-{i % 3}",
            )
            for i in range(10)
        ]

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, candidates)

        # Tier 2 max adequacy is MODERATE
        assert result.adequacy == PrecedentAdequacyLevel.MODERATE

    def test_adequacy_insufficient_no_matches(
        self, default_equivalence_config, default_adequacy_config
    ):
        """No matches = INSUFFICIENT."""
        query = make_enriched_mua(material_key="EXOTIC-001")
        candidates = [
            make_enriched_mua(contract_id=f"CAND-{i}", material_key="SS316L")
            for i in range(10)
        ]

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, candidates)

        assert result.adequacy == PrecedentAdequacyLevel.INSUFFICIENT

    def test_adequacy_insufficient_tier3_only(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Only Tier 3 matches = INSUFFICIENT per config."""
        query = make_enriched_mua(material_key="SS316L")
        candidates = [
            make_enriched_mua(
                contract_id=f"CAND-{i}",
                material_key="SS304L",  # Different material = Tier 3
            )
            for i in range(10)
        ]

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, candidates)

        assert result.adequacy == PrecedentAdequacyLevel.INSUFFICIENT
        assert "Tier 3" in result.adequacy_reasoning

    def test_adequacy_high_rejection_rate(
        self, default_equivalence_config, default_adequacy_config
    ):
        """High rejection rate blocks STRONG adequacy."""
        query = make_enriched_mua(material_key="SS316L")

        # 7 approved, 3 rejected = 30% rejection
        candidates = []
        for i in range(7):
            candidates.append(
                make_enriched_mua(
                    contract_id=f"APPROVED-{i}",
                    material_key="SS316L",
                    is_rejected=False,
                    program=f"Program-{i % 3}",
                )
            )
        for i in range(3):
            candidates.append(
                make_enriched_mua(
                    contract_id=f"REJECTED-{i}",
                    material_key="SS316L",
                    is_rejected=True,
                )
            )

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, candidates)

        # 30% rejection > 0% threshold for STRONG
        # Should be MODERATE at best due to rejections
        assert result.adequacy != PrecedentAdequacyLevel.STRONG


class TestDeviationEquivalence:
    """Tests for deviation type equivalence."""

    def test_same_deviation_types(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Same deviation types = equivalent."""
        query = make_enriched_mua(
            deviation_types=[DeviationType.FLAMMABILITY, DeviationType.OFFGASSING]
        )
        cand = make_enriched_mua(
            deviation_types=[DeviationType.FLAMMABILITY, DeviationType.OFFGASSING]
        )

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.n_tier1 == 1

    def test_different_deviation_types_no_tier1(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Different deviation types = not Tier 1."""
        query = make_enriched_mua(deviation_types=[DeviationType.FLAMMABILITY])
        cand = make_enriched_mua(deviation_types=[DeviationType.OFFGASSING])

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.n_tier1 == 0

    def test_subset_deviation_allows_tier2(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Query deviation subset of candidate allows Tier 2."""
        query = make_enriched_mua(
            deviation_types=[DeviationType.FLAMMABILITY],
            temp_max_f=500.0,  # Force Tier 2 via temp
        )
        cand = make_enriched_mua(
            deviation_types=[DeviationType.FLAMMABILITY, DeviationType.OFFGASSING],
            temp_max_f=300.0,
        )

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        # Should be Tier 2 (subset allowed for Tier 2)
        assert result.n_tier2 == 1


class TestProgramWeight:
    """Tests for cross-program precedent weighting."""

    def test_same_program_full_weight(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Same program = 1.0 weight."""
        query = make_enriched_mua(program_family=ProgramFamily.ORION_ARTEMIS)
        cand = make_enriched_mua(program_family=ProgramFamily.ORION_ARTEMIS)

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        assert result.tier1_matches[0].program_weight == 1.0

    def test_cross_program_reduced_weight(
        self, default_equivalence_config, default_adequacy_config
    ):
        """Cross-program = reduced weight."""
        query = make_enriched_mua(program_family=ProgramFamily.ORION_ARTEMIS)
        cand = make_enriched_mua(program_family=ProgramFamily.SHUTTLE)

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, [cand])

        # Should have reduced weight per config
        assert result.tier1_matches[0].program_weight < 1.0


class TestStatistics:
    """Tests for precedent statistics computation."""

    def test_statistics_counts(self, default_equivalence_config, default_adequacy_config):
        """Statistics correctly count approved/rejected."""
        query = make_enriched_mua(material_key="SS316L")
        candidates = [
            make_enriched_mua(
                contract_id="APPROVED-1", material_key="SS316L", is_rejected=False
            ),
            make_enriched_mua(
                contract_id="APPROVED-2", material_key="SS316L", is_rejected=False
            ),
            make_enriched_mua(
                contract_id="REJECTED-1", material_key="SS316L", is_rejected=True
            ),
        ]

        engine = PrecedentEngine(default_equivalence_config, default_adequacy_config)
        result = engine.evaluate_candidates(query, candidates)

        stats = result.statistics
        assert stats.n_total_with_material == 3
        assert stats.n_approved == 2
        assert stats.n_rejected == 1
        assert stats.approval_rate == pytest.approx(2 / 3, rel=0.01)
