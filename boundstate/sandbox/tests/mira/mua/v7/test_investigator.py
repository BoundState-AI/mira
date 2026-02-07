"""Tests for MUA v7 investigator.

The investigator orchestrates the evidence-gathering step of the MUA
wizard.  Given a material and environment, it queries MAPTIS, the Body
of Knowledge (BOK), and precedent databases, then assembles an
InvestigationResult with:

  - Scored and ranked evidence items (relevance <= 1.0).
  - Novel-material detection (zero precedents).
  - Safety banners for oxygen-enriched, cryogenic, and hydrogen
    environments.

Key safety fixes verified here:

  C1 -- Relevance boost must be capped at 1.0.
  C2 -- Missing data scores as 0.0, not 0.5.
  C4 -- Both temp_min and temp_max are used in envelope matching.
"""

import pytest

from mira.mua.v7.investigator import (
    Investigator,
    InvestigationRequest,
    InvestigationResult,
    EnvironmentSpec,
    Banner,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def investigator():
    """Return an Investigator wired to test-doubles for external services
    (MAPTIS, BOK, precedent DB)."""
    return Investigator(backend="test")


@pytest.fixture
def aluminum_request():
    """Standard investigation request for Al 6061-T6 in cabin air."""
    return InvestigationRequest(
        material="6061-T6",
        environment=EnvironmentSpec(
            medium="AIR",
            o2_percent=20.9,
            pressure_psia=14.7,
            temp_min_f=60.0,
            temp_max_f=120.0,
        ),
        application="Cabin rack structural bracket",
    )


@pytest.fixture
def novel_material_request():
    """Request for a material with zero precedents in the test backend."""
    return InvestigationRequest(
        material="Experimental-Alloy-X99",
        environment=EnvironmentSpec(
            medium="AIR",
            o2_percent=20.9,
            pressure_psia=14.7,
            temp_min_f=60.0,
            temp_max_f=120.0,
        ),
        application="Prototype bracket",
    )


@pytest.fixture
def enriched_o2_request():
    """Request for a material in an oxygen-enriched environment."""
    return InvestigationRequest(
        material="Inconel 718",
        environment=EnvironmentSpec(
            medium="GOX",
            o2_percent=30.0,
            pressure_psia=200.0,
            temp_min_f=60.0,
            temp_max_f=500.0,
        ),
        application="High-pressure oxygen valve body",
    )


@pytest.fixture
def cryogenic_request():
    """Request for a material in a cryogenic environment."""
    return InvestigationRequest(
        material="316L",
        environment=EnvironmentSpec(
            medium="LN2",
            o2_percent=0.0,
            pressure_psia=50.0,
            temp_min_f=-320.0,
            temp_max_f=-280.0,
        ),
        application="Cryogenic feed-line bracket",
    )


@pytest.fixture
def hydrogen_request():
    """Request for a material in gaseous hydrogen service."""
    return InvestigationRequest(
        material="316L",
        environment=EnvironmentSpec(
            medium="GH2",
            o2_percent=0.0,
            pressure_psia=6000.0,
            temp_min_f=-40.0,
            temp_max_f=160.0,
        ),
        application="Hydrogen manifold fitting",
    )


# ---------------------------------------------------------------------------
# Basic investigation result structure
# ---------------------------------------------------------------------------

class TestBasicInvestigation:
    def test_basic_investigation(self, investigator, aluminum_request):
        """A standard investigation must return an InvestigationResult
        containing all expected fields: evidence_items, confidence,
        category, conflicts, gaps, and banners."""
        result = investigator.investigate(aluminum_request)

        assert isinstance(result, InvestigationResult)
        assert result.evidence_items is not None
        assert result.confidence is not None
        assert result.category is not None
        assert result.conflicts is not None
        assert result.gaps is not None
        assert result.banners is not None


# ---------------------------------------------------------------------------
# C1 fix: relevance boost cap
# ---------------------------------------------------------------------------

class TestBoostCap:
    def test_boost_cap_one(self, investigator, aluminum_request):
        """No evidence item's relevance score may exceed 1.0.  The C1 bug
        in v6 allowed boosting to push scores above 1.0, which inflated
        downstream confidence calculations."""
        result = investigator.investigate(aluminum_request)

        for item in result.evidence_items:
            assert item.relevance_score <= 1.0, (
                f"Evidence item {item.id} has relevance {item.relevance_score} > 1.0"
            )


# ---------------------------------------------------------------------------
# C2 fix: missing data scores as 0.0
# ---------------------------------------------------------------------------

class TestMissingDataZero:
    def test_missing_data_zero(self, investigator, aluminum_request):
        """When an evidence item is missing a data field (e.g. no pressure
        test data), that dimension must score 0.0 rather than the 0.5
        default that v6 incorrectly applied."""
        result = investigator.investigate(aluminum_request)

        for item in result.evidence_items:
            if item.missing_fields:
                for field in item.missing_fields:
                    assert item.dimension_scores.get(field, 0.0) == 0.0


# ---------------------------------------------------------------------------
# C4 fix: both temperature bounds used
# ---------------------------------------------------------------------------

class TestTemperatureBounds:
    def test_both_temp_bounds(self, investigator, cryogenic_request):
        """The investigator must use both temp_min and temp_max from the
        request when matching evidence to the use envelope.  The C4 bug
        in v6 only checked temp_max, causing false matches for
        cryogenic applications."""
        result = investigator.investigate(cryogenic_request)

        # The result must reflect that cryogenic temps were evaluated
        assert result.envelope_match is not None
        assert result.envelope_match.temp_min_evaluated is True
        assert result.envelope_match.temp_max_evaluated is True


# ---------------------------------------------------------------------------
# Novel material detection
# ---------------------------------------------------------------------------

class TestNovelMaterial:
    def test_novel_material_detection(self, investigator, novel_material_request):
        """When zero precedents are found, the result must flag
        is_novel_material=True so that the UI can surface appropriate
        warnings to the engineer."""
        result = investigator.investigate(novel_material_request)

        assert result.is_novel_material is True
        assert len([
            item for item in result.evidence_items
            if item.source == "PRECEDENT"
        ]) == 0


# ---------------------------------------------------------------------------
# Safety banners
# ---------------------------------------------------------------------------

class TestBanners:
    def test_banners_enriched_o2(self, investigator, enriched_o2_request):
        """An O2 concentration >= 23.5 % must trigger an oxygen-enriched
        safety banner."""
        result = investigator.investigate(enriched_o2_request)

        banner_types = [b.banner_type for b in result.banners]
        assert "OXYGEN_ENRICHED" in banner_types

    def test_banners_cryogenic(self, investigator, cryogenic_request):
        """A minimum temperature <= -150 F must trigger a cryogenic
        safety banner."""
        result = investigator.investigate(cryogenic_request)

        banner_types = [b.banner_type for b in result.banners]
        assert "CRYOGENIC" in banner_types

    def test_banners_hydrogen(self, investigator, hydrogen_request):
        """Gaseous or liquid hydrogen service (GH2 / LH2) must trigger
        a hydrogen safety banner."""
        result = investigator.investigate(hydrogen_request)

        banner_types = [b.banner_type for b in result.banners]
        assert "HYDROGEN" in banner_types
