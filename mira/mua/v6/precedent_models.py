#!/usr/bin/env python3
"""
Module: Precedent Models
Purpose: Data models for V6 Precedent-Based MUA Generator.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: False
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class IssueCategory(str, Enum):
    """NASA MUA issue categories requiring rationale/mitigation."""

    FLAMMABILITY = "flammability"
    TOXICITY = "toxicity"
    STRESS_CORROSION_CRACKING = "scc"
    CORROSION = "corrosion"
    DISSIMILAR_METALS = "dissimilar_metals"
    THERMAL_VACUUM_STABILITY = "tvs"
    OXYGEN_COMPATIBILITY = "o2_compat"
    PROCESS_SPECIFICATION = "process_spec"
    WORKMANSHIP = "workmanship"
    OFFGASSING = "offgassing"
    FLUID_COMPATIBILITY = "fluid_compat"
    FRACTURE_CONTROL = "fracture_control"
    OTHER = "other"


class EnvironmentType(str, Enum):
    """Normalized environment types for matching."""

    VACUUM = "vacuum"
    CABIN_AIR = "cabin_air"
    ENRICHED_O2 = "enriched_o2"
    PURE_O2 = "pure_o2"
    LOX_GOX = "lox_gox"
    WATER = "water"
    CO2 = "co2"
    CRYOGENIC = "cryogenic"
    HIGH_PRESSURE = "high_pressure"
    AMBIENT = "ambient"
    UNKNOWN = "unknown"


class MaterialFamily(str, Enum):
    """Material family classifications for grouping."""

    STAINLESS_STEEL = "stainless_steel"
    CARBON_STEEL = "carbon_steel"
    ALUMINUM = "aluminum"
    TITANIUM = "titanium"
    NICKEL_ALLOY = "nickel_alloy"
    COPPER_ALLOY = "copper_alloy"
    POLYMER = "polymer"
    ELASTOMER = "elastomer"
    CERAMIC = "ceramic"
    COMPOSITE = "composite"
    COATING = "coating"
    ADHESIVE = "adhesive"
    LUBRICANT = "lubricant"
    SEALANT = "sealant"
    OTHER_METAL = "other_metal"
    OTHER_NONMETAL = "other_nonmetal"
    UNKNOWN = "unknown"


class NormalizedEnvironment(BaseModel):
    """Normalized environment specification for matching."""

    type: EnvironmentType = Field(default=EnvironmentType.UNKNOWN)
    o2_percent: Optional[float] = Field(None)  # No constraint - some parsed values are invalid
    pressure_psia: Optional[float] = Field(None)  # No constraint - some records have odd values
    temperature_f: Optional[float] = None
    is_habitable: bool = False
    raw_text: Optional[str] = Field(None, description="Original environment string")

    def envelope_str(self) -> str:
        """Return human-readable envelope string."""
        parts = [self.type.value]
        if self.o2_percent is not None:
            parts.append(f"{self.o2_percent}% O2")
        if self.pressure_psia is not None:
            parts.append(f"{self.pressure_psia} PSIA")
        if self.temperature_f is not None:
            parts.append(f"{self.temperature_f}F")
        parts.append("Habitable" if self.is_habitable else "Nonhabitable")
        return ", ".join(parts)


class CleanedMUARecord(BaseModel):
    """Cleaned and normalized MUA record for indexing and retrieval."""

    # Identification
    mua_number: str = Field(..., description="MUA identifier")
    source_file: str = Field(..., description="Source PDF filename")

    # Material
    material_designation: str = Field(..., description="Material name/alloy")
    material_family: MaterialFamily = Field(default=MaterialFamily.UNKNOWN)
    specification: Optional[str] = Field(None, description="MIL-SPEC, AMS, etc.")
    manufacturer: Optional[str] = None
    trade_name: Optional[str] = None

    # Environment
    environment: NormalizedEnvironment = Field(default_factory=NormalizedEnvironment)

    # Classification
    category: Optional[str] = Field(None, description="NASA category I, II, III")
    issues: List[IssueCategory] = Field(default_factory=list)
    determination: str = Field(default="UNKNOWN", description="APPROVED/CANCELLED/DEFERRED/REJECTED")

    # Content
    application: str = Field(default="", description="Application/usage context")
    rationale: str = Field(default="", description="Justification for determination")
    test_reports: List[str] = Field(default_factory=list)

    # Metadata
    confidence: float = Field(default=0.0, ge=0, le=1)
    extraction_mode: str = Field(default="unknown")

    def search_text(self) -> str:
        """Generate combined text for semantic search embedding."""
        parts = [
            self.material_designation,
            self.environment.raw_text or self.environment.type.value,
            " ".join(issue.value for issue in self.issues),
            self.application[:500] if self.application else "",
            self.rationale[:500] if self.rationale else "",
        ]
        return " | ".join(p for p in parts if p)


class MatchFactors(BaseModel):
    """Breakdown of match quality factors."""

    material_score: float = Field(0.0, ge=0, le=1, description="Material similarity")
    environment_score: float = Field(0.0, ge=0, le=1, description="Environment compatibility")
    issue_score: float = Field(0.0, ge=0, le=1, description="Issue category overlap")
    determination_boost: float = Field(0.0, ge=0, le=1, description="Boost for APPROVED")
    confidence_score: float = Field(0.0, ge=0, le=1, description="Extraction confidence")

    def weighted_score(self) -> float:
        """Calculate weighted composite score."""
        return (
            0.30 * self.material_score +
            0.25 * self.environment_score +
            0.25 * self.issue_score +
            0.10 * self.determination_boost +
            0.10 * self.confidence_score
        )


class PrecedentMatch(BaseModel):
    """A matched precedent MUA with scoring."""

    record: CleanedMUARecord
    semantic_score: float = Field(0.0, ge=0, le=1, description="FAISS similarity")
    match_factors: MatchFactors = Field(default_factory=MatchFactors)
    composite_score: float = Field(0.0, ge=0, le=1)
    rank: int = Field(0, ge=0)

    def summary(self) -> str:
        """One-line summary for display."""
        return (
            f"[{self.rank}] {self.record.mua_number} - "
            f"{self.record.material_designation} in {self.record.environment.type.value} "
            f"({self.record.determination}) Score: {self.composite_score:.2f}"
        )
