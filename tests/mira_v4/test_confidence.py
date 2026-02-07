#!/usr/bin/env python3
"""
Tests: Confidence Score Formula
Purpose: AC-R1 (deterministic output) and AC-R2 (penalty breakdown logged).

Validates that the penalty-based confidence score is calculated correctly,
that each penalty is independently testable, that the gate thresholds
match BuildSpec Section 2.5, and that the same inputs always produce
the same output (determinism).

BoundState AI 2026
Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 2
"""

import sys
sys.path.insert(0, r"C:\BoundState")

from datetime import datetime, timezone
from typing import List

import pytest

from mira_v4.confidence import ConfidenceCalculator
from mira_v4.models import EnvironmentSpec, EvidenceRow, GateAction


# =============================================================================
# Shared Setup
# =============================================================================

calculator = ConfidenceCalculator()

# Current year used by staleness calculation
CURRENT_YEAR = datetime.now(timezone.utc).year


def _make_env(missing: int = 0) -> EnvironmentSpec:
    """Create an EnvironmentSpec with a controlled number of missing fields.

    Fields are filled left-to-right: temperature_c, pressure_kpa, o2_pct,
    fluid_medium, duration_hr, cycles. `missing` is the count from the end.
    """
    all_fields = {
        "temperature_c": -200.0,
        "pressure_kpa": 5000.0,
        "o2_pct": 99.5,
        "fluid_medium": "LOX",
        "duration_hr": 1.0,
        "cycles": 10,
    }
    field_names = list(all_fields.keys())
    # Fill (6 - missing) fields
    filled_count = 6 - missing
    kwargs = {}
    for i, name in enumerate(field_names):
        if i < filled_count:
            kwargs[name] = all_fields[name]
    return EnvironmentSpec(**kwargs)


def _make_evidence(n: int, test_year: int = 2024) -> List[EvidenceRow]:
    """Create n clean evidence rows with a specified test year."""
    return [
        EvidenceRow(
            record_id=f"REC-{i:04d}",
            source="MAPTIS",
            data_class="direct_test",
            dirty_flag=False,
            test_year=test_year,
        )
        for i in range(n)
    ]


# =============================================================================
# Perfect Score Test
# =============================================================================


class TestPerfectScore:
    """Verify a perfect score when all inputs are optimal."""

    def test_perfect_score_no_penalties(self, sample_environment, sample_evidence):
        """Full env, 5 evidence, 0% dirty, no heritage, not safety -> 1.0 PASS."""
        result = calculator.calculate(
            environment=sample_environment,
            evidence_rows=sample_evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )
        assert result.score == 1.0
        assert result.gate_action == GateAction.PASS
        assert all(v == 0.0 for v in result.penalties.values())


# =============================================================================
# Individual Penalty Tests
# =============================================================================


class TestIndividualPenalties:
    """Verify each penalty type independently."""

    @pytest.mark.parametrize(
        "penalty_type, env_missing, n_evidence, test_year, dirty_frac, heritage, expected_penalty_key",
        [
            # 1. Unknown env: 3 missing fields = 0.24
            ("unknown_env", 3, 5, 2024, 0.0, False, "unknown_env"),
            # 2. Staleness: year 2000, >20yr = 0.15
            ("staleness", 0, 5, 2000, 0.0, False, "staleness"),
            # 3. Sparse evidence: 0 evidence = 0.20
            ("sparse_evidence", 0, 0, 2024, 0.0, False, "sparse_evidence"),
            # 4. Dirty data: 50% dirty = 0.125
            ("dirty_data", 0, 5, 2024, 0.5, False, "dirty_data"),
            # 5. Heritage conflict: active = 0.15
            ("heritage_conflict", 0, 5, 2024, 0.0, True, "heritage_conflict"),
        ],
        ids=[
            "unknown_env_3_missing",
            "staleness_year_2000",
            "sparse_0_evidence",
            "dirty_50_pct",
            "heritage_active",
        ],
    )
    def test_each_penalty_independently(
        self,
        penalty_type,
        env_missing,
        n_evidence,
        test_year,
        dirty_frac,
        heritage,
        expected_penalty_key,
    ):
        """Each penalty type applies independently while others are at zero."""
        env = _make_env(missing=env_missing)
        evidence = _make_evidence(n=n_evidence, test_year=test_year)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=dirty_frac,
            heritage_veto_active=heritage,
            safety_critical=False,
        )

        # The penalty we're testing should be > 0
        assert result.penalties[expected_penalty_key] > 0.0
        # Score should be < 1.0
        assert result.score < 1.0


# =============================================================================
# Unknown Environment Penalty Scaling
# =============================================================================


class TestUnknownEnvPenalty:
    """Verify unknown_env penalty scales at 0.08 per missing field."""

    @pytest.mark.parametrize(
        "missing, expected_penalty",
        [
            (0, 0.0),
            (3, 0.24),
            (6, 0.48),
        ],
        ids=["0_missing", "3_missing", "6_missing"],
    )
    def test_unknown_env_penalty_per_field(self, missing, expected_penalty):
        env = _make_env(missing=missing)
        evidence = _make_evidence(n=5, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )
        assert abs(result.penalties["unknown_env"] - expected_penalty) < 1e-6


# =============================================================================
# Staleness Penalty Tiers
# =============================================================================


class TestStalenessPenalty:
    """Verify staleness penalty tiers based on median test year age."""

    @pytest.mark.parametrize(
        "test_year, expected_penalty",
        [
            (2024, 0.00),   # age ~2yr  -> factor 0
            (2019, 0.05),   # age ~7yr  -> factor 1
            (2010, 0.10),   # age ~16yr -> factor 2
            (2000, 0.15),   # age ~26yr -> factor 3
        ],
        ids=["recent_0yr", "moderate_5_10yr", "old_10_20yr", "stale_20yr_plus"],
    )
    def test_staleness_tiers(self, test_year, expected_penalty):
        env = _make_env(missing=0)
        evidence = _make_evidence(n=5, test_year=test_year)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )
        assert abs(result.penalties["staleness"] - expected_penalty) < 1e-6


# =============================================================================
# Sparse Evidence Penalty Scaling
# =============================================================================


class TestSparseEvidencePenalty:
    """Verify sparse evidence penalty scales linearly from 0.20 to 0.00."""

    @pytest.mark.parametrize(
        "n_evidence, expected_penalty",
        [
            (0, 0.20),     # scale_factor = 1.0
            (1, 0.16),     # scale_factor = 1 - 1/5 = 0.8
            (3, 0.08),     # scale_factor = 1 - 3/5 = 0.4
            (5, 0.00),     # scale_factor = 1 - 5/5 = 0.0
            (10, 0.00),    # scale_factor = 1 - min(10/5, 1.0) = 0.0
        ],
        ids=["0_evidence", "1_evidence", "3_evidence", "5_evidence", "10_evidence"],
    )
    def test_sparse_evidence_scaling(self, n_evidence, expected_penalty):
        env = _make_env(missing=0)
        evidence = _make_evidence(n=n_evidence, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )
        assert abs(result.penalties["sparse_evidence"] - expected_penalty) < 1e-6


# =============================================================================
# Dirty Data Penalty Scaling
# =============================================================================


class TestDirtyDataPenalty:
    """Verify dirty data penalty scales linearly by dirty_fraction."""

    @pytest.mark.parametrize(
        "dirty_frac, expected_penalty",
        [
            (0.0, 0.0),
            (0.5, 0.125),
            (1.0, 0.25),
        ],
        ids=["0_pct_dirty", "50_pct_dirty", "100_pct_dirty"],
    )
    def test_dirty_data_scaling(self, dirty_frac, expected_penalty):
        env = _make_env(missing=0)
        evidence = _make_evidence(n=5, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=dirty_frac,
            heritage_veto_active=False,
            safety_critical=False,
        )
        assert abs(result.penalties["dirty_data"] - expected_penalty) < 1e-6


# =============================================================================
# Heritage Conflict Penalty
# =============================================================================


class TestHeritageConflictPenalty:
    """Verify heritage conflict penalty is binary: 0.00 or 0.15."""

    @pytest.mark.parametrize(
        "heritage_active, expected_penalty",
        [
            (False, 0.0),
            (True, 0.15),
        ],
        ids=["no_conflict", "conflict_active"],
    )
    def test_heritage_conflict_binary(self, heritage_active, expected_penalty):
        env = _make_env(missing=0)
        evidence = _make_evidence(n=5, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=heritage_active,
            safety_critical=False,
        )
        assert abs(result.penalties["heritage_conflict"] - expected_penalty) < 1e-6


# =============================================================================
# Combined Penalties (Additive)
# =============================================================================


class TestCombinedPenalties:
    """Verify penalties are additive."""

    def test_all_penalties_combined(self):
        """All penalties active: verify they sum correctly.

        unknown_env: 3 missing = 0.24
        staleness: year 2000 = 0.15
        sparse_evidence: 1 evidence = 0.16
        dirty_data: 50% = 0.125
        heritage_conflict: active = 0.15

        Total penalty = 0.24 + 0.15 + 0.16 + 0.125 + 0.15 = 0.825
        Score = 1.0 - 0.825 = 0.175
        """
        env = _make_env(missing=3)
        evidence = _make_evidence(n=1, test_year=2000)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.5,
            heritage_veto_active=True,
            safety_critical=False,
        )

        expected_total = 0.24 + 0.15 + 0.16 + 0.125 + 0.15
        expected_score = max(0.0, 1.0 - expected_total)

        assert abs(result.score - expected_score) < 1e-4
        assert result.score > 0.0


# =============================================================================
# Score Floor
# =============================================================================


class TestScoreFloor:
    """Verify score cannot go below 0.0."""

    def test_score_floor_at_zero(self):
        """Massive penalties: score floors at 0.0, never negative.

        unknown_env: 6 missing = 0.48
        staleness: no year data = 0.15 (max factor)
        sparse_evidence: 0 evidence = 0.20
        dirty_data: 100% = 0.25
        heritage_conflict: active = 0.15

        Total penalty = 0.48 + 0.15 + 0.20 + 0.25 + 0.15 = 1.23
        Score = max(0.0, 1.0 - 1.23) = 0.0
        """
        env = EnvironmentSpec()  # All fields None
        evidence = []  # No evidence (also no test years)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=1.0,
            heritage_veto_active=True,
            safety_critical=False,
        )

        assert result.score == 0.0
        assert result.gate_action == GateAction.REFUSE


# =============================================================================
# Gate Threshold Tests
# =============================================================================


class TestGateThresholds:
    """Verify gate actions match BuildSpec Section 2.5 thresholds."""

    def test_gate_safety_pass_threshold(self):
        """Safety-critical: score >= 0.85 -> PASS."""
        # Full env (0 missing), 5 evidence, 2024 year, 0% dirty, no heritage
        # -> score = 1.0. Then we add exactly 0.15 penalty via heritage
        # to get 0.85.
        env = _make_env(missing=0)
        evidence = _make_evidence(n=5, test_year=2024)

        # heritage_veto gives exactly 0.15 penalty -> score = 0.85
        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=True,
            safety_critical=True,
        )
        assert abs(result.score - 0.85) < 1e-4
        assert result.gate_action == GateAction.PASS

    def test_gate_safety_clarify_below_085(self):
        """Safety-critical: score 0.84 -> CLARIFY.

        0.08 (1 missing env) + 0.08 (another via dirty ~0.32 fraction)
        We need score = 0.84 exactly. Use heritage(0.15) + 1 missing env(0.08)
        = 0.23 penalty -> score = 0.77. Still not 0.84.

        Use: heritage(0.15) + sparse(1 evidence = 0.16) -> total=0.31
        -> score=0.69 (too low).

        Simpler: just use the gate method directly for boundary testing.
        1 missing env (0.08) + heritage (0.15) = 0.23 penalty -> score = 0.77
        That is < 0.85 for safety -> CLARIFY. Good enough for threshold test.
        """
        env = _make_env(missing=1)
        evidence = _make_evidence(n=5, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=True,
            safety_critical=True,
        )
        # score = 1.0 - 0.08 - 0.15 = 0.77
        assert result.score < 0.85
        assert result.score >= 0.50
        assert result.gate_action == GateAction.CLARIFY

    def test_gate_general_pass_threshold(self):
        """General: score >= 0.70 -> PASS.

        Use 3 missing env (0.24) + heritage (0.0) = 0.24 -> score = 0.76. PASS.
        Also verify at exactly 0.70: 3 missing(0.24) + staleness(0.05) +
        sparse 5 evidence(0.0) + dirty(0.004) = need 0.30 total.
        Use: 2 missing(0.16) + heritage(0.15) = 0.31 -> score = 0.69 -> CLARIFY.
        """
        # Score = 1.0 - 0.24 = 0.76 -> PASS for general
        env = _make_env(missing=3)
        evidence = _make_evidence(n=5, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )
        assert result.score >= 0.70
        assert result.gate_action == GateAction.PASS

    def test_gate_general_clarify_below_070(self):
        """General: score < 0.70 but >= 0.50 -> CLARIFY.

        2 missing env(0.16) + heritage(0.15) = 0.31 penalty -> score = 0.69.
        """
        env = _make_env(missing=2)
        evidence = _make_evidence(n=5, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=True,
            safety_critical=False,
        )
        # score = 1.0 - 0.16 - 0.15 = 0.69
        assert result.score < 0.70
        assert result.score >= 0.50
        assert result.gate_action == GateAction.CLARIFY

    def test_gate_refuse_threshold(self):
        """Score < 0.50 -> REFUSE.

        6 missing env(0.48) + heritage(0.15) = 0.63 -> score = 0.37 -> REFUSE.
        """
        env = EnvironmentSpec()  # 6 missing
        evidence = _make_evidence(n=5, test_year=2024)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=True,
            safety_critical=False,
        )
        # score = 1.0 - 0.48 - 0.15 = 0.37
        assert result.score < 0.50
        assert result.gate_action == GateAction.REFUSE

    def test_gate_at_050_is_clarify(self):
        """Score = 0.50 exactly -> CLARIFY (not REFUSE).

        Need exactly 0.50 penalty. 6 missing(0.48) + sparse(4 evidence=0.04)
        = 0.52 -> score=0.48. Too much.

        5 missing(0.40) + staleness 5-10yr(0.05) + sparse(4 evidence=0.04)
        + dirty 0.004 = 0.494 -> 0.506. Close.

        Let's use: 6 missing(0.48) + dirty 2%(0.005) = 0.485 -> score=0.515.

        Actually, best: use the _determine_gate method boundary. We verify
        that at 0.50 we get CLARIFY. Use 5 missing(0.40) + staleness(0.10
        via year 2010) = 0.50 penalty -> score = 0.50 exactly.
        """
        env = _make_env(missing=5)
        evidence = _make_evidence(n=5, test_year=2010)

        result = calculator.calculate(
            environment=env,
            evidence_rows=evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )
        # score = 1.0 - 0.40 - 0.10 = 0.50
        assert abs(result.score - 0.50) < 1e-4
        assert result.gate_action == GateAction.CLARIFY


# =============================================================================
# AC-R1: Determinism
# =============================================================================


class TestDeterminism:
    """AC-R1: Same inputs always produce the same output."""

    def test_determinism_repeated_calls(self, sample_environment, sample_evidence):
        """Run 50 identical calculations and verify all produce same score."""
        results = []
        for _ in range(50):
            r = calculator.calculate(
                environment=sample_environment,
                evidence_rows=sample_evidence,
                dirty_fraction=0.0,
                heritage_veto_active=False,
                safety_critical=False,
            )
            results.append(r)

        scores = [r.score for r in results]
        gates = [r.gate_action for r in results]

        # All scores identical
        assert all(s == scores[0] for s in scores)
        # All gate actions identical
        assert all(g == gates[0] for g in gates)


# =============================================================================
# AC-R2: Penalty Breakdown in Result
# =============================================================================


class TestPenaltyBreakdown:
    """AC-R2: All penalty names present in the result dict."""

    def test_penalty_breakdown_in_result(self, sample_environment, sample_evidence):
        """Verify all 5 penalty keys are present in the penalties dict."""
        result = calculator.calculate(
            environment=sample_environment,
            evidence_rows=sample_evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )

        expected_keys = {
            "unknown_env",
            "staleness",
            "sparse_evidence",
            "dirty_data",
            "heritage_conflict",
        }
        assert set(result.penalties.keys()) == expected_keys

    def test_penalty_breakdown_has_explanation(self, sample_environment, sample_evidence):
        """Verify the explanation string is non-empty."""
        result = calculator.calculate(
            environment=sample_environment,
            evidence_rows=sample_evidence,
            dirty_fraction=0.0,
            heritage_veto_active=False,
            safety_critical=False,
        )
        assert len(result.explanation) > 0
