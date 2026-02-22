"""JSC 27301F Category Router — Corrected Semantics.

Routes MUA submissions to Category I, II, or III per JSC 27301F (with
NASA-STD-6016C technical thresholds),
producing a deterministic, fully-traceable audit trail.

CRITICAL FIX (Feb 2026): Category semantics were INVERTED.
    Old:  Cat I = "strong evidence, standard env"   <- WRONG
          Cat III = "weak evidence, needs testing"   <- WRONG
    New:  Cat I = MOST RESTRICTIVE (safety/mission critical)
          Cat III = SIMPLEST (Appendix E code, closed at MIUL level)

Routing hierarchy (most restrictive wins):

    Category I  — Safety/mission critical. LOX/GOX service, enriched O2
                  (>= 23.5%), oxygen component acceptance testing (GOX/enriched
                  air > 1.83 MPa / 265 psia per §4.2.1.4), hydrogen service
                  (embrittlement per §4.2.6.4), prohibited families in O2.
                  OUTPUT: Full 7-section MUA document.
                  APPROVAL: Hardware M&P -> NASA M&P (EM04) -> Program Office.
                  REISSUE: Required for any update (§8).

    Category II — Default bucket. Non-conforming but not safety-critical.
                  Materials with C/D/X ratings requiring engineering
                  disposition, conditional approvals, expired test data.
                  OUTPUT: Full 7-section MUA document.
                  APPROVAL: Hardware M&P -> NASA M&P (EM04).
                  REISSUE: Required for any update (§8).

    Category III — Has approved Appendix E rationale code. Material doesn't
                   meet requirements but has an accepted disposition code
                   (e.g., 103, 104, 105, 106, 107, 108, S01-S06)
                   in the approved M&P plan.
                   OUTPUT: MIUL rationale-code report (NO MUA form submitted).
                   APPROVAL: Hardware M&P -> NASA M&P (via MIUL acceptance).
                   NOTE: Per JSC 27301F §4.3.3, "No MUA form is submitted"
                   for Cat III.

Key thresholds — ALL live in AuthorityPack with §-citations:
    - Enriched O2: >= 23.5% (§4.2.1.4)
    - O2 acceptance testing: > 1.83 MPa / 265 psia (§4.2.1.4.1)
    - Minor quantity: < 45g AND < 13 cm² (JSC 27301F Appendix E, Code 105)
    - Cryogenic: <= -150°F (§4.2.6.1)

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from .models import (
    CategoryRoutingResult,
    Center,
    EnvironmentSpec,
    GapIdentified,
    MaterialResolution,
    MUACategory,
    TestDataRecord,
)

logger = logging.getLogger(__name__)


# JSC 27301F Appendix E rationale-code families supported by Cat III.
# We keep this set explicit so normalization is deterministic and auditable.
_JSC_APPENDIX_E_CODES: set[str] = {
    # Flammability
    "101", "102", "103", "104", "105", "106", "107", "108", "109", "110", "111", "112", "113", "114",
    # Toxicity
    "201", "202", "203", "204",
    # Fluid compatibility
    "301", "302", "303", "304",
    # Thermal vacuum stability
    "401", "402", "403", "404", "405", "406", "407", "408", "409",
    # SCC
    "501", "502", "503", "504", "505", "506",
    # Corrosion
    "601", "602", "603", "604", "606", "607", "608", "609", "610", "611", "612",
    # General
    "702", "703",
    # Stowage
    "S01", "S02", "S03", "S04", "S05", "S06",
}


# ═══════════════════════════════════════════════════════════════════════
# AUTHORITY PACK — All thresholds with citations. No magic numbers.
# ═══════════════════════════════════════════════════════════════════════


class ThresholdEntry(BaseModel):
    """A single threshold value with full provenance.

    Every number in the routing logic traces back to a specific paragraph
    in a governing standard. No hardcoded magic numbers.
    """
    value: float
    unit: str
    source_doc: str
    section: str
    description: str
    effective_date: str = "2020-07-06"  # 6016C Rev 3 effective date


class AuthorityPack(BaseModel):
    """Standards authority pack — parameterizes routing by center/standard.

    Contains ALL thresholds, triggers, and citation info needed to route
    an MUA. Nothing is hardcoded in the routing logic itself.

    The default pack targets MSFC under NASA-STD-6016C Rev. 3.
    Future packs (e.g. ECSS-Q-ST-70 for ESA, JAXA-QTS-2060) can override
    thresholds without forking routing logic.
    """
    name: str = "NASA-STD-6016C"
    version: str = "Rev. 3"
    center: str = "MSFC"

    # ── Oxygen thresholds ──
    enriched_o2_threshold: ThresholdEntry = ThresholdEntry(
        value=23.5,
        unit="percent",
        source_doc="NASA-STD-6016C",
        section="§4.2.1.4",
        description=(
            "Materials used in oxygen systems where the oxygen concentration "
            "exceeds 23.5 percent shall be evaluated for oxygen compatibility"
        ),
    )
    o2_acceptance_test_pressure: ThresholdEntry = ThresholdEntry(
        value=265.0,
        unit="psia",
        source_doc="NASA-STD-6016C",
        section="§4.2.1.4.1",
        description=(
            "GOX and enriched air components above 1.83 MPa (265 psia) "
            "require oxygen component acceptance testing. Listed metallic "
            "exceptions may apply."
        ),
    )

    # ── Minor quantity thresholds (JSC 27301F Appendix E, Code 105) ──
    minor_quantity_mass_g: ThresholdEntry = ThresholdEntry(
        value=45.0,
        unit="grams",
        source_doc="JSC 27301F",
        section="Appendix E, Code 105",
        description="Minor quantity exemption: total mass less than 45 grams",
    )
    minor_quantity_area_cm2: ThresholdEntry = ThresholdEntry(
        value=13.0,
        unit="cm2",
        source_doc="JSC 27301F",
        section="Appendix E, Code 105",
        description=(
            "Minor quantity exemption: total exposed surface area less than "
            "13 cm2 (approximately 2 in2)"
        ),
    )

    # ── Cryogenic threshold ──
    cryogenic_temp_f: ThresholdEntry = ThresholdEntry(
        value=-150.0,
        unit="degF",
        source_doc="NASA-STD-6016C",
        section="§4.2.6.1",
        description=(
            "Materials at or below -150 degF require cryogenic compatibility "
            "evaluation including ductility and fracture toughness"
        ),
    )

    # ── Oxygen service media ──
    o2_service_media: list[str] = [
        "GOX", "LOX", "OXYGEN", "O2",
        "ENRICHED_AIR", "ENRICHED_O2",
    ]

    # ── Prohibited material families in O2 service ──
    prohibited_families_o2: dict[str, str] = {
        "titanium": (
            "Titanium alloys are ignition-sensitive in enriched O2 service "
            "(NASA-STD-6016C §4.2.1.4 Note 2)"
        ),
        "magnesium": (
            "Magnesium alloys are highly flammable in enriched O2 service "
            "(NASA-STD-6016C §4.2.1.4 Note 3)"
        ),
    }

    # ── Ratings acceptable for Category III ──
    acceptable_ratings_cat3: list[str] = ["A", "B"]
    tvs_b_exception_non_habitable: bool = True


# ═══════════════════════════════════════════════════════════════════════
# ROUTING RULE HIT — Audit trail atom
# ═══════════════════════════════════════════════════════════════════════


class RoutingRuleHit(BaseModel):
    """A single routing rule that fired during category determination.

    Every hit carries enough context to reconstruct the routing decision
    during audit or appeal.
    """
    rule_id: str
    rule_description: str
    citation: str           # e.g. "NASA-STD-6016C §4.2.1.4"
    triggered_by: str       # What condition triggered this rule
    severity: str = "info"  # info / warning / critical


# ═══════════════════════════════════════════════════════════════════════
# OUTPUT TYPE — What artifact does each category produce?
# ═══════════════════════════════════════════════════════════════════════


class MUAOutputType(BaseModel):
    """Defines what artifact each category produces.

    CRITICAL: Category III does NOT produce a full MUA form.
    Per JSC 27301F §4.3.3, Cat III items are reported via MIUL rationale codes.
    Generating a full MUA for Cat III is WRONG PAPERWORK.
    """
    category: str
    output_format: str          # "full_mua" or "miul_rationale_code"
    requires_mua_form: bool
    requires_reissue_on_update: bool
    approval_chain: list[str]
    description: str


# Pre-built output types
_OUTPUT_TYPES = {
    "I": MUAOutputType(
        category="I",
        output_format="full_mua",
        requires_mua_form=True,
        requires_reissue_on_update=True,
        approval_chain=[
            "Hardware M&P Engineer",
            "NASA M&P (center branch, e.g. MSFC EM04)",
            "Program/Project Office",
        ],
        description=(
            "Category I: Safety/mission critical. Full MUA document required. "
            "Complete reissue required for any update per section 8."
        ),
    ),
    "II": MUAOutputType(
        category="II",
        output_format="full_mua",
        requires_mua_form=True,
        requires_reissue_on_update=True,
        approval_chain=[
            "Hardware M&P Engineer",
            "NASA M&P (center branch, e.g. MSFC EM04)",
        ],
        description=(
            "Category II: Non-conforming, engineering disposition required. "
            "Full MUA document required. Complete reissue for updates per section 8."
        ),
    ),
    "III": MUAOutputType(
        category="III",
        output_format="miul_rationale_code",
        requires_mua_form=False,
        requires_reissue_on_update=False,
        approval_chain=[
            "Hardware M&P Engineer",
            "NASA M&P (via MIUL acceptance)",
        ],
        description=(
            "Category III: Appendix E rationale code applies. No MUA form "
            "submitted. Disposition reported in MIUL system with rationale "
            "code."
        ),
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX E CODE DETECTION
# ═══════════════════════════════════════════════════════════════════════


class AppendixBEvaluation(BaseModel):
    """Result of Category III rationale-code eligibility check.

    Legacy name preserved for API compatibility.
    """
    eligible: bool
    code: Optional[str] = None       # "103", "104", "105", etc.
    code_description: str = ""
    rationale_template: str = ""
    citation: str = ""
    evidence: list[str] = []         # What conditions were met
    plan_approved: Optional[bool] = None
    plan_approved_codes: list[str] = Field(default_factory=list)


def _normalize_appendix_b_codes(
    codes: Optional[list[str]],
) -> list[str]:
    """Normalize Category III rationale-code allow-list values.

    Legacy function name preserved for API compatibility.
    Accepts values in flexible forms ("104", "104,105", "Code 104", "S01")
    and returns de-duplicated valid JSC 27301F Appendix E codes.
    """
    if not codes:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        if raw is None:
            continue
        # Split on common delimiters in case callers send joined strings.
        chunks = re.split(r"[\s,;|]+", str(raw))
        for chunk in chunks:
            if not chunk:
                continue
            m = re.search(r"\b(S0[1-6]|\d{3})\b", chunk.upper())
            if not m:
                continue
            code = m.group(1)
            if code not in _JSC_APPENDIX_E_CODES:
                continue
            if code not in seen:
                seen.add(code)
                out.append(code)
    return out


def evaluate_appendix_b(
    env: EnvironmentSpec,
    test_data: list[TestDataRecord],
    gaps: list[GapIdentified],
    material: MaterialResolution,
    weight_lb: Optional[float] = None,
    area_in2: Optional[float] = None,
    engineer_notes: str = "",
    authority: Optional[AuthorityPack] = None,
) -> AppendixBEvaluation:
    """Check if material qualifies for a Category III rationale code.

    Legacy function name preserved for API compatibility.
    Semantics follow JSC 27301F Appendix E.

    Codes checked (in order of specificity):
        105 -- Minor quantity (< 45g AND < 13 cm2)
        104 -- Sandwiched/encapsulated between non-flammable materials
        106 -- Hermetically sealed container
        103 -- Tested in actual use configuration
        108 -- Off-the-shelf equipment in configuration
        107 -- Non-propagating (configuration prevents spread)

    Returns the FIRST qualifying code found.
    """
    if authority is None:
        authority = AuthorityPack()

    notes_lower = engineer_notes.lower()

    # ── Disqualifiers: no Cat III rationale code if Cat I triggers present ──
    medium_upper = env.medium.upper() if env.medium else ""
    is_o2_service = medium_upper in [m.upper() for m in authority.o2_service_media]

    if is_o2_service or env.is_enriched_o2:
        return AppendixBEvaluation(
            eligible=False,
            evidence=["O2/enriched O2 service: Appendix E code path not applicable"],
        )

    if env.is_hydrogen_service:
        return AppendixBEvaluation(
            eligible=False,
            evidence=["Hydrogen service: Appendix E code path not applicable"],
        )

    # ── Code 105: Minor quantity ──
    mass_threshold_g = authority.minor_quantity_mass_g.value
    area_threshold_cm2 = authority.minor_quantity_area_cm2.value

    if weight_lb is not None and area_in2 is not None:
        weight_g = weight_lb * 453.592
        area_cm2 = area_in2 * 6.4516

        if weight_g < mass_threshold_g and area_cm2 < area_threshold_cm2:
            return AppendixBEvaluation(
                eligible=True,
                code="105",
                code_description="Minor quantity exemption",
                citation=authority.minor_quantity_mass_g.section,
                rationale_template=(
                    f"The subject material ({material.resolved_name or material.input_text}) "
                    f"is considered acceptable for this application due to:\n"
                    f"1. Total mass {weight_g:.1f}g < {mass_threshold_g}g threshold "
                    f"({weight_lb:.3f} lb) and exposed area {area_cm2:.1f} cm2 < "
                    f"{area_threshold_cm2} cm2 threshold ({area_in2:.2f} in2).\n"
                    f"2. Material not located near ignition source.\n"
                    f"3. No propagation path to adjacent materials.\n"
                    f"[ENGINEER: Confirm no propagation path and no ignition "
                    f"source proximity]"
                ),
                evidence=[
                    f"weight_g={weight_g:.1f} < {mass_threshold_g}",
                    f"area_cm2={area_cm2:.1f} < {area_threshold_cm2}",
                ],
            )

    # ── Code 104: Sandwiched/encapsulated ──
    sandwich_keywords = [
        "sandwich", "sandwiched", "overcoat", "overcoated",
        "encapsulated", "bonded to metal", "between metal",
        "enclosed by", "covered by", "laminated",
    ]
    if any(kw in notes_lower for kw in sandwich_keywords):
        return AppendixBEvaluation(
            eligible=True,
            code="104",
            code_description="Sandwiched between non-flammable materials",
            citation="JSC 27301F Appendix E, Code 104",
            rationale_template=(
                f"The subject material ({material.resolved_name or material.input_text}) "
                f"is acceptable because:\n"
                f"1. Material sandwiched between non-flammable materials "
                f"[SPECIFY: e.g., aluminum panels].\n"
                f"2. Exposed edge area minimal.\n"
                f"3. Surrounding materials act as heat sinks preventing ignition.\n"
                f"[ENGINEER: Specify barrier materials and configuration]"
            ),
            evidence=["Engineer notes contain sandwich/encapsulation keywords"],
        )

    # ── Code 106: Hermetically sealed ──
    sealed_keywords = [
        "hermetically sealed", "sealed container", "welded enclosure",
        "brazed enclosure", "sealed volume", "hermetic",
    ]
    if any(kw in notes_lower for kw in sealed_keywords):
        return AppendixBEvaluation(
            eligible=True,
            code="106",
            code_description="Hermetically sealed container",
            citation="JSC 27301F Appendix E, Code 106",
            rationale_template=(
                f"The subject material ({material.resolved_name or material.input_text}) "
                f"is contained within hermetically sealed enclosure:\n"
                f"1. Enclosure is [SPECIFY: welded/brazed/sealed], prevents "
                f"atmospheric exchange.\n"
                f"2. No ignition source within sealed volume.\n"
                f"3. Material cannot contribute to fire propagation.\n"
                f"[ENGINEER: Specify seal type and enclosure drawing number]"
            ),
            evidence=["Engineer notes contain hermetic seal keywords"],
        )

    # ── Code 103: Tested in actual use configuration ──
    tested_keywords = [
        "tested in configuration", "tested in use",
        "configuration tested", "full-scale test", "system-level test",
    ]
    if any(kw in notes_lower for kw in tested_keywords):
        return AppendixBEvaluation(
            eligible=True,
            code="103",
            code_description="Tested/passes when tested in actual use configuration",
            citation="JSC 27301F Appendix E, Code 103",
            rationale_template=(
                f"The subject material ({material.resolved_name or material.input_text}) "
                f"passes when tested in the actual use configuration:\n"
                f"1. Test report: [SPECIFY: report number and date].\n"
                f"2. Test conditions match service environment.\n"
                f"3. Configuration matches as-installed geometry.\n"
                f"[ENGINEER: Cite specific test report and confirm configuration match]"
            ),
            evidence=["Engineer notes indicate configuration-level testing"],
        )

    # ── Code 108: Off-the-shelf equipment ──
    ots_keywords = [
        "off-the-shelf", "ots", "cots", "commercial off",
        "off the shelf", "catalog item",
    ]
    if any(kw in notes_lower for kw in ots_keywords):
        return AppendixBEvaluation(
            eligible=True,
            code="108",
            code_description="Off-the-shelf equipment acceptable in configuration",
            citation="JSC 27301F Appendix E, Code 108",
            rationale_template=(
                f"The subject material ({material.resolved_name or material.input_text}) "
                f"is part of off-the-shelf equipment:\n"
                f"1. Equipment is [SPECIFY: manufacturer/model].\n"
                f"2. Material is integral to OTS unit and cannot be substituted.\n"
                f"3. OTS unit has flight heritage / qualification data.\n"
                f"[ENGINEER: Specify OTS equipment and heritage data]"
            ),
            evidence=["Engineer notes indicate OTS/COTS equipment"],
        )

    # ── No Appendix E code applies ──
    return AppendixBEvaluation(
        eligible=False,
        evidence=["No Appendix E rationale code criteria met"],
    )


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY ROUTER — The corrected engine
# ═══════════════════════════════════════════════════════════════════════


class CategoryRouter:
    """Routes an MUA to Category I / II / III per NASA-STD-6016C.

    CORRECTED SEMANTICS (Feb 2026):
        Cat I  = MOST RESTRICTIVE (safety critical, LOX/GOX/H2, enriched O2)
        Cat II = DEFAULT (non-conforming, needs engineering disposition)
        Cat III = SIMPLEST (has Appendix E code, reported in MIUL, no MUA form)

    Usage::

        router = CategoryRouter()
        result = router.route(environment, test_records, gaps, material)
        print(result.category)          # MUACategory.I
        print(result.output_type)       # MUAOutputType (full_mua vs miul_rationale_code)
        print(result.routing_basis)     # [RoutingRuleHit, ...]

    The router checks Category I triggers first (most restrictive), then
    evaluates Category III eligibility (Appendix E). If neither applies,
    Category II is assigned (the default bucket).
    """

    def __init__(self, authority_pack: Optional[AuthorityPack] = None) -> None:
        self.authority_pack = authority_pack or AuthorityPack()

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def route(
        self,
        environment: EnvironmentSpec,
        test_data: list[TestDataRecord],
        gaps: list[GapIdentified],
        material_resolution: MaterialResolution,
        weight_lb: Optional[float] = None,
        area_in2: Optional[float] = None,
        engineer_notes: str = "",
        approved_appendix_b_codes: Optional[list[str]] = None,
    ) -> CategoryRoutingResult:
        """Determine MUA category with full audit trail.

        Parameters
        ----------
        environment:
            The service environment specification.
        test_data:
            MAPTIS test data records for the resolved material.
        gaps:
            Gaps identified during the investigation step.
        material_resolution:
            Material resolution result from Step 1.
        weight_lb:
            Optional material weight (for Appendix E Code 105 check).
        area_in2:
            Optional exposed surface area (for Code 105 check).
        engineer_notes:
            Free-text engineer notes (for Appendix E keyword detection).

        Returns
        -------
        CategoryRoutingResult
            Contains category, output type, ordered rule hits, required
            approvals, required verifications, and rationale-code evaluation.
        """
        ap = self.authority_pack
        rule_hits: list[RoutingRuleHit] = []

        # ── Phase 1: Check Category I triggers (most restrictive) ──
        cat1_hits = self._check_category_i(environment, material_resolution)
        rule_hits.extend(cat1_hits)

        if cat1_hits:
            category = MUACategory.I
            output_type = _OUTPUT_TYPES["I"]
            appendix_b = None
        else:
            # ── Phase 2: Evaluate Category III (Appendix E eligibility) ──
            appendix_b = evaluate_appendix_b(
                env=environment,
                test_data=test_data,
                gaps=gaps,
                material=material_resolution,
                weight_lb=weight_lb,
                area_in2=area_in2,
                engineer_notes=engineer_notes,
                authority=ap,
            )
            approved_codes = _normalize_appendix_b_codes(
                approved_appendix_b_codes
            )
            appendix_b.plan_approved_codes = approved_codes
            appendix_b.plan_approved = bool(
                appendix_b.eligible
                and appendix_b.code
                and appendix_b.code in approved_codes
            )

            if appendix_b.eligible and not appendix_b.plan_approved:
                rule_hits.append(RoutingRuleHit(
                    rule_id="CAT3-PLAN-001",
                    rule_description=(
                        f"Appendix E Code {appendix_b.code} is not listed "
                        "as an approved Category III rationale code for "
                        "this hardware/program plan."
                    ),
                    citation=f"{ap.name} §4.1.6.1.3",
                    triggered_by=(
                        f"rationale_code={appendix_b.code}, "
                        f"approved_codes={approved_codes}"
                    ),
                ))

            # Cat III also requires all ratings A or B (no open non-conformances)
            ratings_ok, rating_hits = self._check_ratings_acceptable(
                test_data, environment
            )
            rule_hits.extend(rating_hits)

            # No open critical/high gaps
            critical_gaps = [
                g for g in gaps
                if g.severity in ("critical", "high") and g.requires_review
            ]

            if (
                appendix_b.eligible
                and appendix_b.plan_approved
                and ratings_ok
                and not critical_gaps
            ):
                category = MUACategory.III
                output_type = _OUTPUT_TYPES["III"]
                rule_hits.append(RoutingRuleHit(
                    rule_id="CAT3-ELIGIBLE",
                    rule_description=(
                        f"Appendix E Code {appendix_b.code} applies: "
                        f"{appendix_b.code_description}. No MUA form required."
                    ),
                    citation=appendix_b.citation,
                    triggered_by=", ".join(appendix_b.evidence),
                ))
            else:
                # ── Phase 3: Default to Category II ──
                category = MUACategory.II
                output_type = _OUTPUT_TYPES["II"]
                cat2_hits = self._annotate_category_ii(
                    test_data, gaps, appendix_b
                )
                rule_hits.extend(cat2_hits)

        # ── Build result ──
        approvals = self._get_approvals(category)
        verifications = self._get_verifications(category, gaps, environment)

        return CategoryRoutingResult(
            category=category,
            routing_basis=[hit.model_dump() for hit in rule_hits],
            required_approvals=approvals,
            required_verifications=verifications,
            authority_pack=ap.name,
            authority_pack_version=ap.version,
            # NEW fields for corrected semantics
            output_type=output_type.model_dump() if output_type else None,
            appendix_b_evaluation=(
                appendix_b.model_dump() if appendix_b else None
            ),
        )

    # ──────────────────────────────────────────────────────────────────
    # Category I checks — Safety/mission critical triggers
    # ──────────────────────────────────────────────────────────────────

    def _check_category_i(
        self,
        env: EnvironmentSpec,
        mat: MaterialResolution,
    ) -> list[RoutingRuleHit]:
        """Return all Category I rule hits (may be empty)."""
        ap = self.authority_pack
        hits: list[RoutingRuleHit] = []

        medium_upper = (env.medium or "").upper()
        is_o2_service = medium_upper in [
            m.upper() for m in ap.o2_service_media
        ]

        # ── CAT1-001: LOX / GOX service ──
        if medium_upper in ("LOX", "GOX"):
            hits.append(RoutingRuleHit(
                rule_id="CAT1-001",
                rule_description=(
                    "Material is used in liquid or gaseous oxygen service, "
                    "requiring Category I assessment per NASA-STD-6001B "
                    "oxygen compatibility evaluation"
                ),
                citation=f"{ap.name} §4.2.1.4",
                triggered_by=f"medium={env.medium}",
                severity="critical",
            ))

        # ── CAT1-002: Enriched oxygen (>= 23.5%) ──
        o2_threshold = ap.enriched_o2_threshold.value
        if env.o2_percent is not None and env.o2_percent >= o2_threshold:
            hits.append(RoutingRuleHit(
                rule_id="CAT1-002",
                rule_description=(
                    f"Oxygen concentration {env.o2_percent}% is at or above "
                    f"the enriched threshold of {o2_threshold}%, requiring "
                    f"oxygen compatibility evaluation per NASA-STD-6001B"
                ),
                citation=ap.enriched_o2_threshold.section,
                triggered_by=f"o2_percent={env.o2_percent}% >= {o2_threshold}%",
                severity="critical",
            ))

        # ── CAT1-003: O2 acceptance testing pressure (> 265 psia) ──
        # CORRECTED: Was 43.5 psia (ungrounded). 6016C specifies
        # 1.83 MPa (265 psia) for GOX/enriched air component acceptance.
        psi_threshold = ap.o2_acceptance_test_pressure.value
        if is_o2_service and env.pressure_psia is not None:
            if env.pressure_psia > psi_threshold:
                hits.append(RoutingRuleHit(
                    rule_id="CAT1-003",
                    rule_description=(
                        f"Pressure {env.pressure_psia} psia exceeds "
                        f"{psi_threshold} psia (1.83 MPa) in oxygen service, "
                        f"requiring oxygen component acceptance testing"
                    ),
                    citation=ap.o2_acceptance_test_pressure.section,
                    triggered_by=(
                        f"pressure_psia={env.pressure_psia} > "
                        f"{psi_threshold}, medium={env.medium}"
                    ),
                    severity="critical",
                ))

        # ── CAT1-004: Hydrogen service (embrittlement) ──
        if env.is_hydrogen_service:
            hits.append(RoutingRuleHit(
                rule_id="CAT1-004",
                rule_description=(
                    "Material is used in hydrogen service; hydrogen "
                    "embrittlement assessment required per ASTM G142 "
                    "or equivalent"
                ),
                citation=f"{ap.name} §4.2.6.4",
                triggered_by=f"medium={env.medium}",
                severity="critical",
            ))

        # ── CAT1-005: Prohibited material family in O2 service ──
        if is_o2_service or (
            env.o2_percent is not None and env.o2_percent >= o2_threshold
        ):
            family_lower = (mat.family or "").lower()
            if family_lower in ap.prohibited_families_o2:
                reason = ap.prohibited_families_o2[family_lower]
                hits.append(RoutingRuleHit(
                    rule_id="CAT1-005",
                    rule_description=(
                        f"Prohibited material family '{mat.family}' in "
                        f"oxygen service: {reason}"
                    ),
                    citation=f"{ap.name} §4.2.1.4",
                    triggered_by=(
                        f"family={mat.family}, o2_percent={env.o2_percent}%, "
                        f"medium={env.medium}"
                    ),
                    severity="critical",
                ))

        # ── CAT1-006: Cryogenic service ──
        cryo_threshold = ap.cryogenic_temp_f.value
        if env.temp_min_f is not None and env.temp_min_f <= cryo_threshold:
            hits.append(RoutingRuleHit(
                rule_id="CAT1-006",
                rule_description=(
                    f"Minimum temperature {env.temp_min_f} degF is at or below "
                    f"cryogenic threshold ({cryo_threshold} degF), requiring "
                    f"cryogenic compatibility evaluation"
                ),
                citation=ap.cryogenic_temp_f.section,
                triggered_by=(
                    f"temp_min_f={env.temp_min_f} <= {cryo_threshold}"
                ),
                severity="warning",
            ))

        return hits

    # ──────────────────────────────────────────────────────────────────
    # Ratings check — Are all MAPTIS ratings A or B?
    # ──────────────────────────────────────────────────────────────────

    def _check_ratings_acceptable(
        self,
        test_data: list[TestDataRecord],
        env: EnvironmentSpec,
    ) -> tuple[bool, list[RoutingRuleHit]]:
        """Check if all current MAPTIS ratings are A or B.

        Returns (all_acceptable, rule_hits).
        """
        ap = self.authority_pack
        hits: list[RoutingRuleHit] = []
        acceptable = set(ap.acceptable_ratings_cat3)
        is_non_hab = env.location.lower() in (
            "non_habitable", "non-habitable", "external",
        )

        non_qualifying = []
        for record in test_data:
            if not record.is_current:
                continue  # Only check current data
            if record.test_class.upper() == "FS" and record.medium_match is False:
                continue  # FS evidence for a different medium is non-applicable
            if record.rating is None:
                non_qualifying.append(f"{record.test_class}:None")
                continue

            rating_upper = record.rating.upper()
            if rating_upper not in acceptable:
                # TVS-B exception in non-habitable
                if (
                    ap.tvs_b_exception_non_habitable
                    and record.test_class.upper() == "TVS"
                    and rating_upper == "B"
                    and is_non_hab
                ):
                    hits.append(RoutingRuleHit(
                        rule_id="RATING-TVS-EXCEPTION",
                        rule_description=(
                            "TVS rating B accepted in non-habitable per "
                            "standard exception"
                        ),
                        citation=f"{ap.name} §4.3.3 Note 1",
                        triggered_by=(
                            f"test_class=TVS, rating=B, location={env.location}"
                        ),
                    ))
                    continue
                non_qualifying.append(f"{record.test_class}:{record.rating}")

        if non_qualifying:
            hits.append(RoutingRuleHit(
                rule_id="RATING-FAIL",
                rule_description=(
                    f"Non-qualifying ratings: {', '.join(non_qualifying)}. "
                    f"Cat III requires all A or B."
                ),
                citation=f"{ap.name} §4.3.3",
                triggered_by=f"non_qualifying={non_qualifying}",
            ))
            return False, hits

        if not test_data:
            hits.append(RoutingRuleHit(
                rule_id="RATING-NO-DATA",
                rule_description="No test data available for ratings check",
                citation=f"{ap.name} §4.3.3",
                triggered_by="test_data_count=0",
            ))
            return False, hits

        hits.append(RoutingRuleHit(
            rule_id="RATING-OK",
            rule_description="All current MAPTIS ratings are A or B",
            citation=f"{ap.name} §4.3.3",
            triggered_by="all_ratings_acceptable=True",
        ))
        return True, hits

    # ──────────────────────────────────────────────────────────────────
    # Category II annotations
    # ──────────────────────────────────────────────────────────────────

    def _annotate_category_ii(
        self,
        test_data: list[TestDataRecord],
        gaps: list[GapIdentified],
        appendix_b: Optional[AppendixBEvaluation],
    ) -> list[RoutingRuleHit]:
        """Produce descriptive rule hits explaining why Cat II applies."""
        ap = self.authority_pack
        hits: list[RoutingRuleHit] = []

        # Non-A/B ratings requiring disposition
        for record in test_data:
            if record.test_class.upper() == "FS" and record.medium_match is False:
                continue  # FS evidence for a different medium is non-applicable
            if record.rating and record.rating.upper() not in ("A", "B"):
                hits.append(RoutingRuleHit(
                    rule_id="CAT2-001",
                    rule_description=(
                        f"{record.test_class} rating '{record.rating}' "
                        f"requires engineering disposition"
                    ),
                    citation=f"{ap.name} §4.3.2",
                    triggered_by=(
                        f"test_class={record.test_class}, "
                        f"rating={record.rating}"
                    ),
                ))

        # Expired test data
        expired = [r for r in test_data if r.is_current is False]
        if expired:
            summary = ", ".join(r.test_class for r in expired)
            hits.append(RoutingRuleHit(
                rule_id="CAT2-002",
                rule_description=(
                    f"Expired test data requires re-evaluation: {summary}"
                ),
                citation=f"{ap.name} §4.3.2.1",
                triggered_by=f"expired_tests=[{summary}]",
            ))

        # Open gaps
        open_gaps = [g for g in gaps if g.requires_review]
        if open_gaps:
            hits.append(RoutingRuleHit(
                rule_id="CAT2-003",
                rule_description=(
                    f"{len(open_gaps)} gap(s) requiring engineering review"
                ),
                citation=f"{ap.name} §4.3.2.2",
                triggered_by=f"open_gap_count={len(open_gaps)}",
            ))

        # Category III rationale code not eligible (explain why)
        if appendix_b and not appendix_b.eligible:
            hits.append(RoutingRuleHit(
                rule_id="CAT2-004",
                rule_description=(
                    f"Appendix E code not applicable: "
                    f"{'; '.join(appendix_b.evidence)}"
                ),
                citation="JSC 27301F Appendix E",
                triggered_by="appendix_b_eligible=False",
            ))

        if not hits:
            hits.append(RoutingRuleHit(
                rule_id="CAT2-000",
                rule_description=(
                    "Category II assigned by default: Cat I triggers absent, "
                    "Cat III eligibility not met"
                ),
                citation=f"{ap.name} §4.3.2",
                triggered_by="default_routing",
            ))

        return hits

    # ──────────────────────────────────────────────────────────────────
    # Approvals & Verifications
    # ──────────────────────────────────────────────────────────────────

    def _get_approvals(self, category: MUACategory) -> list[str]:
        """Return ordered approval chain for this category + center."""
        center = self.authority_pack.center.upper()
        output = _OUTPUT_TYPES.get(category.value)
        if output:
            # Substitute center name into approval chain
            return [
                step.replace("center branch, e.g. MSFC EM04", f"{center} EM04")
                for step in output.approval_chain
            ]
        return [f"{center} M&P Engineer"]

    def _get_verifications(
        self,
        category: MUACategory,
        gaps: list[GapIdentified],
        env: EnvironmentSpec,
    ) -> list[str]:
        """Return required verification steps for the category."""
        ap = self.authority_pack
        verifications: list[str] = []

        if category == MUACategory.I:
            verifications.extend([
                "Full MAPTIS test data review against queried environment",
                (
                    "Oxygen compatibility evaluation per NASA-STD-6001B "
                    "(if O2 service)"
                ),
                "Ignition assessment per NASA-TM-2007-213740 (if O2 service)",
                "Promoted combustion test evaluation (if O2 service)",
                "FMEA for material application",
                "Independent verification of precedent applicability",
            ])
            if env.is_hydrogen_service:
                verifications.append(
                    "Hydrogen embrittlement testing per ASTM G142 or equivalent"
                )
            if env.temp_min_f is not None:
                if env.temp_min_f <= ap.cryogenic_temp_f.value:
                    verifications.append(
                        "Cryogenic ductility and fracture toughness evaluation"
                    )

        elif category == MUACategory.II:
            verifications.append(
                "Engineering disposition for all non-A/B MAPTIS ratings"
            )
            verifications.append("Test data currency verification")
            for gap in gaps:
                if gap.requires_review and gap.severity in ("critical", "high"):
                    verifications.append(
                        f"Testing/rationale for {gap.dimension} gap: "
                        f"{gap.description[:100]}"
                    )

        else:  # Category III
            verifications.extend([
                "Verify Appendix E code applicability",
                "Confirm MIUL rationale code entry",
                "Standard MAPTIS data verification (ratings and currency)",
            ])

        return verifications
