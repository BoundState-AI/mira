#!/usr/bin/env python3
"""
Module: Parsing
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

__all__ = ["parse_confidence", "safe_parse_enum", "safe_parse_enum_list"]

E = TypeVar("E", bound=Enum)


def parse_confidence(value: float | str | None) -> float:
    """Parse confidence value to float in range [0.0, 1.0].

    Args:
        value: Raw confidence value (float, string, or None)

    Returns:
        Float confidence clamped to [0.0, 1.0]
    """
    if value is None:
        return 0.5
    try:
        conf = float(value)
        return max(0.0, min(1.0, conf))
    except (ValueError, TypeError):
        return 0.5


def safe_parse_enum(
    enum_cls: type[E],
    value: str | None,
    default: E | None = None,
) -> E | None:
    """Safely parse string to enum value.

    Args:
        enum_cls: Enum class to parse into
        value: String value to parse
        default: Default value if parsing fails

    Returns:
        Parsed enum value or default
    """
    if value is None:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        # Try case-insensitive match
        value_lower = value.lower().replace("-", "_")
        for member in enum_cls:
            if member.value.lower() == value_lower or member.name.lower() == value_lower:
                return member
        return default


def safe_parse_enum_list(
    enum_cls: type[E],
    values: list[str] | None,
) -> list[E]:
    """Safely parse list of strings to enum values.

    Args:
        enum_cls: Enum class to parse into
        values: List of string values

    Returns:
        List of successfully parsed enum values (skips failures)
    """
    if not values:
        return []
    result = []
    for value in values:
        parsed = safe_parse_enum(enum_cls, value)
        if parsed is not None:
            result.append(parsed)
    return result
