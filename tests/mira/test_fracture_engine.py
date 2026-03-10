from mira.fracture.engine import evaluate_fracture_assessment, get_authority_manifest, search_materials
from mira.fracture.models import FractureAssessmentRequest, FractureMaterialContext


def test_fc_metallic_general_routes_to_expected_fcrs():
    result = evaluate_fracture_assessment(
        FractureAssessmentRequest(
            part_name="Main bracket",
            mission_class="HUMAN_RATED",
            hazard_consequence="CATASTROPHIC",
            load_path_type="SINGLE",
            structural_role="PRIMARY",
            material_system="METALLIC",
            specific_hardware_type="GENERAL",
            material_name="Ti-6Al-4V",
            material_context=FractureMaterialContext(
                approved_source_data_attached=True,
                nasa_std_6016_qualified=True,
            ),
        )
    )

    assert result.classification == "FC"
    assert result.baseline_key == "FC_METALLIC_GENERAL"
    assert result.applicable_fcrs == [10, 12, 15, 16, 21, 22, 23, 24, 25]
    assert any(item.finding_id == "fcr22_scope" for item in result.material_findings)


def test_exempt_non_structural_part_routes_to_fcr6_only():
    result = evaluate_fracture_assessment(
        FractureAssessmentRequest(
            part_name="Access cover",
            structural_role="NON_STRUCTURAL",
            hazard_consequence="NEGLIGIBLE",
            load_path_type="REDUNDANT",
            material_system="METALLIC",
        )
    )

    assert result.classification == "EXEMPT"
    assert result.baseline_key == "EXEMPT"
    assert result.applicable_fcrs == [6]


def test_metallic_low_risk_screen_stays_under_fcr8():
    result = evaluate_fracture_assessment(
        FractureAssessmentRequest(
            part_name="Clip",
            mission_class="HUMAN_RATED",
            hazard_consequence="CRITICAL",
            load_path_type="REDUNDANT",
            structural_role="PRIMARY",
            material_system="METALLIC",
            material_name="Al 6061-T6",
            material_context=FractureMaterialContext(
                low_risk_candidate=True,
                kic_fty_ratio=0.41,
                short_transverse_dimension_in=3.5,
            ),
        )
    )

    assert result.classification == "NFC_METALLIC"
    assert result.applicable_fcrs == [8]
    assert any(item.finding_id == "kic_fty_ratio_check" and item.status == "PASS" for item in result.material_findings)
    assert any(item.finding_id == "short_transverse_dimension_fail" and item.status == "FAIL" for item in result.material_findings)
    assert all(22 not in item.governing_fcrs for item in result.material_findings)


def test_indeterminate_inputs_trigger_conservative_fallback():
    result = evaluate_fracture_assessment(
        FractureAssessmentRequest(
            part_name="Bracket",
            structural_role="PRIMARY",
            hazard_consequence="UNKNOWN",
            load_path_type="UNKNOWN",
            material_system="METALLIC",
        )
    )

    assert result.classification == "INDETERMINATE"
    assert set(result.unresolved_inputs) == {"hazard_consequence", "load_path_type"}
    assert result.conservative_fallback == "Treat as FC pending review"


def test_authority_manifest_and_material_search_are_populated():
    authority = get_authority_manifest()
    materials = search_materials("6061")

    assert authority.total_fcrs == 26
    assert authority.baseline_count >= 10
    assert materials
    assert materials[0].canonical_name == "Aluminum 6061-T6"
