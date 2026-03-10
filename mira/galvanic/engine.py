"""Galvanic corrosion assessment engine."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from mira.galvanic.mitigation_recommender import recommend_mitigations
from mira.galvanic.models import (
    EnvironmentDescriptor,
    GalvanicAssessmentRequest,
    GalvanicAssessmentResponse,
    MaterialSearchResult,
    MaterialStateBand,
    ResolvedMaterial,
)


DATA_DIR = Path(__file__).resolve().parent / "data"
SCREENING_DISCLAIMER = (
    "This is a potential-difference screening per NASA-STD-6012A CPR 39. "
    "Where MIL-STD-889D kinetics data exists for this couple, a kinetics-aware "
    "assessment is recommended for certification-level decisions."
)

ENVIRONMENTS: dict[str, EnvironmentDescriptor] = {
    "seawater_proxy": EnvironmentDescriptor(
        key="seawater_proxy",
        label="Seawater / Salt Fog",
        modifier=1.0,
        notes="Reference wet-service environment for galvanic screening.",
    ),
    "coastal_condensing": EnvironmentDescriptor(
        key="coastal_condensing",
        label="Coastal Condensing Humidity",
        modifier=0.7,
        notes="Coastal condensation lowers driving severity relative to immersion.",
    ),
    "industrial_atm": EnvironmentDescriptor(
        key="industrial_atm",
        label="Industrial Atmosphere",
        modifier=0.6,
        notes="Industrial atmosphere remains corrosive but below seawater immersion.",
    ),
    "rural_atm": EnvironmentDescriptor(
        key="rural_atm",
        label="Rural Atmosphere",
        modifier=0.3,
        notes="Dry ambient service significantly suppresses galvanic risk.",
    ),
    "crew_condensing": EnvironmentDescriptor(
        key="crew_condensing",
        label="Controlled Interior / Crew",
        modifier=0.5,
        notes="Interior condensation can still sustain galvanic cells.",
    ),
    "dry_indoor": EnvironmentDescriptor(
        key="dry_indoor",
        label="Dry Controlled Indoor",
        modifier=0.15,
        notes="Dry controlled conditions greatly reduce galvanic exposure.",
    ),
    "cryogenic_ops": EnvironmentDescriptor(
        key="cryogenic_ops",
        label="Cryogenic Ground Ops",
        modifier=0.8,
        notes="Pre-cool and condensation conditions remain galvanically relevant.",
    ),
    "space_vacuum": EnvironmentDescriptor(
        key="space_vacuum",
        label="Space / Hard Vacuum",
        modifier=0.0,
        notes="No electrolyte means galvanic corrosion is not active in hard vacuum.",
    ),
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


@lru_cache(maxsize=1)
def _load_series_payload() -> dict[str, Any]:
    with (DATA_DIR / "galvanic_series.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _series_records() -> list[dict[str, Any]]:
    return list(_load_series_payload()["records"])


@lru_cache(maxsize=1)
def _series_by_group() -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in _series_records():
        groups.setdefault(record["variant_group"], []).append(record)
    for key in groups:
        groups[key].sort(key=lambda item: (item.get("state") != "passive", item["name"]))
    return groups


@lru_cache(maxsize=1)
def _manifest_version() -> str:
    return str(_load_series_payload().get("version", "0.1.0"))


@lru_cache(maxsize=1)
def _search_index() -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for record in _series_records():
        group = record["variant_group"]
        terms = [record["name"], *record.get("aliases", [])]
        for term in terms:
            index.setdefault(_normalize(term), set()).add(group)
    return index


def _find_groups(query: str) -> list[str]:
    normalized = _normalize(query)
    index = _search_index()
    candidate_queries = [normalized]
    if normalized.endswith("ss") and len(normalized) > 2:
        candidate_queries.append(normalized[:-2])

    for candidate in candidate_queries:
        if candidate in index:
            return sorted(index[candidate])

    matches: list[str] = []
    for key, groups in index.items():
        if any(candidate in key for candidate in candidate_queries) or (
            len(key) >= 4 and any(key in candidate for candidate in candidate_queries)
        ):
            matches.extend(groups)
    unique = list(dict.fromkeys(matches))
    return unique


def _build_possible_states(records: list[dict[str, Any]]) -> list[MaterialStateBand]:
    states = []
    for record in records:
        states.append(
            MaterialStateBand(
                state=record.get("state", "single"),
                representative_potential_mv_sce=float(record["representative_potential_mv_sce"]),
            )
        )
    return states


def _resolve_material_family(query: str) -> tuple[str, list[dict[str, Any]]]:
    groups = _find_groups(query)
    if not groups:
        raise ValueError(f"Material not found: {query}")
    group = groups[0]
    return group, _series_by_group()[group]


def _choose_variant_pair(
    material_a_records: list[dict[str, Any]],
    material_b_records: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], float]:
    best_pair: tuple[dict[str, Any], dict[str, Any], float] | None = None
    for record_a in material_a_records:
        for record_b in material_b_records:
            delta = abs(
                float(record_a["representative_potential_mv_sce"])
                - float(record_b["representative_potential_mv_sce"])
            )
            if best_pair is None or delta > best_pair[2]:
                best_pair = (record_a, record_b, delta)
    assert best_pair is not None
    return best_pair


def _surface_modifier(surface_condition: str | None) -> float:
    normalized = (surface_condition or "").strip().lower()
    if normalized in {"anodized", "conversion-coated"}:
        return 0.8
    if normalized in {"passivated", "primed"}:
        return 0.9
    if normalized in {"painted"}:
        return 0.85
    return 1.0


def _has_full_circuit_break(surface_condition: str | None) -> bool:
    return (surface_condition or "").strip().lower() in {"fully_coated", "isolated"}


def _area_factor(ratio: float | None) -> float:
    if ratio is None:
        return 1.0
    return max(0.4, min(2.5, math.log10(ratio) + 1.0))


def _classify(delta_mv: float) -> tuple[str, str]:
    if delta_mv < 250:
        return "COMPATIBLE", "NASA_STD_6012A_CPR39"
    if delta_mv <= 500:
        return "CAUTION", "BOUNDSTATE_SYNTHESIZED"
    return "INCOMPATIBLE", "BOUNDSTATE_SYNTHESIZED"


def _resolved_material_response(
    query: str,
    group_records: list[dict[str, Any]],
    chosen_record: dict[str, Any],
) -> ResolvedMaterial:
    primary = next((record for record in group_records if record.get("primary")), group_records[0])
    return ResolvedMaterial(
        query=query,
        canonical_name=primary["canonical_name"],
        family=primary["family"],
        chosen_state=chosen_record.get("state", "single"),
        representative_potential_mv_sce=float(chosen_record["representative_potential_mv_sce"]),
        potential_range_mv_sce=(
            float(chosen_record["potential_range_mv_sce"][0]),
            float(chosen_record["potential_range_mv_sce"][1]),
        ),
        possible_states=_build_possible_states(group_records),
        source_type=str(chosen_record["source_type"]),
    )


def evaluate_galvanic_assessment(
    request: GalvanicAssessmentRequest,
) -> GalvanicAssessmentResponse:
    environment = ENVIRONMENTS[request.environment]
    warnings: list[str] = []

    if request.couple_context.electrical_contact == "NO":
        material_a_group, material_a_records = _resolve_material_family(request.material_a)
        material_b_group, material_b_records = _resolve_material_family(request.material_b)
        chosen_a, chosen_b, raw_delta = _choose_variant_pair(material_a_records, material_b_records)
        response_a = _resolved_material_response(request.material_a, material_a_records, chosen_a)
        response_b = _resolved_material_response(request.material_b, material_b_records, chosen_b)
        return GalvanicAssessmentResponse(
            severity="COMPATIBLE",
            raw_delta_mv=raw_delta,
            effective_delta_mv=0.0,
            decision_basis="NO_ELECTRICAL_CONTACT",
            screening_disclaimer=SCREENING_DISCLAIMER,
            environment=request.environment,
            environment_modifier=environment.modifier,
            application_type=request.application_type,
            anode=response_a.canonical_name if response_a.representative_potential_mv_sce < response_b.representative_potential_mv_sce else response_b.canonical_name,
            cathode=response_b.canonical_name if response_a.representative_potential_mv_sce < response_b.representative_potential_mv_sce else response_a.canonical_name,
            material_a=response_a,
            material_b=response_b,
            warnings=["No electrical contact — galvanic corrosion is not active."],
            mitigations=[],
            source_manifest_version=_manifest_version(),
        )

    material_a_group, material_a_records = _resolve_material_family(request.material_a)
    material_b_group, material_b_records = _resolve_material_family(request.material_b)
    chosen_a, chosen_b, raw_delta_mv = _choose_variant_pair(material_a_records, material_b_records)

    material_a = _resolved_material_response(request.material_a, material_a_records, chosen_a)
    material_b = _resolved_material_response(request.material_b, material_b_records, chosen_b)

    if request.environment == "space_vacuum":
        warnings.append("Galvanic corrosion is not active in hard vacuum because no electrolyte is present.")
        severity = "COMPATIBLE"
        decision_basis = "NO_ELECTROLYTE"
        effective_delta_mv = 0.0
    elif _has_full_circuit_break(request.surface_condition_a) or _has_full_circuit_break(request.surface_condition_b):
        warnings.append("A full coating or isolation barrier opens the galvanic circuit for the assessed condition.")
        severity = "COMPATIBLE"
        decision_basis = "NO_ELECTROLYTE"
        effective_delta_mv = 0.0
    else:
        effective_delta_mv = raw_delta_mv
        effective_delta_mv *= environment.modifier
        effective_delta_mv *= _area_factor(request.couple_context.cathode_to_anode_area_ratio)
        effective_delta_mv *= _surface_modifier(request.surface_condition_a)
        effective_delta_mv *= _surface_modifier(request.surface_condition_b)
        if request.couple_context.electrolyte_pooling:
            effective_delta_mv *= 1.15
            warnings.append("Electrolyte pooling increases persistence of the galvanic cell.")
        severity, decision_basis = _classify(effective_delta_mv)

    a_potential = material_a.representative_potential_mv_sce
    b_potential = material_b.representative_potential_mv_sce
    anode = material_a.canonical_name if a_potential < b_potential else material_b.canonical_name
    cathode = material_b.canonical_name if a_potential < b_potential else material_a.canonical_name

    families = {material_a.family, material_b.family}
    if "conductive_carbon" in families and "metal" not in families:
        pass
    if "conductive_carbon" in families and len(families) > 1:
        warnings.append("Graphite/CFRP contacts with metals must be treated as dissimilar couples and sealed per CPR 40.")
        if request.couple_context.joint_type == "FASTENER":
            warnings.append("Titanium fasteners may be used with graphite composites when wet installed with sealant or primer.")
    if "magnesium" in families:
        warnings.append("Magnesium in any couple requires the maximum feasible protective system per MIL-STD-889D §5.10.")
    if request.couple_context.cathode_to_anode_area_ratio and request.couple_context.cathode_to_anode_area_ratio > 10:
        warnings.append("Large cathode-to-anode area ratio intensifies attack on the anodic member.")
    if request.couple_context.joint_type == "FASTENER" and severity != "COMPATIBLE":
        warnings.append("For dissimilar fastener joints, the fastener should be the cathodic member per CPR 34.")

    mitigations = recommend_mitigations(
        request,
        severity=severity,
        material_a_family=material_a.family,
        material_b_family=material_b.family,
        warnings=warnings,
    )

    return GalvanicAssessmentResponse(
        severity=severity,
        raw_delta_mv=raw_delta_mv,
        effective_delta_mv=effective_delta_mv,
        decision_basis=decision_basis,  # type: ignore[arg-type]
        screening_disclaimer=SCREENING_DISCLAIMER,
        environment=request.environment,
        environment_modifier=environment.modifier,
        application_type=request.application_type,
        anode=anode,
        cathode=cathode,
        material_a=material_a,
        material_b=material_b,
        warnings=warnings,
        mitigations=mitigations,
        source_manifest_version=_manifest_version(),
    )


def search_materials(query: str) -> list[MaterialSearchResult]:
    matches = _find_groups(query)
    results: list[MaterialSearchResult] = []
    for group in matches[:20]:
        records = _series_by_group()[group]
        primary = next((record for record in records if record.get("primary")), records[0])
        aliases = sorted(
            {
                alias
                for record in records
                for alias in record.get("aliases", [])
            }
        )
        results.append(
            MaterialSearchResult(
                canonical_name=primary["canonical_name"],
                family=primary["family"],
                aliases=aliases,
            )
        )
    return results


def list_environments() -> list[EnvironmentDescriptor]:
    return list(ENVIRONMENTS.values())


def get_series_payload() -> dict[str, Any]:
    return _load_series_payload()
