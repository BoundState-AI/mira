"""P0 safety-fix tests for the CURRENT v6 decision engine.

These tests codify the C2 (missing-data) safety invariants that must hold
in the v6 codebase until the v7 rewrite is complete.  They are regression
guards: if any of these fail, a potentially dangerous scoring bug has been
reintroduced.

C2 invariant: Missing data MUST be scored as a penalty (0.0 or equivalent
review-forcing factor), NEVER as a neutral 0.5 default.  The 0.5 default
was the root cause of MUA confidence scores being silently inflated when
envelope data was incomplete.
"""

import pytest

from mira.mua.v6.decision_engine import (
    DecisionEngine,
    EnvelopeInput,
    DecisionResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return DecisionEngine()


@pytest.fixture
def complete_envelope():
    """An envelope with all data fields present."""
    return EnvelopeInput(
        material="6061-T6",
        medium="AIR",
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        test_data_available=True,
        test_data_expired=False,
    )


@pytest.fixture
def missing_envelope():
    """An envelope with pressure and temperature data missing."""
    return EnvelopeInput(
        material="6061-T6",
        medium="AIR",
        o2_percent=20.9,
        pressure_psia=None,
        temp_min_f=None,
        temp_max_f=None,
        test_data_available=True,
        test_data_expired=False,
    )


@pytest.fixture
def missing_test_data_envelope():
    """An envelope where no test data is available at all."""
    return EnvelopeInput(
        material="6061-T6",
        medium="AIR",
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        test_data_available=False,
        test_data_expired=False,
    )


@pytest.fixture
def h2_missing_pressure():
    """Hydrogen service with pressure data missing -- the most dangerous
    combination for the C2 bug."""
    return EnvelopeInput(
        material="316L",
        medium="GH2",
        o2_percent=0.0,
        pressure_psia=None,
        temp_min_f=-40.0,
        temp_max_f=160.0,
        test_data_available=True,
        test_data_expired=False,
    )


# ---------------------------------------------------------------------------
# C2: missing envelope must not be neutral
# ---------------------------------------------------------------------------

class TestC2MissingEnvelope:
    def test_c2_missing_envelope_not_neutral(self, engine, missing_envelope):
        """When envelope data (pressure, temperature) is missing, the
        decision engine must apply a penalty score of 0.0 for those
        dimensions -- NOT a default of 0.5.

        The 0.5 default was the original C2 bug: it caused missing data
        to look like partial evidence, inflating the confidence score
        and potentially routing materials to a less restrictive category
        than warranted."""
        result = engine.evaluate(missing_envelope)

        assert result.envelope_penalty >= 1.0, (
            f"Expected envelope_penalty >= 1.0 for missing data, "
            f"got {result.envelope_penalty}"
        )
        # Explicitly verify it is NOT the old 0.5 default
        assert result.pressure_score == 0.0, (
            f"Missing pressure must score 0.0, got {result.pressure_score}"
        )
        assert result.temperature_score == 0.0, (
            f"Missing temperature must score 0.0, got {result.temperature_score}"
        )


# ---------------------------------------------------------------------------
# C2: missing test data must add review factor
# ---------------------------------------------------------------------------

class TestC2MissingTestData:
    def test_c2_missing_test_data_flagged(
        self, engine, missing_test_data_envelope
    ):
        """When no flammability / off-gassing test data is available for
        the material, the decision engine must add a review factor that
        forces human review.  The system must not silently proceed as if
        the data were present."""
        result = engine.evaluate(missing_test_data_envelope)

        assert result.requires_review is True
        assert any(
            "test data" in factor.lower()
            for factor in result.review_factors
        ), (
            f"Expected a review factor mentioning 'test data', "
            f"got {result.review_factors}"
        )


# ---------------------------------------------------------------------------
# C2: None pressure in H2 service must force REVIEW
# ---------------------------------------------------------------------------

class TestC2HydrogenPressure:
    def test_c2_none_pressure_h2(self, engine, h2_missing_pressure):
        """In hydrogen service, missing pressure data is an absolute
        safety gate.  The decision engine must force REVIEW status
        regardless of any other evidence.

        Hydrogen embrittlement and leak behavior are strongly
        pressure-dependent; without knowing the service pressure, no
        confidence determination is valid."""
        result = engine.evaluate(h2_missing_pressure)

        assert result.requires_review is True
        assert result.pressure_score == 0.0
        assert any(
            "hydrogen" in factor.lower() or "pressure" in factor.lower()
            for factor in result.review_factors
        )
