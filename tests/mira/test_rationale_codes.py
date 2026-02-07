#!/usr/bin/env python3
"""
Module: Test Rationale Codes
Purpose: Rationale Codes Tests for BoundState

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

from mira.miul.rationale_codes import (
    RationaleCategory,
    RationaleCode,
    get_rationales_for_rating,
    get_mua_reference_code,
    get_rationale,
    FLAMMABILITY_RATIONALES,
    TOXICITY_RATIONALES,
    FLUID_SYSTEM_RATIONALES,
    THERMAL_VACUUM_RATIONALES,
    STRESS_CORROSION_RATIONALES,
    CORROSION_RATIONALES,
)


class TestRationaleCategory:
    """Tests for RationaleCategory enum."""

    def test_all_categories_defined(self):
        """All 6 rating categories should be defined."""
        expected = {"FLAM", "TOX", "FS", "TVS", "SCC", "CORR"}
        actual = {cat.value for cat in RationaleCategory}
        assert actual == expected

    def test_category_is_string_enum(self):
        """Categories should have correct values."""
        # Use .value to get the string value
        assert RationaleCategory.FLAMMABILITY.value == "FLAM"
        assert RationaleCategory.TOXICITY.value == "TOX"


class TestRationaleCode:
    """Tests for RationaleCode model."""

    def test_basic_rationale_code(self):
        """Should create valid rationale code."""
        code = RationaleCode(
            code="403",
            category=RationaleCategory.THERMAL_VACUUM,
            rationale="VCM between 0.1 and 1.0 percent",
        )
        assert code.code == "403"
        assert code.category == RationaleCategory.THERMAL_VACUUM
        assert not code.is_mua_reference
        assert code.mua_category is None

    def test_mua_reference_code(self):
        """MUA reference codes should have category set."""
        code = FLAMMABILITY_RATIONALES["101"]
        assert code.is_mua_reference
        assert code.mua_category == "I"

    def test_category_ii_mua(self):
        """Category II MUA codes should be properly tagged."""
        code = FLAMMABILITY_RATIONALES["102"]
        assert code.is_mua_reference
        assert code.mua_category == "II"


class TestFlammabilityRationales:
    """Tests for 100-series flammability rationales."""

    def test_all_codes_in_100_series(self):
        """All flammability codes should be in 100-series."""
        for code in FLAMMABILITY_RATIONALES.keys():
            assert code.startswith("1"), f"Code {code} not in 100-series"

    def test_mua_codes_101_102(self):
        """Codes 101 and 102 should be MUA references."""
        assert FLAMMABILITY_RATIONALES["101"].is_mua_reference
        assert FLAMMABILITY_RATIONALES["102"].is_mua_reference
        assert FLAMMABILITY_RATIONALES["101"].mua_category == "I"
        assert FLAMMABILITY_RATIONALES["102"].mua_category == "II"

    def test_technical_rationales_exist(self):
        """Technical rationale codes should exist."""
        assert "103" in FLAMMABILITY_RATIONALES  # sandwiched
        assert "104" in FLAMMABILITY_RATIONALES  # encapsulated
        assert "105" in FLAMMABILITY_RATIONALES  # minor usage
        assert "114" in FLAMMABILITY_RATIONALES  # metal/ceramic

    def test_category_assignment(self):
        """All codes should have correct category."""
        for code in FLAMMABILITY_RATIONALES.values():
            assert code.category == RationaleCategory.FLAMMABILITY


class TestToxicityRationales:
    """Tests for 200-series toxicity rationales."""

    def test_all_codes_in_200_series(self):
        """All toxicity codes should be in 200-series."""
        for code in TOXICITY_RATIONALES.keys():
            assert code.startswith("2"), f"Code {code} not in 200-series"

    def test_category_assignment(self):
        """All codes should have correct category."""
        for code in TOXICITY_RATIONALES.values():
            assert code.category == RationaleCategory.TOXICITY


class TestFluidSystemRationales:
    """Tests for 300-series fluid system rationales."""

    def test_all_codes_in_300_series(self):
        """All FS codes should be in 300-series."""
        for code in FLUID_SYSTEM_RATIONALES.keys():
            assert code.startswith("3"), f"Code {code} not in 300-series"


class TestThermalVacuumRationales:
    """Tests for 400-series TVS rationales."""

    def test_all_codes_in_400_series(self):
        """All TVS codes should be in 400-series."""
        for code in THERMAL_VACUUM_RATIONALES.keys():
            assert code.startswith("4"), f"Code {code} not in 400-series"

    def test_vcm_rationales(self):
        """VCM-specific rationales should exist."""
        # 403: VCM 0.1-1.0%, area <13 cm2
        assert "403" in THERMAL_VACUUM_RATIONALES
        # 404: VCM >1.0%, area <1.6 cm2
        assert "404" in THERMAL_VACUUM_RATIONALES


class TestStressCorrosionRationales:
    """Tests for 500-series SCC rationales."""

    def test_all_codes_in_500_series(self):
        """All SCC codes should be in 500-series."""
        for code in STRESS_CORROSION_RATIONALES.keys():
            assert code.startswith("5"), f"Code {code} not in 500-series"


class TestCorrosionRationales:
    """Tests for 600-series corrosion rationales."""

    def test_all_codes_in_600_series(self):
        """All corrosion codes should be in 600-series."""
        for code in CORROSION_RATIONALES.keys():
            assert code.startswith("6"), f"Code {code} not in 600-series"


class TestGetRationalesForRating:
    """Tests for get_rationales_for_rating function."""

    def test_returns_correct_dict_for_each_category(self):
        """Should return correct rationales dict for each category."""
        assert get_rationales_for_rating(RationaleCategory.FLAMMABILITY) is FLAMMABILITY_RATIONALES
        assert get_rationales_for_rating(RationaleCategory.TOXICITY) is TOXICITY_RATIONALES
        assert get_rationales_for_rating(RationaleCategory.FLUID_SYSTEM) is FLUID_SYSTEM_RATIONALES
        assert get_rationales_for_rating(RationaleCategory.THERMAL_VACUUM) is THERMAL_VACUUM_RATIONALES
        assert get_rationales_for_rating(RationaleCategory.STRESS_CORROSION) is STRESS_CORROSION_RATIONALES
        assert get_rationales_for_rating(RationaleCategory.CORROSION) is CORROSION_RATIONALES

    def test_returns_non_empty_dicts(self):
        """Each category should have at least one rationale."""
        for category in RationaleCategory:
            rationales = get_rationales_for_rating(category)
            assert len(rationales) > 0, f"No rationales for {category}"


class TestGetMuaReferenceCode:
    """Tests for get_mua_reference_code function."""

    def test_category_i_codes(self):
        """Category I should return x01 codes."""
        assert get_mua_reference_code("FLAM", "I") == "101"
        assert get_mua_reference_code("TOX", "I") == "201"
        assert get_mua_reference_code("FS", "I") == "301"
        assert get_mua_reference_code("TVS", "I") == "401"
        assert get_mua_reference_code("SCC", "I") == "501"
        assert get_mua_reference_code("CORR", "I") == "601"

    def test_category_ii_codes(self):
        """Category II should return x02 codes."""
        assert get_mua_reference_code("FLAM", "II") == "102"
        assert get_mua_reference_code("TOX", "II") == "202"
        assert get_mua_reference_code("FS", "II") == "302"
        assert get_mua_reference_code("TVS", "II") == "402"
        assert get_mua_reference_code("SCC", "II") == "502"
        assert get_mua_reference_code("CORR", "II") == "602"

    def test_case_insensitive(self):
        """Should handle lowercase rating types."""
        assert get_mua_reference_code("flam", "I") == "101"
        assert get_mua_reference_code("tvs", "II") == "402"

    def test_unknown_rating_type(self):
        """Unknown rating type should return 7xx."""
        assert get_mua_reference_code("UNKNOWN", "I") == "701"


class TestGetRationale:
    """Tests for get_rationale function."""

    def test_finds_existing_code(self):
        """Should find existing rationale code."""
        result = get_rationale("403")
        assert result is not None
        assert result.code == "403"
        assert result.category == RationaleCategory.THERMAL_VACUUM

    def test_returns_none_for_invalid_code(self):
        """Should return None for non-existent code."""
        assert get_rationale("999") is None
        assert get_rationale("") is None
        assert get_rationale("INVALID") is None

    def test_finds_all_mua_reference_codes(self):
        """All x01 and x02 codes should be findable."""
        for prefix in ["1", "2", "3", "4", "5", "6"]:
            code_i = get_rationale(f"{prefix}01")
            code_ii = get_rationale(f"{prefix}02")
            assert code_i is not None, f"Missing {prefix}01"
            assert code_ii is not None, f"Missing {prefix}02"
            assert code_i.is_mua_reference
            assert code_ii.is_mua_reference


class TestRationaleCompleteness:
    """Tests for rationale coverage completeness."""

    def test_each_category_has_mua_codes(self):
        """Each category should have x01 and x02 MUA codes."""
        all_rationales = [
            FLAMMABILITY_RATIONALES,
            TOXICITY_RATIONALES,
            FLUID_SYSTEM_RATIONALES,
            THERMAL_VACUUM_RATIONALES,
            STRESS_CORROSION_RATIONALES,
            CORROSION_RATIONALES,
        ]
        for i, rationales in enumerate(all_rationales, 1):
            code_01 = f"{i}01"
            code_02 = f"{i}02"
            assert code_01 in rationales, f"Missing {code_01}"
            assert code_02 in rationales, f"Missing {code_02}"

    def test_rationale_texts_not_empty(self):
        """All rationale codes should have non-empty text."""
        all_codes = [
            *FLAMMABILITY_RATIONALES.values(),
            *TOXICITY_RATIONALES.values(),
            *FLUID_SYSTEM_RATIONALES.values(),
            *THERMAL_VACUUM_RATIONALES.values(),
            *STRESS_CORROSION_RATIONALES.values(),
            *CORROSION_RATIONALES.values(),
        ]
        for code in all_codes:
            assert len(code.rationale) > 0, f"Empty rationale for {code.code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
