#!/usr/bin/env python3
"""
Module: Review Packet Generator
Purpose: Generate reviewer packets with test deltas and predicted questions

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Fran Fix #13: Reviewers waste time asking for delta info.
Pre-compute test deltas and predicted questions.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..models import (
    EnvironmentDefinition,
    MaterialEntry,
    NonconformanceSignal,
    PlanGeneratorSession,
)
from ..policy import PolicyPack, create_default_policy_pack

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


class TestDelta(BaseModel):
    """
    Delta between test conditions and use conditions.

    Fran Fix #13: Pre-compute these so reviewers don't have to ask.
    """

    material_id: str
    """Material identifier."""

    material_name: str
    """Material name."""

    environment_id: str
    """Environment identifier."""

    environment_name: str
    """Environment name."""

    parameter: str
    """Parameter being compared (e.g., 'o2_pct')."""

    test_value: Any
    """Value from test data."""

    use_value: Any
    """Value in use environment."""

    delta: Any
    """Difference (use - test)."""

    delta_pct: Optional[float] = None
    """Percentage difference if applicable."""

    within_envelope: bool = True
    """Whether use is within test envelope."""

    notes: str = ""
    """Additional notes for reviewer."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class PredictedQuestion(BaseModel):
    """
    Predicted reviewer question with pre-computed answer.

    Fran Fix #13: Anticipate what reviewers will ask.
    """

    question: str
    """The question a reviewer is likely to ask."""

    answer: str
    """Pre-computed answer with evidence."""

    triggered_by: str
    """What triggered this predicted question."""

    evidence_refs: list[str] = Field(default_factory=list)
    """Evidence references supporting the answer."""

    confidence: str = "medium"
    """Confidence level: low, medium, high."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class ReviewPacket(BaseModel):
    """
    Complete reviewer packet.

    Fran Fix #13: Everything a reviewer needs in one place.
    """

    session_id: str
    """Session identifier."""

    program_name: Optional[str] = None
    """Program name."""

    generated_at: datetime = Field(default_factory=datetime.now)
    """When packet was generated."""

    # Summary stats
    material_count: int = 0
    """Number of materials."""

    environment_count: int = 0
    """Number of environments."""

    nonconformance_count: int = 0
    """Number of nonconformances."""

    closed_count: int = 0
    """Number of closed gaps."""

    open_count: int = 0
    """Number of accepted open gaps."""

    # Test deltas
    test_deltas: list[TestDelta] = Field(default_factory=list)
    """All test-to-use deltas."""

    deltas_outside_envelope: list[TestDelta] = Field(default_factory=list)
    """Deltas where use exceeds test envelope."""

    # Predicted questions
    predicted_questions: list[PredictedQuestion] = Field(default_factory=list)
    """Anticipated reviewer questions."""

    # Key findings
    key_findings: list[str] = Field(default_factory=list)
    """Summary of key findings."""

    # Recommendations
    recommendations: list[str] = Field(default_factory=list)
    """Recommended actions."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class ReviewPacketGenerator:
    """
    Generate review packets.

    Fran Fix #13: Pre-compute everything reviewers need.
    """

    def __init__(
        self,
        session: PlanGeneratorSession,
        policy_pack: Optional[PolicyPack] = None,
    ):
        """
        Initialize generator.

        Args:
            session: Plan generator session.
            policy_pack: Optional policy pack.
        """
        self._session = session
        self._policy = policy_pack or create_default_policy_pack()

    def generate(self) -> ReviewPacket:
        """
        Generate review packet.

        Returns:
            Complete ReviewPacket.
        """
        packet = ReviewPacket(
            session_id=self._session.session_id,
            program_name=self._session.program_name,
            material_count=len(self._session.materials),
            environment_count=len(self._session.environments),
            nonconformance_count=len(self._session.nonconformances),
            closed_count=len(self._session.closure_decisions),
            open_count=len(self._session.accepted_open_gaps),
        )

        # Compute test deltas
        packet.test_deltas = self._compute_test_deltas()
        packet.deltas_outside_envelope = [
            d for d in packet.test_deltas if not d.within_envelope
        ]

        # Generate predicted questions
        packet.predicted_questions = self._generate_predicted_questions()

        # Compile key findings
        packet.key_findings = self._compile_key_findings()

        # Generate recommendations
        packet.recommendations = self._generate_recommendations()

        return packet

    def _compute_test_deltas(self) -> list[TestDelta]:
        """Compute test-to-use deltas for all materials."""
        deltas = []

        for material in self._session.materials:
            resolution = self._session.get_resolution(material.id)
            if not resolution:
                continue

            for env in self._session.environments:
                # O2 delta
                if resolution.test_o2_pct is not None:
                    o2_delta = env.o2_pct - resolution.test_o2_pct
                    within = o2_delta <= 0  # Use O2 <= Test O2 is OK

                    deltas.append(TestDelta(
                        material_id=material.id,
                        material_name=material.name,
                        environment_id=env.environment_id,
                        environment_name=env.name,
                        parameter="o2_pct",
                        test_value=resolution.test_o2_pct,
                        use_value=env.o2_pct,
                        delta=o2_delta,
                        delta_pct=(o2_delta / resolution.test_o2_pct * 100)
                            if resolution.test_o2_pct > 0 else None,
                        within_envelope=within,
                        notes="Use O2% exceeds test O2%" if not within else "",
                    ))

                # Pressure delta (if available)
                if resolution.test_pressure_psia is not None:
                    p_delta = env.pressure_psia - resolution.test_pressure_psia
                    within = abs(p_delta) <= 2.0  # Allow 2 psia tolerance

                    deltas.append(TestDelta(
                        material_id=material.id,
                        material_name=material.name,
                        environment_id=env.environment_id,
                        environment_name=env.name,
                        parameter="pressure_psia",
                        test_value=resolution.test_pressure_psia,
                        use_value=env.pressure_psia,
                        delta=p_delta,
                        delta_pct=(p_delta / resolution.test_pressure_psia * 100)
                            if resolution.test_pressure_psia > 0 else None,
                        within_envelope=within,
                        notes="Pressure delta exceeds 2 psia" if not within else "",
                    ))

        return deltas

    def _generate_predicted_questions(self) -> list[PredictedQuestion]:
        """Generate predicted reviewer questions."""
        questions = []

        # Check for use heuristics from policy
        for heuristic in self._policy.reviewer_heuristics:
            # Evaluate trigger condition
            if self._evaluate_trigger(heuristic.trigger_condition):
                questions.append(PredictedQuestion(
                    question=heuristic.predicted_question,
                    answer=f"Pre-computed: {heuristic.recommended_evidence}",
                    triggered_by=heuristic.trigger_condition,
                    confidence="high",
                ))

        # Standard questions based on session state

        # Delta questions
        deltas_outside = [d for d in self._compute_test_deltas() if not d.within_envelope]
        if deltas_outside:
            materials = list(set(d.material_name for d in deltas_outside))
            questions.append(PredictedQuestion(
                question="Why are test conditions different from use conditions?",
                answer=(
                    f"The following materials have use conditions outside test envelope: "
                    f"{', '.join(materials)}. See Test Deltas table for details."
                ),
                triggered_by="deltas_outside_envelope",
                confidence="high",
            ))

        # Nonconformance questions
        if self._session.nonconformances:
            nc_types = list(set(nc.gap_type.value for nc in self._session.nonconformances))
            questions.append(PredictedQuestion(
                question="How are the identified nonconformances being addressed?",
                answer=(
                    f"Identified {len(self._session.nonconformances)} nonconformance(s) "
                    f"of type(s): {', '.join(nc_types)}. "
                    f"Closures: {len(self._session.closure_decisions)}, "
                    f"Accepted open: {len(self._session.accepted_open_gaps)}."
                ),
                triggered_by="nonconformances_present",
                confidence="high",
            ))

        # Open gaps questions
        if self._session.accepted_open_gaps:
            questions.append(PredictedQuestion(
                question="What is the plan for closing accepted open gaps?",
                answer=(
                    f"{len(self._session.accepted_open_gaps)} gap(s) accepted as open. "
                    f"Each has assigned owner and due date. See Accepted Open Gaps table."
                ),
                triggered_by="open_gaps_present",
                confidence="medium",
            ))

        # Minor quantity questions
        if self._session.minor_quantity_aggregation:
            agg = self._session.minor_quantity_aggregation
            qualifying = [g for g in agg.groups if g.eligible]
            if qualifying:
                questions.append(PredictedQuestion(
                    question="How was minor quantity exception justified?",
                    answer=(
                        f"{len(qualifying)} material group(s) qualify for MPR 44(c) "
                        f"minor quantity exception based on aggregated mass and surface area. "
                        f"See Minor Quantity Analysis section for details."
                    ),
                    triggered_by="minor_quantity_used",
                    confidence="high",
                ))

        return questions

    def _evaluate_trigger(self, condition: str) -> bool:
        """Evaluate a trigger condition."""
        # Simple condition evaluation
        if condition == "high_o2":
            return any(env.o2_pct > 23.5 for env in self._session.environments)
        if condition == "habitable":
            return any(env.habitable for env in self._session.environments)
        if condition == "has_nonconformances":
            return len(self._session.nonconformances) > 0
        if condition == "has_open_gaps":
            return len(self._session.accepted_open_gaps) > 0
        return False

    def _compile_key_findings(self) -> list[str]:
        """Compile key findings."""
        findings = []

        # Environment summary
        env_names = [env.name for env in self._session.environments]
        findings.append(f"Environments: {', '.join(env_names) or 'None defined'}")

        # Material summary
        findings.append(f"Materials evaluated: {len(self._session.materials)}")

        # Compliance summary
        resolved = len(self._session.maptis_resolutions)
        total = len(self._session.materials)
        findings.append(f"Materials resolved in MAPTIS: {resolved}/{total}")

        # Nonconformance summary
        if self._session.nonconformances:
            nc_count = len(self._session.nonconformances)
            closed = len(self._session.closure_decisions)
            findings.append(f"Nonconformances: {nc_count} identified, {closed} closed")
        else:
            findings.append("No nonconformances identified")

        # Open gaps
        if self._session.accepted_open_gaps:
            findings.append(
                f"Accepted open gaps: {len(self._session.accepted_open_gaps)} "
                f"(tracked with owners and due dates)"
            )

        return findings

    def _generate_recommendations(self) -> list[str]:
        """Generate recommendations."""
        recommendations = []

        # Unresolved materials
        resolved_ids = {r.material_id for r in self._session.maptis_resolutions}
        unresolved = [
            m for m in self._session.materials
            if m.id not in resolved_ids and not m.maptis_code
        ]
        if unresolved:
            names = [m.name for m in unresolved]
            recommendations.append(
                f"Provide MAPTIS codes for: {', '.join(names)}"
            )

        # Open nonconformances
        closed_ids = {c.gap_id for c in self._session.closure_decisions}
        accepted_ids = {a.gap_id for a in self._session.accepted_open_gaps}
        open_ncs = [
            nc for nc in self._session.nonconformances
            if nc.nonconformance_id not in closed_ids
            and nc.nonconformance_id not in accepted_ids
        ]
        if open_ncs:
            recommendations.append(
                f"Address {len(open_ncs)} open nonconformance(s) before approval"
            )

        # Missing quantity data
        missing_qty = [
            m for m in self._session.materials
            if m.mass_g is None or m.surface_area_cm2 is None
        ]
        if missing_qty:
            names = [m.name for m in missing_qty]
            recommendations.append(
                f"Provide mass/surface area for: {', '.join(names)}"
            )

        if not recommendations:
            recommendations.append("Session appears complete for artifact generation")

        return recommendations

    def to_json(self) -> str:
        """Export packet as JSON."""
        packet = self.generate()
        return packet.model_dump_json(indent=2)


def generate_review_packet(
    session: PlanGeneratorSession,
    policy_pack: Optional[PolicyPack] = None,
) -> ReviewPacket:
    """
    Generate review packet.

    Args:
        session: Plan generator session.
        policy_pack: Optional policy pack.

    Returns:
        ReviewPacket with test deltas and predicted questions.
    """
    generator = ReviewPacketGenerator(session, policy_pack)
    return generator.generate()
