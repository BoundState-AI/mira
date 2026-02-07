#!/usr/bin/env python3
"""
Test Module: Intent Guardrail (intent_guardrail.py)
Purpose: AC-R8 adversarial intent mismatch tests -- 5/5 adversarial cases caught.

BoundState AI 2026
Compliance: SWE-032, SWE-033

Tests cover:
    - Agreement path (no disagreement record returned)
    - Disagreement path (conservative intent chosen)
    - Safety-flag-missing escalation
    - 0.05 penalty on every disagreement
    - Conservatism ordering (compatibility_query > materials_query > general_search)
    - 5 parametrised adversarial scenarios where Sonnet misclassifies a
      safety-relevant query and the heuristic guardrail catches it

The IntentGuardrail wraps the real deterministic IntentClassifier.
For adversarial tests we call guardrail.validate() with a Sonnet intent
string that is deliberately wrong and a query string that the heuristic
WILL classify as compatibility_query (score > 0.5).
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import pytest

from mira_v4.intent_guardrail import (
    CONSERVATISM_ORDER,
    DISAGREEMENT_PENALTY,
    IntentGuardrail,
)
from mira_v4.models import IntentDisagreement


# ===========================================================================
# Helpers
# ===========================================================================

_GUARDRAIL = IntentGuardrail()


# ===========================================================================
# 1. Agreement -- no disagreement
# ===========================================================================


class TestAgreement:
    """When Sonnet and heuristic agree, no penalty is applied."""

    def test_agreement_no_disagreement(self):
        """Sonnet = compatibility_query for a LOX query -> heuristic agrees -> no penalty."""
        # "Is Inconel 718 compatible with LOX?" triggers compatibility_query
        # in the heuristic (patterns: "compatible" +4, "LOX" +5 => score ~1.0).
        resolved, disagreement = _GUARDRAIL.validate(
            sonnet_intent="compatibility_query",
            raw_query="Is Inconel 718 compatible with LOX?",
        )
        assert resolved == "compatibility_query"
        assert disagreement is None


# ===========================================================================
# 2. Disagreement -- conservative choice
# ===========================================================================


class TestDisagreement:
    """When classifiers disagree, the more conservative intent wins."""

    def test_disagreement_chooses_conservative(self):
        """Sonnet=materials_query but heuristic detects compatibility_query
        (LOX keyword) -> heuristic wins because compatibility_query is
        more conservative."""
        resolved, disagreement = _GUARDRAIL.validate(
            sonnet_intent="materials_query",
            raw_query="Is Inconel 718 compatible with LOX at 500 psi?",
        )
        # The heuristic should detect compatibility_query (score > 0.5)
        # so safety-flag-missing fires, or at minimum the conservative
        # choice picks compatibility_query.
        assert resolved == "compatibility_query"
        assert disagreement is not None
        assert disagreement.chosen_intent == "compatibility_query"


# ===========================================================================
# 3. Safety flag missing
# ===========================================================================


class TestSafetyFlagMissing:
    """Sonnet returns a non-safety intent but heuristic detects safety signal."""

    def test_safety_flag_missing_caught(self):
        """Sonnet says general_search for LOX compatibility query.
        Heuristic must catch the safety signal and escalate."""
        resolved, disagreement = _GUARDRAIL.validate(
            sonnet_intent="general_search",
            raw_query="Is Inconel 718 compatible with LOX?",
        )
        assert resolved == "compatibility_query"
        assert disagreement is not None
        assert disagreement.penalty_applied == DISAGREEMENT_PENALTY
        assert "safety" in disagreement.explanation.lower() or \
               "escalat" in disagreement.explanation.lower()


# ===========================================================================
# 4. Penalty value
# ===========================================================================


class TestPenaltyValue:
    """Verify exact penalty amount on disagreement."""

    def test_penalty_applied_on_disagreement(self):
        """0.05 penalty returned when disagreement occurs."""
        _, disagreement = _GUARDRAIL.validate(
            sonnet_intent="general_search",
            raw_query="Is Inconel 718 compatible with LOX at 500 psi?",
        )
        assert disagreement is not None
        assert disagreement.penalty_applied == pytest.approx(0.05)


# ===========================================================================
# 5. Conservatism ordering
# ===========================================================================


class TestConservatismOrder:
    """Verify the conservatism ladder from the BuildSpec Section 6."""

    def test_conservatism_order(self):
        """compatibility_query < materials_query < general_search in rank
        (lower index = more conservative = wins tie-break)."""
        idx_compat = CONSERVATISM_ORDER.index("compatibility_query")
        idx_material = CONSERVATISM_ORDER.index("materials_query")
        idx_general = CONSERVATISM_ORDER.index("general_search")

        assert idx_compat < idx_material < idx_general, (
            "Conservatism ordering must be: "
            "compatibility_query (most conservative) < materials_query < general_search"
        )


# ===========================================================================
# 6. AC-R8 adversarial parametrised tests (5 / 5)
# ===========================================================================

# Each tuple: (test_id, sonnet_intent, raw_query, expected_description)
# All queries contain safety-relevant keywords that the heuristic will score
# above _SAFETY_SCORE_THRESHOLD (0.5) for compatibility_query.

_ADVERSARIAL_CASES = [
    pytest.param(
        "general_search",
        "What materials are compatible with LOX valve service at 600 psi?",
        "LOX valve query classified as general_search by Sonnet",
        id="adversarial_1_lox_valve_general_search",
    ),
    pytest.param(
        "property_query",
        "Is 316L safe for hydrogen service at 5000 psi?",
        "Hydrogen service query classified as property_query by Sonnet",
        id="adversarial_2_hydrogen_property_query",
    ),
    pytest.param(
        "materials_query",
        "Which alloys are O2 compatible for oxygen service?",
        "O2 compatible materials classified as materials_query by Sonnet",
        id="adversarial_3_o2_compatible_materials_query",
    ),
    pytest.param(
        "help",
        "Is Inconel 625 safe and approved for cryogenic LOX use?",
        "Cryogenic safety query classified as help by Sonnet",
        id="adversarial_4_cryogenic_safety_help",
    ),
    pytest.param(
        "comparison",
        "Can I use Inconel 718 in H2 service at high-pressure 4000 psi?",
        "High-pressure H2 query classified as comparison by Sonnet",
        id="adversarial_5_high_pressure_h2_comparison",
    ),
]


class TestAdversarialIntentMismatches:
    """AC-R8: 5/5 adversarial intent mismatches must be caught."""

    @pytest.mark.parametrize("sonnet_intent,raw_query,description", _ADVERSARIAL_CASES)
    def test_adversarial_mismatch_caught(self, sonnet_intent, raw_query, description):
        """Sonnet misclassifies a safety-relevant query.

        The guardrail MUST:
          1. Return a disagreement record (not None).
          2. Choose a more conservative intent than the Sonnet classification.
          3. Apply the 0.05 disagreement penalty.
        """
        resolved, disagreement = _GUARDRAIL.validate(
            sonnet_intent=sonnet_intent,
            raw_query=raw_query,
        )

        # Must detect disagreement
        assert disagreement is not None, (
            f"Guardrail failed to detect mismatch: {description}"
        )

        # Must choose a more conservative intent
        max_rank = len(CONSERVATISM_ORDER)
        try:
            sonnet_rank = CONSERVATISM_ORDER.index(sonnet_intent)
        except ValueError:
            sonnet_rank = max_rank

        try:
            resolved_rank = CONSERVATISM_ORDER.index(resolved)
        except ValueError:
            resolved_rank = max_rank

        assert resolved_rank <= sonnet_rank, (
            f"Resolved intent '{resolved}' (rank {resolved_rank}) "
            f"is NOT more conservative than Sonnet intent '{sonnet_intent}' "
            f"(rank {sonnet_rank}). Description: {description}"
        )

        # Must apply penalty
        assert disagreement.penalty_applied == pytest.approx(DISAGREEMENT_PENALTY), (
            f"Expected penalty {DISAGREEMENT_PENALTY}, "
            f"got {disagreement.penalty_applied}. Description: {description}"
        )
