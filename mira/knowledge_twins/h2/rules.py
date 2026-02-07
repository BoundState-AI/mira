#!/usr/bin/env python3
"""
Module: Rules
Purpose: H2 Knowledge Twin - Rule Engine

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

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..types import (
    Constraint,
    Driver,
    HEEBand,
    HeatTreatCondition,
    Verdict,
    WeldState,
)
from .query import H2Query


@dataclass
class RuleGate:
    """A rule that can trigger verdict floors, constraints, or warnings."""
    rule_id: str
    name: str
    trigger_predicate: str
    effect_type: str  # "hard_block", "soft_warning", "add_constraint"
    verdict_floor: Optional[Verdict] = None
    confidence_penalty: float = 0.0
    constraint: Optional[Constraint] = None
    driver: Optional[Driver] = None


class RuleEngine:
    """Rule engine for fast conservative gates."""

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
        envelope_score: float,
        aged_evidence_found: bool = False,
        dominant_evidence_id: Optional[str] = None
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
                if query.condition == HeatTreatCondition.SOLUTION_TREATED_AGED and not aged_evidence_found:
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
                    drivers.append(Driver(
                        failure_mode=gate.driver.failure_mode,
                        severity=(evidence_band.value if evidence_band else gate.driver.severity),
                        trigger_parameter=gate.driver.trigger_parameter,
                        explanation=gate.driver.explanation,
                        evidence_ids=[dominant_evidence_id] if dominant_evidence_id else []
                    ))

                if gate.constraint:
                    constraints.append(gate.constraint)

        return (verdict_floor, total_penalty, drivers, constraints, triggers)
