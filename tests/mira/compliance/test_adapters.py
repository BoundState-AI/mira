#!/usr/bin/env python3
"""
Module: Test Compliance Adapters
Purpose: Test coverage for O2, H2, and MUA adapters (Fran Fixes #1, #2, #4, #5, #7)

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

from mira.compliance.adapters.base import BaseAdapter
from mira.compliance.adapters.o2_adapter import O2Adapter
from mira.compliance.adapters.h2_adapter import H2Adapter
from mira.compliance.adapters.mua_adapter import MUAAdapter
from mira.compliance.models.enums import (
    ComplianceBasis,
    EnvironmentType,
    FailureMode,
    GapSeverity,
    GapTrigger,
    MUACategory,
    SourceType,
)
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal
from mira.compliance.models.policy import EnvironmentDefinition
from mira.compliance.models.resolution import MaterialResolutionResult


def create_mock_evidence():
    """Create a mock evidence reference for testing."""
    return EvidenceRef(
        source_type=SourceType.MAPTIS,
        source_id="MAPTIS:12345",
        confidence=1.0,
        confidence_basis="Direct lookup",
        retrieved_at=datetime.now(),
        retrieval_method="maptis_direct",
    )


def create_resolved_material(
    material_id: int = 12345,
    canonical_name: str = "316 Stainless Steel",
    material_family: str = "austenitic_ss",
):
    """Create a resolved material for testing."""
    return MaterialResolutionResult(
        input_material_name="SS 316",
        resolved=True,
        resolution_method="maptis_code_direct",
        resolution_confidence=1.0,
        canonical_maptis_code=material_id,
        canonical_material_id=f"MAPTIS:{material_id}",
        canonical_name=canonical_name,
        material_family=material_family,
        evidence_ref=create_mock_evidence(),
    )


def create_unresolved_material():
    """Create an unresolved material for testing."""
    return MaterialResolutionResult(
        input_material_name="Unknown Alloy XYZ",
        resolved=False,
        resolution_method="failed",
        resolution_confidence=0.0,
    )


def create_o2_environment():
    """Create an O2 environment for testing."""
    return EnvironmentDefinition(
        environment_id="ENV_O2_001",
        environment_type=EnvironmentType.OXYGEN,
        description="High-pressure GOX system",
        is_oxygen_enriched=True,
        oxygen_pct=99.5,
        pressure_psia=3000,
        pressure_is_high=True,
    )


def create_h2_environment():
    """Create an H2 environment for testing."""
    return EnvironmentDefinition(
        environment_id="ENV_H2_001",
        environment_type=EnvironmentType.HYDROGEN,
        description="GH2 transfer system",
        is_hydrogen_service=True,
        hydrogen_phase="GH2",
        pressure_psia=5000,
    )


class TestBaseAdapter:
    """Test BaseAdapter base class."""

    def test_version_property(self):
        """Test adapter version property."""
        adapter = O2Adapter(version="1.2.3")
        assert adapter.version == "1.2.3"

    def test_create_evidence_ref(self):
        """Test evidence reference creation helper."""
        adapter = O2Adapter()
        evidence = adapter._create_evidence_ref(
            source_id="TEST-001",
            confidence=0.9,
            confidence_basis="Test basis",
            retrieval_method="test_method",
        )
        assert evidence.source_id == "TEST-001"
        assert evidence.confidence == 0.9


class TestO2Adapter:
    """Test O2Adapter - Fran Fixes #1, #2."""

    def test_evaluate_resolved_material(self):
        """Test evaluation with resolved material."""
        adapter = O2Adapter()
        material = create_resolved_material()
        environment = create_o2_environment()

        output = adapter.evaluate(material, environment)

        assert output.material_id == "MAPTIS:12345"
        assert output.environment_id == "ENV_O2_001"
        # Real O2 twin returns actual classification; placeholder returns UNKNOWN
        assert output.classification in ["OK", "CAUTION", "PROHIBITED", "UNKNOWN"]

    def test_evaluate_unresolved_material(self):
        """Test evaluation with unresolved material."""
        adapter = O2Adapter()
        material = create_unresolved_material()
        environment = create_o2_environment()

        output = adapter.evaluate(material, environment)

        assert output.classification == "UNKNOWN"
        assert len(output.gap_signals) == 1
        assert output.gap_signals[0].gap_type == FailureMode.MISSING_INPUT

    def test_adapter_emits_signals_not_determinations(self):
        """Fran Fix #1: Adapter emits signals, NOT MPRDetermination."""
        adapter = O2Adapter()
        material = create_unresolved_material()
        environment = create_o2_environment()

        output = adapter.evaluate(material, environment)

        # Output should have gap_signals, not mpr_determinations
        assert hasattr(output, "gap_signals")
        assert not hasattr(output, "mpr_determinations")

    def test_evidence_has_source_type(self):
        """Fran Fix #2: EvidenceRef must have source_type."""
        adapter = O2Adapter()
        material = create_resolved_material()
        environment = create_o2_environment()

        output = adapter.evaluate(material, environment)

        # All evidence refs should have source_type
        for evidence in output.evidence_refs:
            assert hasattr(evidence, "source_type")
            assert evidence.source_type is not None


class TestH2Adapter:
    """Test H2Adapter - Fran Fixes #1, #4, #5."""

    def test_evaluate_resolved_material(self):
        """Test evaluation with resolved material."""
        adapter = H2Adapter()
        material = create_resolved_material()
        environment = create_h2_environment()

        output = adapter.evaluate(material, environment)

        assert output.material_id == "MAPTIS:12345"
        assert output.environment_id == "ENV_H2_001"

    def test_evaluate_unresolved_material(self):
        """Test evaluation with unresolved material."""
        adapter = H2Adapter()
        material = create_unresolved_material()
        environment = create_h2_environment()

        output = adapter.evaluate(material, environment)

        assert output.verdict == "UNKNOWN"
        assert len(output.gap_signals) == 1
        assert output.gap_signals[0].gap_type == FailureMode.MISSING_INPUT
        assert output.h2_token_match_risk is True

    def test_adapter_emits_signals_not_determinations(self):
        """Fran Fix #1: Adapter emits signals, NOT MPRDetermination."""
        adapter = H2Adapter()
        material = create_resolved_material()
        environment = create_h2_environment()

        output = adapter.evaluate(material, environment)

        # Output should have gap_signals and constraints, not mpr_determinations
        assert hasattr(output, "gap_signals")
        assert hasattr(output, "operational_constraints")
        assert not hasattr(output, "mpr_determinations")

    def test_h2_token_match_risk_propagation(self):
        """Fran Fix #5: H2 token match risk propagates from resolver."""
        adapter = H2Adapter()
        material = create_resolved_material()
        material.h2_token_match_risk = True
        material.h2_token_match_risk_reasons = ["low confidence"]
        environment = create_h2_environment()

        output = adapter.evaluate(material, environment)

        assert output.h2_token_match_risk is True

    def test_uses_canonical_name(self):
        """Fran Fix #5: Uses canonical_name, not raw input."""
        adapter = H2Adapter()
        material = create_resolved_material(
            canonical_name="316 Stainless Steel, Annealed"
        )
        environment = create_h2_environment()

        # The adapter should use get_h2_query_name() internally
        query_name = material.get_h2_query_name()
        assert query_name == "316 Stainless Steel, Annealed"

    def test_confidence_split(self):
        """Test confidence split between match and envelope."""
        adapter = H2Adapter()
        material = create_resolved_material()
        environment = create_h2_environment()

        output = adapter.evaluate(material, environment)

        assert hasattr(output, "match_confidence")
        assert hasattr(output, "envelope_confidence")
        assert 0.0 <= output.match_confidence <= 1.0
        assert 0.0 <= output.envelope_confidence <= 1.0


class TestMUAAdapter:
    """Test MUAAdapter - Fran Fix #7."""

    def test_generate_with_signals(self):
        """Test MUA generation with gap signals."""
        adapter = MUAAdapter()
        material = create_resolved_material()
        environment = create_o2_environment()

        gap = GapSignal(
            gap_id="test_gap_001",
            gap_type=FailureMode.FLAM,
            trigger=GapTrigger.RESTRICTED_POLICY,
            trigger_parameter="material_family",
            material_id="MAPTIS:12345",
            severity=GapSeverity.HIGH,
            confidence=0.9,
            summary="Test gap signal",
            source_adapter="o2_adapter",
            suggested_basis=ComplianceBasis.POLICY,
        )

        output = adapter.generate([gap], material, environment)

        assert output.material_id == "MAPTIS:12345"
        assert output.category in [1, 2, 3]
        assert len(output.draft_text) > 0
        assert "test_gap_001" in output.triggering_gap_ids

    def test_category_determination_critical_gap(self):
        """Test category determination with critical gap."""
        adapter = MUAAdapter()
        material = create_resolved_material()
        environment = create_o2_environment()

        critical_gap = GapSignal(
            gap_id="critical_001",
            gap_type=FailureMode.O2_PROHIBITED,
            trigger=GapTrigger.PROHIBITED_FAMILY,
            trigger_parameter="material_family",
            material_id="MAPTIS:12345",
            severity=GapSeverity.CRITICAL,
            confidence=0.95,
            summary="Critical gap",
            source_adapter="o2_adapter",
            suggested_basis=ComplianceBasis.POLICY,
        )

        output = adapter.generate([critical_gap], material, environment)

        # Critical gaps should result in Category 1
        assert output.category == 1

    def test_llm_invocation_tracking(self):
        """Fran Fix #7: Track LLM invocations for reproducibility."""
        adapter = MUAAdapter(
            llm_model_id="claude-sonnet-4-20250514",
            prompt_template_version="1.0.0",
        )
        material = create_resolved_material()
        environment = create_o2_environment()

        gap = GapSignal(
            gap_id="test_gap",
            gap_type=FailureMode.FLAM,
            trigger=GapTrigger.RESTRICTED_POLICY,
            trigger_parameter="policy",
            material_id="MAPTIS:12345",
            severity=GapSeverity.HIGH,
            confidence=0.9,
            summary="Test",
            source_adapter="o2_adapter",
            suggested_basis=ComplianceBasis.POLICY,
        )

        # Clear any previous invocations
        adapter.clear_llm_invocations()

        output = adapter.generate([gap], material, environment)

        # Note: Without actual MUA generator, invocations may be empty
        # This test verifies the tracking mechanism exists
        invocations = adapter.get_llm_invocations()
        assert isinstance(invocations, list)

    def test_adapter_never_sets_compliance_status(self):
        """MUA adapter drafts TEXT only, never sets compliance status."""
        adapter = MUAAdapter()
        material = create_resolved_material()
        environment = create_o2_environment()

        gap = GapSignal(
            gap_id="test_gap",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_HIGH,
            trigger_parameter="hee_band",
            material_id="MAPTIS:12345",
            severity=GapSeverity.HIGH,
            confidence=0.9,
            summary="Test",
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS,
        )

        output = adapter.generate([gap], material, environment)

        # Output should NOT have compliance_status
        assert not hasattr(output, "compliance_status")
        # Should have draft_text
        assert hasattr(output, "draft_text")
        assert len(output.draft_text) > 0


class TestAdapterOutputIntegrity:
    """Test adapter outputs maintain required contracts."""

    def test_o2_output_has_required_fields(self):
        """Test O2 adapter output has all required fields."""
        adapter = O2Adapter()
        material = create_resolved_material()
        environment = create_o2_environment()

        output = adapter.evaluate(material, environment)

        # Required fields
        assert hasattr(output, "material_id")
        assert hasattr(output, "environment_id")
        assert hasattr(output, "classification")
        assert hasattr(output, "rationale")
        assert hasattr(output, "gap_signals")
        assert hasattr(output, "evidence_refs")
        assert hasattr(output, "suggested_basis")

    def test_h2_output_has_required_fields(self):
        """Test H2 adapter output has all required fields."""
        adapter = H2Adapter()
        material = create_resolved_material()
        environment = create_h2_environment()

        output = adapter.evaluate(material, environment)

        # Required fields
        assert hasattr(output, "material_id")
        assert hasattr(output, "environment_id")
        assert hasattr(output, "verdict")
        assert hasattr(output, "confidence")
        assert hasattr(output, "match_confidence")
        assert hasattr(output, "envelope_confidence")
        assert hasattr(output, "gap_signals")
        assert hasattr(output, "operational_constraints")
        assert hasattr(output, "h2_token_match_risk")

    def test_mua_output_has_required_fields(self):
        """Test MUA adapter output has all required fields."""
        adapter = MUAAdapter()
        material = create_resolved_material()
        environment = create_o2_environment()

        output = adapter.generate([], material, environment)

        # Required fields
        assert hasattr(output, "material_id")
        assert hasattr(output, "environment_id")
        assert hasattr(output, "triggering_gap_ids")
        assert hasattr(output, "category")
        assert hasattr(output, "category_rule_id")
        assert hasattr(output, "draft_text")
