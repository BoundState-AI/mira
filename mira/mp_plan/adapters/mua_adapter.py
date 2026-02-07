#!/usr/bin/env python3
"""
Module: MUA Generation Adapter
Purpose: Wraps MUA generator for V2 session integration

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

This adapter transforms between V2 session models and the
existing MUA generator interface.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Optional

from ..models import (
    DraftTextBox,
    EnvironmentDefinition,
    MaterialEntry,
    MaterialResolutionResult,
    NonconformanceSignal,
    PlanGeneratorSession,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


class MUAGenerationAdapter:
    """
    Adapts MUA generator to V2 session model.

    This adapter:
    - Takes nonconformance signals from V2 session
    - Generates MUA draft text via existing MUA generator
    - Returns DraftTextBox objects (isolated LLM output)
    """

    def __init__(self):
        """Initialize the adapter."""
        self._generator = None

    def _get_generator(self):
        """Lazy-load the MUA generator."""
        if self._generator is None:
            try:
                from mira.mua.mua_generator import MUAGenerator

                self._generator = MUAGenerator()
            except ImportError as e:
                LOGGER.warning(f"Could not import MUAGenerator: {e}")
                self._generator = None
        return self._generator

    def generate_mua_draft(
        self,
        material: MaterialEntry,
        resolution: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        nonconformance: NonconformanceSignal,
        closure_path: str,
    ) -> Optional[DraftTextBox]:
        """
        Generate MUA draft for a nonconformance.

        Args:
            material: Material entry.
            resolution: MAPTIS resolution.
            environment: Environment definition.
            nonconformance: Nonconformance signal to address.
            closure_path: Selected closure path.

        Returns:
            DraftTextBox with MUA draft, or None on failure.
        """
        # Build inputs for draft generation
        inputs = {
            "material_name": material.name,
            "maptis_code": resolution.maptis_code,
            "environment_name": environment.name,
            "o2_pct": environment.o2_pct,
            "pressure_psia": environment.pressure_psia,
            "failing_rating": nonconformance.failing_value,
            "gap_type": nonconformance.gap_type.value,
            "closure_path": closure_path,
        }

        # Compute inputs hash for traceability
        inputs_str = str(sorted(inputs.items()))
        inputs_hash = hashlib.sha256(inputs_str.encode()).hexdigest()

        # Generate draft content
        draft_content = self._generate_draft_content(inputs, closure_path)

        # Create DraftTextBox (isolated LLM output)
        return DraftTextBox(
            draft_type="mua_rationale",
            content=draft_content,
            prompt_template_id=f"mua_{closure_path.lower()}",
            prompt_hash=hashlib.sha256(f"mua_template_{closure_path}".encode()).hexdigest(),
            model_id="rule_based",  # Not LLM-generated in this simple version
            inputs_hash=inputs_hash,
            generated_at=datetime.now(),
            is_authoritative=False,
            requires_human_review=True,
        )

    def _generate_draft_content(
        self,
        inputs: dict,
        closure_path: str,
    ) -> str:
        """
        Generate draft content based on closure path.

        This is a simple rule-based generator. In production,
        this would call the LLM-based MUA generator.

        Args:
            inputs: Input data for draft.
            closure_path: Selected closure path.

        Returns:
            Draft text content.
        """
        material_name = inputs["material_name"]
        o2_pct = inputs["o2_pct"]
        failing_rating = inputs["failing_rating"]
        gap_type = inputs["gap_type"]

        if closure_path == "MINOR_QUANTITY":
            return (
                f"Material: {material_name}\n\n"
                f"This material is used in minor quantity per MPR 44(c). "
                f"The material has a {failing_rating} {gap_type} rating. "
                f"Per NASA-STD-6016C Section 4.2.1.1, materials used in "
                f"quantities less than 45g and 13cm² exposed surface area "
                f"may be accepted without full flammability assessment.\n\n"
                f"[REQUIRES HUMAN REVIEW: Verify quantity limits are met]"
            )

        elif closure_path == "CONFIGURATION_ANALYSIS":
            return (
                f"Material: {material_name}\n\n"
                f"Configuration analysis demonstrates that the material's "
                f"use configuration limits ignition and flame propagation risk. "
                f"The material is rated {failing_rating} for {gap_type} at "
                f"{o2_pct}% O2.\n\n"
                f"[REQUIRES HUMAN REVIEW: Attach configuration analysis report]"
            )

        elif closure_path == "HEAT_SINK":
            return (
                f"Material: {material_name}\n\n"
                f"The material is in thermal contact with a heat sink that "
                f"prevents ignition temperature from being reached. "
                f"The material is rated {failing_rating} for {gap_type}.\n\n"
                f"[REQUIRES HUMAN REVIEW: Document heat sink analysis]"
            )

        elif closure_path == "SUBSTITUTION":
            return (
                f"Material: {material_name}\n\n"
                f"This material will be substituted with an A-rated alternative. "
                f"Current rating: {failing_rating} for {gap_type}.\n\n"
                f"[REQUIRES HUMAN REVIEW: Identify approved substitute material]"
            )

        else:  # FULL_MUA
            return (
                f"Material: {material_name}\n\n"
                f"Full Material Usage Agreement required.\n\n"
                f"Gap Type: {gap_type}\n"
                f"Failing Rating: {failing_rating}\n"
                f"Environment: {o2_pct}% O2\n\n"
                f"[REQUIRES HUMAN REVIEW: Complete MUA per template]"
            )

    def generate_drafts_for_session(
        self,
        session: PlanGeneratorSession,
    ) -> list[DraftTextBox]:
        """
        Generate MUA drafts for all nonconformances with closure decisions.

        Args:
            session: V2 Plan Generator session.

        Returns:
            List of DraftTextBox objects.
        """
        drafts = []

        # Get closure decisions
        closure_map = {d.gap_id: d for d in session.closure_decisions}

        for nc in session.nonconformances:
            closure = closure_map.get(nc.nonconformance_id)
            if not closure:
                continue

            material = session.get_material(nc.material_id)
            resolution = session.get_resolution(nc.material_id)
            environment = session.get_environment(nc.environment_id)

            if not material or not resolution or not environment:
                continue

            draft = self.generate_mua_draft(
                material=material,
                resolution=resolution,
                environment=environment,
                nonconformance=nc,
                closure_path=closure.selected_path,
            )

            if draft:
                drafts.append(draft)

        return drafts


def get_mua_adapter() -> MUAGenerationAdapter:
    """Get an MUA generation adapter instance."""
    return MUAGenerationAdapter()
