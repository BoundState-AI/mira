"""Issue detection, precedent matching, and conflict detection for v8."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

from .adapters import search_precedents
from .models import (
    ConflictPair,
    EnvironmentSpec,
    IssueCode,
    IssueOutcome,
    IssueState,
    IssueStatus,
    MaterialResolution,
    MUACategory,
    PrecedentMatch,
    RationalePhrase,
    normalize_issue_code,
)
from .rationale_extractor import extract_rationale_phrases


@dataclass(frozen=True)
class ManualIssueRule:
    code: str
    requirement_ref: str
    patterns: tuple[str, ...]
    message: str


_MANUAL_ISSUE_RULES: tuple[ManualIssueRule, ...] = (
    ManualIssueRule(
        code="WIRE",
        requirement_ref="MPR 54-55",
        patterns=("wire insulation", "insulation", "wire jacket"),
        message="Wire insulation assessment is out of scope in v8.0.",
    ),
    ManualIssueRule(
        code="FRACTURE_CRITICAL",
        requirement_ref="MPR 57-58 / §4.3.1",
        patterns=("fracture-critical", "fracture critical"),
        message="Fracture critical assessments are out of scope in v8.0.",
    ),
    ManualIssueRule(
        code="PROHIBITED_METALS",
        requirement_ref="MPR 59-68",
        patterns=("cadmium", "mercury", "beryllium", "zinc"),
        message="Prohibited metals checks are out of scope in v8.0.",
    ),
    ManualIssueRule(
        code="DESIGN_VALUES",
        requirement_ref="JSC 27301F §4.1.8",
        patterns=("s-basis", "s basis", "mmpds"),
        message="Design values checks are out of scope in v8.0.",
    ),
    ManualIssueRule(
        code="SPEC_CHANGES",
        requirement_ref="JSC 27301F §4.1.3.1",
        patterns=("spec change", "specification changed", "revision change"),
        message="Specification change routing is out of scope in v8.0.",
    ),
    ManualIssueRule(
        code="COTS_NDI",
        requirement_ref="JSC 27301F §4.1.3",
        patterns=("cots", "ndi", "commercial off the shelf"),
        message="COTS/NDI disposition is out of scope in v8.0.",
    ),
    ManualIssueRule(
        code="GEN",
        requirement_ref="JSC 27301F Appendix E (702-703)",
        patterns=("code 702", "code 703", "general rationale"),
        message="General rationale codes (702-703) are not implemented in v8.0.",
    ),
)


def auto_detect_issues(
    material: MaterialResolution,
    environment: EnvironmentSpec,
    application_description: str = "",
) -> dict[str, IssueState]:
    """Auto-detect in-scope and manual issues from context."""

    detected: dict[str, IssueState] = {}

    # Baseline in-scope issues.
    detected[IssueCode.FLAM.value] = IssueState(issue=IssueCode.FLAM.value)
    detected[IssueCode.CORR.value] = IssueState(issue=IssueCode.CORR.value)
    detected[IssueCode.SCC.value] = IssueState(issue=IssueCode.SCC.value)
    detected[IssueCode.TVS.value] = IssueState(issue=IssueCode.TVS.value)
    detected[IssueCode.O2.value] = IssueState(issue=IssueCode.O2.value)
    detected[IssueCode.HEE.value] = IssueState(issue=IssueCode.HEE.value)
    detected[IssueCode.FLUID.value] = IssueState(issue=IssueCode.FLUID.value)

    if environment.location.lower() == "habitable":
        detected[IssueCode.TOX.value] = IssueState(issue=IssueCode.TOX.value)

    text = " ".join(
        [
            material.input_text or "",
            material.resolved_name or "",
            environment.medium or "",
            application_description or "",
            environment.application or "",
        ]
    ).lower()
    for rule in _MANUAL_ISSUE_RULES:
        if any(pattern in text for pattern in rule.patterns):
            detected[rule.code] = IssueState(
                issue=rule.code,
                status=IssueStatus.MANUAL_REQUIRED,
                out_of_scope=True,
                requirement_ref=rule.requirement_ref,
                warnings=[rule.message],
            )

    return detected


def environment_banners(environment: EnvironmentSpec, material: MaterialResolution) -> list[str]:
    """Compute warning banners from environmental triggers."""

    banners: list[str] = []
    medium = (environment.medium or "").upper()

    if medium in {"GH2", "LH2", "HYDROGEN", "H2"}:
        banners.append("HYDROGEN SERVICE: ASTM G142 embrittlement evaluation required.")
    if medium in {"LOX", "GOX", "O2", "OXYGEN"} or environment.o2_percent >= 23.5:
        banners.append("OXYGEN SERVICE: Test 17/Test 1 and OCA required if flammable.")
    if environment.temp_min_f <= -150:
        banners.append("CRYOGENIC: demonstrate ductility and fracture toughness at low temperature.")
    if environment.pressure_psia > 1000:
        banners.append("HIGH PRESSURE: evaluate ignition sensitivity and compatibility.")
    if _needs_fluid_compatibility(environment):
        banners.append("FLUID COMPATIBILITY: evaluate per NASA-STD-6001A Test 15.")
    if _is_non_metallic(material) and _is_propellant_or_oxidizer(medium):
        banners.append("FLUID COMPAT (Change 2): non-metallic + propellant/oxidizer needs MPR 210-212.")
    return banners


def run_precedent_match(
    material: MaterialResolution,
    environment: EnvironmentSpec,
    issue: str | IssueCode,
) -> tuple[list[PrecedentMatch], list[RationalePhrase], list[ConflictPair]]:
    """Run precedent lookup + phrase extraction + conflict detection."""

    issue_code = normalize_issue_code(issue)
    precedents = search_precedents(material, environment, issue_code=issue_code)
    phrases = extract_rationale_phrases(precedents, issue=issue_code)
    conflicts = detect_conflicts(precedents, issue_code)
    return precedents, phrases, conflicts


def detect_conflicts(
    precedents: Iterable[PrecedentMatch],
    issue: str | IssueCode,
) -> list[ConflictPair]:
    """Find conflicting precedent pairs within a single issue search result."""

    issue_code = normalize_issue_code(issue)
    all_precedents = list(precedents)

    approved = [p for p in all_precedents if _is_approved(p.determination)]
    negative = [p for p in all_precedents if _is_negative(p.determination)]
    conflicts: list[ConflictPair] = []

    for a in approved:
        for n in negative:
            if not _same_family(a, n):
                continue
            if issue_code not in a.issue_codes and issue_code not in n.issue_codes:
                continue
            if not _overlapping_envelope(a, n):
                continue

            conflicts.append(
                ConflictPair(
                    approved=a,
                    negative=n,
                    overlap_description=_describe_overlap(a, n),
                )
            )

    return conflicts


def determine_category(
    environment: EnvironmentSpec,
    issues: dict[str, IssueState],
) -> tuple[Optional[MUACategory], list[str]]:
    """Compute overall category from issue outcomes and Cat I triggers."""

    reasons: list[str] = []
    medium = (environment.medium or "").upper()
    is_cat_i_trigger = False

    if medium in {"GH2", "LH2", "HYDROGEN", "H2"}:
        is_cat_i_trigger = True
        reasons.append("Hydrogen service trigger")
    if medium in {"GOX", "LOX", "O2", "OXYGEN", "ENRICHED_AIR", "ENRICHED_O2"} or environment.o2_percent >= 23.5:
        is_cat_i_trigger = True
        reasons.append("Oxygen-enriched trigger")
    if environment.temp_min_f <= -150.0:
        is_cat_i_trigger = True
        reasons.append("Cryogenic trigger")

    has_cat_i_ii_issue = any(i.outcome == IssueOutcome.CAT_I_II for i in issues.values())
    if not has_cat_i_ii_issue:
        return None, reasons

    if is_cat_i_trigger:
        return MUACategory.CAT_I, reasons
    reasons.append("Cat I trigger absent; using Category II")
    return MUACategory.CAT_II, reasons


def _needs_fluid_compatibility(environment: EnvironmentSpec) -> bool:
    medium = (environment.medium or "").upper()
    if medium in {"AIR", "STANDARD_AIR", "CABIN_AIR", ""}:
        return False
    keywords = ("HYDRAZINE", "MMH", "UDMH", "NTO", "N2O4", "PROPELLANT", "OXIDIZER", "FUEL")
    return any(keyword in medium for keyword in keywords) or medium not in {"AIR", ""}


def _is_non_metallic(material: MaterialResolution) -> bool:
    klass = (material.material_class or "").lower()
    return klass in {"polymer", "elastomer", "adhesive", "composite", "sealant", "coating", "other"}


def _is_propellant_or_oxidizer(medium: str) -> bool:
    return any(
        keyword in medium
        for keyword in ("PROPELLANT", "OXIDIZER", "LOX", "GOX", "NTO", "N2O4", "HYDRAZINE")
    )


def _is_approved(determination: str) -> bool:
    return (determination or "").strip().lower() in {"approved", "conditional"}


def _is_negative(determination: str) -> bool:
    return (determination or "").strip().lower() in {"rejected", "deferred", "cancelled"}


def _same_family(a: PrecedentMatch, b: PrecedentMatch) -> bool:
    if not a.material_family or not b.material_family:
        return False
    return a.material_family.strip().upper() == b.material_family.strip().upper()


def _overlapping_envelope(a: PrecedentMatch, b: PrecedentMatch) -> bool:
    return _same_media(a, b) or _pressure_within_2x(a, b) or _temperature_overlap(a, b)


def _same_media(a: PrecedentMatch, b: PrecedentMatch) -> bool:
    media_a = _classify_media(a.environment)
    media_b = _classify_media(b.environment)
    if not media_a or not media_b:
        return False
    return media_a == media_b


def _pressure_within_2x(a: PrecedentMatch, b: PrecedentMatch) -> bool:
    if a.pressure_psia is None or b.pressure_psia is None:
        return False
    lo = min(a.pressure_psia, b.pressure_psia)
    hi = max(a.pressure_psia, b.pressure_psia)
    if lo <= 0:
        return False
    return hi / lo <= 2.0


def _temperature_overlap(a: PrecedentMatch, b: PrecedentMatch) -> bool:
    if a.temp_min_f is None or a.temp_max_f is None or b.temp_min_f is None or b.temp_max_f is None:
        return False
    return max(a.temp_min_f, b.temp_min_f) <= min(a.temp_max_f, b.temp_max_f)


def _describe_overlap(a: PrecedentMatch, b: PrecedentMatch) -> str:
    details: list[str] = []
    if _same_media(a, b):
        details.append("same media type")
    if _pressure_within_2x(a, b):
        details.append("pressure ranges within 2x")
    if _temperature_overlap(a, b):
        details.append("temperature ranges overlap")
    if not details:
        details.append("partially overlapping environment")
    return ", ".join(details)


def _classify_media(environment_text: str) -> str:
    text = (environment_text or "").upper()
    if any(token in text for token in ("GOX", "LOX", "OXYGEN", "O2")):
        return "OXYGEN"
    if any(token in text for token in ("GH2", "LH2", "HYDROGEN", "H2")):
        return "HYDROGEN"
    if "AIR" in text:
        return "AIR"
    if any(token in text for token in ("NTO", "MMH", "UDMH", "HYDRAZINE", "PROPELLANT", "OXIDIZER")):
        return "PROPELLANT"
    return ""


def is_auto_scope_issue(issue: str) -> bool:
    """True when issue is one of the canonical v8 automated issue domains."""

    try:
        normalize_issue_code(issue)
        return True
    except ValueError:
        return False


def normalize_manual_status(issue: IssueState) -> IssueState:
    """Normalize manual issue status for safety when loaded from persisted files."""

    if issue.out_of_scope and issue.status != IssueStatus.MANUAL_REQUIRED:
        issue.status = IssueStatus.MANUAL_REQUIRED
    if issue.out_of_scope and issue.outcome is not None:
        issue.outcome = None
    return issue


def safe_float(value: Optional[float]) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    return float(value)
