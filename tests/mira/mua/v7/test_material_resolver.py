"""Tests for MUA v7 material resolution.

The material resolver takes freeform material strings from engineers and
attempts to map them to canonical identifiers (e.g. MAPTIS material codes)
with a confidence classification: RESOLVED, FUZZY, or UNRESOLVED.  It must
distinguish genuinely different alloys, reject non-material text, and flag
process-sensitive materials (adhesives, coatings) that require cure-cycle
or application constraints in the MUA.
"""

import pytest

from mira.mua.v7.material_resolver import (
    resolve_material,
    ResolutionStatus,
    MaterialClass,
    MATERIAL_DATABASE,
    get_material_family,
    is_same_family,
)
from mira.mua.v7.models import MaterialResolution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def aluminum_6061_t6():
    """Canonical properties for Al 6061-T6."""
    return {
        "input": "6061-T6",
        "expected_code": "MAT-A00601",
        "family": "Al-6061",
    }


@pytest.fixture
def inconel_718():
    """Canonical properties for Inconel 718."""
    return {
        "input": "Inconel 718",
        "expected_code": "MAT-N00718",
        "family": "Ni-Inconel718",
    }


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------

class TestExactMatch:
    def test_exact_match(self, aluminum_6061_t6):
        """An unambiguous designation like '6061-T6' should resolve to its
        canonical MAPTIS material code with RESOLVED status."""
        result = resolve_material(aluminum_6061_t6["input"])

        assert result.status == ResolutionStatus.RESOLVED
        assert result.material_code == aluminum_6061_t6["expected_code"]
        assert result.family == "Al-6061"

    def test_case_insensitive(self):
        """Material lookup must be case-insensitive.  'inconel 718' (all
        lower-case) should resolve the same as 'Inconel 718'."""
        result = resolve_material("inconel 718")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.material_code == "MAT-N00718"


# ---------------------------------------------------------------------------
# Fuzzy / near match
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    def test_typo_near_match(self):
        """Common typos such as missing hyphens ('6061T6' instead of
        '6061-T6') should still resolve, though they may be classified
        as FUZZY rather than RESOLVED depending on normalization."""
        result = resolve_material("6061T6")

        assert result.status in (ResolutionStatus.RESOLVED, ResolutionStatus.FUZZY)
        assert result.material_code is not None
        assert "A006" in result.material_code  # MAT-A00601 or MAT-A00602

    def test_generic_material(self):
        """A bare family name like 'aluminum' cannot uniquely identify an
        alloy.  The resolver should return FUZZY with a non-empty
        suggestions list so the engineer can disambiguate, or UNRESOLVED
        if no match is close enough."""
        result = resolve_material("aluminum")

        assert result.status in (ResolutionStatus.FUZZY, ResolutionStatus.UNRESOLVED)
        if result.status == ResolutionStatus.FUZZY:
            assert len(result.suggestions) > 0
            # Suggestions are dicts with 'canonical_name', 'material_code',
            # 'similarity', 'db_key' keys
            suggestion_codes = [s["material_code"] for s in result.suggestions]
            assert all(code.startswith("MAT-") for code in suggestion_codes)


# ---------------------------------------------------------------------------
# Non-lumping: different alloys must NOT collapse
# ---------------------------------------------------------------------------

class TestNonLumping:
    def test_stainless_not_lumped(self):
        """316L and 430 are distinct stainless steel families (austenitic
        vs ferritic).  They must not be treated as interchangeable."""
        r316 = resolve_material("316L")
        r430 = resolve_material("430")

        assert r316.material_code != r430.material_code
        assert r316.family != r430.family  # SS-316 vs SS-430

    def test_aluminum_not_lumped(self):
        """2024-T4 and 2014-T6 are different aluminum alloys with different
        fracture toughness and corrosion behavior.  They must resolve to
        different material codes."""
        r2024 = resolve_material("2024-T4")
        r2014 = resolve_material("2014-T6")

        assert r2024.material_code != r2014.material_code
        assert r2024.family != r2014.family  # Al-2024 vs Al-2014


# ---------------------------------------------------------------------------
# Rejection of non-material text
# ---------------------------------------------------------------------------

class TestRejection:
    def test_non_material_rejection(self):
        """Drawing callouts like 'material per drawing note 7' are not
        actual material designations.  The resolver must return UNRESOLVED
        rather than guessing."""
        result = resolve_material("material per drawing note 7")

        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.material_code is None

    def test_garbage_input(self):
        """Completely meaningless input must be rejected cleanly."""
        result = resolve_material("asdf")

        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.material_code is None


# ---------------------------------------------------------------------------
# Process-sensitive flag
# ---------------------------------------------------------------------------

class TestProcessSensitivity:
    def test_process_sensitive_detection(self):
        """EA 9394 is an epoxy adhesive whose flammability depends on cure
        cycle parameters.  The resolver must flag it as process-sensitive
        so the downstream MUA includes cure constraints."""
        result = resolve_material("EA 9394")

        assert result.is_process_sensitive is True

    def test_metal_not_process_sensitive(self):
        """Wrought metals like Inconel 718 are not process-sensitive; their
        material properties are defined by the alloy and heat-treat
        condition, not by an application process."""
        result = resolve_material("Inconel 718")

        assert result.is_process_sensitive is False


# ---------------------------------------------------------------------------
# Family helpers
# ---------------------------------------------------------------------------

class TestFamilyHelpers:
    def test_get_material_family(self):
        """get_material_family should return the correct family string for
        a known MAPTIS material code."""
        family = get_material_family("MAT-A00210")
        assert family == "Al-2024"

    def test_get_material_family_unknown(self):
        """get_material_family should return None for an unknown code."""
        family = get_material_family("MAT-ZZZZZ")
        assert family is None

    def test_is_same_family_true(self):
        """2024-T3 and 2024-T4 are the same alloy family (Al-2024),
        differing only in temper.  is_same_family must return True."""
        assert is_same_family("MAT-A00210", "MAT-A00211") is True

    def test_is_same_family_false(self):
        """2024-T3 and 2219-T87 are different aluminum alloys despite both
        being 2xxx series.  The v6 regex grouped them together; v7 must
        correctly distinguish them."""
        assert is_same_family("MAT-A00210", "MAT-A00220") is False

    def test_stainless_not_same_family(self):
        """316L and 430 must NOT be in the same family.  v6 lumped all
        3xx/4xx stainless together; v7 corrects this."""
        assert is_same_family("MAT-S00317", "MAT-S00430") is False


# ---------------------------------------------------------------------------
# Alias and spec resolution
# ---------------------------------------------------------------------------

class TestAliasResolution:
    def test_common_alias(self):
        """'SS 316L' is a common alias for stainless steel 316L and should
        resolve to the same material code as '316L'."""
        direct = resolve_material("316L")
        alias = resolve_material("SS 316L")

        assert direct.material_code == alias.material_code

    def test_ams_spec(self):
        """AMS specification numbers should resolve to the correct material.
        AMS 5596 designates Inconel 718."""
        result = resolve_material("AMS 5596")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.material_code == "MAT-N00718"

    def test_uns_spec(self):
        """UNS designations should resolve.  UNS N07718 is Inconel 718."""
        result = resolve_material("UNS N07718")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.material_code == "MAT-N00718"


# ---------------------------------------------------------------------------
# Material class
# ---------------------------------------------------------------------------

class TestMaterialClass:
    def test_metal_class(self):
        """Aluminum alloys should be classified as METAL."""
        result = resolve_material("6061-T6")
        assert result.material_class == MaterialClass.METAL

    def test_adhesive_class(self):
        """EA 9394 is an adhesive and should be classified accordingly."""
        result = resolve_material("EA 9394")
        assert result.material_class == MaterialClass.ADHESIVE

    def test_composite_class(self):
        """IM7/8552 is a carbon fiber composite."""
        result = resolve_material("IM7/8552")
        assert result.material_class == MaterialClass.COMPOSITE


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_input(self):
        """Empty string should return UNRESOLVED cleanly."""
        result = resolve_material("")
        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.material_code is None

    def test_whitespace_only(self):
        """Whitespace-only input should return UNRESOLVED."""
        result = resolve_material("   ")
        assert result.status == ResolutionStatus.UNRESOLVED

    def test_tbd_rejection(self):
        """'TBD' is a placeholder, not a material designation."""
        result = resolve_material("TBD")
        assert result.status == ResolutionStatus.UNRESOLVED

    def test_na_rejection(self):
        """'N/A' is not a material designation."""
        result = resolve_material("N/A")
        assert result.status == ResolutionStatus.UNRESOLVED

    def test_result_preserves_input_text(self):
        """The result should echo back the original input text."""
        result = resolve_material("Inconel 718")
        assert result.input_text == "Inconel 718"
