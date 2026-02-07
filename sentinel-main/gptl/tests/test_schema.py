# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
GPTL Schema Tests
=================

Tests for Pydantic models in gptl.schema.
Updated to match actual GPTL v4.1 schema.
"""

from datetime import datetime

import pytest

from gptl.schema import (
    BaseCondition,
    ConstraintAction,
    ConstraintCondition,
    ConstraintRule,
    ConstraintViolation,
    DateSource,
    DocFeatures,
    DocFlags,
    DocType,
    EntitySet,
    EvidenceCitation,
    EvidenceRequirements,
    EvidenceType,
    GPTLMetrics,
    GPTLRequest,
    IntelligenceOutput,
    IntentCategory,
    IntentClassificationResult,
    IntentFrame,
    ModelCall,
    ModelTier,
    ViolationReport,
)


class TestEntitySet:
    """Tests for EntitySet model."""

    def test_empty_entity_set(self):
        """Test creating an empty entity set."""
        entities = EntitySet(
            materials=[],
            standards=[],
            hazards=[],
            systems=[],
            processes=[],
        )
        assert entities.materials == []
        assert entities.standards == []

    def test_entity_set_with_values(self):
        """Test entity set with populated values."""
        entities = EntitySet(
            materials=["Inconel 718", "Ti-6Al-4V"],
            standards=["NASA-STD-6016", "MIL-STD-1540"],
            hazards=["hydrogen embrittlement"],
            systems=["propulsion"],
            processes=["welding"],
        )
        assert "Inconel 718" in entities.materials
        assert "NASA-STD-6016" in entities.standards

    def test_entity_set_forbids_extra_fields(self):
        """Test that extra fields are rejected."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            EntitySet(
                materials=[],
                standards=[],
                hazards=[],
                systems=[],
                processes=[],
                unknown_field=["bad"],
            )


class TestDocFlags:
    """Tests for DocFlags model."""

    def test_default_flags(self):
        """Test default flag values."""
        flags = DocFlags()
        assert flags.has_measurements is False
        assert flags.has_tables is False
        assert flags.has_test_conditions is False
        assert flags.has_spec_references is False
        assert flags.has_figures is False
        assert flags.has_equations is False
        assert flags.is_noise_candidate is False

    def test_measurement_flag(self):
        """Test has_measurements flag."""
        flags = DocFlags(has_measurements=True)
        assert flags.has_measurements is True

    def test_noise_candidate_flag(self):
        """Test is_noise_candidate flag."""
        flags = DocFlags(is_noise_candidate=True)
        assert flags.is_noise_candidate is True


class TestDocFeatures:
    """Tests for DocFeatures model."""

    def test_minimal_doc_features(self):
        """Test creating DocFeatures with minimal required fields."""
        features = DocFeatures(
            doc_id="DOC-001",
            doc_hash="abc123def456",
        )
        assert features.doc_id == "DOC-001"
        assert features.doc_hash == "abc123def456"
        assert features.doc_type == DocType.UNKNOWN
        assert features.derived_evidence_types == []

    def test_doc_features_with_all_fields(self, sample_doc_features):
        """Test DocFeatures with all fields populated."""
        assert sample_doc_features.doc_id == "DOC-001"
        assert sample_doc_features.doc_type == DocType.SPECIFICATION
        assert sample_doc_features.flags.has_measurements is True
        assert sample_doc_features.date_value is not None

    def test_doc_features_evidence_types(self):
        """Test multiple evidence types."""
        features = DocFeatures(
            doc_id="DOC-002",
            doc_hash="def456abc789",
            derived_evidence_types=[EvidenceType.SPECIFICATION, EvidenceType.TEST_REPORT],
        )
        assert len(features.derived_evidence_types) == 2

    def test_domain_scores_validation(self):
        """Test domain scores must be 0-1."""
        features = DocFeatures(
            doc_id="DOC-003",
            doc_hash="ghi789jkl012",
            domain_scores={"materials": 0.8, "safety": 0.9},
        )
        assert features.domain_scores["materials"] == 0.8

        with pytest.raises(Exception):  # ValidationError
            DocFeatures(
                doc_id="DOC-004",
                doc_hash="invalid",
                domain_scores={"materials": 1.5},  # Invalid: > 1.0
            )


class TestConstraints:
    """Tests for constraint-related models."""

    def test_constraint_condition(self):
        """Test ConstraintCondition creation."""
        condition = ConstraintCondition(
            field="flags.is_noise_candidate",
            operator="eq",
            value=True,
        )
        assert condition.field == "flags.is_noise_candidate"
        assert condition.operator == "eq"
        assert condition.value is True
        assert condition.negate is False

    def test_constraint_condition_with_negate(self):
        """Test ConstraintCondition with negation."""
        condition = ConstraintCondition(
            field="doc_type",
            operator="eq",
            value="specification",
            negate=True,
        )
        assert condition.negate is True

    def test_constraint_rule(self):
        """Test ConstraintRule creation."""
        rule = ConstraintRule(
            rule_id="no_noise",
            name="no_noise",
            description="Exclude noise documents",
            action=ConstraintAction.HARD_DROP,
            conditions=[
                ConstraintCondition(
                    field="flags.is_noise_candidate",
                    operator="eq",
                    value=True,
                ),
            ],
        )
        assert rule.rule_id == "no_noise"
        assert rule.action == ConstraintAction.HARD_DROP
        assert len(rule.conditions) == 1

    def test_constraint_violation(self):
        """Test ConstraintViolation creation."""
        violation = ConstraintViolation(
            doc_id="DOC-001",
            rule_id="no_noise",
            rule_name="no_noise",
            action=ConstraintAction.HARD_DROP,
            reason="Document is noise candidate",
        )
        assert violation.rule_name == "no_noise"
        assert violation.doc_id == "DOC-001"
        assert violation.action == ConstraintAction.HARD_DROP

    def test_violation_report(self):
        """Test ViolationReport creation."""
        report = ViolationReport(
            total_candidates=10,
            candidates_eliminated=3,
            candidates_deprioritized=2,
            survivors=5,
            violations=[
                ConstraintViolation(
                    doc_id="DOC-001",
                    rule_id="no_noise",
                    rule_name="no_noise",
                    action=ConstraintAction.HARD_DROP,
                    reason="Noise candidate",
                ),
            ],
            rules_triggered=["no_noise"],
        )
        assert report.total_candidates == 10
        assert report.survivors == 5
        # Reduction ratio should be computed automatically
        assert report.reduction_ratio == 0.3  # 3/10


class TestIntentModels:
    """Tests for intent-related models."""

    def test_evidence_requirements(self):
        """Test EvidenceRequirements creation."""
        reqs = EvidenceRequirements(
            types=[EvidenceType.SPECIFICATION],
            min_count=2,
            required_entity_classes=["materials"],
        )
        assert reqs.min_count == 2
        assert EvidenceType.SPECIFICATION in reqs.types

    def test_intent_frame(self):
        """Test IntentFrame creation."""
        frame = IntentFrame(
            frame_id="material_lookup_001",
            category=IntentCategory.MATERIAL_LOOKUP,
            decision_question="What material should be used?",
            surface_patterns=["What material", "Which alloy"],
            evidence_requirements=EvidenceRequirements(
                types=[EvidenceType.SPECIFICATION],
                min_count=1,
            ),
            constraint_ids=["no_noise"],
        )
        assert frame.frame_id == "material_lookup_001"
        assert frame.category == IntentCategory.MATERIAL_LOOKUP
        assert len(frame.surface_patterns) == 2

    def test_intent_classification_result(self):
        """Test IntentClassificationResult creation."""
        result = IntentClassificationResult(
            frame_id="material_lookup_001",
            category=IntentCategory.MATERIAL_LOOKUP,
            decision_question="What material should be used?",
            confidence=0.85,
            reasoning="Query asks about materials",
            evidence_requirements=EvidenceRequirements(
                types=[EvidenceType.SPECIFICATION],
                min_count=1,
            ),
            model_used=ModelTier.SONNET,
        )
        assert result.frame_id == "material_lookup_001"
        assert result.confidence == 0.85
        assert result.model_used == ModelTier.SONNET


class TestIntelligenceOutput:
    """Tests for IntelligenceOutput model."""

    def test_intelligence_output(self):
        """Test IntelligenceOutput creation."""
        output = IntelligenceOutput(
            finding="The recommended material is Inconel 718.",
            implication="This material meets hydrogen compatibility requirements.",
            action="Use Inconel 718 for hydrogen service.",
            timeline="Immediate",
            confidence=0.85,
            evidence=[
                EvidenceCitation(
                    doc_id="DOC-001",
                    evidence_type=EvidenceType.SPECIFICATION,
                    snippet="Inconel 718 is approved for hydrogen service...",
                    relevance_score=0.9,
                ),
            ],
            confidence_drivers=["Multiple sources", "Recent data"],
        )
        assert "Inconel 718" in output.finding
        assert len(output.evidence) == 1
        assert output.confidence == 0.85

    def test_intelligence_output_refusal(self):
        """Test IntelligenceOutput with refusal."""
        output = IntelligenceOutput(
            finding="",
            implication="",
            action="",
            timeline="",
            confidence=0.0,
            insufficient_evidence=True,
            refusal_reason="No relevant documents found",
        )
        assert output.insufficient_evidence is True
        assert output.refusal_reason is not None


class TestAPIModels:
    """Tests for API request/response models."""

    def test_gptl_request(self):
        """Test GPTLRequest creation."""
        request = GPTLRequest(
            query="What material for hydrogen storage?",
            domain_id="materials",
            user_id="user-001",
            mode="strict",
            quality_tier="critical",
        )
        assert request.query == "What material for hydrogen storage?"
        assert request.mode == "strict"
        assert request.quality_tier == "critical"

    def test_gptl_metrics(self):
        """Test GPTLMetrics creation."""
        metrics = GPTLMetrics(
            reduction_ratio=0.8,
            total_latency_ms=1500,
            l2_latency_ms=200,
            l3_latency_ms=300,
            l5_latency_ms=600,
            intent_confidence=0.9,
            synthesis_confidence=0.85,
            evidence_count=5,
            citation_count=3,
            model_calls=4,
            escalation_count=1,
        )
        assert metrics.total_latency_ms == 1500
        assert metrics.reduction_ratio == 0.8

    def test_model_call(self):
        """Test ModelCall creation."""
        call = ModelCall(
            model=ModelTier.SONNET,
            layer="L2",
            purpose="intent_classification",
            latency_ms=150,
            tokens_in=500,
            tokens_out=100,
        )
        assert call.model == ModelTier.SONNET
        assert call.layer == "L2"

    def test_model_call_with_escalation(self):
        """Test ModelCall with escalation tracking."""
        call = ModelCall(
            model=ModelTier.OPUS,
            layer="L5",
            purpose="synthesis",
            latency_ms=500,
            tokens_in=2000,
            tokens_out=500,
            escalated_from=ModelTier.SONNET,
        )
        assert call.escalated_from == ModelTier.SONNET


class TestBaseCondition:
    """Tests for BaseCondition shared model."""

    def test_constraint_condition_inherits_base(self):
        """Test that ConstraintCondition uses BaseCondition pattern."""
        condition = ConstraintCondition(
            field="test_field",
            operator="eq",
            value="test_value",
        )
        assert hasattr(condition, "field")
        assert hasattr(condition, "operator")
        assert hasattr(condition, "value")

    def test_supported_operators(self):
        """Test various operator values are accepted."""
        operators = ["eq", "neq", "in", "contains", "lt", "gt", "lte", "gte", "regex", "exists", "empty"]
        for op in operators:
            condition = ConstraintCondition(
                field="test",
                operator=op,
                value="test",
            )
            assert condition.operator == op


class TestIntentCategories:
    """Tests for IntentCategory enum."""

    def test_all_intent_categories(self):
        """Test all intent categories exist."""
        categories = [
            IntentCategory.MATERIAL_LOOKUP,
            IntentCategory.COMPATIBILITY_CHECK,
            IntentCategory.FAILURE_PREDICTION,
            IntentCategory.SUBSTITUTION_ANALYSIS,
            IntentCategory.COMPLIANCE_CHECK,
            IntentCategory.LIABILITY_ASSESSMENT,
            IntentCategory.PROPERTY_COMPARISON,
            IntentCategory.PROCESS_GUIDANCE,
            IntentCategory.GENERAL_QUERY,
        ]
        assert len(categories) == 9


class TestEvidenceTypes:
    """Tests for EvidenceType enum."""

    def test_primary_evidence_types(self):
        """Test primary evidence types."""
        primary = [
            EvidenceType.TEST_REPORT,
            EvidenceType.SPECIFICATION,
            EvidenceType.FAILURE_ANALYSIS,
            EvidenceType.COMPATIBILITY_MATRIX,
            EvidenceType.CERTIFICATION,
        ]
        assert len(primary) == 5

    def test_noise_evidence_types(self):
        """Test noise evidence types."""
        noise = [
            EvidenceType.MARKETING_BROCHURE,
            EvidenceType.NEWS_ARTICLE,
            EvidenceType.WEB_CONTENT,
        ]
        assert len(noise) == 3
