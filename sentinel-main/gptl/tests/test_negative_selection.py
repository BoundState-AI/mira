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
GPTL Negative Selection Tests
=============================

Tests for L3 Negative Selection engine in gptl.negative_selection.
Updated to match actual GPTL v4.1 implementation.
"""

import pytest

from gptl.negative_selection import (
    Candidate,
    FeatureConstraintEvaluator,
    FilterIndex,
    FilterIndexBuilder,
    NegativeSelectionEngine,
    SemanticConstraintEvaluator,
    create_candidates,
    create_negative_selection_engine,
)
from gptl.schema import (
    ConstraintAction,
    ConstraintCondition,
    ConstraintRule,
    DocFeatures,
    DocFlags,
    DocType,
    EntitySet,
    EvidenceType,
    IntentCategory,
    IntentFrame,
    EvidenceRequirements,
    ScoringPolicy,
)
from gptl.tests.conftest import make_doc_features


class TestCandidate:
    """Tests for Candidate wrapper."""

    def test_candidate_creation(self, sample_doc_features):
        """Test creating a candidate."""
        candidate = Candidate(
            features=sample_doc_features,
            initial_score=0.85,
        )
        assert candidate.doc_id == "DOC-001"
        assert candidate.initial_score == 0.85
        assert candidate.current_score == 0.85
        assert candidate.features is sample_doc_features
        assert candidate.eliminated is False

    def test_candidate_score_initialization(self, sample_doc_features):
        """Test candidate score is initialized from initial_score."""
        candidate = Candidate(
            features=sample_doc_features,
            initial_score=0.75,
        )
        assert candidate.current_score == 0.75

    def test_candidate_elimination(self, sample_doc_features):
        """Test candidate elimination."""
        candidate = Candidate(
            features=sample_doc_features,
            initial_score=0.85,
        )
        candidate.eliminate("Noise document", "no_noise")

        assert candidate.eliminated is True
        assert candidate.elimination_reason == "Noise document"
        assert candidate.elimination_rule == "no_noise"
        assert candidate.current_score == 0.0

    def test_candidate_penalty_application(self, sample_doc_features):
        """Test applying penalty to candidate."""
        candidate = Candidate(
            features=sample_doc_features,
            initial_score=0.8,
        )
        policy = ScoringPolicy(
            soft_drop_penalty_weight=0.3,
            soft_drop_penalty_function="multiplicative",
            soft_drop_penalty_cap=0.5,
        )

        candidate.apply_penalty("soft_rule", 0.3, policy)

        assert candidate.current_score == 0.8 * (1 - 0.3)  # 0.56
        assert len(candidate.penalties_applied) == 1
        assert candidate.penalties_applied[0] == ("soft_rule", 0.3)

    def test_candidate_total_penalty(self, sample_doc_features):
        """Test total penalty calculation."""
        candidate = Candidate(
            features=sample_doc_features,
            initial_score=0.9,
        )
        policy = ScoringPolicy()

        candidate.apply_penalty("rule1", 0.1, policy)
        candidate.apply_penalty("rule2", 0.2, policy)

        # Use approximate comparison due to floating point
        assert abs(candidate.total_penalty - 0.3) < 0.001


class TestFilterIndex:
    """Tests for FilterIndex (pre-retrieval gate)."""

    def test_filter_index_creation(self):
        """Test creating a filter index."""
        index = FilterIndex()
        assert index is not None
        assert index.forbidden_doc_types == []
        assert index.exclude_noise_candidates is True

    def test_filter_index_with_forbidden_types(self):
        """Test filter index with forbidden doc types."""
        index = FilterIndex(
            forbidden_doc_types=["memo", "email"],
            exclude_noise_candidates=True,
        )
        assert "memo" in index.forbidden_doc_types
        assert "email" in index.forbidden_doc_types

    def test_filter_index_to_faiss_filter(self):
        """Test converting to FAISS filter dict."""
        index = FilterIndex(
            forbidden_doc_types=["memo"],
            min_domain_score={"materials": 0.3},
        )

        faiss_filter = index.to_faiss_filter()

        assert "doc_type" in faiss_filter
        assert faiss_filter["doc_type"] == {"$nin": ["memo"]}
        assert faiss_filter["is_noise_candidate"] == {"$ne": True}

    def test_filter_index_to_milvus_expr(self):
        """Test converting to Milvus expression."""
        index = FilterIndex(
            forbidden_doc_types=["memo"],
            min_domain_score={"materials": 0.3},
        )

        expr = index.to_milvus_expr()

        assert "doc_type not in" in expr
        assert "is_noise_candidate == false" in expr


class TestFilterIndexBuilder:
    """Tests for FilterIndexBuilder."""

    def test_builder_creation(self):
        """Test creating builder."""
        builder = FilterIndexBuilder()
        assert builder is not None

    def test_builder_builds_from_constraints(self, minimal_domain_pack):
        """Test building filter from constraints."""
        builder = FilterIndexBuilder()

        index = builder.build(
            constraints=minimal_domain_pack.constraints,
            intent_frame=None,
            domain_id="materials",
        )

        assert index is not None
        assert index.min_domain_score.get("materials") is not None


class TestFeatureConstraintEvaluator:
    """Tests for feature-based constraint evaluation."""

    def test_evaluator_creation(self):
        """Test creating evaluator."""
        evaluator = FeatureConstraintEvaluator()
        assert evaluator is not None

    def test_noise_constraint_violation(self):
        """Test noise documents trigger violation."""
        evaluator = FeatureConstraintEvaluator()

        rule = ConstraintRule(
            rule_id="no_noise",
            name="no_noise",
            description="Exclude noise",
            action=ConstraintAction.HARD_DROP,
            conditions=[
                ConstraintCondition(
                    field="flags.is_noise_candidate",
                    operator="eq",
                    value=True,
                ),
            ],
        )

        noise_doc = make_doc_features("DOC-NOISE", is_noise=True)
        candidate = Candidate(features=noise_doc, initial_score=0.8)

        violated, reason = evaluator.evaluate(candidate, rule, {})

        assert violated is True
        assert "is_noise_candidate" in reason

    def test_valid_document_passes(self):
        """Test valid document has no violations."""
        evaluator = FeatureConstraintEvaluator()

        rule = ConstraintRule(
            rule_id="no_noise",
            name="no_noise",
            description="Exclude noise",
            action=ConstraintAction.HARD_DROP,
            conditions=[
                ConstraintCondition(
                    field="flags.is_noise_candidate",
                    operator="eq",
                    value=True,
                ),
            ],
        )

        valid_doc = make_doc_features("DOC-VALID", is_noise=False)
        candidate = Candidate(features=valid_doc, initial_score=0.8)

        violated, reason = evaluator.evaluate(candidate, rule, {})

        assert violated is False

    def test_doc_type_constraint(self):
        """Test doc type constraint evaluation."""
        evaluator = FeatureConstraintEvaluator()

        rule = ConstraintRule(
            rule_id="no_memos",
            name="no_memos",
            description="Exclude memos",
            action=ConstraintAction.SOFT_DROP,
            penalty_weight=0.3,
            conditions=[
                ConstraintCondition(
                    field="doc_type",
                    operator="eq",
                    value="memo",
                ),
            ],
        )

        memo_doc = make_doc_features("DOC-MEMO", doc_type=DocType.MEMO)
        candidate = Candidate(features=memo_doc, initial_score=0.8)

        violated, reason = evaluator.evaluate(candidate, rule, {})

        assert violated is True


class TestNegativeSelectionEngine:
    """Tests for NegativeSelectionEngine."""

    def test_engine_creation(self, minimal_domain_pack, mock_client):
        """Test engine creation."""
        engine = create_negative_selection_engine(
            constraints=minimal_domain_pack.constraints,
            scoring_policy=minimal_domain_pack.scoring_policy,
            claude_client=mock_client,
        )
        assert engine is not None

    def test_select_filters_noise(self, minimal_domain_pack, mock_client):
        """Test selecting filters out noise documents."""
        engine = create_negative_selection_engine(
            constraints=minimal_domain_pack.constraints,
            scoring_policy=minimal_domain_pack.scoring_policy,
            claude_client=mock_client,
        )

        # Create mix of valid and noise documents
        valid = Candidate(
            features=make_doc_features("DOC-1", is_noise=False),
            initial_score=0.9,
        )
        noise = Candidate(
            features=make_doc_features("DOC-2", is_noise=True),
            initial_score=0.8,
        )

        survivors, report = engine.select([valid, noise])

        # Noise should be eliminated
        survivor_ids = [s.doc_id for s in survivors]
        assert "DOC-1" in survivor_ids
        assert "DOC-2" not in survivor_ids
        assert report.candidates_eliminated >= 1

    def test_select_applies_soft_penalties(self, mock_client):
        """Test soft drop applies score penalty."""
        constraints = {
            "hard_drop": [],
            "soft_drop": [
                ConstraintRule(
                    rule_id="penalize_memos",
                    name="penalize_memos",
                    description="Penalize memo documents",
                    action=ConstraintAction.SOFT_DROP,
                    penalty_weight=0.3,
                    conditions=[
                        ConstraintCondition(
                            field="doc_type",
                            operator="eq",
                            value="memo",
                        ),
                    ],
                ),
            ],
        }

        engine = create_negative_selection_engine(
            constraints=constraints,
            scoring_policy=ScoringPolicy(
                soft_drop_penalty_weight=0.3,
                soft_drop_penalty_function="multiplicative",
            ),
            claude_client=mock_client,
        )

        memo = Candidate(
            features=make_doc_features("DOC-MEMO", doc_type=DocType.MEMO),
            initial_score=0.8,
        )

        survivors, report = engine.select([memo])

        # Memo should survive but with reduced score
        assert len(survivors) == 1
        assert survivors[0].current_score < 0.8
        assert report.candidates_deprioritized >= 1

    def test_select_with_intent_frame(self, minimal_domain_pack, mock_client):
        """Test selection with intent frame context."""
        engine = create_negative_selection_engine(
            constraints=minimal_domain_pack.constraints,
            scoring_policy=minimal_domain_pack.scoring_policy,
            claude_client=mock_client,
        )

        intent_frame = IntentFrame(
            frame_id="material_lookup_001",
            category=IntentCategory.MATERIAL_LOOKUP,
            decision_question="What material?",
            evidence_requirements=EvidenceRequirements(
                types=[EvidenceType.SPECIFICATION],
                min_count=1,
            ),
            constraint_ids=["no_noise"],
        )

        doc = Candidate(
            features=make_doc_features("DOC-1", is_noise=False),
            initial_score=0.9,
        )

        survivors, report = engine.select([doc], intent_frame=intent_frame)

        assert len(survivors) == 1

    def test_violation_report(self, minimal_domain_pack, mock_client):
        """Test violation report generation."""
        engine = create_negative_selection_engine(
            constraints=minimal_domain_pack.constraints,
            scoring_policy=minimal_domain_pack.scoring_policy,
            claude_client=mock_client,
        )

        candidates = [
            Candidate(features=make_doc_features("DOC-1", is_noise=False), initial_score=0.9),
            Candidate(features=make_doc_features("DOC-2", is_noise=True), initial_score=0.8),
            Candidate(features=make_doc_features("DOC-3", is_noise=False), initial_score=0.7),
        ]

        survivors, report = engine.select(candidates)

        assert report.total_candidates == 3
        assert report.survivors >= 2
        assert len(report.violations) >= 1


class TestCreateCandidates:
    """Tests for create_candidates helper."""

    def test_create_from_features(self, sample_doc_features):
        """Test creating candidates from features list."""
        features_list = [sample_doc_features]
        scores = [0.9]

        candidates = create_candidates(features_list, scores)

        assert len(candidates) == 1
        assert candidates[0].features is sample_doc_features
        assert candidates[0].initial_score == 0.9

    def test_create_with_default_scores(self, sample_doc_features):
        """Test creating candidates with default scores."""
        features_list = [sample_doc_features]

        candidates = create_candidates(features_list)

        assert len(candidates) == 1
        assert candidates[0].initial_score == 1.0  # Default score


class TestConstraintCascade:
    """Tests for constraint cascade behavior."""

    def test_hard_drop_removes_completely(self, mock_client):
        """Test hard drop removes document entirely."""
        constraints = {
            "hard_drop": [
                ConstraintRule(
                    rule_id="no_noise",
                    name="no_noise",
                    description="Exclude noise",
                    action=ConstraintAction.HARD_DROP,
                    conditions=[
                        ConstraintCondition(
                            field="flags.is_noise_candidate",
                            operator="eq",
                            value=True,
                        ),
                    ],
                ),
            ],
            "soft_drop": [],
        }

        engine = create_negative_selection_engine(
            constraints=constraints,
            claude_client=mock_client,
        )

        candidates = [
            Candidate(features=make_doc_features("DOC-1", is_noise=False), initial_score=0.9),
            Candidate(features=make_doc_features("DOC-2", is_noise=True), initial_score=0.8),
            Candidate(features=make_doc_features("DOC-3", is_noise=False), initial_score=0.7),
        ]

        survivors, report = engine.select(candidates)

        survivor_ids = [s.doc_id for s in survivors]
        assert "DOC-2" not in survivor_ids
        assert "DOC-1" in survivor_ids
        assert "DOC-3" in survivor_ids

    def test_multiple_constraints_applied(self, mock_client):
        """Test multiple constraints are applied."""
        constraints = {
            "hard_drop": [
                ConstraintRule(
                    rule_id="no_noise",
                    name="no_noise",
                    description="Exclude noise",
                    action=ConstraintAction.HARD_DROP,
                    conditions=[
                        ConstraintCondition(
                            field="flags.is_noise_candidate",
                            operator="eq",
                            value=True,
                        ),
                    ],
                ),
                ConstraintRule(
                    rule_id="no_marketing",
                    name="no_marketing",
                    description="Exclude marketing",
                    action=ConstraintAction.HARD_DROP,
                    conditions=[
                        ConstraintCondition(
                            field="doc_type",
                            operator="eq",
                            value="marketing",
                        ),
                    ],
                ),
            ],
            "soft_drop": [],
        }

        engine = create_negative_selection_engine(
            constraints=constraints,
            claude_client=mock_client,
        )

        # Create documents that violate different rules
        noise_doc = Candidate(
            features=make_doc_features("DOC-NOISE", is_noise=True),
            initial_score=0.8,
        )
        marketing_doc = Candidate(
            features=make_doc_features("DOC-MARKETING", doc_type=DocType.MARKETING),
            initial_score=0.7,
        )
        valid_doc = Candidate(
            features=make_doc_features("DOC-VALID", is_noise=False),
            initial_score=0.9,
        )

        survivors, report = engine.select([noise_doc, marketing_doc, valid_doc])

        survivor_ids = [s.doc_id for s in survivors]
        assert "DOC-NOISE" not in survivor_ids
        assert "DOC-MARKETING" not in survivor_ids
        assert "DOC-VALID" in survivor_ids
        assert report.candidates_eliminated >= 2

    def test_survivors_sorted_by_score(self, mock_client):
        """Test survivors are sorted by current score."""
        constraints = {"hard_drop": [], "soft_drop": []}

        engine = create_negative_selection_engine(
            constraints=constraints,
            claude_client=mock_client,
        )

        candidates = [
            Candidate(features=make_doc_features("DOC-LOW"), initial_score=0.3),
            Candidate(features=make_doc_features("DOC-HIGH"), initial_score=0.9),
            Candidate(features=make_doc_features("DOC-MED"), initial_score=0.6),
        ]

        survivors, _ = engine.select(candidates)

        # Should be sorted descending by score
        assert survivors[0].doc_id == "DOC-HIGH"
        assert survivors[1].doc_id == "DOC-MED"
        assert survivors[2].doc_id == "DOC-LOW"
