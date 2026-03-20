#!/usr/bin/env python3
"""
Module: Draft Generator
Purpose: V6 MUA Draft Generator - Generate MUA drafts from precedent matches.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-033 (Safety-critical)
Safety Critical: True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .precedent_models import CleanedMUARecord, IssueCategory, EnvironmentType

logger = logging.getLogger(__name__)

__all__ = ["MUADraftRequest", "MUADraft", "DraftGenerator", "generate_mua_draft"]


@dataclass
class MUADraftRequest:
    """Request for MUA draft generation."""

    material_designation: str
    environment_description: str
    application: str
    o2_percent: Optional[float] = None
    pressure_psia: Optional[float] = None
    temperature_f: Optional[float] = None
    is_habitable: bool = False
    issues: List[str] = field(default_factory=list)


@dataclass
class PrecedentCitation:
    """Citation of a precedent MUA used in draft."""

    mua_number: str
    material: str
    environment: str
    determination: str
    relevance_score: float
    rationale_excerpt: str


@dataclass
class MUADraft:
    """Generated MUA draft with provenance."""

    # Request info
    material: str
    environment: str
    application: str

    # Generated content
    recommended_determination: str
    confidence: float
    rationale: str
    issues_addressed: List[str]

    # Provenance
    precedents_cited: List[PrecedentCitation]
    coverage_assessment: str
    gaps_identified: List[str]

    # Warnings
    warnings: List[str] = field(default_factory=list)


class DraftGenerator:
    """Generate MUA drafts from precedent matches."""

    # Minimum precedents needed for confident recommendation
    MIN_PRECEDENTS_HIGH_CONF = 3
    MIN_PRECEDENTS_MEDIUM_CONF = 1

    # Score thresholds (cosine similarity - lower thresholds to include more results)
    HIGH_RELEVANCE_THRESHOLD = 0.60
    MEDIUM_RELEVANCE_THRESHOLD = 0.40

    def __init__(self):
        self._issue_templates = self._build_issue_templates()

    def _build_issue_templates(self) -> dict:
        """Build rationale templates for each issue category."""
        return {
            IssueCategory.FLAMMABILITY: (
                "Flammability assessment based on {num_precedents} historic precedent(s). "
                "{material} has demonstrated acceptable flammability characteristics in "
                "similar oxygen environments per {citations}."
            ),
            IssueCategory.CORROSION: (
                "Corrosion resistance evaluated per historic usage. "
                "The material will be protected by {protection} as demonstrated in {citations}."
            ),
            IssueCategory.STRESS_CORROSION_CRACKING: (
                "Stress corrosion cracking (SCC) resistance verified. "
                "{material} is rated for SCC resistance per MSFC-SPEC-522A, "
                "consistent with precedent usage in {citations}."
            ),
            IssueCategory.TOXICITY: (
                "Toxicity assessment per NHB 8060.1. Material meets toxicity requirements "
                "as demonstrated in {citations}."
            ),
            IssueCategory.OFFGASSING: (
                "Offgassing characteristics acceptable based on {citations}."
            ),
            IssueCategory.OXYGEN_COMPATIBILITY: (
                "Oxygen compatibility established through precedent usage in {citations}. "
                "Material has demonstrated safe operation in oxygen-enriched environments."
            ),
        }

    def generate_draft(
        self,
        request: MUADraftRequest,
        precedents: List[Tuple[CleanedMUARecord, float]],
    ) -> MUADraft:
        """Generate MUA draft from request and precedent matches.

        Args:
            request: MUA draft request with material/environment/application
            precedents: List of (record, score) tuples from FAISS search

        Returns:
            MUADraft with synthesized rationale and provenance
        """
        if not precedents:
            return self._generate_no_precedent_draft(request)

        # Filter to relevant precedents
        relevant = [
            (rec, score) for rec, score in precedents
            if score >= self.MEDIUM_RELEVANCE_THRESHOLD
        ]

        if not relevant:
            relevant = precedents[:3]  # Use top 3 even if below threshold

        # Analyze precedent coverage
        coverage = self._analyze_coverage(request, relevant)

        # Determine recommendation
        determination, confidence = self._determine_recommendation(relevant, coverage)

        # Build citations
        citations = self._build_citations(relevant[:5])  # Top 5

        # Synthesize rationale
        rationale = self._synthesize_rationale(request, relevant, coverage)

        # Identify gaps
        gaps = self._identify_gaps(request, relevant, coverage)

        # Build warnings
        warnings = self._build_warnings(request, relevant, coverage, confidence)

        # Build environment string
        env_parts = [request.environment_description]
        if request.o2_percent:
            env_parts.append(f"{request.o2_percent}% O2")
        if request.pressure_psia:
            env_parts.append(f"{request.pressure_psia} PSIA")
        env_str = ", ".join(env_parts)

        return MUADraft(
            material=request.material_designation,
            environment=env_str,
            application=request.application,
            recommended_determination=determination,
            confidence=confidence,
            rationale=rationale,
            issues_addressed=coverage["issues_covered"],
            precedents_cited=citations,
            coverage_assessment=coverage["assessment"],
            gaps_identified=gaps,
            warnings=warnings,
        )

    def _analyze_coverage(
        self,
        request: MUADraftRequest,
        precedents: List[Tuple[CleanedMUARecord, float]],
    ) -> dict:
        """Analyze how well precedents cover the request."""
        coverage = {
            "material_match": False,
            "environment_match": False,
            "issues_covered": [],
            "approved_count": 0,
            "total_count": len(precedents),
            "assessment": "",
        }

        request_mat_lower = request.material_designation.lower()

        for rec, score in precedents:
            # Check material match
            rec_mat_lower = rec.material_designation.lower()
            if (request_mat_lower in rec_mat_lower or
                rec_mat_lower in request_mat_lower or
                self._same_alloy_family(request_mat_lower, rec_mat_lower)):
                coverage["material_match"] = True

            # Check environment match
            if request.o2_percent and rec.environment.o2_percent:
                if abs(request.o2_percent - rec.environment.o2_percent) <= 5:
                    coverage["environment_match"] = True

            # Track issues covered
            for issue in rec.issues:
                if issue.value not in coverage["issues_covered"]:
                    coverage["issues_covered"].append(issue.value)

            # Count approved
            if rec.determination == "APPROVED":
                coverage["approved_count"] += 1

        # Build assessment
        if coverage["material_match"] and coverage["environment_match"]:
            coverage["assessment"] = "STRONG - Direct material and environment match found"
        elif coverage["material_match"]:
            coverage["assessment"] = "MODERATE - Material match found, environment extrapolation needed"
        elif coverage["environment_match"]:
            coverage["assessment"] = "MODERATE - Environment match found, material family similar"
        else:
            coverage["assessment"] = "WEAK - Precedents are analogous but not direct matches"

        return coverage

    def _same_alloy_family(self, mat1: str, mat2: str) -> bool:
        """Check if two materials are in the same alloy family."""
        # Extract alloy series numbers
        import re

        # Aluminum alloy series (2xxx, 6xxx, 7xxx)
        al_pattern = r'\b([2567]\d{3})'
        m1 = re.search(al_pattern, mat1)
        m2 = re.search(al_pattern, mat2)
        if m1 and m2:
            # Same series (first digit)
            return m1.group(1)[0] == m2.group(1)[0]

        # Stainless steel (3xx, 4xx)
        ss_pattern = r'\b([34]\d{2})'
        m1 = re.search(ss_pattern, mat1)
        m2 = re.search(ss_pattern, mat2)
        if m1 and m2:
            return m1.group(1)[0] == m2.group(1)[0]

        return False

    def _determine_recommendation(
        self,
        precedents: List[Tuple[CleanedMUARecord, float]],
        coverage: dict,
    ) -> Tuple[str, float]:
        """Determine recommended determination and confidence."""
        if not precedents:
            return "REQUIRES_REVIEW", 0.0

        approved_ratio = coverage["approved_count"] / coverage["total_count"]

        # High confidence: many approved precedents with good coverage
        if (coverage["approved_count"] >= self.MIN_PRECEDENTS_HIGH_CONF and
            approved_ratio >= 0.8 and
            coverage["material_match"]):
            return "APPROVED", min(0.95, 0.7 + approved_ratio * 0.25)

        # Medium confidence: some approved precedents
        if (coverage["approved_count"] >= self.MIN_PRECEDENTS_MEDIUM_CONF and
            approved_ratio >= 0.5):
            confidence = 0.5 + approved_ratio * 0.3
            if coverage["material_match"]:
                confidence += 0.1
            return "APPROVED", min(0.85, confidence)

        # Low confidence: weak precedent support
        if coverage["approved_count"] > 0:
            return "CONDITIONAL", 0.4 + approved_ratio * 0.2

        return "REQUIRES_REVIEW", 0.3

    def _build_citations(
        self,
        precedents: List[Tuple[CleanedMUARecord, float]],
    ) -> List[PrecedentCitation]:
        """Build formatted citations from precedents."""
        citations = []
        for rec, score in precedents:
            excerpt = rec.rationale[:200] + "..." if len(rec.rationale) > 200 else rec.rationale
            citations.append(PrecedentCitation(
                mua_number=rec.mua_number,
                material=rec.material_designation,
                environment=rec.environment.envelope_str(),
                determination=rec.determination,
                relevance_score=score,
                rationale_excerpt=excerpt,
            ))
        return citations

    def _synthesize_rationale(
        self,
        request: MUADraftRequest,
        precedents: List[Tuple[CleanedMUARecord, float]],
        coverage: dict,
    ) -> str:
        """Synthesize rationale from precedents."""
        sections = []

        # Opening
        mua_numbers = [rec.mua_number for rec, _ in precedents[:3]]
        sections.append(
            f"This Material Usage Agreement for {request.material_designation} in "
            f"{request.environment_description} is supported by {len(precedents)} "
            f"historic precedent(s), including {', '.join(mua_numbers)}."
        )

        # Coverage assessment
        sections.append(f"\nPrecedent Coverage: {coverage['assessment']}")

        # Issue-specific rationale
        if coverage["issues_covered"]:
            sections.append(f"\nIssues Addressed: {', '.join(coverage['issues_covered'])}")

        # Pull key rationale excerpts from best matches
        sections.append("\n--- Supporting Rationale from Precedents ---")
        for rec, score in precedents[:3]:
            if rec.rationale:
                excerpt = rec.rationale[:300].replace('\n', ' ').replace('\r', '')
                sections.append(f"\n[{rec.mua_number}] ({rec.determination}): {excerpt}")

        # Conclusion
        approved_count = coverage["approved_count"]
        if approved_count > 0:
            sections.append(
                f"\n\nBased on {approved_count} approved precedent(s), the material "
                f"is recommended for approval subject to the conditions established "
                f"in the cited MUAs."
            )
        else:
            sections.append(
                "\n\nNo directly approved precedents found. Engineering review required."
            )

        return "\n".join(sections)

    def _identify_gaps(
        self,
        request: MUADraftRequest,
        precedents: List[Tuple[CleanedMUARecord, float]],
        coverage: dict,
    ) -> List[str]:
        """Identify gaps in precedent coverage."""
        gaps = []

        if not coverage["material_match"]:
            gaps.append("No exact material match - precedents are from similar alloy families")

        if not coverage["environment_match"]:
            if request.o2_percent and request.o2_percent > 21:
                gaps.append(f"No precedent at {request.o2_percent}% O2 - may require additional testing")

        if request.pressure_psia:
            max_prec_pressure = max(
                (rec.environment.pressure_psia or 0 for rec, _ in precedents),
                default=0
            )
            if request.pressure_psia > max_prec_pressure * 1.2:
                gaps.append(f"Requested pressure ({request.pressure_psia} PSIA) exceeds precedent envelope")

        # Check for missing issue coverage
        requested_issues = set(request.issues)
        covered_issues = set(coverage["issues_covered"])
        missing = requested_issues - covered_issues
        if missing:
            gaps.append(f"Issues not covered by precedents: {', '.join(missing)}")

        return gaps

    def _build_warnings(
        self,
        request: MUADraftRequest,
        precedents: List[Tuple[CleanedMUARecord, float]],
        coverage: dict,
        confidence: float,
    ) -> List[str]:
        """Build warning messages for the draft."""
        warnings = []

        if confidence < 0.5:
            warnings.append("LOW CONFIDENCE - Limited precedent support, engineering review strongly recommended")

        if coverage["approved_count"] == 0:
            warnings.append("NO APPROVED PRECEDENTS - Cannot recommend approval based on precedent alone")

        # Check for conflicting determinations
        determinations = [rec.determination for rec, _ in precedents]
        if "REJECTED" in determinations:
            warnings.append("CONFLICTING PRECEDENT - At least one precedent was REJECTED for similar material/environment")

        if request.is_habitable and not any(rec.environment.is_habitable for rec, _ in precedents):
            warnings.append("HABITABLE APPLICATION - No habitable-environment precedents found, additional scrutiny required")

        return warnings

    def _generate_no_precedent_draft(self, request: MUADraftRequest) -> MUADraft:
        """Generate draft when no precedents are found."""
        return MUADraft(
            material=request.material_designation,
            environment=request.environment_description,
            application=request.application,
            recommended_determination="REQUIRES_REVIEW",
            confidence=0.0,
            rationale=(
                f"No historic precedents found for {request.material_designation} in "
                f"{request.environment_description}. Engineering review and testing required."
            ),
            issues_addressed=[],
            precedents_cited=[],
            coverage_assessment="NONE - No precedents found in corpus",
            gaps_identified=["Complete precedent gap - novel material/environment combination"],
            warnings=["NO PRECEDENTS - Cannot generate draft based on historic usage"],
        )


def generate_mua_draft(
    material: str,
    environment: str,
    application: str,
    precedents: List[Tuple[CleanedMUARecord, float]],
    o2_percent: Optional[float] = None,
    pressure_psia: Optional[float] = None,
    temperature_f: Optional[float] = None,
    is_habitable: bool = False,
    issues: Optional[List[str]] = None,
) -> MUADraft:
    """Convenience function to generate MUA draft.

    Args:
        material: Material designation (e.g., "6061-T6 Aluminum")
        environment: Environment description (e.g., "enriched oxygen")
        application: Application context
        precedents: List of (record, score) tuples from search
        o2_percent: Optional O2 percentage
        pressure_psia: Optional pressure in PSIA
        temperature_f: Optional temperature in F
        is_habitable: Whether application is in habitable volume
        issues: List of issue categories to address

    Returns:
        MUADraft with synthesized content and provenance
    """
    request = MUADraftRequest(
        material_designation=material,
        environment_description=environment,
        application=application,
        o2_percent=o2_percent,
        pressure_psia=pressure_psia,
        temperature_f=temperature_f,
        is_habitable=is_habitable,
        issues=issues or [],
    )

    generator = DraftGenerator()
    return generator.generate_draft(request, precedents)
