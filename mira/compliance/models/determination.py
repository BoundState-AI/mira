#!/usr/bin/env python3
"""
Module: MPR Determination Model
Purpose: Compliance determination for NASA-STD-6016C MPRs

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
NASA-STD-6016C Compliance Module - MPR Determination Model

MPRDetermination: Compliance determination for a single MPR.

IMPORTANT: Only the Conductor creates these, never the adapters.

Fran Fix #1: Adapters emit signals only, conductor creates determinations.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from typing import Optional

from pydantic import BaseModel

from mira.compliance.models.enums import (
    ApplicabilityStatus,
    ComplianceBasis,
    ComplianceStatus,
    RequiredAction,
)
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal, OperationalConstraint


class MPRDetermination(BaseModel):
    """
    Compliance determination for a single MPR.

    Created by the Conductor based on signals from adapters.
    This is the output of the signal → MPR mapping process.

    IMPORTANT: Only the Conductor creates these, never the adapters.
    """

    # MPR identity
    mpr_number: int
    """MPR number from NASA-STD-6016C."""

    mpr_section: str
    """Section reference in the standard."""

    mpr_title: str
    """MPR title/name."""

    mpr_source_evidence: EvidenceRef
    """Evidence reference for the MPR itself."""

    # Applicability determination
    applicability_status: ApplicabilityStatus
    """Whether this MPR applies to the material/environment."""

    applicability_rationale: str
    """Why this applicability status was determined."""

    # Compliance determination (only if applicable)
    compliant: ComplianceStatus = ComplianceStatus.UNKNOWN
    """Compliance status for this MPR."""

    compliance_basis: ComplianceBasis = ComplianceBasis.NOT_APPLICABLE
    """Basis for compliance determination."""

    compliance_rationale: Optional[str] = None
    """Explanation of compliance determination."""

    # Gap signals attached to this MPR
    gap_signals: list[GapSignal] = []
    """Gap signals that affect this MPR's compliance."""

    # Operational constraints
    operational_constraints: list[OperationalConstraint] = []
    """Constraints required for COMPLIANT_WITH_CONSTRAINTS status."""

    # Required action
    required_action: RequiredAction = RequiredAction.NONE
    """What action is required based on determination."""

    required_action_rationale: Optional[str] = None
    """Why this action is required."""

    # MUA linkage (if MUA was generated)
    mua_required: bool = False
    """Whether an MUA is required for this MPR."""

    mua_draft_id: Optional[str] = None
    """ID of MUA draft if generated."""

    # Evidence summary
    supporting_evidence: list[EvidenceRef] = []
    """All evidence supporting this determination."""

    model_config = {"extra": "forbid"}

    def is_applicable(self) -> bool:
        """Check if MPR is applicable."""
        return self.applicability_status == ApplicabilityStatus.APPLICABLE

    def is_compliant(self) -> bool:
        """Check if fully compliant (no constraints)."""
        return self.compliant == ComplianceStatus.COMPLIANT

    def is_compliant_with_constraints(self) -> bool:
        """Check if compliant with constraints."""
        return self.compliant == ComplianceStatus.COMPLIANT_WITH_CONSTRAINTS

    def is_noncompliant(self) -> bool:
        """Check if noncompliant."""
        return self.compliant == ComplianceStatus.NONCOMPLIANT

    def has_gaps(self) -> bool:
        """Check if any gaps are attached."""
        return len(self.gap_signals) > 0

    def has_constraints(self) -> bool:
        """Check if any operational constraints exist."""
        return len(self.operational_constraints) > 0

    def get_worst_gap_severity(self) -> Optional[str]:
        """Get the worst severity among attached gaps."""
        if not self.gap_signals:
            return None

        severity_order = ["low", "medium", "high", "critical"]
        worst_idx = -1
        worst = None

        for gap in self.gap_signals:
            sev = gap.severity.value.lower()
            if sev in severity_order:
                idx = severity_order.index(sev)
                if idx > worst_idx:
                    worst_idx = idx
                    worst = sev

        return worst

    def format_for_report(self) -> str:
        """Format determination for inclusion in compliance report."""
        lines = [
            f"MPR {self.mpr_number}: {self.mpr_title}",
            f"  Section: {self.mpr_section}",
            f"  Applicability: {self.applicability_status.value}",
        ]

        if self.is_applicable():
            lines.extend([
                f"  Compliance: {self.compliant.value}",
                f"  Basis: {self.compliance_basis.value}",
            ])

            if self.compliance_rationale:
                lines.append(f"  Rationale: {self.compliance_rationale}")

            if self.has_gaps():
                lines.append(f"  Gaps: {len(self.gap_signals)}")

            if self.has_constraints():
                lines.append(f"  Constraints: {len(self.operational_constraints)}")

            if self.required_action != RequiredAction.NONE:
                lines.append(f"  Required Action: {self.required_action.value}")

        return "\n".join(lines)


class MPRDeterminationSet(BaseModel):
    """
    Collection of MPR determinations for a compliance analysis.

    Provides rollup statistics and filtering capabilities.
    """

    # Context
    material_id: str
    """Material being evaluated."""

    environment_id: str
    """Environment being evaluated."""

    # Determinations
    determinations: list[MPRDetermination] = []
    """List of MPR determinations."""

    model_config = {"extra": "forbid"}

    @property
    def total_mprs(self) -> int:
        """Total number of MPRs evaluated."""
        return len(self.determinations)

    @property
    def applicable_count(self) -> int:
        """Number of applicable MPRs."""
        return sum(1 for d in self.determinations if d.is_applicable())

    @property
    def compliant_count(self) -> int:
        """Number of fully compliant MPRs."""
        return sum(1 for d in self.determinations if d.is_compliant())

    @property
    def compliant_with_constraints_count(self) -> int:
        """Number of MPRs compliant with constraints."""
        return sum(1 for d in self.determinations if d.is_compliant_with_constraints())

    @property
    def noncompliant_count(self) -> int:
        """Number of noncompliant MPRs."""
        return sum(1 for d in self.determinations if d.is_noncompliant())

    @property
    def unknown_count(self) -> int:
        """Number of MPRs with unknown compliance."""
        return sum(1 for d in self.determinations
                   if d.is_applicable() and d.compliant == ComplianceStatus.UNKNOWN)

    def get_applicable(self) -> list[MPRDetermination]:
        """Get all applicable determinations."""
        return [d for d in self.determinations if d.is_applicable()]

    def get_noncompliant(self) -> list[MPRDetermination]:
        """Get all noncompliant determinations."""
        return [d for d in self.determinations if d.is_noncompliant()]

    def get_requiring_mua(self) -> list[MPRDetermination]:
        """Get determinations requiring MUA."""
        return [d for d in self.determinations if d.mua_required]

    def get_by_mpr_number(self, mpr_number: int) -> Optional[MPRDetermination]:
        """Get determination by MPR number."""
        for d in self.determinations:
            if d.mpr_number == mpr_number:
                return d
        return None

    def all_compliant(self) -> bool:
        """Check if all applicable MPRs are compliant."""
        applicable = self.get_applicable()
        return all(d.is_compliant() or d.is_compliant_with_constraints() for d in applicable)

    def has_noncompliant(self) -> bool:
        """Check if any MPRs are noncompliant."""
        return self.noncompliant_count > 0

    def get_required_actions(self) -> list[RequiredAction]:
        """Get unique required actions across all determinations."""
        actions = set()
        for d in self.determinations:
            if d.required_action != RequiredAction.NONE:
                actions.add(d.required_action)
        return list(actions)

    def get_all_constraints(self) -> list[OperationalConstraint]:
        """Get all operational constraints from all determinations."""
        constraints = []
        for d in self.determinations:
            constraints.extend(d.operational_constraints)
        return constraints

    def get_all_gap_signals(self) -> list[GapSignal]:
        """Get all gap signals from all determinations."""
        signals = []
        for d in self.determinations:
            signals.extend(d.gap_signals)
        return signals
