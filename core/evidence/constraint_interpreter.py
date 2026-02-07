#!/usr/bin/env python3
"""
Module: Constraint Interpreter
Purpose: Constraint Interpreter - Parse natural language queries into structured constraints

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

import re
from typing import Optional


class MaterialConstraints:
    """Material query constraints."""
    def __init__(self):
        self.material: Optional[str] = None
        self.configuration: Optional[str] = None
        self.pressure_psi_max: Optional[float] = None
        self.temp_c_min: Optional[float] = None
        self.temp_c_max: Optional[float] = None
        self.o2_pct: Optional[float] = None
        self.environment: Optional[str] = None

    def to_dict(self):
        return {
            'material': self.material,
            'configuration': self.configuration,
            'pressure_psi_max': self.pressure_psi_max,
            'temp_c_min': self.temp_c_min,
            'temp_c_max': self.temp_c_max,
            'o2_pct': self.o2_pct,
            'environment': self.environment
        }


class ConstraintInterpreter:
    """Parse natural language queries into structured constraints."""

    def parse_query(self, query: str) -> MaterialConstraints:
        """
        Extract constraints from natural language query.

        Example:
            "Stainless steel 316 for oxygen service at 3000 psi and 200 F"
            -> material="stainless steel 316", environment="oxygen",
               pressure_psi_max=3000, temp_c_max=93.3
        """
        constraints = MaterialConstraints()
        query_lower = query.lower()

        # Extract material name (simple pattern)
        # Note: More specific patterns first (e.g., "aluminum 6061" before "aluminum")
        material_patterns = [
            # Known aerospace materials (specific first)
            r'(stainless steel \d+[a-z]*)',
            r'(aluminum \d+[a-z\d-]*)',  # Specific alloys like "aluminum 6061-T6"
            r'(al \d+[a-z\d-]*)',  # AL 6061 format
            r'(inconel \d+)',
            r'(monel \d+)',
            r'(hastelloy [a-z0-9]+)',
            r'(titanium)',
            r'(viton [a-z]*)',
            r'(kel-f)',
            r'(teflon)',
            r'(kapton)',
            r'(elastomer)',
            r'(ptfe)',
            r'(tefzel)',
            r'(silicone\s+rubber|silicone)',
            r'(epdm)',
            r'(buna-n|buna n)',
            r'(fkm)',
            r'(aluminum)',  # Generic "aluminum" as fallback
            r'(stainless steel)',  # Generic "stainless steel" as fallback
            r'(ss \d+[a-z]*)',  # SS 316, SS 304L
            r'(cres \d+[a-z]*)',  # CRES 316

            # Fallback: Capture unknown materials with alphanumeric names
            # This catches things like "unobtainium-42", "handwavium", etc.
            # Must appear AFTER specific patterns to avoid false positives
            r'\buse\s+(\w+[-]?\d*)\b.*(?:in|for|with)',  # "use X in oxygen"
            r'\bis\s+(\w+[-]?\d*)\s+(?:compatible|safe|suitable)',  # "is X compatible"
            r'\bcan\s+(\w+[-]?\d*)\s+be\s+used',  # "can X be used"
        ]

        for pattern in material_patterns:
            match = re.search(pattern, query_lower)
            if match:
                constraints.material = match.group(1)
                break

        # Extract environment
        if 'oxygen' in query_lower or 'gox' in query_lower or 'lox' in query_lower or 'o2' in query_lower or 'o₂' in query_lower:
            constraints.environment = 'oxygen'
        elif 'hydrogen' in query_lower or 'gh2' in query_lower or 'lh2' in query_lower or 'h2' in query_lower:
            constraints.environment = 'hydrogen'
        elif 'vacuum' in query_lower:
            constraints.environment = 'vacuum'

        # Extract pressure (psi, psia, bar, kpa, mpa)
        pressure_match = re.search(r'(\d+(?:\.\d+)?)\s*(psi|psia|bar|kpa|mpa)', query_lower)
        if pressure_match:
            value = float(pressure_match.group(1))
            unit = pressure_match.group(2)

            # Convert to psi
            if unit == 'bar':
                value = value * 14.504
            elif unit == 'kpa':
                value = value * 0.145
            elif unit == 'mpa':
                value = value * 145.04

            constraints.pressure_psi_max = value

        # Extract temperature (F, C, K)
        temp_match = re.search(r'(-?\d+(?:\.\d+)?)\s*(f|c|k|°f|°c)', query_lower)
        if temp_match:
            value = float(temp_match.group(1))
            unit = temp_match.group(2).replace('°', '')

            # Convert to C
            if unit == 'f':
                value = (value - 32) * 5/9
            elif unit == 'k':
                value = value - 273.15

            constraints.temp_c_max = value

        return constraints
