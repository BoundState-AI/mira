#!/usr/bin/env python3
"""
Module: Ontology
Purpose: ATHENA Semantic Ontology.

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

from enum import Enum

__all__ = ["SemanticTag"]
__safety_critical__ = True


class SemanticTag(str, Enum):
    """
    Semantic classification for table column headers.

    Domain-agnostic categories that work across H2, O2, and other contexts.
    """

    # Material identification
    MATERIAL_NAME = "material_name"
    MATERIAL_SPEC = "material_spec"          # Spec number (e.g., AMS 5643)
    MATERIAL_UNS = "material_uns"            # UNS number (e.g., S17400)
    MATERIAL_FORM = "material_form"          # Form (bar, sheet, wire)
    MATERIAL_CONDITION = "material_condition"  # Heat treatment, temper

    # Environment
    ENVIRONMENT_GAS = "environment_gas"      # H2, O2, N2, etc.
    ENVIRONMENT_PRESSURE = "environment_pressure"
    ENVIRONMENT_TEMPERATURE = "environment_temperature"
    ENVIRONMENT_HUMIDITY = "environment_humidity"

    # Mechanical properties
    PROPERTY_TENSILE = "property_tensile"    # Tensile strength
    PROPERTY_YIELD = "property_yield"        # Yield strength
    PROPERTY_ELONGATION = "property_elongation"
    PROPERTY_RA = "property_ra"              # Reduction of area
    PROPERTY_HARDNESS = "property_hardness"
    PROPERTY_MODULUS = "property_modulus"    # Elastic modulus
    PROPERTY_FATIGUE = "property_fatigue"
    PROPERTY_CREEP = "property_creep"
    PROPERTY_IMPACT = "property_impact"      # Charpy, Izod

    # Derived/calculated properties
    PROPERTY_EMBRITTLEMENT_INDEX = "property_embrittlement_index"
    PROPERTY_RATIO = "property_ratio"        # Any ratio (e.g., RA_H2/RA_He)

    # Compatibility/rating
    COMPATIBILITY_CLASS = "compatibility_class"  # A, B, C, D ratings
    COMPATIBILITY_RATING = "compatibility_rating"

    # Test metadata
    TEST_TYPE = "test_type"                  # SSRT, fatigue, etc.
    TEST_STRAIN_RATE = "test_strain_rate"
    TEST_SPECIMEN = "test_specimen"          # Specimen geometry
    TEST_REFERENCE = "test_reference"        # Citation, source

    # Composition
    COMPOSITION_ELEMENT = "composition_element"  # C, Mn, Cr, etc.
    COMPOSITION_RANGE = "composition_range"      # Min-max range

    # Identifiers
    ID_ROW = "id_row"                        # Row number/ID
    ID_SAMPLE = "id_sample"                  # Sample/specimen ID

    # Other
    NOTES = "notes"
    UNKNOWN = "unknown"

    @classmethod
    def is_material_tag(cls, tag: SemanticTag) -> bool:
        """Check if tag is material-related."""
        return tag.value.startswith("material_")

    @classmethod
    def is_environment_tag(cls, tag: SemanticTag) -> bool:
        """Check if tag is environment-related."""
        return tag.value.startswith("environment_")

    @classmethod
    def is_property_tag(cls, tag: SemanticTag) -> bool:
        """Check if tag is a property measurement."""
        return tag.value.startswith("property_")

    @classmethod
    def is_composition_tag(cls, tag: SemanticTag) -> bool:
        """Check if tag is composition-related."""
        return tag.value.startswith("composition_")
