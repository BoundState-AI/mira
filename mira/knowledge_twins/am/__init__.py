"""
Module: AM Knowledge Twin (Demo Track) -- package exports
Purpose: Public surface for the AM Qualification & Compliance Accelerator
         per BS-SPEC-MIRA-AMTWIN-001-REV5.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Coding Standards), SWE-032 (Data Validation),
            SWE-033 (Requirements Traceability), NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from mira.knowledge_twins.am.am_models import (
    AccessContext,
    AMPartClass,
    AMProcess,
    AMRequest,
    ClassificationInput,
    ClassificationPolicy,
    ConsequenceTier,
    DataClassification,
    HazardFlag,
    MaterialType,
    RulePackRef,
)
from mira.knowledge_twins.am.rule_pack_models import (
    ClauseRef,
    CorpusManifest,
    FrozenRulePack,
    PackRequirement,
    PlaceholderStandard,
    VerificationStatus,
)

__all__ = [
    "AccessContext",
    "AMPartClass",
    "AMProcess",
    "AMRequest",
    "ClassificationInput",
    "ClassificationPolicy",
    "ClauseRef",
    "ConsequenceTier",
    "CorpusManifest",
    "DataClassification",
    "FrozenRulePack",
    "HazardFlag",
    "MaterialType",
    "PackRequirement",
    "PlaceholderStandard",
    "RulePackRef",
    "VerificationStatus",
]
