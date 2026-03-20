#!/usr/bin/env python3
"""
Module: Models
Purpose: Shared data models for MUA generation.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal
import uuid


RatingClass = Literal["FLAMM", "SCC", "CORR", "TVS", "TOX", "FS"]


@dataclass
class EvidenceRef:
    map_tis_id: Optional[str] = None
    test_method: Optional[str] = None
    report_no: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class RatingResult:
    test_class: RatingClass
    rating: Literal["A", "B", "C", "X"]
    evidence: Optional[EvidenceRef] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class EnvironmentEnvelope:
    oxygen_pct: Optional[float] = None
    pressure_kpa: Optional[float] = None
    temperature_c: Optional[float] = None
    fluid_medium: Optional[str] = None
    habitable_volume: Optional[bool] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class MIULRef:
    miul_id: str
    materialkey: str
    material_designator: Optional[str]
    spec_refs: List[str]
    program: Optional[str]
    hardware_name: Optional[str]
    hardware_class: Optional[str]
    environment: EnvironmentEnvelope
    remarks: Optional[str] = None
    application_context: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class Mitigation:
    text: str
    source_doc_id: str
    clause_refs: List[str]
    score: float
    hazards: List[str] = field(default_factory=list)
    source_center: Optional[str] = None
    acceptance: Dict[str, float] = field(default_factory=dict)
    has_table: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: str = ""  # NASA SWE-013 traceability


