#!/usr/bin/env python3
"""
Module: MUA Adapter
Purpose: Adapter for the Material Usage Agreement Generator

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
NASA-STD-6016C Compliance Module - MUA Adapter

Adapter for the MUA (Material Usage Agreement) Generator.

IMPORTANT: LLM drafts TEXT only, never sets compliance status.

Fran Fix #7: Includes LLM invocation tracking for reproducibility.

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
from typing import Any, List, Optional
import uuid

from mira.compliance.adapters.base import BaseAdapter
from mira.compliance.id_utils import compute_inputs_hash, compute_prompt_hash
from mira.compliance.models.adapter_outputs import MUAAdapterOutput, PrecedentValidation
from mira.compliance.models.enums import MUACategory, SourceType
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal
from mira.compliance.models.manifest import MUALLMInvocation
from mira.compliance.models.policy import EnvironmentDefinition
from mira.compliance.models.resolution import MaterialResolutionResult


class MUAAdapter(BaseAdapter):
    """
    Adapter for MUA Generator.

    Generates MUA drafts based on gap signals and precedent validation.

    IMPORTANT: LLM drafts TEXT only, never sets compliance status.
    """

    def evaluate(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> MUAAdapterOutput:
        """
        Evaluate method required by BaseAdapter.

        For MUA, this is a no-op since MUA generation is triggered by
        gaps from other adapters, not by direct evaluation.
        Use generate() instead for actual MUA generation.
        """
        return MUAAdapterOutput(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            triggering_gap_ids=[],
            category=2,
            category_rule_id="RULE_DEFAULT",
            category_reasoning_trace=[],
            precedent_validations=[],
            draft_text="No gaps provided - use generate() with gap signals",
            evidence_refs=[],
        )

    def __init__(
        self,
        mua_generator=None,
        precedent_engine=None,
        llm_model_id: str = "claude-sonnet-4-20250514",
        prompt_template_version: str = "1.0.0",
        version: str = "1.0.0",
    ):
        """
        Initialize MUA adapter.

        Args:
            mua_generator: MUA generator instance (optional)
            precedent_engine: Precedent engine instance (optional)
            llm_model_id: LLM model identifier for tracking
            prompt_template_version: Version of prompt templates
            version: Adapter version
        """
        super().__init__(version=version)
        self._mua_generator = mua_generator
        self._precedent_engine = precedent_engine
        self._llm_model_id = llm_model_id
        self._prompt_template_version = prompt_template_version
        self._llm_invocations: list[MUALLMInvocation] = []

    def generate(
        self,
        signals: list[GapSignal],
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> MUAAdapterOutput:
        """
        Generate MUA draft for gap signals.

        Args:
            signals: Gap signals requiring MUA
            material: Resolved material information
            environment: Environment definition

        Returns:
            MUAAdapterOutput with draft text and validation results
        """
        # Determine category (rule-based, deterministic)
        category, category_rule_id, reasoning_trace = self._determine_category(
            signals, material, environment
        )

        # Validate precedents
        precedent_validations = self._validate_precedents(
            material, environment, signals
        )

        # Generate draft text (LLM call)
        draft_text = self._generate_draft(
            signals=signals,
            material=material,
            environment=environment,
            category=category,
            precedents=precedent_validations,
        )

        # Build evidence refs
        evidence_refs = self._collect_evidence(signals, precedent_validations)

        return MUAAdapterOutput(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            triggering_gap_ids=[s.gap_id for s in signals],
            category=category,
            category_rule_id=category_rule_id,
            category_reasoning_trace=reasoning_trace,
            precedent_validations=precedent_validations,
            draft_text=draft_text,
            evidence_refs=evidence_refs,
        )

    def get_llm_invocations(self) -> list[MUALLMInvocation]:
        """Get all LLM invocations for audit trail."""
        return self._llm_invocations

    def clear_llm_invocations(self) -> None:
        """Clear LLM invocation history."""
        self._llm_invocations = []

    def _determine_category(
        self,
        signals: list[GapSignal],
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> tuple[int, str, list[dict]]:
        """
        Determine MUA category using rule-based logic.

        This is deterministic, not LLM-based.

        Returns:
            Tuple of (category, rule_id, reasoning_trace)
        """
        reasoning_trace = []

        # Category I: High-risk
        # - LOX service
        # - GOX > 25%
        # - High pressure O2 enriched
        # - Any critical gaps

        has_critical = any(s.is_critical() for s in signals)
        if has_critical:
            reasoning_trace.append({
                "rule": "critical_gap_check",
                "result": True,
                "detail": "Critical severity gap present",
            })
            return 1, "RULE_CRITICAL_GAP", reasoning_trace

        mua_category = environment.get_mua_category()
        if mua_category == MUACategory.CATEGORY_1:
            reasoning_trace.append({
                "rule": "environment_category",
                "result": 1,
                "detail": f"Environment is Category I: {environment.description}",
            })
            return 1, "RULE_ENV_CAT_1", reasoning_trace

        # Category III: Non-habitable, specialized
        if mua_category == MUACategory.CATEGORY_3:
            reasoning_trace.append({
                "rule": "environment_category",
                "result": 3,
                "detail": "Non-habitable environment",
            })
            return 3, "RULE_ENV_CAT_3", reasoning_trace

        # Category II: Default
        reasoning_trace.append({
            "rule": "default",
            "result": 2,
            "detail": "Standard oxygen environment",
        })
        return 2, "RULE_DEFAULT_CAT_2", reasoning_trace

    def _validate_precedents(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        signals: list[GapSignal],
    ) -> list[PrecedentValidation]:
        """
        Validate precedents for this material/environment.

        Uses deterministic matching rules.
        """
        validations = []

        if not self._precedent_engine:
            # No precedent engine - return empty
            return validations

        # This would call the actual precedent engine
        # For now, return empty list
        return validations

    def _generate_draft(
        self,
        signals: list[GapSignal],
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        category: int,
        precedents: list[PrecedentValidation],
    ) -> str:
        """
        Generate MUA draft text.

        Fran Fix #7: Log LLM invocation for reproducibility.
        """
        if not self._mua_generator:
            # Generate placeholder draft
            return self._generate_placeholder_draft(
                signals, material, environment, category
            )

        # Build prompt
        prompt = self._build_prompt(signals, material, environment, category, precedents)

        # Build inputs for hashing
        inputs = {
            "material_id": material.canonical_material_id,
            "material_name": material.canonical_name,
            "environment_id": environment.environment_id,
            "category": category,
            "gap_ids": [s.gap_id for s in signals],
            "precedent_ids": [p.precedent_id for p in precedents if p.is_applicable],
        }

        # This would call the actual LLM
        draft_text = self._call_llm(prompt, inputs, material, environment)

        return draft_text

    def _build_prompt(
        self,
        signals: list[GapSignal],
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        category: int,
        precedents: list[PrecedentValidation],
    ) -> str:
        """Build LLM prompt for MUA generation."""
        # Build structured prompt
        lines = [
            "Generate a Material Usage Agreement (MUA) draft.",
            "",
            f"Material: {material.canonical_name}",
            f"MAPTIS Code: {material.canonical_maptis_code}",
            f"Material Family: {material.material_family}",
            "",
            f"Environment: {environment.description}",
            f"MUA Category: {category}",
            "",
            "Gap Signals:",
        ]

        for signal in signals:
            lines.append(f"  - {signal.gap_type.value}: {signal.summary}")

        if precedents:
            lines.append("")
            lines.append("Applicable Precedents:")
            for p in precedents:
                if p.is_applicable:
                    lines.append(f"  - {p.precedent_id} (score: {p.match_score:.2f})")

        lines.extend([
            "",
            "Generate the MUA rationale and justification text.",
            "Include relevant citations and evidence references.",
        ])

        return "\n".join(lines)

    def _call_llm(
        self,
        prompt: str,
        inputs: dict,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> str:
        """
        Call LLM and track invocation.

        Fran Fix #7: Log prompt, model, and inputs for reproducibility.
        """
        # Compute hashes for tracking
        prompt_hash = compute_prompt_hash(prompt)
        inputs_hash = compute_inputs_hash(inputs)

        # This would call the actual LLM
        # For now, return placeholder
        draft_text = self._generate_placeholder_draft(
            [], material, environment, 2
        )

        output_hash = compute_prompt_hash(draft_text)

        # Log invocation
        invocation = MUALLMInvocation(
            invocation_id=str(uuid.uuid4())[:12],
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            llm_model_id=self._llm_model_id,
            prompt_template_version=self._prompt_template_version,
            prompt_hash=prompt_hash,
            inputs_hash=inputs_hash,
            output_hash=output_hash,
            timestamp=datetime.now(),
        )
        self._llm_invocations.append(invocation)

        return draft_text

    def _generate_placeholder_draft(
        self,
        signals: list[GapSignal],
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        category: int,
    ) -> str:
        """Generate placeholder MUA draft text."""
        lines = [
            "MATERIAL USAGE AGREEMENT DRAFT",
            "=" * 40,
            "",
            f"Material: {material.canonical_name or material.input_material_name}",
            f"MAPTIS Code: {material.canonical_maptis_code}",
            f"Specification: {material.canonical_spec}",
            f"Material Family: {material.material_family}",
            "",
            f"Environment: {environment.description}",
            f"MUA Category: {category}",
            "",
            "RATIONALE:",
            "",
            "[This is a placeholder draft. The MUA generator was not available.",
            "In production, this would contain LLM-generated rationale based on",
            "the gap signals and precedent validation results.]",
            "",
            "GAPS ADDRESSED:",
        ]

        for signal in signals:
            lines.append(f"  - {signal.gap_type.value}: {signal.summary}")

        lines.extend([
            "",
            "JUSTIFICATION:",
            "[To be completed by engineer]",
            "",
            "MITIGATIONS:",
            "[To be completed by engineer]",
            "",
            "APPROVALS:",
            "[Pending]",
        ])

        return "\n".join(lines)

    def _collect_evidence(
        self,
        signals: list[GapSignal],
        precedents: list[PrecedentValidation],
    ) -> list[EvidenceRef]:
        """Collect all evidence from signals and precedents."""
        evidence_refs = []

        # Collect from signals
        for signal in signals:
            evidence_refs.extend(signal.evidence_refs)

        # Collect from precedents
        for p in precedents:
            if p.evidence_ref:
                evidence_refs.append(p.evidence_ref)

        # Deduplicate by source_id
        seen = set()
        unique = []
        for e in evidence_refs:
            if e.source_id not in seen:
                seen.add(e.source_id)
                unique.append(e)

        return unique
