#!/usr/bin/env python3
"""
Module: H2 Adapter
Purpose: Adapter for the H2 (Hydrogen) Knowledge Twin

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
NASA-STD-6016C Compliance Module - H2 Adapter

Adapter for the H2 (Hydrogen) Knowledge Twin.

IMPORTANT: Emits signals only, NOT MPRDetermination.
That's the conductor's job.

Fran Fix #1: Adapters emit signals only, conductor maps to MPRs.
Fran Fix #4: Uses deterministic HEE band → severity mapping.
Fran Fix #5: Uses canonical_name from resolver, not raw input.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

import logging
from datetime import datetime
from typing import Any, List, Optional

from mira.compliance.adapters.base import BaseAdapter

LOGGER = logging.getLogger(__name__)
from mira.compliance.id_utils import compute_constraint_id, compute_gap_id
from mira.compliance.models.adapter_outputs import H2AdapterOutput
from mira.compliance.models.enums import (
    ComplianceBasis,
    ConstraintSource,
    FailureMode,
    GapSeverity,
    GapTrigger,
    SourceType,
)
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal, OperationalConstraint
from mira.compliance.models.policy import EnvironmentDefinition
from mira.compliance.models.resolution import MaterialResolutionResult
from mira.compliance.severity import hee_band_to_trigger, quantize_hee_severity

# Import H2 twin types (from existing codebase)
try:
    from mira.knowledge_twins.types import (
        Verdict,
        HEEBand,
        Driver,
        Constraint as H2Constraint,
        Gap as H2Gap,
        EvidenceObject,
    )
    from mira.knowledge_twins.h2.query import H2Response
except ImportError:
    # Fallback for standalone testing
    from enum import Enum

    class Verdict(str, Enum):
        ALLOWED = "allowed"
        ALLOWED_WITH_CONSTRAINTS = "allowed_with_constraints"
        NOT_RECOMMENDED = "not_recommended"
        UNKNOWN = "unknown"

    class HEEBand(str, Enum):
        NEGLIGIBLE = "negligible"
        SMALL = "small"
        HIGH = "high"
        SEVERE = "severe"
        EXTREME = "extreme"

    class Driver:
        def __init__(self):
            self.failure_mode = ""
            self.severity = ""
            self.trigger_parameter = ""
            self.explanation = ""
            self.evidence_ids = []

    class H2Constraint:
        def __init__(self):
            self.parameter = ""
            self.limit_type = ""
            self.limit_value = ""
            self.rationale = ""
            self.evidence_id = None

    class H2Gap:
        def __init__(self):
            self.parameter = ""
            self.impact = ""
            self.default_assumption = None

    class EvidenceObject:
        def __init__(self):
            self.evidence_id = ""
            self.hee_band = None

    class H2Response:
        def __init__(self):
            self.verdict = Verdict.UNKNOWN
            self.confidence = 0.5
            self.drivers = []
            self.constraints = []
            self.gaps = []
            self.evidence = []
            self.audit = None


# Import H2 Knowledge Twin
try:
    from mira.h2 import evaluate_h2_compatibility
    from mira.h2.models import H2CompatibilityRequest, HydrogenPhase, H2CompatibilityResponse
    from core.models.answer import AnswerSeverity
    H2_TWIN_AVAILABLE = True
except ImportError:
    LOGGER.warning("H2 Knowledge Twin not available")
    H2_TWIN_AVAILABLE = False


def _f_to_k(fahrenheit: float) -> float:
    """Convert Fahrenheit to Kelvin."""
    return (fahrenheit - 32) * 5 / 9 + 273.15


class H2Adapter(BaseAdapter):
    """
    Adapter for H2 Knowledge Twin.

    Converts H2 twin responses to compliance module signals.

    IMPORTANT:
    - Does NOT select MPRs
    - Uses canonical_name from resolver, not raw input (Fran Fix #5)
    - Uses deterministic HEE band → severity mapping (Fran Fix #4)
    """

    def __init__(self, h2_engine=None, version: str = "1.0.0"):
        """
        Initialize H2 adapter.

        Args:
            h2_engine: H2 engine instance (optional, for testing)
            version: Adapter version
        """
        super().__init__(version=version)
        self._h2_engine = h2_engine

    def evaluate(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> H2AdapterOutput:
        """
        Evaluate material in H2 environment.

        Fran Fix #5: Uses canonical_name from resolver, not raw input.

        Args:
            material: Resolved material information
            environment: Environment definition

        Returns:
            H2AdapterOutput with signals, constraints, and evidence
        """
        if not material.resolved:
            return self._create_unresolved_output(material, environment)

        # Call H2 twin if custom engine provided
        if self._h2_engine:
            h2_response = self._call_h2_twin(material, environment)
            return self._adapt_h2_response(h2_response, material, environment)

        # Use real H2 Knowledge Twin if available
        if H2_TWIN_AVAILABLE:
            return self._call_real_h2_twin(material, environment)

        # Return placeholder when no twin available
        return self._create_placeholder_output(material, environment)

    def _call_h2_twin(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> H2Response:
        """
        Call the H2 Knowledge Twin (custom engine).

        Fran Fix #5: Uses canonical_name, not raw input.

        Args:
            material: Resolved material
            environment: Environment definition

        Returns:
            H2 engine response
        """
        # Build query using canonical_name (Fran Fix #5)
        query_name = material.get_h2_query_name()

        # This would call the actual H2 engine
        # For now, return a mock response
        return H2Response()

    def _call_real_h2_twin(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> H2AdapterOutput:
        """
        Call the real H2 Knowledge Twin via evaluate_h2_compatibility.

        Args:
            material: Resolved material
            environment: Environment definition

        Returns:
            H2AdapterOutput with twin evaluation results
        """
        try:
            # Determine phase from environment
            phase = HydrogenPhase.LIQUID if environment.is_cryogenic else HydrogenPhase.GAS

            # Convert temperature from Fahrenheit to Kelvin
            temp_f = environment.temperature_min_f or 70.0
            temp_k = _f_to_k(temp_f)

            # Build H2 request
            request = H2CompatibilityRequest(
                question=f"Is {material.canonical_name} compatible with hydrogen?",
                material_key=material.canonical_name or material.input_material_name or "",
                pressure_psia=environment.pressure_psia or 14.7,
                temperature_k=temp_k,
                phase=phase,
            )

            # Call the H2 twin
            LOGGER.info(f"Calling H2 twin for {material.canonical_name}")
            response = evaluate_h2_compatibility(request)

            # Convert H2CompatibilityResponse to H2AdapterOutput
            return self._adapt_real_h2_response(response, material, environment)

        except Exception as e:
            LOGGER.error(f"H2 twin evaluation failed: {e}")
            # Return placeholder on error
            return self._create_placeholder_output(material, environment)

    def _adapt_real_h2_response(
        self,
        response: "H2CompatibilityResponse",
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> H2AdapterOutput:
        """
        Convert H2CompatibilityResponse to H2AdapterOutput.

        Uses embrittlement_risk and band_distribution to determine HEE severity.
        """
        gap_signals = []
        evidence_refs = []
        constraints = []

        # Convert evidence from response
        for ev in response.evidence:
            evidence_refs.append(self._create_evidence_ref(
                source_id=ev.source_id,
                locator=ev.location,
                quote=ev.summary[:500] if ev.summary else None,
                confidence=0.9,
                confidence_basis="H2 Knowledge Twin evaluation",
                retrieval_method="h2_twin_engine",
            ))

        # Determine HEE band from embrittlement_risk
        hee_band = self._map_embrittlement_risk_to_band(response.embrittlement_risk)

        # Determine suggested basis
        has_test_evidence = any(e.supports_test_basis() for e in evidence_refs)
        suggested_basis = ComplianceBasis.TEST if has_test_evidence else ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS

        # Generate gap signals for non-OK classifications
        if response.classification in [AnswerSeverity.CAUTION, AnswerSeverity.PROHIBITED]:
            severity = quantize_hee_severity(hee_band) if hee_band else GapSeverity.HIGH
            trigger = hee_band_to_trigger(hee_band)

            gap_signals.append(GapSignal(
                gap_id=compute_gap_id(
                    material.canonical_material_id or "",
                    environment.environment_id,
                    FailureMode.HEE,
                    trigger,
                    response.embrittlement_risk,
                ),
                gap_type=FailureMode.HEE,
                trigger=trigger,
                trigger_parameter="hee_index",
                material_id=material.canonical_material_id or "",
                environment_id=environment.environment_id,
                hee_band=hee_band,
                severity=severity,
                confidence=response.h2_score if response.h2_score else 0.8,
                evidence_refs=evidence_refs,
                summary=response.rationale,
                source_adapter="h2_adapter",
                suggested_basis=suggested_basis,
            ))

        # Map verdict to output format
        verdict_map = {
            AnswerSeverity.OK: "ALLOWED",
            AnswerSeverity.CAUTION: "ALLOWED_WITH_CONSTRAINTS",
            AnswerSeverity.PROHIBITED: "NOT_RECOMMENDED",
            AnswerSeverity.UNKNOWN: "UNKNOWN",
        }

        return H2AdapterOutput(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            verdict=verdict_map.get(response.classification, "UNKNOWN"),
            confidence=response.h2_score if response.h2_score else 0.5,
            match_confidence=material.resolution_confidence,
            envelope_confidence=response.h2_score if response.h2_score else 0.5,
            gap_signals=gap_signals,
            operational_constraints=constraints,
            evidence_refs=evidence_refs,
            suggested_basis=suggested_basis,
            h2_token_match_risk=material.h2_token_match_risk,
            raw_response={
                "classification": response.classification.value,
                "rationale": response.rationale,
                "embrittlement_risk": response.embrittlement_risk,
                "h2_score": response.h2_score,
                "band_distribution": response.band_distribution,
            },
        )

    def _map_embrittlement_risk_to_band(self, risk: Optional[str]) -> Optional[str]:
        """Map embrittlement_risk to HEE band."""
        if not risk:
            return None
        risk_lower = risk.lower()
        # Map embrittlement risk levels to HEE bands
        mapping = {
            "low": "negligible",
            "medium": "small",
            "high": "high",
            "severe": "severe",
            "extreme": "extreme",
        }
        return mapping.get(risk_lower, risk_lower)

    def _adapt_h2_response(
        self,
        h2_response: H2Response,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> H2AdapterOutput:
        """
        Convert H2 twin response to adapter output.

        IMPORTANT:
        - Does NOT select MPRs
        - Uses canonical_name from resolver (Fran Fix #5)
        - Uses deterministic HEE band → severity mapping (Fran Fix #4)
        """
        gap_signals = []
        constraints = []
        evidence_refs = []

        # Convert H2 evidence
        for ev in h2_response.evidence:
            evidence_refs.append(self._convert_h2_evidence(ev))

        # Get worst HEE band from dominant evidence (Fran Fix #4)
        worst_hee_band = self._get_worst_hee_band(h2_response)

        # Generate GapSignals from drivers
        for driver in h2_response.drivers:
            gap_signals.append(self._create_driver_gap_signal(
                driver=driver,
                worst_hee_band=worst_hee_band,
                material=material,
                environment=environment,
                evidence_refs=evidence_refs,
                h2_response=h2_response,
            ))

        # Generate GapSignals from gaps (info gaps)
        for gap in h2_response.gaps:
            gap_signals.append(self._create_info_gap_signal(
                gap=gap,
                material=material,
                environment=environment,
            ))

        # Convert constraints (Fran Fix #6: hash-based IDs)
        for c in h2_response.constraints:
            constraints.append(self._convert_constraint(
                constraint=c,
                material=material,
                evidence_refs=evidence_refs,
            ))

        # Compute confidence split
        match_confidence = self._compute_match_confidence(h2_response, material)
        envelope_confidence = self._compute_envelope_confidence(h2_response)

        return H2AdapterOutput(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            verdict=h2_response.verdict.value.upper(),
            confidence=h2_response.confidence,
            match_confidence=match_confidence,
            envelope_confidence=envelope_confidence,
            gap_signals=gap_signals,
            operational_constraints=constraints,
            evidence_refs=evidence_refs,
            suggested_basis=ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS,
            h2_token_match_risk=material.h2_token_match_risk,
            raw_response={
                "verdict": h2_response.verdict.value,
                "confidence": h2_response.confidence,
            },
        )

    def _convert_h2_evidence(self, ev: EvidenceObject) -> EvidenceRef:
        """Convert H2 evidence object to EvidenceRef."""
        return self._create_evidence_ref(
            source_id=ev.evidence_id,
            confidence=0.9,
            confidence_basis="H2 Knowledge Twin evidence",
            retrieval_method="h2_twin_engine",
        )

    def _get_worst_hee_band(self, h2_response: H2Response) -> Optional[str]:
        """
        Get worst HEE band from dominant evidence.

        Fran Fix #4: Use deterministic band selection.
        """
        band_order = ["negligible", "small", "high", "severe", "extreme"]
        worst_idx = -1
        worst_band = None

        # Use audit trail's dominant evidence IDs if available
        dominant_ids = set()
        if h2_response.audit:
            dominant_ids = set(getattr(h2_response.audit, 'dominant_evidence_ids', []))

        for ev in h2_response.evidence:
            if dominant_ids and ev.evidence_id not in dominant_ids:
                continue
            if ev.hee_band:
                band_value = ev.hee_band.value if hasattr(ev.hee_band, 'value') else str(ev.hee_band)
                band_lower = band_value.lower()
                if band_lower in band_order:
                    idx = band_order.index(band_lower)
                    if idx > worst_idx:
                        worst_idx = idx
                        worst_band = band_lower

        return worst_band

    def _create_driver_gap_signal(
        self,
        driver: Driver,
        worst_hee_band: Optional[str],
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        evidence_refs: list[EvidenceRef],
        h2_response: H2Response,
    ) -> GapSignal:
        """Create gap signal from H2 driver."""
        # Use deterministic severity from HEE band, not driver.severity text (Fran Fix #4)
        severity = quantize_hee_severity(worst_hee_band) if worst_hee_band else GapSeverity.HIGH

        trigger = hee_band_to_trigger(worst_hee_band)

        # Filter evidence for this driver
        driver_evidence = [
            e for e in evidence_refs
            if e.source_id in driver.evidence_ids
        ]

        return GapSignal(
            gap_id=compute_gap_id(
                material.canonical_material_id or "",
                environment.environment_id,
                FailureMode.HEE,
                trigger,
                driver.failure_mode,
            ),
            gap_type=FailureMode.HEE,
            trigger=trigger,
            trigger_parameter=driver.trigger_parameter,
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            hee_band=worst_hee_band,
            severity=severity,
            confidence=h2_response.confidence,
            evidence_refs=driver_evidence,
            summary=driver.explanation,
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS,
        )

    def _create_info_gap_signal(
        self,
        gap: H2Gap,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> GapSignal:
        """Create gap signal from H2 info gap."""
        return GapSignal(
            gap_id=compute_gap_id(
                material.canonical_material_id or "",
                environment.environment_id,
                FailureMode.MISSING_INPUT,
                GapTrigger.MISSING_DATA,
                gap.parameter,
            ),
            gap_type=FailureMode.MISSING_INPUT,
            trigger=GapTrigger.MISSING_DATA,
            trigger_parameter=gap.parameter,
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            severity=GapSeverity.MEDIUM,
            confidence=0.8,
            evidence_refs=[],
            summary=f"Missing {gap.parameter}: {gap.impact}",
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS,
        )

    def _convert_constraint(
        self,
        constraint: H2Constraint,
        material: MaterialResolutionResult,
        evidence_refs: list[EvidenceRef],
    ) -> OperationalConstraint:
        """Convert H2 constraint to OperationalConstraint."""
        # Find evidence for this constraint
        constraint_evidence = None
        if constraint.evidence_id:
            for e in evidence_refs:
                if e.source_id == constraint.evidence_id:
                    constraint_evidence = e
                    break

        return OperationalConstraint(
            constraint_id=compute_constraint_id(
                material.canonical_material_id or "",
                constraint.parameter,
                constraint.limit_type,
                constraint.limit_value or "",
            ),
            description=constraint.rationale,
            source_basis=ConstraintSource.ENGINE_CONSTRAINT,
            parameter=constraint.parameter,
            limit_type=constraint.limit_type,
            limit_value=constraint.limit_value or "",
            verification_method="Plan review / inspection",
            evidence_ref=constraint_evidence,
        )

    def _compute_match_confidence(
        self,
        h2_response: H2Response,
        material: MaterialResolutionResult,
    ) -> float:
        """Compute confidence in material matching."""
        # Base confidence from resolution
        base = material.resolution_confidence

        # Penalty for H2 token match risk (Fran Fix #5)
        if material.h2_token_match_risk:
            base *= 0.9

        return min(1.0, base)

    def _compute_envelope_confidence(self, h2_response: H2Response) -> float:
        """Compute confidence in envelope matching."""
        # This would analyze the envelope match from H2 response
        # For now, use overall confidence
        return h2_response.confidence

    def _create_unresolved_output(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> H2AdapterOutput:
        """Create output for unresolved material."""
        gap_signal = GapSignal(
            gap_id=compute_gap_id(
                material.input_material_name or "unknown",
                environment.environment_id,
                FailureMode.MISSING_INPUT,
                GapTrigger.MISSING_DATA,
                "material_resolution",
            ),
            gap_type=FailureMode.MISSING_INPUT,
            trigger=GapTrigger.MISSING_DATA,
            trigger_parameter="material_identity",
            material_id=material.input_material_name or "unknown",
            environment_id=environment.environment_id,
            severity=GapSeverity.HIGH,
            confidence=1.0,
            evidence_refs=[],
            summary=f"Material '{material.input_material_name}' could not be resolved",
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
        )

        return H2AdapterOutput(
            material_id=material.input_material_name or "unknown",
            environment_id=environment.environment_id,
            verdict="UNKNOWN",
            confidence=0.0,
            match_confidence=0.0,
            envelope_confidence=0.0,
            gap_signals=[gap_signal],
            operational_constraints=[],
            evidence_refs=[],
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
            h2_token_match_risk=True,
            raw_response={},
        )

    def _create_placeholder_output(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> H2AdapterOutput:
        """Create placeholder output when H2 engine not available."""
        # Generate gap signal for missing H2/HEE evaluation
        gap_signal = GapSignal(
            gap_id=compute_gap_id(
                material.canonical_material_id or material.input_material_name or "unknown",
                environment.environment_id,
                FailureMode.HEE,
                GapTrigger.MISSING_DATA,
                "h2_engine_unavailable",
            ),
            gap_type=FailureMode.HEE,
            trigger=GapTrigger.MISSING_DATA,
            trigger_parameter="hee_index",
            material_id=material.canonical_material_id or material.input_material_name or "unknown",
            environment_id=environment.environment_id,
            severity=GapSeverity.HIGH,  # H2 embrittlement is serious
            confidence=1.0,
            evidence_refs=[],
            summary=f"HEE susceptibility not evaluated for '{material.canonical_name or material.input_material_name}' - H2 engine unavailable. Manual review required per NASA-STD-6016C MPR-6.",
            source_adapter="h2_adapter",
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
        )

        return H2AdapterOutput(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            verdict="UNKNOWN",
            confidence=0.5,
            match_confidence=material.resolution_confidence,
            envelope_confidence=0.5,
            gap_signals=[gap_signal],
            operational_constraints=[],
            evidence_refs=[],
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
            h2_token_match_risk=material.h2_token_match_risk,
            raw_response={"note": "placeholder - H2 engine not initialized"},
        )
