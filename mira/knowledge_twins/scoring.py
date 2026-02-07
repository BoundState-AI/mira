#!/usr/bin/env python3
"""
Module: Scoring
Purpose: Knowledge Twins - Envelope Match Scoring

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

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .types import (
    EvidenceObject,
    HeatTreatCondition,
    HeatTreatment,
    LoadingMode,
    Phase,
    SpecimenType,
)

if TYPE_CHECKING:
    from .h2.query import H2Query


class EnvelopeMatchScorer:
    """
    Compute envelope match scores between query and evidence.
    Per Fran's spec: deterministic, per-dimension scoring.
    """

    @staticmethod
    def score_pressure(query_mpa: Optional[float], evidence_mpa: Optional[float]) -> float:
        """Score pressure match on log scale (hydrogen effects are pressure-sensitive)."""
        if query_mpa is None or evidence_mpa is None:
            return 0.5  # Neutral but flagged as gap

        if evidence_mpa <= 0 or query_mpa <= 0:
            return 0.0

        d = abs(math.log10(query_mpa / evidence_mpa))

        if d <= 0.05:
            return 1.0
        if d <= 0.20:
            return 0.8
        if d <= 0.50:
            return 0.6
        return 0.3

    @staticmethod
    def score_temperature(query_c: Optional[float], evidence_c: Optional[float]) -> float:
        """Score temperature match with special handling for cryo boundary."""
        if query_c is None or evidence_c is None:
            return 0.5

        # Cryo boundary: big change in behavior
        query_cryo = query_c < -150
        evidence_cryo = evidence_c < -150

        if query_cryo != evidence_cryo:
            return 0.2  # Heavy penalty for crossing cryo boundary

        # Within same regime: absolute distance
        diff = abs(query_c - evidence_c)
        if diff < 10:
            return 1.0
        elif diff < 50:
            return 0.8
        elif diff < 100:
            return 0.5
        else:
            return 0.3

    @staticmethod
    def score_phase(query: Phase, evidence: Phase) -> float:
        """GH2 vs LH2 mismatch penalized heavily."""
        if query == Phase.UNKNOWN or evidence == Phase.UNKNOWN:
            return 0.5
        if query == evidence:
            return 1.0
        return 0.3  # Heavy penalty

    @staticmethod
    def score_loading(query: LoadingMode, evidence: LoadingMode) -> float:
        """Static vs cyclic mismatch penalized."""
        if query == LoadingMode.UNKNOWN or evidence == LoadingMode.UNKNOWN:
            return 0.5
        if query == evidence:
            return 1.0
        # Cyclic is generally more severe
        if evidence == LoadingMode.CYCLIC and query == LoadingMode.STATIC:
            return 0.7  # Evidence is conservative
        return 0.4

    @staticmethod
    def score_condition(query_ht: Optional[HeatTreatment], evidence_ht: Optional[HeatTreatment]) -> float:
        """
        Score heat treatment condition match.
        CRITICAL: Aged vs non-aged is huge difference.
        """
        if query_ht is None or evidence_ht is None:
            return 0.5

        # Aged mismatch is severe
        query_aged = query_ht.is_aged()
        evidence_aged = evidence_ht.is_aged()

        if query_aged != evidence_aged:
            return 0.3  # Heavy penalty

        # Solution temp matters for superalloys
        if query_ht.solution_temp_c and evidence_ht.solution_temp_c:
            temp_diff = abs(query_ht.solution_temp_c - evidence_ht.solution_temp_c)
            if temp_diff > 100:
                return 0.5

        return 0.9

    @staticmethod
    def score_notch(query_notch: Optional[bool], evidence_specimen: SpecimenType) -> float:
        """
        Score notch/specimen type match.
        Notched data is more conservative.
        """
        if query_notch is None:
            return 0.5

        evidence_notched = evidence_specimen == SpecimenType.NOTCHED

        if query_notch == evidence_notched:
            return 1.0

        # Notched evidence for smooth query is conservative
        if evidence_notched and not query_notch:
            return 0.7

        # Smooth evidence for notched query is non-conservative
        return 0.4

    def compute_envelope_score(
        self,
        query: "H2Query",
        evidence: EvidenceObject
    ) -> Tuple[float, Dict[str, float], List[str]]:
        """
        Compute overall envelope match score.

        Returns: (total_score, dimension_scores, gaps)
        """
        gaps = []
        scores = {}

        # Pressure
        query_pressure = query.pressure_mpa
        evidence_pressure = evidence.environment.pressure_mpa if evidence.environment else None
        scores["pressure"] = self.score_pressure(query_pressure, evidence_pressure)
        if query_pressure is None:
            gaps.append("pressure")

        # Temperature
        query_temp = query.temperature_c
        evidence_temp = evidence.environment.temperature_c if evidence.environment else None
        scores["temperature"] = self.score_temperature(query_temp, evidence_temp)
        if query_temp is None:
            gaps.append("temperature")

        # Phase
        evidence_phase = evidence.environment.phase if evidence.environment else Phase.UNKNOWN
        scores["phase"] = self.score_phase(query.phase, evidence_phase)

        # Loading
        evidence_loading = evidence.loading.mode if evidence.loading else LoadingMode.UNKNOWN
        scores["loading"] = self.score_loading(query.loading_mode, evidence_loading)

        # Condition
        scores["condition"] = self.score_condition(query.heat_treatment, evidence.heat_treatment)
        if query.condition == HeatTreatCondition.UNKNOWN:
            gaps.append("heat_treatment")

        # Notch
        scores["notch"] = self.score_notch(query.has_notch, evidence.specimen_type)

        # Strength (if available)
        if query.strength and evidence.loading:
            scores["strength"] = 0.8
        else:
            scores["strength"] = 0.5
            if query.strength is None:
                gaps.append("strength")

        # Total: weighted average
        weights = {
            "pressure": 0.2,
            "temperature": 0.2,
            "phase": 0.15,
            "loading": 0.15,
            "condition": 0.15,
            "notch": 0.1,
            "strength": 0.05,
        }

        total = sum(scores[k] * weights[k] for k in scores.keys())

        # Penalty for gaps (but don't kill the score)
        gap_penalty = 0.05 * len(gaps)
        total = max(0.1, total - gap_penalty)

        return (total, scores, gaps)
