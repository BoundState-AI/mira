#!/usr/bin/env python3
"""
Module: Analysis Result Model
Purpose: Complete result of compliance analysis

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
NASA-STD-6016C Compliance Module - Analysis Result Model

ComplianceAnalysisResult: Complete result of compliance analysis.

This is the top-level output of the compliance module.

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
from typing import Any, Optional

from pydantic import BaseModel

from mira.compliance.models.adapter_outputs import MUAAdapterOutput
from mira.compliance.models.determination import MPRDetermination, MPRDeterminationSet
from mira.compliance.models.gaps import GapSummary, OperationalConstraint
from mira.compliance.models.manifest import RunManifest
from mira.compliance.models.policy import EnvironmentPolicy


class ComplianceSummary(BaseModel):
    """
    High-level summary of compliance analysis.

    Suitable for executive reporting.
    """

    # Overall status
    overall_status: str
    """Overall compliance status: 'compliant', 'noncompliant', 'partial', 'unknown'."""

    status_rationale: str
    """Explanation of overall status."""

    # Counts
    total_materials: int = 0
    """Total materials evaluated."""

    materials_compliant: int = 0
    """Materials fully compliant."""

    materials_noncompliant: int = 0
    """Materials with noncompliance."""

    materials_requiring_mua: int = 0
    """Materials requiring MUA."""

    # MPR summary
    total_mprs_applicable: int = 0
    """Total applicable MPRs."""

    mprs_compliant: int = 0
    """MPRs fully compliant."""

    mprs_compliant_with_constraints: int = 0
    """MPRs compliant with constraints."""

    mprs_noncompliant: int = 0
    """MPRs noncompliant."""

    # Gaps
    total_gaps: int = 0
    """Total gap signals."""

    critical_gaps: int = 0
    """Critical-severity gaps."""

    # Actions
    muas_required: int = 0
    """Number of MUAs required."""

    engineering_reviews_required: int = 0
    """Number of engineering reviews required."""

    model_config = {"extra": "forbid"}


class ComplianceAnalysisResult(BaseModel):
    """
    Complete result of compliance analysis.

    This is the top-level output of the compliance module.
    """

    # Plan identification
    plan_id: str
    """Identifier of the plan being analyzed."""

    plan_version: str
    """Version of the plan."""

    analysis_timestamp: datetime
    """When analysis was performed."""

    # Standard reference
    standard_version: str
    """Version of NASA-STD-6016C used."""

    mpr_index_version: str
    """Version of MPR index used."""

    # Policy used
    environment_policy: EnvironmentPolicy
    """Environment policy applied."""

    # Run manifest (complete audit trail)
    manifest: RunManifest
    """Complete audit trail of the analysis."""

    # MPR determinations (the core output)
    mpr_determinations: list[MPRDetermination] = []
    """All MPR determinations."""

    # MUA outputs
    mua_outputs: list[MUAAdapterOutput] = []
    """MUA drafts generated."""

    # Gap summaries by material
    gap_summaries: list[GapSummary] = []
    """Gap summaries per material/environment."""

    # Aggregated constraints
    all_constraints: list[OperationalConstraint] = []
    """All operational constraints across all materials."""

    # Summary
    summary: Optional[ComplianceSummary] = None
    """High-level summary."""

    model_config = {"extra": "forbid"}

    def compute_summary(self) -> ComplianceSummary:
        """Compute summary from determinations."""
        # Count MPR statuses
        applicable = [d for d in self.mpr_determinations if d.is_applicable()]
        compliant = sum(1 for d in applicable if d.is_compliant())
        compliant_constrained = sum(1 for d in applicable if d.is_compliant_with_constraints())
        noncompliant = sum(1 for d in applicable if d.is_noncompliant())

        # Count material statuses from manifest
        materials_compliant = 0
        materials_noncompliant = 0
        materials_requiring_mua = self.manifest.materials_requiring_mua

        # Determine overall status
        if noncompliant > 0:
            overall_status = "noncompliant"
            status_rationale = f"{noncompliant} MPRs are noncompliant"
        elif compliant_constrained > 0:
            overall_status = "partial"
            status_rationale = f"{compliant_constrained} MPRs require constraints"
        elif self.manifest.unknown_mprs > 0:
            overall_status = "unknown"
            status_rationale = f"{self.manifest.unknown_mprs} MPRs have unknown status"
        else:
            overall_status = "compliant"
            status_rationale = "All applicable MPRs are compliant"

        # Count gaps
        total_gaps = sum(len(d.gap_signals) for d in self.mpr_determinations)
        critical_gaps = sum(
            1 for d in self.mpr_determinations
            for g in d.gap_signals if g.is_critical()
        )

        # Count actions
        muas_required = sum(1 for d in self.mpr_determinations if d.mua_required)
        eng_reviews = sum(
            1 for d in self.mpr_determinations
            if d.required_action.value == "engineering_review"
        )

        self.summary = ComplianceSummary(
            overall_status=overall_status,
            status_rationale=status_rationale,
            total_materials=self.manifest.total_materials_evaluated,
            materials_compliant=materials_compliant,
            materials_noncompliant=materials_noncompliant,
            materials_requiring_mua=materials_requiring_mua,
            total_mprs_applicable=len(applicable),
            mprs_compliant=compliant,
            mprs_compliant_with_constraints=compliant_constrained,
            mprs_noncompliant=noncompliant,
            total_gaps=total_gaps,
            critical_gaps=critical_gaps,
            muas_required=muas_required,
            engineering_reviews_required=eng_reviews,
        )

        return self.summary

    def get_determination_set(
        self,
        material_id: str,
        environment_id: str,
    ) -> MPRDeterminationSet:
        """Get determination set for a specific material/environment."""
        # Filter determinations - this is a simplified implementation
        # In practice, determinations would be indexed by material/env
        relevant = [d for d in self.mpr_determinations]  # TODO: filter

        return MPRDeterminationSet(
            material_id=material_id,
            environment_id=environment_id,
            determinations=relevant,
        )

    def get_noncompliant_determinations(self) -> list[MPRDetermination]:
        """Get all noncompliant determinations."""
        return [d for d in self.mpr_determinations if d.is_noncompliant()]

    def get_determinations_requiring_mua(self) -> list[MPRDetermination]:
        """Get determinations requiring MUA."""
        return [d for d in self.mpr_determinations if d.mua_required]

    def has_critical_gaps(self) -> bool:
        """Check if any critical gaps exist."""
        for d in self.mpr_determinations:
            for g in d.gap_signals:
                if g.is_critical():
                    return True
        return False

    def is_fully_compliant(self) -> bool:
        """Check if fully compliant (all MPRs compliant, no constraints)."""
        applicable = [d for d in self.mpr_determinations if d.is_applicable()]
        return all(d.is_compliant() for d in applicable)

    def export_for_report(self) -> dict[str, Any]:
        """Export result in format suitable for report generation."""
        if not self.summary:
            self.compute_summary()

        return {
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "analysis_date": self.analysis_timestamp.isoformat(),
            "standard_version": f"NASA-STD-6016{self.standard_version}",
            "summary": self.summary.model_dump() if self.summary else None,
            "mprs": [d.format_for_report() for d in self.mpr_determinations],
            "muas": [m.model_dump() for m in self.mua_outputs],
            "constraints": [c.format_for_document() for c in self.all_constraints],
            "warnings": self.manifest.warnings,
            "errors": self.manifest.errors,
        }
