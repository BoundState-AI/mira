#!/usr/bin/env python3
"""
Module: Engine
Purpose: ATHENA Query Engine.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from athena.interpreters.models.requirement import (
    RequirementRecord,
    RequirementType,
    VerdictType,
)

__all__ = [
    "QueryEngine",
    "CompatibilityQuery",
    "ExpertVerdict",
    "Citation",
    "VerdictType",
]
__safety_critical__ = True

logger = logging.getLogger(__name__)


class Citation(BaseModel):
    """Citation to a source document."""
    document: str
    section: str
    page: int
    requirement_text: str


class CompatibilityQuery(BaseModel):
    """Query for materials compatibility assessment."""
    material: str = Field(..., description="Material name or specification")
    environment: str = Field(..., description="Environment: GOX, LOX, O2, etc.")
    pressure_psi: Optional[float] = Field(None, description="Operating pressure in PSI")
    temperature_f: Optional[float] = Field(None, description="Operating temperature in °F")
    application: Optional[str] = Field(None, description="Application context")


class ExpertVerdict(BaseModel):
    """Expert system verdict for a compatibility query."""
    query: CompatibilityQuery
    verdict: VerdictType
    confidence: float = Field(ge=0.0, le=1.0)

    # Conditions/requirements that must be met
    conditions: list[str] = Field(default_factory=list)

    # Matching requirements with citations
    citations: list[Citation] = Field(default_factory=list)

    # Prohibitions (if verdict is NO)
    prohibitions: list[str] = Field(default_factory=list)

    # Recommendations for further action
    recommendations: list[str] = Field(default_factory=list)

    # Number of requirements evaluated
    requirements_matched: int = 0
    requirements_total: int = 0

    def to_natural_language(self) -> str:
        """Generate natural language response."""
        lines = []

        # Main verdict
        if self.verdict == VerdictType.YES:
            lines.append(f"**YES** - {self.query.material} is compatible with {self.query.environment}.")
        elif self.verdict == VerdictType.YES_WITH_CONDITIONS:
            lines.append(f"**YES, with conditions** - {self.query.material} can be used in {self.query.environment}:")
            for cond in self.conditions:
                lines.append(f"  • {cond}")
        elif self.verdict == VerdictType.MAYBE:
            lines.append(f"**MAYBE** - More information needed for {self.query.material} in {self.query.environment}:")
            for rec in self.recommendations:
                lines.append(f"  • {rec}")
        elif self.verdict == VerdictType.NO:
            lines.append(f"**NO** - {self.query.material} is NOT recommended for {self.query.environment}:")
            for prob in self.prohibitions:
                lines.append(f"  • {prob}")

        # Citations
        if self.citations:
            lines.append("\n**References:**")
            for cite in self.citations[:5]:  # Limit to 5
                lines.append(f"  - {cite.document} §{cite.section} (p.{cite.page})")

        return "\n".join(lines)


class QueryEngine:
    """
    Query engine for materials compatibility.

    Loads RequirementRecords and answers queries about material compatibility.
    No API calls needed - purely structure-based lookup.
    """

    def __init__(self):
        self.requirements: list[RequirementRecord] = []
        self.logger = logging.getLogger(self.__class__.__name__)

    def load_requirements(self, source: str | Path | list[RequirementRecord]) -> int:
        """
        Load requirements from JSON file or list.

        Args:
            source: Path to JSON file or list of RequirementRecords

        Returns:
            Number of requirements loaded
        """
        if isinstance(source, list):
            self.requirements.extend(source)
            return len(source)

        source = Path(source)
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Handle both formats: direct list or wrapped in "requirements" key
        req_data = data.get("requirements", data)
        if not isinstance(req_data, list):
            raise ValueError("Expected list of requirements")

        for raw in req_data:
            try:
                # Remove computed fields that shouldn't be passed to constructor
                clean = {k: v for k, v in raw.items() if k not in (
                    "is_prohibitive", "has_test_requirement", "has_cleaning_requirement", "is_complete"
                )}
                record = RequirementRecord(**clean)
                self.requirements.append(record)
            except Exception as e:
                self.logger.warning(f"Failed to parse requirement: {e}")

        self.logger.info(f"Loaded {len(self.requirements)} requirements from {source}")
        return len(self.requirements)

    def query(self, query: CompatibilityQuery) -> ExpertVerdict:
        """
        Query for compatibility verdict.

        Args:
            query: Compatibility query

        Returns:
            ExpertVerdict with verdict and citations
        """
        self.logger.info(
            f"Query: {query.material} in {query.environment} "
            f"@ {query.pressure_psi} psi"
        )

        # Find matching requirements
        matching = self._find_matching_requirements(query)

        # Build verdict
        verdict = self._build_verdict(query, matching)

        self.logger.info(
            f"  -> {verdict.verdict.value} "
            f"({verdict.requirements_matched}/{len(self.requirements)} matched)"
        )

        return verdict

    def _find_matching_requirements(
        self,
        query: CompatibilityQuery,
    ) -> list[RequirementRecord]:
        """Find requirements that match the query."""
        matching = []

        for req in self.requirements:
            if req.matches_query(
                material=query.material,
                environment=query.environment,
                pressure_psi=query.pressure_psi,
            ):
                matching.append(req)

        return matching

    def _build_verdict(
        self,
        query: CompatibilityQuery,
        matching: list[RequirementRecord],
    ) -> ExpertVerdict:
        """Build verdict from matching requirements."""
        conditions = []
        prohibitions = []
        recommendations = []
        citations = []

        # Analyze matching requirements
        has_prohibition = False
        has_testing_req = False
        has_cleaning_req = False

        for req in matching:
            # Build citation
            cite = Citation(
                document=req.source_document,
                section=req.section,
                page=req.page,
                requirement_text=req.requirement_text,
            )
            citations.append(cite)

            # Check requirement type
            if req.requirement_type == RequirementType.PROHIBITION:
                has_prohibition = True
                prohibitions.append(req.requirement_text)

            elif req.requirement_type == RequirementType.TESTING:
                has_testing_req = True
                if req.test_method:
                    conditions.append(f"Test per {req.test_method}")
                else:
                    conditions.append(req.requirement_text)

            elif req.requirement_type == RequirementType.CLEANING:
                has_cleaning_req = True
                if req.cleaning_spec:
                    conditions.append(f"Clean per {req.cleaning_spec}")
                else:
                    conditions.append(req.requirement_text)

            elif req.has_test_requirement:
                has_testing_req = True
                if req.test_method:
                    conditions.append(f"Verify per {req.test_method}")

            elif req.has_cleaning_requirement:
                has_cleaning_req = True
                if req.cleaning_spec:
                    conditions.append(f"Clean per {req.cleaning_spec}")

        # Determine verdict
        if has_prohibition:
            verdict_type = VerdictType.NO
        elif not matching:
            # No matching requirements - need more info
            verdict_type = VerdictType.MAYBE
            recommendations.append(
                f"No specific requirements found for {query.material} in {query.environment}"
            )
            recommendations.append("Consult materials engineer for guidance")
        elif conditions:
            verdict_type = VerdictType.YES_WITH_CONDITIONS
        else:
            verdict_type = VerdictType.YES

        # Confidence based on number of matching requirements
        if not matching:
            confidence = 0.3  # Low - no data
        elif len(matching) >= 3:
            confidence = 0.95  # High - multiple sources agree
        elif len(matching) >= 1:
            confidence = 0.75  # Medium - some data
        else:
            confidence = 0.5

        return ExpertVerdict(
            query=query,
            verdict=verdict_type,
            confidence=confidence,
            conditions=list(set(conditions)),  # Dedupe
            citations=citations,
            prohibitions=prohibitions,
            recommendations=recommendations,
            requirements_matched=len(matching),
            requirements_total=len(self.requirements),
        )

    def query_natural(
        self,
        material: str,
        environment: str,
        pressure_psi: Optional[float] = None,
        temperature_f: Optional[float] = None,
    ) -> str:
        """
        Natural language query interface.

        Args:
            material: Material name
            environment: Environment (GOX, LOX, etc.)
            pressure_psi: Optional pressure
            temperature_f: Optional temperature

        Returns:
            Natural language response
        """
        query = CompatibilityQuery(
            material=material,
            environment=environment,
            pressure_psi=pressure_psi,
            temperature_f=temperature_f,
        )
        verdict = self.query(query)
        return verdict.to_natural_language()
