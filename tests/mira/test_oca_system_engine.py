from __future__ import annotations

from types import SimpleNamespace

import pytest

import mira.oca.system_engine as system_engine
from mira.oca.models import (
    CredibleStatus,
    FlammabilityRating,
    HazardControlEntry,
    IgnitionMechanismName,
    KindlingChainResult,
    MaterialInstance,
    MechanismAssessment,
    MechanismTrace,
    OcaTier,
    OCADisposition,
    ReactionEffect,
    RequirementStatus,
    TriggeredRequirement,
)
from mira.oca.system_models import (
    ActuationType,
    ComponentArchetype,
    ComponentConfig,
    ComponentFeatureFlags,
    InferenceConfidence,
    InferenceSource,
    InferredFact,
    MaterialSlotValue,
    OCASystemAssembly,
    OpeningProfile,
    SAVolumeRatio,
    SeatContactMode,
    SonicFlowPoint,
    SystemComponent,
    SystemConnection,
    SystemInputs,
    SystemKindlingChain,
    SystemZoneType,
    TopologyInferenceResult,
)


def _material(
    name: str,
    *,
    flammability: FlammabilityRating = FlammabilityRating.A,
    is_nonmetal: bool = False,
    is_titanium: bool = False,
) -> MaterialInstance:
    return MaterialInstance(
        material_name=name,
        canonical_name=name.upper(),
        flammability_rating=flammability,
        is_nonmetal=is_nonmetal,
        is_titanium=is_titanium,
    )


def _slot(name: str, material: MaterialInstance) -> MaterialSlotValue:
    return MaterialSlotValue(slot_name=name, material=material)


def _mechanism(
    name: IgnitionMechanismName,
    status: CredibleStatus,
    rating: int,
) -> MechanismAssessment:
    return MechanismAssessment(
        mechanism_name=name,
        credible_status=status,
        rating=rating,
        source_ref="system-test",
        required_elements=["element"],
        observed_elements=["element"] if status != CredibleStatus.NOT_CREDIBLE else [],
        missing_elements=[] if status != CredibleStatus.NOT_CREDIBLE else ["element"],
        linked_evidence_ids=[],
        gaps_identified=[],
        reviewer_comments=[],
        mechanism_trace=MechanismTrace(
            mechanism_name=name,
            source_ref="system-test",
            required_elements=["element"],
            observed_elements=["element"] if status != CredibleStatus.NOT_CREDIBLE else [],
            missing_elements=[] if status != CredibleStatus.NOT_CREDIBLE else ["element"],
            rating_formula_version="test",
            rating_result=rating,
            reviewer_comments=[],
        ),
    )


def test_derive_features_combines_library_materials_and_config() -> None:
    features = system_engine.derive_features(
        ComponentArchetype.VALVE,
        ComponentConfig(
            actuation_type=ActuationType.SOLENOID,
            bypass_path_exists=True,
            exposed_to_flow=True,
            is_flex=True,
        ),
        [
            _slot("body", _material("Aluminum 6061")),
            _slot("seat", _material("PTFE", flammability=FlammabilityRating.D, is_nonmetal=True)),
        ],
    )

    assert features.has_polymer_seal is True
    assert features.reactive_metal_present is True
    assert features.electrical_energy_present is True
    assert features.filter_integrity_assumed is False
    assert features.wetted_surface_flag is True
    assert features.has_moving_contact is True
    assert features.dynamic_contact_flag is True
    assert features.creates_particles is True
    assert features.seat_contact_mode == SeatContactMode.METAL_TO_POLYMER

    assert system_engine.derive_features(ComponentArchetype.FILTER, ComponentConfig(), []).sa_to_volume_ratio == SAVolumeRatio.HIGH
    assert system_engine.derive_features(ComponentArchetype.GASKET, ComponentConfig(), []).sa_to_volume_ratio == SAVolumeRatio.LOW


def test_topology_inference_populates_velocity_sonic_filter_volume_and_zones() -> None:
    vessel = SystemComponent(
        component_id="vessel",
        archetype=ComponentArchetype.PRESSURE_VESSEL,
        label="Tank",
        config=ComponentConfig(volume_liters=4.0),
        materials=[_slot("body", _material("316L"))],
    )
    line = SystemComponent(
        component_id="line",
        archetype=ComponentArchetype.LINE,
        label="Feed Line",
        config=ComponentConfig(inner_diameter_mm=10.0, length_m=2.0),
        materials=[_slot("body", _material("316L"))],
    )
    filter_component = SystemComponent(
        component_id="filter",
        archetype=ComponentArchetype.FILTER,
        label="Main Filter",
        config=ComponentConfig(bypass_path_exists=False),
        materials=[_slot("body", _material("316L"))],
    )
    valve = SystemComponent(
        component_id="valve",
        archetype=ComponentArchetype.VALVE,
        label="MOV",
        config=ComponentConfig(opening_profile=OpeningProfile.FAST),
        materials=[_slot("body", _material("316L"))],
    )
    orifice = SystemComponent(
        component_id="orifice",
        archetype=ComponentArchetype.ORIFICE,
        label="Trim Orifice",
        config=ComponentConfig(bore_diameter_mm=1.5),
        materials=[_slot("body", _material("316L"))],
    )
    regulator = SystemComponent(
        component_id="regulator",
        archetype=ComponentArchetype.REGULATOR,
        label="Downstream Regulator",
        config=ComponentConfig(set_pressure_psia=1000.0),
        materials=[_slot("body", _material("316L"))],
    )

    system = OCASystemAssembly(
        inputs=SystemInputs(
            system_pressure_min_psia=100.0,
            system_pressure_max_psia=3000.0,
            design_flow_rate_m3_s=0.02,
            phase="gox",
            oxygen_phase="gas",
        ),
        components=[vessel, line, filter_component, valve, orifice, regulator],
        connections=[
            SystemConnection(source_component_id="vessel", target_component_id="line"),
            SystemConnection(source_component_id="line", target_component_id="filter"),
            SystemConnection(source_component_id="filter", target_component_id="valve"),
            SystemConnection(source_component_id="valve", target_component_id="orifice"),
            SystemConnection(source_component_id="orifice", target_component_id="regulator"),
        ],
    )

    topology = system_engine.run_topology_inference(system)

    assert ("vessel", "line") in topology.flow_direction
    assert "vessel" in topology.dead_end_component_ids
    assert "regulator" in topology.dead_end_component_ids
    assert topology.velocity_estimates[0].component_id == "line"
    assert topology.velocity_estimates[0].velocity_m_s == pytest.approx(254.65, abs=0.05)
    assert topology.sonic_flow_points[0].component_id == "orifice"
    assert set(topology.filter_protected_ids) == {"valve", "orifice", "regulator"}
    assert "regulator" in topology.chatter_candidate_ids
    assert topology.upstream_volumes["valve"] > 4.1
    assert SystemZoneType.FILTERED in topology.zone_assignments["valve"]
    assert SystemZoneType.ACCEPTANCE_TEST in topology.zone_assignments["valve"]
    assert SystemZoneType.CAVITY_RESONANCE in topology.zone_assignments["regulator"]
    assert all(component.connected for component in system.components)
    assert any(fact.rule_id == "TOPO-003" for fact in topology.inferred_facts)
    assert any(fact.rule_id == "TOPO-004" for fact in topology.inferred_facts)
    assert any(fact.rule_id == "TOPO-005" for fact in topology.inferred_facts)


def test_topology_inference_honors_bidirectional_flow_risk() -> None:
    filter_component = SystemComponent(
        component_id="filter",
        archetype=ComponentArchetype.FILTER,
        label="Filter",
        materials=[_slot("body", _material("316L"))],
    )
    valve = SystemComponent(
        component_id="valve",
        archetype=ComponentArchetype.VALVE,
        label="Valve",
        materials=[_slot("body", _material("316L"))],
    )
    system = OCASystemAssembly(
        inputs=SystemInputs(
            system_pressure_min_psia=14.7,
            system_pressure_max_psia=500.0,
            bi_directional_flow_risk=True,
            phase="gox",
            oxygen_phase="gas",
        ),
        components=[filter_component, valve],
        connections=[SystemConnection(source_component_id="filter", target_component_id="valve")],
    )

    topology = system_engine.run_topology_inference(system)

    assert any(fact.rule_id == "TOPO-008" for fact in topology.inferred_facts)
    assert topology.zone_assignments["valve"] == [SystemZoneType.UNFILTERED, SystemZoneType.DEAD_LEG, SystemZoneType.ACCEPTANCE_TEST]


def test_assess_component_applies_topology_adjustments(monkeypatch: pytest.MonkeyPatch) -> None:
    component = SystemComponent(
        component_id="component-1",
        archetype=ComponentArchetype.VALVE,
        label="Dynamic Valve",
        materials=[
            _slot("body", _material("316L")),
            _slot("seat", _material("PTFE", flammability=FlammabilityRating.D, is_nonmetal=True)),
        ],
        features=ComponentFeatureFlags(filter_integrity_assumed=True),
    )
    topology = TopologyInferenceResult(
        dead_end_component_ids=["component-1"],
        filter_protected_ids=["component-1"],
        chatter_candidate_ids=["component-1"],
        sonic_flow_points=[
            SonicFlowPoint(
                component_id="orifice-1",
                pressure_ratio=3.0,
                bore_diameter_mm=1.5,
                downstream_component_ids=["component-1"],
            )
        ],
    )

    monkeypatch.setattr(
        system_engine,
        "assess_ignition_mechanisms",
        lambda *_args, **_kwargs: [
            _mechanism(IgnitionMechanismName.PARTICLE_IMPACT, CredibleStatus.CREDIBLE, 3),
            _mechanism(IgnitionMechanismName.RAPID_PRESSURIZATION, CredibleStatus.NOT_CREDIBLE, 1),
            _mechanism(IgnitionMechanismName.GALLING_FRICTION, CredibleStatus.INDETERMINATE, 1),
            _mechanism(IgnitionMechanismName.MECHANICAL_IMPACT, CredibleStatus.INDETERMINATE, 1),
            _mechanism(IgnitionMechanismName.RESONANCE, CredibleStatus.NOT_CREDIBLE, 1),
        ],
    )

    system_engine.assess_component(
        component,
        SystemInputs(system_pressure_min_psia=14.7, system_pressure_max_psia=500.0, phase="gox", oxygen_phase="gas"),
        {},
        topology,
    )

    by_name = {item.mechanism_name: item for item in component.mechanism_assessments}
    assert by_name[IgnitionMechanismName.PARTICLE_IMPACT].credible_status == CredibleStatus.INDETERMINATE
    assert by_name[IgnitionMechanismName.RAPID_PRESSURIZATION].credible_status == CredibleStatus.INDETERMINATE
    assert by_name[IgnitionMechanismName.GALLING_FRICTION].rating == 2
    assert by_name[IgnitionMechanismName.MECHANICAL_IMPACT].rating == 2
    assert by_name[IgnitionMechanismName.RESONANCE].credible_status == CredibleStatus.INDETERMINATE
    assert component.overall_status == "yellow"
    assert set(component.credible_mechanisms) >= {"PI", "RP", "GF", "MI", "RS"}


def test_run_system_assessment_aggregates_flags_and_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    titanium_valve = SystemComponent(
        component_id="valve-1",
        archetype=ComponentArchetype.VALVE,
        label="Titanium Valve",
        materials=[_slot("body", _material("Ti-6Al-4V", flammability=FlammabilityRating.C, is_titanium=True))],
    )
    unresolved_line = SystemComponent(
        component_id="line-1",
        archetype=ComponentArchetype.LINE,
        label="Open Line",
        config=ComponentConfig(inner_diameter_mm=12.0, length_m=1.0),
        materials=[],
    )
    system = OCASystemAssembly(
        inputs=SystemInputs(
            o2_fraction=1.0,
            system_pressure_min_psia=14.7,
            system_pressure_max_psia=800.0,
            phase="gox",
            oxygen_phase="gas",
        ),
        components=[titanium_valve, unresolved_line],
        connections=[SystemConnection(source_component_id="valve-1", target_component_id="line-1")],
    )

    monkeypatch.setattr(
        system_engine,
        "run_topology_inference",
        lambda _system: TopologyInferenceResult(
            zone_assignments={"valve-1": [SystemZoneType.UNFILTERED], "line-1": [SystemZoneType.UNFILTERED]},
        ),
    )

    def fake_assess_component(comp: SystemComponent, *_args) -> None:
        if comp.materials:
            comp.mechanism_assessments = [_mechanism(IgnitionMechanismName.PARTICLE_IMPACT, CredibleStatus.CREDIBLE, 3)]
            comp.overall_status = "red"
            comp.highest_rating = 3
            comp.credible_mechanisms = ["PI"]
        else:
            comp.mechanism_assessments = []
            comp.overall_status = "pending"

    monkeypatch.setattr(system_engine, "assess_component", fake_assess_component)
    monkeypatch.setattr(
        system_engine,
        "evaluate_requirement_triggers",
        lambda *_args, **_kwargs: [
            TriggeredRequirement(
                requirement_id="MPR_52",
                title="MUA Required",
                citation="NASA-STD-6016C",
                tier=OcaTier.TIER_A,
                triggered=True,
                status=RequirementStatus.ACTION_REQUIRED,
                reasoning="Flammable material present in oxygen system.",
            )
        ],
    )
    monkeypatch.setattr(
        system_engine,
        "assess_system_kindling_chains",
        lambda _system: [
            SystemKindlingChain(
                propagation_path=["valve-1", "line-1"],
                materials_in_path=["Ti-6Al-4V (C)"],
                longest_continuous_length=2,
                reaction_effect=ReactionEffect.D,
            )
        ],
    )
    monkeypatch.setattr(
        system_engine,
        "evaluate_kindling_chain",
        lambda *_args, **_kwargs: KindlingChainResult(kindling_chain_present=True, reaction_effect=ReactionEffect.C),
    )
    monkeypatch.setattr(
        system_engine,
        "generate_hazard_controls",
        lambda *_args, **_kwargs: [HazardControlEntry(component_ref="valve-1", ignition_hazard="particle_impact", recommendation="Filter flow path")],
    )
    monkeypatch.setattr(system_engine, "retrieve_evidence", lambda *_args, **_kwargs: ([], ["Need direct evidence"]))
    monkeypatch.setattr(system_engine, "determine_disposition", lambda *_args, **_kwargs: OCADisposition.REQUIRES_MUA)
    monkeypatch.setattr(
        system_engine,
        "generate_mua_seed",
        lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda: {"seed": "mua"}) or None,
    )

    system_engine.run_system_assessment(system)

    blocked_types = {item.state_type for item in system.system_blocked_states}
    assert "materials" in system.system_blocked_states[-1].missing_fields
    assert blocked_types == {"MATERIAL_IDENTITY_UNRESOLVED"}
    assert system.has_titanium is True
    assert system.mpr67_active is True
    assert system.system_disposition == OCADisposition.REQUIRES_MUA
    assert system.system_reaction_effect == ReactionEffect.D
    assert len(system.system_hazard_controls) == 1
    assert len(system.mua_seeds) == 1
    assert system.kindling_chains[0].reaction_effect == ReactionEffect.D


def test_kindling_chains_path_inspector_and_export_capture_system_outputs() -> None:
    filter_component = SystemComponent(
        component_id="filter-1",
        archetype=ComponentArchetype.FILTER,
        label="Primary Filter",
        materials=[_slot("body", _material("316L"))],
    )
    valve = SystemComponent(
        component_id="valve-1",
        archetype=ComponentArchetype.VALVE,
        label="Valve",
        materials=[_slot("body", _material("PTFE", flammability=FlammabilityRating.D, is_nonmetal=True))],
        mechanism_assessments=[
            _mechanism(IgnitionMechanismName.PARTICLE_IMPACT, CredibleStatus.CREDIBLE, 3),
            _mechanism(IgnitionMechanismName.RAPID_PRESSURIZATION, CredibleStatus.CREDIBLE, 2),
            _mechanism(IgnitionMechanismName.GALLING_FRICTION, CredibleStatus.CREDIBLE, 2),
        ],
        overall_status="red",
        highest_rating=3,
        credible_mechanisms=["PI", "RP", "GF"],
        connected=True,
        config=ComponentConfig(opening_profile=OpeningProfile.FAST),
        features=ComponentFeatureFlags(filter_integrity_assumed=False),
        zones=[SystemZoneType.UNFILTERED, SystemZoneType.ACCEPTANCE_TEST],
    )
    line = SystemComponent(
        component_id="line-1",
        archetype=ComponentArchetype.LINE,
        label="Line",
        materials=[_slot("body", _material("PTFE", flammability=FlammabilityRating.D, is_nonmetal=True))],
        overall_status="yellow",
        connected=True,
    )
    vessel = SystemComponent(
        component_id="vessel-1",
        archetype=ComponentArchetype.PRESSURE_VESSEL,
        label="Buffer Vessel",
        materials=[_slot("body", _material("316L", flammability=FlammabilityRating.A))],
        overall_status="green",
        connected=True,
    )

    system = OCASystemAssembly(
        name="Exportable System",
        inputs=SystemInputs(
            system_pressure_min_psia=14.7,
            system_pressure_max_psia=500.0,
            phase="gox",
            oxygen_phase="gas",
        ),
        components=[filter_component, valve, line, vessel],
        connections=[
            SystemConnection(source_component_id="filter-1", target_component_id="valve-1"),
            SystemConnection(source_component_id="valve-1", target_component_id="line-1"),
            SystemConnection(source_component_id="line-1", target_component_id="vessel-1"),
        ],
        system_disposition=OCADisposition.COMPATIBLE_WITH_CONTROLS,
        system_reaction_effect=ReactionEffect.C,
        system_hazard_controls=[
            HazardControlEntry(component_ref="valve-1", ignition_hazard="particle_impact", recommendation="Install filter")
        ],
        audit_log=[{"action": "assess", "timestamp": "2026-03-10T12:00:00Z"}],
    )

    system.kindling_chains = system_engine.assess_system_kindling_chains(system)
    inspector = system_engine.inspect_component_path(system, "valve-1")
    export = system_engine.generate_system_export(system)

    assert len(system.kindling_chains) == 1
    assert system.kindling_chains[0].chain_broken_at == "vessel-1"
    assert inspector.upstream_contributors[0]["label"] == "Primary Filter"
    assert any("particle impact" in item["mechanism"] or item["mechanism"] == "particle_impact" for item in inspector.controls_that_would_change)
    assert any("Line: flammable material" in item for item in inspector.downstream_propagation_risk)
    assert export["system_name"] == "Exportable System"
    assert export["system_oca_report"]["red_components"] == 1
    assert export["component_cards"][1]["credible_mechanisms"] == ["PI", "RP", "GF"]
    assert export["acceptance_test_schedule"][0]["component_id"] == "valve-1"
    assert export["audit_trail"][0]["action"] == "assess"
