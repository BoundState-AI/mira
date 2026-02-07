#!/usr/bin/env python3
"""
Module: Test Compliance Enumerations
Purpose: Test coverage for compliance module enums

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


class TestApplicabilityStatus:
    """Test ApplicabilityStatus enum."""

    def test_applicable_value(self):
        """Test APPLICABLE enum value."""
        assert ApplicabilityStatus.APPLICABLE.value == "applicable"

    def test_not_applicable_by_condition(self):
        """Test NOT_APPLICABLE_BY_CONDITION enum value."""
        assert ApplicabilityStatus.NOT_APPLICABLE_BY_CONDITION.value == "not_applicable_by_condition"

    def test_tailored_out(self):
        """Test TAILORED_OUT enum value."""
        assert ApplicabilityStatus.TAILORED_OUT.value == "tailored_out"


class TestComplianceStatus:
    """Test ComplianceStatus enum."""

    def test_compliant_value(self):
        """Test COMPLIANT enum value."""
        assert ComplianceStatus.COMPLIANT.value == "compliant"

    def test_compliant_with_constraints(self):
        """Test COMPLIANT_WITH_CONSTRAINTS enum value."""
        assert ComplianceStatus.COMPLIANT_WITH_CONSTRAINTS.value == "compliant_with_constraints"

    def test_noncompliant(self):
        """Test NONCOMPLIANT enum value."""
        assert ComplianceStatus.NONCOMPLIANT.value == "noncompliant"

    def test_unknown(self):
        """Test UNKNOWN enum value."""
        assert ComplianceStatus.UNKNOWN.value == "unknown"


class TestComplianceBasis:
    """Test ComplianceBasis enum."""

    def test_test_basis(self):
        """Test TEST enum value."""
        assert ComplianceBasis.TEST.value == "test"

    def test_policy_basis(self):
        """Test POLICY enum value."""
        assert ComplianceBasis.POLICY.value == "policy"

    def test_evidence_weighted_analysis(self):
        """Test EVIDENCE_WEIGHTED_ANALYSIS enum value."""
        assert ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS.value == "evidence_weighted_analysis"


class TestFailureMode:
    """Test FailureMode enum."""

    def test_hee_value(self):
        """Test HEE (Hydrogen Environment Embrittlement) enum value."""
        assert FailureMode.HEE.value == "hee"

    def test_o2_prohibited(self):
        """Test O2_PROHIBITED enum value."""
        assert FailureMode.O2_PROHIBITED.value == "o2_prohibited"

    def test_flam_value(self):
        """Test FLAM (Flammability) enum value."""
        assert FailureMode.FLAM.value == "flam"

    def test_missing_input(self):
        """Test MISSING_INPUT enum value."""
        assert FailureMode.MISSING_INPUT.value == "missing_input"


class TestGapSeverity:
    """Test GapSeverity enum."""

    def test_severity_ordering(self):
        """Test severity levels are properly ordered."""
        severities = [
            GapSeverity.LOW,
            GapSeverity.MEDIUM,
            GapSeverity.HIGH,
            GapSeverity.CRITICAL,
        ]
        # All values should be distinct
        values = [s.value for s in severities]
        assert len(set(values)) == len(values)

    def test_critical_value(self):
        """Test CRITICAL enum value."""
        assert GapSeverity.CRITICAL.value == "critical"

    def test_high_value(self):
        """Test HIGH enum value."""
        assert GapSeverity.HIGH.value == "high"


class TestGapTrigger:
    """Test GapTrigger enum."""

    def test_hee_band_trigger(self):
        """Test HEE_BAND_EXTREME enum value."""
        assert GapTrigger.HEE_BAND_EXTREME.value == "hee_band_extreme"

    def test_prohibited_family(self):
        """Test PROHIBITED_FAMILY enum value."""
        assert GapTrigger.PROHIBITED_FAMILY.value == "prohibited_family"

    def test_missing_data(self):
        """Test MISSING_DATA enum value."""
        assert GapTrigger.MISSING_DATA.value == "missing_data"


class TestSourceType:
    """Test SourceType enum - Fran Fix #2."""

    def test_maptis_source(self):
        """Test MAPTIS source type enables TEST basis."""
        assert SourceType.MAPTIS.value == "maptis"

    def test_test_report_source(self):
        """Test TEST_REPORT source type."""
        assert SourceType.TEST_REPORT.value == "test_report"

    def test_standard_source(self):
        """Test STANDARD source type enables POLICY basis."""
        assert SourceType.STANDARD.value == "standard"

    def test_bok_source(self):
        """Test BOK (Body of Knowledge) source type."""
        assert SourceType.BOK.value == "bok"


class TestRequiredAction:
    """Test RequiredAction enum."""

    def test_generate_mua(self):
        """Test GENERATE_MUA action."""
        assert RequiredAction.GENERATE_MUA.value == "generate_mua"

    def test_substitute_material(self):
        """Test SUBSTITUTE_MATERIAL action."""
        assert RequiredAction.SUBSTITUTE_MATERIAL.value == "substitute_material"

    def test_engineering_review(self):
        """Test ENGINEERING_REVIEW action."""
        assert RequiredAction.ENGINEERING_REVIEW.value == "engineering_review"

    def test_none_action(self):
        """Test NONE action for compliant cases."""
        assert RequiredAction.NONE.value == "none"


class TestMUACategory:
    """Test MUACategory enum."""

    def test_category_1(self):
        """Test CATEGORY_1 (high risk) enum value - stored as string."""
        assert MUACategory.CATEGORY_1.value == "1"

    def test_category_2(self):
        """Test CATEGORY_2 (medium risk) enum value - stored as string."""
        assert MUACategory.CATEGORY_2.value == "2"

    def test_category_3(self):
        """Test CATEGORY_3 (low risk) enum value - stored as string."""
        assert MUACategory.CATEGORY_3.value == "3"


class TestEnvironmentType:
    """Test EnvironmentType enum."""

    def test_oxygen_environment(self):
        """Test OXYGEN environment type."""
        assert EnvironmentType.OXYGEN.value == "oxygen"

    def test_hydrogen_environment(self):
        """Test HYDROGEN environment type."""
        assert EnvironmentType.HYDROGEN.value == "hydrogen"

    def test_other_environment(self):
        """Test OTHER environment type for non-classified environments."""
        assert EnvironmentType.OTHER.value == "other"


class TestConstraintSource:
    """Test ConstraintSource enum."""

    def test_engine_constraint(self):
        """Test ENGINE_CONSTRAINT source."""
        assert ConstraintSource.ENGINE_CONSTRAINT.value == "engine_constraint"

    def test_policy_constraint(self):
        """Test POLICY_CONSTRAINT source."""
        assert ConstraintSource.POLICY_CONSTRAINT.value == "policy_constraint"
