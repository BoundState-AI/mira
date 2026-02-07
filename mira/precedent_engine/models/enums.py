#!/usr/bin/env python3
"""
Module: Enums
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

from enum import Enum
import uuid


class DeviationType(str, Enum):
    """
    High-level deviation categories from NASA-STD-6016.

    These represent the types of material property deviations that an MUA
    may address. A single MUA may cover multiple deviation types.
    """

    FLAMMABILITY = "flammability"
    OFFGASSING = "offgassing"
    TOXICITY = "toxicity"
    CORROSION = "corrosion"
    SCC = "stress_corrosion_cracking"
    COMPATIBILITY = "compatibility"
    TVS = "thermal_vacuum_stability"
    OTHER = "other"


class ProgramFamily(str, Enum):
    """
    Coarse program families for cross-program precedent rules.

    Precedent weight varies based on how closely related the source
    program is to the target program.
    """

    APOLLO = "apollo"
    SHUTTLE = "shuttle"
    ISS = "iss"
    ORION_ARTEMIS = "orion_artemis"
    COMMERCIAL_CREW = "commercial_crew"
    OTHER = "other"


class PrecedentAdequacyLevel(str, Enum):
    """
    Classification of precedent strength.

    This is a DETERMINISTIC classification computed by PrecedentEngine.
    LLM is NOT involved in this determination.

    STRONG: Safe to auto-draft; high confidence in precedent applicability
    MODERATE: Draft with warnings; additional engineering review recommended
    INSUFFICIENT: Escalate to manual; precedent base does not support auto-draft
    """

    STRONG = "strong"
    MODERATE = "moderate"
    INSUFFICIENT = "insufficient"


class EquivalenceMode(str, Enum):
    """
    How strictly to enforce equivalence rules.

    STRICT: All equivalence criteria must be met exactly
    ADVISORY: Criteria are evaluated but violations are warnings, not blocks
    OFF: Equivalence checking disabled for this dimension
    """

    STRICT = "strict"
    ADVISORY = "advisory"
    OFF = "off"


class LLMContribution(str, Enum):
    """
    How the LLM contributed to a rationale segment.

    Used for provenance tracking - every piece of generated text must
    indicate how it was derived from source precedents.

    COPIED: Text copied verbatim from a single precedent
    REPHRASED: Text rephrased from a single precedent (minor edits)
    MERGED: Text synthesized from multiple precedents
    GAP_FLAGGED: Gap identified - requires manual justification
    """

    COPIED = "copied"
    REPHRASED = "rephrased"
    MERGED = "merged"
    GAP_FLAGGED = "gap_flagged"
