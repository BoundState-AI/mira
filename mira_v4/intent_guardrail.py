#!/usr/bin/env python3
"""
Module: Intent Guardrail
Purpose: Safety guardrail wrapping the deterministic IntentClassifier.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 6

The deterministic IntentClassifier in mira.nlp is PRESERVED as a safety
guardrail. Sonnet handles query-to-typed-filter translation. This module
validates Sonnet's output against the deterministic rule set.

When the two classifiers disagree, this guardrail:
  1. Chooses the MORE CONSERVATIVE intent.
  2. Applies a 0.05 confidence penalty (DISAGREEMENT_PENALTY).
  3. Returns an IntentDisagreement record for the Decision Lineage.

Safety-relevant intents (compatibility_query, risk_query) receive
special treatment: if the heuristic detects safety signals that Sonnet
missed, the guardrail escalates to the safety intent regardless.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Import the existing deterministic IntentClassifier from mira.nlp
# ---------------------------------------------------------------------------
sys.path.insert(0, r"C:\BoundState")
from mira.nlp.intent_classifier import IntentClassifier, IntentClassificationResult

from .models import IntentDisagreement

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Confidence penalty applied whenever Sonnet and heuristic disagree
DISAGREEMENT_PENALTY: float = 0.05

# Conservatism ordering: index 0 is MOST conservative.
# When the two classifiers disagree, the intent with the LOWER index wins.
CONSERVATISM_ORDER: list[str] = [
    "compatibility_query",
    "risk_query",
    "test_analysis",
    "test_report",
    "materials_query",
    "property_query",
    "comparison",
    "recommendation",
    "document_lookup",
    "help",
    "general_search",
]

# Intents that carry safety implications
_SAFETY_INTENTS: frozenset[str] = frozenset({
    "compatibility_query",
    "risk_query",
})

# Heuristic score threshold above which a safety intent is considered
# "detected" even if it is not the top-ranked intent.
_SAFETY_SCORE_THRESHOLD: float = 0.5


# =============================================================================
# IntentGuardrail
# =============================================================================


class IntentGuardrail:
    """Validates Sonnet intent output against the deterministic IntentClassifier.

    Usage::

        guardrail = IntentGuardrail()
        resolved_intent, disagreement = guardrail.validate(
            sonnet_intent="materials_query",
            raw_query="Is Inconel 718 compatible with LOX at 500 psi?"
        )

    If ``disagreement`` is not None, the caller should:
      - Use ``resolved_intent`` (the more conservative choice).
      - Apply ``DISAGREEMENT_PENALTY`` to the confidence score.
      - Attach the ``IntentDisagreement`` record to the Decision Lineage.

    Compliance: SWE-032, SWE-033
    Safety Critical: True
    """

    def __init__(self) -> None:
        """Initialise the guardrail with a fresh IntentClassifier instance."""
        self._classifier = IntentClassifier()
        logger.info(
            "IntentGuardrail initialised with deterministic IntentClassifier"
        )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def validate(
        self,
        sonnet_intent: str,
        raw_query: str,
    ) -> Tuple[str, Optional[IntentDisagreement]]:
        """Validate Sonnet's intent against the deterministic heuristic.

        Args:
            sonnet_intent: Intent string returned by Sonnet.
            raw_query:     The original user query text.

        Returns:
            A 2-tuple of:
              - resolved_intent (str): The intent to use going forward.
              - disagreement (IntentDisagreement | None): If the classifiers
                disagreed, a record suitable for Decision Lineage storage.

        Compliance: SWE-032, SWE-033
        """
        # Step 1 -- run the deterministic classifier
        heuristic_result: IntentClassificationResult = self._classifier.classify(
            raw_query
        )
        heuristic_intent, heuristic_score = heuristic_result.best()

        logger.debug(
            "Heuristic classification: intent=%s score=%.3f | Sonnet: %s",
            heuristic_intent,
            heuristic_score,
            sonnet_intent,
        )

        # Step 2 -- check for safety-flag-missing scenario
        safety_flag_missing = self._check_safety_flag_missing(
            sonnet_intent, heuristic_result
        )
        if safety_flag_missing:
            # Heuristic detected a safety signal that Sonnet missed.
            # Escalate to the safety intent regardless of normal comparison.
            safety_intent = self._get_highest_safety_intent(heuristic_result)
            logger.warning(
                "Safety flag missing: Sonnet returned '%s' but heuristic "
                "detected safety intent '%s' (score > %.2f). "
                "Escalating to safety intent.",
                sonnet_intent,
                safety_intent,
                _SAFETY_SCORE_THRESHOLD,
            )
            disagreement = IntentDisagreement(
                sonnet_intent=sonnet_intent,
                heuristic_intent=safety_intent,
                chosen_intent=safety_intent,
                penalty_applied=DISAGREEMENT_PENALTY,
                explanation=(
                    f"Heuristic detected safety-relevant intent "
                    f"'{safety_intent}' with score > {_SAFETY_SCORE_THRESHOLD} "
                    f"but Sonnet returned non-safety intent '{sonnet_intent}'. "
                    f"Escalating to '{safety_intent}' per BuildSpec Section 6."
                ),
            )
            return safety_intent, disagreement

        # Step 3 -- normal agreement / disagreement check
        if self._intents_agree(sonnet_intent, heuristic_intent):
            logger.debug(
                "Sonnet and heuristic agree: '%s'", sonnet_intent
            )
            return sonnet_intent, None

        # Step 4 -- disagreement: choose the more conservative intent
        chosen = self._choose_more_conservative(sonnet_intent, heuristic_intent)
        logger.info(
            "Intent disagreement: Sonnet='%s', Heuristic='%s' -> "
            "Chose more conservative '%s'. Penalty=%.3f",
            sonnet_intent,
            heuristic_intent,
            chosen,
            DISAGREEMENT_PENALTY,
        )

        disagreement = IntentDisagreement(
            sonnet_intent=sonnet_intent,
            heuristic_intent=heuristic_intent,
            chosen_intent=chosen,
            penalty_applied=DISAGREEMENT_PENALTY,
            explanation=(
                f"Sonnet classified as '{sonnet_intent}' but deterministic "
                f"heuristic classified as '{heuristic_intent}'. Chose "
                f"'{chosen}' as the more conservative classification per "
                f"BuildSpec Section 6 conservatism ordering."
            ),
        )
        return chosen, disagreement

    # --------------------------------------------------------------------- #
    # Safety helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _is_safety_relevant(intent: str) -> bool:
        """Check whether an intent is safety-relevant.

        Safety-relevant intents are ``compatibility_query`` and
        ``risk_query``. These receive elevated scrutiny in the
        guardrail validation flow.

        Args:
            intent: An intent classification string.

        Returns:
            True if the intent is safety-relevant.
        """
        return intent in _SAFETY_INTENTS

    @staticmethod
    def _check_safety_flag_missing(
        sonnet_intent: str,
        heuristic_result: IntentClassificationResult,
    ) -> bool:
        """Detect when the heuristic flags a safety signal that Sonnet missed.

        A safety flag is considered "missing" when:
          - The heuristic has a compatibility_query or risk_query score
            above ``_SAFETY_SCORE_THRESHOLD`` (0.5).
          - Sonnet returned a non-safety intent.

        Args:
            sonnet_intent:    Intent string from Sonnet.
            heuristic_result: Full result from the deterministic classifier.

        Returns:
            True if a safety signal was missed.
        """
        if sonnet_intent in _SAFETY_INTENTS:
            # Sonnet already flagged a safety intent -- no miss.
            return False

        scores = heuristic_result.scores
        for safety_intent in _SAFETY_INTENTS:
            if scores.get(safety_intent, 0.0) > _SAFETY_SCORE_THRESHOLD:
                logger.debug(
                    "Safety flag missing: heuristic '%s' score=%.3f > %.2f "
                    "but Sonnet returned '%s'",
                    safety_intent,
                    scores[safety_intent],
                    _SAFETY_SCORE_THRESHOLD,
                    sonnet_intent,
                )
                return True

        return False

    @staticmethod
    def _get_highest_safety_intent(
        heuristic_result: IntentClassificationResult,
    ) -> str:
        """Return the safety intent with the highest heuristic score.

        If neither safety intent has a score, falls back to
        ``compatibility_query`` as the most conservative default.

        Args:
            heuristic_result: Full result from the deterministic classifier.

        Returns:
            The safety intent string with the highest score.
        """
        scores = heuristic_result.scores
        best_intent = "compatibility_query"
        best_score = -1.0

        for intent in _SAFETY_INTENTS:
            score = scores.get(intent, 0.0)
            if score > best_score:
                best_score = score
                best_intent = intent

        return best_intent

    # --------------------------------------------------------------------- #
    # Conservatism logic
    # --------------------------------------------------------------------- #

    @staticmethod
    def _intents_agree(sonnet_intent: str, heuristic_intent: str) -> bool:
        """Determine if two intents are in meaningful agreement.

        Two intents agree if they are identical strings. Intents that are
        semantically similar but differently named are NOT treated as
        agreement -- the conservatism ordering handles tie-breaking.

        Args:
            sonnet_intent:    Intent string from Sonnet.
            heuristic_intent: Best intent from the deterministic classifier.

        Returns:
            True if the intents match exactly.
        """
        return sonnet_intent == heuristic_intent

    @staticmethod
    def _choose_more_conservative(intent_a: str, intent_b: str) -> str:
        """Return the more conservative of two intents.

        Uses the ``CONSERVATISM_ORDER`` list where lower indices are
        more conservative (safety-first).

        If an intent is not in the conservatism order, it is assigned
        the least-conservative rank (i.e. treated as ``general_search``).

        Args:
            intent_a: First intent string.
            intent_b: Second intent string.

        Returns:
            The more conservative intent (lower index in CONSERVATISM_ORDER).
        """
        max_rank = len(CONSERVATISM_ORDER)

        try:
            rank_a = CONSERVATISM_ORDER.index(intent_a)
        except ValueError:
            logger.warning(
                "Intent '%s' not in CONSERVATISM_ORDER; assigning least "
                "conservative rank (%d).",
                intent_a,
                max_rank,
            )
            rank_a = max_rank

        try:
            rank_b = CONSERVATISM_ORDER.index(intent_b)
        except ValueError:
            logger.warning(
                "Intent '%s' not in CONSERVATISM_ORDER; assigning least "
                "conservative rank (%d).",
                intent_b,
                max_rank,
            )
            rank_b = max_rank

        if rank_a <= rank_b:
            return intent_a
        return intent_b
