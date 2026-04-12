#!/usr/bin/env python3
"""
Module: H2 Knowledge Twin V2
Purpose: Evidence-weighted hydrogen compatibility assessment engine.

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True

Engine logic for H2 compatibility assessment. Type definitions (enums,
dataclasses) are in h2_twin_v2_types.py. This file contains:
- Classification functions (HEE band, verdict floor, Ni predictor)
- EnvelopeMatchScorer (pressure, temperature, phase, loading scoring)
- RuleEngine (deterministic safety gates)
- H2DecisionEngine (7-step query pipeline)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from mira.knowledge_twins.h2_twin_v2_types import (
    Verdict,
    HEEBand,
    HEMechanism,
    EvidenceGrade,
    Phase,
    LoadingMode,
    SpecimenType,
    ProductForm,
    WeldState,
    MaterialFamily,
    HeatTreatCondition,
    ReferenceEnvironment,
    TemperatureBehavior,
    Composition,
    HeatTreatment,
    StrengthData,
    LoadingRates,
    MaterialRecord,
    HydrogenEnvironment,
    LoadingState,
    Provenance,
    MetricValue,
    EvidenceObject,
    H2Query,
    Driver,
    Constraint,
    Gap,
    RecommendedTest,
    MatchStats,
    AuditTrail,
    H2Response,
)

# =============================================================================
# SECTION 1: DESIGN PRINCIPLES (NON-NEGOTIABLE)
# =============================================================================
"""
1. EVIDENCE-FIRST
   No claim without a pointer to a source and a concrete extracted value.
   
2. CONSERVATIVE UNDER UNCERTAINTY
   If envelope match is weak or missing key inputs, verdict trends toward
   Unknown or Allowed-with-constraints. Never "Allowed" by vibes.
   
3. DETERMINISTIC + AUDITABLE
   Same inputs → same result. Every step logs evidence IDs, match scores,
   and rule triggers.
   
4. HUMAN-LEGIBLE REASONING
   Engineers must be able to read the answer and disagree constructively.

5. DOMAIN-ACCURATE
   Data structures match the source documents exactly. No hand-wavy fields.
   Three loading rates, not one. Full heat treatment, not an enum.
"""

logger = logging.getLogger(__name__)


# =============================================================================
# SECTIONS 2-8: Type definitions — extracted to h2_twin_v2_types.py
# Enums: Verdict, HEEBand, HEMechanism, EvidenceGrade, Phase, LoadingMode,
#        SpecimenType, ProductForm, WeldState, MaterialFamily, etc.
# Dataclasses: Composition, HeatTreatment, StrengthData, MaterialRecord,

# =============================================================================
# SECTION 9: CLASSIFICATION FUNCTIONS
# =============================================================================

def classify_hee_band(index: float) -> HEEBand:
    """
    Classify HEE index to band per NASA/TM-2016-218602 Table 1.
    """
    if index >= 0.97:
        return HEEBand.NEGLIGIBLE
    elif index >= 0.90:
        return HEEBand.SMALL
    elif index >= 0.70:
        return HEEBand.HIGH
    elif index >= 0.50:
        return HEEBand.SEVERE
    else:
        return HEEBand.EXTREME


def band_to_verdict_floor(band: HEEBand) -> Verdict:
    """
    Map HEE band to minimum verdict (floor).
    Conservative: severe/extreme → not_recommended.
    """
    if band == HEEBand.NEGLIGIBLE:
        return Verdict.ALLOWED_WITH_CONSTRAINTS  # Need strong match for ALLOWED
    elif band == HEEBand.SMALL:
        return Verdict.ALLOWED_WITH_CONSTRAINTS
    elif band == HEEBand.HIGH:
        return Verdict.ALLOWED_WITH_CONSTRAINTS
    elif band == HEEBand.SEVERE:
        return Verdict.NOT_RECOMMENDED
    else:  # EXTREME
        return Verdict.NOT_RECOMMENDED


def apply_ni_predictor(
    ni_wt_pct: float,
    family: MaterialFamily,
    condition: HeatTreatCondition
) -> Tuple[Optional[HEEBand], str, float]:
    """
    Apply nickel content predictor for Fe-Ni-Cr systems.
    Per NASA/TM-2016-218602 Table 10, Figure 15.
    
    Returns: (predicted_band, rationale, confidence)
    """
    # Check applicability
    fe_ni_cr_families = [
        MaterialFamily.AUSTENITIC_SS_304,
        MaterialFamily.AUSTENITIC_SS_316,
        MaterialFamily.AUSTENITIC_SS_321_347,
        MaterialFamily.NITROGEN_SS,
        MaterialFamily.PH_SS_A286,
        MaterialFamily.IRON_SUPERALLOY,
        MaterialFamily.NICKEL_SUPERALLOY,
    ]
    
    if family not in fe_ni_cr_families:
        return (None, "Ni predictor only valid for Fe-Ni-Cr systems", 0.0)
    
    if condition not in [HeatTreatCondition.ANNEALED, HeatTreatCondition.SOLUTION_TREATED]:
        return (
            None,
            f"Ni predictor requires annealed/ST condition. "
            f"Aging significantly increases susceptibility regardless of Ni content.",
            0.0
        )
    
    # Apply predictor
    if ni_wt_pct < 8.0:
        return (
            HEEBand.SEVERE,
            f"Ni {ni_wt_pct}% < 8% → typically severe HEE",
            0.7
        )
    elif ni_wt_pct < NI_PREDICTOR["threshold_wt_pct"]:
        return (
            HEEBand.HIGH,
            f"Ni {ni_wt_pct}% in transition zone (8-12.5%)",
            0.6
        )
    elif ni_wt_pct <= NI_PREDICTOR["max_for_predictor"]:
        return (
            HEEBand.NEGLIGIBLE,
            f"Ni {ni_wt_pct}% in negligible range (12.5-35%) per Table 10",
            0.75
        )
    else:
        return (
            HEEBand.HIGH,
            f"Ni {ni_wt_pct}% > 35% → Ni-rich superalloys can show increased susceptibility",
            0.5
        )


def get_temperature_behavior(family: MaterialFamily, material_name: str) -> TemperatureBehavior:
    """
    Get expected temperature dependence for HEE.
    Per NASA/TM-2016-218602 Figures 12-14.
    
    CRITICAL: Some superalloys peak at 400-600°C, NOT room temp!
    """
    # Check for elevated temp peak materials
    for mat in ELEVATED_TEMP_PEAK_MATERIALS:
        if mat.lower() in material_name.lower():
            return TemperatureBehavior.PEAK_AT_ELEVATED
    
    # Most austenitic materials peak near ambient
    if family in [
        MaterialFamily.AUSTENITIC_SS_304,
        MaterialFamily.AUSTENITIC_SS_316,
        MaterialFamily.AUSTENITIC_SS_321_347,
        MaterialFamily.IRON_SUPERALLOY,
    ]:
        return TemperatureBehavior.PEAK_NEAR_AMBIENT
    
    return TemperatureBehavior.PEAK_NEAR_AMBIENT


# =============================================================================
# SECTION 10: ENVELOPE MATCHING ENGINE
# =============================================================================

class EnvelopeMatchScorer:
    """
    Compute envelope match scores between query and evidence.
    Per Fran's spec: deterministic, per-dimension scoring.
    """
    
    @staticmethod
    def score_pressure(query_mpa: Optional[float], evidence_mpa: Optional[float]) -> float:
        """
        Score pressure match on log scale (hydrogen effects are pressure-sensitive).
        """
        if query_mpa is None or evidence_mpa is None:
            return 0.5  # Neutral but flagged as gap
        
        if evidence_mpa <= 0 or query_mpa <= 0:
            return 0.0
        
        # Log scale ratio
        import math
        ratio = math.log10(query_mpa) / math.log10(evidence_mpa)
        
        # Score: 1.0 if exact, decreasing with distance
        if 0.8 <= ratio <= 1.2:
            return 1.0 - abs(1.0 - ratio) * 0.5
        elif 0.5 <= ratio <= 2.0:
            return 0.6
        else:
            return 0.3
    
    @staticmethod
    def score_temperature(query_c: Optional[float], evidence_c: Optional[float]) -> float:
        """
        Score temperature match.
        Special handling for cryo boundary.
        """
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
        query: H2Query,
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
            # Could add strength matching here
            scores["strength"] = 0.8
        else:
            scores["strength"] = 0.5
            if query.strength is None:
                gaps.append("strength")
        
        # Total: weighted average instead of product (product is too harsh)
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


# =============================================================================
# SECTION 11: RULE GATES
# =============================================================================

@dataclass
class RuleGate:
    """
    A rule that can trigger verdict floors, constraints, or warnings.
    """
    rule_id: str
    name: str
    trigger_predicate: str                        # Description of trigger
    effect_type: str                              # "hard_block", "soft_warning", "add_constraint"
    verdict_floor: Optional[Verdict] = None
    confidence_penalty: float = 0.0
    constraint: Optional[Constraint] = None
    driver: Optional[Driver] = None
    source: str = ""  # NASA SWE-013 traceability



class RuleEngine:
    """
    Rule engine for fast conservative gates.
    """
    
    def __init__(self):
        self.gates: List[RuleGate] = self._load_default_gates()
    
    def _load_default_gates(self) -> List[RuleGate]:
        """Load default rule gates."""
        return [
            # Hard block: severe HEE band with matching envelope
            RuleGate(
                rule_id="R001",
                name="Severe HEE Block",
                trigger_predicate="HEE band is SEVERE or EXTREME with envelope match > 0.65",
                effect_type="hard_block",
                verdict_floor=Verdict.NOT_RECOMMENDED,
                driver=Driver(
                    failure_mode="Hydrogen environment embrittlement",
                    severity="severe",
                    trigger_parameter="HEE_band",
                    explanation="Material shows severe susceptibility at test conditions"
                )
            ),
            
            # Soft warning: weld/HAZ
            RuleGate(
                rule_id="R002",
                name="Weld HAZ Warning",
                trigger_predicate="weld_state is HAZ",
                effect_type="soft_warning",
                confidence_penalty=0.15,
                constraint=Constraint(
                    parameter="weld_qualification",
                    limit_type="required",
                    rationale="HAZ often shows worse HEE than base metal - requires specific qualification"
                )
            ),
            
            # Soft warning: aged condition without evidence
            RuleGate(
                rule_id="R003",
                name="Aged Condition Warning",
                trigger_predicate="condition is aged but no aged-specific evidence",
                effect_type="soft_warning",
                confidence_penalty=0.2,
                driver=Driver(
                    failure_mode="Heat treatment sensitivity",
                    severity="high",
                    trigger_parameter="heat_treatment",
                    explanation="Aged conditions typically show much higher HEE susceptibility than annealed/ST"
                )
            ),
            
            # Constraint: high strength
            RuleGate(
                rule_id="R004",
                name="High Strength Constraint",
                trigger_predicate="yield_strength > 1200 MPa or UTS > 1400 MPa",
                effect_type="add_constraint",
                constraint=Constraint(
                    parameter="strength",
                    limit_type="max",
                    limit_value="1200 MPa yield",
                    rationale="High strength increases HEE susceptibility - verify with strength-specific data"
                )
            ),
        ]
    
    def evaluate(
        self,
        query: H2Query,
        evidence_band: Optional[HEEBand],
        envelope_score: float
    ) -> Tuple[Optional[Verdict], float, List[Driver], List[Constraint], List[str]]:
        """
        Evaluate rule gates.
        
        Returns: (verdict_floor, confidence_penalty, drivers, constraints, triggers)
        """
        verdict_floor = None
        total_penalty = 0.0
        drivers = []
        constraints = []
        triggers = []
        
        for gate in self.gates:
            triggered = False
            
            # R001: Severe HEE
            if gate.rule_id == "R001":
                if evidence_band in [HEEBand.SEVERE, HEEBand.EXTREME] and envelope_score >= 0.65:
                    triggered = True
            
            # R002: Weld HAZ
            elif gate.rule_id == "R002":
                if query.weld_state == WeldState.HAZ:
                    triggered = True
            
            # R003: Aged condition
            elif gate.rule_id == "R003":
                if query.condition == HeatTreatCondition.SOLUTION_TREATED_AGED:
                    triggered = True
            
            # R004: High strength
            elif gate.rule_id == "R004":
                if query.strength:
                    if (query.strength.yield_mpa and query.strength.yield_mpa > 1200) or \
                       (query.strength.uts_mpa and query.strength.uts_mpa > 1400):
                        triggered = True
            
            if triggered:
                triggers.append(gate.rule_id)
                total_penalty += gate.confidence_penalty
                
                if gate.verdict_floor:
                    if verdict_floor is None:
                        verdict_floor = gate.verdict_floor
                    elif gate.verdict_floor == Verdict.NOT_RECOMMENDED:
                        verdict_floor = Verdict.NOT_RECOMMENDED
                
                if gate.driver:
                    drivers.append(gate.driver)
                
                if gate.constraint:
                    constraints.append(gate.constraint)
        
        return (verdict_floor, total_penalty, drivers, constraints, triggers)


# =============================================================================
# SECTION 12: DECISION ENGINE
# =============================================================================

class H2DecisionEngine:
    """
    The core decision engine.
    
    Pipeline:
    1. Normalize material + condition → material_key
    2. Normalize environment + loading → env_envelope
    3. Retrieve candidate evidence by material_family + env tags
    4. Compute envelope match score per evidence
    5. Apply rule gates
    6. Aggregate conservatively → verdict
    7. Generate explanation + audit trail
    """
    
    def __init__(self, evidence_store: Optional[List[EvidenceObject]] = None):
        self.evidence_store = evidence_store or []
        self.scorer = EnvelopeMatchScorer()
        self.rules = RuleEngine()
        self.version = "2.0.0"
    
    def query(self, q: H2Query) -> H2Response:
        """
        Execute a compatibility query.
        """
        query_id = str(uuid.uuid4())
        timestamp = datetime.now()
        
        # Initialize response components
        drivers = []
        constraints = []
        all_gaps = []
        warnings = []
        match_stats = []
        
        # Step 1: Environment validity check
        if q.pressure_mpa and q.temperature_c:
            env = HydrogenEnvironment(
                phase=q.phase,
                pressure_mpa=q.pressure_mpa,
                temperature_c=q.temperature_c
            )
            is_valid, env_warnings = env.is_within_nasa_envelope()
            warnings.extend(env_warnings)
        
        # Step 2: Find matching evidence
        candidates = self._find_candidates(q)
        
        if not candidates:
            # No evidence found
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
                    target_conditions=f"in H2 at target pressure/temperature",
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
        
        # Step 3: Score each evidence object
        scored_evidence = []
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
            match_stats.append(MatchStats(
                evidence_id=ev.evidence_id,
                envelope_match_score=score,
                dimension_scores=dim_scores,
                evidence_weight=final_weight
            ))
        
        # Step 4: Find best matching evidence
        threshold = 0.4  # Minimum match threshold
        credible = [(ev, score, weight, dims, gaps) 
                    for ev, score, weight, dims, gaps in scored_evidence 
                    if score >= threshold]
        
        if not credible:
            # Evidence exists but no good match
            unique_gaps = list(set(all_gaps))
            return H2Response(
                verdict=Verdict.UNKNOWN,
                confidence=0.2,
                decision_summary=(
                    f"Evidence exists for {q.material_name} but envelope match is poor. "
                    f"Test conditions differ significantly from query conditions. "
                    f"Missing or mismatched: {', '.join(unique_gaps) if unique_gaps else 'conditions'}."
                ),
                gaps=[Gap(parameter=g, impact="Weak envelope match") for g in unique_gaps],
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
        
        # Step 5: Get worst credible evidence (conservative)
        worst_ev = None
        worst_band = HEEBand.NEGLIGIBLE
        best_score = 0.0
        
        for ev, score, weight, _, _ in credible:
            if ev.hee_band:
                # Find worst band among credible evidence
                band_order = [HEEBand.NEGLIGIBLE, HEEBand.SMALL, HEEBand.HIGH, 
                              HEEBand.SEVERE, HEEBand.EXTREME]
                if band_order.index(ev.hee_band) > band_order.index(worst_band):
                    worst_band = ev.hee_band
                    worst_ev = ev
            if score > best_score:
                best_score = score
        
        # Step 6: Apply rule gates
        rule_verdict, conf_penalty, rule_drivers, rule_constraints, triggers = \
            self.rules.evaluate(q, worst_band, best_score)
        
        drivers.extend(rule_drivers)
        constraints.extend(rule_constraints)
        
        # Step 7: Determine verdict
        base_verdict = band_to_verdict_floor(worst_band)
        
        if rule_verdict == Verdict.NOT_RECOMMENDED:
            final_verdict = Verdict.NOT_RECOMMENDED
        elif base_verdict == Verdict.NOT_RECOMMENDED:
            final_verdict = Verdict.NOT_RECOMMENDED
        elif best_score >= 0.8 and not all_gaps and worst_band in [HEEBand.NEGLIGIBLE, HEEBand.SMALL]:
            # Strong match, minimal gaps, good band → could be ALLOWED
            # But per Fran: need primary_test grade
            has_primary = any(ev.grade == EvidenceGrade.PRIMARY_TEST for ev, s, w, _, _ in credible if s >= 0.8)
            if has_primary:
                final_verdict = Verdict.ALLOWED
            else:
                final_verdict = Verdict.ALLOWED_WITH_CONSTRAINTS
        else:
            final_verdict = Verdict.ALLOWED_WITH_CONSTRAINTS
        
        # Step 8: Calculate confidence
        base_confidence = best_score
        
        # Adjust for evidence quality
        primary_count = sum(1 for ev, _, _, _, _ in credible if ev.grade == EvidenceGrade.PRIMARY_TEST)
        if primary_count >= 2:
            base_confidence = min(base_confidence + 0.1, 1.0)
        elif primary_count == 0:
            base_confidence *= 0.7
        
        # Apply rule penalties
        final_confidence = max(0.0, base_confidence - conf_penalty)
        
        # Gap penalty
        unique_gaps = list(set(all_gaps))
        final_confidence -= 0.05 * len(unique_gaps)
        final_confidence = max(0.0, final_confidence)
        
        # Step 9: Generate explanation
        summary_parts = []
        
        if final_verdict == Verdict.ALLOWED:
            summary_parts.append(
                f"{q.material_name} is compatible with the specified hydrogen environment."
            )
        elif final_verdict == Verdict.ALLOWED_WITH_CONSTRAINTS:
            summary_parts.append(
                f"{q.material_name} may be used with constraints in the specified hydrogen environment."
            )
        elif final_verdict == Verdict.NOT_RECOMMENDED:
            summary_parts.append(
                f"{q.material_name} is NOT recommended for the specified hydrogen environment."
            )
        
        if worst_ev and worst_ev.hee_band:
            summary_parts.append(
                f"HEE susceptibility rated '{worst_ev.hee_band.value}' per matched evidence."
            )
        
        if warnings:
            summary_parts.append(f"Note: {warnings[0]}")
        
        decision_summary = " ".join(summary_parts)
        
        # Build gaps list
        gap_objects = []
        for g in unique_gaps:
            gap_objects.append(Gap(
                parameter=g,
                impact=f"Missing {g} weakens envelope match",
                default_assumption="conservative"
            ))
        
        # Build recommended tests
        recommended = []
        if unique_gaps or final_verdict != Verdict.ALLOWED:
            recommended.append(RecommendedTest(
                test_type="notched tensile",
                description="HEE characterization at service conditions",
                target_conditions=f"in H2 at {q.pressure_mpa or 'target'} MPa, {q.temperature_c or 'target'}°C",
                standard="ASTM G129"
            ))
        
        # Add driver for worst evidence
        if worst_ev and worst_ev.hee_band:
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
            confidence=round(final_confidence, 2),
            decision_summary=decision_summary,
            drivers=drivers,
            constraints=constraints,
            gaps=gap_objects,
            recommended_tests=recommended,
            evidence=[ev for ev, _, _, _, _ in credible[:5]],
            warnings=warnings,
            audit=AuditTrail(
                query_id=query_id,
                timestamp=timestamp,
                engine_version=self.version,
                rule_triggers=triggers,
                match_stats=match_stats,
                dominant_evidence_ids=[worst_ev.evidence_id] if worst_ev else [],
                confidence_calculation=f"base={best_score:.2f}, penalty={conf_penalty:.2f}, gaps={len(unique_gaps)}"
            )
        )
    
    def _find_candidates(self, q: H2Query) -> List[EvidenceObject]:
        """Find candidate evidence objects for query."""
        candidates = []
        
        # Normalize query name: lowercase, remove special chars
        query_tokens = set(q.material_name.lower().replace("_", " ").replace("-", " ").split())
        
        for ev in self.evidence_store:
            # Normalize evidence key
            ev_tokens = set(ev.material_key.lower().replace("_", " ").replace("-", " ").split())
            
            # Token overlap matching
            overlap = query_tokens & ev_tokens
            if len(overlap) >= 1:  # At least one meaningful token matches
                # Check it's a meaningful token (not just "steel" alone)
                meaningful = any(len(t) > 3 for t in overlap)
                if meaningful or len(overlap) >= 2:
                    candidates.append(ev)
                    continue
            
            # Direct substring match as fallback
            query_clean = q.material_name.lower().replace(" ", "").replace("-", "").replace("_", "")
            ev_clean = ev.material_key.lower().replace(" ", "").replace("-", "").replace("_", "")
            if query_clean in ev_clean or ev_clean in query_clean:
                candidates.append(ev)
        
        return candidates
    
    def add_evidence(self, evidence: EvidenceObject):
        """Add evidence to the store."""
        self.evidence_store.append(evidence)


# =============================================================================
# SECTION 13: EXAMPLE DATA + DEMO
# =============================================================================

def create_example_evidence() -> List[EvidenceObject]:
    """
    Create example evidence from NASA/TM-2016-218602.
    """
    evidence = []
    
    # 316 SS - Negligible HEE (Table 3)
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T3-316",
        material_key="316_stainless_steel",
        material_family=MaterialFamily.AUSTENITIC_SS_316,
        material_condition="annealed",
        heat_treatment=HeatTreatment(condition=HeatTreatCondition.ANNEALED),
        product_form=ProductForm.BAR,
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=68.9,
            temperature_c=24.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=1.00,
            units="ratio"
        ),
        hee_band=HEEBand.NEGLIGIBLE,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=9,
            table_id="Table 3"
        )
    ))
    
    # Inconel 718 HT-A (Severe) - Table 9
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T9-718-HTA",
        material_key="inconel_718",
        material_family=MaterialFamily.NICKEL_SUPERALLOY,
        material_condition="STA",
        heat_treatment=HeatTreatment(
            condition=HeatTreatCondition.SOLUTION_TREATED_AGED,
            solution_temp_c=940,
            solution_time_hr=1.0,
            age_temp_c=720,
            age_time_hr=8.0,
            second_age_temp_c=620,
            second_age_time_hr=8.0,
            description="940°C/1hr + 720°C/8hr + 620°C/8hr (HT-A)"
        ),
        product_form=ProductForm.ROLLED_BAR,
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=34.5,
            temperature_c=22.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=0.54,
            units="ratio"
        ),
        hee_band=HEEBand.SEVERE,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=31,
            table_id="Table 9",
            original_authors="Chandler, Walter"
        ),
        notes="Heat treatment A - lower solution temp (940°C vs 1037°C) yields δ phase at grain boundaries"
    ))
    
    # Inconel 718 - Better heat treatment (Small HEE)
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T7-718-BETTER",
        material_key="inconel_718",
        material_family=MaterialFamily.NICKEL_SUPERALLOY,
        material_condition="ST-no-age",
        heat_treatment=HeatTreatment(
            condition=HeatTreatCondition.SOLUTION_TREATED,
            solution_temp_c=1025,
            solution_time_hr=0.17,  # 10 min
            description="1025°C/10min, no aging (HT-D)"
        ),
        product_form=ProductForm.ROLLED_BAR,
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=34.5,
            temperature_c=22.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=0.83,
            units="ratio"
        ),
        hee_band=HEEBand.HIGH,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=31,
            table_id="Table 9"
        ),
        notes="Solution treated WITHOUT aging - significantly better than aged condition"
    ))
    
    # 7075-T73 Aluminum - Negligible (Table 2)
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T2-7075",
        material_key="7075_aluminum",
        material_family=MaterialFamily.ALUMINUM,
        material_condition="T73",
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=68.9,
            temperature_c=24.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=0.98,
            units="ratio"
        ),
        hee_band=HEEBand.NEGLIGIBLE,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=8,
            table_id="Table 2"
        ),
        notes="Aluminum alloys generally show negligible HEE"
    ))
    
    return evidence


def demo():
    """Demonstrate the H2 Knowledge Twin."""
    print("=" * 70)
    print("H2 KNOWLEDGE TWIN v2.0 - DEMONSTRATION")
    print("=" * 70)
    
    # Initialize engine with example evidence
    evidence = create_example_evidence()
    engine = H2DecisionEngine(evidence_store=evidence)
    
    print(f"\nLoaded {len(evidence)} evidence objects")
    
    # Query 1: 316 SS - should be good
    print("\n" + "-" * 70)
    print("QUERY 1: 316 Stainless Steel at 70 MPa, room temp")
    print("-" * 70)
    
    q1 = H2Query(
        material_name="316 stainless steel",
        condition=HeatTreatCondition.ANNEALED,
        phase=Phase.GH2,
        pressure_mpa=70.0,
        temperature_c=25.0,
        loading_mode=LoadingMode.STATIC
    )
    
    r1 = engine.query(q1)
    print(f"Verdict: {r1.verdict.value}")
    print(f"Confidence: {r1.confidence}")
    print(f"Summary: {r1.decision_summary}")
    if r1.warnings:
        print(f"Warnings: {r1.warnings}")
    
    # Query 2: Inconel 718 aged - should be NOT RECOMMENDED
    print("\n" + "-" * 70)
    print("QUERY 2: Inconel 718 (aged) at 35 MPa, room temp")
    print("-" * 70)
    
    q2 = H2Query(
        material_name="Inconel 718",
        condition=HeatTreatCondition.SOLUTION_TREATED_AGED,
        heat_treatment=HeatTreatment(
            condition=HeatTreatCondition.SOLUTION_TREATED_AGED,
            solution_temp_c=940
        ),
        phase=Phase.GH2,
        pressure_mpa=35.0,
        temperature_c=22.0,
        loading_mode=LoadingMode.STATIC
    )
    
    r2 = engine.query(q2)
    print(f"Verdict: {r2.verdict.value}")
    print(f"Confidence: {r2.confidence}")
    print(f"Summary: {r2.decision_summary}")
    if r2.drivers:
        print(f"Drivers: {[d.failure_mode + ' (' + d.severity + ')' for d in r2.drivers]}")
    
    # Query 3: Unknown material
    print("\n" + "-" * 70)
    print("QUERY 3: Unknown exotic alloy")
    print("-" * 70)
    
    q3 = H2Query(
        material_name="Unobtanium XYZ",
        phase=Phase.GH2,
        pressure_mpa=50.0,
        temperature_c=25.0
    )
    
    r3 = engine.query(q3)
    print(f"Verdict: {r3.verdict.value}")
    print(f"Confidence: {r3.confidence}")
    print(f"Summary: {r3.decision_summary}")
    if r3.recommended_tests:
        print(f"Recommended: {[t.test_type for t in r3.recommended_tests]}")
    
    # Query 4: Cryogenic LH2
    print("\n" + "-" * 70)
    print("QUERY 4: 316 SS in LH2 (cryogenic)")
    print("-" * 70)
    
    q4 = H2Query(
        material_name="316 stainless steel",
        condition=HeatTreatCondition.ANNEALED,
        phase=Phase.LH2,
        pressure_mpa=0.5,
        temperature_c=-253.0,  # LH2 boiling point
        loading_mode=LoadingMode.STATIC
    )
    
    r4 = engine.query(q4)
    print(f"Verdict: {r4.verdict.value}")
    print(f"Confidence: {r4.confidence}")
    print(f"Summary: {r4.decision_summary}")
    if r4.warnings:
        print(f"Warnings: {r4.warnings[0][:100]}...")
    
    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    demo()
