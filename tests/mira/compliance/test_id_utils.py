#!/usr/bin/env python3
"""
Module: Test ID Utilities
Purpose: Test coverage for hash-based ID generation (Fran Fix #6)

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

from mira.compliance.id_utils import (
    compute_gap_id,
    compute_constraint_id,
    compute_mpr_determination_id,
    compute_evidence_hash,
    compute_document_fingerprint,
    compute_prompt_hash,
    compute_inputs_hash,
)
from mira.compliance.models.enums import FailureMode, GapTrigger


class TestComputeGapId:
    """Test compute_gap_id function - Fran Fix #6."""

    def test_deterministic_output(self):
        """Same inputs should produce same ID - critical for reproducibility."""
        id1 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_O2_001",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_EXTREME,
            policy_rule=None,
        )
        id2 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_O2_001",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_EXTREME,
            policy_rule=None,
        )
        assert id1 == id2, "Gap IDs must be deterministic"

    def test_id_length(self):
        """ID should be 12 characters (truncated SHA-256)."""
        gap_id = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_SEVERE,
        )
        assert len(gap_id) == 12, "Gap ID should be 12 characters"

    def test_different_materials_produce_different_ids(self):
        """Different materials should produce different IDs."""
        id1 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_EXTREME,
        )
        id2 = compute_gap_id(
            material_id="MAPTIS:99999",
            environment_id="ENV_001",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_EXTREME,
        )
        assert id1 != id2, "Different materials must produce different IDs"

    def test_different_environments_produce_different_ids(self):
        """Different environments should produce different IDs."""
        id1 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_O2_001",
            gap_type=FailureMode.O2_PROHIBITED,
            trigger=GapTrigger.PROHIBITED_FAMILY,
        )
        id2 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_H2_001",
            gap_type=FailureMode.O2_PROHIBITED,
            trigger=GapTrigger.PROHIBITED_FAMILY,
        )
        assert id1 != id2, "Different environments must produce different IDs"

    def test_different_triggers_produce_different_ids(self):
        """Different triggers should produce different IDs."""
        id1 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_EXTREME,
        )
        id2 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.HEE_BAND_SEVERE,
        )
        assert id1 != id2, "Different triggers must produce different IDs"

    def test_policy_rule_affects_id(self):
        """Policy rule should affect the ID."""
        id1 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
            gap_type=FailureMode.FLAM,
            trigger=GapTrigger.RESTRICTED_POLICY,
            policy_rule="O2 family gate: titanium",
        )
        id2 = compute_gap_id(
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
            gap_type=FailureMode.FLAM,
            trigger=GapTrigger.RESTRICTED_POLICY,
            policy_rule=None,
        )
        assert id1 != id2, "Policy rule should affect the ID"


class TestComputeConstraintId:
    """Test compute_constraint_id function - Fran Fix #6."""

    def test_deterministic_output(self):
        """Same inputs should produce same ID."""
        id1 = compute_constraint_id(
            material_id="MAPTIS:12345",
            parameter="pressure",
            limit_type="max",
            limit_value="5000 psia",
        )
        id2 = compute_constraint_id(
            material_id="MAPTIS:12345",
            parameter="pressure",
            limit_type="max",
            limit_value="5000 psia",
        )
        assert id1 == id2, "Constraint IDs must be deterministic"

    def test_id_length(self):
        """ID should be 12 characters."""
        constraint_id = compute_constraint_id(
            material_id="MAPTIS:12345",
            parameter="temperature",
            limit_type="min",
            limit_value="-423 F",
        )
        assert len(constraint_id) == 12

    def test_different_parameters_produce_different_ids(self):
        """Different parameters should produce different IDs."""
        id1 = compute_constraint_id(
            material_id="MAPTIS:12345",
            parameter="pressure",
            limit_type="max",
            limit_value="5000 psia",
        )
        id2 = compute_constraint_id(
            material_id="MAPTIS:12345",
            parameter="temperature",
            limit_type="max",
            limit_value="5000 psia",
        )
        assert id1 != id2


class TestComputeMPRDeterminationId:
    """Test compute_mpr_determination_id function."""

    def test_deterministic_output(self):
        """Same inputs should produce same ID."""
        id1 = compute_mpr_determination_id(
            mpr_number=1,
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
        )
        id2 = compute_mpr_determination_id(
            mpr_number=1,
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
        )
        assert id1 == id2

    def test_different_mprs_produce_different_ids(self):
        """Different MPR numbers should produce different IDs."""
        id1 = compute_mpr_determination_id(
            mpr_number=1,
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
        )
        id2 = compute_mpr_determination_id(
            mpr_number=2,
            material_id="MAPTIS:12345",
            environment_id="ENV_001",
        )
        assert id1 != id2


class TestComputeEvidenceHash:
    """Test compute_evidence_hash function."""

    def test_full_hash_length(self):
        """Evidence hash should be full SHA-256 (64 chars)."""
        hash_value = compute_evidence_hash("Test evidence content")
        assert len(hash_value) == 64

    def test_deterministic_output(self):
        """Same content should produce same hash."""
        content = "Material XYZ tested at 5000 psia GH2, results OK"
        hash1 = compute_evidence_hash(content)
        hash2 = compute_evidence_hash(content)
        assert hash1 == hash2

    def test_different_content_produces_different_hash(self):
        """Different content should produce different hash."""
        hash1 = compute_evidence_hash("Evidence 1")
        hash2 = compute_evidence_hash("Evidence 2")
        assert hash1 != hash2


class TestComputeDocumentFingerprint:
    """Test compute_document_fingerprint function."""

    def test_bytes_input(self):
        """Should accept bytes input."""
        content = b"PDF document bytes here"
        fingerprint = compute_document_fingerprint(content)
        assert len(fingerprint) == 64

    def test_deterministic_output(self):
        """Same bytes should produce same fingerprint."""
        content = b"Some document content"
        fp1 = compute_document_fingerprint(content)
        fp2 = compute_document_fingerprint(content)
        assert fp1 == fp2


class TestComputePromptHash:
    """Test compute_prompt_hash function - Fran Fix #7."""

    def test_full_hash_length(self):
        """Prompt hash should be full SHA-256."""
        hash_value = compute_prompt_hash("Generate MUA for material XYZ")
        assert len(hash_value) == 64

    def test_deterministic_output(self):
        """Same prompt should produce same hash."""
        prompt = "Please generate an MUA draft for this material"
        hash1 = compute_prompt_hash(prompt)
        hash2 = compute_prompt_hash(prompt)
        assert hash1 == hash2


class TestComputeInputsHash:
    """Test compute_inputs_hash function - Fran Fix #7."""

    def test_deterministic_output(self):
        """Same inputs should produce same hash."""
        inputs = {
            "material_id": "MAPTIS:12345",
            "environment_id": "ENV_001",
            "category": 2,
        }
        hash1 = compute_inputs_hash(inputs)
        hash2 = compute_inputs_hash(inputs)
        assert hash1 == hash2

    def test_key_order_does_not_affect_hash(self):
        """Different key ordering should produce same hash (sorted internally)."""
        inputs1 = {"a": 1, "b": 2, "c": 3}
        inputs2 = {"c": 3, "a": 1, "b": 2}
        hash1 = compute_inputs_hash(inputs1)
        hash2 = compute_inputs_hash(inputs2)
        assert hash1 == hash2, "Key order should not affect hash"

    def test_nested_inputs(self):
        """Should handle nested dictionaries."""
        inputs = {
            "material": {"id": "MAPTIS:12345", "name": "SS 316"},
            "gaps": ["gap1", "gap2"],
        }
        hash_value = compute_inputs_hash(inputs)
        assert len(hash_value) == 64
