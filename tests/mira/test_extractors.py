#!/usr/bin/env python3
"""
Module: Test Extractors
Purpose: BOM Extractor Tests for BoundState

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

import pytest
boto3 = pytest.importorskip('boto3', reason='boto3 required for AWS extractors')
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, r"C:\BoundState")

from mira.miul.extractors.service import (
    ExtractorService,
    get_extractor_service,
    reset_extractor_service,
)
from mira.miul.extractors.haiku import HaikuExtractor
from mira.miul.extractors.drawing_parser import (
    MaterialSource,
    DrawingMaterial,
    EmbeddedHardware,
    DrawingExtraction,
    DrawingParserPrompts,
    HARDWARE_STANDARD_MATERIALS,
    aggregate_hardware_by_standard,
    resolve_hardware_material,
    check_material_compatibility,
)
from mira.miul.interfaces import BOMExtractorBase, SafetyCriticalError


# =============================================================================
# Test Fixtures
# =============================================================================


class MockExtractor(BOMExtractorBase):
    """Mock extractor for testing."""

    def __init__(
        self,
        name: str = "Mock",
        priority: int = 50,
        available: bool = True,
        parts: list = None,
        should_raise: bool = False,
    ):
        self._name = name
        self._priority = priority
        self._available = available
        self._parts = parts or []
        self._should_raise = should_raise

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def is_available(self) -> bool:
        return self._available

    async def extract(self, file_paths):
        if self._should_raise:
            raise Exception("Mock extraction error")
        return self._parts


# =============================================================================
# ExtractorService Tests
# =============================================================================


class TestExtractorServiceInit:
    """Tests for ExtractorService initialization."""

    def test_starts_empty(self):
        """Should start with no extractors."""
        service = ExtractorService()
        assert service._extractors == []

    def test_no_available_extractors_initially(self):
        """get_available_extractors should return empty initially."""
        service = ExtractorService()
        assert service.get_available_extractors() == []


class TestExtractorServiceRegister:
    """Tests for extractor registration."""

    def test_register_valid_extractor(self):
        """Should register valid extractor."""
        service = ExtractorService()
        extractor = MockExtractor()

        service.register(extractor)

        assert len(service._extractors) == 1
        assert service._extractors[0] is extractor

    def test_register_returns_self_for_chaining(self):
        """Register should return self for method chaining."""
        service = ExtractorService()
        extractor = MockExtractor()

        result = service.register(extractor)

        assert result is service

    def test_register_rejects_invalid_type(self):
        """Should raise TypeError for non-BOMExtractorBase."""
        service = ExtractorService()

        with pytest.raises(TypeError):
            service.register("not an extractor")

    def test_sorts_by_priority(self):
        """Extractors should be sorted by priority (highest first)."""
        service = ExtractorService()

        low = MockExtractor(name="Low", priority=10)
        high = MockExtractor(name="High", priority=100)
        mid = MockExtractor(name="Mid", priority=50)

        service.register(low).register(high).register(mid)

        assert service._extractors[0].name == "High"
        assert service._extractors[1].name == "Mid"
        assert service._extractors[2].name == "Low"


class TestExtractorServiceAvailability:
    """Tests for extractor availability checking."""

    def test_filters_unavailable(self):
        """get_available_extractors should filter unavailable."""
        service = ExtractorService()

        available = MockExtractor(name="Available", available=True)
        unavailable = MockExtractor(name="Unavailable", available=False)

        service.register(available).register(unavailable)

        result = service.get_available_extractors()

        assert len(result) == 1
        assert result[0].name == "Available"


class TestExtractorServiceExtract:
    """Tests for extraction orchestration."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_files(self):
        """Should return empty list when no files provided."""
        service = ExtractorService()
        service.register(MockExtractor())

        result = await service.extract([])

        assert result == []

    @pytest.mark.asyncio
    async def test_raises_when_no_extractors_and_required(self):
        """Should raise SafetyCriticalError when required and no extractors."""
        service = ExtractorService()

        with pytest.raises(SafetyCriticalError):
            await service.extract([Path("test.pdf")], require_extraction=True)

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_extractors_and_not_required(self):
        """Should return empty when not required and no extractors."""
        service = ExtractorService()

        result = await service.extract([Path("test.pdf")], require_extraction=False)

        assert result == []

    @pytest.mark.asyncio
    async def test_uses_first_successful_extractor(self):
        """Should use first successful extractor by priority."""
        service = ExtractorService()

        high_parts = [{"part_number": "HIGH-001"}]
        low_parts = [{"part_number": "LOW-001"}]

        high = MockExtractor(name="High", priority=100, parts=high_parts)
        low = MockExtractor(name="Low", priority=10, parts=low_parts)

        service.register(low).register(high)

        result = await service.extract([Path("test.pdf")])

        assert result == high_parts

    @pytest.mark.asyncio
    async def test_falls_back_on_failure(self):
        """Should fall back to next extractor on failure."""
        service = ExtractorService()

        backup_parts = [{"part_number": "BACKUP-001"}]

        failing = MockExtractor(name="Failing", priority=100, should_raise=True)
        backup = MockExtractor(name="Backup", priority=50, parts=backup_parts)

        service.register(failing).register(backup)

        result = await service.extract([Path("test.pdf")])

        assert result == backup_parts

    @pytest.mark.asyncio
    async def test_falls_back_on_empty_result(self):
        """Should fall back when extractor returns empty."""
        service = ExtractorService()

        backup_parts = [{"part_number": "BACKUP-001"}]

        empty = MockExtractor(name="Empty", priority=100, parts=[])
        backup = MockExtractor(name="Backup", priority=50, parts=backup_parts)

        service.register(empty).register(backup)

        result = await service.extract([Path("test.pdf")])

        assert result == backup_parts

    @pytest.mark.asyncio
    async def test_raises_when_all_fail_and_required(self):
        """Should raise when all extractors fail and require_extraction=True."""
        service = ExtractorService()

        failing = MockExtractor(name="Failing", priority=100, should_raise=True)
        service.register(failing)

        with pytest.raises(SafetyCriticalError):
            await service.extract([Path("test.pdf")], require_extraction=True)


class TestExtractorServiceSingleton:
    """Tests for singleton management."""

    @patch("mira.miul.extractors.haiku.HaikuExtractor")
    @patch("mira.miul.extractors.local.LocalExtractor")
    def test_get_returns_singleton(self, mock_local, mock_haiku):
        """get_extractor_service should return same instance."""
        mock_haiku.return_value = MockExtractor()
        mock_local.return_value = MockExtractor(priority=10)

        reset_extractor_service()

        service1 = get_extractor_service()
        service2 = get_extractor_service()

        assert service1 is service2

        reset_extractor_service()

    @patch("mira.miul.extractors.haiku.HaikuExtractor")
    @patch("mira.miul.extractors.local.LocalExtractor")
    def test_reset_clears_singleton(self, mock_local, mock_haiku):
        """reset_extractor_service should clear singleton."""
        mock_haiku.return_value = MockExtractor()
        mock_local.return_value = MockExtractor(priority=10)

        reset_extractor_service()

        service1 = get_extractor_service()
        reset_extractor_service()
        service2 = get_extractor_service()

        assert service1 is not service2

        reset_extractor_service()


# =============================================================================
# HaikuExtractor Tests
# =============================================================================


class TestHaikuExtractorProperties:
    """Tests for HaikuExtractor properties."""

    def test_name_property(self):
        """Name should identify Claude Haiku API."""
        extractor = HaikuExtractor()
        assert "Haiku" in extractor.name

    def test_priority_is_high(self):
        """Priority should be high (100) to try first."""
        extractor = HaikuExtractor()
        assert extractor.priority == 100


class TestHaikuExtractorAvailability:
    """Tests for HaikuExtractor availability checking."""

    def test_unavailable_without_api_key(self):
        """Should be unavailable without API key."""
        with patch.dict("os.environ", {}, clear=True):
            extractor = HaikuExtractor(api_key=None)

        # Mock the class loading to return a valid class
        with patch(
            "mira.miul.extractors.haiku._get_haiku_extractor_class",
            return_value=MagicMock,
        ):
            assert not extractor.is_available()

    def test_available_with_api_key(self):
        """Should be available with API key."""
        extractor = HaikuExtractor(api_key="test-api-key")

        with patch(
            "mira.miul.extractors.haiku._get_haiku_extractor_class",
            return_value=MagicMock,
        ):
            assert extractor.is_available()


class TestHaikuExtractorExtract:
    """Tests for HaikuExtractor extraction."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_unavailable(self):
        """Should return empty when not available."""
        extractor = HaikuExtractor(api_key=None)

        result = await extractor.extract([Path("test.pdf")])

        assert result == []


# =============================================================================
# Drawing Parser Tests - MaterialSource Enum
# =============================================================================


class TestMaterialSource:
    """Tests for MaterialSource enum."""

    def test_all_sources_defined(self):
        """All expected material sources should be defined."""
        expected = {
            "title_block",
            "note",
            "callout",
            "bill_of_materials",
            "inferred_from_standard",
        }
        actual = {s.value for s in MaterialSource}
        assert actual == expected


# =============================================================================
# Drawing Parser Tests - DrawingMaterial Model
# =============================================================================


class TestDrawingMaterial:
    """Tests for DrawingMaterial model."""

    def test_basic_creation(self):
        """Should create valid DrawingMaterial."""
        material = DrawingMaterial(
            designation="7075-T6 ALUMINUM",
            source=MaterialSource.TITLE_BLOCK,
            raw_text="MATERIAL: 7075-T6 ALUMINUM PER SAE AMS4124",
        )

        assert material.designation == "7075-T6 ALUMINUM"
        assert material.source == MaterialSource.TITLE_BLOCK
        assert material.quantity == 1  # Default

    def test_with_specification(self):
        """Should handle optional specification."""
        material = DrawingMaterial(
            designation="316L STAINLESS",
            specification="SAE AMS5648",
            source=MaterialSource.TITLE_BLOCK,
            raw_text="316L PER AMS5648",
        )

        assert material.specification == "SAE AMS5648"

    def test_with_uns_number(self):
        """Should handle UNS number."""
        material = DrawingMaterial(
            designation="316L STAINLESS",
            uns_number="S31603",
            source=MaterialSource.TITLE_BLOCK,
            raw_text="316L UNS S31603",
        )

        assert material.uns_number == "S31603"


# =============================================================================
# Drawing Parser Tests - EmbeddedHardware Model
# =============================================================================


class TestEmbeddedHardware:
    """Tests for EmbeddedHardware model."""

    def test_basic_creation(self):
        """Should create valid EmbeddedHardware."""
        hardware = EmbeddedHardware(
            standard="NASM33537",
            quantity=24,
            raw_callout="24X HELICAL COIL INSERT NASM33537",
        )

        assert hardware.standard == "NASM33537"
        assert hardware.quantity == 24

    def test_with_thread_size(self):
        """Should handle thread size."""
        hardware = EmbeddedHardware(
            standard="NASM33537",
            thread_size=".3125-18 UNC",
            quantity=12,
            raw_callout="12X .3125-18 UNC HELICAL COIL",
        )

        assert hardware.thread_size == ".3125-18 UNC"

    def test_confidence_reduced_for_inferred(self):
        """Confidence should be reduced when material is inferred."""
        hardware = EmbeddedHardware(
            standard="NASM33537",
            quantity=1,
            inferred_material="CRES 302/304",
            confidence=1.0,  # Will be reduced
            raw_callout="HELICAL COIL INSERT",
        )

        # Validator should reduce confidence for inferred materials
        assert hardware.confidence == 0.85


# =============================================================================
# Drawing Parser Tests - DrawingExtraction Model
# =============================================================================


class TestDrawingExtraction:
    """Tests for DrawingExtraction model."""

    def test_basic_creation(self):
        """Should create valid DrawingExtraction."""
        extraction = DrawingExtraction(
            drawing_number="12345-001",
            revision="A",
            title="BRACKET, SUPPORT",
        )

        assert extraction.drawing_number == "12345-001"
        assert extraction.revision == "A"

    def test_all_materials_for_miul_primary(self):
        """all_materials_for_miul should include primary material."""
        primary = DrawingMaterial(
            designation="7075-T6",
            specification="AMS4124",
            source=MaterialSource.TITLE_BLOCK,
            raw_text="7075-T6 PER AMS4124",
        )

        extraction = DrawingExtraction(
            drawing_number="12345",
            primary_material=primary,
        )

        items = extraction.all_materials_for_miul()

        assert len(items) == 1
        assert items[0]["material_designation"] == "7075-T6"
        assert items[0]["source"] == "primary"

    def test_all_materials_for_miul_subordinate(self):
        """all_materials_for_miul should include subordinate materials."""
        subordinate = DrawingMaterial(
            designation="316L",
            source=MaterialSource.NOTE,
            quantity=4,
            raw_text="316L SS BUSHINGS",
        )

        extraction = DrawingExtraction(
            drawing_number="12345",
            subordinate_materials=[subordinate],
        )

        items = extraction.all_materials_for_miul()

        assert len(items) == 1
        assert items[0]["material_designation"] == "316L"
        assert items[0]["source"] == "note"

    def test_all_materials_for_miul_embedded_hardware(self):
        """all_materials_for_miul should include inferred hardware materials."""
        hardware = EmbeddedHardware(
            standard="NASM33537",
            quantity=24,
            inferred_material="CRES 302/304",
            inferred_spec="AMS 5688",
            raw_callout="24X HELICAL COIL",
        )

        extraction = DrawingExtraction(
            drawing_number="12345",
            embedded_hardware=[hardware],
        )

        items = extraction.all_materials_for_miul()

        assert len(items) == 1
        assert items[0]["material_designation"] == "CRES 302/304"
        assert "NASM33537" in items[0]["source"]


# =============================================================================
# Drawing Parser Tests - Hardware Standard Materials
# =============================================================================


class TestHardwareStandardMaterials:
    """Tests for hardware standard materials lookup table."""

    def test_nasm33537_exists(self):
        """NASM33537 helical coil inserts should be in table."""
        assert "NASM33537" in HARDWARE_STANDARD_MATERIALS
        info = HARDWARE_STANDARD_MATERIALS["NASM33537"]
        assert "CRES" in info["material"]

    def test_nas1149_exists(self):
        """NAS1149 washers should be in table."""
        assert "NAS1149" in HARDWARE_STANDARD_MATERIALS

    def test_an_bolts_exist(self):
        """AN series bolts should be in table."""
        for an in ["AN3", "AN4", "AN5", "AN6"]:
            assert an in HARDWARE_STANDARD_MATERIALS

    def test_all_entries_have_required_fields(self):
        """All entries should have material and confidence fields."""
        for std, info in HARDWARE_STANDARD_MATERIALS.items():
            assert "material" in info, f"Missing material for {std}"
            assert "confidence" in info, f"Missing confidence for {std}"


# =============================================================================
# Drawing Parser Tests - Prompt Templates
# =============================================================================


class TestDrawingParserPrompts:
    """Tests for prompt templates."""

    def test_pass1_returns_string(self):
        """Title block prompt should return string."""
        prompt = DrawingParserPrompts.pass1_title_block()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_pass2_returns_string(self):
        """Embedded hardware prompt should return string."""
        prompt = DrawingParserPrompts.pass2_embedded_hardware()
        assert isinstance(prompt, str)
        assert "NASM33537" in prompt  # Should mention inserts

    def test_pass3_returns_string(self):
        """Standards prompt should return string."""
        prompt = DrawingParserPrompts.pass3_referenced_standards()
        assert isinstance(prompt, str)


# =============================================================================
# Drawing Parser Tests - Aggregate Hardware
# =============================================================================


class TestAggregateHardwareByStandard:
    """Tests for hardware aggregation function."""

    def test_aggregates_same_standard(self):
        """Should aggregate items with same standard."""
        items = [
            EmbeddedHardware(
                standard="NASM33537",
                quantity=12,
                raw_callout="12X INSERT",
            ),
            EmbeddedHardware(
                standard="NASM33537",
                quantity=6,
                raw_callout="6X INSERT",
            ),
        ]

        result = aggregate_hardware_by_standard(items)

        assert len(result) == 1
        assert result[0].quantity == 18

    def test_keeps_different_standards_separate(self):
        """Should keep different standards separate."""
        items = [
            EmbeddedHardware(
                standard="NASM33537",
                quantity=12,
                raw_callout="12X INSERT",
            ),
            EmbeddedHardware(
                standard="NAS1149",
                quantity=6,
                raw_callout="6X WASHER",
            ),
        ]

        result = aggregate_hardware_by_standard(items)

        assert len(result) == 2

    def test_normalizes_case(self):
        """Should normalize standard names to uppercase."""
        items = [
            EmbeddedHardware(
                standard="nasm33537",
                quantity=12,
                raw_callout="12X INSERT",
            ),
            EmbeddedHardware(
                standard="NASM33537",
                quantity=6,
                raw_callout="6X INSERT",
            ),
        ]

        result = aggregate_hardware_by_standard(items)

        assert len(result) == 1
        assert result[0].standard == "NASM33537"


# =============================================================================
# Drawing Parser Tests - Resolve Hardware Material
# =============================================================================


class TestResolveHardwareMaterial:
    """Tests for hardware material resolution."""

    def test_resolves_known_standard(self):
        """Should resolve material for known standard."""
        hw = EmbeddedHardware(
            standard="NASM33537",
            quantity=1,
            raw_callout="INSERT",
        )

        resolve_hardware_material(hw)

        assert hw.inferred_material is not None
        assert "CRES" in hw.inferred_material

    def test_strips_dash_number(self):
        """Should strip dash number for lookup."""
        hw = EmbeddedHardware(
            standard="NASM33537-1032",
            quantity=1,
            raw_callout="INSERT",
        )

        resolve_hardware_material(hw)

        assert hw.inferred_material is not None

    def test_handles_unknown_standard(self):
        """Should handle unknown standard gracefully."""
        hw = EmbeddedHardware(
            standard="UNKNOWN-12345",
            quantity=1,
            raw_callout="MYSTERY PART",
        )

        resolve_hardware_material(hw)

        assert hw.inferred_material is None
        assert hw.confidence == 0.0


# =============================================================================
# Drawing Parser Tests - Material Compatibility
# =============================================================================


class TestCheckMaterialCompatibility:
    """Tests for material compatibility checking."""

    def test_warns_aluminum_with_cres_inserts(self):
        """Should warn about aluminum parent with CRES inserts."""
        hardware = [
            EmbeddedHardware(
                standard="NASM33537",
                quantity=24,
                inferred_material="CRES 302/304",
                raw_callout="INSERT",
            ),
        ]

        warnings = check_material_compatibility("7075-T6 ALUMINUM", hardware)

        assert len(warnings) > 0
        assert any("aluminum" in w.lower() for w in warnings)

    def test_warns_galvanic_corrosion_risk(self):
        """Should warn about galvanic corrosion risk."""
        hardware = [
            EmbeddedHardware(
                standard="AN4",
                quantity=4,
                inferred_material="Alloy Steel, cadmium plated",
                raw_callout="BOLT",
            ),
        ]

        warnings = check_material_compatibility("6061 ALUMINUM", hardware)

        assert len(warnings) > 0
        assert any("corrosion" in w.lower() for w in warnings)

    def test_no_warnings_for_compatible(self):
        """Should return no warnings for compatible combinations."""
        hardware = [
            EmbeddedHardware(
                standard="NASM33537",
                quantity=12,
                inferred_material="CRES 302/304",
                raw_callout="INSERT",
            ),
        ]

        warnings = check_material_compatibility("316L STAINLESS STEEL", hardware)

        assert len(warnings) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
