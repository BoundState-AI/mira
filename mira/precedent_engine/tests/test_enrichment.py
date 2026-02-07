#!/usr/bin/env python3
"""
Module: Test Enrichment
Purpose: test_enrichment

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import pytest

from mira.precedent_engine.core.enrichment import (
    derive_min_temperature,
    derive_program_family,
    generate_material_hash_key,
    is_valid_material,
    normalize_environment,
    normalize_location,
)
from mira.precedent_engine.models.enums import ProgramFamily
import uuid


class TestEnvironmentNormalization:
    """Tests for environment normalization."""

    def test_normalize_gox(self):
        """GOX environment."""
        media, o2 = normalize_environment("GOX")
        assert media == "GOX"
        assert o2 == 99.5

    def test_normalize_oxygen(self):
        """Oxygen keyword."""
        media, o2 = normalize_environment("oxygen service")
        assert media == "GOX"
        assert o2 == 99.5

    def test_normalize_lox(self):
        """LOX environment."""
        media, o2 = normalize_environment("LOX system")
        assert media == "LOX"
        assert o2 == 99.5

    def test_normalize_vacuum(self):
        """Vacuum environment."""
        media, o2 = normalize_environment("hard vacuum")
        assert media == "Vacuum"
        assert o2 == 0.0

    def test_normalize_air(self):
        """Air/cabin environment."""
        media, o2 = normalize_environment("cabin air")
        assert media == "Air"
        assert o2 == 21.0

    def test_normalize_nitrogen(self):
        """Nitrogen environment."""
        media, o2 = normalize_environment("GN2 purge")
        assert media == "GN2"
        assert o2 == 0.0

    def test_normalize_hydrogen(self):
        """Hydrogen environment."""
        media, o2 = normalize_environment("LH2 tank")
        assert media == "LH2"
        assert o2 == 0.0

    def test_normalize_unknown(self):
        """Unknown environment passes through."""
        media, o2 = normalize_environment("exotic atmosphere")
        assert media == "exotic atmosphere"
        assert o2 == 21.0

    def test_normalize_none(self):
        """None returns defaults."""
        media, o2 = normalize_environment(None)
        assert media is None
        assert o2 == 21.0


class TestLocationNormalization:
    """Tests for location class normalization."""

    def test_habitable(self):
        """Habitable location."""
        assert normalize_location("Habitable") == "habitable"
        assert normalize_location("habitable area") == "habitable"

    def test_non_habitable(self):
        """Non-habitable location."""
        assert normalize_location("Non-Habitable") == "non_habitable"
        assert normalize_location("nonhabitable") == "non_habitable"

    def test_none_defaults(self):
        """None defaults to non_habitable."""
        assert normalize_location(None) == "non_habitable"


class TestMinTemperatureDerivation:
    """Tests for minimum temperature derivation."""

    def test_lox_cryogenic(self):
        """LOX implies cryogenic min temp."""
        assert derive_min_temperature(100.0, "LOX") == -320.0

    def test_ln2_cryogenic(self):
        """LN2 implies cryogenic min temp."""
        assert derive_min_temperature(100.0, "LN2") == -320.0

    def test_lh2_cryogenic(self):
        """LH2 implies very cold min temp."""
        assert derive_min_temperature(100.0, "LH2") == -423.0

    def test_negative_max_temp(self):
        """Negative max temp derives range below."""
        assert derive_min_temperature(-100.0, "Air") == -150.0

    def test_default_room_temp(self):
        """Default to room temperature."""
        assert derive_min_temperature(200.0, "Air") == 70.0
        assert derive_min_temperature(None, None) == 70.0


class TestProgramFamilyDerivation:
    """Tests for program family derivation."""

    def test_orion(self):
        """Orion program."""
        assert derive_program_family("Orion MPCV") == ProgramFamily.ORION_ARTEMIS

    def test_artemis(self):
        """Artemis program."""
        assert derive_program_family("Artemis III") == ProgramFamily.ORION_ARTEMIS

    def test_sls(self):
        """SLS program."""
        assert derive_program_family("SLS Core Stage") == ProgramFamily.ORION_ARTEMIS

    def test_iss(self):
        """ISS program."""
        assert derive_program_family("ISS Node 2") == ProgramFamily.ISS

    def test_shuttle(self):
        """Shuttle program."""
        assert derive_program_family("STS-135") == ProgramFamily.SHUTTLE

    def test_commercial_crew(self):
        """Commercial crew."""
        assert derive_program_family("Crew Dragon") == ProgramFamily.COMMERCIAL_CREW

    def test_unknown(self):
        """Unknown returns OTHER."""
        assert derive_program_family("Unknown Project") == ProgramFamily.OTHER
        assert derive_program_family(None) == ProgramFamily.OTHER


class TestMaterialValidation:
    """Tests for material designation validation."""

    def test_valid_materials(self):
        """Valid material designations."""
        assert is_valid_material("CRES 316L") is True
        assert is_valid_material("Inconel 718") is True
        assert is_valid_material("AL 6061-T6") is True

    def test_invalid_na(self):
        """N/A is invalid."""
        assert is_valid_material("N/A") is False
        assert is_valid_material("n/a") is False

    def test_invalid_see(self):
        """'See...' references are invalid."""
        assert is_valid_material("See Application") is False
        assert is_valid_material("see drawing") is False

    def test_invalid_various(self):
        """'Various' is invalid."""
        assert is_valid_material("Various") is False

    def test_invalid_short(self):
        """Too short is invalid."""
        assert is_valid_material("A") is False
        assert is_valid_material("") is False

    def test_invalid_none(self):
        """None is invalid."""
        assert is_valid_material(None) is False


class TestMaterialHashKey:
    """Tests for material hash key generation."""

    def test_deterministic(self):
        """Same input = same hash."""
        key1 = generate_material_hash_key("316L CRES", "AMS 5648")
        key2 = generate_material_hash_key("316L CRES", "AMS 5648")
        assert key1 == key2

    def test_different_inputs(self):
        """Different inputs = different hash."""
        key1 = generate_material_hash_key("316L CRES", "AMS 5648")
        key2 = generate_material_hash_key("304L CRES", "AMS 5648")
        assert key1 != key2

    def test_prefix(self):
        """Hash key has MAT- prefix."""
        key = generate_material_hash_key("316L CRES")
        assert key.startswith("MAT-")

    def test_normalization(self):
        """Whitespace/case normalized before hashing."""
        key1 = generate_material_hash_key("316L CRES", "ams 5648")
        key2 = generate_material_hash_key("316L  CRES", "AMS 5648")
        # Should be same after normalization
        assert key1 == key2
