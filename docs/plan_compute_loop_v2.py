"""
M&P Plan Generator - Compute Loop V2.

Implements Fran's compute-question-recompute loop with:
- Dependency graph tracking
- Split deficiency/nonconformance handling
- Multi-environment evaluation

Compliance: SWE-013 (iterative computation), SWE-033 (audit trail).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .plan_session_v2 import (
    BlockingQuestion,
    BlockingQuestionType,
    DecisionGraph,
    DeficiencySignal,
    EnvironmentDefinition,
    MaterialEntry,
    NonconformanceSignal,
    PlanGeneratorSession,
    UserDecision,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AutoDerivation",
    "generate_blocking_questions",
    "apply_auto_derivations",
    "run_compute_loop",
    "VEHICLE_ENVIRONMENTS",
]

__safety_critical__ = False


# -----------------------------------------------------------------------------
# Vehicle Environment Presets (Tribal Knowledge - Should be PolicyPack)
# -----------------------------------------------------------------------------

VEHICLE_ENVIRONMENTS: dict[str, dict[str, Any]] = {
    "ISS": {
        "name": "ISS Habitable Volume",
        "o2_pct": 30.0,
        "pressure_psia": 14.7,
        "temp_range_c": (15.6, 26.7),
        "habitable": True,
        "vacuum_exposure": False,
        "lunar_dust": False,
        "source": "SSP 30233",
        "phase": "nominal",
    },
    "HLS": {
        "name": "HLS Lunar Lander",
        "o2_pct": 37.0,
        "pressure_psia": 8.2,
        "temp_range_c": (-50.0, 120.0),
        "habitable": True,
        "vacuum_exposure": True,
        "lunar_dust": True,
        "source": "HLS-RQMT-001",
        "phase": "nominal",
    },
    "ORION": {
        "name": "Orion Crew Module",
        "o2_pct": 34.0,
        "pressure_psia": 10.2,
        "temp_range_c": (18.3, 26.7),
        "habitable": True,
        "vacuum_exposure": False,
        "lunar_dust": False,
        "source": "Orion MPCV",
        "phase": "nominal",
    },
    "GATEWAY": {
        "name": "Gateway Habitation",
        "o2_pct": 34.0,
        "pressure_psia": 10.2,
        "temp_range_c": (18.3, 26.7),
        "habitable": True,
        "vacuum_exposure": False,
        "lunar_dust": False,
        "source": "Gateway ICD",
        "phase": "nominal",
    },
    "EVA_SUIT": {
        "name": "EVA Suit (EMU/xEMU)",
        "o2_pct": 100.0,
        "pressure_psia": 4.3,
        "temp_range_c": (-157.0, 121.0),
        "habitable": False,
        "vacuum_exposure": True,
        "lunar_dust": True,
        "source": "EMU/xEMU requirements",
        "phase": "nominal",
    },
}


# -----------------------------------------------------------------------------
# Auto-Derivation
# -----------------------------------------------------------------------------

class AutoDerivation(BaseModel):
    """Record of auto-derived value."""
    field: str
    derived_from: str
    value: Any
    rule: str
    derived_at: datetime = Field(default_factory=datetime.now)
    source: str = "auto_derivation"

    model_config = {"extra": "forbid", "populate_by_name": True}


def apply_auto_derivations(session: PlanGeneratorSession) -> list[AutoDerivation]:
    """
    Apply tribal knowledge rules to derive values.

    Returns list of derivations made (for audit trail).

    Compliance: SWE-013 (auto-derivation traceability).
    """
    derivations = []

    # Vehicle → Environment (if program name matches known vehicle)
    if session.program_name and not session.environments:
        vehicle = session.program_name.upper()
        if vehicle in VEHICLE_ENVIRONMENTS:
            preset = VEHICLE_ENVIRONMENTS[vehicle]
            env = EnvironmentDefinition(
                name=preset["name"],
                o2_pct=preset["o2_pct"],
                pressure_psia=preset["pressure_psia"],
                temp_range_c=preset["temp_range_c"],
                habitable=preset["habitable"],
                vacuum_exposure=preset["vacuum_exposure"],
                lunar_dust=preset["lunar_dust"],
                phase=preset["phase"],
                source=preset["source"],
            )
            session.environments.append(env)
            derivations.append(AutoDerivation(
                field="environments",
                derived_from="program_name",
                value=env.model_dump(),
                rule=f"VEHICLE_ENVIRONMENTS[{vehicle}]",
            ))
            logger.info(f"Auto-derived environment for {vehicle}: O2={env.o2_pct}%")

    # O2 concentration → Flammability applicability inference
    for env in session.environments:
        if env.o2_pct > 23.5:
            derivations.append(AutoDerivation(
                field=f"flammability_applicable_{env.environment_id}",
                derived_from=f"environment.{env.environment_id}.o2_pct",
                value=True,
                rule=f"O2 {env.o2_pct}% > 23.5% threshold (MPR 44)",
            ))

    return derivations


# -----------------------------------------------------------------------------
# Blocking Question Generation
# -----------------------------------------------------------------------------

def compute_question_id(obj_id: str, suffix: str) -> str:
    """Compute reproducible question ID."""
    hash_input = f"{obj_id}:{suffix}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:32]


def generate_blocking_questions(session: PlanGeneratorSession) -> list[BlockingQuestion]:
    """
    Generate blocking questions from gaps, not a scripted flow.

    Questions are generated from:
    - Missing environments (deficiency)
    - Unresolved materials (deficiency)
    - Missing quantity data (deficiency)
    - Open nonconformances needing closure (nonconformance)
    - Grouping assumptions needing confirmation

    Compliance: SWE-013 (gap-driven questions).
    """
    questions = []

    # Priority 1: Environment missing
    if not session.environments:
        questions.append(BlockingQuestion(
            question_id="env_missing",
            question_type=BlockingQuestionType.ENVIRONMENT_MISSING,
            question_text="What vehicle/environment is the hardware flying in?",
            context="Required for all applicability and rating checks",
            blocked_decisions=["all_applicability", "all_rating_checks"],
            options=list(VEHICLE_ENVIRONMENTS.keys()) + ["CUSTOM"],
            source="session_validation",
        ))
        # Return early - can't proceed without environment
        return questions

    # Priority 2: Unresolved materials
    resolved_ids = {r.material_id for r in session.maptis_resolutions}
    for material in session.materials:
        if material.id not in resolved_ids and material.maptis_code is None:
            questions.append(BlockingQuestion(
                question_id=compute_question_id(material.id, "resolution"),
                question_type=BlockingQuestionType.MATERIAL_AMBIGUOUS,
                question_text=f"Provide MAPTIS code or spec for '{material.name}'",
                context=f"Application: {material.application}",
                blocked_decisions=[f"rating_check_{material.id}"],
                source="material_resolution",
            ))

    # Priority 3: Missing quantity data for potential minor quantity materials
    for material in session.materials:
        if material.mass_g is None or material.surface_area_cm2 is None:
            # Check if this material has any nonconformance that might use minor qty
            has_flam_nonconformance = any(
                n.material_id == material.id and n.gap_type.value == "flam"
                for n in session.nonconformances
            )
            if has_flam_nonconformance:
                questions.append(BlockingQuestion(
                    question_id=compute_question_id(material.id, "quantity"),
                    question_type=BlockingQuestionType.QUANTITY_MISSING,
                    question_text=(
                        f"Enter mass (g) and surface area (cm²) for '{material.name}'"
                    ),
                    context="Required for minor quantity exception check (MPR 44(c))",
                    blocked_decisions=[f"minor_qty_{material.id}"],
                    source="minor_quantity_check",
                ))

    # Priority 4: Closure selection for open nonconformances
    closed_ids = {d.gap_id for d in session.closure_decisions}
    accepted_ids = {a.gap_id for a in session.accepted_open_gaps}

    for nonconformance in session.nonconformances:
        nc_id = nonconformance.nonconformance_id
        if nc_id not in closed_ids and nc_id not in accepted_ids:
            # Get material name for display
            material = session.get_material(nonconformance.material_id)
            material_name = material.name if material else nonconformance.material_id

            # Get environment for context
            env = session.get_environment(nonconformance.environment_id)
            env_name = env.name if env else nonconformance.environment_id

            questions.append(BlockingQuestion(
                question_id=compute_question_id(nc_id, "closure"),
                question_type=BlockingQuestionType.CLOSURE_SELECTION,
                question_text=(
                    f"Select closure path for '{material_name}' "
                    f"({nonconformance.gap_type.value.upper()}) in {env_name}"
                ),
                context=(
                    f"Failing: {nonconformance.failing_requirement}, "
                    f"Value: {nonconformance.failing_value}, "
                    f"Required: {nonconformance.required_value}"
                ),
                options=[
                    "MINOR_QUANTITY",
                    "CONFIGURATION_ANALYSIS",
                    "HEAT_SINK",
                    "SUBSTITUTION",
                    "FULL_MUA",
                    "ACCEPT_OPEN",
                ],
                blocked_decisions=[f"closure_{nc_id}"],
                source_gap_id=nc_id,
                source_mpr=nonconformance.affected_mprs[0] if nonconformance.affected_mprs else None,
                source="nonconformance_closure",
            ))

    return questions


# -----------------------------------------------------------------------------
# Compute Loop
# -----------------------------------------------------------------------------

def build_decision_graph(session: PlanGeneratorSession) -> DecisionGraph:
    """
    Build decision graph from session state.

    This tracks dependencies between materials, environments, and decisions.

    Compliance: SWE-013 (dependency tracking).
    """
    graph = DecisionGraph()

    # Add environment nodes
    for env in session.environments:
        graph.add_node(
            node_type="environment",
            object_id=env.environment_id,
            object_type="EnvironmentDefinition",
            derived_from_fields=[
                f"environment.{env.environment_id}.o2_pct",
                f"environment.{env.environment_id}.pressure_psia",
            ],
        )

    # Add material nodes
    for material in session.materials:
        graph.add_node(
            node_type="material",
            object_id=material.id,
            object_type="MaterialEntry",
            derived_from_fields=[
                f"material.{material.id}.mass_g",
                f"material.{material.id}.surface_area_cm2",
                f"material.{material.id}.maptis_code",
            ],
        )

    # Add resolution nodes depending on materials
    for resolution in session.maptis_resolutions:
        node_id = graph.add_node(
            node_type="resolution",
            object_id=resolution.material_id,
            object_type="MaterialResolutionResult",
            depends_on=[f"material:{resolution.material_id}"],
            derived_from_fields=[
                f"resolution.{resolution.material_id}.flam_rating",
                f"resolution.{resolution.material_id}.test_o2_pct",
            ],
        )
        graph.add_edge(
            from_node=f"material:{resolution.material_id}",
            to_node=node_id,
            edge_type="depends_on",
        )

    # Add nonconformance nodes depending on resolution + environment
    for nc in session.nonconformances:
        depends = [
            f"resolution:{nc.material_id}",
            f"environment:{nc.environment_id}",
        ]
        node_id = graph.add_node(
            node_type="nonconformance",
            object_id=nc.nonconformance_id,
            object_type="NonconformanceSignal",
            depends_on=depends,
            derived_from_fields=[
                f"resolution.{nc.material_id}.flam_rating",
                f"environment.{nc.environment_id}.o2_pct",
            ],
        )
        for dep in depends:
            if dep in graph.nodes:
                graph.add_edge(from_node=dep, to_node=node_id, edge_type="depends_on")

    return graph


def run_compute_loop(
    session: PlanGeneratorSession,
    answer_callback: Optional[callable] = None,
) -> PlanGeneratorSession:
    """
    Run compute-question-recompute loop.

    Fran: "The workflow is a loop that alternates:
    system computes everything it can → produces blocking questions →
    user answers → system recomputes"

    Args:
        session: Current session state.
        answer_callback: Optional callback for interactive answers.
            If None, uses CLI input.

    Returns:
        Updated session.

    Compliance: SWE-013 (iterative computation).
    """
    iteration = 0
    max_iterations = 100  # Safety limit

    while iteration < max_iterations:
        iteration += 1
        logger.info(f"Compute loop iteration {iteration}")

        # Step 1: Apply auto-derivations
        derivations = apply_auto_derivations(session)
        if derivations:
            logger.info(f"Applied {len(derivations)} auto-derivations")
            session.updated_at = datetime.now()

        # Step 2: Build/update decision graph
        session.decision_graph = build_decision_graph(session)

        # Step 3: Generate blocking questions
        session.blocking_questions = generate_blocking_questions(session)

        # Step 4: Check if ready to generate
        can_generate, blockers = session.can_generate()
        if can_generate:
            logger.info("Session ready for artifact generation")
            break

        # Step 5: If no blocking questions but still blockers, something's wrong
        if not session.blocking_questions and blockers:
            logger.error(f"Cannot generate but no questions: {blockers}")
            break

        # Step 6: Present questions and get answers
        if session.blocking_questions:
            if answer_callback:
                # Use provided callback for answers
                for question in session.blocking_questions:
                    answer, rationale = answer_callback(question)
                    decision = UserDecision(
                        question_id=question.question_id,
                        decision=answer,
                        rationale=rationale,
                        decided_by="user",
                        source="interactive",
                    )
                    session.user_decisions.append(decision)
                    _apply_decision(session, question, answer)
            else:
                # CLI fallback
                print("\n" + "=" * 60)
                print("BLOCKING QUESTIONS")
                print("=" * 60)
                for question in session.blocking_questions:
                    print(f"\n[{question.question_type.value}]")
                    print(f"Q: {question.question_text}")
                    print(f"   Context: {question.context}")
                    if question.options:
                        print(f"   Options: {', '.join(question.options)}")
                    answer = input("A: ").strip()
                    rationale = input("   Rationale: ").strip()

                    decision = UserDecision(
                        question_id=question.question_id,
                        decision=answer,
                        rationale=rationale,
                        decided_by="cli_user",
                        source="cli",
                    )
                    session.user_decisions.append(decision)
                    _apply_decision(session, question, answer)

        session.updated_at = datetime.now()

    if iteration >= max_iterations:
        logger.warning(f"Compute loop reached max iterations ({max_iterations})")

    return session


def _apply_decision(
    session: PlanGeneratorSession,
    question: BlockingQuestion,
    answer: str,
) -> None:
    """
    Apply user decision to session state.

    This is where answers update the session data.
    """
    if question.question_type == BlockingQuestionType.ENVIRONMENT_MISSING:
        # Add environment from preset or prompt for custom
        if answer.upper() in VEHICLE_ENVIRONMENTS:
            preset = VEHICLE_ENVIRONMENTS[answer.upper()]
            env = EnvironmentDefinition(
                name=preset["name"],
                o2_pct=preset["o2_pct"],
                pressure_psia=preset["pressure_psia"],
                temp_range_c=preset["temp_range_c"],
                habitable=preset["habitable"],
                vacuum_exposure=preset["vacuum_exposure"],
                lunar_dust=preset["lunar_dust"],
                phase=preset["phase"],
                source=preset["source"],
            )
            session.environments.append(env)
            logger.info(f"Added environment: {env.name}")

    elif question.question_type == BlockingQuestionType.MATERIAL_AMBIGUOUS:
        # Update material with MAPTIS code
        # Extract material_id from question_id (hash-based, need to track)
        for material in session.materials:
            if compute_question_id(material.id, "resolution") == question.question_id:
                material.maptis_code = answer
                logger.info(f"Set MAPTIS code for {material.name}: {answer}")
                break

    elif question.question_type == BlockingQuestionType.CLOSURE_SELECTION:
        # Record closure decision
        if answer.upper() == "ACCEPT_OPEN":
            # Create accepted open gap
            from datetime import date, timedelta
            accepted = AcceptedOpenGap(
                gap_id=question.source_gap_id,
                gap_type="nonconformance",
                accepted_by="user",
                accepted_at=datetime.now(),
                acceptance_rationale="User accepted as open",
                owner="TBD",
                due_date=date.today() + timedelta(days=30),
                risk_statement="Risk to be documented",
            )
            session.accepted_open_gaps.append(accepted)
            logger.info(f"Accepted gap {question.source_gap_id} as open")
        else:
            # Create closure decision
            closure = ClosureDecision(
                gap_id=question.source_gap_id,
                selected_path=answer.upper(),
                provided_inputs={},
                decision_rationale="User selected",
                decided_by="user",
                decided_at=datetime.now(),
                available_options=[{"path": opt} for opt in question.options],
                source="interactive",
            )
            session.closure_decisions.append(closure)
            logger.info(f"Closure decision for {question.source_gap_id}: {answer}")


# Import needed for _apply_decision
from .plan_session_v2 import AcceptedOpenGap, ClosureDecision
