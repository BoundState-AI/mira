#!/usr/bin/env python3
"""
Module: Boundary Checker
Purpose: from __future__ import annotations

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

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class BoundaryVerdict(Enum):
    """Deterministic boundary check verdicts."""
    WITHIN_LIMITS = "WITHIN_LIMITS"
    EXCEEDS_LIMIT = "EXCEEDS_LIMIT"
    BELOW_MINIMUM = "BELOW_MINIMUM"
    NO_DATA = "NO_DATA"
    REQUIRES_ANALYSIS = "REQUIRES_ANALYSIS"


@dataclass
class BOKLimit:
    """
    Structured BOK limit record.

    Represents a single limit extracted from BOK standards like:
    - "Aluminum alloys should not be used above 3000 psia in oxygen service"
    - "Titanium is prohibited above 100 psia in oxygen environments"
    """
    material_family: str  # e.g., "aluminum", "titanium", "stainless_steel"
    environment: str  # e.g., "oxygen", "hydrogen", "lox", "gox"
    limit_type: str  # "max_pressure", "min_pressure", "max_temp", "min_temp"
    limit_value: float
    units: str  # "psia", "psig", "degF", "degC"
    source_doc: str  # e.g., "NASA-STD-6016C", "JSC-27301F"
    section_ref: Optional[str] = None  # e.g., "4.3.2.1"
    configuration: Optional[str] = None  # e.g., "mesh", "solid", "filter"
    notes: Optional[str] = None


@dataclass
class BoundaryCheckResult:
    """
    Result of deterministic boundary check.

    This is the AUTHORITATIVE decision - LLM only explains this result.
    """
    verdict: BoundaryVerdict
    limit_checked: Optional[BOKLimit] = None
    query_value: Optional[float] = None
    margin: Optional[float] = None  # How far from the limit (positive = within, negative = exceeded)
    rationale: str = ""
    evidence_sources: List[str] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        """True if within all checked limits."""
        return self.verdict == BoundaryVerdict.WITHIN_LIMITS

    @property
    def is_prohibited(self) -> bool:
        """True if explicitly exceeds a limit."""
        return self.verdict in (BoundaryVerdict.EXCEEDS_LIMIT, BoundaryVerdict.BELOW_MINIMUM)


class BOKBoundaryChecker:
    """
    Deterministic boundary checker for BOK safety limits.

    This class implements pure rule-based checking with NO LLM involvement.
    All decisions are traceable to specific BOK limit records.

    Usage:
        checker = BOKBoundaryChecker()
        result = checker.check_pressure_limit(
            query_pressure=6000.0,
            material_family="aluminum",
            environment="oxygen"
        )
        if result.is_prohibited:
            # Decision is PROHIBITED - LLM only explains why
            pass
    """

    def __init__(self, limits: Optional[List[BOKLimit]] = None):
        """
        Initialize checker with BOK limits.

        Args:
            limits: Pre-loaded BOK limits. If None, uses hardcoded safety limits.
        """
        self.limits = limits or self._get_default_limits()
        self._build_limit_index()

    def _get_default_limits(self) -> List[BOKLimit]:
        """
        Default safety limits from NASA-STD-6016C and JSC-27301F.

        These are the most critical limits that must NEVER be exceeded.
        In production, these should come from bok_numeric_limits table.
        """
        return [
            # Aluminum limits (NASA-STD-6016C)
            BOKLimit(
                material_family="aluminum",
                environment="oxygen",
                limit_type="max_pressure",
                limit_value=3000.0,
                units="psia",
                source_doc="NASA-STD-6016C",
                section_ref="4.3.2.1",
                configuration="static",
                notes="Static service only; dynamic service limit is 100 psia"
            ),
            BOKLimit(
                material_family="aluminum",
                environment="oxygen",
                limit_type="max_pressure",
                limit_value=100.0,
                units="psia",
                source_doc="NASA-STD-6016C",
                section_ref="4.3.2.1",
                configuration="dynamic",
                notes="Dynamic service (valves, regulators, flow conditions)"
            ),

            # Titanium limits (NASA-STD-6016C)
            BOKLimit(
                material_family="titanium",
                environment="oxygen",
                limit_type="max_pressure",
                limit_value=100.0,
                units="psia",
                source_doc="NASA-STD-6016C",
                section_ref="4.3.3",
                notes="All configurations - titanium is highly reactive with oxygen"
            ),

            # Stainless steel 300-series limits
            BOKLimit(
                material_family="stainless_steel_300",
                environment="oxygen",
                limit_type="max_pressure",
                limit_value=10000.0,
                units="psia",
                source_doc="NASA-STD-6016C",
                section_ref="4.3.1",
                notes="Austenitic stainless steels - generally compatible"
            ),

            # Hydrogen limits (general metals)
            BOKLimit(
                material_family="carbon_steel",
                environment="hydrogen",
                limit_type="max_pressure",
                limit_value=1000.0,
                units="psia",
                source_doc="NASA-STD-8719.17",
                notes="Carbon steel susceptible to hydrogen embrittlement"
            ),

            # Temperature limits
            BOKLimit(
                material_family="aluminum",
                environment="cryogenic",
                limit_type="min_temp",
                limit_value=-320.0,
                units="degF",
                source_doc="NASA-STD-6016C",
                notes="Aluminum generally suitable for cryogenic service"
            ),
        ]

    def _build_limit_index(self) -> None:
        """Build lookup index for fast limit retrieval."""
        self._limit_index: Dict[str, List[BOKLimit]] = {}

        for limit in self.limits:
            key = f"{limit.material_family}:{limit.environment}"
            if key not in self._limit_index:
                self._limit_index[key] = []
            self._limit_index[key].append(limit)

    def _normalize_material_family(self, material: str) -> str:
        """
        Normalize material name to family category.

        Args:
            material: Raw material name like "SS 316L", "AL 6061-T6"

        Returns:
            Normalized family like "stainless_steel_300", "aluminum"
        """
        material_lower = material.lower().strip()

        # Stainless steel variants
        if any(x in material_lower for x in ['ss 3', 'cres 3', 'stainless steel 3', '316', '304', '321', '347']):
            return "stainless_steel_300"
        if any(x in material_lower for x in ['ss 4', 'stainless steel 4', '410', '440']):
            return "stainless_steel_400"
        if any(x in material_lower for x in ['ss', 'stainless', 'cres']):
            return "stainless_steel"

        # Aluminum
        if any(x in material_lower for x in ['al ', 'aluminum', '6061', '7075', '2024']):
            return "aluminum"

        # Titanium
        if any(x in material_lower for x in ['ti ', 'titanium', 'ti-6al']):
            return "titanium"

        # Nickel alloys
        if any(x in material_lower for x in ['monel', 'inconel', 'hastelloy', 'nickel']):
            return "nickel_alloy"

        # Copper alloys
        if any(x in material_lower for x in ['copper', 'brass', 'bronze', 'beryllium copper']):
            return "copper_alloy"

        # Carbon steel
        if any(x in material_lower for x in ['carbon steel', 'a36', '1018', '4130', '4340']):
            return "carbon_steel"

        return "unknown"

    def _normalize_environment(self, environment: str) -> str:
        """
        Normalize environment name.

        Args:
            environment: Raw environment like "GOX", "LO2", "GH2"

        Returns:
            Normalized environment like "oxygen", "hydrogen"
        """
        env_lower = environment.lower().strip()

        # Oxygen variants
        if any(x in env_lower for x in ['oxygen', 'o2', 'gox', 'lox', 'lo2']):
            return "oxygen"

        # Hydrogen variants
        if any(x in env_lower for x in ['hydrogen', 'h2', 'gh2', 'lh2']):
            return "hydrogen"

        # Cryogenic
        if any(x in env_lower for x in ['cryo', 'ln2', 'liquid nitrogen']):
            return "cryogenic"

        return env_lower

    def get_applicable_limits(
        self,
        material: str,
        environment: str,
        configuration: Optional[str] = None
    ) -> List[BOKLimit]:
        """
        Get all BOK limits applicable to a material/environment combination.

        Args:
            material: Material name (will be normalized to family)
            environment: Environment name (will be normalized)
            configuration: Optional configuration (mesh, solid, etc.)

        Returns:
            List of applicable BOKLimit records
        """
        family = self._normalize_material_family(material)
        env = self._normalize_environment(environment)

        key = f"{family}:{env}"
        limits = self._limit_index.get(key, [])

        # Filter by configuration if specified
        if configuration and limits:
            config_lower = configuration.lower()
            config_limits = [
                lim for lim in limits
                if lim.configuration is None or lim.configuration.lower() == config_lower
            ]
            if config_limits:
                return config_limits

        return limits

    def check_pressure_limit(
        self,
        query_pressure: float,
        material: str,
        environment: str,
        configuration: Optional[str] = None,
        pressure_units: str = "psia"
    ) -> BoundaryCheckResult:
        """
        Check if query pressure is within BOK limits.

        This is the PRIMARY deterministic check for pressure safety.

        Args:
            query_pressure: Pressure value from user query
            material: Material name
            environment: Operating environment
            configuration: Optional configuration (static, dynamic, mesh, etc.)
            pressure_units: Units of query pressure (psia, psig)

        Returns:
            BoundaryCheckResult with deterministic verdict
        """
        # Normalize pressure to psia if needed
        if pressure_units.lower() == "psig":
            query_pressure = query_pressure + 14.7  # Convert to psia

        # Get applicable limits
        limits = self.get_applicable_limits(material, environment, configuration)

        if not limits:
            family = self._normalize_material_family(material)
            return BoundaryCheckResult(
                verdict=BoundaryVerdict.NO_DATA,
                query_value=query_pressure,
                rationale=f"No BOK pressure limits found for {family} in {environment} service",
                evidence_sources=[]
            )

        # Check against max pressure limits
        for limit in limits:
            if limit.limit_type == "max_pressure":
                margin = limit.limit_value - query_pressure

                if query_pressure > limit.limit_value:
                    return BoundaryCheckResult(
                        verdict=BoundaryVerdict.EXCEEDS_LIMIT,
                        limit_checked=limit,
                        query_value=query_pressure,
                        margin=margin,
                        rationale=(
                            f"Query pressure {query_pressure} psia EXCEEDS "
                            f"BOK limit of {limit.limit_value} psia for "
                            f"{limit.material_family} in {limit.environment} service. "
                            f"Source: {limit.source_doc}"
                            + (f" Section {limit.section_ref}" if limit.section_ref else "")
                        ),
                        evidence_sources=[
                            f"{limit.source_doc}" + (f" {limit.section_ref}" if limit.section_ref else "")
                        ]
                    )
                else:
                    return BoundaryCheckResult(
                        verdict=BoundaryVerdict.WITHIN_LIMITS,
                        limit_checked=limit,
                        query_value=query_pressure,
                        margin=margin,
                        rationale=(
                            f"Query pressure {query_pressure} psia is within "
                            f"BOK limit of {limit.limit_value} psia for "
                            f"{limit.material_family} in {limit.environment} service "
                            f"(margin: {margin:.1f} psia). Source: {limit.source_doc}"
                        ),
                        evidence_sources=[
                            f"{limit.source_doc}" + (f" {limit.section_ref}" if limit.section_ref else "")
                        ]
                    )

        return BoundaryCheckResult(
            verdict=BoundaryVerdict.REQUIRES_ANALYSIS,
            query_value=query_pressure,
            rationale="Pressure limits found but no max_pressure limit applicable",
            evidence_sources=[lim.source_doc for lim in limits]
        )

    def check_temperature_limit(
        self,
        query_temp: float,
        material: str,
        environment: str,
        temp_units: str = "degF"
    ) -> BoundaryCheckResult:
        """
        Check if query temperature is within BOK limits.

        Args:
            query_temp: Temperature value from user query
            material: Material name
            environment: Operating environment
            temp_units: Units (degF, degC)

        Returns:
            BoundaryCheckResult with deterministic verdict
        """
        # Convert to Fahrenheit if needed
        if temp_units.lower() in ["degc", "c", "celsius"]:
            query_temp = (query_temp * 9/5) + 32

        limits = self.get_applicable_limits(material, environment)

        if not limits:
            return BoundaryCheckResult(
                verdict=BoundaryVerdict.NO_DATA,
                query_value=query_temp,
                rationale=f"No BOK temperature limits found for {material} in {environment} service"
            )

        # Check min temp limits (cryogenic)
        for limit in limits:
            if limit.limit_type == "min_temp":
                if query_temp < limit.limit_value:
                    return BoundaryCheckResult(
                        verdict=BoundaryVerdict.BELOW_MINIMUM,
                        limit_checked=limit,
                        query_value=query_temp,
                        margin=query_temp - limit.limit_value,
                        rationale=(
                            f"Query temperature {query_temp}F is BELOW "
                            f"minimum limit of {limit.limit_value}F. Source: {limit.source_doc}"
                        ),
                        evidence_sources=[limit.source_doc]
                    )

        # Check max temp limits
        for limit in limits:
            if limit.limit_type == "max_temp":
                if query_temp > limit.limit_value:
                    return BoundaryCheckResult(
                        verdict=BoundaryVerdict.EXCEEDS_LIMIT,
                        limit_checked=limit,
                        query_value=query_temp,
                        margin=limit.limit_value - query_temp,
                        rationale=(
                            f"Query temperature {query_temp}F EXCEEDS "
                            f"maximum limit of {limit.limit_value}F. Source: {limit.source_doc}"
                        ),
                        evidence_sources=[limit.source_doc]
                    )

        return BoundaryCheckResult(
            verdict=BoundaryVerdict.WITHIN_LIMITS,
            query_value=query_temp,
            rationale="Temperature within applicable BOK limits",
            evidence_sources=[lim.source_doc for lim in limits if lim.limit_type in ["min_temp", "max_temp"]]
        )

    def check_all_limits(
        self,
        material: str,
        environment: str,
        pressure: Optional[float] = None,
        temperature: Optional[float] = None,
        configuration: Optional[str] = None,
        pressure_units: str = "psia",
        temp_units: str = "degF"
    ) -> List[BoundaryCheckResult]:
        """
        Check all applicable limits for a material query.

        Args:
            material: Material name
            environment: Operating environment
            pressure: Optional pressure value
            temperature: Optional temperature value
            configuration: Optional configuration
            pressure_units: Pressure units
            temp_units: Temperature units

        Returns:
            List of BoundaryCheckResult for each applicable limit
        """
        results = []

        if pressure is not None:
            results.append(
                self.check_pressure_limit(
                    pressure, material, environment, configuration, pressure_units
                )
            )

        if temperature is not None:
            results.append(
                self.check_temperature_limit(
                    temperature, material, environment, temp_units
                )
            )

        return results

    def get_worst_result(self, results: List[BoundaryCheckResult]) -> Optional[BoundaryCheckResult]:
        """
        Get the most restrictive result from a list of checks.

        Priority: EXCEEDS_LIMIT > BELOW_MINIMUM > NO_DATA > REQUIRES_ANALYSIS > WITHIN_LIMITS
        """
        if not results:
            return None

        priority = {
            BoundaryVerdict.EXCEEDS_LIMIT: 0,
            BoundaryVerdict.BELOW_MINIMUM: 1,
            BoundaryVerdict.NO_DATA: 2,
            BoundaryVerdict.REQUIRES_ANALYSIS: 3,
            BoundaryVerdict.WITHIN_LIMITS: 4,
        }

        return min(results, key=lambda r: priority.get(r.verdict, 5))


# Module-level convenience function
_default_checker: Optional[BOKBoundaryChecker] = None


def get_boundary_checker() -> BOKBoundaryChecker:
    """Get or create the default boundary checker instance."""
    global _default_checker
    if _default_checker is None:
        _default_checker = BOKBoundaryChecker()
    return _default_checker


def check_material_boundary(
    material: str,
    environment: str,
    pressure: Optional[float] = None,
    temperature: Optional[float] = None,
    configuration: Optional[str] = None
) -> BoundaryCheckResult:
    """
    Convenience function for quick boundary checks.

    Args:
        material: Material name
        environment: Operating environment
        pressure: Optional pressure in psia
        temperature: Optional temperature in degF
        configuration: Optional configuration

    Returns:
        Most restrictive BoundaryCheckResult
    """
    checker = get_boundary_checker()
    results = checker.check_all_limits(
        material=material,
        environment=environment,
        pressure=pressure,
        temperature=temperature,
        configuration=configuration
    )

    if not results:
        return BoundaryCheckResult(
            verdict=BoundaryVerdict.NO_DATA,
            rationale="No boundary conditions provided to check"
        )

    return checker.get_worst_result(results) or results[0]
