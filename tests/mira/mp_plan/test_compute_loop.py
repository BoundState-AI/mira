#!/usr/bin/env python3
"""
Tests for M&P Plan Generator V2 compute loop.

BoundState AI 2026
"""

import pytest
from datetime import datetime

from mira.mp_plan.models import (
    PlanGeneratorSession,
    EnvironmentDefinition,
    MaterialEntry,
    BlockingQuestion,
    BlockingQuestionType,
)
from mira.mp_plan.compute_loop import (
    generate_blocking_questions,
    build_decision_graph,
    apply_user_decision,
    compute_question_id,
)
from mira.mp_plan.policy import create_default_policy_pack


class TestComputeQuestionId:
    """Tests for question ID generation."""

    def test_consistent_ids(self):
        """Test that same inputs produce same ID."""
        id1 = compute_question_id("MAT001", "resolution")
        id2 = compute_question_id("MAT001", "resolution")
        assert id1 == id2

    def test_different_ids(self):
        """Test that different inputs produce different IDs."""
        id1 = compute_question_id("MAT001", "resolution")
        id2 = compute_question_id("MAT002", "resolution")
        assert id1 != id2


class TestGenerateBlockingQuestions:
    """Tests for blocking question generation."""

    def test_environment_missing_question(self):
        """Test that missing environment generates question."""
        session = PlanGeneratorSession(
            session_id="test-001",
            source="test",
        )
        # No environments added

        questions = generate_blocking_questions(session)

        assert len(questions) == 1
        assert questions[0].question_type == BlockingQuestionType.ENVIRONMENT_MISSING
        assert "env_missing" == questions[0].question_id

    def test_no_questions_when_complete(self):
        """Test no questions when session is ready."""
        session = PlanGeneratorSession(
            session_id="test-002",
            source="test",
        )
        # Add environment
        session.environments.append(
            EnvironmentDefinition(
                name="ISS",
                o2_pct=23.0,
                pressure_psia=14.7,
                temp_range_c=(18.0, 27.0),
                habitable=True,
                source="test",
            )
        )
        # Add resolved material
        material = MaterialEntry(
            name="Kapton",
            application="Insulation",
            quantity=1,
            maptis_code="KAPTON-001",
            source="test",
        )
        session.materials.append(material)

        questions = generate_blocking_questions(session)

        # Should have no env question since env exists
        env_questions = [q for q in questions if q.question_type == BlockingQuestionType.ENVIRONMENT_MISSING]
        assert len(env_questions) == 0

    def test_material_resolution_question(self):
        """Test unresolved material generates question."""
        session = PlanGeneratorSession(
            session_id="test-003",
            source="test",
        )
        # Add environment first
        session.environments.append(
            EnvironmentDefinition(
                name="ISS",
                o2_pct=23.0,
                pressure_psia=14.7,
                temp_range_c=(18.0, 27.0),
                habitable=True,
                source="test",
            )
        )
        # Add material without MAPTIS code
        material = MaterialEntry(
            name="Unknown Material",
            application="Test",
            quantity=1,
            source="test",
        )
        session.materials.append(material)

        questions = generate_blocking_questions(session)

        # Should have a material ambiguous question
        mat_questions = [q for q in questions if q.question_type == BlockingQuestionType.MATERIAL_AMBIGUOUS]
        assert len(mat_questions) == 1
        assert "Unknown Material" in mat_questions[0].question_text


class TestBuildDecisionGraph:
    """Tests for decision graph building."""

    def test_empty_session_graph(self):
        """Test building graph from empty session."""
        session = PlanGeneratorSession(
            session_id="test-001",
            source="test",
        )

        graph = build_decision_graph(session)

        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_graph_includes_environments(self):
        """Test that environments are in graph."""
        session = PlanGeneratorSession(
            session_id="test-002",
            source="test",
        )
        env = EnvironmentDefinition(
            name="ISS",
            o2_pct=23.0,
            pressure_psia=14.7,
            temp_range_c=(18.0, 27.0),
            habitable=True,
            source="test",
        )
        session.environments.append(env)

        graph = build_decision_graph(session)

        assert f"environment:{env.environment_id}" in graph.nodes

    def test_graph_includes_materials(self):
        """Test that materials are in graph."""
        session = PlanGeneratorSession(
            session_id="test-003",
            source="test",
        )
        material = MaterialEntry(
            name="Kapton",
            application="Insulation",
            quantity=1,
            source="test",
        )
        session.materials.append(material)

        graph = build_decision_graph(session)

        assert f"material:{material.id}" in graph.nodes


class TestApplyUserDecision:
    """Tests for applying user decisions."""

    def test_apply_environment_selection(self):
        """Test applying environment selection answer."""
        session = PlanGeneratorSession(
            session_id="test-001",
            source="test",
        )

        question = BlockingQuestion(
            question_id="env_missing",
            question_type=BlockingQuestionType.ENVIRONMENT_MISSING,
            question_text="What vehicle?",
            context="Required",
            blocked_decisions=["all"],
            source="test",
        )

        apply_user_decision(session, question, "ISS", "Standard ISS cabin")

        assert len(session.environments) == 1
        assert session.environments[0].name == "ISS Habitable Volume"

    def test_apply_maptis_code(self):
        """Test applying MAPTIS code answer."""
        session = PlanGeneratorSession(
            session_id="test-002",
            source="test",
        )
        material = MaterialEntry(
            name="Test Material",
            application="Test",
            quantity=1,
            source="test",
        )
        session.materials.append(material)

        question_id = compute_question_id(material.id, "resolution")
        question = BlockingQuestion(
            question_id=question_id,
            question_type=BlockingQuestionType.MATERIAL_AMBIGUOUS,
            question_text="Provide MAPTIS code",
            context="Resolution needed",
            blocked_decisions=[f"resolution:{material.id}"],
            source="test",
        )

        apply_user_decision(session, question, "MAPTIS-12345", "Found in database")

        assert session.materials[0].maptis_code == "MAPTIS-12345"


class TestPolicyPack:
    """Tests for policy pack integration."""

    def test_default_policy_pack(self):
        """Test default policy pack loads."""
        policy = create_default_policy_pack()

        assert policy.policy_pack_id is not None
        assert len(policy.vehicle_environments) > 0

    def test_vehicle_presets(self):
        """Test vehicle environment presets."""
        policy = create_default_policy_pack()

        assert "ISS" in policy.vehicle_environments
        assert "HLS" in policy.vehicle_environments

        iss = policy.vehicle_environments["ISS"]
        assert iss["o2_pct"] == 30.0  # Per SSP 30233
        assert iss["habitable"] is True
