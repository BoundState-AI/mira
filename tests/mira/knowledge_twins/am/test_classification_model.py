"""
Tests: NASA-STD-6030 classification decision model (PR-0).

Numeric assertions are pinned to the approved 2021-04-21 source text:
[AMR-6] p.35, [AMR-7] p.35, [AMR-8] p.36, [AMR-10] p.37, [AMR-12] p.40,
Table 2 p.41, Table 3 p.43, Table 4 p.44, risk threshold §4.3.2.2 p.43.

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

from mira.knowledge_twins.am.am_models import (
    AMPartClass,
    AMProcess,
    ConsequenceTier,
    HazardFlag,
    MaterialType,
)
from mira.knowledge_twins.am.classification_model import (
    AM_RISK_CRITERIA,
    AM_RISK_HIGH_THRESHOLD,
    AMRiskLevel,
    CLASS_C_CRITERIA,
    ClassificationVerdict,
    METALLIC_STRUCTURAL_DEMAND,
    POLYMERIC_STRUCTURAL_DEMAND,
    SecondaryInputs,
    StructuralDemand,
    SUBCLASS_MATRIX,
    assess_am_risk,
    assess_secondary_classification,
    assess_structural_demand,
    validate_primary_class,
)

_MET = MaterialType.METALLIC
_POL = MaterialType.POLYMERIC
_LPBF = AMProcess.L_PBF
_DED = AMProcess.DED


def _all_yes_risk() -> dict[str, bool]:
    return {c.criterion_id: True for c in AM_RISK_CRITERIA}


def _all_met_demand() -> dict[str, bool]:
    return {c.criterion_id: True for c in METALLIC_STRUCTURAL_DEMAND}


# ---------------------------------------------------------------- source pins


def test_source_constants_match_standard_text() -> None:
    """Pin the transcribed tables to the source document values."""
    # [AMR-10] p.37 lists exactly ten criteria, (a) through (j).
    assert [letter for letter, _ in CLASS_C_CRITERIA] == list("abcdefghij")
    # §4.3.2.2 p.43: sum >= 5 is high AM risk.
    assert AM_RISK_HIGH_THRESHOLD == 5
    # Table 4 p.44 "No" scores: 5, 3, 3, 2, 2, 2.
    assert sorted((c.no_score for c in AM_RISK_CRITERIA), reverse=True) == [
        5, 3, 3, 2, 2, 2,
    ]
    # Table 2 p.41 has ten rows; Table 3 p.43 has seven.
    assert len(METALLIC_STRUCTURAL_DEMAND) == 10
    assert len(POLYMERIC_STRUCTURAL_DEMAND) == 7
    # §4.3.2.1 p.40 + §4.3.2.2 p.43 subclass matrix.
    assert SUBCLASS_MATRIX[(StructuralDemand.HIGH, AMRiskLevel.HIGH)] == 1
    assert SUBCLASS_MATRIX[(StructuralDemand.HIGH, AMRiskLevel.LOW)] == 2
    assert SUBCLASS_MATRIX[(StructuralDemand.LOW, AMRiskLevel.HIGH)] == 3
    assert SUBCLASS_MATRIX[(StructuralDemand.LOW, AMRiskLevel.LOW)] == 4
    # Every constant carries a citation back to the standard.
    for criterion in AM_RISK_CRITERIA:
        assert criterion.clause.standard_id == "NASA-STD-6030"
        assert criterion.clause.page == 44


def test_table4_applicability_columns_match_source() -> None:
    """Table 4 p.44 'X' columns by process/material."""
    by_id = {c.criterion_id: c for c in AM_RISK_CRITERIA}
    # As-built fatigue-surface removal applies to metallic only.
    assert (_POL, _LPBF) not in by_id["as_built_removed_fatigue"].applies_to
    assert (_MET, _LPBF) in by_id["as_built_removed_fatigue"].applies_to
    # >=8 trace widths: L-PBF columns; >=2 trace widths: DED only.
    assert (_MET, _DED) not in by_id["walls_8_trace_widths"].applies_to
    assert by_id["walls_2_trace_widths"].applies_to == frozenset({(_MET, _DED)})


# ------------------------------------------------------------- primary class


def test_declared_c_with_catastrophic_consequence_is_mismatch() -> None:
    """GC-4: declared Class C, consequence implies Class A ([AMR-6])."""
    finding = validate_primary_class(
        AMPartClass.CLASS_C,
        ConsequenceTier.CATASTROPHIC,
        [],
        mission_critical=None,
        class_c_criteria_confirmed=True,
    )
    assert finding.verdict is ClassificationVerdict.MISMATCH
    assert finding.expected_class is AMPartClass.CLASS_A
    assert any(c.requirement_tag == "AMR-6" for c in finding.citations)


def test_declared_a_with_catastrophic_matches() -> None:
    finding = validate_primary_class(
        AMPartClass.CLASS_A,
        ConsequenceTier.CATASTROPHIC,
        [HazardFlag.FRACTURE_CRITICAL],
        mission_critical=None,
        class_c_criteria_confirmed=None,
    )
    assert finding.verdict is ClassificationVerdict.MATCHES


def test_mission_critical_alone_triggers_class_a() -> None:
    """[AMR-6]: '...and/or the part is defined as mission critical'."""
    finding = validate_primary_class(
        AMPartClass.CLASS_B,
        ConsequenceTier.MINOR,
        [],
        mission_critical=True,
        class_c_criteria_confirmed=None,
    )
    assert finding.verdict is ClassificationVerdict.MISMATCH
    assert finding.expected_class is AMPartClass.CLASS_A


def test_conservative_class_a_is_accepted() -> None:
    """[AMR-8] rationale p.36: a higher class may always be chosen."""
    finding = validate_primary_class(
        AMPartClass.CLASS_A,
        ConsequenceTier.MINOR,
        [],
        mission_critical=False,
        class_c_criteria_confirmed=None,
    )
    assert finding.verdict is ClassificationVerdict.MATCHES


def test_declared_b_without_trigger_matches_default() -> None:
    finding = validate_primary_class(
        AMPartClass.CLASS_B,
        ConsequenceTier.MAJOR,
        [],
        mission_critical=False,
        class_c_criteria_confirmed=None,
    )
    assert finding.verdict is ClassificationVerdict.MATCHES
    assert any(c.requirement_tag == "AMR-8" for c in finding.citations)


def test_declared_c_without_confirmation_cannot_validate() -> None:
    """GC-5 flavor: the tool never assumes unstated [AMR-10] criteria."""
    finding = validate_primary_class(
        AMPartClass.CLASS_C,
        ConsequenceTier.NEGLIGIBLE,
        [],
        mission_critical=False,
        class_c_criteria_confirmed=None,
    )
    assert finding.verdict is ClassificationVerdict.CANNOT_VALIDATE
    assert "class_c_criteria_confirmed" in finding.missing_inputs


def test_declared_c_with_conflicting_hazard_is_mismatch() -> None:
    """Pressure-vessel hazard violates [AMR-10](c) containment criterion."""
    finding = validate_primary_class(
        AMPartClass.CLASS_C,
        ConsequenceTier.NEGLIGIBLE,
        [HazardFlag.PRESSURE_VESSEL],
        mission_critical=False,
        class_c_criteria_confirmed=True,
    )
    assert finding.verdict is ClassificationVerdict.MISMATCH
    assert finding.expected_class is AMPartClass.CLASS_B


def test_polymeric_class_a_violates_amr7() -> None:
    finding = validate_primary_class(
        AMPartClass.CLASS_A,
        ConsequenceTier.CATASTROPHIC,
        [],
        mission_critical=None,
        class_c_criteria_confirmed=None,
        material_type=MaterialType.POLYMERIC,
    )
    assert finding.verdict is ClassificationVerdict.MISMATCH
    assert any(c.requirement_tag == "AMR-7" for c in finding.citations)


def test_no_declared_class_cannot_validate_never_assigns() -> None:
    finding = validate_primary_class(
        None,
        ConsequenceTier.CATASTROPHIC,
        [],
        mission_critical=None,
        class_c_criteria_confirmed=None,
    )
    assert finding.verdict is ClassificationVerdict.CANNOT_VALIDATE
    assert finding.expected_class is None
    assert "intended_class" in finding.missing_inputs


# ----------------------------------------------------------- secondary class


def test_all_low_demand_all_yes_risk_gives_subclass_4() -> None:
    finding = assess_secondary_classification(
        AMPartClass.CLASS_A,
        _MET,
        _LPBF,
        SecondaryInputs(
            demand_criteria_met=_all_met_demand(), risk_answers=_all_yes_risk()
        ),
    )
    assert finding.structural_demand is StructuralDemand.LOW
    assert finding.am_risk is AMRiskLevel.LOW
    assert finding.am_risk_score == 0
    assert finding.subclass == 4


def test_uninspectable_part_scores_exactly_threshold_and_is_high_risk() -> None:
    """Table 4 row 1 'No' = 5 = threshold; >= comparison per §4.3.2.2."""
    answers = _all_yes_risk()
    answers["inspectable_or_proof"] = False
    demand = _all_met_demand()
    demand["yield_strength"] = False  # high demand
    finding = assess_secondary_classification(
        AMPartClass.CLASS_B, _MET, _LPBF, SecondaryInputs(demand, answers)
    )
    assert finding.am_risk_score == 5
    assert finding.am_risk is AMRiskLevel.HIGH
    assert finding.structural_demand is StructuralDemand.HIGH
    assert finding.subclass == 1


def test_metallic_lpbf_max_risk_score_is_15() -> None:
    """Sum of applicable 'No' scores for metallic L-PBF: 5+3+3+2+2 = 15."""
    answers = {c.criterion_id: False for c in AM_RISK_CRITERIA}
    level, score, missing, _ = assess_am_risk(_MET, _LPBF, answers)
    assert missing == ()
    assert score == 15
    assert level is AMRiskLevel.HIGH


def test_unanswered_risk_row_is_never_scored_zero() -> None:
    answers = _all_yes_risk()
    del answers["no_support_in_critical_regions"]
    level, score, missing, rationale = assess_am_risk(_MET, _LPBF, answers)
    assert level is None and score is None
    assert "no_support_in_critical_regions" in missing
    assert "never scored as zero-risk" in rationale


def test_missing_process_blocks_risk_assessment() -> None:
    level, score, missing, _ = assess_am_risk(_MET, None, _all_yes_risk())
    assert level is None
    assert "am_process" in missing


def test_single_failed_demand_criterion_is_high_demand() -> None:
    demand, missing, _ = assess_structural_demand(
        _MET, {"ultimate_strength": False}
    )
    assert demand is StructuralDemand.HIGH
    assert missing == ()


def test_incomplete_demand_answers_block_low_finding() -> None:
    demand, missing, rationale = assess_structural_demand(
        _MET, {"ultimate_strength": True}
    )
    assert demand is None
    assert "load_cases" in missing
    assert "not assumed" in rationale


def test_class_c_has_no_secondary_classification() -> None:
    finding = assess_secondary_classification(
        AMPartClass.CLASS_C, _MET, _LPBF, SecondaryInputs()
    )
    assert finding.subclass is None
    assert "Class A and B" in finding.rationale
