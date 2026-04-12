"""Mitigation recommendation engine for galvanic assessments."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from mira.galvanic.models import GalvanicAssessmentRequest, MitigationRecommendation


DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def _load_mitigations() -> dict[str, dict]:
    with (DATA_DIR / "galvanic_mitigations.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {entry["mitigation_id"]: entry for entry in payload["entries"]}


def _build_recommendation(entry: dict, trigger_reason: str) -> MitigationRecommendation:
    return MitigationRecommendation(
        mitigation_id=entry["mitigation_id"],
        name=entry["name"],
        mechanism=entry["mechanism"],
        mitigation_class=entry["mitigation_class"],
        boundstate_priority=entry["boundstate_priority"],
        description=entry["description"],
        source_clauses=entry["source_clauses"],
        standards=entry["standards"],
        restrictions=entry["restrictions"],
        notes=entry["notes"],
        coat_cathode_warning=entry["coat_cathode_warning"],
        trigger_reason=trigger_reason,
    )


def recommend_mitigations(
    request: GalvanicAssessmentRequest,
    *,
    severity: str,
    material_a_family: str,
    material_b_family: str,
    warnings: list[str],
) -> list[MitigationRecommendation]:
    entries = _load_mitigations()
    selected: dict[str, MitigationRecommendation] = {}
    families = {material_a_family, material_b_family}
    joint_type = request.couple_context.joint_type
    app_type = request.application_type
    wet_environment = request.environment not in {"dry_indoor", "space_vacuum"}
    contains_carbon = bool(families & {"conductive_carbon"})
    contains_aluminum = bool(families & {"aluminum"})
    contains_stainless = bool(families & {"stainless", "stainless_ph"})
    contains_steel = bool(families & {"steel"})
    contains_magnesium = bool(families & {"magnesium"})

    def add(mitigation_id: str, reason: str) -> None:
        if mitigation_id not in entries or mitigation_id in selected:
            return
        selected[mitigation_id] = _build_recommendation(entries[mitigation_id], reason)

    # NASA-STD-6012A CPR 39: Dissimilar metal couples require separation
    # barriers, electrolyte exclusion, or barrier coatings depending on
    # severity and application.
    if severity in {"CAUTION", "INCOMPATIBLE"}:
        add("physical_isolation", "Dissimilar couple requires a primary separation barrier per CPR 39.")
        add("seal_faying_surfaces", "Electrolyte exclusion required per CPR 39 for dissimilar couples.")
        add("cathodic_barrier_coating", "Barrier coating per CPR 39 when isolation is not feasible.")

    # CPR 39 §4.3.1: Fastener joints require wet-install sealant.
    if joint_type == "FASTENER":
        add("wet_install_fasteners", "Fastener joint selected; wet-install protection applies per CPR 39 §4.3.1.")

    # CPR 40: Graphite/CFRP contacts require sealing and isolation.
    if contains_carbon:
        add("seal_faying_surfaces", "Graphite/CFRP contacts must be sealed per CPR 40.")
        add("physical_isolation", "Conductive carbon should be isolated from metals per CPR 40.")
        if joint_type == "FASTENER":
            add("titanium_fasteners_for_cfrp", "Titanium fasteners preferred for CFRP joints per CPR 40 §4.4.")
            add("wet_install_fasteners", "Titanium fasteners in graphite joints must be wet installed per CPR 40.")

    # CPR 39 §4.2: Magnesium is the most anodic common structural metal;
    # requires maximum feasible protection in any dissimilar couple.
    if contains_magnesium:
        add("physical_isolation", "Magnesium requires maximum feasible protection per CPR 39 §4.2.")
        if wet_environment and app_type != "FLIGHT_HARDWARE":
            add("sacrificial_anode_gacp", "Wet service plus magnesium may justify sacrificial protection.")

    # CPR 39 §4.1: Anodizing is baseline corrosion control for aluminum alloys.
    if contains_aluminum:
        add("anodize_aluminum", "Aluminum alloy present; anodize is baseline per CPR 39 §4.1.")

    # ASTM A967: Stainless steel fasteners should be passivated.
    if contains_stainless and joint_type == "FASTENER":
        add("passivate_stainless_fasteners", "Stainless fasteners should be passivated per ASTM A967.")

    if contains_steel:
        add("zinc_nickel_plating_for_steel", "Steel surface protection is recommended for galvanic service.")
        if severity == "INCOMPATIBLE":
            add("cadmium_plating_restricted", "Cadmium remains a restricted last-resort option for steel coatings.")

    if severity == "INCOMPATIBLE" and wet_environment and app_type in {
        "GROUND_SUPPORT_EQUIPMENT",
        "LAUNCH_STRUCTURE",
        "FIXED_INSTALLATION",
    }:
        add("sacrificial_anode_gacp", "Wet incompatible couple supports sacrificial anode mitigation.")
        add("iccp_structures_only", "Application type permits ICCP as a system-level option.")

    # Sort by BoundState priority, preserving unique recommendations only.
    return sorted(selected.values(), key=lambda item: item.boundstate_priority)
