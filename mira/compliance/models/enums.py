#!/usr/bin/env python3
"""
Module: Compliance Enumerations
Purpose: All enums for gap types, severity levels, and compliance statuses

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - Enumerations

All enums for the compliance module, including gap types, severity levels,
compliance statuses, and source types.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from enum import Enum


class ApplicabilityStatus(str, Enum):
    """MPR applicability determination."""
    APPLICABLE = "applicable"
    NOT_APPLICABLE_BY_CONDITION = "not_applicable_by_condition"
    TAILORED_OUT = "tailored_out"


class ComplianceStatus(str, Enum):
    """Compliance determination for an MPR."""
    COMPLIANT = "compliant"
    COMPLIANT_WITH_CONSTRAINTS = "compliant_with_constraints"
    NONCOMPLIANT = "noncompliant"
    UNKNOWN = "unknown"


class ComplianceBasis(str, Enum):
    """Basis for compliance determination - what evidence supports the finding."""
    TEST = "test"                                       # Specific test record cited
    ANALYSIS = "analysis"                               # Engineering analysis
    EVIDENCE_WEIGHTED_ANALYSIS = "evidence_weighted_analysis"  # H2 band selection
    POLICY = "policy"                                   # Family gate, policy decision
    INSPECTION = "inspection"
    SIMILARITY = "similarity"
    PRECEDENT = "precedent"
    NOT_APPLICABLE = "not_applicable"


class FailureMode(str, Enum):
    """
    Failure modes tracked by the compliance module.

    Maps to specific NASA-STD-6016C requirements and testing categories.
    """
    # Core failure modes
    FLAM = "flam"                       # Flammability (O2)
    HEE = "hee"                         # Hydrogen Environment Embrittlement
    TVS = "tvs"                         # Toxic Vapor Susceptibility
    SCC = "scc"                         # Stress Corrosion Cracking
    TOX = "tox"                         # Toxicity
    OFFGAS = "offgas"                   # Offgassing
    CORR = "corr"                       # Corrosion
    FS = "fs"                           # Fracture Strength/Toughness

    # O2-specific
    O2_PROHIBITED = "o2_prohibited"     # Material prohibited in O2 service
    O2_RESTRICTED = "o2_restricted"     # Material restricted in O2 service

    # Data quality
    TEST_CONDITION_MISMATCH = "test_condition_mismatch"
    MISSING_INPUT = "missing_input"


class GapTrigger(str, Enum):
    """
    What triggered the gap signal.

    Used to classify WHY a gap was raised, enabling appropriate response.
    """
    # Rating-based
    RATING_NON_A = "rating_non_a"

    # Policy-based
    PROHIBITED_FAMILY = "prohibited_family"
    RESTRICTED_POLICY = "restricted_policy"

    # Data quality
    MISSING_DATA = "missing_data"

    # Envelope-based
    ENVELOPE_OUTSIDE = "envelope_outside"
    CONFIGURATION_MISMATCH = "configuration_mismatch"

    # HEE-specific (deterministic from HEE band)
    HEE_BAND_SEVERE = "hee_band_severe"
    HEE_BAND_EXTREME = "hee_band_extreme"
    HEE_BAND_HIGH = "hee_band_high"


class GapSeverity(str, Enum):
    """
    Deterministic severity levels.

    Derived from HEE band or policy rules, NOT from human-generated text.
    """
    CRITICAL = "critical"   # HEE extreme/severe, O2 prohibited
    HIGH = "high"           # HEE high, significant gaps
    MEDIUM = "medium"       # HEE small, moderate gaps
    LOW = "low"             # HEE negligible, minor issues


class ConstraintSource(str, Enum):
    """Source of an operational constraint."""
    POLICY_CONSTRAINT = "policy_constraint"
    TEST_LIMIT = "test_limit"
    ANALYSIS_LIMIT = "analysis_limit"
    ENGINE_CONSTRAINT = "engine_constraint"


class SourceType(str, Enum):
    """
    Evidence source types.

    Fran Fix #2: Enables TEST vs POLICY basis selection without string parsing.
    """
    MAPTIS = "maptis"                       # MAPTIS database record
    TEST_REPORT = "test_report"             # Specific test report
    BOK = "bok"                             # Body of Knowledge (standards, handbooks)
    STANDARD = "standard"                   # NASA/industry standard
    MUA_PRECEDENT = "mua_precedent"         # Historical MUA
    ANALYSIS_REPORT = "analysis_report"     # Engineering analysis
    ENGINEERING_JUDGMENT = "engineering_judgment"  # Expert judgment


class RequiredAction(str, Enum):
    """Required action based on compliance status."""
    NONE = "none"                           # Compliant, no action needed
    ADD_CONSTRAINTS_SECTION = "add_constraints_section"  # Document constraints
    GENERATE_MUA = "generate_mua"           # MUA required
    ENGINEERING_REVIEW = "engineering_review"  # Human review needed
    PROVIDE_DATA = "provide_data"           # Missing data must be supplied
    SUBSTITUTE_MATERIAL = "substitute_material"  # Material cannot be used


class MUACategory(str, Enum):
    """MUA categorization per NASA-STD-6016C."""
    CATEGORY_1 = "1"    # High-risk (LOX, GOX >25%, P>300kPa)
    CATEGORY_2 = "2"    # Medium-risk (Standard oxygen environments)
    CATEGORY_3 = "3"    # Low-risk/specialized (Non-habitable)


class EnvironmentType(str, Enum):
    """Environment classification for routing decisions."""
    OXYGEN = "oxygen"           # O2 service (GOX, LOX)
    HYDROGEN = "hydrogen"       # H2 service (GH2, LH2)
    HABITABLE = "habitable"     # Crew-occupied spaces
    VACUUM = "vacuum"           # Space vacuum
    OTHER = "other"             # Other environments
