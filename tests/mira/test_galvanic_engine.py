from mira.galvanic.engine import evaluate_galvanic_assessment
from mira.galvanic.models import CoupleContext, GalvanicAssessmentRequest


def test_aluminum_316_seawater_is_incompatible():
    result = evaluate_galvanic_assessment(
        GalvanicAssessmentRequest(
            material_a="Al 6061-T6",
            material_b="316SS",
            environment="seawater_proxy",
        )
    )
    assert result.severity == "INCOMPATIBLE"
    assert result.raw_delta_mv > 700
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
    result = evaluate_galvanic_assessment(
        GalvanicAssessmentRequest(
            material_a="Mg AZ31B",
            material_b="316SS",
            environment="seawater_proxy",
            application_type="LAUNCH_STRUCTURE",
        )
    )
    assert any(item.mitigation_id == "iccp_structures_only" for item in result.mitigations)
