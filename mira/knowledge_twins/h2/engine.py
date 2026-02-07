#!/usr/bin/env python3
"""
Module: Engine
Purpose: H2 Knowledge Twin - Decision Engine

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import List, Optional

from ..types import (
    AuditTrail,
    Constraint,
    Driver,
    EvidenceGrade,
    EvidenceObject,
    Gap,
    HEEBand,
    HeatTreatCondition,
    HydrogenEnvironment,
    MatchStats,
    Phase,
    RecommendedTest,
    Verdict,
    band_to_verdict_floor,
)
from ..scoring import EnvelopeMatchScorer
from ..matching import CandidateFinder
from .query import H2Query, H2Response
from .rules import RuleEngine


class H2DecisionEngine:
    """
    The core decision engine for H2 compatibility assessment.

    Pipeline:
    1. Normalize material + condition -> material_key
    2. Normalize environment + loading -> env_envelope
    3. Retrieve candidate evidence by material_family + env tags
    4. Compute envelope match score per evidence
    5. Apply rule gates
    6. Aggregate conservatively -> verdict
    7. Generate explanation + audit trail
    """

    def __init__(self, evidence_store: Optional[List[EvidenceObject]] = None):
        self.evidence_store = evidence_store or []
        self.scorer = EnvelopeMatchScorer()
        self.rules = RuleEngine()
        self.finder = CandidateFinder(self.evidence_store)
        self.version = "2.1.0"

    def query(self, q: H2Query) -> H2Response:
        """Execute a compatibility query."""
        query_id = str(uuid.uuid4())
        timestamp = datetime.now()

        # Initialize response components
        drivers: List[Driver] = []
        constraints: List[Constraint] = []
        all_gaps: List[str] = []
        warnings: List[str] = []
        mismatches: List[str] = []
        match_stats: List[MatchStats] = []
        query_in_nasa_envelope: Optional[bool] = None

        # Step 1: Environment validity check
        if q.pressure_mpa and q.temperature_c:
            env = HydrogenEnvironment(
                phase=q.phase,
                pressure_mpa=q.pressure_mpa,
                temperature_c=q.temperature_c
            )
            is_valid, env_warnings = env.is_within_nasa_envelope()
            query_in_nasa_envelope = is_valid
            warnings.extend(env_warnings)

        # Step 2: Find matching evidence
        candidates = self.finder.find_candidates(q)

        if not candidates:
            return self._no_candidates_response(
                q, query_id, timestamp, warnings, self.finder.generic_query_prompt
            )

        # Step 3: Score each evidence object
        scored_evidence = []
        best_overall = None

        for ev in candidates:
            score, dim_scores, gaps = self.scorer.compute_envelope_score(q, ev)
            all_gaps.extend(gaps)

            # Weight by evidence grade
            grade_weight = {
                EvidenceGrade.PRIMARY_TEST: 1.0,
                EvidenceGrade.SECONDARY_SUMMARY: 0.7,
                EvidenceGrade.GUIDELINE_STATEMENT: 0.4,
            }.get(ev.grade, 0.5)

            final_weight = score * grade_weight * ev.extraction_confidence
            scored_evidence.append((ev, score, final_weight, dim_scores, gaps))

            if best_overall is None or score > best_overall[1]:
                best_overall = (ev, score, final_weight, dim_scores, gaps)

            match_stats.append(MatchStats(
                evidence_id=ev.evidence_id,
                envelope_match_score=score,
                dimension_scores=dim_scores,
                evidence_weight=final_weight
            ))

        # Derive explicit envelope mismatches
        if best_overall is not None:
            mismatches = self._compute_mismatches(q, best_overall)

        # Step 4: Find best matching evidence
        threshold = 0.4
        credible = [(ev, score, weight, dims, gaps)
                    for ev, score, weight, dims, gaps in scored_evidence
                    if score >= threshold]

        if not credible:
            return self._poor_match_response(
                q, query_id, timestamp, warnings, all_gaps, mismatches, scored_evidence, match_stats
            )

        # Step 5: Select dominant evidence (CONSERVATIVE: use worst HEE band)
        credible_sorted = sorted(credible, key=lambda x: x[1], reverse=True)
        best_score = credible_sorted[0][1] if credible_sorted else 0.0

        dominant, worst_matched = self._select_dominant_evidence(credible_sorted)

        # SAFETY CRITICAL: Use worst-case evidence for verdict determination
        # The worst_matched evidence represents the most severe HEE band among credible matches
        # This ensures we don't underestimate embrittlement risk
        if worst_matched:
            worst_ev, worst_score, _, _, _ = worst_matched
            worst_band = worst_ev.hee_band if worst_ev.hee_band else HEEBand.NEGLIGIBLE
        elif dominant:
            worst_ev = dominant[0]
            worst_band = worst_ev.hee_band if worst_ev.hee_band else HEEBand.NEGLIGIBLE
        else:
            worst_ev = None
            worst_band = HEEBand.NEGLIGIBLE

        # Add warning if there's conflicting evidence with different severity bands
        if credible_sorted:
            self._add_severity_warning(credible_sorted, warnings)

        # Step 6: Apply rule gates
        query_is_aged = (
            q.heat_treatment.is_aged() if q.heat_treatment
            else (q.condition == HeatTreatCondition.SOLUTION_TREATED_AGED)
        )
        aged_evidence_found = False
        if query_is_aged:
            aged_evidence_found = any(
                (ev.heat_treatment is not None and ev.heat_treatment.is_aged()) and score >= 0.65
                for ev, score, _, _, _ in credible
            )

        rule_verdict, conf_penalty, rule_drivers, rule_constraints, triggers = self.rules.evaluate(
            q, worst_band, best_score,
            aged_evidence_found=aged_evidence_found,
            dominant_evidence_id=(worst_ev.evidence_id if worst_ev else None)
        )

        drivers.extend(rule_drivers)
        constraints.extend(rule_constraints)

        # Step 7: Determine verdict
        final_verdict = self._determine_verdict(
            rule_verdict, worst_band, best_score, all_gaps, credible, query_in_nasa_envelope, worst_ev
        )

        # Step 8: Calculate confidence
        final_confidence = self._calculate_confidence(best_score, conf_penalty, all_gaps, credible)

        # Step 9: Generate response
        return self._build_response(
            q, final_verdict, final_confidence, worst_ev, warnings, mismatches,
            all_gaps, drivers, constraints, credible_sorted, query_id, timestamp, triggers, match_stats
        )

    def _no_candidates_response(
        self, q: H2Query, query_id: str, timestamp: datetime,
        warnings: List[str], generic_prompt: Optional[str]
    ) -> H2Response:
        """Generate response when no candidates found."""
        if generic_prompt:
            return H2Response(
                verdict=Verdict.UNKNOWN,
                confidence=0.0,
                decision_summary=(
                    f"'{q.material_name}' is too generic for a specific assessment. "
                    f"{generic_prompt}"
                ),
                gaps=[Gap(
                    parameter="alloy_designation",
                    impact="Different alloys have vastly different HEE susceptibility",
                    default_assumption=None
                )],
                recommended_tests=[],
                warnings=[],
                audit=AuditTrail(
                    query_id=query_id,
                    timestamp=timestamp,
                    engine_version=self.version,
                    rule_triggers=[],
                    match_stats=[],
                    dominant_evidence_ids=[],
                    confidence_calculation="Generic query - needs alloy specification"
                )
            )

        return H2Response(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            decision_summary=(
                f"No evidence found for {q.material_name} in hydrogen environment. "
                "Cannot make a compatibility determination. "
                "Recommend conducting baseline HEE testing per ASTM G129."
            ),
            gaps=[Gap(
                parameter="evidence",
                impact="No data available for this material/condition combination",
                default_assumption=None
            )],
            recommended_tests=[RecommendedTest(
                test_type="notched tensile",
                description="Baseline HEE characterization",
                target_conditions="in H2 at target pressure/temperature",
                standard="ASTM G129"
            )],
            warnings=warnings,
            audit=AuditTrail(
                query_id=query_id,
                timestamp=timestamp,
                engine_version=self.version,
                rule_triggers=[],
                match_stats=[],
                dominant_evidence_ids=[],
                confidence_calculation="No evidence found"
            )
        )

    def _poor_match_response(
        self, q: H2Query, query_id: str, timestamp: datetime,
        warnings: List[str], all_gaps: List[str], mismatches: List[str],
        scored_evidence: list, match_stats: List[MatchStats]
    ) -> H2Response:
        """Generate response when evidence exists but envelope match is poor."""
        unique_gaps = list(set(all_gaps))
        mismatch_note = f" Major mismatches: {', '.join(mismatches)}." if mismatches else ""
        gap_note = f" Missing inputs: {', '.join(unique_gaps)}." if unique_gaps else ""

        return H2Response(
            verdict=Verdict.UNKNOWN,
            confidence=0.2,
            decision_summary=(
                f"Evidence exists for {q.material_name} but envelope match is poor. "
                f"Test conditions differ significantly from query conditions."
                f"{mismatch_note}{gap_note}"
            ),
            gaps=[Gap(parameter=g, impact="Weak envelope match") for g in unique_gaps],
            mismatches=mismatches,
            evidence=[ev for ev, _, _, _, _ in scored_evidence[:3]],
            warnings=warnings,
            audit=AuditTrail(
                query_id=query_id,
                timestamp=timestamp,
                engine_version=self.version,
                rule_triggers=[],
                match_stats=match_stats,
                dominant_evidence_ids=[],
                confidence_calculation="Envelope match below threshold"
            )
        )

    def _compute_mismatches(self, q: H2Query, best_overall: tuple) -> List[str]:
        """Compute explicit envelope mismatches."""
        mismatches = []
        best_ev, _, _, _, best_gaps = best_overall
        best_env = best_ev.environment

        # Phase mismatch
        if "phase" not in best_gaps and q.phase != Phase.UNKNOWN and best_env and best_env.phase != Phase.UNKNOWN:
            if q.phase != best_env.phase:
                mismatches.append(f"phase mismatch (query {q.phase.value} vs evidence {best_env.phase.value})")

        # Cryo regime mismatch
        if "temperature" not in best_gaps and q.temperature_c is not None and best_env and best_env.temperature_c is not None:
            q_cryo = q.temperature_c < -150
            e_cryo = best_env.temperature_c < -150
            if q_cryo != e_cryo:
                mismatches.append("temperature regime mismatch (crosses cryogenic boundary ~-150C)")

        # Pressure mismatch
        if "pressure" not in best_gaps and q.pressure_mpa is not None and best_env and best_env.pressure_mpa is not None:
            d = abs(math.log10(q.pressure_mpa / best_env.pressure_mpa))
            if d > 0.50:
                mismatches.append("pressure mismatch (evidence pressure differs by >~3x)")

        return mismatches

    def _select_dominant_evidence(self, credible_sorted: list) -> tuple:
        """Select dominant and worst-matched evidence."""
        severity_rank = {
            HEEBand.NEGLIGIBLE: 0,
            HEEBand.SMALL: 1,
            HEEBand.HIGH: 2,
            HEEBand.SEVERE: 3,
            HEEBand.EXTREME: 4,
        }

        dominant = None
        for ev, score, weight, dims, gaps in credible_sorted:
            if ev.hee_band:
                dominant = (ev, score, weight, dims, gaps)
                break

        worst_matched = None
        worst_severity = -1
        for ev, score, weight, dims, gaps in credible_sorted:
            if ev.hee_band and score >= 0.5:
                sev = severity_rank.get(ev.hee_band, 0)
                if sev > worst_severity:
                    worst_matched = (ev, score, weight, dims, gaps)
                    worst_severity = sev

        return dominant, worst_matched

    def _add_severity_warning(self, credible_sorted: List[tuple], warnings: List[str]):
        """Add warning explaining why evidence shows different HEE bands.

        This helps users understand that variation is due to different test
        conditions (heat treatment, pressure, orientation), not bad data.
        """
        severity_rank = {
            HEEBand.NEGLIGIBLE: 0,
            HEEBand.SMALL: 1,
            HEEBand.HIGH: 2,
            HEEBand.SEVERE: 3,
            HEEBand.EXTREME: 4,
        }

        # Collect all HEE bands from credible evidence
        bands_found = set()
        heat_treatments = set()
        pressures = set()
        orientations = set()

        for ev, score, weight, dims, gaps in credible_sorted:
            if ev.hee_band:
                bands_found.add(ev.hee_band)
            if ev.heat_treatment:
                heat_treatments.add(ev.heat_treatment.condition if ev.heat_treatment else None)
            if ev.environment and ev.environment.pressure_mpa:
                pressures.add(round(ev.environment.pressure_mpa, 0))
            if ev.grain_direction:
                orientations.add(ev.grain_direction)

        if len(bands_found) < 2:
            return  # No variation to explain

        # Calculate severity range
        min_band = min(bands_found, key=lambda b: severity_rank.get(b, 0))
        max_band = max(bands_found, key=lambda b: severity_rank.get(b, 0))
        severity_gap = severity_rank[max_band] - severity_rank[min_band]

        # Only warn if there's meaningful variation (gap >= 1)
        if severity_gap >= 1:
            # Build explanation based on what varies across evidence
            diff_reasons = []
            if len(heat_treatments) > 1:
                diff_reasons.append("heat treatment")
            if len(pressures) > 1:
                diff_reasons.append("test pressure")
            if len(orientations) > 1:
                diff_reasons.append("grain orientation")

            reason_text = ", ".join(diff_reasons) if diff_reasons else "test conditions"

            warnings.append(
                f"Evidence shows {min_band.value} to {max_band.value} HEE "
                f"depending on {reason_text}. Using conservative {max_band.value} "
                f"rating for safety. Specify exact conditions for a more precise assessment."
            )

    def _determine_verdict(
        self, rule_verdict: Optional[Verdict], worst_band: HEEBand, best_score: float,
        all_gaps: List[str], credible: list, query_in_nasa_envelope: Optional[bool],
        worst_ev: Optional[EvidenceObject]
    ) -> Verdict:
        """Determine final verdict."""
        base_verdict = band_to_verdict_floor(worst_band)

        if rule_verdict == Verdict.NOT_RECOMMENDED:
            return Verdict.NOT_RECOMMENDED
        elif base_verdict == Verdict.NOT_RECOMMENDED:
            return Verdict.NOT_RECOMMENDED
        elif best_score >= 0.8 and not all_gaps and worst_band in [HEEBand.NEGLIGIBLE, HEEBand.SMALL]:
            has_primary = any(ev.grade == EvidenceGrade.PRIMARY_TEST for ev, s, w, _, _ in credible if s >= 0.8)
            if has_primary:
                final_verdict = Verdict.ALLOWED
            else:
                final_verdict = Verdict.ALLOWED_WITH_CONSTRAINTS
        else:
            final_verdict = Verdict.ALLOWED_WITH_CONSTRAINTS

        # Guardrail: no ALLOWED if extrapolating outside NASA envelope
        if final_verdict == Verdict.ALLOWED and query_in_nasa_envelope is False:
            ev_in_envelope = True
            if worst_ev and worst_ev.environment:
                ev_in_envelope, _ = worst_ev.environment.is_within_nasa_envelope()
            if ev_in_envelope:
                final_verdict = Verdict.ALLOWED_WITH_CONSTRAINTS

        return final_verdict

    def _calculate_confidence(
        self, best_score: float, conf_penalty: float, all_gaps: List[str], credible: list
    ) -> float:
        """Calculate final confidence score."""
        base_confidence = best_score

        primary_count = sum(1 for ev, _, _, _, _ in credible if ev.grade == EvidenceGrade.PRIMARY_TEST)
        if primary_count >= 2:
            base_confidence = min(base_confidence + 0.1, 1.0)
        elif primary_count == 0:
            base_confidence *= 0.7

        final_confidence = max(0.0, base_confidence - conf_penalty)

        unique_gaps = list(set(all_gaps))
        final_confidence -= 0.05 * len(unique_gaps)
        final_confidence = max(0.0, final_confidence)

        return round(final_confidence, 2)

    def _build_response(
        self, q: H2Query, final_verdict: Verdict, final_confidence: float,
        worst_ev: Optional[EvidenceObject], warnings: List[str], mismatches: List[str],
        all_gaps: List[str], drivers: List[Driver], constraints: List[Constraint],
        credible_sorted: list, query_id: str, timestamp: datetime,
        triggers: List[str], match_stats: List[MatchStats]
    ) -> H2Response:
        """Build the final response object."""
        unique_gaps = list(set(all_gaps))

        # Generate summary
        summary_parts = []
        if final_verdict == Verdict.ALLOWED:
            summary_parts.append(f"{q.material_name} is compatible with the specified hydrogen environment.")
        elif final_verdict == Verdict.ALLOWED_WITH_CONSTRAINTS:
            summary_parts.append(f"{q.material_name} may be used with constraints in the specified hydrogen environment.")
        elif final_verdict == Verdict.NOT_RECOMMENDED:
            summary_parts.append(f"{q.material_name} is NOT recommended for the specified hydrogen environment.")

        if worst_ev and worst_ev.hee_band:
            summary_parts.append(f"HEE susceptibility rated '{worst_ev.hee_band.value}' per matched evidence.")

        if warnings:
            summary_parts.append(f"Note: {warnings[0]}")

        if mismatches:
            summary_parts.append(f"Major envelope mismatches: {', '.join(mismatches)}")

        decision_summary = " ".join(summary_parts)

        # Build gaps list
        gap_objects = [
            Gap(parameter=g, impact=f"Missing {g} weakens envelope match", default_assumption="conservative")
            for g in unique_gaps
        ]

        # Build recommended tests
        recommended = []
        if unique_gaps or final_verdict != Verdict.ALLOWED:
            recommended.append(RecommendedTest(
                test_type="notched tensile",
                description="HEE characterization at service conditions",
                target_conditions=f"in H2 at {q.pressure_mpa or 'target'} MPa, {q.temperature_c or 'target'}C",
                standard="ASTM G129"
            ))

        # Add driver for dominant evidence
        if worst_ev and worst_ev.hee_band:
            already = any(
                d.failure_mode == "Hydrogen environment embrittlement" and worst_ev.evidence_id in (d.evidence_ids or [])
                for d in drivers
            )
            if not already:
                drivers.append(Driver(
                    failure_mode="Hydrogen environment embrittlement",
                    severity=worst_ev.hee_band.value,
                    trigger_parameter="HEE_index",
                    explanation=f"Based on {worst_ev.metric.metric_name if worst_ev.metric else 'N/A'} "
                               f"= {worst_ev.metric.value if worst_ev.metric else 'N/A'}",
                    evidence_ids=[worst_ev.evidence_id]
                ))

        return H2Response(
            verdict=final_verdict,
            confidence=final_confidence,
            decision_summary=decision_summary,
            drivers=drivers,
            constraints=constraints,
            gaps=gap_objects,
            mismatches=mismatches,
            recommended_tests=recommended,
            evidence=[ev for ev, _, _, _, _ in credible_sorted[:5]],
            warnings=warnings,
            audit=AuditTrail(
                query_id=query_id,
                timestamp=timestamp,
                engine_version=self.version,
                rule_triggers=triggers,
                match_stats=match_stats,
                dominant_evidence_ids=[worst_ev.evidence_id] if worst_ev else [],
                confidence_calculation=f"base={credible_sorted[0][1]:.2f}, gaps={len(unique_gaps)}"
            )
        )

    def add_evidence(self, evidence: EvidenceObject):
        """Add evidence to the store."""
        self.evidence_store.append(evidence)
        self.finder = CandidateFinder(self.evidence_store)
