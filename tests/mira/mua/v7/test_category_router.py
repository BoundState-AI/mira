"""Tests for MUA v7 NASA-STD-6016C category routing.

The category router assigns each material-use scenario to one of three
categories defined in NASA-STD-6016C:

  Category I  -- Oxygen-enriched, LOX, or hydrogen service.
  Category II -- Default category when not Cat I and evidence is
                 insufficient for the less restrictive Cat III.
  Category III -- All A-rated test data in a non-habitable volume
                  (with limited B-allowance for TVS).

Every routing decision must include a machine-readable rule_id and a
human-readable citation so that the audit trail is complete.
"""

import pytest

from mira.mua.v7.category_router import (
    AuthorityPack,
    CategoryRouter,
    RoutingRuleHit,
)
from mira.mua.v7.models import (
    CategoryRoutingResult,
    EnvironmentSpec,
    GapIdentified,
    MaterialResolution,
    MUACategory,
    ResolutionStatus,
    TestDataRecord,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def router():
    return CategoryRouter()


@pytest.fixture
def base_env():
    """Non-special environment: air at ambient conditions, non-habitable."""
    return EnvironmentSpec(
        medium="AIR",
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        location="non_habitable",
        application="General structure",
    )


@pytest.fixture
def enriched_o2_env():
    """Oxygen-enriched environment at 30 % O2."""
    return EnvironmentSpec(
        medium="GOX",
        o2_percent=30.0,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        location="non_habitable",
        application="Oxygen system component",
    )


@pytest.fixture
def lox_env():
    """Liquid oxygen service environment."""
    return EnvironmentSpec(
        medium="LOX",
        o2_percent=99.5,
        pressure_psia=50.0,
        temp_min_f=-297.0,
        temp_max_f=-280.0,
        location="non_habitable",
        application="LOX feed system",
    )


@pytest.fixture
def h2_env():
    """Gaseous hydrogen service environment."""
    return EnvironmentSpec(
        medium="GH2",
        o2_percent=0.0,
        pressure_psia=3000.0,
        temp_min_f=-40.0,
        temp_max_f=160.0,
        location="non_habitable",
        application="Hydrogen propellant line",
    )


@pytest.fixture
def high_pressure_o2_env():
    """High-pressure oxygen service environment (> 43.5 psia in GOX)."""
    return EnvironmentSpec(
        medium="GOX",
        o2_percent=25.0,
        pressure_psia=50.0,
        temp_min_f=60.0,
        temp_max_f=120.0,
        location="non_habitable",
        application="High-pressure O2 regulator",
    )


@pytest.fixture
def habitable_env():
    """Habitable volume environment with normal atmosphere."""
    return EnvironmentSpec(
        medium="AIR",
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=65.0,
        temp_max_f=80.0,
        location="habitable",
        application="Crew module interior panel",
    )


@pytest.fixture
def base_material():
    """A resolved non-special material (aluminum)."""
    return MaterialResolution(
        input_text="6061-T6",
        status=ResolutionStatus.RESOLVED,
        material_code="MAT-A96061",
        resolved_name="6061-T6 Aluminum",
        family="aluminum",
    )


@pytest.fixture
def titanium_material():
    """A titanium material -- prohibited in O2 service."""
    return MaterialResolution(
        input_text="Ti-6Al-4V",
        status=ResolutionStatus.RESOLVED,
        material_code="MAT-TI6AL4V",
        resolved_name="Ti-6Al-4V Titanium",
        family="titanium",
    )


@pytest.fixture
def all_a_ratings():
    """Full set of A-rated test results."""
    return [
        TestDataRecord(test_class="FLAMM", rating="A", is_current=True),
        TestDataRecord(test_class="ODOR", rating="A", is_current=True),
        TestDataRecord(test_class="OFFGAS", rating="A", is_current=True),
        TestDataRecord(test_class="TVS", rating="A", is_current=True),
    ]


@pytest.fixture
def mixed_ratings_with_b_tvs():
    """Ratings where TVS is B but everything else is A."""
    return [
        TestDataRecord(test_class="FLAMM", rating="A", is_current=True),
        TestDataRecord(test_class="ODOR", rating="A", is_current=True),
        TestDataRecord(test_class="OFFGAS", rating="A", is_current=True),
        TestDataRecord(test_class="TVS", rating="B", is_current=True),
    ]


@pytest.fixture
def non_a_rating():
    """Ratings containing a non-A/B flammability result (C rating).

    Ratings of C or below are not acceptable for Category III, which
    requires all ratings to be A or B.
    """
    return [
        TestDataRecord(test_class="FLAMM", rating="C", is_current=True),
        TestDataRecord(test_class="ODOR", rating="A", is_current=True),
        TestDataRecord(test_class="OFFGAS", rating="A", is_current=True),
        TestDataRecord(test_class="TVS", rating="A", is_current=True),
    ]


@pytest.fixture
def no_gaps():
    """No gaps identified."""
    return []


@pytest.fixture
def open_gap():
    """A single open gap requiring review."""
    return [
        GapIdentified(
            gap_id="GAP-001",
            dimension="temperature",
            description="No cryogenic test data available",
            severity="high",
            requires_review=True,
        )
    ]


# ---------------------------------------------------------------------------
# Category I triggers
# ---------------------------------------------------------------------------


class TestCategoryI:
    def test_category_i_enriched_o2(
        self, router, enriched_o2_env, all_a_ratings, no_gaps, base_material
    ):
        """Any environment with O2 >= 23.5 % must route to Category I,
        regardless of test ratings.  This is a hard safety gate per
        NASA-STD-6016C section 4.3.1."""
        result = router.route(enriched_o2_env, all_a_ratings, no_gaps, base_material)

        assert result.category == MUACategory.I

    def test_category_i_lox_service(
        self, router, lox_env, all_a_ratings, no_gaps, base_material
    ):
        """LOX service is always Category I regardless of other conditions."""
        result = router.route(lox_env, all_a_ratings, no_gaps, base_material)

        assert result.category == MUACategory.I

    def test_category_i_h2_service(
        self, router, h2_env, all_a_ratings, no_gaps, base_material
    ):
        """Hydrogen service (GH2 or LH2) is always Category I per
        NASA-STD-6016C section 4.3.1.3."""
        result = router.route(h2_env, all_a_ratings, no_gaps, base_material)

        assert result.category == MUACategory.I

    def test_category_i_high_pressure_o2(
        self, router, high_pressure_o2_env, all_a_ratings, no_gaps, base_material
    ):
        """O2 service with pressure > 43.5 psia must route to Category I
        for ignition and combustion risk."""
        result = router.route(
            high_pressure_o2_env, all_a_ratings, no_gaps, base_material
        )

        assert result.category == MUACategory.I

    def test_category_i_prohibited_family_titanium(
        self, router, enriched_o2_env, all_a_ratings, no_gaps, titanium_material
    ):
        """Titanium in oxygen service is a prohibited family and must
        route to Category I."""
        result = router.route(
            enriched_o2_env, all_a_ratings, no_gaps, titanium_material
        )

        assert result.category == MUACategory.I
        # Verify the prohibited-family rule fired
        rule_ids = [rb["rule_id"] for rb in result.routing_basis]
        assert "CAT1-005" in rule_ids


# ---------------------------------------------------------------------------
# Category III (least restrictive)
# ---------------------------------------------------------------------------


class TestCategoryIII:
    def test_category_iii_all_a_ratings(
        self, router, base_env, all_a_ratings, no_gaps, base_material
    ):
        """All A ratings + Appendix B code in a non-habitable, non-Cat-I
        environment should route to Category III (least restrictive).

        CORRECTED: Cat III requires Appendix B eligibility (per 6016C),
        not just all A ratings.  We supply engineer_notes triggering Code 104
        (sandwiched between non-flammable materials)."""
        result = router.route(
            base_env, all_a_ratings, no_gaps, base_material,
            engineer_notes="Material is sandwiched between aluminum panels",
            approved_appendix_b_codes=["104"],
        )

        assert result.category == MUACategory.III
        assert result.appendix_b_evaluation is not None
        assert result.appendix_b_evaluation["eligible"] is True
        assert result.appendix_b_evaluation["code"] == "104"
        assert result.output_type is not None
        assert result.output_type["output_format"] == "miul_rationale_code"

    def test_category_iii_b_tvs_nonhab(
        self, router, base_env, mixed_ratings_with_b_tvs, no_gaps, base_material
    ):
        """A TVS rating of B is permitted in non-habitable volumes and
        should still allow Category III routing when Appendix B applies.
        This exception is codified in NASA-STD-6016C Table 2, note (b).

        CORRECTED: Cat III requires Appendix B eligibility.  We supply
        engineer_notes triggering Code 104."""
        result = router.route(
            base_env, mixed_ratings_with_b_tvs, no_gaps, base_material,
            engineer_notes="Material is sandwiched between aluminum panels",
            approved_appendix_b_codes=["104"],
        )

        assert result.category == MUACategory.III

    def test_category_ii_when_appendix_b_not_plan_approved(
        self, router, base_env, all_a_ratings, no_gaps, base_material
    ):
        """Cat III must be blocked if Appendix B code is not approved in-plan."""
        result = router.route(
            base_env, all_a_ratings, no_gaps, base_material,
            engineer_notes="Material is sandwiched between aluminum panels",
            approved_appendix_b_codes=["105"],  # 104 detected, not approved
        )

        assert result.category == MUACategory.II
        rule_ids = [rb["rule_id"] for rb in result.routing_basis]
        assert "CAT3-PLAN-001" in rule_ids


# ---------------------------------------------------------------------------
# Category II (default / fallback)
# ---------------------------------------------------------------------------


class TestCategoryII:
    def test_category_ii_non_a_flammability(
        self, router, base_env, non_a_rating, no_gaps, base_material
    ):
        """A non-A flammability rating in a non-Cat-I environment must
        route to Category II (the default, more restrictive path)."""
        result = router.route(base_env, non_a_rating, no_gaps, base_material)

        assert result.category == MUACategory.II

    def test_category_ii_habitable_location(
        self, router, habitable_env, all_a_ratings, no_gaps, base_material
    ):
        """Even with all A ratings, a habitable location prevents Category III
        eligibility, resulting in Category II."""
        result = router.route(habitable_env, all_a_ratings, no_gaps, base_material)

        assert result.category == MUACategory.II

    def test_category_ii_open_gaps(
        self, router, base_env, all_a_ratings, open_gap, base_material
    ):
        """Open gaps requiring review prevent Category III eligibility,
        resulting in Category II even with all A ratings."""
        result = router.route(base_env, all_a_ratings, open_gap, base_material)

        assert result.category == MUACategory.II


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_routing_audit_trail(
        self, router, enriched_o2_env, all_a_ratings, no_gaps, base_material
    ):
        """Every routing decision must carry a rule_id (machine-readable)
        and a citation (human-readable reference to the standard) so that
        the decision is fully traceable.

        Citations may be full standard refs (NASA-STD-6016C §4.2.1.4) or
        section-only refs (§4.2.1.4) sourced from AuthorityPack thresholds."""
        result = router.route(enriched_o2_env, all_a_ratings, no_gaps, base_material)

        assert len(result.routing_basis) > 0
        for rule_hit in result.routing_basis:
            assert "rule_id" in rule_hit
            assert len(rule_hit["rule_id"]) > 0
            assert "citation" in rule_hit
            # Citation must reference a section (§) or the standard name
            citation = rule_hit["citation"]
            assert "§" in citation or "6016" in citation, (
                f"Citation '{citation}' lacks section reference or standard name"
            )

    def test_authority_pack_default(
        self, router, base_env, all_a_ratings, no_gaps, base_material
    ):
        """The default authority pack for routing must be NASA-STD-6016C
        (revision C).  Future revisions will add support for 6016D."""
        result = router.route(base_env, all_a_ratings, no_gaps, base_material)

        assert result.authority_pack == "NASA-STD-6016C"
