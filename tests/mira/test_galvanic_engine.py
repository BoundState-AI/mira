from mira.galvanic.engine import _classify, evaluate_galvanic_assessment
from mira.galvanic.models import CoupleContext, GalvanicAssessmentRequest


def _evaluate(**overrides):
    payload = {
        "material_a": "Al 6061-T6",
        "material_b": "316SS",
        "environment": "seawater_proxy",
    }
    payload.update(overrides)
    return evaluate_galvanic_assessment(GalvanicAssessmentRequest(**payload))


def test_aluminum_316_seawater_is_incompatible():
    result = _evaluate()
    assert result.severity == "INCOMPATIBLE"
    assert result.raw_delta_mv == 675
    assert result.anode.startswith("Aluminum 6061")


def test_no_electrical_contact_short_circuits_risk():
    result = evaluate_galvanic_assessment(
        GalvanicAssessmentRequest(
            material_a="316SS",
            material_b="Al 6061-T6",
            couple_context=CoupleContext(electrical_contact="NO"),
        )
    )
    assert result.severity == "COMPATIBLE"
    assert result.decision_basis == "NO_ELECTRICAL_CONTACT"
    assert result.effective_delta_mv == 0


def test_cfrp_triggers_special_warnings():
    result = evaluate_galvanic_assessment(
        GalvanicAssessmentRequest(
            material_a="CFRP",
            material_b="Al 6061-T6",
            environment="seawater_proxy",
            couple_context=CoupleContext(joint_type="FASTENER"),
        )
    )
    warning_text = " ".join(result.warnings)
    assert "CPR 40" in warning_text
    assert any(item.mitigation_id == "titanium_fasteners_for_cfrp" for item in result.mitigations)


def test_launch_structure_can_recommend_iccp():
    result = _evaluate(
        material_a="Mg AZ31B",
        application_type="LAUNCH_STRUCTURE",
    )
    assert any(item.mitigation_id == "iccp_structures_only" for item in result.mitigations)


def test_flight_hardware_does_not_recommend_iccp():
    result = _evaluate(
        material_a="Mg AZ31B",
        application_type="FLIGHT_HARDWARE",
    )
    assert not any(item.mitigation_id == "iccp_structures_only" for item in result.mitigations)


def test_cathodic_barrier_coating_marks_coat_cathode_warning():
    result = _evaluate()
    coating = next(item for item in result.mitigations if item.mitigation_id == "cathodic_barrier_coating")
    assert coating.coat_cathode_warning is True


def test_caution_and_incompatible_bands_use_boundstate_synthesized_basis():
    caution = _evaluate(material_b="430SS")
    incompatible = _evaluate()
    assert caution.severity == "CAUTION"
    assert caution.decision_basis == "BOUNDSTATE_SYNTHESIZED"
    assert incompatible.severity == "INCOMPATIBLE"
    assert incompatible.decision_basis == "BOUNDSTATE_SYNTHESIZED"


def test_space_vacuum_short_circuits_to_no_electrolyte():
    result = _evaluate(environment="space_vacuum")
    assert result.severity == "COMPATIBLE"
    assert result.decision_basis == "NO_ELECTROLYTE"
    assert result.effective_delta_mv == 0
    assert any("hard vacuum" in warning for warning in result.warnings)


def test_full_circuit_break_short_circuits_to_no_electrolyte():
    result = _evaluate(surface_condition_a="fully_coated")
    assert result.severity == "COMPATIBLE"
    assert result.decision_basis == "NO_ELECTROLYTE"
    assert result.effective_delta_mv == 0
    assert any("opens the galvanic circuit" in warning for warning in result.warnings)


def test_dual_state_material_uses_worst_case_variant_pair():
    result = _evaluate(material_a="316SS", material_b="Graphite")
    assert result.material_a.chosen_state == "active"
    assert result.raw_delta_mv == 775
    assert result.severity == "INCOMPATIBLE"


def test_electrolyte_pooling_increases_effective_delta():
    baseline = _evaluate(material_b="Copper")
    pooled = _evaluate(
        material_b="Copper",
        couple_context=CoupleContext(electrolyte_pooling=True),
    )
    assert pooled.effective_delta_mv > baseline.effective_delta_mv
    assert any("Electrolyte pooling" in warning for warning in pooled.warnings)


def test_large_cathode_to_anode_area_ratio_increases_effective_delta():
    baseline = _evaluate(
        material_b="Copper",
        couple_context=CoupleContext(cathode_to_anode_area_ratio=1),
    )
    severe = _evaluate(
        material_b="Copper",
        couple_context=CoupleContext(cathode_to_anode_area_ratio=100),
    )
    assert severe.effective_delta_mv > baseline.effective_delta_mv
    assert any("Large cathode-to-anode area ratio" in warning for warning in severe.warnings)


def test_real_250_mv_boundary_is_caution():
    result = _evaluate(material_a="316SS", material_b="430SS")
    assert result.effective_delta_mv == 250
    assert result.severity == "CAUTION"
    assert result.decision_basis == "BOUNDSTATE_SYNTHESIZED"


def test_real_500_mv_boundary_is_caution():
    result = _evaluate(material_a="Graphite", material_b="PH 13-8")
    assert result.effective_delta_mv == 500
    assert result.severity == "CAUTION"
    assert result.decision_basis == "BOUNDSTATE_SYNTHESIZED"


def test_classification_threshold_edges_are_stable():
    assert _classify(249) == ("COMPATIBLE", "NASA_STD_6012A_CPR39")
    assert _classify(250) == ("CAUTION", "BOUNDSTATE_SYNTHESIZED")
    assert _classify(500) == ("CAUTION", "BOUNDSTATE_SYNTHESIZED")
    assert _classify(501) == ("INCOMPATIBLE", "BOUNDSTATE_SYNTHESIZED")


def test_fastener_warning_appears_for_plain_metallic_couple():
    result = _evaluate(
        material_b="Copper",
        couple_context=CoupleContext(joint_type="FASTENER"),
    )
    assert any("fastener should be the cathodic member" in warning for warning in result.warnings)


def test_magnesium_warning_is_explicit():
    result = _evaluate(material_a="Mg AZ31B")
    assert any("Magnesium in any couple requires the maximum feasible protective system" in warning for warning in result.warnings)


def test_environment_modifier_reduces_effective_delta_in_dry_service():
    wet = _evaluate(material_b="Copper", environment="seawater_proxy")
    dry = _evaluate(material_b="Copper", environment="dry_indoor")
    assert dry.effective_delta_mv < wet.effective_delta_mv
    assert dry.decision_basis == "NASA_STD_6012A_CPR39"
