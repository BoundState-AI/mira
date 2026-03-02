#!/usr/bin/env python3
"""
Tests for mira.utils.json_extract — robust JSON extraction from LLM output.
"""

import json
import pytest

from mira.utils.json_extract import (
    ExtractionError,
    extract_json,
    normalize_json_candidate,
    strip_code_fences,
)


# ── ExtractionError ────────────────────────────────────────────────────────


class TestExtractionError:
    def test_carries_diagnostic_and_snippet(self):
        err = ExtractionError("bad json", "raw text here")
        assert err.diagnostic == "bad json"
        assert err.raw_snippet == "raw text here"
        assert "bad json" in str(err)
        assert "raw text here" in str(err)

    def test_is_value_error(self):
        assert issubclass(ExtractionError, ValueError)


# ── strip_code_fences ──────────────────────────────────────────────────────


class TestStripCodeFences:
    def test_json_fence(self):
        text = '```json\n{"a": 1}\n```'
        assert strip_code_fences(text) == '{"a": 1}'

    def test_plain_fence(self):
        text = '```\n[1, 2, 3]\n```'
        assert strip_code_fences(text) == "[1, 2, 3]"

    def test_no_fence_returns_original(self):
        text = '{"a": 1}'
        assert strip_code_fences(text) is text

    def test_fence_with_surrounding_text(self):
        text = 'Here is the result:\n```json\n{"x": 2}\n```\nDone.'
        assert strip_code_fences(text) == '{"x": 2}'


# ── normalize_json_candidate ──────────────────────────────────────────────


class TestNormalizeJsonCandidate:
    def test_trailing_comma_object(self):
        assert normalize_json_candidate('{"a": 1,}') == '{"a": 1}'

    def test_trailing_comma_array(self):
        assert normalize_json_candidate("[1, 2, 3,]") == "[1, 2, 3]"

    def test_trailing_comma_nested(self):
        raw = '{"a": [1, 2,], "b": 3,}'
        result = normalize_json_candidate(raw)
        assert json.loads(result) == {"a": [1, 2], "b": 3}

    def test_no_trailing_comma_unchanged(self):
        text = '{"a": 1}'
        assert normalize_json_candidate(text) == text


# ── extract_json — clean inputs ───────────────────────────────────────────


class TestExtractJsonClean:
    def test_clean_object(self):
        data = extract_json('{"key": "value"}')
        assert data == {"key": "value"}

    def test_clean_array(self):
        data = extract_json("[1, 2, 3]", expect="array")
        assert data == [1, 2, 3]

    def test_whitespace_padded(self):
        data = extract_json('   \n {"a": 1}  \n ')
        assert data == {"a": 1}

    def test_returns_dict_for_object(self):
        result = extract_json('{"x": 1}')
        assert isinstance(result, dict)

    def test_returns_list_for_array(self):
        result = extract_json("[1]", expect="array")
        assert isinstance(result, list)


# ── extract_json — fenced outputs ─────────────────────────────────────────


class TestExtractJsonFenced:
    def test_json_fence(self):
        text = '```json\n{"status": "ok"}\n```'
        assert extract_json(text) == {"status": "ok"}

    def test_plain_fence(self):
        text = '```\n{"status": "ok"}\n```'
        assert extract_json(text) == {"status": "ok"}

    def test_fenced_array(self):
        text = '```json\n[{"id": 1}, {"id": 2}]\n```'
        result = extract_json(text, expect="array")
        assert len(result) == 2

    def test_fence_with_preamble(self):
        text = 'Here is the JSON:\n```json\n{"result": true}\n```'
        assert extract_json(text) == {"result": True}


# ── extract_json — preamble + JSON ────────────────────────────────────────


class TestExtractJsonPreamble:
    def test_text_before_object(self):
        text = 'The analysis shows:\n\n{"score": 0.95, "label": "compatible"}'
        assert extract_json(text) == {"score": 0.95, "label": "compatible"}

    def test_text_before_array(self):
        text = "Found results:\n[1, 2, 3]"
        assert extract_json(text, expect="array") == [1, 2, 3]

    def test_text_after_object(self):
        text = '{"a": 1}\n\nNote: this is approximate.'
        assert extract_json(text) == {"a": 1}

    def test_text_surrounding_object(self):
        text = 'Sure! Here is the output:\n{"key": "val"}\nLet me know if you need more.'
        assert extract_json(text) == {"key": "val"}

    def test_nested_objects_extracts_outermost(self):
        text = 'Result: {"outer": {"inner": 1}}'
        result = extract_json(text)
        assert result == {"outer": {"inner": 1}}

    def test_multiple_objects_extracts_first(self):
        text = '{"a": 1}\n{"b": 2}'
        result = extract_json(text)
        assert result == {"a": 1}


# ── extract_json — trailing comma recovery ────────────────────────────────


class TestExtractJsonTrailingComma:
    def test_trailing_comma_object(self):
        text = '{"a": 1, "b": 2,}'
        assert extract_json(text) == {"a": 1, "b": 2}

    def test_trailing_comma_array(self):
        text = '["x", "y",]'
        assert extract_json(text, expect="array") == ["x", "y"]

    def test_trailing_comma_with_preamble(self):
        text = 'Here:\n{"a": 1,}'
        assert extract_json(text) == {"a": 1}

    def test_trailing_comma_in_fence(self):
        text = '```json\n{"a": 1,}\n```'
        assert extract_json(text) == {"a": 1}


# ── extract_json — type enforcement ───────────────────────────────────────


class TestExtractJsonTypeEnforcement:
    def test_object_expected_but_array_given(self):
        with pytest.raises(ExtractionError) as exc_info:
            extract_json("[1, 2]", expect="object")
        assert "object" in exc_info.value.diagnostic

    def test_array_expected_but_object_given(self):
        with pytest.raises(ExtractionError) as exc_info:
            extract_json('{"a": 1}', expect="array")
        assert "array" in exc_info.value.diagnostic

    def test_invalid_expect_value(self):
        with pytest.raises(ValueError, match="expect must be"):
            extract_json("{}", expect="string")


# ── extract_json — malformed / non-recoverable ───────────────────────────


class TestExtractJsonMalformed:
    def test_plain_text_raises(self):
        with pytest.raises(ExtractionError):
            extract_json("This is just plain text with no JSON at all.")

    def test_empty_string_raises(self):
        with pytest.raises(ExtractionError):
            extract_json("")

    def test_truncated_json_raises(self):
        with pytest.raises(ExtractionError):
            extract_json('{"key": "value", "nested": {"a":')

    def test_error_includes_snippet(self):
        raw = "No JSON here, just a wall of text."
        with pytest.raises(ExtractionError) as exc_info:
            extract_json(raw)
        assert exc_info.value.raw_snippet == raw[:200]

    def test_error_snippet_truncated_at_200(self):
        raw = "x" * 500
        with pytest.raises(ExtractionError) as exc_info:
            extract_json(raw)
        assert len(exc_info.value.raw_snippet) == 200


# ── extract_json — realistic LLM outputs ─────────────────────────────────


class TestExtractJsonRealisticOutputs:
    """Patterns observed in production from Sonnet/Haiku/Opus outputs."""

    def test_sonnet_verbose_preamble(self):
        text = (
            "Based on my analysis of the material properties and compatibility "
            "data, here is the assessment:\n\n"
            '{"material": "316L SS", "compatible": true, "confidence": 0.92}\n\n'
            "Let me know if you need further details."
        )
        result = extract_json(text)
        assert result["material"] == "316L SS"
        assert result["compatible"] is True

    def test_haiku_json_fence_with_lang(self):
        text = '```json\n{"status": "approved", "citations": ["MUA-1234"]}\n```'
        result = extract_json(text)
        assert result["status"] == "approved"

    def test_ellipsis_truncation_not_recovered(self):
        """Ellipsis in JSON is not valid and not in our recovery scope.
        The caller's prompt should prevent this."""
        text = '{"items": [1, 2, 3, ...]}'
        with pytest.raises(ExtractionError):
            extract_json(text)

    def test_json_with_string_containing_braces(self):
        text = '{"formula": "Fe{2}O{3}", "name": "iron oxide"}'
        result = extract_json(text)
        assert result["name"] == "iron oxide"

    def test_deeply_nested(self):
        obj = {
            "assessment": {
                "material": "Inconel 718",
                "environment": {"gas": "H2", "pressure_psi": 6000},
                "result": {"compatible": True, "notes": ["approved per MUA-5678"]},
            }
        }
        text = f"Result:\n```json\n{json.dumps(obj, indent=2)}\n```"
        result = extract_json(text)
        assert result["assessment"]["environment"]["pressure_psi"] == 6000
