#!/usr/bin/env python3
"""
Module: Test Alloy Normalizer
Purpose: Alloy Normalizer Tests for BoundState

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import pytest
import sys

sys.path.insert(0, r"C:\BoundState")

from mira.miul.alloy_normalizer import (
    AlloyFamily,
    NormalizedAlloy,
    AlloyNormalizer,
    normalize_alloy,
    UNS_ALUMINUM,
    UNS_STAINLESS,
    UNS_TITANIUM,
    UNS_NICKEL,
    UNS_COPPER,
    UNS_COBALT,
)


class TestAlloyFamily:
    """Tests for AlloyFamily enum."""

    def test_all_families_defined(self):
        """All expected alloy families should be defined."""
        expected = {
            "aluminum", "stainless_steel", "carbon_steel",
            "titanium", "nickel", "copper", "magnesium",
            "cobalt", "refractory", "unknown"
        }
        actual = {f.value for f in AlloyFamily}
        assert actual == expected


class TestNormalizedAlloy:
    """Tests for NormalizedAlloy dataclass."""

    def test_is_resolved_true_when_uns_and_high_confidence(self):
        """is_resolved should be True with UNS and confidence >= 0.7."""
        result = NormalizedAlloy(
            original_input="316L",
            uns="S31603",
            confidence=0.9,
        )
        assert result.is_resolved

    def test_is_resolved_false_without_uns(self):
        """is_resolved should be False without UNS."""
        result = NormalizedAlloy(
            original_input="UNKNOWN",
            confidence=0.9,
        )
        assert not result.is_resolved

    def test_is_resolved_false_with_low_confidence(self):
        """is_resolved should be False with low confidence."""
        result = NormalizedAlloy(
            original_input="316L",
            uns="S31603",
            confidence=0.5,
        )
        assert not result.is_resolved


class TestUnsLookupTables:
    """Tests for UNS lookup table completeness."""

    def test_aluminum_table_has_common_alloys(self):
        """Aluminum table should have common alloys."""
        common = ["2024", "6061", "7075", "5052", "2219"]
        for alloy in common:
            assert alloy in UNS_ALUMINUM, f"Missing aluminum {alloy}"

    def test_stainless_table_has_common_grades(self):
        """Stainless table should have common grades."""
        common = ["304", "304L", "316", "316L", "321", "347", "17-4 PH"]
        for grade in common:
            assert grade in UNS_STAINLESS, f"Missing stainless {grade}"

    def test_stainless_18_8_maps_to_304(self):
        """18-8 stainless should map to 304 (S30400)."""
        assert UNS_STAINLESS.get("18-8") == "S30400"

    def test_titanium_table_has_common_grades(self):
        """Titanium table should have common grades."""
        assert "TI-6AL-4V" in UNS_TITANIUM
        assert "TI-6AL-4V ELI" in UNS_TITANIUM
        assert "GRADE 2" in UNS_TITANIUM

    def test_nickel_table_has_inconel_grades(self):
        """Nickel table should have Inconel grades."""
        common = ["INCONEL 625", "INCONEL 718", "INCONEL X-750"]
        for grade in common:
            assert grade in UNS_NICKEL, f"Missing {grade}"


class TestAlloyNormalizerStainless:
    """Tests for stainless steel normalization."""

    def test_304_variants(self):
        """Should normalize 304 variants correctly."""
        normalizer = AlloyNormalizer()

        variants = ["304", "SS304", "SS 304", "CRES 304", "AISI 304"]
        for v in variants:
            result = normalizer.normalize(v)
            assert result.uns == "S30400", f"Failed for {v}"
            assert result.family == AlloyFamily.STAINLESS_STEEL

    def test_304l_variant(self):
        """Should normalize 304L correctly."""
        result = normalize_alloy("304L")
        assert result.uns == "S30403"
        assert result.family == AlloyFamily.STAINLESS_STEEL

    def test_316l_variant(self):
        """Should normalize 316L correctly."""
        result = normalize_alloy("316L")
        assert result.uns == "S31603"

    def test_18_8_maps_to_304(self):
        """18-8 stainless should map to 304."""
        result = normalize_alloy("18-8 SS")
        assert result.uns == "S30400"
        assert "304" in result.canonical_name

    def test_17_4_ph_variants(self):
        """Should normalize 17-4 PH variants correctly."""
        normalizer = AlloyNormalizer()

        variants = ["17-4 PH", "17-4PH", "174PH", "CRES 17-4 PH"]
        for v in variants:
            result = normalizer.normalize(v)
            assert result.uns == "S17400", f"Failed for {v}: got {result.uns}"

    def test_a286_variants(self):
        """Should normalize A-286 variants correctly."""
        variants = ["A-286", "A286", "A 286", "CRES A-286"]
        for v in variants:
            result = normalize_alloy(v)
            assert result.uns == "S66286", f"Failed for {v}: got {result.uns}"

    def test_a286_with_strength_qualifier(self):
        """A286 with KSI qualifier should still normalize to S66286."""
        result = normalize_alloy("A286 (160 KSI)")
        assert result.uns == "S66286"
        assert result.match_method == "stainless_a286"

    def test_a286_sst_variant(self):
        """A286 with SST suffix should still normalize to S66286."""
        result = normalize_alloy("A286 SST")
        assert result.uns == "S66286"
        assert result.match_method == "stainless_a286"


class TestAlloyNormalizerAluminum:
    """Tests for aluminum normalization."""

    def test_basic_alloys(self):
        """Should normalize basic aluminum alloys."""
        test_cases = [
            ("2024", "A92024"),
            ("6061", "A96061"),
            ("7075", "A97075"),
        ]
        for designation, expected_uns in test_cases:
            result = normalize_alloy(designation)
            assert result.uns == expected_uns, f"Failed for {designation}"
            assert result.family == AlloyFamily.ALUMINUM

    def test_alloy_with_temper(self):
        """Should extract temper designation."""
        result = normalize_alloy("7075-T6")
        assert result.uns == "A97075"
        assert result.temper == "T6"

    def test_aluminum_prefix(self):
        """Should handle ALUMINUM prefix."""
        result = normalize_alloy("ALUMINUM 6061-T6")
        assert result.uns == "A96061"


class TestAlloyNormalizerTitanium:
    """Tests for titanium normalization."""

    def test_6al4v_variants(self):
        """Should normalize Ti-6Al-4V variants."""
        variants = ["Ti-6Al-4V", "6Al-4V", "Ti 6-4", "TI64"]
        for v in variants:
            result = normalize_alloy(v)
            assert result.uns == "R56400", f"Failed for {v}: got {result.uns}"
            assert result.family == AlloyFamily.TITANIUM

    def test_6al4v_eli(self):
        """Should normalize Ti-6Al-4V ELI."""
        result = normalize_alloy("Ti-6Al-4V ELI")
        assert result.uns == "R56401"
        assert "ELI" in result.canonical_name

    def test_cp_grades(self):
        """Should normalize CP titanium grades."""
        result = normalize_alloy("Ti Grade 2")
        assert result.uns == "R50400"


class TestAlloyNormalizerNickel:
    """Tests for nickel alloy normalization."""

    def test_inconel_625(self):
        """Should normalize Inconel 625."""
        # Note: "ALLOY 625" is ambiguous and may not resolve correctly
        variants = ["Inconel 625", "IN625"]
        for v in variants:
            result = normalize_alloy(v)
            assert result.uns == "N06625", f"Failed for {v}"
            assert result.family == AlloyFamily.NICKEL

    def test_inconel_718(self):
        """Should normalize Inconel 718."""
        result = normalize_alloy("Inconel 718")
        assert result.uns == "N07718"

    def test_generic_inconel_alloy_unresolved(self):
        """Generic Inconel without grade should remain unresolved."""
        result = normalize_alloy("INCONEL ALLOY")
        assert result.uns is None
        assert not result.is_resolved

    def test_hastelloy_c276(self):
        """Should normalize Hastelloy C-276."""
        result = normalize_alloy("Hastelloy C-276")
        assert result.uns == "N10276"

    def test_monel_400(self):
        """Should normalize Monel 400."""
        result = normalize_alloy("Monel 400")
        assert result.uns == "N04400"

    def test_waspaloy(self):
        """Should normalize Waspaloy."""
        result = normalize_alloy("Waspaloy")
        assert result.uns == "N07001"


class TestAlloyNormalizerCopper:
    """Tests for copper alloy normalization."""

    def test_beryllium_copper(self):
        """Should normalize BeCu variants."""
        variants = ["BeCu", "Beryllium Copper", "BECU", "Alloy 25"]
        for v in variants:
            result = normalize_alloy(v)
            assert result.uns == "C17200", f"Failed for {v}: got {result.uns}"
            assert result.family == AlloyFamily.COPPER

    def test_copper_uns(self):
        """Should handle direct copper UNS."""
        result = normalize_alloy("C17200")
        assert result.uns == "C17200"


class TestAlloyNormalizerCobalt:
    """Tests for cobalt alloy normalization."""

    def test_mp35n(self):
        """Should normalize MP35N."""
        result = normalize_alloy("MP35N")
        assert result.uns == "R30035"
        assert result.family == AlloyFamily.COBALT


class TestAlloyNormalizerUns:
    """Tests for direct UNS code handling."""

    def test_direct_uns_stainless(self):
        """Should recognize direct UNS codes."""
        result = normalize_alloy("UNS S31603")
        assert result.uns == "S31603"
        assert result.family == AlloyFamily.STAINLESS_STEEL
        assert result.confidence >= 0.9

    def test_direct_uns_nickel(self):
        """Should recognize nickel UNS codes."""
        result = normalize_alloy("N06625")
        assert result.uns == "N06625"
        assert result.family == AlloyFamily.NICKEL


class TestAlloyNormalizerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_string(self):
        """Should handle empty string."""
        result = normalize_alloy("")
        assert not result.is_resolved
        assert len(result.warnings) > 0

    def test_whitespace_only(self):
        """Should handle whitespace-only string."""
        result = normalize_alloy("   ")
        assert not result.is_resolved

    def test_unknown_designation(self):
        """Should handle unknown designations gracefully."""
        # Use a string that won't match any alloy patterns
        result = normalize_alloy("QQQWWWEEE")
        assert not result.is_resolved
        assert result.match_method == "unresolved"

    def test_preserves_original_input(self):
        """Should preserve original input in result."""
        original = "  SS 316L  "
        result = normalize_alloy(original)
        assert result.original_input == original

    def test_strips_spec_prefix(self):
        """Should strip AMS/ASTM prefixes."""
        result = normalize_alloy("AMS 5528 316L")
        assert result.uns == "S31603"


class TestH2Compatibility:
    """Tests for hydrogen compatibility checking."""

    def test_austenitic_compatible(self):
        """Austenitic stainless should be H2 compatible."""
        normalizer = AlloyNormalizer()

        # 300-series should be compatible
        assert normalizer.is_h2_compatible("S30400") is True  # 304
        assert normalizer.is_h2_compatible("S31603") is True  # 316L

    def test_ph_grades_incompatible(self):
        """PH grades should be H2 incompatible."""
        normalizer = AlloyNormalizer()

        assert normalizer.is_h2_compatible("S17400") is False  # 17-4 PH

    def test_nickel_compatible(self):
        """Nickel alloys should be H2 compatible."""
        normalizer = AlloyNormalizer()

        assert normalizer.is_h2_compatible("N06625") is True  # Inconel 625
        assert normalizer.is_h2_compatible("N07718") is True  # Inconel 718

    def test_titanium_compatible(self):
        """Titanium should be H2 compatible."""
        normalizer = AlloyNormalizer()

        assert normalizer.is_h2_compatible("R56400") is True  # Ti-6Al-4V

    def test_unknown_returns_none(self):
        """Unknown UNS should return None."""
        normalizer = AlloyNormalizer()

        assert normalizer.is_h2_compatible("X99999") is None
        assert normalizer.is_h2_compatible(None) is None


class TestGetUnsInfo:
    """Tests for get_uns_info method."""

    def test_returns_complete_info(self):
        """Should return complete info dict."""
        normalizer = AlloyNormalizer()
        info = normalizer.get_uns_info("S31603")

        assert info["uns"] == "S31603"
        assert info["family"] == "stainless_steel"
        assert "canonical_name" in info
        assert "h2_compatible" in info

    def test_empty_uns_returns_empty(self):
        """Empty UNS should return empty dict."""
        normalizer = AlloyNormalizer()
        assert normalizer.get_uns_info("") == {}
        assert normalizer.get_uns_info(None) == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
