#!/usr/bin/env python3
"""
Module: O2 Adapter
Purpose: Adapter for the O2 (Oxygen) Knowledge Twin

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
NASA-STD-6016C Compliance Module - O2 Adapter

Adapter for the O2 (Oxygen) Knowledge Twin.

IMPORTANT: Emits signals only, NOT MPRDetermination.
That's the conductor's job.

Fran Fix #1: Adapters emit signals only, conductor maps to MPRs.
Fran Fix #2: Uses source_type for basis selection.

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
from typing import Any, Optional

from mira.compliance.adapters.base import BaseAdapter
from mira.compliance.id_utils import compute_gap_id
from mira.compliance.models.adapter_outputs import O2AdapterOutput
from mira.compliance.models.enums import (
    ComplianceBasis,
    FailureMode,
    GapSeverity,
    GapTrigger,
    SourceType,
)
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal
from mira.compliance.models.policy import EnvironmentDefinition
from mira.compliance.models.resolution import MaterialResolutionResult

LOGGER = logging.getLogger(__name__)

# Import O2 twin types (from existing codebase)
try:
    from core.models.answer import AnswerSeverity, EvidenceItem, EngineAnswer
except ImportError:
    # Fallback for when running standalone
    from enum import Enum

    class AnswerSeverity(str, Enum):
        OK = "ok"
        CAUTION = "caution"
        PROHIBITED = "prohibited"
        UNKNOWN = "unknown"

    class EvidenceItem:
        def __init__(self, source_id: str = "", location: str = "", summary: str = ""):
            self.source_id = source_id
            self.location = location
            self.summary = summary

    class EngineAnswer:
        def __init__(self):
            self.classification = AnswerSeverity.UNKNOWN
            self.rationale = ""
            self.evidence = []
            self.notes = None

# Import O2 Knowledge Twin
try:
    from mira.o2 import evaluate_o2_compatibility
    from mira.o2.models import O2CompatibilityRequest, OxygenPhase
    O2_TWIN_AVAILABLE = True
except ImportError:
    LOGGER.warning("O2 Knowledge Twin not available")
    O2_TWIN_AVAILABLE = False


def _f_to_k(fahrenheit: float) -> float:
    """Convert Fahrenheit to Kelvin."""
    return (fahrenheit - 32) * 5 / 9 + 273.15


class O2Adapter(BaseAdapter):
    """
    Adapter for O2 Knowledge Twin.

    Converts O2 twin responses to compliance module signals.

    IMPORTANT: Does NOT select MPRs. Emits signals for conductor to map.
    """

    def __init__(self, o2_engine=None, version: str = "1.0.0"):
        """
        Initialize O2 adapter.

        Args:
            o2_engine: O2 engine instance (optional, for testing)
            version: Adapter version
        """
        super().__init__(version=version)
        self._o2_engine = o2_engine

    def evaluate(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> O2AdapterOutput:
        """
        Evaluate material in O2 environment.

        Args:
            material: Resolved material information
            environment: Environment definition

        Returns:
            O2AdapterOutput with signals and evidence
        """
        if not material.resolved:
            return self._create_unresolved_output(material, environment)

        # Call O2 twin if custom engine provided
        if self._o2_engine:
            o2_response = self._call_o2_twin(material, environment)
            return self._adapt_o2_response(o2_response, material, environment)

        # Use real O2 Knowledge Twin if available
        if O2_TWIN_AVAILABLE:
            return self._call_real_o2_twin(material, environment)

        # Return placeholder when no twin available
        return self._create_placeholder_output(material, environment)

    def _call_o2_twin(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> EngineAnswer:
        """
        Call the O2 Knowledge Twin (custom engine).

        Args:
            material: Resolved material
            environment: Environment definition

        Returns:
            O2 engine response
        """
        # Build query for O2 twin
        # This would use the actual O2 engine interface
        # For now, return a mock response
        return EngineAnswer()

    def _call_real_o2_twin(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> O2AdapterOutput:
        """
        Call the real O2 Knowledge Twin via evaluate_o2_compatibility.

        Args:
            material: Resolved material
            environment: Environment definition

        Returns:
            O2AdapterOutput with twin evaluation results
        """
        try:
            # Build O2 request
            # Determine phase from environment
            phase = OxygenPhase.LIQUID if environment.is_cryogenic else OxygenPhase.GAS

            # Convert temperature from Fahrenheit to Kelvin
            temp_f = environment.temperature_min_f or 70.0
            temp_k = _f_to_k(temp_f)

            request = O2CompatibilityRequest(
                question=f"Is {material.canonical_name} compatible with oxygen?",
                material_key=material.canonical_name or material.input_material_name or "",
                pressure_psia=environment.pressure_psia or 14.7,
                temperature_k=temp_k,
                phase=phase,
            )

            # Call the O2 twin
            LOGGER.info(f"Calling O2 twin for {material.canonical_name}")
            response = evaluate_o2_compatibility(request)

            # Adapt response to O2AdapterOutput
            return self._adapt_o2_response(response, material, environment)

        except Exception as e:
            LOGGER.error(f"O2 twin evaluation failed: {e}")
            # Return placeholder on error
            return self._create_placeholder_output(material, environment)

    def _adapt_o2_response(
        self,
        o2_response: EngineAnswer,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> O2AdapterOutput:
        """
        Convert O2 twin response to adapter output.

        IMPORTANT: Does NOT select MPRs. Emits signals for conductor to map.

        Fran Fix #2: Uses source_type for basis selection.
        """
        gap_signals = []
        evidence_refs = []

        # Convert O2 evidence to EvidenceRef with source_type
        for ev in o2_response.evidence:
            evidence_refs.append(self._create_evidence_ref(
                source_id=ev.source_id,
                locator=ev.location,
                quote=ev.summary[:500] if ev.summary else None,
                confidence=0.9,
                confidence_basis="O2 Knowledge Twin policy gate",
                retrieval_method="o2_twin_engine",
            ))

        # Determine suggested basis (Fran Fix #2)
        # TEST if any evidence is MAPTIS/TEST_REPORT, else POLICY
        has_test_evidence = any(e.supports_test_basis() for e in evidence_refs)
        suggested_basis = ComplianceBasis.TEST if has_test_evidence else ComplianceBasis.POLICY

        # Generate GapSignals for non-OK classifications
        if o2_response.classification in [AnswerSeverity.CAUTION, AnswerSeverity.PROHIBITED]:
            gap_signals.append(self._create_gap_signal(
                o2_response=o2_response,
                material=material,
                environment=environment,
                evidence_refs=evidence_refs,
                suggested_basis=suggested_basis,
            ))

        return O2AdapterOutput(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            classification=o2_response.classification.value.upper(),
            rationale=o2_response.rationale,
            gap_signals=gap_signals,
            evidence_refs=evidence_refs,
            suggested_basis=suggested_basis,
            raw_response={
                "classification": o2_response.classification.value,
                "rationale": o2_response.rationale,
                "notes": o2_response.notes,
            },
        )

    def _create_gap_signal(
        self,
        o2_response: EngineAnswer,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        evidence_refs: list[EvidenceRef],
        suggested_basis: ComplianceBasis,
    ) -> GapSignal:
        """Create a gap signal from O2 response."""
        # Determine gap type and trigger based on classification
        if o2_response.classification == AnswerSeverity.PROHIBITED:
            gap_type = FailureMode.O2_PROHIBITED
            trigger = GapTrigger.PROHIBITED_FAMILY
            severity = GapSeverity.CRITICAL
        else:  # CAUTION
            gap_type = FailureMode.FLAM
            trigger = GapTrigger.RESTRICTED_POLICY
            severity = GapSeverity.HIGH

        return GapSignal(
            gap_id=compute_gap_id(
                material.canonical_material_id or "",
                environment.environment_id,
                gap_type,
                trigger,
                None,
            ),
            gap_type=gap_type,
            trigger=trigger,
            trigger_parameter="material_family",
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            policy_rule=f"O2 family gate: {material.material_family}",
            severity=severity,
            confidence=0.9,
            evidence_refs=evidence_refs,
            summary=o2_response.rationale,
            source_adapter="o2_adapter",
            suggested_basis=suggested_basis,
        )

    def _create_unresolved_output(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> O2AdapterOutput:
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
            summary=f"Material '{material.input_material_name}' could not be resolved to MAPTIS",
            source_adapter="o2_adapter",
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
        )

        return O2AdapterOutput(
            material_id=material.input_material_name or "unknown",
            environment_id=environment.environment_id,
            classification="UNKNOWN",
            rationale=f"Material could not be resolved: {material.input_material_name}",
            gap_signals=[gap_signal],
            evidence_refs=[],
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
            raw_response={},
        )

    def _create_placeholder_output(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> O2AdapterOutput:
        """Create placeholder output when O2 engine not available."""
        # Generate gap signal for missing O2 evaluation
        gap_signal = GapSignal(
            gap_id=compute_gap_id(
                material.canonical_material_id or material.input_material_name or "unknown",
                environment.environment_id,
                FailureMode.MISSING_INPUT,
                GapTrigger.MISSING_DATA,
                "o2_engine_unavailable",
            ),
            gap_type=FailureMode.MISSING_INPUT,
            trigger=GapTrigger.MISSING_DATA,
            trigger_parameter="o2_compatibility_test",
            material_id=material.canonical_material_id or material.input_material_name or "unknown",
            environment_id=environment.environment_id,
            severity=GapSeverity.HIGH if environment.is_oxygen_enriched else GapSeverity.MEDIUM,
            confidence=1.0,
            evidence_refs=[],
            summary=f"O2 compatibility not evaluated for '{material.canonical_name or material.input_material_name}' - engine unavailable. Manual review required.",
            source_adapter="o2_adapter",
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
        )

        return O2AdapterOutput(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            classification="UNKNOWN",
            rationale=f"O2 engine not available - cannot evaluate {material.canonical_name or material.input_material_name}",
            gap_signals=[gap_signal],
            evidence_refs=[],
            suggested_basis=ComplianceBasis.NOT_APPLICABLE,
            raw_response={"note": "placeholder - O2 engine not initialized"},
        )
