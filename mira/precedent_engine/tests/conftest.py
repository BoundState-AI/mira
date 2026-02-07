#!/usr/bin/env python3
"""
Module: Conftest
Purpose: [Automatically migrated - needs manual review]

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

from datetime import date
from typing import Literal

import pytest

from mira.precedent_engine.models.config import (
    EngineConfig,
    PrecedentAdequacyConfig,
    PrecedentEquivalenceConfig,
)
from mira.precedent_engine.models.enriched import EnrichedMUA
from mira.precedent_engine.models.enums import DeviationType, ProgramFamily
import uuid


@pytest.fixture
def default_config() -> EngineConfig:
    """Default engine configuration for testing."""
    return EngineConfig()


@pytest.fixture
def default_equivalence_config() -> PrecedentEquivalenceConfig:
    """Default equivalence configuration for testing."""
    return PrecedentEquivalenceConfig()


@pytest.fixture
def default_adequacy_config() -> PrecedentAdequacyConfig:
    """Default adequacy configuration for testing."""
    return PrecedentAdequacyConfig()


def make_enriched_mua(
    contract_id: str = "TEST-001",
    material_name: str = "CRES 316L",
    material_key: str | None = "SS316L",
    media: str | None = "GOX",
    o2_pct: float = 99.5,
    location_class: Literal["habitable", "non_habitable"] = "non_habitable",
    temp_max_f: float | None = 500.0,
    temp_min_f: float = 70.0,
    pressure_max_psia: float | None = 3000.0,
    deviation_types: list[DeviationType] | None = None,
    is_rejected: bool = False,
    is_usable_precedent: bool = True,
    program: str | None = "Orion",
    program_family: ProgramFamily = ProgramFamily.ORION_ARTEMIS,
    rationale_text: str | None = "Test rationale text.",
    approval_date: date | None = None,
    category: Literal["I", "II", "III"] | None = "I",
) -> EnrichedMUA:
    """Factory function to create EnrichedMUA for testing."""
    return EnrichedMUA(
        contract_id=contract_id,
        source_file="test.json",
        material_name=material_name,
        material_key=material_key,
        media=media,
        o2_pct=o2_pct,
        location_class=location_class,
        temp_max_f=temp_max_f,
        temp_min_f=temp_min_f,
        pressure_max_psia=pressure_max_psia,
        deviation_types=deviation_types or [DeviationType.FLAMMABILITY],
        is_rejected=is_rejected,
        is_usable_precedent=is_usable_precedent,
        program=program,
        program_family=program_family,
        rationale_text=rationale_text,
        approval_date=approval_date,
        category=category,
    )


@pytest.fixture
def sample_query() -> EnrichedMUA:
    """Sample query MUA for testing."""
    return make_enriched_mua(
        contract_id="QUERY-001",
        material_key="SS316L",
        media="GOX",
        temp_max_f=500.0,
        pressure_max_psia=3000.0,
        deviation_types=[DeviationType.FLAMMABILITY],
    )


@pytest.fixture
def sample_tier1_candidate() -> EnrichedMUA:
    """Sample Tier 1 candidate (exact match)."""
    return make_enriched_mua(
        contract_id="CAND-TIER1-001",
        material_key="SS316L",
        media="GOX",
        temp_max_f=500.0,
        pressure_max_psia=3000.0,
        deviation_types=[DeviationType.FLAMMABILITY],
    )


@pytest.fixture
def sample_tier2_candidate() -> EnrichedMUA:
    """Sample Tier 2 candidate (same material, different environment)."""
    return make_enriched_mua(
        contract_id="CAND-TIER2-001",
        material_key="SS316L",
        media="GOX",
        temp_max_f=300.0,  # Different temp
        pressure_max_psia=2000.0,  # Different pressure
        deviation_types=[DeviationType.FLAMMABILITY],
    )


@pytest.fixture
def sample_tier3_candidate() -> EnrichedMUA:
    """Sample Tier 3 candidate (analog - different material)."""
    return make_enriched_mua(
        contract_id="CAND-TIER3-001",
        material_key="SS304L",  # Different material
        media="GOX",
        temp_max_f=500.0,
        pressure_max_psia=3000.0,
        deviation_types=[DeviationType.FLAMMABILITY],
    )


@pytest.fixture
def sample_rejected_candidate() -> EnrichedMUA:
    """Sample rejected MUA (should be Tier 3 at best)."""
    return make_enriched_mua(
        contract_id="CAND-REJECTED-001",
        material_key="SS316L",
        is_rejected=True,
        is_usable_precedent=False,
    )
