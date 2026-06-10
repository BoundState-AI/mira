"""
Module: AM Knowledge Twin -- NASA-STD-6030 classification decision model
Purpose: Encode the 6030 part-classification system (§4.3, [AMR-5]..[AMR-12])
         as cited data tables + pure validation functions. Validates an
         engineer's declared class; NEVER generates a class from material or
         process alone, and never resolves missing inputs by guessing.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True

Provenance discipline (NO MAGIC NUMBERS):
    Every criterion, score, and threshold below is transcribed from
    NASA-STD-6030 (Approved 2021-04-21, "APPROVED FOR PUBLIC RELEASE")
    and carries the clause tag and PDF page it came from. The governing
    frozen rule pack is ``am_rulepack`` for NASA-STD-6030 (see freeze.py);
    requirement ids referenced here resolve into that pack.

Source map (PDF page numbers in the approved 2021-04-21 edition):
    [AMR-5]  §4.3.1   p.34  primary classification per Figure 4
    [AMR-6]  §4.3.1.1 p.35  Class A definition
    [AMR-7]  §4.3.1.1.1 p.35 Class A restrictions
    [AMR-8]  §4.3.1.2 p.36  Class B = not A and not C (higher class always allowed)
    [AMR-9]  §4.3.1.2.1 p.36 Class B restrictions
    [AMR-10] §4.3.1.3 p.37  Class C requires ALL criteria a-j
    [AMR-11] §4.3.1.4 p.39  Exempt = all Class C criteria + a-c
    [AMR-12] §4.3.2   p.40  secondary classification per Tables 2/3/4
    Table 2  p.41           structural demand, metallic
    Table 3  p.43           structural demand, polymeric
    Table 4  p.44           AM risk criteria and scores
    §4.3.2.2 p.43           risk threshold: sum < 5 low (subclass 2/4),
                            sum >= 5 high (subclass 1/3)
    §4.3.2.1 p.40           demand: all-table-criteria met -> low (3/4),
                            otherwise high (1/2)

Known UNVERIFIED-pack artifacts (flagged by adversarial review 2026-06-09):
    The frozen GPCM pack records Appendix A compliance-matrix locations for
    some requirements (AMR-6/AMR-7 page 144; AMR-8 section 4.3.1.1.1;
    AMR-12 section 4.3.1.2.1). The pages/sections above were verified
    directly against the body text of the source PDF and are correct; the
    pack metadata corrections belong to the human verification pass that
    re-freezes with --verified (Rev 5 §4.3). Do not hand-edit the pack.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional

from mira.knowledge_twins.am.am_models import (
    AMPartClass,
    AMProcess,
    ConsequenceTier,
    HazardFlag,
    MaterialType,
)
from mira.knowledge_twins.am.rule_pack_models import ClauseRef

_STD = "NASA-STD-6030"


def _clause(section: str, tag: str, page: int) -> ClauseRef:
    return ClauseRef(standard_id=_STD, section=section, requirement_tag=tag, page=page)


# --------------------------------------------------------------------------
# Primary classification criteria ([AMR-5] p.34, Figure 4)
# --------------------------------------------------------------------------

CLASS_A_CLAUSE = _clause("4.3.1.1", "AMR-6", 35)
# [AMR-6]: "Class A, High Consequence of Failure, if failure of the part
# leads to a catastrophic, critical, or safety hazard and/or the part is
# defined as mission critical by the program or project."
CLASS_A_CONSEQUENCE_TIERS = frozenset(
    {ConsequenceTier.CATASTROPHIC, ConsequenceTier.CRITICAL}
)

CLASS_B_CLAUSE = _clause("4.3.1.2", "AMR-8", 36)
CLASS_C_CLAUSE = _clause("4.3.1.3", "AMR-10", 37)
EXEMPT_CLAUSE = _clause("4.3.1.4", "AMR-11", 39)

# [AMR-10] p.37: Class C requires ALL of the following criteria satisfied.
CLASS_C_CRITERIA: tuple[tuple[str, str], ...] = (
    ("a", "Failure of part does not lead to any form of hazardous condition."),
    ("b", "Failure of part does not eliminate a critical redundancy."),
    ("c", "Part does not serve as primary or secondary containment."),
    (
        "d",
        "Part does not serve as redundant structure for fail-safe criteria "
        "per NASA-STD-5019.",
    ),
    ("e", "Part is not designated Non-Hazardous Leak Before Burst per NASA-STD-5019."),
    (
        "f",
        "Failure of part does not cause debris or contamination concerns "
        "(Non-Fracture Critical Low-Release Mass per NASA-STD-5019/6016).",
    ),
    ("g", "Failure of part causes only minor inconvenience to crew or operations."),
    (
        "h",
        "Failure of part does not alter structural margins or related "
        "evaluations on other hardware.",
    ),
    ("i", "Failure of part does not adversely affect other systems or operations."),
    ("j", "Failure of part does not affect minimum mission operations."),
)

# Hazard flags that directly contradict specific Class C criteria.
# Mapping: HazardFlag -> Class C criterion letter it violates ([AMR-10] p.37).
HAZARD_FLAG_CLASS_C_CONFLICTS: Mapping[HazardFlag, str] = {
    HazardFlag.FRACTURE_CRITICAL: "d",
    HazardFlag.PRESSURE_VESSEL: "c",
    HazardFlag.PRIMARY_CONTAINMENT: "c",
    HazardFlag.CRITICAL_REDUNDANCY: "b",
    HazardFlag.DEBRIS_CONTAMINATION: "f",
    HazardFlag.SINGLE_POINT_FAILURE: "b",
}

# [AMR-7] p.35: Class A parts shall not be polymeric, fasteners, or contain
# printed threads. [AMR-9] p.36: Class B parts shall not be fasteners or
# contain printed threads.
CLASS_A_RESTRICTIONS_CLAUSE = _clause("4.3.1.1.1", "AMR-7", 35)
CLASS_B_RESTRICTIONS_CLAUSE = _clause("4.3.1.2.1", "AMR-9", 36)
CLASS_A_PROHIBITS_POLYMERIC = True  # [AMR-7](a) p.35


# --------------------------------------------------------------------------
# Secondary classification ([AMR-12] p.40; Tables 2/3/4; §4.3.2.1-.2)
# --------------------------------------------------------------------------

SECONDARY_CLAUSE = _clause("4.3.2", "AMR-12", 40)


class StructuralDemand(str, Enum):
    LOW = "low"
    HIGH = "high"


class AMRiskLevel(str, Enum):
    LOW = "low"
    HIGH = "high"


@dataclass(frozen=True)
class DemandCriterion:
    """One row of Table 2 (metallic, p.41) or Table 3 (polymeric, p.43)."""

    criterion_id: str
    property_name: str
    low_demand_criterion: str
    clause: ClauseRef


METALLIC_DEMAND_TABLE_CLAUSE = _clause("4.3.2.1 Table 2", "AMR-12", 41)
METALLIC_STRUCTURAL_DEMAND: tuple[DemandCriterion, ...] = tuple(
    DemandCriterion(cid, name, crit, METALLIC_DEMAND_TABLE_CLAUSE)
    for cid, name, crit in (
        ("load_cases", "Load cases", "Well-defined or bounded loads environment"),
        ("env_degradation", "Environmental degradation", "Only due to temperature"),
        ("ultimate_strength", "Ultimate strength", "Minimum margin >= 0.3"),
        ("yield_strength", "Yield strength", "Minimum margin >= 0.2"),
        ("point_strain", "Point strain", "Local plastic strain < 0.005"),
        (
            "hcf_improved",
            "High cycle fatigue, improved surfaces",
            "Cyclic stress range <= 80% of applicable fatigue limit",
        ),
        (
            "hcf_as_built",
            "High cycle fatigue, as-built surfaces",
            "Cyclic stress range <= 60% of applicable fatigue limit",
        ),
        ("lcf", "Low cycle fatigue", "No predicted cyclic plastic strain"),
        ("fracture_life", "Fracture mechanics life", "20x life factor"),
        ("creep", "Creep strain", "No predicted creep strain"),
    )
)

POLYMERIC_DEMAND_TABLE_CLAUSE = _clause("4.3.2.1 Table 3", "AMR-12", 43)
POLYMERIC_STRUCTURAL_DEMAND: tuple[DemandCriterion, ...] = tuple(
    DemandCriterion(cid, name, crit, POLYMERIC_DEMAND_TABLE_CLAUSE)
    for cid, name, crit in (
        ("load_cases", "Load cases", "Well-defined or bounded loads environment"),
        (
            "env_degradation",
            "Environmental degradation",
            "Only temperature and moisture with data; design environment "
            "does not cross Tg",
        ),
        (
            "fatigue",
            "Fatigue",
            "Cyclic stress range <= 50% of applicable fatigue limit",
        ),
        (
            "sustained_stress",
            "Sustained stress / creep strain",
            "No sustained stress and no predicted creep strain",
        ),
        (
            "ultimate_ductile",
            "Ultimate strength (elongation >= 3%)",
            "Minimum margin >= 0.5",
        ),
        (
            "yield_ductile",
            "Yield strength (elongation >= 3%)",
            "Minimum margin >= 0.3",
        ),
        (
            "ultimate_brittle",
            "Ultimate strength (elongation < 3%)",
            "Minimum margin >= 2.0",
        ),
    )
)


@dataclass(frozen=True)
class RiskCriterion:
    """One row of Table 4 (p.44). Score is binary: 0 for Yes, ``no_score``
    for No. Applicability ('X' columns) varies by process/material."""

    criterion_id: str
    question: str
    no_score: int
    applies_to: frozenset[tuple[MaterialType, AMProcess]]
    clause: ClauseRef


_RISK_TABLE_CLAUSE = _clause("4.3.2.2 Table 4", "AMR-12", 44)
_MET_LPBF = (MaterialType.METALLIC, AMProcess.L_PBF)
_MET_DED = (MaterialType.METALLIC, AMProcess.DED)
_POL_LPBF = (MaterialType.POLYMERIC, AMProcess.L_PBF)

AM_RISK_CRITERIA: tuple[RiskCriterion, ...] = (
    RiskCriterion(
        "inspectable_or_proof",
        "All surfaces and volumes can be reliably inspected, or the design "
        "permits adequate proof testing based on stress state?",
        5,
        frozenset({_MET_LPBF, _MET_DED, _POL_LPBF}),
        _RISK_TABLE_CLAUSE,
    ),
    RiskCriterion(
        "as_built_removed_fatigue",
        "As-built surface can be fully removed on all fatigue-critical surfaces?",
        3,
        frozenset({_MET_LPBF, _MET_DED}),
        _RISK_TABLE_CLAUSE,
    ),
    RiskCriterion(
        "support_surfaces_accessible",
        "Surfaces interfacing with support structures are fully accessible "
        "and the as-built surface removed?",
        3,
        frozenset({_MET_LPBF, _MET_DED, _POL_LPBF}),
        _RISK_TABLE_CLAUSE,
    ),
    RiskCriterion(
        "walls_8_trace_widths",
        "Structural walls or protrusions are the equivalent of >= 8 trace "
        "(melt pool / bead / scan path) widths in cross section?",
        2,
        frozenset({_MET_LPBF, _POL_LPBF}),
        _RISK_TABLE_CLAUSE,
    ),
    RiskCriterion(
        "walls_2_trace_widths",
        "Structural walls or protrusions are the equivalent of >= 2 trace "
        "widths in cross section?",
        2,
        frozenset({_MET_DED}),
        _RISK_TABLE_CLAUSE,
    ),
    RiskCriterion(
        "no_support_in_critical_regions",
        "Critical regions of the part do not require support structure?",
        2,
        frozenset({_MET_LPBF, _MET_DED, _POL_LPBF}),
        _RISK_TABLE_CLAUSE,
    ),
)

# §4.3.2.2 p.43: "If the summed AM risk scores less than 5, then the part
# will be assigned low AM risk and placed in subclass 2 or 4. If the summed
# AM risk scores greater than or equal to 5, then the part will be assigned
# high AM risk and placed in subclass 1 or 3."
AM_RISK_HIGH_THRESHOLD = 5
AM_RISK_THRESHOLD_CLAUSE = _clause("4.3.2.2", "AMR-12", 43)

# §4.3.2.1 p.40 + §4.3.2.2 p.43 jointly define the subclass matrix:
#   high demand + high risk -> 1     high demand + low risk -> 2
#   low demand + high risk  -> 3     low demand + low risk  -> 4
SUBCLASS_MATRIX: Mapping[tuple[StructuralDemand, AMRiskLevel], int] = {
    (StructuralDemand.HIGH, AMRiskLevel.HIGH): 1,
    (StructuralDemand.HIGH, AMRiskLevel.LOW): 2,
    (StructuralDemand.LOW, AMRiskLevel.HIGH): 3,
    (StructuralDemand.LOW, AMRiskLevel.LOW): 4,
}
SUBCLASS_MATRIX_CLAUSE = _clause("4.3.2.1-4.3.2.2", "AMR-12", 40)


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


class ClassificationVerdict(str, Enum):
    """Outcome of validating a declared class against declared inputs."""

    MATCHES = "MATCHES"
    MISMATCH = "MISMATCH"
    CANNOT_VALIDATE = "CANNOT_VALIDATE"


@dataclass(frozen=True)
class ClassificationFinding:
    """Result of primary-class validation. Always cites its basis."""

    verdict: ClassificationVerdict
    declared_class: Optional[AMPartClass]
    expected_class: Optional[AMPartClass]
    rationale: str
    citations: tuple[ClauseRef, ...]
    missing_inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecondaryFinding:
    """Result of structural-demand x AM-risk subclass assessment."""

    subclass: Optional[int]
    structural_demand: Optional[StructuralDemand]
    am_risk: Optional[AMRiskLevel]
    am_risk_score: Optional[int]
    rationale: str
    citations: tuple[ClauseRef, ...]
    missing_inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecondaryInputs:
    """Engineer-supplied answers for the secondary assessment.

    ``demand_criteria_met``: per Table 2/3 criterion_id -> True (criterion
    met), False (not met), or absent (unanswered).
    ``risk_answers``: per Table 4 criterion_id -> True (Yes, scores 0) /
    False (No, scores the row's no_score), or absent (unanswered).
    """

    demand_criteria_met: Mapping[str, bool] = field(default_factory=dict)
    risk_answers: Mapping[str, bool] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Pure validation functions
# --------------------------------------------------------------------------


def _class_a_trigger(
    consequence: ConsequenceTier,
    hazard_context: list[HazardFlag],
    mission_critical: Optional[bool],
) -> tuple[bool, str]:
    """[AMR-6] p.35: catastrophic/critical/safety hazard and/or mission
    critical. Crewed-flight hazard context is treated as a safety-hazard
    indicator requiring Class A review."""
    if consequence in CLASS_A_CONSEQUENCE_TIERS:
        return True, f"consequence_of_failure={consequence.value} meets [AMR-6]"
    if mission_critical:
        return True, "part declared mission critical by the program ([AMR-6])"
    if HazardFlag.CREWED_FLIGHT in hazard_context:
        return True, "crewed-flight hazard context indicates safety hazard ([AMR-6])"
    return False, "no [AMR-6] Class A trigger present in declared inputs"


def validate_primary_class(
    declared: Optional[AMPartClass],
    consequence: ConsequenceTier,
    hazard_context: list[HazardFlag],
    mission_critical: Optional[bool],
    class_c_criteria_confirmed: Optional[bool],
    material_type: Optional[MaterialType] = None,
) -> ClassificationFinding:
    """Validate a declared primary class against NASA-STD-6030 §4.3.1.

    Never generates a class on its own authority: where the declared class
    cannot be checked against the supplied inputs, the verdict is
    CANNOT_VALIDATE with the missing inputs named.
    """
    if declared is None:
        return ClassificationFinding(
            verdict=ClassificationVerdict.CANNOT_VALIDATE,
            declared_class=None,
            expected_class=None,
            rationale=(
                "No intended_class declared. NASA-STD-6030 [AMR-5] requires the "
                "CEO to assign the classification; this tool validates, it does "
                "not assign."
            ),
            citations=(_clause("4.3.1", "AMR-5", 34),),
            missing_inputs=("intended_class",),
        )

    a_trigger, a_reason = _class_a_trigger(consequence, hazard_context, mission_critical)
    citations: list[ClauseRef] = [CLASS_A_CLAUSE]

    # [AMR-7](a) p.35: polymeric materials are prohibited for Class A.
    if (
        declared is AMPartClass.CLASS_A
        and material_type is MaterialType.POLYMERIC
        and CLASS_A_PROHIBITS_POLYMERIC
    ):
        return ClassificationFinding(
            verdict=ClassificationVerdict.MISMATCH,
            declared_class=declared,
            expected_class=None,
            rationale=(
                "Declared Class A with polymeric material: [AMR-7](a) prohibits "
                "polymeric materials for Class A parts. Non-metallic AM parts "
                "are intended only for Class B and C applications."
            ),
            citations=(CLASS_A_RESTRICTIONS_CLAUSE,),
        )

    if a_trigger:
        if declared is AMPartClass.CLASS_A:
            return ClassificationFinding(
                verdict=ClassificationVerdict.MATCHES,
                declared_class=declared,
                expected_class=AMPartClass.CLASS_A,
                rationale=f"Class A confirmed: {a_reason}.",
                citations=tuple(citations),
            )
        return ClassificationFinding(
            verdict=ClassificationVerdict.MISMATCH,
            declared_class=declared,
            expected_class=AMPartClass.CLASS_A,
            rationale=(
                f"Declared {declared.value}, but {a_reason}. [AMR-6] requires "
                "Class A for high consequence of failure."
            ),
            citations=tuple(citations),
        )

    # No Class A trigger. A higher class may always be chosen ([AMR-8]
    # rationale, p.36), so a conservative Class A declaration is acceptable.
    if declared is AMPartClass.CLASS_A:
        return ClassificationFinding(
            verdict=ClassificationVerdict.MATCHES,
            declared_class=declared,
            expected_class=AMPartClass.CLASS_A,
            rationale=(
                "No [AMR-6] trigger present, but a higher class designation may "
                "always be chosen ([AMR-8] rationale). Class A accepted as a "
                "conservative declaration."
            ),
            citations=(CLASS_A_CLAUSE, CLASS_B_CLAUSE),
        )

    if declared in (AMPartClass.CLASS_C, AMPartClass.EXEMPT):
        conflicts = sorted(
            {
                f"criterion ({HAZARD_FLAG_CLASS_C_CONFLICTS[flag]})"
                for flag in hazard_context
                if flag in HAZARD_FLAG_CLASS_C_CONFLICTS
            }
        )
        if conflicts:
            return ClassificationFinding(
                verdict=ClassificationVerdict.MISMATCH,
                declared_class=declared,
                expected_class=AMPartClass.CLASS_B,
                rationale=(
                    f"Declared {declared.value}, but declared hazard context "
                    f"violates [AMR-10] {', '.join(conflicts)}. Parts failing any "
                    "Class C criterion and lacking an [AMR-6] trigger default to "
                    "Class B per [AMR-8]."
                ),
                citations=(CLASS_C_CLAUSE, CLASS_B_CLAUSE),
            )
        if not class_c_criteria_confirmed:
            return ClassificationFinding(
                verdict=ClassificationVerdict.CANNOT_VALIDATE,
                declared_class=declared,
                expected_class=None,
                rationale=(
                    f"Declared {declared.value}: [AMR-10] requires ALL ten "
                    "criteria (a-j) to be satisfied"
                    + (
                        " and [AMR-11] adds three further Exempt criteria"
                        if declared is AMPartClass.EXEMPT
                        else ""
                    )
                    + ". Engineer confirmation of the full criteria checklist is "
                    "required; this tool does not assume unstated criteria are met."
                ),
                citations=(CLASS_C_CLAUSE,)
                + ((EXEMPT_CLAUSE,) if declared is AMPartClass.EXEMPT else ()),
                missing_inputs=("class_c_criteria_confirmed",),
            )
        return ClassificationFinding(
            verdict=ClassificationVerdict.MATCHES,
            declared_class=declared,
            expected_class=declared,
            rationale=(
                f"{declared.value} accepted: engineer confirmed all [AMR-10] "
                "criteria (a-j)"
                + (
                    " and the [AMR-11] Exempt criteria"
                    if declared is AMPartClass.EXEMPT
                    else ""
                )
                + "; no [AMR-6] Class A trigger present."
            ),
            citations=(CLASS_C_CLAUSE,)
            + ((EXEMPT_CLAUSE,) if declared is AMPartClass.EXEMPT else ()),
        )

    # Declared Class B: [AMR-8] default when not A and not C.
    return ClassificationFinding(
        verdict=ClassificationVerdict.MATCHES,
        declared_class=declared,
        expected_class=AMPartClass.CLASS_B,
        rationale=(
            "Class B confirmed per [AMR-8]: no [AMR-6] Class A trigger, and "
            "Class C was not claimed."
        ),
        citations=(CLASS_B_CLAUSE,),
    )


def assess_structural_demand(
    material_type: Optional[MaterialType],
    demand_criteria_met: Mapping[str, bool],
) -> tuple[Optional[StructuralDemand], tuple[str, ...], str]:
    """§4.3.2.1 p.40: low demand iff ALL table criteria are met.

    Returns (demand or None, missing criterion ids, rationale). Any
    unanswered criterion blocks a LOW finding (never assumed met); a single
    answered False is sufficient for HIGH.
    """
    if material_type is None:
        return None, ("material_type",), (
            "Structural demand requires material_type to select Table 2 "
            "(metallic) or Table 3 (polymeric)."
        )
    table = (
        METALLIC_STRUCTURAL_DEMAND
        if material_type is MaterialType.METALLIC
        else POLYMERIC_STRUCTURAL_DEMAND
    )
    failed = [c.criterion_id for c in table if demand_criteria_met.get(c.criterion_id) is False]
    if failed:
        return (
            StructuralDemand.HIGH,
            (),
            "High structural demand: criteria not met for "
            + ", ".join(failed)
            + " (§4.3.2.1: otherwise the part is high structural demand).",
        )
    missing = tuple(
        c.criterion_id for c in table if c.criterion_id not in demand_criteria_met
    )
    if missing:
        return None, missing, (
            "Cannot assess structural demand: unanswered Table "
            + ("2" if material_type is MaterialType.METALLIC else "3")
            + " criteria. Low demand requires ALL criteria met (§4.3.2.1); "
            "unanswered criteria are not assumed."
        )
    return (
        StructuralDemand.LOW,
        (),
        "Low structural demand: all applicable table criteria met (§4.3.2.1).",
    )


def assess_am_risk(
    material_type: Optional[MaterialType],
    am_process: Optional[AMProcess],
    risk_answers: Mapping[str, bool],
) -> tuple[Optional[AMRiskLevel], Optional[int], tuple[str, ...], str]:
    """Table 4 p.44 + §4.3.2.2 p.43: binary row scores, sum >= 5 is high risk.

    Returns (risk or None, score or None, missing ids, rationale). All
    applicable rows must be answered: an unanswered row cannot be scored 0,
    because that would silently lower risk.
    """
    if material_type is None or am_process is None:
        needed = tuple(
            name
            for name, value in (("material_type", material_type), ("am_process", am_process))
            if value is None
        )
        return None, None, needed, (
            "AM risk assessment requires material_type and am_process to "
            "determine Table 4 column applicability."
        )
    applicable = [
        c for c in AM_RISK_CRITERIA if (material_type, am_process) in c.applies_to
    ]
    if not applicable:
        return None, None, (), (
            f"Table 4 defines no applicability column for "
            f"{material_type.value} {am_process.value}; AM risk cannot be "
            "scored from NASA-STD-6030 for this combination."
        )
    missing = tuple(c.criterion_id for c in applicable if c.criterion_id not in risk_answers)
    if missing:
        return None, None, missing, (
            "Cannot score AM risk: unanswered Table 4 criteria. Unanswered "
            "rows are never scored as zero-risk."
        )
    score = sum(0 if risk_answers[c.criterion_id] else c.no_score for c in applicable)
    level = AMRiskLevel.HIGH if score >= AM_RISK_HIGH_THRESHOLD else AMRiskLevel.LOW
    return level, score, (), (
        f"AM risk score {score} ({'>=' if level is AMRiskLevel.HIGH else '<'} "
        f"threshold {AM_RISK_HIGH_THRESHOLD}, §4.3.2.2) -> {level.value} risk."
    )


def assess_secondary_classification(
    primary: AMPartClass,
    material_type: Optional[MaterialType],
    am_process: Optional[AMProcess],
    inputs: SecondaryInputs,
) -> SecondaryFinding:
    """[AMR-12] p.40: subclass for Class A/B from demand x risk.

    Class C and Exempt parts carry no secondary classification.
    """
    if primary not in (AMPartClass.CLASS_A, AMPartClass.CLASS_B):
        return SecondaryFinding(
            subclass=None,
            structural_demand=None,
            am_risk=None,
            am_risk_score=None,
            rationale=(
                "[AMR-12] assigns secondary classification only to Class A "
                "and B parts."
            ),
            citations=(SECONDARY_CLAUSE,),
        )

    demand, demand_missing, demand_note = assess_structural_demand(
        material_type, inputs.demand_criteria_met
    )
    risk, score, risk_missing, risk_note = assess_am_risk(
        material_type, am_process, inputs.risk_answers
    )
    missing = tuple(dict.fromkeys((*demand_missing, *risk_missing)))
    if demand is None or risk is None:
        return SecondaryFinding(
            subclass=None,
            structural_demand=demand,
            am_risk=risk,
            am_risk_score=score,
            rationale=f"{demand_note} {risk_note}".strip(),
            citations=(SECONDARY_CLAUSE, AM_RISK_THRESHOLD_CLAUSE),
            missing_inputs=missing,
        )
    subclass = SUBCLASS_MATRIX[(demand, risk)]
    return SecondaryFinding(
        subclass=subclass,
        structural_demand=demand,
        am_risk=risk,
        am_risk_score=score,
        rationale=(
            f"{demand_note} {risk_note} Subclass {subclass} per the "
            "demand x risk matrix (§4.3.2.1-§4.3.2.2)."
        ),
        citations=(SECONDARY_CLAUSE, SUBCLASS_MATRIX_CLAUSE, AM_RISK_THRESHOLD_CLAUSE),
    )
