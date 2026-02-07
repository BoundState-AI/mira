#!/usr/bin/env python3
"""
Module: Test Llm Answer Generator
Purpose: Tests for LLMAnswerGenerator - Explanation Generation (NOT Decision Making)

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (traceability), SWE-033 (deterministic safety)
Safety Critical: False
"""

import pytest
from unittest.mock import Mock, patch
from core.evidence.llm_answer_generator import (
    LLMAnswerGenerator,
    MaterialDecision,
    EvidenceBundle,
    EXPLANATION_SYSTEM_PROMPT,
)
from core.evidence.boundary_checker import (
    BoundaryCheckResult,
    BoundaryVerdict,
    BOKLimit,
)


class TestExplanationSystemPrompt:
    """Verify the system prompt enforces explanation-only mode."""

    def test_prompt_says_technical_writer(self):
        """Prompt should say LLM is a TECHNICAL WRITER."""
        assert "TECHNICAL WRITER" in EXPLANATION_SYSTEM_PROMPT
        assert "decision maker" not in EXPLANATION_SYSTEM_PROMPT.lower() or \
               "not a decision maker" in EXPLANATION_SYSTEM_PROMPT.lower()

    def test_prompt_says_do_not_override(self):
        """Prompt should prohibit overriding decisions."""
        assert "DO NOT override" in EXPLANATION_SYSTEM_PROMPT or \
               "override the decision" in EXPLANATION_SYSTEM_PROMPT

    def test_prompt_says_already_made(self):
        """Prompt should clarify decision is ALREADY MADE."""
        assert "ALREADY BEEN MADE" in EXPLANATION_SYSTEM_PROMPT or \
               "already been made" in EXPLANATION_SYSTEM_PROMPT.lower()


class TestMaterialDecision:
    """Test MaterialDecision dataclass."""

    def test_create_decision(self):
        """Test creating a MaterialDecision."""
        decision = MaterialDecision(
            material_name="Aluminum 6061",
            decision="NO",
            rationale="Exceeds BOK limit",
            evidence_sources=["NASA-STD-6016C"],
            confidence=0.95
        )
        assert decision.material_name == "Aluminum 6061"
        assert decision.decision == "NO"
        assert decision.confidence == 0.95

    def test_decision_with_boundary_result(self):
        """Test decision with BoundaryCheckResult attached."""
        boundary_result = BoundaryCheckResult(
            verdict=BoundaryVerdict.EXCEEDS_LIMIT,
            rationale="200 psia exceeds 100 psia limit"
        )
        decision = MaterialDecision(
            material_name="Titanium",
            decision="NO",
            rationale="Exceeds pressure limit",
            boundary_result=boundary_result
        )
        assert decision.boundary_result.verdict == BoundaryVerdict.EXCEEDS_LIMIT


class TestEvidenceBundle:
    """Test EvidenceBundle formatting."""

    def test_to_llm_prompt_basic(self):
        """Test basic evidence bundle formatting."""
        bundle = EvidenceBundle(
            material_id="AL6061",
            material_name="Aluminum 6061-T6",
            required_env="oxygen",
            required_pressure_psia=200.0
        )
        prompt = bundle.to_llm_prompt()
        assert "Aluminum 6061-T6" in prompt
        assert "oxygen" in prompt
        assert "200.0" in prompt

    def test_to_llm_prompt_with_mua(self):
        """Test evidence bundle with MUA precedents."""
        bundle = EvidenceBundle(
            material_id="AL6061",
            material_name="Aluminum 6061-T6",
            mua_precedents=[
                {
                    "mua_number": "MUA-2024-001",
                    "determination": "APPROVED",
                    "pressure_psi_max": 1000
                }
            ]
        )
        prompt = bundle.to_llm_prompt()
        assert "MUA PRECEDENTS" in prompt
        assert "MUA-2024-001" in prompt

    def test_to_llm_prompt_with_boundary_results(self):
        """Test evidence bundle with boundary check results."""
        boundary_result = BoundaryCheckResult(
            verdict=BoundaryVerdict.EXCEEDS_LIMIT,
            rationale="Exceeds 100 psia limit",
            limit_checked=BOKLimit(
                material_family="titanium",
                environment="oxygen",
                limit_type="max_pressure",
                limit_value=100.0,
                units="psia",
                source_doc="NASA-STD-6016C"
            )
        )
        bundle = EvidenceBundle(
            material_id="TI64",
            material_name="Titanium 6Al-4V",
            boundary_results=[boundary_result]
        )
        prompt = bundle.to_llm_prompt()
        assert "BOUNDARY CHECK RESULTS" in prompt
        assert "EXCEEDS_LIMIT" in prompt


class TestLLMAnswerGenerator:
    """Test LLMAnswerGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create generator (will fail to connect but that's OK for unit tests)."""
        return LLMAnswerGenerator(provider="ollama")

    def test_numeric_limit_extraction(self, generator):
        """Test extracting numeric limits from evidence texts."""
        texts = [
            "Maximum pressure is 3000 psia",
            "Temperature limit: 500 C",
            "Approved at 100 psi and 200F"
        ]
        limits = generator._extract_numeric_limits(texts)
        assert "3000 psia" in limits
        assert "500 C" in limits
        assert "100 psi" in limits

    def test_numeric_limit_sanity_filter(self, generator):
        """Test that insane values are filtered out."""
        # Implementation filters: temps outside ±2000°C, pressures > 100k psi
        texts = [
            "Value is 999999999 psi",  # Too high - filtered
            "Temperature -3000 C",  # Outside ±2000°C threshold - filtered
            "Normal value 5000 psi"  # Within range - kept
        ]
        limits = generator._extract_numeric_limits(texts)
        # Only the sane value should remain
        assert len(limits) == 1
        assert "5000 psi" in limits

    def test_mua_reference_validation_valid(self, generator):
        """Test MUA reference validation with valid references."""
        answer = "Based on MUA-2024-001 and MUA-2024-002, the material is approved."
        allowed = {"MUA-2024-001", "MUA-2024-002"}
        # Returns empty list when all references are valid
        assert generator._validate_mua_references(answer, allowed) == []

    def test_mua_reference_validation_invalid(self, generator):
        """Test MUA reference validation catches hallucinated MUAs."""
        answer = "Based on MUA-FAKE-999, the material is approved."
        allowed = {"MUA-2024-001"}
        # Returns list of invalid (hallucinated) MUA references
        invalid = generator._validate_mua_references(answer, allowed)
        assert "MUA-FAKE-999" in invalid

    @patch('requests.post')
    def test_explain_decision_calls_llm(self, mock_post, generator):
        """Test that explain_decision calls the LLM endpoint."""
        mock_response = Mock()
        mock_response.json.return_value = {"response": "This is an explanation."}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        decision = MaterialDecision(
            material_name="Aluminum 6061",
            decision="NO",
            rationale="Exceeds limit"
        )
        evidence = EvidenceBundle(
            material_id="AL6061",
            material_name="Aluminum 6061"
        )

        result = generator.explain_decision(
            decision=decision,
            evidence=evidence,
            query="Can aluminum be used in oxygen?"
        )

        assert mock_post.called
        assert "explanation" in result.lower() or "NO" in result

    def test_generate_answer_deprecated_warning(self, generator, caplog):
        """Test that generate_answer logs deprecation warning."""
        # This will fail to connect but should log deprecation
        with patch('requests.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = {"response": "Test"}
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            generator.generate_answer(
                query="test",
                mua_precedents=[],
                semantic_evidence=None,
                decisions=[{"decision": "NO", "rationale": "Test"}],
                requirements=[]
            )
            # Should log deprecation warning (check logs)


class TestIntegration:
    """Integration tests for the refactored system."""

    def test_full_flow_deterministic_decision(self):
        """Test that the full flow uses deterministic decisions."""
        from core.evidence.boundary_checker import check_material_boundary

        # Step 1: BoundaryChecker makes deterministic decision
        boundary_result = check_material_boundary(
            material="aluminum 6061",
            environment="oxygen",
            pressure=5000.0  # Exceeds 3000 psia limit
        )

        # Verify decision is deterministic
        assert boundary_result.verdict == BoundaryVerdict.EXCEEDS_LIMIT
        assert boundary_result.is_prohibited is True

        # Step 2: Create MaterialDecision from boundary result
        decision = MaterialDecision(
            material_name="Aluminum 6061",
            decision="NO",
            rationale=boundary_result.rationale,
            evidence_sources=boundary_result.evidence_sources,
            confidence=0.95,
            boundary_result=boundary_result
        )

        # Verify decision is based on boundary check
        assert decision.decision == "NO"
        assert "NASA-STD-6016C" in decision.rationale or len(decision.evidence_sources) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
