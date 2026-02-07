#!/usr/bin/env python3
"""
Shared pytest fixtures for MIRA v4 test suite.

BoundState AI 2026
Compliance: NASA-STD-8739.8B, SWE-013, SWE-032, SWE-033
Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1
"""

import sys
sys.path.insert(0, r"C:\BoundState")

from typing import List

import pytest

from mira_v4.models import (
    EnvironmentSpec,
    EvidenceRow,
    ParsedQuery,
    SafetyContext,
)


# =============================================================================
# Environment Fixtures
# =============================================================================


@pytest.fixture
def sample_environment() -> EnvironmentSpec:
    """Full environment with all 6 fields populated.

    Represents a LOX service environment at cryogenic temperature
    and elevated pressure -- a realistic O2-service test case.
    """
    return EnvironmentSpec(
        temperature_c=-200.0,
        pressure_kpa=5000.0,
        o2_pct=99.5,
        fluid_medium="LOX",
        duration_hr=1.0,
        cycles=10,
    )


@pytest.fixture
def empty_environment() -> EnvironmentSpec:
    """Environment with all fields None (maximum missing)."""
    return EnvironmentSpec()


@pytest.fixture
def partial_environment() -> EnvironmentSpec:
    """Environment with only temperature and fluid medium specified.

    4 of 6 fields are missing.
    """
    return EnvironmentSpec(
        temperature_c=-200.0,
        fluid_medium="LOX",
    )


# =============================================================================
# Evidence Fixtures
# =============================================================================


@pytest.fixture
def sample_evidence() -> List[EvidenceRow]:
    """5 clean evidence rows with test_year=2024."""
    return _make_evidence(n=5, test_year=2024, dirty=False)


@pytest.fixture
def dirty_evidence() -> List[EvidenceRow]:
    """10 evidence rows, 4 of which are dirty.

    dirty_fraction = 4/10 = 0.40 -> REFUSE tier.
    """
    return _make_dirty_evidence(n=10, dirty_count=4)


@pytest.fixture
def stale_evidence() -> List[EvidenceRow]:
    """3 evidence rows with test_year=1998 (stale data, >20yr)."""
    return _make_evidence(n=3, test_year=1998, dirty=False)


def _make_evidence(n: int, test_year: int, dirty: bool) -> List[EvidenceRow]:
    """Helper: create n EvidenceRow objects."""
    rows = []
    for i in range(n):
        rows.append(
            EvidenceRow(
                record_id=f"REC-{i:04d}",
                source="MAPTIS",
                data_class="direct_test",
                dirty_flag=dirty,
                dirty_fields=["tensile_strength"] if dirty else [],
                test_year=test_year,
            )
        )
    return rows


def _make_dirty_evidence(n: int, dirty_count: int) -> List[EvidenceRow]:
    """Helper: create n rows with dirty_count dirty records first."""
    rows = []
    for i in range(n):
        is_dirty = i < dirty_count
        rows.append(
            EvidenceRow(
                record_id=f"REC-{i:04d}",
                source="GRANTA",
                data_class="derived" if is_dirty else "direct_test",
                dirty_flag=is_dirty,
                dirty_fields=["tensile_strength"] if is_dirty else [],
                test_year=2024,
            )
        )
    return rows


# =============================================================================
# ParsedQuery Fixtures
# =============================================================================


@pytest.fixture
def safety_query(sample_environment: EnvironmentSpec) -> ParsedQuery:
    """Safety-critical O2 service query with full environment."""
    return ParsedQuery(
        raw_query="Find materials compatible with LOX at -200C and 5000 kPa",
        intent="material_compatibility",
        safety_context=SafetyContext.OXYGEN,
        environment=sample_environment,
        material_key="PTFE",
        filters={"fluid_medium": "LOX", "temperature_c": -200.0},
        batch_mode=False,
    )


@pytest.fixture
def general_query(partial_environment: EnvironmentSpec) -> ParsedQuery:
    """General search query with partial environment."""
    return ParsedQuery(
        raw_query="Search for tensile strength data",
        intent="general_search",
        safety_context=SafetyContext.GENERAL,
        environment=partial_environment,
        filters={"property": "tensile_strength"},
        batch_mode=False,
    )


@pytest.fixture
def batch_safety_query() -> ParsedQuery:
    """Batch mode O2 query with missing fields (pressure, o2_pct, duration, cycles)."""
    env = EnvironmentSpec(
        temperature_c=-200.0,
        fluid_medium="LOX",
    )
    return ParsedQuery(
        raw_query="Batch: LOX compatibility for PTFE at -200C",
        intent="material_compatibility",
        safety_context=SafetyContext.OXYGEN,
        environment=env,
        material_key="PTFE",
        filters={"fluid_medium": "LOX"},
        batch_mode=True,
    )
