#!/usr/bin/env python3
"""
Module: Data Acquisition Engine (Engine A)
Purpose: Material data acquisition and normalization

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Engine A responsibilities:
- Parse material inputs (BOM, manual entry)
- Resolve materials to MAPTIS codes
- Fetch test data and ratings
- Track evidence for all lookups

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ..adapters import MaptisResolutionAdapter
from ..models import (
    DeficiencySignal,
    EnvironmentDefinition,
    MaterialEntry,
    MaterialEnvironmentUsage,
    MaterialResolutionResult,
    PlanGeneratorSession,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


class DataAcquisitionEngine:
    """
    Engine A: Data Acquisition and Normalization.

    Responsible for:
    - Material resolution to MAPTIS codes
    - Rating data retrieval
    - Evidence tracking for all lookups
    - Deficiency detection for missing data
    """

    def __init__(
        self,
        maptis_adapter: Optional[MaptisResolutionAdapter] = None,
    ):
        """
        Initialize the data acquisition engine.

        Args:
            maptis_adapter: Optional adapter for MAPTIS lookups.
                           If not provided, attempts to create one from
                           environment variables. Falls back to mock mode
                           if credentials are not available.
        """
        self._maptis_adapter = maptis_adapter
        self._mock_mode = False

        if self._maptis_adapter is None:
            try:
                self._maptis_adapter = MaptisResolutionAdapter()
            except ValueError as e:
                # Database credentials not available - use mock mode
                LOGGER.warning(
                    f"MAPTIS adapter not available ({e}). "
                    "Running in mock mode without database connectivity."
                )
                self._mock_mode = True
                self._maptis_adapter = None

    def resolve_materials(
        self,
        session: PlanGeneratorSession,
    ) -> list[MaterialResolutionResult]:
        """
        Resolve all materials in session to MAPTIS data.

        Args:
            session: Plan generator session.

        Returns:
            List of resolution results.
        """
        results = []

        # In mock mode, create mock resolutions for materials with MAPTIS codes
        if self._mock_mode:
            LOGGER.info("Running in mock mode - creating stub resolutions")
            for material in session.materials:
                if material.maptis_code:
                    # Create a mock resolution
                    results.append(
                        MaterialResolutionResult(
                            material_id=material.id,
                            maptis_code=material.maptis_code,
                            flam_rating="U",  # Unknown - needs actual lookup
                            tvs_rating="U",
                            tox_rating="U",
                            test_o2_pct=21.0,
                            source="mock_mode",
                        )
                    )
                    LOGGER.info(
                        f"Mock resolved {material.name} ({material.maptis_code})"
                    )
            return results

        # Normal mode with database
        for material in session.materials:
            if material.maptis_code:
                # Material has MAPTIS code - resolve it
                result = self._maptis_adapter.resolve_material(material)
                if result:
                    results.append(result)
                    LOGGER.info(
                        f"Resolved {material.name} ({material.maptis_code}): "
                        f"FLAM={result.flam_rating}"
                    )
                else:
                    LOGGER.warning(
                        f"Failed to resolve {material.name} ({material.maptis_code})"
                    )
            else:
                LOGGER.info(f"Material {material.name} has no MAPTIS code - skipping")

        return results

    def detect_deficiencies(
        self,
        session: PlanGeneratorSession,
    ) -> list[DeficiencySignal]:
        """
        Detect data deficiencies in session.

        Checks for:
        - Materials without MAPTIS codes
        - Materials without resolutions
        - Missing mass/surface area for potential minor quantity

        Args:
            session: Plan generator session.

        Returns:
            List of deficiency signals.
        """
        deficiencies = []

        # Check materials without MAPTIS codes
        resolved_ids = {r.material_id for r in session.maptis_resolutions}

        for material in session.materials:
            if not material.maptis_code:
                deficiencies.append(
                    DeficiencySignal(
                        deficiency_type="missing_maptis_code",
                        missing_field="maptis_code",
                        missing_for=f"resolution of {material.name}",
                        material_id=material.id,
                        blocked_decision_ids=[f"resolution:{material.id}"],
                        source="data_acquisition_engine",
                    )
                )
            elif material.id not in resolved_ids:
                deficiencies.append(
                    DeficiencySignal(
                        deficiency_type="resolution_failed",
                        missing_field="maptis_resolution",
                        missing_for=f"compliance evaluation of {material.name}",
                        material_id=material.id,
                        blocked_decision_ids=[f"compliance:{material.id}"],
                        source="data_acquisition_engine",
                    )
                )

            # Check for missing quantity data
            if material.mass_g is None:
                deficiencies.append(
                    DeficiencySignal(
                        deficiency_type="missing_mass",
                        missing_field="mass_g",
                        missing_for=f"minor quantity check for {material.name}",
                        material_id=material.id,
                        blocked_decision_ids=[f"minor_qty:{material.id}"],
                        conservative_default_available=True,
                        conservative_default_value=1000.0,  # Conservative: assume large
                        conservative_default_rationale="Assume mass exceeds minor quantity limit",
                        source="data_acquisition_engine",
                    )
                )

            if material.surface_area_cm2 is None:
                deficiencies.append(
                    DeficiencySignal(
                        deficiency_type="missing_surface_area",
                        missing_field="surface_area_cm2",
                        missing_for=f"minor quantity check for {material.name}",
                        material_id=material.id,
                        blocked_decision_ids=[f"minor_qty:{material.id}"],
                        conservative_default_available=True,
                        conservative_default_value=100.0,  # Conservative: assume large
                        conservative_default_rationale="Assume area exceeds minor quantity limit",
                        source="data_acquisition_engine",
                    )
                )

        return deficiencies

    def ensure_environment_mappings(
        self,
        session: PlanGeneratorSession,
    ) -> list[MaterialEnvironmentUsage]:
        """
        Ensure all materials have environment mappings.

        If materials don't have explicit mappings, create default
        mappings to all environments.

        Args:
            session: Plan generator session.

        Returns:
            List of new environment mappings created.
        """
        new_mappings = []

        # Get existing mappings
        existing = {
            (u.material_id, u.environment_id)
            for u in session.material_environment_usages
        }

        # Create mappings for materials without them
        for material in session.materials:
            has_mapping = any(
                material.id == mid for mid, _ in existing
            )

            if not has_mapping and session.environments:
                # Map to all environments by default
                for env in session.environments:
                    mapping = MaterialEnvironmentUsage(
                        material_id=material.id,
                        environment_id=env.environment_id,
                        location=material.location or "unspecified",
                    )
                    new_mappings.append(mapping)
                    LOGGER.info(
                        f"Created default mapping: {material.name} -> {env.name}"
                    )

        return new_mappings

    def run(
        self,
        session: PlanGeneratorSession,
    ) -> tuple[list[MaterialResolutionResult], list[DeficiencySignal], list[MaterialEnvironmentUsage]]:
        """
        Run full data acquisition pipeline.

        Args:
            session: Plan generator session.

        Returns:
            Tuple of (resolutions, deficiencies, new_mappings).
        """
        LOGGER.info(f"Running data acquisition for {len(session.materials)} materials")

        # Step 1: Resolve materials
        resolutions = self.resolve_materials(session)

        # Update session with resolutions
        session.maptis_resolutions = resolutions

        # Step 2: Ensure environment mappings
        new_mappings = self.ensure_environment_mappings(session)
        session.material_environment_usages.extend(new_mappings)

        # Step 3: Detect deficiencies
        deficiencies = self.detect_deficiencies(session)

        LOGGER.info(
            f"Data acquisition complete: {len(resolutions)} resolved, "
            f"{len(deficiencies)} deficiencies, {len(new_mappings)} new mappings"
        )

        return resolutions, deficiencies, new_mappings

    def close(self) -> None:
        """Close any open connections."""
        if self._maptis_adapter:
            self._maptis_adapter.close()


def get_data_acquisition_engine() -> DataAcquisitionEngine:
    """Get a data acquisition engine instance."""
    return DataAcquisitionEngine()
