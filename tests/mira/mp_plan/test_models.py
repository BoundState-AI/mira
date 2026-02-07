#!/usr/bin/env python3
"""
Tests for M&P Plan Generator V2 models.

BoundState AI 2026
"""

import pytest
from datetime import datetime

from mira.mp_plan.models import (
    PlanGeneratorSession,
    EnvironmentDefinition,
    MaterialEntry,
    MaterialEnvironmentUsage,
    DeficiencySignal,
    NonconformanceSignal,
    DecisionGraph,
    DraftTextBox,
    BlockingQuestion,
    BlockingQuestionType,
    ClosureDecision,
    AcceptedOpenGap,
)


class TestEnvironmentDefinition:
    """Tests for EnvironmentDefinition model."""

    def test_create_environment(self):
        """Test creating a basic environment."""
        env = EnvironmentDefinition(
            name="ISS Cabin",
            o2_pct=23.0,
            pressure_psia=14.7,
            temp_range_c=(18.0, 27.0),
            habitable=True,
            source="test",
        )
        assert env.name == "ISS Cabin"
        assert env.o2_pct == 23.0
        assert env.habitable is True
        assert env.environment_id is not None

    def test_environment_with_vacuum(self):
        """Test creating environment with vacuum exposure."""
        env = EnvironmentDefinition(
            name="EVA",
            o2_pct=100.0,
            pressure_psia=4.3,
            temp_range_c=(-157.0, 121.0),
            habitable=False,
            vacuum_exposure=True,
            source="test",
        )
        assert env.vacuum_exposure is True
        assert env.o2_pct == 100.0


class TestMaterialEntry:
    """Tests for MaterialEntry model."""

    def test_create_material(self):
        """Test creating a basic material."""
        material = MaterialEntry(
            name="Kapton",
            application="Insulation",
            quantity=1,
            source="test",
        )
        assert material.name == "Kapton"
        assert material.application == "Insulation"
        assert material.id is not None

    def test_material_with_maptis(self):
        """Test material with MAPTIS code."""
        material = MaterialEntry(
            name="Viton A",
            application="O-Ring",
            quantity=5,
            maptis_code="VITON-A-001",
            mass_g=5.2,
            surface_area_cm2=12.5,
            source="test",
        )
        assert material.maptis_code == "VITON-A-001"
        assert material.mass_g == 5.2
        assert material.surface_area_cm2 == 12.5


class TestPlanGeneratorSession:
    """Tests for PlanGeneratorSession model."""

    def test_create_empty_session(self):
        """Test creating an empty session."""
        session = PlanGeneratorSession(
            session_id="test-001",
            source="test",
        )
        assert session.session_id == "test-001"
        assert len(session.materials) == 0
        assert len(session.environments) == 0

    def test_session_can_generate_requires_environment(self):
        """Test that can_generate requires at least one environment."""
        session = PlanGeneratorSession(
            session_id="test-002",
            source="test",
        )
        can_generate, blockers = session.can_generate()
        assert can_generate is False
        assert "No environments defined" in blockers

    def test_session_can_generate_requires_materials(self):
        """Test that can_generate requires at least one material."""
        session = PlanGeneratorSession(
            session_id="test-003",
            source="test",
        )
        session.environments.append(
            EnvironmentDefinition(
                name="Test Env",
                o2_pct=21.0,
                pressure_psia=14.7,
                temp_range_c=(20.0, 25.0),
                habitable=True,
                source="test",
            )
        )
        can_generate, blockers = session.can_generate()
        assert can_generate is False
        assert "No materials entered" in blockers

    def test_session_get_material(self):
        """Test getting material by ID."""
        session = PlanGeneratorSession(
            session_id="test-004",
            source="test",
        )
        material = MaterialEntry(name="Test Mat", application="Test", quantity=1, source="test")
        session.materials.append(material)

        found = session.get_material(material.id)
        assert found is not None
        assert found.name == "Test Mat"

        not_found = session.get_material("nonexistent")
        assert not_found is None


class TestDecisionGraph:
    """Tests for DecisionGraph model."""

    def test_create_empty_graph(self):
        """Test creating empty graph."""
        graph = DecisionGraph()
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_add_node(self):
        """Test adding nodes to graph."""
        graph = DecisionGraph()
        node_id = graph.add_node(
            node_type="material",
            object_id="MAT001",
            object_type="MaterialEntry",
        )
        assert node_id is not None
        assert "material:MAT001" in graph.nodes

    def test_add_edge(self):
        """Test adding edges to graph."""
        graph = DecisionGraph()
        graph.add_node(
            node_type="material",
            object_id="MAT001",
            object_type="MaterialEntry",
        )
        graph.add_node(
            node_type="resolution",
            object_id="MAT001",
            object_type="MaterialResolutionResult",
            depends_on=["material:MAT001"],
        )
        graph.add_edge(
            from_node="material:MAT001",
            to_node="resolution:MAT001",
            edge_type="depends_on",
        )
        assert len(graph.edges) == 1

    def test_get_invalidated_by(self):
        """Test finding invalidated nodes when a field changes."""
        graph = DecisionGraph()
        graph.add_node(
            node_type="material",
            object_id="MAT001",
            object_type="MaterialEntry",
            derived_from_fields=["material.MAT001.mass_g"],
        )
        graph.add_node(
            node_type="minor_qty",
            object_id="MAT001",
            object_type="MinorQuantityCheck",
            depends_on=["material:MAT001"],
            derived_from_fields=["material.MAT001.mass_g"],
        )
        graph.add_edge(
            from_node="material:MAT001",
            to_node="minor_qty:MAT001",
            edge_type="depends_on",
        )

        invalidated = graph.get_invalidated_by("material.MAT001.mass_g")
        assert "minor_qty:MAT001" in invalidated


class TestDraftTextBox:
    """Tests for DraftTextBox model - Fran Fix #11."""

    def test_draft_is_never_authoritative(self):
        """Test that DraftTextBox enforces non-authoritative status."""
        draft = DraftTextBox(
            draft_type="mua_rationale",
            content="Some LLM-generated text",
            prompt_template_id="test-template",
            prompt_hash="abc123",
            model_id="claude-sonnet-4",
            inputs_hash="def456",
        )
        assert draft.is_authoritative is False
        assert draft.requires_human_review is True

    def test_draft_rejects_authoritative(self):
        """Test that setting authoritative=True raises error."""
        with pytest.raises(ValueError, match="can never be authoritative"):
            DraftTextBox(
                draft_type="mua_rationale",
                content="Test",
                prompt_template_id="test-template",
                prompt_hash="abc123",
                model_id="claude-sonnet-4",
                inputs_hash="def456",
                is_authoritative=True,
            )

    def test_draft_rejects_no_review(self):
        """Test that setting requires_human_review=False raises error."""
        with pytest.raises(ValueError, match="requires human review"):
            DraftTextBox(
                draft_type="mua_rationale",
                content="Test",
                prompt_template_id="test-template",
                prompt_hash="abc123",
                model_id="claude-sonnet-4",
                inputs_hash="def456",
                requires_human_review=False,
            )


class TestBlockingQuestion:
    """Tests for BlockingQuestion model."""

    def test_create_blocking_question(self):
        """Test creating a blocking question."""
        question = BlockingQuestion(
            question_id="q-001",
            question_type=BlockingQuestionType.ENVIRONMENT_MISSING,
            question_text="What vehicle is this for?",
            context="Required for applicability",
            blocked_decisions=["all_applicability"],
            source="test",
        )
        assert question.question_id == "q-001"
        assert question.question_type == BlockingQuestionType.ENVIRONMENT_MISSING

    def test_question_with_options(self):
        """Test question with predefined options."""
        question = BlockingQuestion(
            question_id="q-002",
            question_type=BlockingQuestionType.CLOSURE_SELECTION,
            question_text="How to close this gap?",
            context="Flammability nonconformance",
            blocked_decisions=["closure_NC001"],
            options=["MINOR_QUANTITY", "FULL_MUA", "ACCEPT_OPEN"],
            source="test",
        )
        assert len(question.options) == 3
        assert "MINOR_QUANTITY" in question.options


class TestClosureDecision:
    """Tests for ClosureDecision model."""

    def test_create_closure_decision(self):
        """Test creating a closure decision."""
        closure = ClosureDecision(
            gap_id="NC001",
            selected_path="MINOR_QUANTITY",
            provided_inputs={"mass_g": 0.5},
            decision_rationale="Mass below threshold",
            decided_by="engineer",
            decided_at=datetime.now(),
            available_options=[],
            source="test",
        )
        assert closure.gap_id == "NC001"
        assert closure.selected_path == "MINOR_QUANTITY"


class TestAcceptedOpenGap:
    """Tests for AcceptedOpenGap model - Fran Fix #8."""

    def test_create_accepted_gap(self):
        """Test creating an accepted open gap."""
        from datetime import date, timedelta

        gap = AcceptedOpenGap(
            gap_id="NC002",
            gap_type="nonconformance",
            accepted_by="pm",
            accepted_at=datetime.now(),
            acceptance_rationale="Will be addressed in Phase 2",
            owner="John Doe",
            due_date=date.today() + timedelta(days=30),
            risk_statement="Low risk due to limited exposure",
        )
        assert gap.gap_id == "NC002"
        assert gap.owner == "John Doe"
        assert gap.risk_statement is not None


class TestDeficiencySignal:
    """Tests for DeficiencySignal - Fran Fix #7."""

    def test_create_deficiency(self):
        """Test creating a deficiency signal."""
        deficiency = DeficiencySignal(
            deficiency_type="missing_maptis_code",
            missing_field="maptis_code",
            missing_for="resolution of Kapton",
            material_id="MAT001",
            blocked_decision_ids=["resolution:MAT001"],
            source="test",
        )
        assert deficiency.deficiency_type == "missing_maptis_code"
        assert deficiency.material_id == "MAT001"


class TestNonconformanceSignal:
    """Tests for NonconformanceSignal - Fran Fix #7."""

    def test_create_nonconformance(self):
        """Test creating a nonconformance signal."""
        from mira.compliance.models.enums import FailureMode, GapSeverity

        nc = NonconformanceSignal(
            gap_type=FailureMode.FLAM,
            material_id="MAT001",
            environment_id="ENV001",
            failing_requirement="MPR 44(a)",
            failing_value="B-Rated",
            required_value="A-Rated",
            affected_mprs=["MPR_44"],
            severity=GapSeverity.HIGH,
            confidence=0.95,
            source_adapter="test_adapter",
        )
        assert nc.gap_type == FailureMode.FLAM
        assert nc.failing_requirement == "MPR 44(a)"
        assert "MPR_44" in nc.affected_mprs
