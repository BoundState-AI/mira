"""NASA-STD-6016C Category Routing with AuthorityPack Interface.

Routes MUA submissions to Category I, II, or III per NASA-STD-6016C,
producing a deterministic, fully-traceable audit trail.

Routing hierarchy (most restrictive wins):

    Category I  -- LOX/GOX service, enriched O2 (>= 23.5 %), high-pressure
                   O2 service (> 300 kPa / ~43.5 psia), hydrogen service
                   (embrittlement risk), prohibited material-family gates
                   (e.g. titanium in O2).
    Category II -- Default bucket.  Materials with non-A ratings needing
                   engineering disposition, conditional approvals, or
                   expired test data requiring re-evaluation.
    Category III -- All MAPTIS ratings A or B, non-habitable location,
                    no enriched O2, no open gaps requiring testing.
                    TVS rating of B is acceptable in non-habitable zones.

Design notes
------------
- Every rule that fires produces a :class:`RoutingRuleHit` with a stable
  ``rule_id``, a human-readable description, and a citation back to the
  governing standard section.
- The :class:`AuthorityPack` makes the standard/center axis explicit so
  the router can later be extended to ECSS-Q-ST-70 (ESA) or JAXA-QTS-2060
  without forking logic.
- The router is deterministic: given the same inputs it always produces
  the same category and the same ordered list of rule hits.
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Pressure threshold: 300 kPa expressed in psia (the unit used by
# EnvironmentSpec).  300 kPa = 43.5113 psia; we use a rounded constant
# and document the origin.
# ---------------------------------------------------------------------------
_O2_HIGH_PRESSURE_PSIA = 43.5  # 300 kPa per NASA-STD-6016C Table 4-1

# Oxygen-adjacent media considered "O2 service".
_O2_SERVICE_MEDIA = frozenset({"GOX", "LOX", "OXYGEN", "O2"})

# Material families prohibited in oxygen service.
_PROHIBITED_FAMILIES_IN_O2: dict[str, str] = {
    "titanium": "Titanium alloys are ignition-sensitive in enriched O2 service",
    "magnesium": "Magnesium alloys are highly flammable in enriched O2 service",
}

# Ratings that satisfy the "all A-or-B" criterion for Category III.
_ACCEPTABLE_RATINGS_CAT3 = frozenset({"A", "B"})

# TVS is explicitly allowed as B in non-habitable per NASA-STD-6016C.
_TVS_TEST_CLASS = "TVS"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RoutingRuleHit(BaseModel):
    """A single routing rule that fired during category determination.

    Every hit carries enough context to reconstruct the routing decision
    during audit or appeal.
    """

    rule_id: str
    rule_description: str
    citation: str  # e.g. "NASA-STD-6016C SS4.3.2"
    triggered_by: str  # What condition triggered this rule


class AuthorityPack(BaseModel):
    """Standards authority pack -- parameterizes routing by center/standard.

    The default pack targets MSFC under NASA-STD-6016C Rev. 3.
    Future packs (e.g. ``name="ECSS-Q-ST-70"``, ``center="ESA"``) can
    be created to re-use the routing architecture for non-NASA standards.
    """

    name: str = "NASA-STD-6016C"
    version: str = "Rev. 3"
    center: str = "MSFC"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class CategoryRouter:
    """Routes an MUA to Category I / II / III per NASA-STD-6016C.

    Usage::

        router = CategoryRouter()
        result = router.route(environment, test_records, gaps, material_resolution)
        print(result.category)       # MUACategory.II
        print(result.routing_basis)  # [{"rule_id": ..., ...}, ...]

    The router checks Category I triggers first (most restrictive), then
    evaluates Category III eligibility.  If neither applies the MUA falls
    into Category II (the default bucket).
    """

    def __init__(self, authority_pack: Optional[AuthorityPack] = None) -> None:
        self.authority_pack = authority_pack or AuthorityPack()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        environment: EnvironmentSpec,
        test_data: list[TestDataRecord],
        gaps: list[GapIdentified],
        material_resolution: MaterialResolution,
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

        Returns
        -------
        CategoryRoutingResult
            Contains the assigned category, ordered list of rule hits
            (``routing_basis``), required approvals, and required
            verifications.
        """
        rule_hits: list[RoutingRuleHit] = []

        # --- Phase 1: Check Category I triggers (most restrictive) ------
        cat1_hits = self._check_category_i(
            environment, test_data, material_resolution,
        )
        rule_hits.extend(cat1_hits)

        if cat1_hits:
            category = MUACategory.I
        else:
            # --- Phase 2: Evaluate Category III eligibility --------------
            cat3_eligible, cat3_hits = self._check_category_iii(
                environment, test_data, gaps,
            )
            rule_hits.extend(cat3_hits)

            if cat3_eligible:
                category = MUACategory.III
            else:
                # --- Phase 3: Default to Category II ---------------------
                cat2_hits = self._check_category_ii(
                    test_data, gaps,
                )
                rule_hits.extend(cat2_hits)
                category = MUACategory.II

        # --- Build result ------------------------------------------------
        approvals = get_required_approvals(category, self.authority_pack.center)
        verifications = get_required_verifications(category, gaps)

        return CategoryRoutingResult(
            category=category,
            routing_basis=[hit.model_dump() for hit in rule_hits],
            required_approvals=approvals,
            required_verifications=verifications,
            authority_pack=self.authority_pack.name,
            authority_pack_version=self.authority_pack.version,
        )

    # ------------------------------------------------------------------
    # Category I checks
    # ------------------------------------------------------------------

    def _check_category_i(
        self,
        env: EnvironmentSpec,
        test_data: list[TestDataRecord],
        mat: MaterialResolution,
    ) -> list[RoutingRuleHit]:
        """Return all Category I rule hits (may be empty)."""
        hits: list[RoutingRuleHit] = []

        medium_upper = env.medium.upper()
        is_o2_service = medium_upper in _O2_SERVICE_MEDIA

        # Rule CAT1-001: LOX / GOX service
        if medium_upper in ("LOX", "GOX"):
            hits.append(RoutingRuleHit(
                rule_id="CAT1-001",
                rule_description=(
                    "Material is used in liquid or gaseous oxygen service, "
                    "requiring Category I assessment"
                ),
                citation="NASA-STD-6016C \u00a74.3.1",
                triggered_by=f"medium={env.medium}",
            ))

        # Rule CAT1-002: Enriched oxygen (O2 >= 23.5 %)
        if env.is_enriched_o2:
            hits.append(RoutingRuleHit(
                rule_id="CAT1-002",
                rule_description=(
                    "Oxygen concentration is at or above the enriched "
                    "threshold of 23.5 %, requiring Category I assessment"
                ),
                citation="NASA-STD-6016C \u00a74.3.1.1",
                triggered_by=f"o2_percent={env.o2_percent}%",
            ))

        # Rule CAT1-003: High-pressure O2 service (> 300 kPa / ~43.5 psia)
        if is_o2_service and env.pressure_psia > _O2_HIGH_PRESSURE_PSIA:
            hits.append(RoutingRuleHit(
                rule_id="CAT1-003",
                rule_description=(
                    "Pressure exceeds 300 kPa (~43.5 psia) in oxygen "
                    "service, requiring Category I assessment for ignition "
                    "and combustion risk"
                ),
                citation="NASA-STD-6016C \u00a74.3.1.2",
                triggered_by=(
                    f"pressure_psia={env.pressure_psia}, "
                    f"medium={env.medium}"
                ),
            ))

        # Rule CAT1-004: Hydrogen service (embrittlement)
        if env.is_hydrogen_service:
            hits.append(RoutingRuleHit(
                rule_id="CAT1-004",
                rule_description=(
                    "Material is used in hydrogen service; hydrogen "
                    "embrittlement assessment is required under Category I"
                ),
                citation="NASA-STD-6016C \u00a74.3.1.3",
                triggered_by=f"medium={env.medium}",
            ))

        # Rule CAT1-005: Prohibited material family in O2 service
        if is_o2_service or env.is_enriched_o2:
            family_lower = (mat.family or "").lower()
            if family_lower in _PROHIBITED_FAMILIES_IN_O2:
                reason = _PROHIBITED_FAMILIES_IN_O2[family_lower]
                hits.append(RoutingRuleHit(
                    rule_id="CAT1-005",
                    rule_description=(
                        f"Prohibited material family '{mat.family}' in "
                        f"oxygen service: {reason}"
                    ),
                    citation="NASA-STD-6016C \u00a74.3.1.4",
                    triggered_by=(
                        f"family={mat.family}, "
                        f"o2_percent={env.o2_percent}%, "
                        f"medium={env.medium}"
                    ),
                ))

        return hits

    # ------------------------------------------------------------------
    # Category III checks
    # ------------------------------------------------------------------

    def _check_category_iii(
        self,
        env: EnvironmentSpec,
        test_data: list[TestDataRecord],
        gaps: list[GapIdentified],
    ) -> tuple[bool, list[RoutingRuleHit]]:
        """Evaluate Category III eligibility.

        Returns
        -------
        tuple[bool, list[RoutingRuleHit]]
            ``(eligible, rule_hits)`` -- ``eligible`` is True only when
            *all* Category III criteria are satisfied.
        """
        hits: list[RoutingRuleHit] = []
        disqualifiers: list[RoutingRuleHit] = []

        # Criterion CAT3-001: Non-habitable location
        is_non_habitable = env.location.lower() in (
            "non_habitable", "non-habitable", "external",
        )
        if is_non_habitable:
            hits.append(RoutingRuleHit(
                rule_id="CAT3-001",
                rule_description="Location is non-habitable (Cat III eligible)",
                citation="NASA-STD-6016C \u00a74.3.3 criterion (a)",
                triggered_by=f"location={env.location}",
            ))
        else:
            disqualifiers.append(RoutingRuleHit(
                rule_id="CAT3-001-FAIL",
                rule_description=(
                    "Location is habitable; Cat III requires non-habitable"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (a)",
                triggered_by=f"location={env.location}",
            ))

        # Criterion CAT3-002: No enriched O2
        if not env.is_enriched_o2:
            hits.append(RoutingRuleHit(
                rule_id="CAT3-002",
                rule_description=(
                    "Oxygen is below 23.5 % enrichment (Cat III eligible)"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (b)",
                triggered_by=f"o2_percent={env.o2_percent}%",
            ))
        else:
            disqualifiers.append(RoutingRuleHit(
                rule_id="CAT3-002-FAIL",
                rule_description=(
                    "Enriched O2 present; Cat III requires "
                    "non-enriched atmosphere"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (b)",
                triggered_by=f"o2_percent={env.o2_percent}%",
            ))

        # Criterion CAT3-003: All MAPTIS ratings A or B
        # (TVS rating of B in non-habitable is explicitly acceptable)
        non_qualifying_ratings: list[str] = []
        for record in test_data:
            if record.rating is None:
                non_qualifying_ratings.append(
                    f"{record.test_class}:rating=None"
                )
                continue
            rating_upper = record.rating.upper()
            if rating_upper not in _ACCEPTABLE_RATINGS_CAT3:
                # TVS-B exception in non-habitable
                if (
                    record.test_class.upper() == _TVS_TEST_CLASS
                    and rating_upper == "B"
                    and is_non_habitable
                ):
                    hits.append(RoutingRuleHit(
                        rule_id="CAT3-003-TVS-EXCEPTION",
                        rule_description=(
                            "TVS rating B accepted in non-habitable "
                            "location per standard exception"
                        ),
                        citation="NASA-STD-6016C \u00a74.3.3 Note 1",
                        triggered_by=(
                            f"test_class=TVS, rating=B, "
                            f"location={env.location}"
                        ),
                    ))
                    continue
                non_qualifying_ratings.append(
                    f"{record.test_class}:rating={record.rating}"
                )

        if not non_qualifying_ratings and test_data:
            hits.append(RoutingRuleHit(
                rule_id="CAT3-003",
                rule_description=(
                    "All MAPTIS ratings are A or B (Cat III eligible)"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (c)",
                triggered_by="all_ratings_acceptable=True",
            ))
        elif not test_data:
            disqualifiers.append(RoutingRuleHit(
                rule_id="CAT3-003-FAIL",
                rule_description=(
                    "No test data available; Cat III requires all "
                    "ratings A or B"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (c)",
                triggered_by="test_data_count=0",
            ))
        else:
            disqualifiers.append(RoutingRuleHit(
                rule_id="CAT3-003-FAIL",
                rule_description=(
                    f"Non-qualifying ratings found: "
                    f"{', '.join(non_qualifying_ratings)}; "
                    f"Cat III requires all A or B"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (c)",
                triggered_by=(
                    f"non_qualifying={non_qualifying_ratings}"
                ),
            ))

        # Criterion CAT3-004: No gaps requiring testing
        open_gaps = [g for g in gaps if g.requires_review]
        if not open_gaps:
            hits.append(RoutingRuleHit(
                rule_id="CAT3-004",
                rule_description=(
                    "No open gaps requiring testing (Cat III eligible)"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (d)",
                triggered_by="open_gap_count=0",
            ))
        else:
            gap_summary = ", ".join(g.gap_id for g in open_gaps)
            disqualifiers.append(RoutingRuleHit(
                rule_id="CAT3-004-FAIL",
                rule_description=(
                    f"{len(open_gaps)} gap(s) require testing; "
                    f"Cat III requires no open gaps"
                ),
                citation="NASA-STD-6016C \u00a74.3.3 criterion (d)",
                triggered_by=f"open_gaps=[{gap_summary}]",
            ))

        # Combine: eligible only if zero disqualifiers
        eligible = len(disqualifiers) == 0
        all_hits = hits + disqualifiers
        return eligible, all_hits

    # ------------------------------------------------------------------
    # Category II annotations
    # ------------------------------------------------------------------

    def _check_category_ii(
        self,
        test_data: list[TestDataRecord],
        gaps: list[GapIdentified],
    ) -> list[RoutingRuleHit]:
        """Produce descriptive rule hits explaining why Cat II applies.

        Category II is the default; these hits document the specific
        conditions that placed the MUA outside Cat III without
        triggering Cat I.
        """
        hits: list[RoutingRuleHit] = []

        # Annotate non-A ratings that require engineering disposition
        for record in test_data:
            if record.rating and record.rating.upper() not in ("A",):
                hits.append(RoutingRuleHit(
                    rule_id="CAT2-001",
                    rule_description=(
                        f"{record.test_class} rating '{record.rating}' is "
                        f"not A; engineering disposition required"
                    ),
                    citation="NASA-STD-6016C \u00a74.3.2",
                    triggered_by=(
                        f"test_class={record.test_class}, "
                        f"rating={record.rating}"
                    ),
                ))

        # Annotate expired test data
        expired = [r for r in test_data if r.is_current is False]
        if expired:
            test_summary = ", ".join(
                r.test_class + (f" (#{r.test_number})" if r.test_number else "")
                for r in expired
            )
            hits.append(RoutingRuleHit(
                rule_id="CAT2-002",
                rule_description=(
                    f"Expired test data requires re-evaluation: "
                    f"{test_summary}"
                ),
                citation="NASA-STD-6016C \u00a74.3.2.1",
                triggered_by=f"expired_tests=[{test_summary}]",
            ))

        # Annotate open gaps
        open_gaps = [g for g in gaps if g.requires_review]
        if open_gaps:
            hits.append(RoutingRuleHit(
                rule_id="CAT2-003",
                rule_description=(
                    f"{len(open_gaps)} gap(s) identified requiring "
                    f"engineering review or testing"
                ),
                citation="NASA-STD-6016C \u00a74.3.2.2",
                triggered_by=(
                    f"open_gaps=[{', '.join(g.gap_id for g in open_gaps)}]"
                ),
            ))

        # If no specific Cat II drivers, add a default explanation
        if not hits:
            hits.append(RoutingRuleHit(
                rule_id="CAT2-000",
                rule_description=(
                    "Category II assigned by default: Category I triggers "
                    "absent, Category III eligibility criteria not fully met"
                ),
                citation="NASA-STD-6016C \u00a74.3.2",
                triggered_by="default_routing",
            ))

        return hits


# ---------------------------------------------------------------------------
# Approval & Verification helpers
# ---------------------------------------------------------------------------


def get_required_approvals(category: MUACategory, center: str) -> list[str]:
    """Return the ordered list of required approvals for a given category.

    Parameters
    ----------
    category:
        The assigned MUA category.
    center:
        The NASA center code (e.g. ``"MSFC"``, ``"JSC"``).

    Returns
    -------
    list[str]
        Human-readable approval authority titles, ordered from first
        to last required signatory.
    """
    center_upper = center.upper()

    if category == MUACategory.I:
        approvals = [
            f"{center_upper} Materials & Processes (M&P) Branch Chief",
            f"{center_upper} M&P Lead Engineer",
            "Program/Project Chief Engineer",
            "NASA Safety Review Panel (SRP)",
            "Oxygen Compatibility Assessment Board (OCAB)" if center_upper == "MSFC"
            else f"{center_upper} Oxygen Safety Representative",
        ]
    elif category == MUACategory.II:
        approvals = [
            f"{center_upper} M&P Engineer (assigned)",
            f"{center_upper} M&P Branch representative",
            "Project Lead Engineer",
        ]
    else:
        # Category III
        approvals = [
            f"{center_upper} M&P Engineer (assigned)",
        ]

    return approvals


def get_required_verifications(
    category: MUACategory,
    gaps: list[GapIdentified],
) -> list[str]:
    """Return required verification steps for the assigned category.

    Parameters
    ----------
    category:
        The assigned MUA category.
    gaps:
        Gaps identified during the investigation step.  Gap severity
        and dimension influence the verification requirements for
        Category I and II MUAs.

    Returns
    -------
    list[str]
        Ordered list of verification actions the engineer must complete
        or confirm before the MUA can be finalized.
    """
    verifications: list[str] = []

    if category == MUACategory.I:
        verifications.extend([
            "Full MAPTIS test data review against queried environment",
            "Ignition compatibility assessment per NASA-TM-2007-213740",
            "Promoted combustion test evaluation (if O2 service)",
            "Failure Mode and Effects Analysis (FMEA) for material application",
            "Independent verification of precedent applicability",
            "Pressure system material compatibility review",
        ])
        # Add hydrogen-specific verifications if any gap dimension is
        # hydrogen-related (the router cannot see the environment directly
        # here, so we infer from gap dimensions).
        h2_gaps = [g for g in gaps if "hydrogen" in g.dimension.lower()]
        if h2_gaps:
            verifications.append(
                "Hydrogen embrittlement susceptibility testing per "
                "ASTM G142 or equivalent"
            )

    elif category == MUACategory.II:
        verifications.append(
            "Engineering disposition for all non-A MAPTIS ratings"
        )
        verifications.append("Test data currency verification")

        # Gap-specific verifications
        for gap in gaps:
            if not gap.requires_review:
                continue
            if gap.severity in ("critical", "high"):
                verifications.append(
                    f"Testing required for {gap.dimension} gap "
                    f"({gap.gap_id}): {gap.description}"
                )
            else:
                verifications.append(
                    f"Engineering rationale required for {gap.dimension} "
                    f"gap ({gap.gap_id}): {gap.description}"
                )

    else:
        # Category III
        verifications.extend([
            "Standard MAPTIS data verification (ratings and currency)",
            "Confirmation that environment matches tested envelope",
        ])

    return verifications
