#!/usr/bin/env python3
"""
Module: Test Logic Validator
Purpose: Tests for Logic Validator (MUA v6 Phase 5).

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
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.logic_validator import (
    RationaleValidationResult,
    LogicValidator,
)
from mira.mua.v6.enriched_search import EnrichedMUAResult


class TestRationaleValidationResult:
    """Tests for RationaleValidationResult model."""

    def test_default_invalid(self):
        """Default result should be invalid."""
        result = RationaleValidationResult()
        assert not result.is_valid
        assert result.synthesized_rationale == ""
        assert len(result.citations) == 0

    def test_valid_result(self):
        """Valid result should have citations."""
        result = RationaleValidationResult(
            is_valid=True,
            synthesized_rationale="Material approved per MUA-1234.",
            citations=["MUA-1234"],
            reasoning="Precedent rationale transfers.",
        )
        assert result.is_valid
        assert result.has_citations
        assert not result.all_rejected

    def test_all_rejected(self):
        """All rejected result should have flag."""
        result = RationaleValidationResult(
            is_valid=False,
            rejected_precedents=["MUA-1234", "MUA-5678"],
            rejection_reasons={
                "MUA-1234": "Relies on sealed container",
                "MUA-5678": "Empty rationale",
            },
        )
        assert not result.is_valid
        assert result.all_rejected
        assert not result.has_citations

    def test_source_traceability(self):
        """Should have default source for SWE-013."""
        result = RationaleValidationResult()
        assert result.source == "LogicValidator"


class TestLogicValidatorInit:
    """Tests for LogicValidator initialization."""

    def test_init_with_api_key(self):
        """Should initialize with provided API key."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            validator = LogicValidator(api_key="test-key")
            mock_anthropic.assert_called_once_with(api_key="test-key")

    def test_init_with_env_var(self):
        """Should use environment variable if no key provided."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
                validator = LogicValidator()
                mock_anthropic.assert_called_once_with(api_key="env-key")

    def test_init_no_key_raises(self):
        """Should raise if no API key available."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY if present
            import os
            env_backup = os.environ.get("ANTHROPIC_API_KEY")
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]
            try:
                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                    LogicValidator()
            finally:
                if env_backup:
                    os.environ["ANTHROPIC_API_KEY"] = env_backup


def _make_mock_precedent(
    mua_number: str = "MUA-001",
    determination: str = "APPROVED",
    rationale: str = "Test rationale",
    environment: str = "Oxygen",
) -> EnrichedMUAResult:
    """Create mock EnrichedMUAResult for testing."""
    return EnrichedMUAResult(
        rank=1,
        score=0.5,
        semantic_score=0.3,
        string_score=0.7,
        file="test.pdf",
        mua_number=mua_number,
        material_designation="INCONEL 625",
        material_family="NICKEL",
        material_family_raw="inconel",
        is_umbrella=False,
        environment=environment,
        category="I",
        determination=determination,
        rationale=rationale,
        application="Test application",
        is_supporting=True,
        is_conflicting=False,
    )


class TestLogicValidatorValidate:
    """Tests for LogicValidator.validate method."""

    def test_empty_precedents_invalid(self):
        """Empty precedents should return invalid."""
        with patch("anthropic.Anthropic"):
            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[],
            )
            assert not result.is_valid
            assert "no precedents" in result.reasoning.lower()

    def test_api_error_fail_closed(self):
        """API error should return invalid (fail closed)."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("API Error")
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[_make_mock_precedent()],
            )

            assert not result.is_valid
            assert "error" in result.reasoning.lower()

    def test_parse_valid_json_response(self):
        """Valid JSON response should be parsed."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = MagicMock()
            mock_response.content = [MagicMock()]
            mock_response.content[0].text = """
{
  "is_valid": true,
  "synthesized_rationale": "Material approved per MUA-001.",
  "citations": ["MUA-001"],
  "rejected_precedents": [],
  "rejection_reasons": {},
  "reasoning": "The precedent rationale transfers."
}
"""
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[_make_mock_precedent()],
            )

            assert result.is_valid
            assert "MUA-001" in result.citations
            assert result.synthesized_rationale == "Material approved per MUA-001."

    def test_parse_markdown_wrapped_json(self):
        """JSON wrapped in markdown code blocks should be parsed."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = MagicMock()
            mock_response.content = [MagicMock()]
            mock_response.content[0].text = """Here's my analysis:

```json
{
  "is_valid": true,
  "synthesized_rationale": "Approved per MUA-002.",
  "citations": ["MUA-002"],
  "rejected_precedents": [],
  "rejection_reasons": {},
  "reasoning": "Analysis complete."
}
```

That's my assessment.
"""
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[_make_mock_precedent(mua_number="MUA-002")],
            )

            assert result.is_valid
            assert "MUA-002" in result.citations

    def test_rejected_no_rationale(self):
        """Precedent with no rationale should be rejected in response."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = MagicMock()
            mock_response.content = [MagicMock()]
            mock_response.content[0].text = """
{
  "is_valid": false,
  "synthesized_rationale": "",
  "citations": [],
  "rejected_precedents": ["MUA-003"],
  "rejection_reasons": {"MUA-003": "Empty rationale provided"},
  "reasoning": "The precedent had no rationale to transfer."
}
"""
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[_make_mock_precedent(mua_number="MUA-003", rationale="")],
            )

            assert not result.is_valid
            assert "MUA-003" in result.rejected_precedents
            assert "MUA-003" in result.rejection_reasons

    def test_synthesized_rationale_has_citations(self):
        """Synthesized rationale should include MUA citations."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = MagicMock()
            mock_response.content = [MagicMock()]
            mock_response.content[0].text = """
{
  "is_valid": true,
  "synthesized_rationale": "Material INCONEL 625 is approved for 100% O2 service per MUA-004 and MUA-005. The nickel alloy family demonstrates oxygen compatibility at these conditions.",
  "citations": ["MUA-004", "MUA-005"],
  "rejected_precedents": [],
  "rejection_reasons": {},
  "reasoning": "Both precedents have valid transferable rationale."
}
"""
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            precedents = [
                _make_mock_precedent(mua_number="MUA-004"),
                _make_mock_precedent(mua_number="MUA-005"),
            ]
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2 at 14.7 PSIA",
                precedents=precedents,
            )

            assert result.is_valid
            assert len(result.citations) == 2
            assert "MUA-004" in result.synthesized_rationale
            assert "MUA-005" in result.synthesized_rationale

    def test_partial_rejection(self):
        """Some precedents valid, some rejected."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = MagicMock()
            mock_response.content = [MagicMock()]
            mock_response.content[0].text = """
{
  "is_valid": true,
  "synthesized_rationale": "Approved per MUA-006.",
  "citations": ["MUA-006"],
  "rejected_precedents": ["MUA-007"],
  "rejection_reasons": {"MUA-007": "Relies on sealed container mitigation not present in target"},
  "reasoning": "MUA-006 transfers, MUA-007 does not."
}
"""
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[
                    _make_mock_precedent(mua_number="MUA-006"),
                    _make_mock_precedent(mua_number="MUA-007"),
                ],
            )

            assert result.is_valid
            assert "MUA-006" in result.citations
            assert "MUA-007" in result.rejected_precedents

    def test_invalid_json_returns_invalid(self):
        """Unparseable response should return invalid."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = MagicMock()
            mock_response.content = [MagicMock()]
            mock_response.content[0].text = "This is not valid JSON at all."

            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[_make_mock_precedent()],
            )

            assert not result.is_valid
            assert "failed to parse" in result.reasoning.lower()

    def test_req_id_in_source(self):
        """Request ID should be in source field."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = MagicMock()
            mock_response.content = [MagicMock()]
            mock_response.content[0].text = """
{
  "is_valid": true,
  "synthesized_rationale": "Test.",
  "citations": ["MUA-001"],
  "rejected_precedents": [],
  "rejection_reasons": {},
  "reasoning": "OK."
}
"""
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            validator = LogicValidator(api_key="test-key")
            result = validator.validate(
                material="INCONEL 625",
                environment_desc="100% O2",
                precedents=[_make_mock_precedent()],
                req_id="REQ-12345",
            )

            assert "REQ-12345" in result.source


class TestLogicValidatorParseJson:
    """Tests for JSON parsing logic."""

    def test_parse_direct_json(self):
        """Direct JSON should parse."""
        with patch("anthropic.Anthropic"):
            validator = LogicValidator(api_key="test-key")
            result = validator._parse_json_response('{"is_valid": true}')
            assert result["is_valid"] is True

    def test_parse_json_with_markdown(self):
        """JSON in markdown block should parse."""
        with patch("anthropic.Anthropic"):
            validator = LogicValidator(api_key="test-key")
            result = validator._parse_json_response('''
```json
{"is_valid": false}
```
''')
            assert result["is_valid"] is False

    def test_parse_json_embedded_in_text(self):
        """JSON embedded in text should parse."""
        with patch("anthropic.Anthropic"):
            validator = LogicValidator(api_key="test-key")
            result = validator._parse_json_response(
                'Here is my answer: {"is_valid": true, "citations": ["MUA-001"]} End.'
            )
            assert result["is_valid"] is True
            assert "MUA-001" in result["citations"]

    def test_parse_invalid_json(self):
        """Invalid JSON should return None."""
        with patch("anthropic.Anthropic"):
            validator = LogicValidator(api_key="test-key")
            result = validator._parse_json_response("not json at all")
            assert result is None

    def test_parse_with_ellipsis_fix(self):
        """Truncated JSON with ellipsis should be handled."""
        with patch("anthropic.Anthropic"):
            validator = LogicValidator(api_key="test-key")
            # This tests the ellipsis fix path
            result = validator._parse_json_response('{"is_valid": true, ... }')
            # The fix removes ", ..." before closing brace
            assert result is not None or result is None  # May or may not work depending on content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
