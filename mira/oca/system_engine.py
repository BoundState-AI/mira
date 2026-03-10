#!/usr/bin/env python3
"""
Module: OCA System Engine (Phase 2)
Purpose: Topology inference, staged recompute, and system-level assessment
         for the Visual System Builder per BS-SPEC-OCA-002-REV0.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6001B, NASA-STD-6016C, SWE-013, SWE-032
Safety Critical: True

Architecture:
  - Topology Inference Engine: graph analysis for dead ends, flow, velocity, zones
  - Feature Derivation Engine: compute feature flags from archetype + config + materials
  - Staged Recompute: only reassess affected subgraph on topology change
  - System Assessment: per-component mechanism eval + system-level kindling chain
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .engine import (
    OCAEngine,
    adiabatic_compression_temperature,
    assess_ignition_mechanisms,
    determine_disposition,
    evaluate_kindling_chain,
    evaluate_requirement_triggers,
    generate_hazard_controls,
    generate_mua_seed,
    get_oca_engine,
    retrieve_evidence,
)
from .models import (
    BlockedState,
    BlockedStateType,
    ComponentInfo,
    CredibleStatus,
    FlammabilityRating,
    GeometryClass,
    HazardControlEntry,
    IgnitionMechanismName,
    KindlingChainResult,
    MaterialInstance,
    MechanismTrace,
    MUASeed,
    OCADisposition,
    OxidizerType,
    OxygenPhase,
    OxygenServiceContext,
    ReactionEffect,
    RuleTier,
    TriggeredRequirement,
)
from .system_models import (
    AddComponentRequest,
    ComponentArchetype,
    ComponentConfig,
    ComponentFeatureFlags,
    InferenceConfidence,
    InferenceSource,
    InferredFact,
    MaterialSlotValue,
    OCASystemAssembly,
    OpeningProfile,
    PathInspectorResult,
    SAVolumeRatio,
    SeatContactMode,
    SonicFlowPoint,
    SystemComponent,
    SystemConnection,
    SystemInputs,
    SystemKindlingChain,
    SystemZoneType,
    TopologyInferenceResult,
    VelocityEstimate,
)

LOGGER = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent / "data"

# Mechanism abbreviation map
MECHANISM_ABBREV = {
    "particle_impact": "PI",
    "rapid_pressurization": "RP",
    "flow_friction": "FF",
    "resonance": "RS",
    "mechanical_impact": "MI",
    "galling_friction": "GF",
    "fresh_metal_exposure": "FM",
    "static_discharge": "SD",
    "electrical_arc": "EA",
    "chemical_reaction": "CR",
    "thermal_runaway": "TR",
    "other": "OT",
}


# ---------------------------------------------------------------------------
# Feature Derivation Engine
# ---------------------------------------------------------------------------

def derive_features(
    archetype: ComponentArchetype,
    config: ComponentConfig,
    materials: list[MaterialSlotValue],
) -> ComponentFeatureFlags:
    """Derive feature flags from archetype, config, and materials."""
    # Load defaults from library
    lib_path = _DATA_DIR / "oca_component_library.json"
    defaults = ComponentFeatureFlags()
    if lib_path.exists():
        with open(lib_path) as f:
            lib = json.load(f)
        for arch in lib.get("archetypes", []):
            if arch["archetype_id"] == archetype.value:
                df = arch.get("default_features", {})
                defaults = ComponentFeatureFlags(**{
                    k: v for k, v in df.items()
                    if k in ComponentFeatureFlags.model_fields and v is not None
                })
                break

    features = defaults.model_copy()

    # Derive from materials
    has_nonmetal = False
    has_reactive = False
    material_names = []
    for ms in materials:
        mat = ms.material
        name_lower = mat.material_name.lower()
        material_names.append(name_lower)
        if mat.is_nonmetal or any(kw in name_lower for kw in (
            "teflon", "ptfe", "viton", "kel-f", "pctfe", "silicone",
            "rubber", "nylon", "peek", "vespel", "polyimide", "epoxy",
        )):
            has_nonmetal = True
        if mat.is_titanium or any(kw in name_lower for kw in (
            "titanium", "ti-6al-4v", "ti-", "aluminum", "al ", "al-",
            "6061", "7075", "2024", "magnesium", "lithium",
        )):
            has_reactive = True

    if has_nonmetal:
        features.has_polymer_seal = True
    if has_reactive:
        features.reactive_metal_present = True

    # Derive from config
    if config.actuation_type and config.actuation_type == "solenoid":
        features.electrical_energy_present = True

    if config.bypass_path_exists:
        features.filter_integrity_assumed = False

    if config.exposed_to_flow:
        features.wetted_surface_flag = True

    if config.is_flex:
        features.has_moving_contact = True
        features.dynamic_contact_flag = True
        features.creates_particles = True

    # SA/V ratio from archetype
    if archetype in (ComponentArchetype.FILTER, ComponentArchetype.HEAT_EXCHANGER):
        features.sa_to_volume_ratio = SAVolumeRatio.HIGH
    elif archetype == ComponentArchetype.GASKET:
        features.sa_to_volume_ratio = SAVolumeRatio.LOW

    # Seat contact mode from multi-material analysis
    if len(materials) >= 2:
        seat_slots = [ms for ms in materials if "seat" in ms.slot_name.lower()]
        body_slots = [ms for ms in materials if "body" in ms.slot_name.lower() or "stem" in ms.slot_name.lower()]
        if seat_slots and body_slots:
            seat_nonmetal = any(ms.material.is_nonmetal for ms in seat_slots)
            body_nonmetal = any(ms.material.is_nonmetal for ms in body_slots)
            if seat_nonmetal and body_nonmetal:
                features.seat_contact_mode = SeatContactMode.POLYMER_TO_POLYMER
            elif seat_nonmetal or body_nonmetal:
                features.seat_contact_mode = SeatContactMode.METAL_TO_POLYMER
            else:
                features.seat_contact_mode = SeatContactMode.METAL_TO_METAL
                features.metal_pair_contact = True

    return features


# ---------------------------------------------------------------------------
# Topology Inference Engine
# ---------------------------------------------------------------------------

def build_adjacency(
    components: list[SystemComponent],
    connections: list[SystemConnection],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build forward and reverse adjacency lists from connections."""
    forward: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    comp_ids = {c.component_id for c in components}

    for conn in connections:
        if conn.source_component_id in comp_ids and conn.target_component_id in comp_ids:
            forward[conn.source_component_id].append(conn.target_component_id)
            reverse[conn.target_component_id].append(conn.source_component_id)

    return dict(forward), dict(reverse)


def get_downstream_ids(
    start_id: str,
    forward: dict[str, list[str]],
) -> set[str]:
    """BFS to get all downstream component IDs."""
    visited: set[str] = set()
    queue = [start_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for neighbor in forward.get(current, []):
            if neighbor not in visited:
                queue.append(neighbor)
    visited.discard(start_id)
    return visited


def get_upstream_ids(
    start_id: str,
    reverse: dict[str, list[str]],
) -> set[str]:
    """BFS to get all upstream component IDs."""
    visited: set[str] = set()
    queue = [start_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for neighbor in reverse.get(current, []):
            if neighbor not in visited:
                queue.append(neighbor)
    visited.discard(start_id)
    return visited


def run_topology_inference(
    system: OCASystemAssembly,
) -> TopologyInferenceResult:
    """Run full topology inference on the system assembly."""
    components = system.components
    connections = system.connections
    inputs = system.inputs
    comp_map = {c.component_id: c for c in components}

    forward, reverse = build_adjacency(components, connections)
    connected_ids = set(forward.keys()) | set(reverse.keys())

    result = TopologyInferenceResult()

    # --- Dead-end detection (TOPO-001) ---
    for comp in components:
        cid = comp.component_id
        in_count = len(reverse.get(cid, []))
        out_count = len(forward.get(cid, []))
        total_connections = in_count + out_count

        if total_connections == 1 and comp.archetype != ComponentArchetype.GASKET:
            result.dead_end_component_ids.append(cid)
            comp.features.has_dead_volume = True
            result.inferred_facts.append(InferredFact(
                fact_name="dead_end",
                value=True,
                source=InferenceSource.INFERRED,
                confidence=InferenceConfidence.HIGH,
                rule_id="TOPO-001",
                explanation=f"Component '{comp.label or comp.archetype.value}' has only {total_connections} connection — dead-end volume.",
            ))
        elif total_connections == 0 and comp.archetype != ComponentArchetype.GASKET:
            # Unconnected — treat as isolated dead end
            result.dead_end_component_ids.append(cid)
            comp.features.has_dead_volume = True
            comp.connected = False

    # --- Flow direction (TOPO-002) ---
    for conn in connections:
        result.flow_direction.append((conn.source_component_id, conn.target_component_id))

    # --- Velocity estimation (TOPO-003) ---
    if inputs.design_flow_rate_m3_s and inputs.design_flow_rate_m3_s > 0:
        for comp in components:
            if comp.archetype == ComponentArchetype.LINE and comp.config.inner_diameter_mm:
                r_m = (comp.config.inner_diameter_mm / 1000.0) / 2.0
                area = math.pi * r_m * r_m
                if area > 0:
                    vel = inputs.design_flow_rate_m3_s / area
                    result.velocity_estimates.append(VelocityEstimate(
                        component_id=comp.component_id,
                        velocity_m_s=round(vel, 2),
                        inner_diameter_mm=comp.config.inner_diameter_mm,
                        flow_rate_m3_s=inputs.design_flow_rate_m3_s,
                    ))
                    result.inferred_facts.append(InferredFact(
                        fact_name="velocity_estimate",
                        value=round(vel, 2),
                        source=InferenceSource.CALCULATED,
                        confidence=InferenceConfidence.MEDIUM,
                        rule_id="TOPO-003",
                        explanation=f"v = Q/A = {inputs.design_flow_rate_m3_s}/{area:.6f} = {vel:.2f} m/s",
                        missing_assumptions=["Incompressible flow assumed"],
                    ))

    # --- Sonic flow points (TOPO-004) ---
    for comp in components:
        if comp.archetype == ComponentArchetype.ORIFICE and comp.config.bore_diameter_mm:
            # Check pressure ratio
            p_up = inputs.system_pressure_max_psia
            # Assume downstream at ~50% of upstream if no regulator downstream
            downstream_comps = forward.get(comp.component_id, [])
            p_down = inputs.system_pressure_min_psia or (p_up * 0.5)
            for dc_id in downstream_comps:
                dc = comp_map.get(dc_id)
                if dc and dc.archetype == ComponentArchetype.REGULATOR and dc.config.set_pressure_psia:
                    p_down = dc.config.set_pressure_psia

            if p_down > 0:
                ratio = p_up / p_down
                if ratio > 1.893:
                    result.sonic_flow_points.append(SonicFlowPoint(
                        component_id=comp.component_id,
                        pressure_ratio=round(ratio, 2),
                        bore_diameter_mm=comp.config.bore_diameter_mm,
                        downstream_component_ids=list(get_downstream_ids(comp.component_id, forward)),
                    ))
                    result.inferred_facts.append(InferredFact(
                        fact_name="sonic_flow_point",
                        value=True,
                        source=InferenceSource.CALCULATED,
                        confidence=InferenceConfidence.MEDIUM,
                        rule_id="TOPO-004",
                        explanation=f"Pressure ratio {ratio:.2f} > 1.893 — sonic flow at orifice.",
                    ))

    # --- Filter protection regions (TOPO-005) ---
    for comp in components:
        if comp.archetype == ComponentArchetype.FILTER:
            bypass = comp.config.bypass_path_exists or False
            if not bypass:
                downstream = get_downstream_ids(comp.component_id, forward)
                for did in downstream:
                    if did not in result.filter_protected_ids:
                        result.filter_protected_ids.append(did)
                    dc = comp_map.get(did)
                    if dc:
                        dc.features.filter_integrity_assumed = True

                if downstream:
                    result.inferred_facts.append(InferredFact(
                        fact_name="filter_protection_region",
                        value=list(downstream),
                        source=InferenceSource.INFERRED,
                        confidence=InferenceConfidence.HIGH,
                        rule_id="TOPO-005",
                        explanation=f"Filter '{comp.label or 'filter'}' protects {len(downstream)} downstream component(s). Assumes filter intact, no bypass.",
                        missing_assumptions=["Filter element intact", "No bypass path"],
                    ))

    # --- Chatter candidates (TOPO-006) ---
    chatter_archetypes = {
        ComponentArchetype.REGULATOR,
        ComponentArchetype.CHECK_VALVE,
        ComponentArchetype.RELIEF_VALVE,
    }
    for comp in components:
        if comp.archetype in chatter_archetypes:
            chatter = comp.config.chatter_susceptible
            if chatter is None or chatter:
                result.chatter_candidate_ids.append(comp.component_id)

    # --- Upstream volume (TOPO-007) ---
    for comp in components:
        if comp.archetype == ComponentArchetype.VALVE:
            opening = comp.config.opening_profile
            if opening == OpeningProfile.FAST or opening is None:
                upstream = get_upstream_ids(comp.component_id, reverse)
                total_vol = 0.0
                for uid in upstream:
                    uc = comp_map.get(uid)
                    if uc and uc.config.volume_liters:
                        total_vol += uc.config.volume_liters
                    elif uc and uc.archetype == ComponentArchetype.LINE:
                        if uc.config.inner_diameter_mm and uc.config.length_m:
                            r_m = (uc.config.inner_diameter_mm / 1000.0) / 2.0
                            vol_m3 = math.pi * r_m * r_m * uc.config.length_m
                            total_vol += vol_m3 * 1000.0  # to liters
                if total_vol > 0:
                    result.upstream_volumes[comp.component_id] = round(total_vol, 3)

    # --- Bi-directional flow risk (TOPO-008) ---
    if inputs.bi_directional_flow_risk:
        # Invalidate filter protection for reverse flow
        result.inferred_facts.append(InferredFact(
            fact_name="bi_directional_flow_risk",
            value=True,
            source=InferenceSource.USER_ENTERED,
            confidence=InferenceConfidence.LOW,
            rule_id="TOPO-008",
            explanation="Bi-directional flow risk flagged. Filter protection may be bypassed in reverse flow.",
        ))

    # --- Zone assignments ---
    for comp in components:
        cid = comp.component_id
        zones: list[SystemZoneType] = []

        # Unfiltered vs filtered
        if cid in result.filter_protected_ids and not inputs.bi_directional_flow_risk:
            zones.append(SystemZoneType.FILTERED)
        else:
            zones.append(SystemZoneType.UNFILTERED)

        # Dead leg
        if cid in result.dead_end_component_ids:
            zones.append(SystemZoneType.DEAD_LEG)

        # Dynamic
        if comp.features.dynamic_contact_flag:
            zones.append(SystemZoneType.DYNAMIC)

        # Cavity/resonance
        for sfp in result.sonic_flow_points:
            if cid in sfp.downstream_component_ids:
                zones.append(SystemZoneType.CAVITY_RESONANCE)
                break

        # Acceptance test
        if (inputs.system_pressure_max_psia > 265
                and inputs.phase in (OxidizerType.GOX, OxidizerType.ENRICHED_AIR)
                and not comp.is_rigid_metallic_tubing
                and not comp.is_metallic_flex_hose
                and not comp.is_all_metal_seal
                and not comp.is_metallic_pressure_vessel):
            zones.append(SystemZoneType.ACCEPTANCE_TEST)

        comp.zones = zones
        result.zone_assignments[cid] = zones

    # Mark connected components
    for comp in components:
        cid = comp.component_id
        if cid in connected_ids:
            comp.connected = True

    return result


# ---------------------------------------------------------------------------
# System Assessment Engine
# ---------------------------------------------------------------------------

def _build_component_service_context(
    comp: SystemComponent,
    inputs: SystemInputs,
    velocity_map: dict[str, float],
) -> OxygenServiceContext:
    """Build a Phase 1 OxygenServiceContext from system inputs + component."""
    vel = velocity_map.get(comp.component_id, 0.0)

    return OxygenServiceContext(
        case_id=comp.component_id,
        oxidizer_type=inputs.phase,
        o2_fraction=inputs.o2_fraction,
        total_pressure_min_psia=inputs.system_pressure_min_psia,
        total_pressure_max_psia=inputs.system_pressure_max_psia,
        phase=inputs.oxygen_phase,
        temp_min_c=inputs.temp_min_c,
        temp_max_c=inputs.temp_max_c,
        velocity_m_s=vel if vel > 0 else None,
        cleanliness_verified=bool(inputs.cleanliness_spec),
        mission_phase=inputs.mission_phase,
    )


def _build_component_info(comp: SystemComponent) -> ComponentInfo:
    """Build a Phase 1 ComponentInfo from a system component."""
    # Map archetype to component class
    archetype_to_class = {
        ComponentArchetype.VALVE: "valve",
        ComponentArchetype.REGULATOR: "regulator",
        ComponentArchetype.LINE: "line",
        ComponentArchetype.FILTER: "filter",
        ComponentArchetype.FITTING: "fitting",
        ComponentArchetype.PRESSURE_VESSEL: "vessel",
        ComponentArchetype.RELIEF_VALVE: "valve",
        ComponentArchetype.CHECK_VALVE: "valve",
        ComponentArchetype.ORIFICE: "fitting",
        ComponentArchetype.HEAT_EXCHANGER: "other",
        ComponentArchetype.GASKET: "seal",
        ComponentArchetype.FLEX_HOSE: "flex_hose",
    }
    # Map archetype to geometry class
    archetype_to_geom = {
        ComponentArchetype.FILTER: "sintered",
        ComponentArchetype.GASKET: "seal",
        ComponentArchetype.HEAT_EXCHANGER: "thin_wall",
        ComponentArchetype.FLEX_HOSE: "mesh",
    }

    from .models import ComponentClass
    comp_class_str = archetype_to_class.get(comp.archetype, "other")
    geom_str = archetype_to_geom.get(comp.archetype, "bulk")

    return ComponentInfo(
        component_id=comp.component_id,
        component_class=comp_class_str,
        geometry_class=geom_str,
        dynamic_contact_flag=comp.features.dynamic_contact_flag,
        is_rigid_metallic_tubing=comp.is_rigid_metallic_tubing,
        is_metallic_flex_hose=comp.is_metallic_flex_hose,
        is_all_metal_seal=comp.is_all_metal_seal,
        is_metallic_pressure_vessel=comp.is_metallic_pressure_vessel,
    )


def _get_component_materials(comp: SystemComponent) -> list[MaterialInstance]:
    """Extract MaterialInstance list from component's material slots."""
    return [ms.material for ms in comp.materials]


def assess_component(
    comp: SystemComponent,
    inputs: SystemInputs,
    velocity_map: dict[str, float],
    topology: TopologyInferenceResult,
) -> None:
    """Run Phase 1 mechanism assessment on a single component, updating it in place."""
    context = _build_component_service_context(comp, inputs, velocity_map)
    comp_info = _build_component_info(comp)
    materials = _get_component_materials(comp)

    if not materials:
        comp.overall_status = "pending"
        return

    # Normalize materials (same as Phase 1 engine)
    for mat in materials:
        if not mat.canonical_name:
            mat.canonical_name = mat.material_name.upper().strip()
        name_lower = mat.material_name.lower()
        if any(kw in name_lower for kw in ("titanium", "ti-6al-4v", "ti-", "ti ", "grade 5")):
            mat.is_titanium = True
        if any(kw in name_lower for kw in (
            "teflon", "ptfe", "viton", "kel-f", "pctfe", "silicone", "rubber",
            "nylon", "peek", "vespel", "polyimide", "epoxy", "composite",
        )):
            mat.is_nonmetal = True

    # Modify assessment based on topology inference
    # If filter-protected, suppress particle source
    if comp.features.filter_integrity_assumed:
        # Particle impact: reduce credibility
        pass  # Handled in mechanism assessment via velocity/feature checks

    # Run mechanism assessment
    mechanisms = assess_ignition_mechanisms(context, comp_info, materials)

    # Apply topology-aware adjustments
    for mech in mechanisms:
        # Filter protection reduces particle impact
        if (mech.mechanism_name == IgnitionMechanismName.PARTICLE_IMPACT
                and comp.features.filter_integrity_assumed
                and comp.component_id in topology.filter_protected_ids):
            if mech.credible_status == CredibleStatus.CREDIBLE:
                mech.credible_status = CredibleStatus.INDETERMINATE
                mech.rating = max(mech.rating - 1, 1)
                mech.reviewer_comments.append(
                    "Particle impact reduced: upstream filter assumed intact (no bypass). "
                    "Subject to filter integrity assumption."
                )

        # Dead-end enhances rapid pressurization
        if (mech.mechanism_name == IgnitionMechanismName.RAPID_PRESSURIZATION
                and comp.component_id in topology.dead_end_component_ids):
            if mech.credible_status == CredibleStatus.NOT_CREDIBLE and any(m.is_nonmetal for m in materials):
                mech.credible_status = CredibleStatus.INDETERMINATE
                mech.rating = max(mech.rating, 2)
                mech.reviewer_comments.append(
                    "Dead-end detected by topology. Rapid pressurization credibility elevated."
                )

        # Chatter enhances galling/mechanical impact
        if (mech.mechanism_name in (IgnitionMechanismName.GALLING_FRICTION, IgnitionMechanismName.MECHANICAL_IMPACT)
                and comp.component_id in topology.chatter_candidate_ids):
            if mech.credible_status == CredibleStatus.INDETERMINATE:
                mech.rating = max(mech.rating, 2)
                mech.reviewer_comments.append(
                    "Chatter candidate detected. Mechanical impact/galling risk elevated."
                )

        # Resonance from sonic flow
        if mech.mechanism_name == IgnitionMechanismName.RESONANCE:
            for sfp in topology.sonic_flow_points:
                if comp.component_id in sfp.downstream_component_ids:
                    if mech.credible_status == CredibleStatus.NOT_CREDIBLE:
                        mech.credible_status = CredibleStatus.INDETERMINATE
                        mech.rating = max(mech.rating, 2)
                        mech.reviewer_comments.append(
                            f"Sonic flow detected upstream (pressure ratio {sfp.pressure_ratio}). "
                            "Resonance credibility elevated."
                        )
                    break

    comp.mechanism_assessments = mechanisms

    # Compute overall status
    credible = [m for m in mechanisms if m.credible_status == CredibleStatus.CREDIBLE]
    indeterminate = [m for m in mechanisms if m.credible_status == CredibleStatus.INDETERMINATE]
    max_rating = max((m.rating for m in mechanisms), default=0)

    comp.highest_rating = max_rating
    comp.credible_mechanisms = [
        MECHANISM_ABBREV.get(m.mechanism_name.value, m.mechanism_name.value)
        for m in mechanisms
        if m.credible_status in (CredibleStatus.CREDIBLE, CredibleStatus.INDETERMINATE)
    ]

    if credible:
        comp.overall_status = "red"
    elif indeterminate:
        comp.overall_status = "yellow"
    else:
        comp.overall_status = "green"


def assess_system_kindling_chains(
    system: OCASystemAssembly,
) -> list[SystemKindlingChain]:
    """Evaluate kindling chain propagation across connected components."""
    comp_map = {c.component_id: c for c in system.components}
    forward, _ = build_adjacency(system.components, system.connections)

    chains: list[SystemKindlingChain] = []

    # For each component with credible mechanisms, trace propagation downstream
    for comp in system.components:
        if comp.overall_status != "red":
            continue

        # Trace downstream
        path = [comp.component_id]
        materials_in_path = []
        chain_broken_at = None
        break_reason = None

        # Collect materials for this component
        for ms in comp.materials:
            materials_in_path.append(f"{ms.material.material_name} ({ms.material.flammability_rating.value})")

        # Follow downstream
        current_id = comp.component_id
        visited = {current_id}

        while True:
            downstream = forward.get(current_id, [])
            if not downstream:
                break

            next_id = downstream[0]  # Follow primary path
            if next_id in visited:
                break
            visited.add(next_id)

            dc = comp_map.get(next_id)
            if not dc:
                break

            # Check if material is nonflammable (breaks chain)
            dc_materials = _get_component_materials(dc)
            has_nonflammable = any(
                m.flammability_rating in (FlammabilityRating.A, FlammabilityRating.B)
                for m in dc_materials
            )

            if has_nonflammable and dc_materials:
                chain_broken_at = next_id
                break_reason = f"Nonflammable material at '{dc.label or dc.archetype.value}'"
                path.append(next_id)
                for ms in dc.materials:
                    materials_in_path.append(f"{ms.material.material_name} ({ms.material.flammability_rating.value})")
                break

            path.append(next_id)
            for ms in dc.materials:
                materials_in_path.append(f"{ms.material.material_name} ({ms.material.flammability_rating.value})")
            current_id = next_id

        # Determine chain length and effect
        continuous_length = len(path)
        if chain_broken_at:
            continuous_length = path.index(chain_broken_at)

        # Reaction effect based on chain length and worst rating
        if continuous_length <= 1:
            effect = ReactionEffect.B
        elif continuous_length <= 3:
            effect = ReactionEffect.C
        else:
            effect = ReactionEffect.D

        if len(path) > 1:
            chains.append(SystemKindlingChain(
                propagation_path=path,
                materials_in_path=materials_in_path,
                chain_broken_at=chain_broken_at,
                break_reason=break_reason,
                longest_continuous_length=continuous_length,
                reaction_effect=effect,
            ))

    return chains


def run_system_assessment(system: OCASystemAssembly) -> None:
    """Run full system-level OCA assessment."""
    inputs = system.inputs

    # Check system-level blocked states
    system.system_blocked_states = []
    if not inputs.o2_fraction or inputs.o2_fraction <= 0:
        system.system_blocked_states.append(BlockedState(
            state_type=BlockedStateType.SERVICE_ENVELOPE_INCOMPLETE,
            description="O2 fraction missing or zero.",
            missing_fields=["o2_fraction"],
        ))
    if inputs.system_pressure_max_psia <= 0:
        system.system_blocked_states.append(BlockedState(
            state_type=BlockedStateType.SERVICE_ENVELOPE_INCOMPLETE,
            description="System pressure not set.",
            missing_fields=["system_pressure_max_psia"],
        ))

    # Check for unresolved materials
    for comp in system.components:
        if not comp.materials:
            system.system_blocked_states.append(BlockedState(
                state_type=BlockedStateType.MATERIAL_IDENTITY_UNRESOLVED,
                description=f"Component '{comp.label or comp.archetype.value}' has no materials assigned.",
                missing_fields=["materials"],
            ))

    # Run topology inference
    topology = run_topology_inference(system)
    system.topology = topology

    # Build velocity map
    velocity_map: dict[str, float] = {}
    for ve in topology.velocity_estimates:
        velocity_map[ve.component_id] = ve.velocity_m_s

    # Assess each component (Stage 3 of staged recompute)
    for comp in system.components:
        assess_component(comp, inputs, velocity_map, topology)

    # Check for titanium (MPR 67)
    system.has_titanium = any(
        ms.material.is_titanium
        for comp in system.components
        for ms in comp.materials
    )
    system.mpr67_active = False
    if system.has_titanium:
        o2_pp = inputs.system_pressure_max_psia * inputs.o2_fraction
        if inputs.phase in (OxidizerType.LOX, OxidizerType.GOX) or o2_pp > 5.0:
            system.mpr67_active = True

    # System-level requirement triggers
    all_materials = [
        ms.material
        for comp in system.components
        for ms in comp.materials
    ]
    system_context = OxygenServiceContext(
        oxidizer_type=inputs.phase,
        o2_fraction=inputs.o2_fraction,
        total_pressure_min_psia=inputs.system_pressure_min_psia,
        total_pressure_max_psia=inputs.system_pressure_max_psia,
        phase=inputs.oxygen_phase,
        mission_phase=inputs.mission_phase,
    )
    # Use a generic component for system-level triggers
    generic_comp = ComponentInfo()
    system.system_triggered_requirements = evaluate_requirement_triggers(
        system_context, generic_comp, all_materials
    )

    # Kindling chains
    system.kindling_chains = assess_system_kindling_chains(system)

    # System-level hazard controls
    system.system_hazard_controls = []
    for comp in system.components:
        comp_info = _build_component_info(comp)
        materials = _get_component_materials(comp)
        if materials:
            kindling = evaluate_kindling_chain(materials, comp_info, comp.mechanism_assessments)
            controls = generate_hazard_controls(comp_info, comp.mechanism_assessments, kindling)
            system.system_hazard_controls.extend(controls)

    # System disposition (worst case across all components)
    worst_disposition = OCADisposition.COMPATIBLE_AS_CONFIGURED
    disposition_order = [
        OCADisposition.COMPATIBLE_AS_CONFIGURED,
        OCADisposition.COMPATIBLE_WITH_CONTROLS,
        OCADisposition.REQUIRES_ACCEPTANCE_TEST,
        OCADisposition.REQUIRES_MUA,
        OCADisposition.REQUIRES_SUPPLEMENTAL_TESTING,
        OCADisposition.INSUFFICIENT_EVIDENCE,
    ]

    for comp in system.components:
        materials = _get_component_materials(comp)
        if not materials:
            continue
        comp_info = _build_component_info(comp)
        context = _build_component_service_context(comp, inputs, velocity_map)
        _, gaps = retrieve_evidence(materials, context)
        blocked = []
        if not materials:
            blocked.append(BlockedState(
                state_type=BlockedStateType.MATERIAL_IDENTITY_UNRESOLVED,
                description="No materials",
                missing_fields=["materials"],
            ))

        kindling = evaluate_kindling_chain(materials, comp_info, comp.mechanism_assessments)
        comp_disp = determine_disposition(
            system.system_triggered_requirements,
            comp.mechanism_assessments,
            kindling,
            [],
            gaps,
            blocked + system.system_blocked_states,
        )

        if disposition_order.index(comp_disp) > disposition_order.index(worst_disposition):
            worst_disposition = comp_disp

    system.system_disposition = worst_disposition

    # System reaction effect (worst case from kindling chains)
    effect_order = [ReactionEffect.A, ReactionEffect.B, ReactionEffect.C, ReactionEffect.D]
    worst_effect = ReactionEffect.A
    for chain in system.kindling_chains:
        if effect_order.index(chain.reaction_effect) > effect_order.index(worst_effect):
            worst_effect = chain.reaction_effect
    system.system_reaction_effect = worst_effect

    # MUA seeds
    system.mua_seeds = []
    for comp in system.components:
        materials = _get_component_materials(comp)
        if materials:
            context = _build_component_service_context(comp, inputs, velocity_map)
            _, gaps = retrieve_evidence(materials, context)
            seed = generate_mua_seed(context, materials, comp.mechanism_assessments, gaps, worst_disposition)
            if seed:
                system.mua_seeds.append(seed)

    system.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Path Inspector
# ---------------------------------------------------------------------------

def inspect_component_path(
    system: OCASystemAssembly,
    component_id: str,
) -> PathInspectorResult:
    """Generate path inspector result for a specific component."""
    comp_map = {c.component_id: c for c in system.components}
    comp = comp_map.get(component_id)
    if not comp:
        return PathInspectorResult(component_id=component_id)

    forward, reverse = build_adjacency(system.components, system.connections)

    result = PathInspectorResult(component_id=component_id)

    # Upstream contributors
    upstream_ids = get_upstream_ids(component_id, reverse)
    for uid in upstream_ids:
        uc = comp_map.get(uid)
        if uc:
            contribution = []
            if uc.archetype == ComponentArchetype.FILTER:
                contribution.append("Provides particle filtration")
            if uc.features.creates_particles:
                contribution.append("Potential particle source")
            if uc.archetype == ComponentArchetype.VALVE and uc.config.opening_profile == OpeningProfile.FAST:
                contribution.append("Fast-opening valve — rapid pressurization source")
            result.upstream_contributors.append({
                "component_id": uid,
                "label": uc.label or uc.archetype.value,
                "contributions": "; ".join(contribution) if contribution else "Flow path contributor",
            })

    # Local mechanism triggers
    for mech in comp.mechanism_assessments:
        if mech.credible_status in (CredibleStatus.CREDIBLE, CredibleStatus.INDETERMINATE):
            result.local_mechanism_triggers.append({
                "mechanism": mech.mechanism_name.value,
                "abbreviation": MECHANISM_ABBREV.get(mech.mechanism_name.value, ""),
                "status": mech.credible_status.value,
                "rating": str(mech.rating),
                "observed_elements": ", ".join(mech.observed_elements),
            })

    # Downstream propagation risk
    downstream_ids = get_downstream_ids(component_id, forward)
    for did in downstream_ids:
        dc = comp_map.get(did)
        if dc:
            dc_materials = _get_component_materials(dc)
            flammable = any(
                m.flammability_rating in (FlammabilityRating.C, FlammabilityRating.D,
                                          FlammabilityRating.X, FlammabilityRating.UNKNOWN)
                for m in dc_materials
            )
            if flammable:
                result.downstream_propagation_risk.append(
                    f"{dc.label or dc.archetype.value}: flammable material — propagation possible"
                )
            else:
                result.downstream_propagation_risk.append(
                    f"{dc.label or dc.archetype.value}: nonflammable — chain break"
                )

    # Controls that would change result
    for mech in comp.mechanism_assessments:
        if mech.credible_status == CredibleStatus.CREDIBLE:
            if mech.mechanism_name == IgnitionMechanismName.PARTICLE_IMPACT:
                if not comp.features.filter_integrity_assumed:
                    result.controls_that_would_change.append({
                        "action": "Add upstream filter",
                        "expected_effect": "Removes unfiltered-particle pathway. PI rating would decrease.",
                        "mechanism": "particle_impact",
                    })
                result.controls_that_would_change.append({
                    "action": "Reduce velocity below 30 m/s (increase line diameter)",
                    "expected_effect": "Removes velocity characteristic element for particle impact.",
                    "mechanism": "particle_impact",
                })
            elif mech.mechanism_name == IgnitionMechanismName.RAPID_PRESSURIZATION:
                result.controls_that_would_change.append({
                    "action": "Add slow-opening actuator (>1s)",
                    "expected_effect": "Removes 'rapid' characteristic element. RP credibility drops.",
                    "mechanism": "rapid_pressurization",
                })
                result.controls_that_would_change.append({
                    "action": "Eliminate dead-end configuration",
                    "expected_effect": "Removes trapped volume. RP may become not credible.",
                    "mechanism": "rapid_pressurization",
                })
            elif mech.mechanism_name == IgnitionMechanismName.GALLING_FRICTION:
                result.controls_that_would_change.append({
                    "action": "Use dissimilar metals to resist galling",
                    "expected_effect": "Reduces galling risk at contact surfaces.",
                    "mechanism": "galling_friction",
                })

        # Material change control
        if comp.overall_status == "red":
            result.controls_that_would_change.append({
                "action": "Change body material to nonflammable alloy (e.g., Monel 400)",
                "expected_effect": "Breaks kindling chain if body is propagation path.",
                "mechanism": "kindling_chain",
            })

    return result


# ---------------------------------------------------------------------------
# System Export
# ---------------------------------------------------------------------------

def generate_system_export(system: OCASystemAssembly) -> dict:
    """Generate full system export artifacts."""
    from datetime import datetime

    export: dict = {
        "system_id": system.system_id,
        "system_name": system.name,
        "spec_id": system.spec_id,
        "generated_at": datetime.utcnow().isoformat(),
        "system_disposition": system.system_disposition.value if system.system_disposition else "pending",
        "system_reaction_effect": system.system_reaction_effect.value if system.system_reaction_effect else "A",
        "has_titanium": system.has_titanium,
        "mpr67_active": system.mpr67_active,
    }

    # System OCA Report
    export["system_oca_report"] = {
        "total_components": len(system.components),
        "total_connections": len(system.connections),
        "components_assessed": sum(1 for c in system.components if c.overall_status != "pending"),
        "red_components": sum(1 for c in system.components if c.overall_status == "red"),
        "yellow_components": sum(1 for c in system.components if c.overall_status == "yellow"),
        "green_components": sum(1 for c in system.components if c.overall_status == "green"),
        "system_inputs": system.inputs.model_dump(),
        "triggered_requirements": [r.model_dump() for r in system.system_triggered_requirements],
        "blocked_states": [b.model_dump() for b in system.system_blocked_states],
    }

    # Per-Component OCA Cards
    export["component_cards"] = []
    for comp in system.components:
        card = {
            "component_id": comp.component_id,
            "archetype": comp.archetype.value,
            "label": comp.label,
            "overall_status": comp.overall_status,
            "highest_rating": comp.highest_rating,
            "credible_mechanisms": comp.credible_mechanisms,
            "zones": [z.value for z in comp.zones],
            "materials": [
                {"slot": ms.slot_name, "material": ms.material.material_name,
                 "flammability": ms.material.flammability_rating.value}
                for ms in comp.materials
            ],
            "mechanisms": [
                {
                    "name": m.mechanism_name.value,
                    "abbreviation": MECHANISM_ABBREV.get(m.mechanism_name.value, ""),
                    "status": m.credible_status.value,
                    "rating": m.rating,
                }
                for m in comp.mechanism_assessments
                if m.credible_status != CredibleStatus.NOT_CREDIBLE
            ],
        }
        export["component_cards"].append(card)

    # Kindling chain map
    export["kindling_chain_map"] = [
        {
            "chain_id": chain.chain_id,
            "path": chain.propagation_path,
            "materials": chain.materials_in_path,
            "broken_at": chain.chain_broken_at,
            "break_reason": chain.break_reason,
            "continuous_length": chain.longest_continuous_length,
            "reaction_effect": chain.reaction_effect.value,
        }
        for chain in system.kindling_chains
    ]

    # Hazard control table
    export["hazard_control_table"] = [hc.model_dump() for hc in system.system_hazard_controls]

    # BOM with O2 compatibility
    seen_materials: dict[str, dict] = {}
    for comp in system.components:
        for ms in comp.materials:
            mat = ms.material
            key = mat.material_name.upper()
            if key not in seen_materials:
                seen_materials[key] = {
                    "material_name": mat.material_name,
                    "spec": mat.spec,
                    "flammability_rating": mat.flammability_rating.value,
                    "is_titanium": mat.is_titanium,
                    "is_nonmetal": mat.is_nonmetal,
                    "used_in_components": [],
                }
            seen_materials[key]["used_in_components"].append(
                comp.label or comp.archetype.value
            )
    export["bill_of_materials"] = list(seen_materials.values())

    # MIUL seeds
    export["miul_seeds"] = [seed.model_dump() for seed in system.mua_seeds]

    # Acceptance test schedule
    export["acceptance_test_schedule"] = [
        {
            "component_id": comp.component_id,
            "label": comp.label or comp.archetype.value,
            "reason": "MPR 53 — GOX/enriched-air above 265 psia, non-exempt",
        }
        for comp in system.components
        if SystemZoneType.ACCEPTANCE_TEST in comp.zones
    ]

    # Audit trail
    export["audit_trail"] = system.audit_log

    return export


__safety_critical__ = True
