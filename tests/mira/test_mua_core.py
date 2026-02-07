#!/usr/bin/env python3
"""
Module: Test Mua Core
Purpose: MUA Core Tests for BoundState

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

sys.path.insert(0, r"C:\BoundState")

from mira.mua import (
    generate_mua,
    MuaGenerationRequest,
    MuaGenerationResponse,
    EnvironmentSpec,
    MaterialRating,
)


class TestMuaGenerationBasic:
    """Basic MUA generation tests."""

    def test_generate_mua_returns_response(self):
        """generate_mua should return a MuaGenerationResponse."""
        request = MuaGenerationRequest(
            material_key="SS316L",
            material_name="Stainless Steel 316L",
            program="Gateway",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=101.3,
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="FLAMM", rating="A"),
                MaterialRating(test_class="TOX", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert isinstance(response, MuaGenerationResponse)
        assert response.material_key == "SS316L"
        assert response.program == "Gateway"

    def test_no_mua_needed_for_all_a_ratings(self):
        """Material with all A-ratings should not need MUA."""
        request = MuaGenerationRequest(
            material_key="SS316L",
            material_name="Stainless Steel 316L",
            program="Orion",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=101.3,
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="FLAMM", rating="A"),
                MaterialRating(test_class="TOX", rating="A"),
                MaterialRating(test_class="TVS", rating="A"),
                MaterialRating(test_class="SCC", rating="A"),
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert response.category == "N/A"
        assert len(response.gaps_identified) == 0
        assert "No MUA required" in response.rationale_summary


class TestMuaGapIdentification:
    """Tests for gap identification."""

    def test_identifies_non_a_ratings_as_gaps(self):
        """Non-A ratings should be identified as gaps."""
        request = MuaGenerationRequest(
            material_key="AL6061",
            program="Test",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=101.3,
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="FLAMM", rating="A"),
                MaterialRating(test_class="TOX", rating="B"),  # Gap
                MaterialRating(test_class="TVS", rating="C"),  # Gap
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert "TOX" in response.gaps_identified
        assert "TVS" in response.gaps_identified
        assert response.gaps_identified["TOX"] == "B"
        assert response.gaps_identified["TVS"] == "C"
        assert "FLAMM" not in response.gaps_identified  # A-rating, not a gap

    def test_generates_mitigations_for_gaps(self):
        """Each gap should have a corresponding mitigation."""
        request = MuaGenerationRequest(
            material_key="AL6061",
            program="Test",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=101.3,
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="TVS", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert len(response.mitigations) == 1
        assert response.mitigations[0].test_class == "TVS"
        assert response.mitigations[0].rating_gap == "B"


class TestMuaCategoryRouting:
    """Tests for MUA category routing per NASA-STD-6016C."""

    def test_category_iii_for_tvs_non_habitable(self):
        """TVS gap in non-habitable volume should route to Category III."""
        request = MuaGenerationRequest(
            material_key="Test Material",
            program="Test",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=101.3,
                habitable_volume=False,  # Non-habitable
            ),
            known_ratings=[
                MaterialRating(test_class="TVS", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert response.category == "III"
        assert "TVS-407" in response.appendix_b_exemptions

    def test_category_i_for_oxygen_enriched(self):
        """O2-enriched environment should route to Category I."""
        request = MuaGenerationRequest(
            material_key="Test Material",
            program="Test",
            environment=EnvironmentSpec(
                oxygen_pct=30.0,  # >23.5% = enriched
                pressure_kpa=101.3,
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="FLAMM", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert response.category == "I"

    def test_category_i_for_high_pressure(self):
        """High pressure (>300 kPa) should route to Category I."""
        request = MuaGenerationRequest(
            material_key="Test Material",
            program="Test",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=500.0,  # >300 kPa
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="FLAMM", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert response.category == "I"

    def test_category_i_for_lox_environment(self):
        """LOX environment should route to Category I."""
        request = MuaGenerationRequest(
            material_key="Test Material",
            program="Test",
            environment=EnvironmentSpec(
                fluid_medium="LOX",
                pressure_kpa=101.3,
                habitable_volume=False,
            ),
            known_ratings=[
                MaterialRating(test_class="FLAMM", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert response.category == "I"

    def test_category_ii_for_standard_conditions(self):
        """Standard ambient conditions should route to Category II."""
        request = MuaGenerationRequest(
            material_key="Test Material",
            program="Test",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=101.3,
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="CORR", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert response.success
        assert response.category == "II"


class TestMuaEvidence:
    """Tests for evidence generation."""

    def test_response_has_evidence(self):
        """Responses should include evidence items."""
        request = MuaGenerationRequest(
            material_key="SS316L",
            program="Test",
            environment=EnvironmentSpec(
                oxygen_pct=21.0,
                pressure_kpa=101.3,
                habitable_volume=True,
            ),
            known_ratings=[
                MaterialRating(test_class="TVS", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert len(response.evidence) > 0
        # Should have evidence for request and category routing
        source_ids = [e.source_id for e in response.evidence]
        assert "mua_generation_request" in source_ids

    def test_mitigation_references_nasa_std_6016(self):
        """Mitigations should reference NASA-STD-6016C."""
        request = MuaGenerationRequest(
            material_key="Test",
            program="Test",
            environment=EnvironmentSpec(habitable_volume=True),
            known_ratings=[
                MaterialRating(test_class="TVS", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert len(response.mitigations) > 0
        assert "NASA-STD-6016" in response.mitigations[0].source_document


class TestMuaRationale:
    """Tests for rationale generation."""

    def test_rationale_mentions_material(self):
        """Rationale should mention the material."""
        request = MuaGenerationRequest(
            material_key="SS316L",
            material_name="Stainless Steel 316L",
            program="Gateway",
            environment=EnvironmentSpec(habitable_volume=True),
            known_ratings=[
                MaterialRating(test_class="TVS", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert "Stainless Steel 316L" in response.rationale_summary

    def test_rationale_mentions_program(self):
        """Rationale should mention the program."""
        request = MuaGenerationRequest(
            material_key="SS316L",
            program="Gateway",
            environment=EnvironmentSpec(habitable_volume=True),
            known_ratings=[
                MaterialRating(test_class="TVS", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert "Gateway" in response.rationale_summary

    def test_rationale_mentions_category(self):
        """Rationale should mention the MUA category."""
        request = MuaGenerationRequest(
            material_key="SS316L",
            program="Test",
            environment=EnvironmentSpec(habitable_volume=True),
            known_ratings=[
                MaterialRating(test_class="TVS", rating="B"),
            ],
        )
        response = generate_mua(request)

        assert "Category" in response.rationale_summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
