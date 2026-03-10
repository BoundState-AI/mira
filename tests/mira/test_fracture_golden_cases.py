from mira.fracture.engine import evaluate_fracture_assessment
from mira.fracture.models import FractureAssessmentRequest, FractureMaterialContext


def _evaluate(**overrides):
    payload = {
        "part_name": "Golden Case",
        "mission_class": "HUMAN_RATED",
        "hazard_consequence": "CRITICAL",
        "load_path_type": "REDUNDANT",
        "structural_role": "PRIMARY",
        "material_system": "METALLIC",
        "specific_hardware_type": "GENERAL",
        "material_name": "Al 6061-T6",
        "material_context": FractureMaterialContext(),
    }
    payload.update(overrides)
    return evaluate_fracture_assessment(FractureAssessmentRequest(**payload))


def test_golden_nfc_metallic_general():
    result = _evaluate()
    assert result.classification == "NFC_METALLIC"
    assert result.baseline_key == "NFC_METALLIC_GENERAL"
    assert result.applicable_fcrs == [8]


def test_golden_nfc_composite_general_adds_traceability_and_materials():
    result = _evaluate(
        material_system="COMPOSITE",
        material_name="CFRP",
    )
    assert result.classification == "NFC_COMPOSITE_BONDED"
    assert result.baseline_key == "NFC_COMPOSITE_BONDED_GENERAL"
    assert result.applicable_fcrs == [8, 9, 17, 21, 22]


def test_golden_nfc_specific_fastener_path():
    result = _evaluate(specific_hardware_type="FASTENER")
    assert result.classification == "NFC_METALLIC"
    assert result.baseline_key == "NFC_METALLIC_SPECIFIC"
    assert result.applicable_fcrs == [7]


def test_golden_fc_specific_pressure_hardware_path():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        specific_hardware_type="PRESSURE_VESSEL",
        material_name="Ti-6Al-4V",
    )
    assert result.classification == "FC"
    assert result.baseline_key == "FC_SPECIFIC_HARDWARE"
    assert result.applicable_fcrs == [10, 11, 15, 16, 21, 22, 23, 24, 25]


def test_golden_fc_composite_general_path():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_system="COMPOSITE",
        material_name="CFRP",
    )
    assert result.classification == "FC"
    assert result.baseline_key == "FC_COMPOSITE_BONDED_GENERAL"
    assert result.applicable_fcrs == [10, 13, 15, 17, 21, 22, 23, 24, 25]


def test_golden_fc_optional_approach_path():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_system="CERAMIC",
        optional_approach_requested=True,
        material_name="Al 6061-T6",
    )
    assert result.classification == "FC"
    assert result.baseline_key == "FC_OPTIONAL_APPROACH"
    assert result.applicable_fcrs == [10, 14, 15, 21, 22, 23, 24, 25]


def test_golden_proof_test_process_control_and_detected_flaw_conditionals():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        proof_test_used=True,
        process_controls_used=True,
        detected_flaw_accepted_for_flight=True,
        material_name="Ti-6Al-4V",
    )
    assert result.classification == "FC"
    assert 18 in result.applicable_fcrs
    assert 19 in result.applicable_fcrs
    assert 20 in result.applicable_fcrs


def test_golden_mua_required_when_not_qualified_to_6016():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
        material_context=FractureMaterialContext(
            nasa_std_6016_qualified=False,
            mua_present=False,
        ),
    )
    finding_ids = {item.finding_id: item for item in result.material_findings}
    assert finding_ids["mua_required"].status == "FAIL"


def test_golden_mua_passes_when_present():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
        material_context=FractureMaterialContext(
            nasa_std_6016_qualified=False,
            mua_present=True,
        ),
    )
    finding_ids = {item.finding_id: item for item in result.material_findings}
    assert finding_ids["mua_required"].status == "PASS"


def test_golden_cross_module_alert_is_product_warning_not_fcr():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
        corrosion_iccp_recommended=True,
    )
    assert any("CrossModuleAlert" in warning for warning in result.warnings)


def test_golden_titanium_sustained_load_watch():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
        material_context=FractureMaterialContext(
            sustained_load_expected=True,
            nasa_std_6016_qualified=True,
        ),
    )
    assert any(item.finding_id == "titanium_slc_watch" for item in result.material_findings)


def test_golden_high_strength_steel_fastener_watch():
    result = _evaluate(
        specific_hardware_type="FASTENER",
        material_name="300M",
        material_context=FractureMaterialContext(ftu_ksi=190),
    )
    assert any(item.finding_id == "steel_fastener_low_toughness_watch" for item in result.material_findings)
