#!/usr/bin/env python3
"""
Module: Compute Loop
Purpose: Main compute-question-recompute loop for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Fran: "The workflow is a loop that alternates:
system computes everything it can -> produces blocking questions ->
user answers -> system recomputes"

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from .engines import (
    ApplicabilityEngine,
    ComplianceEvaluationEngine,
    DataAcquisitionEngine,
    MinorQuantityEngine,
)
from .models import (
    AcceptedOpenGap,
    BlockingQuestion,
    BlockingQuestionType,
    ClosureDecision,
    DecisionGraph,
    EnvironmentDefinition,
    PlanGeneratorSession,
    UserDecision,
)
from .policy import PolicyPack, create_default_policy_pack

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


def compute_question_id(obj_id: str, suffix: str) -> str:
    """Compute reproducible question ID."""
    hash_input = f"{obj_id}:{suffix}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:32]


def generate_blocking_questions(
    session: PlanGeneratorSession,
    policy_pack: Optional[PolicyPack] = None,
) -> list[BlockingQuestion]:
    """
    Generate blocking questions from gaps.

    Questions are generated from session state gaps,
    not from a scripted flow.

    Args:
        session: Plan generator session.
        policy_pack: Optional policy pack.

    Returns:
        List of blocking questions.
    """
    questions = []
    policy = policy_pack or create_default_policy_pack()

    # Priority 1: Environment missing
    if not session.environments:
        questions.append(
            BlockingQuestion(
                question_id="env_missing",
                question_type=BlockingQuestionType.ENVIRONMENT_MISSING,
                question_text="What vehicle/environment is the hardware flying in?",
                context="Required for all applicability and rating checks",
                blocked_decisions=["all_applicability", "all_rating_checks"],
                options=list(policy.vehicle_environments.keys()) + ["CUSTOM"],
                source="session_validation",
            )
        )
        return questions  # Can't proceed without environment

    # Priority 2: Unresolved materials (either no code, or code failed lookup)
    resolved_ids = {r.material_id for r in session.maptis_resolutions}
    for material in session.materials:
        if material.id not in resolved_ids:
            # Material needs resolution - either no code provided or code didn't resolve
            if material.maptis_code:
                # Code was provided but failed to resolve in MAPTIS
                question_text = f"MAPTIS code '{material.maptis_code}' not found for '{material.name}'. Provide correct code."
                context = f"Application: {material.application}. The code entered was not found in MAPTIS database."
            else:
                # No code provided
                question_text = f"Provide MAPTIS code or spec for '{material.name}'"
                context = f"Application: {material.application}"

            questions.append(
                BlockingQuestion(
                    question_id=compute_question_id(material.id, "resolution"),
                    question_type=BlockingQuestionType.MATERIAL_AMBIGUOUS,
                    question_text=question_text,
                    context=context,
                    blocked_decisions=[f"rating_check_{material.id}"],
                    source="material_resolution",
                )
            )

    # Priority 3: Missing quantity data
    for material in session.materials:
        if material.mass_g is None or material.surface_area_cm2 is None:
            has_flam_nc = any(
                n.material_id == material.id and n.gap_type.value == "flam"
                for n in session.nonconformances
            )
            if has_flam_nc:
                questions.append(
                    BlockingQuestion(
                        question_id=compute_question_id(material.id, "quantity"),
                        question_type=BlockingQuestionType.QUANTITY_MISSING,
                        question_text=f"Enter mass (g) and surface area (cm²) for '{material.name}'",
                        context="Format: mass_g, surface_area_cm2 (e.g., '10.5, 25.0'). Required for minor quantity exception check (MPR 44(c))",
                        blocked_decisions=[f"minor_qty_{material.id}"],
                        source="minor_quantity_check",
                    )
                )

    # Priority 4: Closure selection for open nonconformances
    closed_ids = {d.gap_id for d in session.closure_decisions}
    accepted_ids = {a.gap_id for a in session.accepted_open_gaps}

    for nc in session.nonconformances:
        nc_id = nc.nonconformance_id
        if nc_id not in closed_ids and nc_id not in accepted_ids:
            material = session.get_material(nc.material_id)
            material_name = material.name if material else nc.material_id
            env = session.get_environment(nc.environment_id)
            env_name = env.name if env else nc.environment_id

            questions.append(
                BlockingQuestion(
                    question_id=compute_question_id(nc_id, "closure"),
                    question_type=BlockingQuestionType.CLOSURE_SELECTION,
                    question_text=(
                        f"Select closure path for '{material_name}' "
                        f"({nc.gap_type.value.upper()}) in {env_name}"
                    ),
                    context=(
                        f"Failing: {nc.failing_requirement}, "
                        f"Value: {nc.failing_value}, "
                        f"Required: {nc.required_value}"
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
                    source_mpr=nc.affected_mprs[0] if nc.affected_mprs else None,
                    source="nonconformance_closure",
                )
            )

    return questions


def build_decision_graph(session: PlanGeneratorSession) -> DecisionGraph:
    """
    Build decision graph from session state.

    Args:
        session: Plan generator session.

    Returns:
        Decision graph with all nodes and edges.
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

    # Add resolution nodes
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

    # Add nonconformance nodes
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
        )
        for dep in depends:
            if dep in graph.nodes:
                graph.add_edge(from_node=dep, to_node=node_id, edge_type="depends_on")

    return graph


def apply_user_decision(
    session: PlanGeneratorSession,
    question: BlockingQuestion,
    answer: str,
    rationale: str,
    policy_pack: Optional[PolicyPack] = None,
) -> None:
    """
    Apply user decision to session state.

    Args:
        session: Plan generator session.
        question: Question being answered.
        answer: User's answer.
        rationale: User's rationale.
        policy_pack: Optional policy pack.
    """
    policy = policy_pack or create_default_policy_pack()

    if question.question_type == BlockingQuestionType.ENVIRONMENT_MISSING:
        # Add environment from preset
        if answer.upper() in policy.vehicle_environments:
            preset = policy.vehicle_environments[answer.upper()]
            env = EnvironmentDefinition(
                name=preset["name"],
                o2_pct=preset["o2_pct"],
                pressure_psia=preset["pressure_psia"],
                temp_range_c=tuple(preset["temp_range_c"]),
                habitable=preset["habitable"],
                vacuum_exposure=preset.get("vacuum_exposure", False),
                lunar_dust=preset.get("lunar_dust", False),
                phase=preset.get("phase", "nominal"),
                source=preset.get("source", "policy_pack"),
            )
            session.environments.append(env)
            LOGGER.info(f"Added environment: {env.name}")

    elif question.question_type == BlockingQuestionType.MATERIAL_AMBIGUOUS:
        # Update material with MAPTIS code
        for material in session.materials:
            if compute_question_id(material.id, "resolution") == question.question_id:
                material.maptis_code = answer
                LOGGER.info(f"Set MAPTIS code for {material.name}: {answer}")
                break

    elif question.question_type == BlockingQuestionType.QUANTITY_MISSING:
        # Parse "mass_g, surface_area_cm2" format
        for material in session.materials:
            if compute_question_id(material.id, "quantity") == question.question_id:
                try:
                    parts = answer.replace(" ", "").split(",")
                    if len(parts) >= 2:
                        material.mass_g = float(parts[0])
                        material.surface_area_cm2 = float(parts[1])
                        LOGGER.info(
                            f"Set quantity for {material.name}: "
                            f"mass={material.mass_g}g, area={material.surface_area_cm2}cm²"
                        )
                    else:
                        LOGGER.warning(
                            f"Invalid quantity format for {material.name}: {answer}. "
                            "Expected: mass_g, surface_area_cm2"
                        )
                except ValueError as e:
                    LOGGER.error(f"Failed to parse quantity for {material.name}: {e}")
                break

    elif question.question_type == BlockingQuestionType.CLOSURE_SELECTION:
        if answer.upper() == "ACCEPT_OPEN":
            from datetime import date, timedelta

            accepted = AcceptedOpenGap(
                gap_id=question.source_gap_id,
                gap_type="nonconformance",
                accepted_by="user",
                accepted_at=datetime.now(),
                acceptance_rationale=rationale,
                owner="TBD",
                due_date=date.today() + timedelta(days=30),
                risk_statement="Risk to be documented",
            )
            session.accepted_open_gaps.append(accepted)
            LOGGER.info(f"Accepted gap {question.source_gap_id} as open")
        else:
            closure = ClosureDecision(
                gap_id=question.source_gap_id,
                selected_path=answer.upper(),
                provided_inputs={},
                decision_rationale=rationale,
                decided_by="user",
                decided_at=datetime.now(),
                available_options=[{"path": opt} for opt in question.options],
                source="interactive",
            )
            session.closure_decisions.append(closure)
            LOGGER.info(f"Closure decision for {question.source_gap_id}: {answer}")


def run_compute_loop(
    session: PlanGeneratorSession,
    policy_pack: Optional[PolicyPack] = None,
    answer_callback: Optional[Callable[[BlockingQuestion], tuple[str, str]]] = None,
    max_iterations: int = 100,
) -> PlanGeneratorSession:
    """
    Run compute-question-recompute loop.

    Fran: "The workflow is a loop that alternates:
    system computes everything it can -> produces blocking questions ->
    user answers -> system recomputes"

    Args:
        session: Plan generator session.
        policy_pack: Optional policy pack.
        answer_callback: Callback for interactive answers (question) -> (answer, rationale).
        max_iterations: Safety limit on iterations.

    Returns:
        Updated session.
    """
    policy = policy_pack or create_default_policy_pack()

    # Initialize engines
    data_engine = DataAcquisitionEngine()
    applicability_engine = ApplicabilityEngine()
    compliance_engine = ComplianceEvaluationEngine()
    minor_qty_engine = MinorQuantityEngine()

    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        LOGGER.info(f"Compute loop iteration {iteration}")

        # Step 1: Build/update decision graph
        session.decision_graph = build_decision_graph(session)

        # Step 2: Run data acquisition (Engine A)
        if session.materials:
            resolutions, deficiencies, new_mappings = data_engine.run(session)
            session.deficiencies.extend(deficiencies)

        # Step 3: Run applicability (Engine B) if we have environments
        if session.environments and session.maptis_resolutions:
            session.applicability_matrix = applicability_engine.run(session)

        # Step 4: Run compliance evaluation (Engine C)
        if session.applicability_matrix:
            new_deficiencies, nonconformances, determinations = compliance_engine.run(
                session
            )
            # Merge new gaps (avoid duplicates)
            existing_nc_ids = {n.nonconformance_id for n in session.nonconformances}
            for nc in nonconformances:
                if nc.nonconformance_id not in existing_nc_ids:
                    session.nonconformances.append(nc)
            session.mpr_determinations = determinations

        # Step 5: Run minor quantity aggregation
        if session.nonconformances:
            session.minor_quantity_aggregation = minor_qty_engine.run(session)

        # Step 6: Generate blocking questions
        session.blocking_questions = generate_blocking_questions(session, policy)

        # Step 7: Check if ready
        can_generate, blockers = session.can_generate()
        if can_generate:
            LOGGER.info("Session ready for artifact generation")
            break

        # Step 8: Handle blocking questions
        if not session.blocking_questions and blockers:
            LOGGER.error(f"Cannot generate but no questions: {blockers}")
            break

        if session.blocking_questions:
            if answer_callback:
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
                    apply_user_decision(session, question, answer, rationale, policy)
            else:
                # No callback - return with questions
                LOGGER.info(
                    f"Returning with {len(session.blocking_questions)} blocking questions"
                )
                break

        session.updated_at = datetime.now()

    if iteration >= max_iterations:
        LOGGER.warning(f"Compute loop reached max iterations ({max_iterations})")

    # Cleanup
    data_engine.close()

    return session
