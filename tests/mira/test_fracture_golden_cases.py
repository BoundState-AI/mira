from mira.fracture.engine import evaluate_fracture_assessment, search_materials
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
    assert 21 not in result.applicable_fcrs
    assert 22 not in result.applicable_fcrs


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


def test_golden_pressure_vessel_escalates_to_fc_even_with_redundant_path():
    result = _evaluate(
        specific_hardware_type="PRESSURE_VESSEL",
        material_name="Ti-6Al-4V",
    )
    assert result.classification == "FC"
    assert result.baseline_key == "FC_SPECIFIC_HARDWARE"
    assert 11 in result.applicable_fcrs
    assert 12 not in result.applicable_fcrs


def test_golden_copv_escalates_to_fc_specific_hardware():
    result = _evaluate(
        specific_hardware_type="COPV",
        material_name="Ti-6Al-4V",
    )
    assert result.classification == "FC"
    assert result.baseline_key == "FC_SPECIFIC_HARDWARE"
    assert 11 in result.applicable_fcrs


def test_golden_rotating_hardware_nfc_vs_fc_disambiguation():
    nfc_result = _evaluate(
        specific_hardware_type="ROTATING_HARDWARE",
        hazard_consequence="CRITICAL",
        load_path_type="REDUNDANT",
    )
    fc_result = _evaluate(
        specific_hardware_type="ROTATING_HARDWARE",
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
    )

    assert nfc_result.classification == "NFC_METALLIC"
    assert nfc_result.baseline_key == "NFC_METALLIC_SPECIFIC"
    assert fc_result.classification == "FC"
    assert fc_result.baseline_key == "FC_SPECIFIC_HARDWARE"


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
    matches = [warning for warning in result.warnings if "CrossModuleAlert" in warning]
    assert matches == [
        "CrossModuleAlert: corrosion indicates ICCP consideration while this part is fracture-critical. This is a BoundState product alert, not an FCR."
    ]


def test_golden_cross_module_alert_does_not_fire_for_nfc():
    result = _evaluate(
        corrosion_iccp_recommended=True,
    )
    assert not any("CrossModuleAlert" in warning for warning in result.warnings)


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


def test_golden_non_structural_catastrophic_does_not_fall_to_exempt():
    result = _evaluate(
        structural_role="NON_STRUCTURAL",
        hazard_consequence="CATASTROPHIC",
        material_name="Ti-6Al-4V",
    )
    assert result.classification == "FC"
    assert result.baseline_key == "FC_METALLIC_GENERAL"


def test_golden_non_human_rated_mission_warns_but_still_classifies():
    result = _evaluate(
        mission_class="GSE",
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
    )
    assert result.classification == "FC"
    assert any("best-practice fracture guidance" in warning for warning in result.warnings)


def test_golden_single_unknown_field_is_indeterminate():
    hazard_unknown = _evaluate(hazard_consequence="UNKNOWN")
    load_unknown = _evaluate(load_path_type="UNKNOWN")

    assert hazard_unknown.classification == "INDETERMINATE"
    assert load_unknown.classification == "INDETERMINATE"
    assert hazard_unknown.applicable_fcrs == [10, 12, 15, 16, 21, 22, 23, 24, 25]
    assert load_unknown.applicable_fcrs == [10, 12, 15, 16, 21, 22, 23, 24, 25]


def test_golden_unknown_and_empty_material_names_do_not_fake_resolution():
    unknown = _evaluate(material_name="mystery alloy")
    empty = _evaluate(material_name=None)

    assert unknown.resolved_material is None
    assert empty.resolved_material is None


def test_golden_every_returned_citation_has_section_and_pages():
    result = _evaluate(
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
    )

    assert result.citations
    for citation in result.citations:
        assert citation.section
        assert citation.source_pages


def test_golden_priority_materials_exist_in_reference_search():
    expected_queries = [
        "2024",
        "2219",
        "6061",
        "7050",
        "7075",
        "Ti-6Al-4V",
        "6Al-4V",
        "Ti64",
        "titanium 64",
        "300M",
        "4340",
        "Inconel 718",
        "IN718",
        "316L",
        "304",
    ]

    for query in expected_queries:
        matches = search_materials(query)
        assert matches, f"Expected material reference match for {query}"


def test_golden_am_part_fails_low_risk_path():
    result = _evaluate(
        material_name="Ti64",
        material_context=FractureMaterialContext(
            low_risk_candidate=True,
            additive_manufactured=True,
            kic_fty_ratio=0.5,
        ),
    )
    finding_ids = {item.finding_id: item for item in result.material_findings}
    assert finding_ids["am_low_risk_disallowed"].status == "FAIL"


def test_golden_reflight_hardware_surfaces_warning():
    result = _evaluate(
        lifecycle_phase="REFLIGHT",
        hazard_consequence="CATASTROPHIC",
        load_path_type="SINGLE",
        material_name="Ti-6Al-4V",
    )
    assert any("Reflight hardware selected" in warning for warning in result.warnings)
