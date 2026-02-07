#!/usr/bin/env python3
"""
Module: Test Miul Session
Purpose: Tests for MIUL session management.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import pytest
from datetime import datetime

from mira.miul.session import (
    SessionState,
    PartStatus,
    ResolutionType,
    UseEnvironmentInput,
    PartResolution,
    MIULSession,
)


class TestSessionState:
    """Tests for SessionState enum."""

    def test_all_states_defined(self):
        """Verify all workflow states are defined."""
        states = {s.value for s in SessionState}
        expected = {
            "setup",
            "uploading",
            "extracting",
            "enriching",
            "review",
            "complete",
            "error",
        }
        assert states == expected


class TestPartStatus:
    """Tests for PartStatus enum."""

    def test_all_statuses_defined(self):
        """Verify all part statuses are defined."""
        statuses = {s.value for s in PartStatus}
        expected = {
            "ok",
            "needs_review",
            "needs_action",
            "resolved",
            "mua_required",
            "pending_test",
        }
        assert statuses == expected


class TestResolutionType:
    """Tests for ResolutionType enum."""

    def test_all_types_defined(self):
        """Verify all resolution types are defined."""
        types = {t.value for t in ResolutionType}
        expected = {
            "technical_rationale",
            "new_mua_requested",
            "existing_mua_linked",
            "testing_requested",
            "substitution_needed",
            "engineering_review",
        }
        assert types == expected


class TestUseEnvironmentInput:
    """Tests for UseEnvironmentInput model."""

    def test_sls_defaults(self):
        """Test SLS default environment values."""
        env = UseEnvironmentInput()
        assert env.use_sls_default is True
        assert env.min_pressure_psia == 0.0
        assert env.max_pressure_psia == 14.7
        assert env.min_temperature_f == 0.0
        assert env.max_temperature_f == 120.0
        assert "Air" in env.media
        assert "Vacuum" in env.media
        assert env.o2_percent == 20.9

    def test_custom_environment(self):
        """Test custom environment values."""
        env = UseEnvironmentInput(
            use_sls_default=False,
            min_pressure_psia=0.0,
            max_pressure_psia=3000.0,
            min_temperature_f=-100.0,
            max_temperature_f=500.0,
            media=["GOX", "GH2"],
            o2_percent=100.0,
        )
        assert env.use_sls_default is False
        assert env.max_pressure_psia == 3000.0
        assert env.o2_percent == 100.0
        assert "GOX" in env.media


class TestPartResolution:
    """Tests for PartResolution model."""

    def test_technical_rationale_resolution(self):
        """Test creating technical rationale resolution."""
        resolution = PartResolution(
            part_index=3,
            rating_type="TVS",
            resolution_type=ResolutionType.TECHNICAL_RATIONALE,
            rationale_code="403",
            rationale_text="VCM within limits, small area",
            confirmed=True,
        )
        assert resolution.part_index == 3
        assert resolution.rating_type == "TVS"
        assert resolution.rationale_code == "403"
        assert resolution.confirmed is True

    def test_new_mua_requested_resolution(self):
        """Test creating new MUA request resolution."""
        resolution = PartResolution(
            part_index=5,
            rating_type="FLAM",
            resolution_type=ResolutionType.NEW_MUA_REQUESTED,
            notes="Material does not meet any technical rationale",
        )
        assert resolution.resolution_type == ResolutionType.NEW_MUA_REQUESTED
        assert resolution.mua_number is None

    def test_existing_mua_linked_resolution(self):
        """Test linking to existing MUA."""
        resolution = PartResolution(
            part_index=7,
            rating_type="TVS",
            resolution_type=ResolutionType.EXISTING_MUA_LINKED,
            mua_number="MUA-2024-0042",
            mua_category="I",
        )
        assert resolution.mua_number == "MUA-2024-0042"
        assert resolution.mua_category == "I"


class TestMIULSession:
    """Tests for MIULSession model."""

    def test_session_creation(self):
        """Test creating new session."""
        session = MIULSession(
            program="SLS Block 1B",
            end_item="Payload Bay Camera",
            miul_acronym="PBC",
        )
        assert session.program == "SLS Block 1B"
        assert session.end_item == "Payload Bay Camera"
        assert session.state == SessionState.SETUP
        assert session.session_id is not None
        assert len(session.session_id) > 0

    def test_session_with_custom_environment(self):
        """Test session with custom environment."""
        env = UseEnvironmentInput(
            use_sls_default=False,
            max_pressure_psia=3000.0,
            o2_percent=100.0,
        )
        session = MIULSession(
            program="Test",
            end_item="Unit",
            environment=env,
        )
        assert session.environment.max_pressure_psia == 3000.0

    def test_add_resolution(self):
        """Test adding resolution to session."""
        session = MIULSession(
            program="Test",
            end_item="Unit",
            parts_needs_review=3,
        )
        assert session.parts_resolved == 0

        resolution = PartResolution(
            part_index=1,
            rating_type="TVS",
            resolution_type=ResolutionType.TECHNICAL_RATIONALE,
            rationale_code="403",
            confirmed=True,
        )
        session.add_resolution(resolution)

        assert session.parts_resolved == 1
        assert len(session.resolutions) == 1
        assert session.resolutions[0].resolved_at is not None

    def test_get_resolution(self):
        """Test retrieving resolution for part/rating."""
        session = MIULSession(program="Test", end_item="Unit")

        # Add some resolutions
        session.add_resolution(
            PartResolution(
                part_index=1,
                rating_type="TVS",
                resolution_type=ResolutionType.TECHNICAL_RATIONALE,
                rationale_code="403",
                confirmed=True,
            )
        )
        session.add_resolution(
            PartResolution(
                part_index=1,
                rating_type="FLAM",
                resolution_type=ResolutionType.TECHNICAL_RATIONALE,
                rationale_code="104",
                confirmed=True,
            )
        )

        # Find specific resolution
        tvs_res = session.get_resolution(1, "TVS")
        assert tvs_res is not None
        assert tvs_res.rationale_code == "403"

        flam_res = session.get_resolution(1, "FLAM")
        assert flam_res is not None
        assert flam_res.rationale_code == "104"

        # Non-existent resolution
        missing = session.get_resolution(1, "SCC")
        assert missing is None

    def test_completion_percent_none_needed(self):
        """Test completion percentage when nothing needs attention."""
        session = MIULSession(
            program="Test",
            end_item="Unit",
            parts_needs_review=0,
            parts_needs_action=0,
        )
        assert session.completion_percent == 100.0

    def test_completion_percent_partial(self):
        """Test completion percentage with partial progress."""
        session = MIULSession(
            program="Test",
            end_item="Unit",
            parts_needs_review=6,
            parts_needs_action=4,
            parts_resolved=5,
        )
        # 5 resolved out of 10 needing attention = 50%
        assert session.completion_percent == 50.0

    def test_completion_percent_complete(self):
        """Test completion percentage when all resolved."""
        session = MIULSession(
            program="Test",
            end_item="Unit",
            parts_needs_review=6,
            parts_needs_action=4,
            parts_resolved=10,
        )
        assert session.completion_percent == 100.0

    def test_can_export_false_wrong_state(self):
        """Test can_export is False when not in REVIEW state."""
        session = MIULSession(
            program="Test",
            end_item="Unit",
            state=SessionState.SETUP,
            parts_resolved=10,
            parts_needs_review=10,
        )
        assert session.can_export is False

    def test_can_export_false_incomplete(self):
        """Test can_export is False when not all resolved."""
        session = MIULSession(
            program="Test",
            end_item="Unit",
            state=SessionState.REVIEW,
            parts_needs_review=10,
            parts_resolved=5,
        )
        assert session.can_export is False

    def test_can_export_true(self):
        """Test can_export is True when ready."""
        session = MIULSession(
            program="Test",
            end_item="Unit",
            state=SessionState.REVIEW,
            parts_needs_review=5,
            parts_needs_action=5,
            parts_resolved=10,
        )
        assert session.can_export is True

    def test_summary_property(self):
        """Test summary property returns correct data."""
        session = MIULSession(
            program="SLS",
            end_item="Camera",
            state=SessionState.REVIEW,
            total_parts=47,
            enriched_parts=38,
            parts_ok=30,
            parts_needs_review=5,
            parts_needs_action=3,
            parts_resolved=4,
        )
        summary = session.summary

        assert summary["program"] == "SLS"
        assert summary["end_item"] == "Camera"
        assert summary["state"] == "review"
        assert summary["total_parts"] == 47
        assert summary["parts_resolved"] == 4
        assert summary["completion_percent"] == 50.0  # 4/8

    def test_uploaded_files_tracking(self):
        """Test tracking uploaded files."""
        session = MIULSession(program="Test", end_item="Unit")
        assert len(session.uploaded_files) == 0

        session.uploaded_files.append("drawing.pdf")
        session.uploaded_files.append("bom.xlsx")

        assert len(session.uploaded_files) == 2
        assert "drawing.pdf" in session.uploaded_files
