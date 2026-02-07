#!/usr/bin/env python3
"""
Module: Run Manifest Model
Purpose: Complete audit trail for compliance analysis runs

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
NASA-STD-6016C Compliance Module - Run Manifest Model

RunManifest: Complete audit trail for compliance analysis run.
MUALLMInvocation: Tracking for MUA LLM invocation.

Fran Fix #7: Log prompt, model, and inputs for reproducibility.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from mira.compliance.models.adapter_outputs import (
    H2AdapterOutput,
    MUAAdapterOutput,
    O2AdapterOutput,
)
from mira.compliance.models.policy import PolicyRoutingDecision
from mira.compliance.models.resolution import MaterialResolutionResult


class MUALLMInvocation(BaseModel):
    """
    Tracking for MUA LLM invocation.

    Fran Fix #7: Log prompt, model, and inputs for reproducibility.
    Every LLM call in MUA generation is tracked for audit.
    """

    invocation_id: str
    """Unique ID for this invocation."""

    material_id: str
    """Material being processed."""

    environment_id: str
    """Environment being processed."""

    # Model identity
    llm_model_id: str
    """Model identifier (e.g., 'claude-sonnet-4-20250514')."""

    # Prompt tracking
    prompt_template_version: str
    """Version of prompt template used."""

    prompt_hash: str
    """SHA-256 of actual prompt sent to LLM."""

    # Input tracking
    inputs_hash: str
    """SHA-256 of structured JSON inputs to LLM."""

    # Output tracking
    output_hash: str
    """SHA-256 of draft text from LLM."""

    # Timing
    timestamp: datetime
    """When invocation occurred."""

    latency_ms: int = 0
    """Response latency in milliseconds."""

    # Token counts
    input_tokens: int = 0
    """Number of input tokens."""

    output_tokens: int = 0
    """Number of output tokens."""

    model_config = {"extra": "forbid"}


class RunManifest(BaseModel):
    """
    Complete audit trail for compliance analysis run.

    Captures everything needed to reproduce and audit the analysis.
    This is the authoritative record of what happened.
    """

    # Run identity
    run_id: str
    """Unique identifier for this run."""

    run_timestamp: datetime
    """When the run started."""

    run_duration_ms: int = 0
    """Total run duration in milliseconds."""

    # Inputs with fingerprints
    inputs: list[dict[str, Any]] = []
    """Input documents/data with fingerprints."""

    # Material resolutions (authoritative)
    material_resolutions: list[MaterialResolutionResult] = []
    """How materials were resolved to canonical IDs."""

    # Routing decisions
    routing_decisions: list[PolicyRoutingDecision] = []
    """Which twins were invoked for each material/environment."""

    # Adapter outputs (not determinations - those come from conductor)
    o2_adapter_outputs: list[O2AdapterOutput] = []
    """Outputs from O2 adapter."""

    h2_adapter_outputs: list[H2AdapterOutput] = []
    """Outputs from H2 adapter."""

    mua_adapter_outputs: list[MUAAdapterOutput] = []
    """Outputs from MUA adapter."""

    # MUA LLM invocations (Fran Fix #7)
    mua_llm_invocations: list[MUALLMInvocation] = []
    """All LLM invocations for MUA generation."""

    # Policy versions
    environment_policy_version: str = ""
    """Version of environment policy used."""

    mpr_index_version: str = ""
    """Version of MPR index used."""

    conductor_policy_version: str = ""
    """Version of conductor policy used."""

    # Component versions
    o2_twin_version: str = ""
    """Version of O2 twin."""

    h2_twin_version: str = ""
    """Version of H2 twin."""

    mua_generator_version: str = ""
    """Version of MUA generator."""

    compliance_module_version: str = "2.0.0"
    """Version of compliance module."""

    # Summary counts
    total_mprs_evaluated: int = 0
    """Total MPRs evaluated."""

    applicable_mprs: int = 0
    """MPRs that were applicable."""

    not_applicable_by_condition_mprs: int = 0
    """MPRs not applicable by condition."""

    tailored_mprs: int = 0
    """MPRs tailored out."""

    compliant_mprs: int = 0
    """MPRs that are fully compliant."""

    compliant_with_constraints_mprs: int = 0
    """MPRs compliant with constraints."""

    noncompliant_mprs: int = 0
    """MPRs that are noncompliant."""

    unknown_mprs: int = 0
    """MPRs with unknown status."""

    total_materials_evaluated: int = 0
    """Total materials in the analysis."""

    materials_with_ambiguous_resolution: int = 0
    """Materials with ambiguous resolution."""

    materials_with_h2_token_risk: int = 0
    """Materials with H2 token match risk."""

    materials_requiring_mua: int = 0
    """Materials requiring MUA generation."""

    # Gap summary
    total_gap_signals: int = 0
    """Total gap signals generated."""

    critical_gaps: int = 0
    """Number of critical-severity gaps."""

    high_gaps: int = 0
    """Number of high-severity gaps."""

    # Decision log
    decision_log: list[dict[str, Any]] = []
    """Log of key decisions made during analysis."""

    # Outputs
    outputs: list[dict[str, Any]] = []
    """Generated outputs (reports, MUAs, etc.)."""

    # Warnings and errors
    warnings: list[str] = []
    """Warnings generated during analysis."""

    errors: list[str] = []
    """Errors encountered during analysis."""

    model_config = {"extra": "forbid"}

    def log_decision(self, decision_type: str, details: dict[str, Any]) -> None:
        """Add a decision to the log."""
        self.decision_log.append({
            "timestamp": datetime.now().isoformat(),
            "type": decision_type,
            **details,
        })

    def add_warning(self, warning: str) -> None:
        """Add a warning."""
        self.warnings.append(warning)

    def add_error(self, error: str) -> None:
        """Add an error."""
        self.errors.append(error)

    def update_summary_counts(
        self,
        total_mprs: int = 0,
        applicable: int = 0,
        not_applicable: int = 0,
        tailored: int = 0,
        compliant: int = 0,
        compliant_with_constraints: int = 0,
        noncompliant: int = 0,
        unknown: int = 0,
    ) -> None:
        """Update summary counts."""
        self.total_mprs_evaluated = total_mprs
        self.applicable_mprs = applicable
        self.not_applicable_by_condition_mprs = not_applicable
        self.tailored_mprs = tailored
        self.compliant_mprs = compliant
        self.compliant_with_constraints_mprs = compliant_with_constraints
        self.noncompliant_mprs = noncompliant
        self.unknown_mprs = unknown

    def has_errors(self) -> bool:
        """Check if any errors occurred."""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if any warnings were generated."""
        return len(self.warnings) > 0

    def get_completion_status(self) -> str:
        """Get overall completion status."""
        if self.errors:
            return "failed"
        if self.noncompliant_mprs > 0:
            return "completed_with_noncompliance"
        if self.unknown_mprs > 0:
            return "completed_with_unknowns"
        if self.warnings:
            return "completed_with_warnings"
        return "completed_successfully"
