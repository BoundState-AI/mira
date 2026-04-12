from __future__ import annotations

import pytest

from mira.core.session_store import reset_session_store
from mira.oca.engine import (
    _build_legacy_normalized_input,
    _hazard_control_recommendation,
    _legacy_family,
    _map_test_method,
    _material_instance_to_resolved,
    _worst_reaction_effect,
    adiabatic_compression_temperature,
    assess_ignition_mechanisms,
    create_case,
    determine_disposition,
    evaluate_kindling_chain,
    evaluate_requirement_triggers,
    get_case_mechanisms,
    generate_hazard_controls,
    generate_mua_seed,
    get_oca_engine,
    retrieve_evidence,
)
from mira.oca.models import (
    BlockedState,
    BlockedStateCode,
    ComponentInfo,
    CredibleStatus,
    FinalDisposition,
    FlammabilityRating,
    HazardControlEntry,
    IgnitionMechanismName,
    KindlingChainResult,
    MaterialInstance,
    MechanismAssessment,
    MechanismTrace,
    OcaTier,
    OxygenServiceContext,
    OxidizerType,
    RequirementStatus,
    ServicePhase,
    TriggeredRequirement,
    CreateOcaCaseRequest,
)


@pytest.fixture(autouse=True)
def _reset_session_store_fixture():
    reset_session_store()
    yield
    reset_session_store()


def _context() -> OxygenServiceContext:
    return OxygenServiceContext(
        case_id="shim-case",
        oxidizer_type=OxidizerType.GOX,
        o2_fraction=1.0,
        total_pressure_min_psia=14.7,
        total_pressure_max_psia=350.0,
        phase=ServicePhase.GAS,
        temp_min_c=20.0,
        temp_max_c=25.0,
        velocity_m_s=42.0,
        cleanliness_verified=True,
        mission_phase="ground_test",
    )


def _component() -> ComponentInfo:
    return ComponentInfo(
        component_id="comp-1",
        component_class="valve",
        geometry_class="bulk",
        design_function="pressure control",
        dynamic_contact_flag=True,
    )


def _mechanism(
    name: IgnitionMechanismName,
    status: CredibleStatus,
    rating: int,
) -> MechanismAssessment:
    return MechanismAssessment(
        mechanism_name=name,
        credible_status=status,
        rating=rating,
        source_ref="compat-test",
        required_elements=["element"],
        observed_elements=["element"] if status != CredibleStatus.NOT_CREDIBLE else [],
        missing_elements=[] if status != CredibleStatus.NOT_CREDIBLE else ["element"],
        linked_evidence_ids=[],
        gaps_identified=[],
        reviewer_comments=[],
        mechanism_trace=MechanismTrace(
            mechanism_name=name,
            source_ref="compat-test",
            required_elements=["element"],
            observed_elements=["element"] if status != CredibleStatus.NOT_CREDIBLE else [],
            missing_elements=[] if status != CredibleStatus.NOT_CREDIBLE else ["element"],
            rating_formula_version="test",
            rating_result=rating,
            reviewer_comments=[],
        ),
    )


def test_legacy_helpers_build_normalized_inputs_and_maps() -> None:
    titanium = MaterialInstance(
        material_name="Ti-6Al-4V",
        canonical_name="TI-6AL-4V",
        is_titanium=True,
        flammability_rating=FlammabilityRating.C,
    )
    ptfe = MaterialInstance(
        material_name="PTFE",
        canonical_name="PTFE",
        is_nonmetal=True,
        flammability_rating=FlammabilityRating.D,
    )

    assert get_oca_engine() is get_oca_engine()
    assert adiabatic_compression_temperature(20.0, 10.0) == pytest.approx(292.83, abs=0.01)
    assert adiabatic_compression_temperature(None, 10.0) is None
    assert adiabatic_compression_temperature(20.0, 0.0) is None

    assert _legacy_family(titanium) == "titanium"
    assert _legacy_family(ptfe) == "polymer_organic"
    assert _legacy_family(MaterialInstance(material_name="316L")) == "unknown"

    resolved = _material_instance_to_resolved(titanium)
    assert resolved.family == "titanium"
    assert resolved.rating_flam == "C"

    normalized = _build_legacy_normalized_input(_context(), _component(), [titanium, ptfe])
    assert normalized.service_context.case_id == "shim-case"
    assert len(normalized.materials) == 2
    assert normalized.components[0].component_class == "valve"

    assert _map_test_method("titanium", normalized) == "Test 17"
    assert _map_test_method("stainless", normalized) == "ASTM G74"


def test_legacy_shim_generates_mechanisms_evidence_controls_and_seed() -> None:
    context = _context()
    component = _component()
    materials = [
        MaterialInstance(
            material_name="PTFE",
            canonical_name="PTFE",
            is_nonmetal=True,
            flammability_rating=FlammabilityRating.D,
        ),
        MaterialInstance(
            material_name="316L",
            canonical_name="316L",
            flammability_rating=FlammabilityRating.A,
        ),
    ]

    mechanisms = assess_ignition_mechanisms(context, component, materials)
    requirements = evaluate_requirement_triggers(context, component, materials)
    evidence, gaps = retrieve_evidence(materials, context)
    kindling = evaluate_kindling_chain(materials, component, mechanisms)
    controls = generate_hazard_controls(component, mechanisms, kindling)
    seed = generate_mua_seed(
        context,
        materials,
        mechanisms,
        gaps,
        FinalDisposition.REQUIRES_MUA,
    )

    assert len(mechanisms) == 18
    assert any(item.requirement_id == "MPR_52" for item in requirements)
    assert evidence
    assert kindling.kindling_chain_present is True
    assert any(item.ignition_hazard == "kindling_chain" for item in controls)
    assert seed is not None
    assert seed.recommended_disposition == FinalDisposition.REQUIRES_MUA
    assert "PTFE" in seed.material_names

    assert _worst_reaction_effect(materials) == "D"
    assert _worst_reaction_effect([MaterialInstance(material_name="Unknown", flammability_rating=FlammabilityRating.UNKNOWN)]) == "B"
    assert _hazard_control_recommendation("particle_impact").startswith("Reduce particle source strength")
    assert _hazard_control_recommendation("mystery") == "Apply configuration-specific controls and document closure evidence."


@pytest.mark.anyio
async def test_partial_external_mechanism_signal_mappings_are_applied() -> None:
    created = await create_case(
        CreateOcaCaseRequest(
            service_context={
                "oxidizer_type": "gox",
                "o2_fraction": 1.0,
                "total_pressure_min_psia": 14.7,
                "total_pressure_max_psia": 350.0,
                "phase": "gas",
                "temp_min_c": 20.0,
                "temp_max_c": 25.0,
                "velocity_m_s": 12.0,
                "cleanliness_verified": False,
            },
            materials=[{"material_name": "PTFE", "product_form": "seal"}],
            components=[
                {
                    "component_id": "comp-1",
                    "component_class": "valve",
                    "geometry_class": "bulk",
                    "design_function": "pressure control",
                    "seal_type": "polymer",
                }
            ],
            ignition_context={
                "open_flame_or_hot_work_present": True,
                "mechanical_impact_risk": True,
            },
        )
    )
    mechanisms = {
        item.mechanism_name.value: item
        for item in (await get_case_mechanisms(created.case_id)).mechanisms
    }

    assert mechanisms["welding"].credible_status == CredibleStatus.CREDIBLE
    assert mechanisms["welding"].rating == 4
    assert mechanisms["personnel_smoking_open_flames"].credible_status == CredibleStatus.INDETERMINATE
    assert mechanisms["personnel_smoking_open_flames"].rating == 1
    assert mechanisms["fragments_from_bursting_vessels"].credible_status == CredibleStatus.INDETERMINATE
    assert mechanisms["fragments_from_bursting_vessels"].rating == 1


@pytest.mark.parametrize(
    ("requirements", "mechanisms", "kindling", "hazard_controls", "gaps", "blocked_states", "expected"),
    [
        (
            [
                TriggeredRequirement(
                    requirement_id="MPR_67",
                    title="Titanium prohibited",
                    citation="NASA-STD-6016C",
                    tier=OcaTier.TIER_A,
                    triggered=True,
                    status=RequirementStatus.PROHIBITED,
                    reasoning="Titanium present in GOX.",
                )
            ],
            [],
            KindlingChainResult(),
            [],
            [],
            [],
            FinalDisposition.PROHIBITED,
        ),
        (
            [],
            [],
            KindlingChainResult(),
            [],
            [],
            [
                BlockedState(
                    code=BlockedStateCode.SERVICE_ENVELOPE_INCOMPLETE,
                    detail="Pressure missing.",
                    missing_fields=["total_pressure_max_psia"],
                )
            ],
            FinalDisposition.INSUFFICIENT_EVIDENCE,
        ),
        (
            [
                TriggeredRequirement(
                    requirement_id="MPR_53",
                    title="Acceptance test",
                    citation="NASA-STD-6001B",
                    tier=OcaTier.TIER_A,
                    triggered=True,
                    status=RequirementStatus.ACTION_REQUIRED,
                    reasoning="Non-exempt GOX component above threshold.",
                )
            ],
            [],
            KindlingChainResult(),
            [],
            [],
            [],
            FinalDisposition.REQUIRES_ACCEPTANCE_TEST,
        ),
        (
            [
                TriggeredRequirement(
                    requirement_id="MPR_52",
                    title="MUA",
                    citation="NASA-STD-6016C",
                    tier=OcaTier.TIER_A,
                    triggered=True,
                    status=RequirementStatus.ACTION_REQUIRED,
                    reasoning="Flammable material requires MUA.",
                )
            ],
            [],
            KindlingChainResult(),
            [],
            [],
            [],
            FinalDisposition.REQUIRES_MUA,
        ),
        (
            [],
            [_mechanism(IgnitionMechanismName.PARTICLE_IMPACT, CredibleStatus.INDETERMINATE, 2)],
            KindlingChainResult(),
            [],
            [],
            [],
            FinalDisposition.COMPATIBLE_WITH_CONTROLS,
        ),
        (
            [],
            [],
            KindlingChainResult(kindling_chain_present=True),
            [HazardControlEntry(ignition_hazard="kindling_chain", recommendation="Break chain")],
            [],
            [],
            FinalDisposition.COMPATIBLE_WITH_CONTROLS,
        ),
        (
            [],
            [],
            KindlingChainResult(),
            [],
            [],
            [],
            FinalDisposition.COMPATIBLE_AS_CONFIGURED,
        ),
    ],
)
def test_determine_disposition_precedence(
    requirements: list[TriggeredRequirement],
    mechanisms: list[MechanismAssessment],
    kindling: KindlingChainResult,
    hazard_controls: list[HazardControlEntry],
    gaps: list[str],
    blocked_states: list[BlockedState],
    expected: FinalDisposition,
) -> None:
    assert determine_disposition(requirements, mechanisms, kindling, hazard_controls, gaps, blocked_states) == expected


def test_generate_mua_seed_returns_none_for_non_routed_disposition() -> None:
    seed = generate_mua_seed(
        _context(),
        [MaterialInstance(material_name="316L", canonical_name="316L", flammability_rating=FlammabilityRating.A)],
        [],
        [],
        FinalDisposition.COMPATIBLE_AS_CONFIGURED,
    )
    assert seed is None
