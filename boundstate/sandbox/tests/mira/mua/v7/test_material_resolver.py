"""Tests for MUA v7 material resolution.

The material resolver takes freeform material strings from engineers and
attempts to map them to canonical identifiers (e.g. UNS numbers) with a
confidence classification: RESOLVED, FUZZY, or UNRESOLVED.  It must
distinguish genuinely different alloys, reject non-material text, and flag
process-sensitive materials (adhesives, coatings) that require cure-cycle
or application constraints in the MUA.
"""

import pytest

from mira.mua.v7.material_resolver import (
    MaterialResolver,
    ResolutionStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def resolver():
    """Return a MaterialResolver backed by the default material catalog."""
    return MaterialResolver()


@pytest.fixture
def aluminum_6061_t6():
    """Canonical properties for Al 6061-T6."""
    return {
        "input": "6061-T6",
        "expected_uns": "MAT-A96061",
        "family": "aluminum",
        "temper": "T6",
    }


@pytest.fixture
def inconel_718():
    """Canonical properties for Inconel 718."""
    return {
        "input": "Inconel 718",
        "expected_uns_prefix": "MAT-N07718",
        "family": "nickel",
    }


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------

class TestExactMatch:
    def test_exact_match(self, resolver, aluminum_6061_t6):
        """An unambiguous designation like '6061-T6' should resolve to its
        canonical UNS identifier with RESOLVED status."""
        result = resolver.resolve(aluminum_6061_t6["input"])

        assert result.status == ResolutionStatus.RESOLVED
        assert result.canonical_id == aluminum_6061_t6["expected_uns"]
        assert result.family == "aluminum"

    def test_case_insensitive(self, resolver):
        """Material lookup must be case-insensitive.  'inconel 718' (all
        lower-case) should resolve the same as 'Inconel 718'."""
        result = resolver.resolve("inconel 718")

        assert result.status == ResolutionStatus.RESOLVED
        assert "N07718" in result.canonical_id


# ---------------------------------------------------------------------------
# Fuzzy / near match
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    def test_fuzzy_match(self, resolver):
        """Common typos such as missing hyphens ('6061T6' instead of
        '6061-T6') should still resolve, though they may be classified
        as FUZZY rather than RESOLVED."""
        result = resolver.resolve("6061T6")

        assert result.status in (ResolutionStatus.RESOLVED, ResolutionStatus.FUZZY)
        assert result.canonical_id is not None
        assert "A96061" in result.canonical_id

    def test_generic_material(self, resolver):
        """A bare family name like 'aluminum' cannot uniquely identify an
        alloy.  The resolver should return FUZZY with a non-empty
        suggestions list so the engineer can disambiguate."""
        result = resolver.resolve("aluminum")

        assert result.status == ResolutionStatus.FUZZY
        assert len(result.suggestions) > 0
        # Suggestions should include common aluminum alloys
        suggestion_ids = [s.canonical_id for s in result.suggestions]
        assert any("A96061" in sid for sid in suggestion_ids)


# ---------------------------------------------------------------------------
# Non-lumping: different alloys must NOT collapse
# ---------------------------------------------------------------------------

class TestNonLumping:
    def test_stainless_not_lumped(self, resolver):
        """316L and 430 are distinct stainless steel families (austenitic
        vs ferritic).  They must not be treated as interchangeable."""
        r316 = resolver.resolve("316L")
        r430 = resolver.resolve("430")

        assert r316.canonical_id != r430.canonical_id

    def test_aluminum_not_lumped(self, resolver):
        """2024-T4 and 2014 are different aluminum alloys with different
        fracture toughness and corrosion behavior.  They must resolve to
        different canonical IDs."""
        r2024 = resolver.resolve("2024-T4")
        r2014 = resolver.resolve("2014")

        assert r2024.canonical_id != r2014.canonical_id


# ---------------------------------------------------------------------------
# Rejection of non-material text
# ---------------------------------------------------------------------------

class TestRejection:
    def test_non_material_rejection(self, resolver):
        """Drawing callouts like 'material per drawing note 7' are not
        actual material designations.  The resolver must return UNRESOLVED
        rather than guessing."""
        result = resolver.resolve("material per drawing note 7")

        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.canonical_id is None

    def test_garbage_input(self, resolver):
        """Completely meaningless input must be rejected cleanly."""
        result = resolver.resolve("asdf")

        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.canonical_id is None


# ---------------------------------------------------------------------------
# Process-sensitive flag
# ---------------------------------------------------------------------------

class TestProcessSensitivity:
    def test_process_sensitive_detection(self, resolver):
        """EA 9394 is an epoxy adhesive whose flammability depends on cure
        cycle parameters.  The resolver must flag it as process-sensitive
        so the downstream MUA includes cure constraints."""
        result = resolver.resolve("EA 9394")

        assert result.is_process_sensitive is True

    def test_metal_not_process_sensitive(self, resolver):
        """Wrought metals like Inconel 718 are not process-sensitive; their
        material properties are defined by the alloy and heat-treat
        condition, not by an application process."""
        result = resolver.resolve("Inconel 718")

        assert result.is_process_sensitive is False
