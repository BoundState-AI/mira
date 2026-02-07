#!/usr/bin/env python3
"""
Module: Test Compliance Models
Purpose: Test coverage for compliance data models

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright (c) 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program

import pytest
import sys
from datetime import datetime

sys.path.insert(0, r"C:\BoundState")

from mira.compliance.models.enums import (
    ApplicabilityStatus,
    ComplianceBasis,
    ComplianceStatus,
    ConstraintSource,
    EnvironmentType,
    FailureMode,
    GapSeverity,
    GapTrigger,
    MUACategory,
    RequiredAction,
    SourceType,
)
from mira.compliance.models.evidence import EvidenceRef, EvidenceCollection
from mira.compliance.models.gaps import GapSignal, OperationalConstraint, GapSummary
from mira.compliance.models.resolution import MaterialResolutionResult
from mira.compliance.models.policy import (
    EnvironmentDefinition,
    EnvironmentPolicy,
    ConductorPolicy,
)


class TestEvidenceRef:
    """Test EvidenceRef model - Fran Fix #2."""

    def test_create_maptis_evidence(self):
        """Test creating MAPTIS evidence reference."""
        evidence = EvidenceRef(
            source_type=SourceType.MAPTIS,
            source_id="MAPTIS:12345",
            confidence=0.95,
            confidence_basis="Direct MAPTIS lookup",
            retrieved_at=datetime.now(),
            retrieval_method="maptis_direct",
        )
        assert evidence.source_type == SourceType.MAPTIS
        assert evidence.supports_test_basis() is True
        assert evidence.supports_policy_basis() is False

    def test_create_standard_evidence(self):
        """Test creating standard/policy evidence reference."""
        evidence = EvidenceRef(
            source_type=SourceType.STANDARD,
            source_id="NASA-STD-6016C",
            source_version="C",
            locator="Section 4.2.1",
            confidence=1.0,
            confidence_basis="Direct standard citation",
            retrieved_at=datetime.now(),
            retrieval_method="manual_citation",
        )
        assert evidence.source_type == SourceType.STANDARD
        assert evidence.supports_test_basis() is False
        assert evidence.supports_policy_basis() is True

    def test_supports_test_basis_for_test_report(self):
        """Test that TEST_REPORT supports TEST basis."""
        evidence = EvidenceRef(
            source_type=SourceType.TEST_REPORT,
            source_id="TR-2025-001",
            confidence=0.9,
            confidence_basis="Test report analysis",
            retrieved_at=datetime.now(),
            retrieval_method="document_search",
        )
        assert evidence.supports_test_basis() is True

    def test_is_precedent(self):
        """Test precedent detection."""
        evidence = EvidenceRef(
            source_type=SourceType.MUA_PRECEDENT,
            source_id="MUA-2024-0042",
            confidence=0.85,
            confidence_basis="Precedent match",
            retrieved_at=datetime.now(),
            retrieval_method="precedent_search",
        )
        assert evidence.is_precedent() is True

    def test_get_citation(self):
        """Test citation generation."""
        evidence = EvidenceRef(
            source_type=SourceType.STANDARD,
            source_id="NASA-STD-6016C",
            source_version="C",
            locator="Table 4.2",
            confidence=1.0,
            confidence_basis="Direct citation",
            retrieved_at=datetime.now(),
            retrieval_method="manual",
        )
        citation = evidence.get_citation()
        assert "NASA-STD-6016C" in citation
        assert "vC" in citation
        assert "Table 4.2" in citation


class TestEvidenceCollection:
    """Test EvidenceCollection model."""

    def test_get_strongest_evidence(self):
        """Test getting evidence with highest confidence."""
        collection = EvidenceCollection(evidence_refs=[
            EvidenceRef(
                source_type=SourceType.MAPTIS,
                source_id="MAPTIS:001",
                confidence=0.8,
                confidence_basis="Test 1",
                retrieved_at=datetime.now(),
                retrieval_method="test",
            ),
            EvidenceRef(
                source_type=SourceType.MAPTIS,
                source_id="MAPTIS:002",
                confidence=0.95,
                confidence_basis="Test 2",
                retrieved_at=datetime.now(),
                retrieval_method="test",
            ),
        ])
        strongest = collection.get_strongest_evidence()
        assert strongest.source_id == "MAPTIS:002"
        assert strongest.confidence == 0.95

    def test_has_test_evidence(self):
        """Test checking for TEST basis support."""
        collection = EvidenceCollection(evidence_refs=[
            EvidenceRef(
                source_type=SourceType.MAPTIS,
                source_id="MAPTIS:001",
                confidence=0.9,
                confidence_basis="Test",
                retrieved_at=datetime.now(),
                retrieval_method="test",
            ),
        ])
        assert collection.has_test_evidence() is True

    def test_empty_collection(self):
        """Test empty collection behavior."""
        collection = EvidenceCollection()
        assert collection.get_strongest_evidence() is None
        assert collection.has_test_evidence() is False
        assert collection.get_average_confidence() == 0.0


class TestGapSignal:
    """Test GapSignal model."""

    def test_create_hee_gap_signal(self):
        """Test creating an HEE gap signal."""
        gap = GapSignal(
            gap_id="abc123def456",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_EXTREME,
            trigger_parameter="hee_band",
            material_id="MAPTIS:12345",
            environment_id="ENV_H2_001",
            hee_band="extreme",
            severity=GapSeverity.CRITICAL,
            confidence=0.9,
            summary="Extreme HEE risk for material in H2 service",
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS,
        )
        assert gap.gap_type == FailureMode.HEE
        assert gap.is_critical() is True
        assert gap.is_hee_related() is True
        assert gap.requires_mua() is True

    def test_create_o2_gap_signal(self):
        """Test creating an O2 gap signal."""
        gap = GapSignal(
            gap_id="xyz789abc123",
            gap_type=FailureMode.O2_PROHIBITED,
            trigger=GapTrigger.PROHIBITED_FAMILY,
            trigger_parameter="material_family",
            material_id="MAPTIS:99999",
            environment_id="ENV_O2_001",
            severity=GapSeverity.CRITICAL,
            confidence=0.95,
            summary="Material family prohibited in O2 service",
            source_adapter="o2_adapter",
            suggested_basis=ComplianceBasis.POLICY,
        )
        assert gap.is_o2_related() is True
        assert gap.is_hee_related() is False

    def test_is_critical(self):
        """Test critical severity check."""
        gap = GapSignal(
            gap_id="test123",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_SEVERE,
            trigger_parameter="hee_band",
            material_id="MAPTIS:12345",
            severity=GapSeverity.CRITICAL,
            confidence=0.9,
            summary="Test gap",
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.TEST,
        )
        assert gap.is_critical() is True

    def test_requires_mua(self):
        """Test MUA requirement check."""
        # HIGH severity requires MUA
        gap_high = GapSignal(
            gap_id="test123",
            gap_type=FailureMode.FLAM,
            trigger=GapTrigger.RESTRICTED_POLICY,
            trigger_parameter="policy",
            material_id="MAPTIS:12345",
            severity=GapSeverity.HIGH,
            confidence=0.9,
            summary="Test gap",
            source_adapter="o2_adapter",
            suggested_basis=ComplianceBasis.POLICY,
        )
        assert gap_high.requires_mua() is True

        # MEDIUM severity does not require MUA
        gap_medium = GapSignal(
            gap_id="test456",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_HIGH,
            trigger_parameter="hee_band",
            material_id="MAPTIS:12345",
            severity=GapSeverity.MEDIUM,
            confidence=0.8,
            summary="Test gap",
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.TEST,
        )
        assert gap_medium.requires_mua() is False


class TestOperationalConstraint:
    """Test OperationalConstraint model."""

    def test_create_pressure_constraint(self):
        """Test creating a pressure constraint."""
        constraint = OperationalConstraint(
            constraint_id="con123",
            description="Maximum pressure limit for H2 service",
            source_basis=ConstraintSource.ENGINE_CONSTRAINT,
            parameter="pressure",
            limit_type="max",
            limit_value="5000 psia",
            verification_method="Plan review",
        )
        assert constraint.is_pressure_constraint() is True
        assert constraint.is_temperature_constraint() is False

    def test_create_temperature_constraint(self):
        """Test creating a temperature constraint."""
        constraint = OperationalConstraint(
            constraint_id="con456",
            description="Minimum temperature limit",
            source_basis=ConstraintSource.POLICY_CONSTRAINT,
            parameter="temperature_min",
            limit_type="min",
            limit_value="-423 F",
            verification_method="Inspection",
        )
        assert constraint.is_temperature_constraint() is True
        assert constraint.is_pressure_constraint() is False

    def test_format_for_document(self):
        """Test formatting for document inclusion."""
        constraint = OperationalConstraint(
            constraint_id="con789",
            description="Test constraint",
            source_basis=ConstraintSource.ENGINE_CONSTRAINT,
            parameter="pressure",
            limit_type="max",
            limit_value="3000 psia",
            verification_method="Test verification",
        )
        formatted = constraint.format_for_document()
        assert "pressure" in formatted
        assert "max" in formatted
        assert "3000 psia" in formatted


class TestGapSummary:
    """Test GapSummary model."""

    def test_from_gaps_empty(self):
        """Test creating summary from empty list."""
        summary = GapSummary.from_gaps([], "MAPTIS:12345")
        assert summary.total_gaps == 0
        assert summary.critical_gaps == 0
        assert summary.requires_mua is False

    def test_from_gaps_with_critical(self):
        """Test creating summary with critical gaps."""
        gaps = [
            GapSignal(
                gap_id="gap1",
                gap_type=FailureMode.HEE,
                trigger=GapTrigger.HEE_BAND_EXTREME,
                trigger_parameter="hee_band",
                material_id="MAPTIS:12345",
                severity=GapSeverity.CRITICAL,
                confidence=0.9,
                summary="Critical gap",
                source_adapter="h2_adapter",
                suggested_basis=ComplianceBasis.TEST,
            ),
        ]
        summary = GapSummary.from_gaps(gaps, "MAPTIS:12345")
        assert summary.total_gaps == 1
        assert summary.critical_gaps == 1
        assert summary.hee_gaps == 1
        assert summary.requires_mua is True


class TestMaterialResolutionResult:
    """Test MaterialResolutionResult model - Fran Fix #5."""

    def test_resolved_material(self):
        """Test resolved material with canonical identifiers."""
        evidence = EvidenceRef(
            source_type=SourceType.MAPTIS,
            source_id="MAPTIS:12345",
            confidence=1.0,
            confidence_basis="Direct lookup",
            retrieved_at=datetime.now(),
            retrieval_method="maptis_direct",
        )
        resolution = MaterialResolutionResult(
            input_material_name="SS 316",
            input_material_spec="AMS 5648",
            resolved=True,
            resolution_method="maptis_code_direct",
            resolution_confidence=1.0,
            canonical_maptis_code=12345,
            canonical_material_id="MAPTIS:12345",
            canonical_name="316 Stainless Steel",
            canonical_spec="AMS 5648J",
            material_family="austenitic_ss",
            evidence_ref=evidence,
        )
        assert resolution.resolved is True
        assert resolution.get_h2_query_name() == "316 Stainless Steel"

    def test_unresolved_material(self):
        """Test unresolved material."""
        resolution = MaterialResolutionResult(
            input_material_name="Unknown Alloy XYZ",
            resolved=False,
            resolution_method="failed",
            resolution_confidence=0.0,
        )
        assert resolution.resolved is False
        assert resolution.get_h2_query_name() is None

    def test_h2_token_match_risk_flagging(self):
        """Test H2 token match risk detection - Fran Fix #5."""
        evidence = EvidenceRef(
            source_type=SourceType.MAPTIS,
            source_id="MAPTIS:99999",
            confidence=0.7,
            confidence_basis="Fuzzy match",
            retrieved_at=datetime.now(),
            retrieval_method="name_search_single",
        )
        resolution = MaterialResolutionResult(
            input_material_name="steel or aluminum",
            resolved=True,
            resolution_method="fuzzy_match",
            resolution_confidence=0.7,
            canonical_maptis_code=99999,
            canonical_material_id="MAPTIS:99999",
            canonical_name="steel",
            material_family="unknown",
            evidence_ref=evidence,
        )
        resolution.should_flag_h2_risk()
        assert resolution.h2_token_match_risk is True
        assert len(resolution.h2_token_match_risk_reasons) > 0


class TestEnvironmentDefinition:
    """Test EnvironmentDefinition model."""

    def test_oxygen_environment(self):
        """Test creating an oxygen environment."""
        env = EnvironmentDefinition(
            environment_id="ENV_O2_001",
            environment_type=EnvironmentType.OXYGEN,
            description="High-pressure GOX system",
            is_oxygen_enriched=True,
            oxygen_pct=99.5,
            pressure_psia=3000,
            pressure_is_high=True,
            is_habitable=False,
        )
        assert env.is_oxygen_enriched is True
        mua_cat = env.get_mua_category()
        assert mua_cat == MUACategory.CATEGORY_1  # High-risk O2

    def test_hydrogen_environment(self):
        """Test creating a hydrogen environment."""
        env = EnvironmentDefinition(
            environment_id="ENV_H2_001",
            environment_type=EnvironmentType.HYDROGEN,
            description="GH2 transfer system",
            is_hydrogen_service=True,
            hydrogen_phase="GH2",
            pressure_psia=5000,
            pressure_is_high=True,
            is_habitable=False,
        )
        assert env.is_hydrogen_service is True

    def test_habitable_environment_category(self):
        """Test MUA category for habitable environment."""
        env = EnvironmentDefinition(
            environment_id="ENV_HAB_001",
            environment_type=EnvironmentType.HABITABLE,
            description="Crew cabin",
            is_habitable=True,
            is_breathing_atmosphere=True,
            oxygen_pct=21.0,
        )
        mua_cat = env.get_mua_category()
        assert mua_cat == MUACategory.CATEGORY_2  # Standard habitable


class TestEnvironmentPolicy:
    """Test EnvironmentPolicy model."""

    def test_requires_o2_twin(self):
        """Test O2 twin routing decision."""
        policy = EnvironmentPolicy()
        env_o2 = EnvironmentDefinition(
            environment_id="ENV_001",
            environment_type=EnvironmentType.OXYGEN,
            description="O2 system",
            is_oxygen_enriched=True,
        )
        assert policy.requires_o2_twin(env_o2) is True

        env_other = EnvironmentDefinition(
            environment_id="ENV_002",
            environment_type=EnvironmentType.OTHER,
            description="Non-O2 environment",
        )
        assert policy.requires_o2_twin(env_other) is False

    def test_requires_h2_twin(self):
        """Test H2 twin routing decision."""
        policy = EnvironmentPolicy()
        env_h2 = EnvironmentDefinition(
            environment_id="ENV_001",
            environment_type=EnvironmentType.HYDROGEN,
            description="H2 system",
            is_hydrogen_service=True,
        )
        assert policy.requires_h2_twin(env_h2) is True


class TestConductorPolicy:
    """Test ConductorPolicy model - Fran Fix #3."""

    def test_get_caution_action_habitable(self):
        """Test CAUTION action in habitable environment - Fran Fix #3."""
        policy = ConductorPolicy()
        action = policy.get_caution_action(
            is_habitable=True,
            o2_pct=21.0,
            has_constraints=True,
        )
        assert action == RequiredAction.GENERATE_MUA

    def test_get_caution_action_o2_enriched(self):
        """Test CAUTION action in O2-enriched environment - Fran Fix #3."""
        policy = ConductorPolicy()
        action = policy.get_caution_action(
            is_habitable=False,
            o2_pct=30.0,  # O2-enriched
            has_constraints=True,
        )
        assert action == RequiredAction.GENERATE_MUA

    def test_get_caution_action_non_habitable_normal_o2(self):
        """Test CAUTION action in non-habitable, normal O2 environment."""
        policy = ConductorPolicy()
        action = policy.get_caution_action(
            is_habitable=False,
            o2_pct=21.0,
            has_constraints=True,
        )
        assert action == RequiredAction.ADD_CONSTRAINTS_SECTION

    def test_get_required_action_critical(self):
        """Test required action for CRITICAL severity."""
        policy = ConductorPolicy()
        action = policy.get_required_action_for_severity(
            severity="critical",
            is_habitable=False,
        )
        assert action == RequiredAction.GENERATE_MUA

    def test_get_required_action_low(self):
        """Test required action for LOW severity."""
        policy = ConductorPolicy()
        action = policy.get_required_action_for_severity(
            severity="low",
            has_constraints=False,
        )
        assert action == RequiredAction.NONE
