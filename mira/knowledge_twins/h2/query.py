#!/usr/bin/env python3
"""
Module: Query
Purpose: H2 Knowledge Twin - Query and Response Models

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

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..types import (
    AuditTrail,
    Constraint,
    Driver,
    EvidenceObject,
    Gap,
    HeatTreatCondition,
    HeatTreatment,
    LoadingMode,
    Phase,
    ProductForm,
    RecommendedTest,
    StrengthData,
    Verdict,
    WeldState,
)


@dataclass
class H2Query:
    """
    User query input for H2 compatibility assessment.
    Per Fran's spec - minimum viable inputs with explicit unknowns.
    """
    # Material (required)
    material_name: str
    material_spec: Optional[str] = None

    # Condition (all optional, but gaps will be flagged)
    condition: HeatTreatCondition = HeatTreatCondition.UNKNOWN
    heat_treatment: Optional[HeatTreatment] = None
    strength: Optional[StrengthData] = None
    product_form: ProductForm = ProductForm.UNKNOWN
    weld_state: WeldState = WeldState.BASE_METAL

    # Environment (required for meaningful answer)
    phase: Phase = Phase.UNKNOWN
    pressure_mpa: Optional[float] = None
    temperature_c: Optional[float] = None

    # Loading (optional but recommended)
    loading_mode: LoadingMode = LoadingMode.UNKNOWN
    has_notch: Optional[bool] = None
    sigma_max_mpa: Optional[float] = None
    fraction_of_yield: Optional[float] = None

    # Options
    consequence_class: str = "medium"
    prefer_conservative: bool = True


@dataclass
class H2Response:
    """
    System response for H2 compatibility assessment.
    Everything is traceable. No vibes.
    """
    # The answer
    verdict: Verdict
    confidence: float

    # Human readable
    decision_summary: str

    # Supporting detail
    drivers: List[Driver] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    mismatches: List[str] = field(default_factory=list)
    recommended_tests: List[RecommendedTest] = field(default_factory=list)

    # Evidence
    evidence: List[EvidenceObject] = field(default_factory=list)

    # Audit
    audit: Optional[AuditTrail] = None

    # Warnings
    warnings: List[str] = field(default_factory=list)
