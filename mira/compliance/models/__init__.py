#!/usr/bin/env python3
"""
Module: Models Package
Purpose: All data models for the compliance module

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
NASA-STD-6016C Compliance Module - Models Package

All data models for the compliance module.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

# Enums
from mira.compliance.models.enums import (
    ApplicabilityStatus,
    ComplianceBasis,
    ComplianceStatus,
    ConstraintSource,
    EnvironmentType,
    FailureMode,
    GapSeverity,
    GapTrigger,
    MUACategory,
    RequiredAction,
    SourceType,
)

# Evidence
from mira.compliance.models.evidence import (
    EvidenceCollection,
    EvidenceRef,
)

# Gaps and Constraints
from mira.compliance.models.gaps import (
    GapSignal,
    GapSummary,
    OperationalConstraint,
)

# Material Resolution
from mira.compliance.models.resolution import (
    MaterialResolutionBatch,
    MaterialResolutionResult,
)

# Policy
from mira.compliance.models.policy import (
    ConductorPolicy,
    EnvironmentDefinition,
    EnvironmentPolicy,
    PolicyRoutingDecision,
)

# MPR
from mira.compliance.models.mpr import (
    MPRIndex,
    MPRRecord,
    create_mpr_index_from_yaml,
)

# Adapter Outputs
from mira.compliance.models.adapter_outputs import (
    H2AdapterOutput,
    MUAAdapterOutput,
    O2AdapterOutput,
    PrecedentValidation,
)

# Determinations
from mira.compliance.models.determination import (
    MPRDetermination,
    MPRDeterminationSet,
)

# Manifest
from mira.compliance.models.manifest import (
    MUALLMInvocation,
    RunManifest,
)

# Results
from mira.compliance.models.result import (
    ComplianceAnalysisResult,
    ComplianceSummary,
)


__all__ = [
    # Enums
    "ApplicabilityStatus",
    "ComplianceBasis",
    "ComplianceStatus",
    "ConstraintSource",
    "EnvironmentType",
    "FailureMode",
    "GapSeverity",
    "GapTrigger",
    "MUACategory",
    "RequiredAction",
    "SourceType",
    # Evidence
    "EvidenceCollection",
    "EvidenceRef",
    # Gaps and Constraints
    "GapSignal",
    "GapSummary",
    "OperationalConstraint",
    # Material Resolution
    "MaterialResolutionBatch",
    "MaterialResolutionResult",
    # Policy
    "ConductorPolicy",
    "EnvironmentDefinition",
    "EnvironmentPolicy",
    "PolicyRoutingDecision",
    # MPR
    "MPRIndex",
    "MPRRecord",
    "create_mpr_index_from_yaml",
    # Adapter Outputs
    "H2AdapterOutput",
    "MUAAdapterOutput",
    "O2AdapterOutput",
    "PrecedentValidation",
    # Determinations
    "MPRDetermination",
    "MPRDeterminationSet",
    # Manifest
    "MUALLMInvocation",
    "RunManifest",
    # Results
    "ComplianceAnalysisResult",
    "ComplianceSummary",
]
