#!/usr/bin/env python3
"""
Module: NASA-STD-6016C Compliance Module
Purpose: Automates materials and processes compliance analysis

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
NASA-STD-6016C Compliance Module

Automates materials and processes compliance analysis by orchestrating
BoundState knowledge twins (H2, O2) and the MUA generator.

Architecture:
- Adapters: Emit signals (gaps, constraints, evidence) - DO NOT select MPRs
- Conductor: Maps signals to MPR determinations - ONLY place that does this

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from mira.compliance.models import (
    # Enums
    ApplicabilityStatus,
    ComplianceStatus,
    ComplianceBasis,
    FailureMode,
    GapTrigger,
    GapSeverity,
    ConstraintSource,
    SourceType,
    RequiredAction,
    # Core models
    EvidenceRef,
    GapSignal,
    OperationalConstraint,
    MaterialResolutionResult,
    # Policy
    EnvironmentPolicy,
    ConductorPolicy,
    # MPR
    MPRRecord,
    MPRIndex,
    # Adapter outputs
    O2AdapterOutput,
    H2AdapterOutput,
    MUAAdapterOutput,
    # Determination & Results
    MPRDetermination,
    MUALLMInvocation,
    RunManifest,
    ComplianceAnalysisResult,
)

__version__ = "2.0.0"
__all__ = [
    # Enums
    "ApplicabilityStatus",
    "ComplianceStatus",
    "ComplianceBasis",
    "FailureMode",
    "GapTrigger",
    "GapSeverity",
    "ConstraintSource",
    "SourceType",
    "RequiredAction",
    # Core models
    "EvidenceRef",
    "GapSignal",
    "OperationalConstraint",
    "MaterialResolutionResult",
    # Policy
    "EnvironmentPolicy",
    "ConductorPolicy",
    # MPR
    "MPRRecord",
    "MPRIndex",
    # Adapter outputs
    "O2AdapterOutput",
    "H2AdapterOutput",
    "MUAAdapterOutput",
    # Determination & Results
    "MPRDetermination",
    "MUALLMInvocation",
    "RunManifest",
    "ComplianceAnalysisResult",
]
