#!/usr/bin/env python3
"""
Module: Applicability Engine (Codex)
Purpose: Full-index MPR applicability evaluation for M&P Plan v2

This engine evaluates applicability across all MPR entries loaded from the
configured NASA-STD-6016C index file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import logging

import yaml

from mira.compliance.models.enums import ApplicabilityStatus

from ..models import (
    EnvironmentDefinition,
    HardwareContext,
    MaterialEntry,
    MaterialEnvironmentUsage,
    PlanGeneratorSession,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.1.0-codex"
__safety_critical__ = False

DEFAULT_MPR_INDEX_PATH = (
    Path(__file__).resolve().parents[2] / "compliance" / "data" / "mprs_6016c.yaml"
)


@dataclass(frozen=True)
class MPRCatalogEntryCodex:
    """Normalized MPR catalog entry used by applicability and compliance engines."""

    mpr_number: int
    mpr_id: str
    section: str
    title: str
    shall_text: str
    verification_method: str
    applicability_triggers: tuple[str, ...]
    related_failure_modes: tuple[str, ...]
    priority: int


def load_mpr_catalog_codex(path: Optional[Path] = None) -> list[MPRCatalogEntryCodex]:
    """
    Load MPR catalog entries from YAML.

    Returns:
        Sorted list of normalized MPR entries.
    """
    index_path = path or DEFAULT_MPR_INDEX_PATH
    with open(index_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    entries: list[MPRCatalogEntryCodex] = []
    for raw in data.get("mprs", []):
        entries.append(
            MPRCatalogEntryCodex(
                mpr_number=int(raw.get("mpr_number")),
                mpr_id=str(raw.get("mpr_id", f"MPR-{int(raw.get('mpr_number')):03d}")),
                section=str(raw.get("section", "")),
                title=str(raw.get("title", "")),
                shall_text=str(raw.get("shall_text", "")),
                verification_method=str(raw.get("verification_method", "Analysis/Test")),
                applicability_triggers=tuple(
                    str(t).strip().lower() for t in raw.get("applicability_triggers", [])
                ),
                related_failure_modes=tuple(
                    str(t).strip().lower() for t in raw.get("related_failure_modes", [])
                ),
                priority=int(raw.get("priority", 100)),
            )
        )

    entries.sort(key=lambda e: (e.priority, e.mpr_number))
    return entries


class ApplicabilityEngineCodex:
    """
    Full-index applicability engine.

    Evaluates every MPR in the loaded index for each material/environment usage.
    """

    def __init__(
        self,
        mpr_catalog: Optional[list[MPRCatalogEntryCodex]] = None,
        index_path: Optional[Path] = None,
    ):
        self._mpr_catalog = mpr_catalog or load_mpr_catalog_codex(index_path)

    @property
    def mpr_count(self) -> int:
        return len(self._mpr_catalog)

    @property
    def catalog(self) -> list[MPRCatalogEntryCodex]:
        return list(self._mpr_catalog)

    @staticmethod
    def _material_text(material: MaterialEntry) -> str:
        parts = [
            material.name or "",
            material.application or "",
            material.spec or "",
            material.function or "",
            material.location or "",
        ]
        return " ".join(parts).lower()

    @staticmethod
    def _material_tags(material: MaterialEntry) -> set[str]:
        text = ApplicabilityEngineCodex._material_text(material)
        tags: set[str] = set()

        if any(k in text for k in ("steel", "inconel", "aluminum", "titanium", "metal")):
            tags.add("metallic_material")
        if any(
            k in text
            for k in ("poly", "elastomer", "rubber", "epoxy", "adhesive", "composite", "paint", "coating")
        ):
            tags.add("nonmetallic_material")
        if "composite" in text or "carbon fiber" in text:
            tags.add("composite_material")
        if any(k in text for k in ("lubricant", "grease", "oil")):
            tags.add("lubricant")
        if any(k in text for k in ("adhesive", "bond", "epoxy")):
            tags.add("adhesive")
        if any(k in text for k in ("coating", "paint", "anodize", "plating")):
            tags.add("coating")
        if any(k in text for k in ("seal", "gasket", "o-ring", "oring")):
            tags.add("seal")
            tags.add("gasket")
        if any(k in text for k in ("wire", "cable", "harness", "insulation")):
            tags.add("wiring")
            tags.add("cable")
        if any(k in text for k in ("cots", "off-the-shelf", "commercial")):
            tags.add("cots")
        if any(k in text for k in ("optic", "lens", "window", "mirror")):
            tags.add("optical_surface")
        return tags

    @staticmethod
    def _env_trigger_match(trigger: str, env: EnvironmentDefinition) -> bool:
        if trigger in ("always", "all", "any"):
            return True
        if trigger in ("oxygen_service", "high_o2", "oxygen_enriched"):
            return env.o2_pct > 23.5
        if trigger == "habitable":
            return env.habitable
        if trigger in ("vacuum", "vacuum_exposure"):
            return env.vacuum_exposure
        if trigger in ("lunar_dust", "dust"):
            return env.lunar_dust
        if trigger in ("cryogenic", "low_temperature"):
            return env.temp_range_c[0] <= -150.0
        if trigger == "high_pressure":
            return env.pressure_psia >= 300.0
        if trigger == "low_pressure":
            return env.pressure_psia <= 4.3
        if trigger in ("external_environment", "external"):
            return env.vacuum_exposure or env.lunar_dust
        return False

    @staticmethod
    def _hardware_trigger_match(
        trigger: str,
        hardware_context: Optional[HardwareContext],
    ) -> bool:
        if not hardware_context:
            return False
        if trigger in ("ignition_source_present", "ignition_sources"):
            return bool(hardware_context.ignition_sources)
        if trigger == "crew_contact":
            return hardware_context.crew_contact
        return trigger == (hardware_context.hardware_type or "").strip().lower()

    @classmethod
    def _trigger_match(
        cls,
        trigger: str,
        material: MaterialEntry,
        environment: EnvironmentDefinition,
        hardware_context: Optional[HardwareContext],
        tags: set[str],
        material_text: str,
    ) -> bool:
        if cls._env_trigger_match(trigger, environment):
            return True
        if cls._hardware_trigger_match(trigger, hardware_context):
            return True
        if trigger in tags:
            return True
        return trigger and trigger in material_text

    def determine_applicability_for_usage(
        self,
        material: MaterialEntry,
        environment: EnvironmentDefinition,
        hardware_context: Optional[HardwareContext] = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Determine applicability for every MPR for a material/environment usage.
        """
        material_text = self._material_text(material)
        tags = self._material_tags(material)
        decisions: dict[str, dict[str, Any]] = {}

        for mpr in self._mpr_catalog:
            triggers = list(mpr.applicability_triggers)
            matched = [
                t
                for t in triggers
                if self._trigger_match(
                    trigger=t,
                    material=material,
                    environment=environment,
                    hardware_context=hardware_context,
                    tags=tags,
                    material_text=material_text,
                )
            ]

            if not triggers:
                status = ApplicabilityStatus.APPLICABLE.value
                rationale = "MPR has no trigger gates; treated as generally applicable."
            elif matched:
                status = ApplicabilityStatus.APPLICABLE.value
                rationale = f"Triggered by: {', '.join(sorted(set(matched)))}"
            else:
                status = ApplicabilityStatus.NOT_APPLICABLE_BY_CONDITION.value
                rationale = f"Triggers not met: {', '.join(triggers)}"

            decisions[mpr.mpr_id] = {
                "mpr_id": mpr.mpr_id,
                "mpr_number": mpr.mpr_number,
                "mpr_title": mpr.title,
                "mpr_section": mpr.section,
                "verification_method": mpr.verification_method,
                "related_failure_modes": list(mpr.related_failure_modes),
                "priority": mpr.priority,
                "status": status,
                "rationale": rationale,
                "triggered_by": matched,
                "citation": f"NASA-STD-6016C w/CHANGE 2 §{mpr.section}",
                "confidence": 1.0 if matched or not triggers else 0.95,
            }

        return decisions

    def build_applicability_matrix(
        self,
        session: PlanGeneratorSession,
    ) -> dict[str, dict[str, Any]]:
        """
        Build applicability matrix keyed by "material_id:environment_id".
        """
        matrix: dict[str, dict[str, Any]] = {}
        usages: list[MaterialEnvironmentUsage] = list(session.material_environment_usages)

        if not usages and session.materials and session.environments:
            # Fallback to a full cartesian map when explicit usages are absent.
            for material in session.materials:
                for env in session.environments:
                    usages.append(
                        MaterialEnvironmentUsage(
                            material_id=material.id,
                            environment_id=env.environment_id,
                            location=material.location or "unspecified",
                        )
                    )

        for usage in usages:
            material = session.get_material(usage.material_id)
            environment = session.get_environment(usage.environment_id)
            if not material or not environment:
                continue
            key = f"{material.id}:{environment.environment_id}"
            matrix[key] = self.determine_applicability_for_usage(
                material=material,
                environment=environment,
                hardware_context=session.hardware_context,
            )

        LOGGER.info(
            "Codex applicability built for %d usage pairs over %d indexed MPRs",
            len(matrix),
            self.mpr_count,
        )
        return matrix

    def run(self, session: PlanGeneratorSession) -> dict[str, dict[str, Any]]:
        matrix = self.build_applicability_matrix(session)
        session.applicability_matrix = matrix
        return matrix

