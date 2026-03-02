#!/usr/bin/env python3
"""
Centralized robust JSON extraction for LLM responses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class _AttemptResult:
    parsed: dict | list | None
    mismatch_actual: str | None = None


class ExtractionError(ValueError):
    """Raised when JSON extraction fails."""

    def __init__(self, diagnostic: str, raw_text: str):
        self.diagnostic = diagnostic
        self.raw_snippet = (raw_text or "")[:200]
        super().__init__(f"{diagnostic} | raw_snippet={self.raw_snippet!r}")


def strip_code_fences(text: str) -> str:
    """Return fenced content if present; otherwise return original text."""
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text, flags=re.IGNORECASE)
    if not match:
        return text
    return match.group(1).strip()


def normalize_json_candidate(text: str) -> str:
    """Remove trailing commas before closing braces/brackets."""
    normalized = text
    while True:
        updated = re.sub(r",\s*([}\]])", r"\1", normalized)
        if updated == normalized:
            return updated
        normalized = updated


def extract_json(text: str, expect: str = "object") -> dict | list:
    """
    Extract and parse JSON with robust recovery for common LLM formatting quirks.

    Recovery order:
    1) direct parse
    2) strip markdown fences, parse
    3) bracket-depth scan for first complete JSON span, parse
    4) normalize trailing commas and retry steps 1-3
    """
    if expect not in {"object", "array"}:
        raise ValueError("expect must be 'object' or 'array'")

    raw = text or ""
    if not raw.strip():
        raise ExtractionError("Empty response; no JSON content found", raw)

    first_pass = _extract_with_strategies(raw, expect=expect, normalize=False)
    if first_pass.parsed is not None:
        return first_pass.parsed
    if first_pass.mismatch_actual:
        raise ExtractionError(
            f"Expected JSON {expect} but got {first_pass.mismatch_actual}",
            raw,
        )

    normalized = normalize_json_candidate(raw)
    second_pass = _extract_with_strategies(normalized, expect=expect, normalize=False)
    if second_pass.parsed is not None:
        return second_pass.parsed
    if second_pass.mismatch_actual:
        raise ExtractionError(
            f"Expected JSON {expect} but got {second_pass.mismatch_actual}",
            raw,
        )

    raise ExtractionError(
        f"Unable to extract valid JSON {expect} from model response",
        raw,
    )


def _extract_with_strategies(text: str, *, expect: str, normalize: bool) -> _AttemptResult:
    # 1) Direct parse (clean output)
    direct = _parse_candidate(text.strip(), expect=expect, normalize=normalize)
    if direct.parsed is not None or direct.mismatch_actual:
        return direct

    # 2) Fenced parse
    stripped = strip_code_fences(text)
    if stripped is not text:
        fenced = _parse_candidate(stripped.strip(), expect=expect, normalize=normalize)
        if fenced.parsed is not None or fenced.mismatch_actual:
            return fenced

    # 3) First complete JSON span
    span = _find_first_json_span(text, expect=expect)
    if span is not None:
        span_parse = _parse_candidate(span, expect=expect, normalize=normalize)
        if span_parse.parsed is not None or span_parse.mismatch_actual:
            return span_parse

    return _AttemptResult(parsed=None)


def _parse_candidate(candidate: str, *, expect: str, normalize: bool) -> _AttemptResult:
    if not candidate:
        return _AttemptResult(parsed=None)

    payload = normalize_json_candidate(candidate) if normalize else candidate
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return _AttemptResult(parsed=None)

    if expect == "object":
        if isinstance(parsed, dict):
            return _AttemptResult(parsed=parsed)
        return _AttemptResult(parsed=None, mismatch_actual=type(parsed).__name__)

    if isinstance(parsed, list):
        return _AttemptResult(parsed=parsed)
    return _AttemptResult(parsed=None, mismatch_actual=type(parsed).__name__)


def _find_first_json_span(text: str, *, expect: str) -> str | None:
    open_char = "{" if expect == "object" else "["
    close_char = "}" if expect == "object" else "]"
    opener_for_closer = {"}": "{", "]": "["}

    for idx, ch in enumerate(text):
        if ch != open_char:
            continue

        stack = [ch]
        in_string = False
        escaped = False
        for pos in range(idx + 1, len(text)):
            token = text[pos]
            if escaped:
                escaped = False
                continue
            if token == "\\":
                escaped = True
                continue
            if token == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if token in "{[":
                stack.append(token)
                continue
            if token in "}]":
                if not stack:
                    break
                expected_open = opener_for_closer[token]
                if stack[-1] != expected_open:
                    break
                stack.pop()
                if not stack and token == close_char:
                    return text[idx : pos + 1]
                if not stack:
                    break
    return None
