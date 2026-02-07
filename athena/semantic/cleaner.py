#!/usr/bin/env python3
"""
Module: Cleaner
Purpose: ATHENA Value Cleaner.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032
Safety Critical: True
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

__all__ = ["ValueCleaner", "NumericValue"]
__safety_critical__ = True


@dataclass
class NumericValue:
    """Parsed numeric value with metadata."""
    value: float
    raw: str                        # Original text
    is_range: bool = False          # True if parsed from range
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    modifier: Optional[str] = None  # "<", ">", "≤", "≥", "~"
    unit: Optional[str] = None      # Extracted unit if present

    @property
    def is_approximate(self) -> bool:
        """True if value has modifier indicating approximation."""
        return self.modifier in ("~", "≈", "approx", "about")

    @property
    def is_limit(self) -> bool:
        """True if value is a limit (< or >)."""
        return self.modifier in ("<", ">", "≤", "≥", "max", "min")


class ValueCleaner:
    """
    Cleans and extracts numeric values from cell text.

    Handles:
    - Simple numbers: "123.45"
    - Ranges: "100-200", "100 to 200"
    - Modifiers: "<100", ">50", "~75"
    - Scientific notation: "1.5e-4", "1.5×10^-4"
    - Thousands separators: "1,234.56"
    - Parenthetical values: "123 (±5)"
    """

    # Patterns for numeric extraction
    SCIENTIFIC_PATTERN = re.compile(
        r"([+-]?\d+\.?\d*)\s*[×x]\s*10\^?\s*([+-]?\d+)",
        re.IGNORECASE
    )

    NUMBER_PATTERN = re.compile(
        r"([<>≤≥~≈]?)\s*"           # Optional modifier
        r"([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)"  # Number with optional commas
        r"(?:\s*[eE]([+-]?\d+))?"   # Optional exponent
    )

    RANGE_PATTERN = re.compile(
        r"([+-]?\d+\.?\d*)\s*[-–—to]+\s*([+-]?\d+\.?\d*)",
        re.IGNORECASE
    )

    def __init__(self) -> None:
        pass

    def clean(self, text: Optional[str]) -> Optional[NumericValue]:
        """
        Extract numeric value from cell text.

        Args:
            text: Raw cell text

        Returns:
            NumericValue if parseable, None otherwise
        """
        if not text:
            return None

        text = text.strip()
        if not text:
            return None

        # Check for range first
        range_match = self.RANGE_PATTERN.search(text)
        if range_match:
            try:
                low = float(range_match.group(1).replace(",", ""))
                high = float(range_match.group(2).replace(",", ""))
                return NumericValue(
                    value=(low + high) / 2,  # Midpoint as value
                    raw=text,
                    is_range=True,
                    range_min=low,
                    range_max=high,
                )
            except ValueError:
                pass

        # Check for scientific notation with ×10^
        sci_match = self.SCIENTIFIC_PATTERN.search(text)
        if sci_match:
            try:
                mantissa = float(sci_match.group(1))
                exponent = int(sci_match.group(2))
                value = mantissa * (10 ** exponent)
                return NumericValue(
                    value=value,
                    raw=text,
                )
            except ValueError:
                pass

        # Standard number with optional modifier
        num_match = self.NUMBER_PATTERN.search(text)
        if num_match:
            try:
                modifier = num_match.group(1) if num_match.group(1) else None
                num_str = num_match.group(2).replace(",", "")
                value = float(num_str)

                # Handle exponent
                if num_match.group(3):
                    value *= 10 ** int(num_match.group(3))

                return NumericValue(
                    value=value,
                    raw=text,
                    modifier=modifier,
                )
            except ValueError:
                pass

        return None

    def clean_percentage(self, text: Optional[str]) -> Optional[float]:
        """
        Extract percentage value, returning as 0-100 scale.

        Handles: "45%", "45 %", "45 percent", "0.45" (auto-detects fraction)
        """
        if not text:
            return None

        result = self.clean(text)
        if result is None:
            return None

        value = result.value

        # Auto-detect if value is likely a fraction (0-1 range)
        # Only if no % symbol and value is in 0-1 range
        if "%" not in text and 0 <= value <= 1:
            value *= 100

        return value

    def clean_temperature(self, text: Optional[str]) -> Optional[tuple[float, str]]:
        """
        Extract temperature with unit detection.

        Returns (value, unit) where unit is 'C', 'F', or 'K'.
        """
        if not text:
            return None

        result = self.clean(text)
        if result is None:
            return None

        # Detect unit
        text_lower = text.lower()
        if "°c" in text_lower or "celsius" in text_lower:
            return (result.value, "C")
        elif "°f" in text_lower or "fahrenheit" in text_lower:
            return (result.value, "F")
        elif "k" in text_lower:
            return (result.value, "K")
        else:
            # Default to Celsius for material science context
            return (result.value, "C")

    def clean_pressure(self, text: Optional[str]) -> Optional[tuple[float, str]]:
        """
        Extract pressure with unit detection.

        Returns (value, unit) where unit is 'MPa', 'psi', 'bar', etc.
        """
        if not text:
            return None

        result = self.clean(text)
        if result is None:
            return None

        # Detect unit
        text_lower = text.lower()
        if "mpa" in text_lower:
            return (result.value, "MPa")
        elif "gpa" in text_lower:
            return (result.value, "GPa")
        elif "ksi" in text_lower:
            return (result.value, "ksi")
        elif "psi" in text_lower:
            return (result.value, "psi")
        elif "bar" in text_lower:
            return (result.value, "bar")
        elif "atm" in text_lower:
            return (result.value, "atm")
        else:
            # Default to MPa for material science context
            return (result.value, "MPa")
