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
    CategoryRouter,
    Category,
    RoutingInput,
    EnvironmentDescriptor,
    TestRating,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def router():
    return CategoryRouter()


@pytest.fixture
def base_env():
    """Non-special environment: air at ambient conditions."""
    return EnvironmentDescriptor(
        medium="AIR",
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        is_habitable=False,
    )


@pytest.fixture
def enriched_o2_env():
    """Oxygen-enriched environment at 30 % O2."""
    return EnvironmentDescriptor(
        medium="GOX",
        o2_percent=30.0,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        is_habitable=False,
    )


@pytest.fixture
def lox_env():
    """Liquid oxygen service environment."""
    return EnvironmentDescriptor(
        medium="LOX",
        o2_percent=99.5,
        pressure_psia=50.0,
        temp_min_f=-297.0,
        temp_max_f=-280.0,
        is_habitable=False,
    )


@pytest.fixture
def h2_env():
    """Gaseous hydrogen service environment."""
    return EnvironmentDescriptor(
        medium="GH2",
        o2_percent=0.0,
        pressure_psia=3000.0,
        temp_min_f=-40.0,
        temp_max_f=160.0,
        is_habitable=False,
    )


@pytest.fixture
def all_a_ratings():
    """Full set of A-rated test results."""
    return [
        TestRating(test_type="FLAMM", rating="A"),
        TestRating(test_type="ODOR", rating="A"),
        TestRating(test_type="OFFGAS", rating="A"),
        TestRating(test_type="TVS", rating="A"),
    ]


@pytest.fixture
def mixed_ratings_with_b_tvs():
    """Ratings where TVS is B but everything else is A."""
    return [
        TestRating(test_type="FLAMM", rating="A"),
        TestRating(test_type="ODOR", rating="A"),
        TestRating(test_type="OFFGAS", rating="A"),
        TestRating(test_type="TVS", rating="B"),
    ]


@pytest.fixture
def non_a_rating():
    """Ratings containing a non-A flammability result."""
    return [
        TestRating(test_type="FLAMM", rating="B"),
        TestRating(test_type="ODOR", rating="A"),
        TestRating(test_type="OFFGAS", rating="A"),
        TestRating(test_type="TVS", rating="A"),
    ]


@pytest.fixture
def expired_ratings():
    """Ratings where all test data has expired."""
    return [
        TestRating(test_type="FLAMM", rating="A", expired=True),
        TestRating(test_type="ODOR", rating="A", expired=True),
        TestRating(test_type="OFFGAS", rating="A", expired=True),
        TestRating(test_type="TVS", rating="A", expired=True),
    ]


# ---------------------------------------------------------------------------
# Category I triggers
# ---------------------------------------------------------------------------

class TestCategoryI:
    def test_category_i_enriched_o2(self, router, enriched_o2_env, all_a_ratings):
        """Any environment with O2 >= 23.5 % must route to Category I,
        regardless of test ratings.  This is a hard safety gate per
        NASA-STD-6016C section 4.2.1."""
        inp = RoutingInput(
            material="6061-T6",
            environment=enriched_o2_env,
            ratings=all_a_ratings,
        )
        result = router.route(inp)

        assert result.category == Category.I

    def test_category_i_lox_service(self, router, lox_env, all_a_ratings):
        """LOX service is always Category I regardless of other conditions."""
        inp = RoutingInput(
            material="Monel 400",
            environment=lox_env,
            ratings=all_a_ratings,
        )
        result = router.route(inp)

        assert result.category == Category.I

    def test_category_i_h2_service(self, router, h2_env, all_a_ratings):
        """Hydrogen service (GH2 or LH2) is always Category I per
        NASA-STD-6016C section 4.2.1."""
        inp = RoutingInput(
            material="316L",
            environment=h2_env,
            ratings=all_a_ratings,
        )
        result = router.route(inp)

        assert result.category == Category.I


# ---------------------------------------------------------------------------
# Category III (least restrictive)
# ---------------------------------------------------------------------------

class TestCategoryIII:
    def test_category_iii_all_a_ratings(self, router, base_env, all_a_ratings):
        """All A ratings in a non-habitable, non-Cat-I environment should
        route to Category III (least restrictive)."""
        inp = RoutingInput(
            material="6061-T6",
            environment=base_env,
            ratings=all_a_ratings,
        )
        result = router.route(inp)

        assert result.category == Category.III

    def test_category_iii_b_tvs_nonhab(
        self, router, base_env, mixed_ratings_with_b_tvs
    ):
        """A TVS rating of B is permitted in non-habitable volumes and
        should still allow Category III routing.  This exception is
        codified in NASA-STD-6016C Table 2, note (b)."""
        inp = RoutingInput(
            material="6061-T6",
            environment=base_env,
            ratings=mixed_ratings_with_b_tvs,
        )
        result = router.route(inp)

        assert result.category == Category.III


# ---------------------------------------------------------------------------
# Category II (default / fallback)
# ---------------------------------------------------------------------------

class TestCategoryII:
    def test_category_ii_default(self, router, base_env, non_a_rating):
        """A non-A flammability rating in a non-Cat-I environment must
        route to Category II (the default, more restrictive path)."""
        inp = RoutingInput(
            material="Nomex",
            environment=base_env,
            ratings=non_a_rating,
        )
        result = router.route(inp)

        assert result.category == Category.II

    def test_category_ii_expired_data(self, router, base_env, expired_ratings):
        """Even if all ratings are A, expired test data must bump the
        routing to Category II because the currency of the data cannot
        be guaranteed."""
        inp = RoutingInput(
            material="6061-T6",
            environment=base_env,
            ratings=expired_ratings,
        )
        result = router.route(inp)

        assert result.category == Category.II


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:
    def test_routing_audit_trail(self, router, enriched_o2_env, all_a_ratings):
        """Every routing decision must carry a rule_id (machine-readable)
        and a citation (human-readable reference to the standard) so that
        the decision is fully traceable."""
        inp = RoutingInput(
            material="6061-T6",
            environment=enriched_o2_env,
            ratings=all_a_ratings,
        )
        result = router.route(inp)

        assert result.rule_id is not None
        assert len(result.rule_id) > 0
        assert result.citation is not None
        assert "6016" in result.citation  # Must reference the standard

    def test_authority_pack_default(self, router, base_env, all_a_ratings):
        """The default authority pack for routing must be NASA-STD-6016C
        (revision C).  Future revisions will add support for 6016D."""
        inp = RoutingInput(
            material="6061-T6",
            environment=base_env,
            ratings=all_a_ratings,
        )
        result = router.route(inp)

        assert result.applied_standard == "NASA-STD-6016C"
