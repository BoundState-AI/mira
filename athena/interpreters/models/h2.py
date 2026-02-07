#!/usr/bin/env python3
"""
Module: H2
Purpose: ATHENA H2 Interpreter Models.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, computed_field

__all__ = ["EmbrittlementRecord"]
__safety_critical__ = True


class EmbrittlementRecord(BaseModel):
    """
    Single hydrogen embrittlement data record.

    Represents one row of H2 compatibility data extracted from a table.
    """
    model_config = {"extra": "forbid"}

    # Source tracking
    record_id: str
    table_id: str
    row_index: int

    # Material identification
    material_name: str
    material_uns: Optional[str] = None
    material_spec: Optional[str] = None
    material_form: Optional[str] = None
    material_condition: Optional[str] = None

    # Environment (SI units)
    pressure_pa: Optional[float] = None       # Pressure in Pascals
    temperature_k: Optional[float] = None     # Temperature in Kelvin

    # Properties (SI units or %)
    uts_h2_pa: Optional[float] = None         # UTS in H2, Pascals
    uts_he_pa: Optional[float] = None         # UTS in He/air, Pascals
    ys_h2_pa: Optional[float] = None          # YS in H2, Pascals
    ys_he_pa: Optional[float] = None          # YS in He/air, Pascals

    elongation_h2: Optional[float] = None     # Elongation in H2, %
    elongation_he: Optional[float] = None     # Elongation in He/air, %

    ra_h2: Optional[float] = None             # RA in H2, %
    ra_he: Optional[float] = None             # RA in He/air, %

    # Test metadata
    strain_rate_s: Optional[float] = None     # Strain rate, s^-1
    test_type: Optional[str] = None           # SSRT, fatigue, etc.
    specimen_type: Optional[str] = None
    reference: Optional[str] = None

    # Notes
    notes: Optional[str] = None

    # Quality
    extraction_confidence: float = 1.0

    @computed_field
    @property
    def embrittlement_index(self) -> Optional[float]:
        """
        Calculate hydrogen embrittlement index.

        HEI = (RA_He - RA_H2) / RA_He * 100

        Returns:
            Embrittlement index as percentage, or None if data insufficient
        """
        if self.ra_h2 is None or self.ra_he is None:
            return None

        if self.ra_he <= 0:
            return None

        return (self.ra_he - self.ra_h2) / self.ra_he * 100

    @computed_field
    @property
    def ra_ratio(self) -> Optional[float]:
        """
        Calculate RA ratio (H2/He).

        Returns:
            RA_H2 / RA_He ratio, or None if data insufficient
        """
        if self.ra_h2 is None or self.ra_he is None:
            return None

        if self.ra_he <= 0:
            return None

        return self.ra_h2 / self.ra_he

    @computed_field
    @property
    def is_complete(self) -> bool:
        """Check if record has minimum required data."""
        return bool(
            self.material_name
            and (self.ra_h2 is not None or self.elongation_h2 is not None)
        )

    @property
    def severity(self) -> str:
        """
        Categorize embrittlement severity.

        Returns:
            'severe', 'moderate', 'mild', or 'unknown'
        """
        hei = self.embrittlement_index
        if hei is None:
            return "unknown"

        if hei > 50:
            return "severe"
        elif hei > 25:
            return "moderate"
        else:
            return "mild"

    @computed_field
    @property
    def compatibility_class(self) -> Optional[str]:
        """
        Map RA ratio to A/B/C/D compatibility class.

        Based on HEE (Hydrogen Environment Embrittlement) index:
        - A: Negligible embrittlement (RA ratio > 0.9)
        - B: Slight embrittlement (RA ratio 0.7-0.9)
        - C: Moderate embrittlement (RA ratio 0.5-0.7)
        - D: Severe embrittlement (RA ratio < 0.5)

        Returns:
            Compatibility class A/B/C/D, or None if data insufficient
        """
        ratio = self.ra_ratio
        if ratio is None:
            return None

        if ratio > 0.9:
            return "A"
        elif ratio > 0.7:
            return "B"
        elif ratio > 0.5:
            return "C"
        else:
            return "D"
