#!/usr/bin/env python3
"""
Module: Requirement
Purpose: ATHENA Requirements Interpreter Models.

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

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field

__all__ = ["RequirementRecord", "RequirementType", "VerdictType"]
__safety_critical__ = True


class RequirementType(str, Enum):
    """Type of requirement from a standard."""
    TESTING = "testing"           # Requires specific test method
    CLEANING = "cleaning"         # Cleaning/contamination control
    PROHIBITION = "prohibition"   # Material/use not allowed
    APPROVAL = "approval"         # Requires explicit approval
    DOCUMENTATION = "documentation"  # Documentation requirements
    INSPECTION = "inspection"     # Inspection requirements
    HANDLING = "handling"         # Handling/storage requirements
    GENERAL = "general"           # General guidance


class VerdictType(str, Enum):
    """Expert system verdict type."""
    YES = "yes"                           # Compatible
    YES_WITH_CONDITIONS = "yes_with_conditions"  # Compatible with conditions
    MAYBE = "maybe"                       # Need more information/testing
    NO = "no"                             # Not compatible


class RequirementRecord(BaseModel):
    """
    Single requirement extracted from a standards document.

    Represents one structured requirement from NASA-STD, ASTM, or similar
    specifications for materials compatibility assessment.
    """
    model_config = {"extra": "forbid"}

    # Identity & dedup
    requirement_id: str = Field(
        ...,
        description="Unique ID: '{doc}-{section}-{seq}' e.g. '6016-4.2.3.1-001'"
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords for fast filtering: ['316', 'stainless', 'GOX']"
    )

    # Source provenance
    source_document: str = Field(..., description="Document ID: 'NASA-STD-6016'")
    section: str = Field(..., description="Section number: '4.2.3.1'")
    page: int = Field(..., description="Page number in source PDF")

    # Applicability scope
    material_category: Optional[str] = Field(
        None, description="Material scope: 'Category A', 'all metals', 'polymers'"
    )
    environment: Optional[str] = Field(
        None, description="Environment: 'GOX', 'LOX', 'enriched air'"
    )
    pressure_threshold: Optional[str] = Field(
        None, description="Pressure condition: '>200 psi', 'any'"
    )
    temperature_threshold: Optional[str] = Field(
        None, description="Temperature condition: '<-150°F', 'cryogenic'"
    )

    # Requirement content
    requirement_type: RequirementType = Field(
        RequirementType.GENERAL,
        description="Type of requirement"
    )
    requirement_text: str = Field(
        ...,
        description="The actual requirement text (concise)"
    )
    test_method: Optional[str] = Field(
        None, description="Test method reference: 'ASTM G124', 'NASA-STD-6001B Test 17'"
    )
    cleaning_spec: Optional[str] = Field(
        None, description="Cleaning specification: 'ASTM G93 Level 100A'"
    )

    # Full context for citation
    full_paragraph: str = Field(
        ...,
        description="Complete paragraph for human review and citation"
    )

    # Extraction metadata
    extraction_confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in extraction accuracy"
    )

    @computed_field
    @property
    def is_prohibitive(self) -> bool:
        """Check if this requirement prohibits use."""
        return self.requirement_type == RequirementType.PROHIBITION

    @computed_field
    @property
    def has_test_requirement(self) -> bool:
        """Check if this requirement mandates testing."""
        return (
            self.requirement_type == RequirementType.TESTING
            or self.test_method is not None
        )

    @computed_field
    @property
    def has_cleaning_requirement(self) -> bool:
        """Check if this requirement mandates cleaning."""
        return (
            self.requirement_type == RequirementType.CLEANING
            or self.cleaning_spec is not None
        )

    def matches_query(
        self,
        material: Optional[str] = None,
        environment: Optional[str] = None,
        pressure_psi: Optional[float] = None,
    ) -> bool:
        """
        Check if this requirement applies to a query.

        Args:
            material: Material name or type
            environment: Environment (GOX, LOX, etc.)
            pressure_psi: Operating pressure in PSI

        Returns:
            True if requirement may apply to this query
        """
        material_lower = material.lower() if material else ""
        env_lower = environment.lower() if environment else ""

        # Check if requirement mentions the queried material
        material_match = False
        if material_lower:
            # Check keywords
            if self.keywords:
                material_match = any(
                    kw.lower() in material_lower or material_lower in kw.lower()
                    for kw in self.keywords
                )
            # Check material_category
            if not material_match and self.material_category:
                cat_lower = self.material_category.lower()
                cat_words = set(cat_lower.split())
                # Broad categories like "all metals", "flight hardware"
                # Must be whole word match (not "all" in "alloys")
                if any(broad in cat_words for broad in ["all", "flight", "hardware"]):
                    material_match = True
                elif any(term in cat_lower for term in material_lower.split()):
                    material_match = True
            # Check full_paragraph for material mention
            if not material_match and self.full_paragraph:
                para_lower = self.full_paragraph.lower()
                # Check if material name appears in paragraph
                if material_lower in para_lower:
                    material_match = True
                # Check material type words
                for term in ["stainless", "steel", "aluminum", "titanium", "inconel", "nickel"]:
                    if term in material_lower and term in para_lower:
                        material_match = True
                        break

        # Check environment match
        env_match = False
        if env_lower:
            if self.environment:
                req_env_lower = self.environment.lower()
                if env_lower in req_env_lower or req_env_lower in env_lower:
                    env_match = True
                elif "oxygen" in req_env_lower or "o2" in req_env_lower:
                    if "gox" in env_lower or "lox" in env_lower or "oxygen" in env_lower:
                        env_match = True
            # Check full_paragraph for environment mention
            if not env_match and self.full_paragraph:
                para_lower = self.full_paragraph.lower()
                if env_lower in para_lower:
                    env_match = True

        # Matching logic depends on requirement type:
        # - PROHIBITION: Material-specific, require material match
        # - Other types: Can match on material OR environment
        if self.requirement_type == RequirementType.PROHIBITION:
            # Prohibitions are material-specific - only match if material matches
            # A titanium prohibition shouldn't match a stainless steel query
            if material and not material_match:
                return False
            # Still need environment match too for prohibitions with env context
            if environment and self.environment:
                return env_match
            return material_match

        # For non-prohibitions (testing, cleaning, general, etc.):
        # Match if material OR environment matches
        if material and environment:
            return material_match or env_match
        elif material:
            return material_match
        elif environment:
            return env_match
        else:
            return False  # No query = no match
