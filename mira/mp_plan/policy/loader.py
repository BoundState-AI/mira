#!/usr/bin/env python3
"""
Module: Policy Pack Loader
Purpose: Load and validate policy packs from YAML

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .pack import ClosurePathRule, PolicyPack, ReviewerHeuristic, RoutingThreshold

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False

# Default policy pack location
DEFAULT_POLICY_DIR = Path(__file__).parent.parent / "data" / "policy_packs"


def load_policy_pack(path: Path) -> PolicyPack:
    """
    Load a policy pack from YAML file.

    Args:
        path: Path to YAML file.

    Returns:
        Loaded PolicyPack.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If YAML is invalid.
    """
    LOGGER.info(f"Loading policy pack from {path}")

    if not path.exists():
        raise FileNotFoundError(f"Policy pack not found: {path}")

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    # Convert nested structures
    if "threshold_overrides" in data:
        data["threshold_overrides"] = {
            k: RoutingThreshold(**v) for k, v in data["threshold_overrides"].items()
        }

    if "closure_path_rules" in data:
        data["closure_path_rules"] = [
            ClosurePathRule(**r) for r in data["closure_path_rules"]
        ]

    if "reviewer_heuristics" in data:
        data["reviewer_heuristics"] = [
            ReviewerHeuristic(**h) for h in data["reviewer_heuristics"]
        ]

    pack = PolicyPack(**data)
    pack.content_hash = pack.compute_hash()

    LOGGER.info(f"Loaded policy pack: {pack.name} v{pack.version}")
    return pack


def load_default_policy_pack() -> PolicyPack:
    """
    Load the default policy pack.

    Returns:
        Default PolicyPack.
    """
    default_path = DEFAULT_POLICY_DIR / "default.yaml"

    if default_path.exists():
        return load_policy_pack(default_path)

    # Return built-in default if file doesn't exist
    LOGGER.info("Using built-in default policy pack")
    return create_default_policy_pack()


def create_default_policy_pack() -> PolicyPack:
    """
    Create a default policy pack with standard values.

    Returns:
        Default PolicyPack with NASA-STD-6016C thresholds.
    """
    pack = PolicyPack(
        policy_pack_id="default",
        name="NASA-STD-6016C Default",
        version="1.0.0",
        applicable_centers=["ALL"],
        applicable_programs=["ALL"],
        # Vehicle environments from spec
        vehicle_environments={
            "ISS": {
                "name": "ISS Habitable Volume",
                "o2_pct": 30.0,
                "pressure_psia": 14.7,
                "temp_range_c": [15.6, 26.7],
                "habitable": True,
                "vacuum_exposure": False,
                "lunar_dust": False,
                "source": "SSP 30233",
                "phase": "nominal",
            },
            "HLS": {
                "name": "HLS Lunar Lander",
                "o2_pct": 37.0,
                "pressure_psia": 8.2,
                "temp_range_c": [-50.0, 120.0],
                "habitable": True,
                "vacuum_exposure": True,
                "lunar_dust": True,
                "source": "HLS-RQMT-001",
                "phase": "nominal",
            },
            "ORION": {
                "name": "Orion Crew Module",
                "o2_pct": 34.0,
                "pressure_psia": 10.2,
                "temp_range_c": [18.3, 26.7],
                "habitable": True,
                "vacuum_exposure": False,
                "lunar_dust": False,
                "source": "Orion MPCV",
                "phase": "nominal",
            },
            "GATEWAY": {
                "name": "Gateway Habitation",
                "o2_pct": 34.0,
                "pressure_psia": 10.2,
                "temp_range_c": [18.3, 26.7],
                "habitable": True,
                "vacuum_exposure": False,
                "lunar_dust": False,
                "source": "Gateway ICD",
                "phase": "nominal",
            },
            "EVA_SUIT": {
                "name": "EVA Suit (EMU/xEMU)",
                "o2_pct": 100.0,
                "pressure_psia": 4.3,
                "temp_range_c": [-157.0, 121.0],
                "habitable": False,
                "vacuum_exposure": True,
                "lunar_dust": True,
                "source": "EMU/xEMU requirements",
                "phase": "nominal",
            },
        },
        # Standard thresholds
        threshold_overrides={
            "o2_pct_flammability": RoutingThreshold(
                parameter="o2_pct",
                operator="gt",
                value=23.5,
            ),
            "minor_qty_mass": RoutingThreshold(
                parameter="mass_g",
                operator="lte",
                value=45.0,
            ),
            "minor_qty_area": RoutingThreshold(
                parameter="surface_area_cm2",
                operator="lte",
                value=13.0,
            ),
        },
        # Default reviewer heuristics
        reviewer_heuristics=[
            ReviewerHeuristic(
                trigger_condition="test_o2_pct < use_o2_pct",
                predicted_question="Verify flammability test O2% covers use condition",
                recommended_evidence="Test report with O2% and pressure conditions",
            ),
            ReviewerHeuristic(
                trigger_condition="minor_quantity_group_count > 1",
                predicted_question="Verify aggregation doesn't exceed limits",
                recommended_evidence="Aggregation calculation worksheet",
            ),
        ],
        created_by="system",
        created_at=datetime.now(),
    )

    pack.content_hash = pack.compute_hash()
    return pack


def list_available_packs(
    directory: Optional[Path] = None,
) -> list[dict[str, str]]:
    """
    List available policy packs.

    Args:
        directory: Directory to search (default: data/policy_packs).

    Returns:
        List of dicts with pack info.
    """
    search_dir = directory or DEFAULT_POLICY_DIR

    packs = []

    if search_dir.exists():
        for yaml_file in search_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r") as f:
                    data = yaml.safe_load(f)
                packs.append(
                    {
                        "id": data.get("policy_pack_id", yaml_file.stem),
                        "name": data.get("name", yaml_file.stem),
                        "version": data.get("version", "unknown"),
                        "path": str(yaml_file),
                    }
                )
            except Exception as e:
                LOGGER.warning(f"Could not read {yaml_file}: {e}")

    # Always include default
    if not any(p["id"] == "default" for p in packs):
        packs.append(
            {
                "id": "default",
                "name": "NASA-STD-6016C Default",
                "version": "1.0.0",
                "path": "built-in",
            }
        )

    return packs
