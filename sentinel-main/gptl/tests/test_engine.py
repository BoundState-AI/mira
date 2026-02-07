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
GPTL Engine Integration Tests
=============================

Tests for the main GPTLEngine orchestrator.
Updated to match actual GPTL v4.1 implementation.
"""

import pytest

from gptl.engine import (
    PipelineResult,
    PipelineStageResult,
)


class TestPipelineStageResult:
    """Tests for PipelineStageResult."""

    def test_stage_result_success(self):
        """Test successful stage result."""
        stage = PipelineStageResult(
            stage="L2_intent_framing",
            success=True,
            duration_ms=150,
            output={"intent": "material_selection"},
        )
        assert stage.success is True
        assert stage.error is None

    def test_stage_result_failure(self):
        """Test failed stage result."""
        stage = PipelineStageResult(
            stage="L3_negative_selection",
            success=False,
            duration_ms=50,
            output=None,
            error="Connection timeout",
        )
        assert stage.success is False
        assert stage.error == "Connection timeout"

    def test_stage_has_required_fields(self):
        """Test stage has required fields."""
        stage = PipelineStageResult(
            stage="L5_synthesis",
            success=True,
            duration_ms=200,
            output={"answer": "test"},
        )
        assert hasattr(stage, "stage")
        assert hasattr(stage, "success")
        assert hasattr(stage, "duration_ms")
        assert hasattr(stage, "output")


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_pipeline_result_structure(self):
        """Test PipelineResult can be created."""
        # Create a minimal mock response
        from gptl.schema import (
            GPTLResponse,
            IntelligenceOutput,
            ViolationReport,
            GPTLMetrics,
            AuditTrail,
        )

        # Create minimal components for a valid GPTLResponse
        # This tests the structure exists, not the engine integration
        result = PipelineResult(
            response=None,  # Would be GPTLResponse in real usage
            stages=[],
            total_duration_ms=0,
        )

        assert hasattr(result, "response")
        assert hasattr(result, "stages")
        assert hasattr(result, "total_duration_ms")

    def test_pipeline_result_with_stages(self):
        """Test PipelineResult with stages."""
        stages = [
            PipelineStageResult(stage="L2", success=True, duration_ms=100, output={}),
            PipelineStageResult(stage="L3", success=True, duration_ms=150, output={}),
        ]

        result = PipelineResult(
            response=None,
            stages=stages,
            total_duration_ms=250,
        )

        assert len(result.stages) == 2
        assert result.total_duration_ms == 250


# Full engine integration tests are skipped until engine.py is complete
# The engine requires many components working together which is complex to mock

@pytest.mark.skip(reason="Engine integration requires complete module implementation")
class TestGPTLEngine:
    """Placeholder for GPTLEngine integration tests."""
    pass
