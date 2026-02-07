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
GPTL Test Fixtures
==================

Shared pytest fixtures for GPTL test suite.
Updated to match actual GPTL v4.1 schema.
"""

from datetime import datetime, timedelta
from typing import Any

import pytest

from gptl.schema import (
    ConstraintAction,
    ConstraintCondition,
    ConstraintRule,
    DateSource,
    DerivationCondition,
    DerivationRule,
    DocFeatures,
    DocFlags,
    DocType,
    DomainPack,
    EntitySet,
    EscalationTrigger,
    EvidenceRequirements,
    EvidenceTaxonomy,
    EvidenceType,
    IntentCategory,
    IntentFrame,
    LLMPolicies,
    ModelPolicy,
    ModelTier,
    RetrievalDeterminismConfig,
    ScoringPolicy,
)
from gptl.claude_client import MockClaudeClient


# =============================================================================
# MOCK CLIENT FIXTURES
# =============================================================================

@pytest.fixture
def mock_client() -> MockClaudeClient:
    """Create a mock Claude client with standard responses."""
    client = MockClaudeClient()

    # Intent classification response
    client.add_response(
        "classify",
        '{"frame_id": "material_lookup_001", "category": "material_lookup", "decision_question": "What material should be used?", "confidence": 0.85, "reasoning": "Query asks about materials", "evidence_requirements": {"types": ["specification"], "min_count": 1}, "escalate_to_opus": false, "model_used": "sonnet"}',
    )

    # Semantic check response
    client.add_response(
        "semantic",
        '{"decision": "KEEP", "confidence": 0.9, "reasoning": "Document is relevant"}',
    )

    # Synthesis response
    client.add_response(
        "synthesize",
        '{"finding": "Based on the evidence, the recommended material is...", "implication": "This material meets requirements", "action": "Use recommended material", "timeline": "Immediate", "confidence": 0.85, "evidence": [], "insufficient_evidence": false}',
    )

    # Anomaly explanation
    client.add_response(
        "anomaly",
        "The temporal gap may indicate a policy revision period.",
    )

    return client


# =============================================================================
# DOCUMENT FEATURE FIXTURES
# =============================================================================

@pytest.fixture
def sample_entities() -> EntitySet:
    """Create sample entity set matching actual schema."""
    return EntitySet(
        materials=["Inconel 718", "Ti-6Al-4V", "Aluminum 6061"],
        standards=["NASA-STD-6016", "MIL-STD-1540"],
        hazards=["hydrogen embrittlement", "stress corrosion"],
        systems=["propulsion", "fuel system"],
        processes=["welding", "heat treatment"],
    )


@pytest.fixture
def sample_flags() -> DocFlags:
    """Create sample document flags matching actual schema."""
    return DocFlags(
        has_measurements=True,
        has_tables=True,
        has_test_conditions=True,
        has_spec_references=True,
        has_figures=False,
        has_equations=False,
        is_noise_candidate=False,
    )


@pytest.fixture
def sample_doc_features(sample_entities: EntitySet, sample_flags: DocFlags) -> DocFeatures:
    """Create sample DocFeatures matching actual schema."""
    return DocFeatures(
        doc_id="DOC-001",
        doc_hash="abc123def456",
        feature_schema_version="1.0",
        extraction_model="haiku-3.5",
        derivation_validated=True,
        derivation_confidence=0.95,
        doc_type=DocType.SPECIFICATION,
        domain_scores={"materials": 0.9, "compatibility": 0.7},
        tags=["hydrogen", "materials", "testing"],
        entities=sample_entities,
        flags=sample_flags,
        derived_evidence_types=[EvidenceType.SPECIFICATION, EvidenceType.TEST_REPORT],
        spec_ref_count=5,
        drawing_ref_count=2,
        internal_ref_count=3,
        date_value=datetime.now() - timedelta(days=30),
        date_confidence=0.9,
        date_source=DateSource.METADATA,
        noise_markers=[],
    )


@pytest.fixture
def sample_doc_features_list(sample_doc_features: DocFeatures) -> list[DocFeatures]:
    """Create a list of sample doc features for testing."""
    features_list = [sample_doc_features]

    # Secondary document with different type
    features2 = DocFeatures(
        doc_id="DOC-002",
        doc_hash="def456abc789",
        doc_type=DocType.MEMO,
        entities=EntitySet(
            materials=["Aluminum 6061"],
            standards=[],
            hazards=[],
            systems=["thermal"],
            processes=[],
        ),
        flags=DocFlags(
            has_measurements=False,
            has_tables=False,
            has_test_conditions=False,
            has_spec_references=False,
            has_figures=False,
            has_equations=False,
            is_noise_candidate=False,
        ),
        derived_evidence_types=[EvidenceType.INTERNAL_MEMO],
        date_value=datetime.now() - timedelta(days=60),
        date_confidence=0.7,
        date_source=DateSource.CONTENT,
        derivation_confidence=0.8,
    )
    features_list.append(features2)

    # Noise candidate document
    features3 = DocFeatures(
        doc_id="DOC-003",
        doc_hash="ghi789jkl012",
        doc_type=DocType.MARKETING,
        entities=EntitySet(
            materials=["Steel 304"],
            standards=[],
            hazards=[],
            systems=[],
            processes=[],
        ),
        flags=DocFlags(
            has_measurements=False,
            has_tables=False,
            has_test_conditions=False,
            has_spec_references=False,
            has_figures=True,
            has_equations=False,
            is_noise_candidate=True,  # Marked as noise
        ),
        derived_evidence_types=[EvidenceType.MARKETING_BROCHURE],
        date_value=datetime.now() - timedelta(days=365),
        date_confidence=0.5,
        date_source=DateSource.INFERRED,
        derivation_confidence=0.6,
    )
    features_list.append(features3)

    return features_list


# =============================================================================
# DOMAIN PACK FIXTURES
# =============================================================================

@pytest.fixture
def minimal_domain_pack() -> DomainPack:
    """Create a minimal domain pack for testing."""
    return DomainPack(
        domain_id="test_domain",
        version="1.0.0",
        model_policy=ModelPolicy(),
        evidence_taxonomy=EvidenceTaxonomy(
            primary=[EvidenceType.SPECIFICATION, EvidenceType.TEST_REPORT],
            supporting=[EvidenceType.TECHNICAL_MANUAL, EvidenceType.DATASHEET],
            contextual=[EvidenceType.INTERNAL_MEMO, EvidenceType.EMAIL],
            noise=[EvidenceType.MARKETING_BROCHURE, EvidenceType.WEB_CONTENT],
        ),
        evidence_derivation=[
            DerivationRule(
                rule_id="test_to_measurement",
                conditions=[
                    DerivationCondition(
                        field="doc_type",
                        operator="eq",
                        value="report",
                    ),
                ],
                result=[EvidenceType.TEST_REPORT],
                validate_with_llm=False,
            ),
        ],
        constraints={
            "hard_drop": [
                ConstraintRule(
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
                ),
            ],
            "soft_drop": [
                ConstraintRule(
                    rule_id="deprioritize_memos",
                    name="deprioritize_memos",
                    description="Deprioritize internal memos",
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
        },
        intent_frames=[
            IntentFrame(
                frame_id="material_lookup_001",
                category=IntentCategory.MATERIAL_LOOKUP,
                decision_question="What material should be used for this application?",
                surface_patterns=["What material", "Which alloy", "material selection"],
                evidence_requirements=EvidenceRequirements(
                    types=[EvidenceType.SPECIFICATION],
                    min_count=1,
                    required_entity_classes=["materials"],
                ),
                constraint_ids=["no_noise"],
            ),
            IntentFrame(
                frame_id="compatibility_check_001",
                category=IntentCategory.COMPATIBILITY_CHECK,
                decision_question="Is this material compatible with the environment?",
                surface_patterns=["compatible", "compatibility", "work with"],
                evidence_requirements=EvidenceRequirements(
                    types=[EvidenceType.TEST_REPORT, EvidenceType.COMPATIBILITY_MATRIX],
                    min_count=2,
                    required_entity_classes=["materials", "hazards"],
                ),
                constraint_ids=["no_noise"],
            ),
        ],
        scoring_policy=ScoringPolicy(
            soft_drop_penalty_weight=0.3,
            soft_drop_penalty_function="multiplicative",
            log_penalty_in_audit=True,
        ),
        llm_policies=LLMPolicies(
            l0_derivation_validation=True,
            l2_intent_always_llm=True,
            l3_semantic_checks_enabled=True,
            l4_anomaly_explanation=True,
            l5_confidence_calibration=True,
        ),
        retrieval_determinism=RetrievalDeterminismConfig(
            index_snapshot_required=True,
            search_params_locked=True,
            tie_breaking="doc_id_ascending",
            random_seed=42,
        ),
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def make_doc_features(
    doc_id: str,
    doc_type: DocType = DocType.SPECIFICATION,
    evidence_types: list[EvidenceType] | None = None,
    is_noise: bool = False,
    has_measurements: bool = False,
    days_old: int = 30,
) -> DocFeatures:
    """Helper to create DocFeatures with sensible defaults."""
    return DocFeatures(
        doc_id=doc_id,
        doc_hash=f"hash_{doc_id}",
        derived_evidence_types=evidence_types or [EvidenceType.SPECIFICATION],
        entities=EntitySet(
            materials=[],
            standards=[],
            hazards=[],
            systems=[],
            processes=[],
        ),
        flags=DocFlags(
            has_measurements=has_measurements,
            has_tables=False,
            has_test_conditions=False,
            has_spec_references=False,
            has_figures=False,
            has_equations=False,
            is_noise_candidate=is_noise,
        ),
        doc_type=doc_type,
        date_value=datetime.now() - timedelta(days=days_old),
        date_source=DateSource.METADATA,
        date_confidence=0.9,
        derivation_confidence=0.9,
    )
