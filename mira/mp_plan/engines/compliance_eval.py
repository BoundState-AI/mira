#!/usr/bin/env python3
"""
Module: Compliance Evaluation Engine (Engine C)
Purpose: Gap detection and compliance evaluation

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Engine C responsibilities:
- Evaluate materials against applicable MPRs
- Detect nonconformances (rating failures)
- Split gaps into Deficiency vs Nonconformance (V2)
- Track evidence for all evaluations

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from mira.compliance.models.enums import (
    ComplianceBasis,
    ComplianceStatus,
    FailureMode,
    GapSeverity,
    GapTrigger,
    SourceType,
)
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal

from ..models import (
    DecisionGraph,
    DeficiencySignal,
    EnvironmentDefinition,
    MaterialEntry,
    MaterialResolutionResult,
    NonconformanceSignal,
    PlanGeneratorSession,
    split_gap_signals,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


class ComplianceEvaluationEngine:
    """
    Engine C: Compliance Evaluation.

    Responsible for:
    - Evaluating materials against applicable MPRs
    - Detecting nonconformances from rating failures
    - Splitting gaps into V2 types (Deficiency vs Nonconformance)
    - Building MPR determinations
    """

    def evaluate_flammability(
        self,
        material: MaterialEntry,
        resolution: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> Optional[GapSignal]:
        """
        Evaluate flammability compliance.

        Args:
            material: Material entry.
            resolution: MAPTIS resolution.
            environment: Environment definition.

        Returns:
            GapSignal if nonconformance detected, None otherwise.
        """
        # Only check flammability in high O2 environments
        if environment.o2_pct <= 23.5:
            return None

        # A and B ratings are acceptable
        if resolution.flam_rating in ("A", "B"):
            return None

        # Determine severity based on rating
        if resolution.flam_rating in ("X", "D"):
            severity = GapSeverity.CRITICAL
        elif resolution.flam_rating == "C":
            severity = GapSeverity.HIGH
        else:
            severity = GapSeverity.MEDIUM

        # Create evidence reference
        evidence = EvidenceRef(
            source_type=SourceType.MAPTIS,
            source_id=f"MAPTIS:{resolution.maptis_code}",
            confidence=0.95,
            confidence_basis="Direct MAPTIS flammability test data",
            retrieved_at=datetime.now(),
            retrieval_method="compliance_engine",
        )

        return GapSignal(
            gap_id=f"FLAM:{material.id}:{environment.environment_id}",
            gap_type=FailureMode.FLAM,
            trigger=GapTrigger.RATING_NON_A,
            trigger_parameter="flam_rating",
            material_id=material.id,
            environment_id=environment.environment_id,
            failing_rating=resolution.flam_rating,
            test_value=resolution.test_o2_pct,
            severity=severity,
            confidence=0.95,
            evidence_refs=[evidence],
            summary=(
                f"Flammability rating {resolution.flam_rating} in "
                f"{environment.o2_pct}% O2 environment"
            ),
            source_adapter="compliance_eval_engine",
            suggested_basis=ComplianceBasis.TEST,
        )

    def evaluate_outgassing(
        self,
        material: MaterialEntry,
        resolution: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> Optional[GapSignal]:
        """
        Evaluate outgassing (TVS) compliance.

        Args:
            material: Material entry.
            resolution: MAPTIS resolution.
            environment: Environment definition.

        Returns:
            GapSignal if nonconformance detected, None otherwise.
        """
        # Check outgassing for vacuum or habitable environments
        if not (environment.vacuum_exposure or environment.habitable):
            return None

        # A rating is acceptable
        if resolution.tvs_rating == "A":
            return None

        # Create evidence reference
        evidence = EvidenceRef(
            source_type=SourceType.MAPTIS,
            source_id=f"MAPTIS:{resolution.maptis_code}",
            confidence=0.9,
            confidence_basis="Direct MAPTIS outgassing test data",
            retrieved_at=datetime.now(),
            retrieval_method="compliance_engine",
        )

        return GapSignal(
            gap_id=f"TVS:{material.id}:{environment.environment_id}",
            gap_type=FailureMode.TVS,
            trigger=GapTrigger.RATING_NON_A,
            trigger_parameter="tvs_rating",
            material_id=material.id,
            environment_id=environment.environment_id,
            failing_rating=resolution.tvs_rating,
            severity=GapSeverity.MEDIUM,
            confidence=0.9,
            evidence_refs=[evidence],
            summary=f"TVS rating {resolution.tvs_rating}",
            source_adapter="compliance_eval_engine",
            suggested_basis=ComplianceBasis.TEST,
        )

    def evaluate_toxicity(
        self,
        material: MaterialEntry,
        resolution: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> Optional[GapSignal]:
        """
        Evaluate toxicity compliance.

        Args:
            material: Material entry.
            resolution: MAPTIS resolution.
            environment: Environment definition.

        Returns:
            GapSignal if nonconformance detected, None otherwise.
        """
        # Only check toxicity in habitable environments
        if not environment.habitable:
            return None

        # A rating is acceptable
        if resolution.tox_rating == "A":
            return None

        # Create evidence reference
        evidence = EvidenceRef(
            source_type=SourceType.MAPTIS,
            source_id=f"MAPTIS:{resolution.maptis_code}",
            confidence=0.85,
            confidence_basis="Direct MAPTIS toxicity test data",
            retrieved_at=datetime.now(),
            retrieval_method="compliance_engine",
        )

        return GapSignal(
            gap_id=f"TOX:{material.id}:{environment.environment_id}",
            gap_type=FailureMode.TOX,
            trigger=GapTrigger.RATING_NON_A,
            trigger_parameter="tox_rating",
            material_id=material.id,
            environment_id=environment.environment_id,
            failing_rating=resolution.tox_rating,
            severity=GapSeverity.HIGH if environment.habitable else GapSeverity.MEDIUM,
            confidence=0.85,
            evidence_refs=[evidence],
            summary=f"Toxicity rating {resolution.tox_rating} in habitable volume",
            source_adapter="compliance_eval_engine",
            suggested_basis=ComplianceBasis.TEST,
        )

    def evaluate_material_in_environment(
        self,
        material: MaterialEntry,
        resolution: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> list[GapSignal]:
        """
        Evaluate a material in a specific environment.

        Args:
            material: Material entry.
            resolution: MAPTIS resolution.
            environment: Environment definition.

        Returns:
            List of gap signals detected.
        """
        gaps = []

        # Check flammability
        flam_gap = self.evaluate_flammability(material, resolution, environment)
        if flam_gap:
            gaps.append(flam_gap)

        # Check outgassing
        tvs_gap = self.evaluate_outgassing(material, resolution, environment)
        if tvs_gap:
            gaps.append(tvs_gap)

        # Check toxicity
        tox_gap = self.evaluate_toxicity(material, resolution, environment)
        if tox_gap:
            gaps.append(tox_gap)

        return gaps

    def build_mpr_determination(
        self,
        mpr_id: str,
        material: MaterialEntry,
        environment: EnvironmentDefinition,
        gaps: list[GapSignal],
    ) -> dict[str, Any]:
        """
        Build MPR determination from gaps.

        Args:
            mpr_id: MPR identifier.
            material: Material entry.
            environment: Environment definition.
            gaps: Related gap signals.

        Returns:
            MPR determination dict.
        """
        # Determine compliance status from gaps
        if not gaps:
            status = ComplianceStatus.COMPLIANT
            basis = ComplianceBasis.TEST
        elif any(g.severity == GapSeverity.CRITICAL for g in gaps):
            status = ComplianceStatus.NONCOMPLIANT
            basis = ComplianceBasis.TEST
        else:
            status = ComplianceStatus.COMPLIANT_WITH_CONSTRAINTS
            basis = ComplianceBasis.TEST

        return {
            "mpr_id": mpr_id,
            "material_id": material.id,
            "environment_id": environment.environment_id,
            "status": status.value,
            "basis": basis.value,
            "gap_ids": [g.gap_id for g in gaps],
            "evaluated_at": datetime.now().isoformat(),
        }

    def run(
        self,
        session: PlanGeneratorSession,
    ) -> tuple[list[DeficiencySignal], list[NonconformanceSignal], list[dict[str, Any]]]:
        """
        Run compliance evaluation on session.

        Args:
            session: Plan generator session.

        Returns:
            Tuple of (deficiencies, nonconformances, mpr_determinations).
        """
        LOGGER.info("Running compliance evaluation")

        all_gaps = []
        determinations = []

        for usage in session.material_environment_usages:
            material = session.get_material(usage.material_id)
            resolution = session.get_resolution(usage.material_id)
            environment = session.get_environment(usage.environment_id)

            if not material or not environment:
                continue

            if not resolution:
                # Create deficiency for missing resolution
                all_gaps.append(
                    GapSignal(
                        gap_id=f"MISSING:{material.id}",
                        gap_type=FailureMode.MISSING_INPUT,
                        trigger=GapTrigger.MISSING_DATA,
                        trigger_parameter="maptis_resolution",
                        material_id=material.id,
                        severity=GapSeverity.HIGH,
                        confidence=1.0,
                        summary=f"Material {material.name} not resolved in MAPTIS",
                        source_adapter="compliance_eval_engine",
                        suggested_basis=ComplianceBasis.NOT_APPLICABLE,
                    )
                )
                continue

            # Evaluate material in environment
            gaps = self.evaluate_material_in_environment(
                material, resolution, environment
            )
            all_gaps.extend(gaps)

            # Build MPR determinations
            flam_gaps = [g for g in gaps if g.gap_type == FailureMode.FLAM]
            tvs_gaps = [g for g in gaps if g.gap_type == FailureMode.TVS]
            tox_gaps = [g for g in gaps if g.gap_type == FailureMode.TOX]

            if session.applicability_matrix:
                key = f"{material.id}:{environment.environment_id}"
                applicability = session.applicability_matrix.get(key, {})

                if "MPR_44" in applicability:
                    determinations.append(
                        self.build_mpr_determination(
                            "MPR_44", material, environment, flam_gaps
                        )
                    )

                if "MPR_67" in applicability:
                    determinations.append(
                        self.build_mpr_determination(
                            "MPR_67", material, environment, tvs_gaps
                        )
                    )

                if "MPR_89" in applicability:
                    determinations.append(
                        self.build_mpr_determination(
                            "MPR_89", material, environment, tox_gaps
                        )
                    )

        # Split gaps into V2 types
        deficiencies, nonconformances = split_gap_signals(all_gaps)

        LOGGER.info(
            f"Compliance evaluation complete: "
            f"{len(deficiencies)} deficiencies, "
            f"{len(nonconformances)} nonconformances, "
            f"{len(determinations)} determinations"
        )

        return deficiencies, nonconformances, determinations


def get_compliance_eval_engine() -> ComplianceEvaluationEngine:
    """Get a compliance evaluation engine instance."""
    return ComplianceEvaluationEngine()
