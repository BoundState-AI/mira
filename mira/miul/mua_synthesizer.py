#!/usr/bin/env python3
"""
Module: Mua Synthesizer
Purpose: MUA Synthesizer V3 - LLM-powered MUA generation with applicability analysis.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C, SWE-013 (Traceability)
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# AWS Bedrock vs Direct API
# Default to direct API (USE_BEDROCK=0) - set ANTHROPIC_API_KEY env var
USE_BEDROCK = os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("AWS_REGION", os.getenv("BEDROCK_REGION", "us-east-1"))

# Model IDs - use Sonnet for synthesis quality
SONNET_MODEL_DIRECT = "claude-sonnet-4-5-20250929"
SONNET_MODEL_BEDROCK = "anthropic.claude-sonnet-4-5-20250929-v1:0"


# =============================================================================
# Data Models
# =============================================================================

class Applicability(str, Enum):
    """Applicability verdict for a precedent."""
    YES = "YES"
    PARTIAL = "PARTIAL"
    NO = "NO"


class MatchLevel(str, Enum):
    """Match level for comparison factors."""
    EXACT = "EXACT"
    FAMILY = "FAMILY"
    SIMILAR = "SIMILAR"
    DIFFERENT = "DIFFERENT"
    YES = "YES"
    PARTIAL = "PARTIAL"
    NO = "NO"


@dataclass
class FactorAnalysis:
    """Analysis of a single comparison factor."""
    match: MatchLevel
    reason: str
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class ApplicabilityAnalysis:
    """Full applicability analysis for a precedent."""
    precedent_id: str
    applicability: Applicability
    relevance_score: float
    factors: Dict[str, FactorAnalysis]
    summary: str
    source: str = ""  # NASA SWE-013 traceability


    @classmethod
    def parse(cls, precedent_id: str, response_text: str) -> "ApplicabilityAnalysis":
        """Parse LLM response into ApplicabilityAnalysis."""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                # Fallback parsing
                data = {}

            applicability_str = data.get("applicability", "PARTIAL").upper()
            if applicability_str not in ["YES", "PARTIAL", "NO"]:
                applicability_str = "PARTIAL"

            factors = {}
            factors_data = data.get("factors", {})
            for factor_name, factor_data in factors_data.items():
                if isinstance(factor_data, dict):
                    match_str = factor_data.get("match", "PARTIAL").upper()
                    try:
                        match_level = MatchLevel(match_str)
                    except ValueError:
                        match_level = MatchLevel.PARTIAL
                    factors[factor_name] = FactorAnalysis(
                        match=match_level,
                        reason=factor_data.get("reason", "")
                    )

            return cls(
                precedent_id=precedent_id,
                applicability=Applicability(applicability_str),
                relevance_score=float(data.get("relevance_score", 0.5)),
                factors=factors,
                summary=data.get("summary", "Analysis completed.")
            )
        except Exception as e:
            logger.warning(f"Failed to parse applicability response: {e}")
            return cls(
                precedent_id=precedent_id,
                applicability=Applicability.PARTIAL,
                relevance_score=0.5,
                factors={},
                summary=f"Analysis parsing failed: {str(e)[:100]}"
            )


@dataclass
class MUAPrecedent:
    """A historic MUA that serves as precedent."""
    mua_number: str
    material: str
    environment: str
    determination: str
    rationale: str
    score: float
    source_file: str
    category: Optional[str] = None
    issue: Optional[str] = None
    material_family: Optional[str] = None
    application: Optional[str] = None
    location: Optional[str] = None
    max_temperature_f: Optional[float] = None
    max_pressure: Optional[float] = None
    conditions: List[str] = field(default_factory=list)
    test_reports: List[str] = field(default_factory=list)
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class MUASynthesisRequest:
    """Request for MUA synthesis."""
    material: str
    material_code: Optional[str] = None
    issue: str = ""  # Primary issue type (FLAM, SCC, etc.)
    application: str = ""
    environment: str = ""
    location: str = ""  # Habitable / Non-habitable
    mass_quantity: Optional[str] = None
    program: Optional[str] = None
    additional_context: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class MUASynthesisResult:
    """Result of MUA synthesis."""
    success: bool
    material: str = ""
    issue: str = ""
    category: str = ""
    rationale: str = ""
    confidence: float = 0.0
    precedents: List[MUAPrecedent] = field(default_factory=list)
    applicability_analyses: List[ApplicabilityAnalysis] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability



# =============================================================================
# LLM Client Factory
# =============================================================================

def get_llm_client(use_bedrock: bool = USE_BEDROCK):
    """Create LLM client - either direct API or AWS Bedrock."""
    if use_bedrock:
        try:
            from anthropic import AnthropicBedrock
        except ImportError:
            raise ImportError("pip install anthropic[bedrock]")

        logger.info(f"Using AWS Bedrock in region: {BEDROCK_REGION}")
        return AnthropicBedrock(aws_region=BEDROCK_REGION), SONNET_MODEL_BEDROCK
    else:
        from anthropic import Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        return Anthropic(api_key=api_key), SONNET_MODEL_DIRECT


# =============================================================================
# MUA Synthesizer V3
# =============================================================================

class MUASynthesizer:
    """
    MUA Synthesizer V3 - LLM-powered MUA generation with applicability analysis.

    Workflow:
    1. Find precedents matching material/issue from BOK
    2. Analyze applicability of each precedent to user's use case
    3. Synthesize NEW rationale citing applicable precedents
    """

    def __init__(self, use_bedrock: bool = USE_BEDROCK):
        """Initialize synthesizer with LLM client and BOK engine."""
        self.client, self.model = get_llm_client(use_bedrock)
        self.bok_engine = None
        self._load_bok_engine()

    def _load_bok_engine(self):
        """Lazy load the MUA BOK engine."""
        try:
            from mira.miul.mua_bok_engine import MUABOKEngine
            self.bok_engine = MUABOKEngine()
            logger.info(f"Loaded MUA BOK engine with {len(self.bok_engine.metadata)} records")
        except Exception as e:
            logger.warning(f"Failed to load MUA BOK engine: {e}")
            self.bok_engine = None

    async def generate_mua(self, request: MUASynthesisRequest) -> MUASynthesisResult:
        """
        Full MUA generation pipeline.

        Steps:
        1. Find precedents matching material/issue
        2. Analyze applicability of each precedent
        3. Synthesize rationale from applicable precedents
        4. Calculate confidence and determine category
        """
        logger.info(f"[MUA Synth] Generating MUA for {request.material} / {request.issue}")

        # Validate BOK engine
        if self.bok_engine is None or not self.bok_engine.metadata:
            return MUASynthesisResult(
                success=False,
                error="MUA BOK index not loaded. Ensure mua_bok_v2.faiss exists."
            )

        # Step 1: Find precedents
        precedents = self._find_precedents(request)

        if not precedents:
            return MUASynthesisResult(
                success=False,
                material=request.material,
                issue=request.issue,
                error=f"No precedents found for {request.material} with {request.issue} issue."
            )

        logger.info(f"[MUA Synth] Found {len(precedents)} candidate precedents")

        # Step 2: Analyze applicability of each precedent
        applicable: List[Tuple[MUAPrecedent, ApplicabilityAnalysis]] = []
        analyses: List[ApplicabilityAnalysis] = []

        for p in precedents[:10]:  # Limit to top 10 for efficiency
            analysis = await self._analyze_applicability(request, p)
            analyses.append(analysis)
            if analysis.applicability in [Applicability.YES, Applicability.PARTIAL]:
                applicable.append((p, analysis))

        if not applicable:
            # Return with analyses even if none applicable
            return MUASynthesisResult(
                success=False,
                material=request.material,
                issue=request.issue,
                precedents=[p for p in precedents[:10]],
                applicability_analyses=analyses,
                error="Found precedents but none are applicable to this specific use case."
            )

        logger.info(f"[MUA Synth] {len(applicable)} precedents are applicable")

        # Step 3: Synthesize rationale
        rationale = await self._synthesize_rationale(request, applicable)

        # Step 4: Determine category and confidence
        category = self._route_category(request, applicable)
        confidence = self._calculate_confidence(applicable)

        # Build warnings
        warnings = []
        if confidence < 0.6:
            warnings.append("Low confidence - consider additional precedent review")
        if len(applicable) == 1:
            warnings.append("Only one applicable precedent found")
        partial_only = all(a.applicability == Applicability.PARTIAL for _, a in applicable)
        if partial_only:
            warnings.append("All precedents are partially applicable - manual review recommended")

        return MUASynthesisResult(
            success=True,
            material=request.material,
            issue=request.issue,
            category=category,
            rationale=rationale,
            confidence=confidence,
            precedents=[p for p, _ in applicable],
            applicability_analyses=[a for _, a in applicable],
            warnings=warnings,
        )

    def generate_mua_sync(self, request: MUASynthesisRequest) -> MUASynthesisResult:
        """Synchronous wrapper for generate_mua."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.generate_mua(request))

    def _find_precedents(self, request: MUASynthesisRequest) -> List[MUAPrecedent]:
        """Find precedents from BOK matching material and issue."""
        if not self.bok_engine:
            return []

        # First try exact match
        issues = [request.issue] if request.issue else []
        precedents = self.bok_engine.find_exact_precedents(
            material=request.material,
            issues=issues,
            k=20
        )

        # If no exact matches, try semantic search
        if len(precedents) < 3:
            gaps = {request.issue: "B"} if request.issue else {}
            semantic_results = self.bok_engine.search_precedents(
                material=request.material,
                environment=request.environment,
                gaps=gaps,
                k=20
            )
            # Add semantic results not already in exact matches
            existing_ids = {p.mua_number for p in precedents}
            for p in semantic_results:
                if p.mua_number not in existing_ids:
                    precedents.append(p)

        # Convert to our MUAPrecedent format with additional fields
        enriched = []
        for p in precedents:
            # Get metadata for additional fields
            meta = self._get_precedent_metadata(p.mua_number)
            enriched.append(MUAPrecedent(
                mua_number=p.mua_number,
                material=p.material,
                environment=p.environment,
                determination=p.determination,
                rationale=p.rationale,
                score=p.score,
                source_file=p.source_file,
                category=p.category,
                issue=p.issue,
                material_family=p.material_family,
                application=meta.get("application"),
                location=meta.get("location"),
                max_temperature_f=meta.get("max_temperature_f"),
                max_pressure=meta.get("max_pressure"),
                conditions=meta.get("conditions", []),
                test_reports=p.test_reports,
            ))

        # Filter to only APPROVED precedents
        approved = [p for p in enriched if p.determination == "APPROVED"]
        return approved if approved else enriched[:10]

    def _get_precedent_metadata(self, mua_number: str) -> Dict[str, Any]:
        """Get full metadata for a precedent."""
        if not self.bok_engine:
            return {}
        for meta in self.bok_engine.metadata:
            if (meta.get("mua_number") == mua_number or
                meta.get("file", "").replace(".pdf", "") == mua_number):
                return meta
        return {}

    async def _analyze_applicability(
        self,
        request: MUASynthesisRequest,
        precedent: MUAPrecedent
    ) -> ApplicabilityAnalysis:
        """Use LLM to analyze if precedent applies to user's case."""

        # Build comparison context
        user_context = f"""
Material: {request.material}
Issue: {request.issue or 'Not specified'}
Application: {request.application or 'Not specified'}
Environment: {request.environment or 'Not specified'}
Location: {request.location or 'Not specified'}
Mass/Quantity: {request.mass_quantity or 'Not specified'}
Program: {request.program or 'Not specified'}
"""

        precedent_context = f"""
MUA Number: {precedent.mua_number}
Material: {precedent.material}
Issue: {precedent.issue or 'Not specified'}
Application: {precedent.application or 'Not specified'}
Environment: {precedent.environment or 'Not specified'}
Determination: {precedent.determination}
Category: {precedent.category or 'Not specified'}

Rationale (first 2000 chars):
{precedent.rationale[:2000] if precedent.rationale else 'No rationale available'}
"""

        prompt = f"""You are a NASA materials engineer analyzing MUA precedent applicability.

USER'S NEW APPLICATION:
{user_context}

HISTORIC PRECEDENT:
{precedent_context}

TASK: Analyze whether this precedent is applicable to the user's new application.

Consider these factors:
1. MATERIAL MATCH: Is the material the same, same family (e.g., both nylons), or different?
2. ENVIRONMENT MATCH: Are the user's conditions the same or less severe than the precedent?
3. APPLICATION MATCH: Is the application functionally similar?
4. LOCATION MATCH: Same location category (habitable vs non-habitable)?
5. OVERALL: Would the rationale that approved the precedent also apply here?

Return a JSON object with this exact structure:
{{
  "applicability": "YES" | "PARTIAL" | "NO",
  "relevance_score": 0.0-1.0,
  "factors": {{
    "material_match": {{"match": "EXACT|FAMILY|SIMILAR|DIFFERENT", "reason": "explanation"}},
    "environment_match": {{"match": "YES|PARTIAL|NO", "reason": "explanation"}},
    "application_match": {{"match": "YES|SIMILAR|NO", "reason": "explanation"}},
    "location_match": {{"match": "YES|NO", "reason": "explanation"}}
  }},
  "summary": "One sentence summary of why this precedent is/isn't applicable"
}}

Rules:
- YES = All key factors match, precedent directly applies
- PARTIAL = Some factors match, precedent provides supporting evidence
- NO = Critical factors don't match, precedent not applicable

Return ONLY the JSON object, no other text."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = response.content[0].text
            return ApplicabilityAnalysis.parse(precedent.mua_number, response_text)
        except Exception as e:
            logger.error(f"Applicability analysis failed for {precedent.mua_number}: {e}")
            return ApplicabilityAnalysis(
                precedent_id=precedent.mua_number,
                applicability=Applicability.PARTIAL,
                relevance_score=0.5,
                factors={},
                summary=f"Analysis failed: {str(e)[:100]}"
            )

    async def _synthesize_rationale(
        self,
        request: MUASynthesisRequest,
        applicable: List[Tuple[MUAPrecedent, ApplicabilityAnalysis]]
    ) -> str:
        """Use LLM to synthesize NEW rationale (not copy/paste)."""

        # Build precedent summaries
        precedent_summaries = []
        for p, a in applicable[:5]:  # Limit to top 5
            summary = f"""
- {p.mua_number} ({a.applicability.value}, score: {a.relevance_score:.2f})
  Material: {p.material}
  Application: {p.application or 'N/A'}
  Environment: {p.environment}
  Why applicable: {a.summary}
"""
            precedent_summaries.append(summary)

        # Extract key approval factors from precedents
        factors_text = self._extract_approval_factors(applicable)

        prompt = f"""You are a NASA materials engineer writing an MUA rationale.

CRITICAL INSTRUCTION: DO NOT copy text from precedent rationales. Write ORIGINAL prose.

USER'S APPLICATION:
- Material: {request.material}
- Issue: {request.issue} (non-A rating requiring MUA)
- Application: {request.application or 'Not specified'}
- Environment: {request.environment or 'Not specified'}
- Location: {request.location or 'Not specified'}
- Mass/Quantity: {request.mass_quantity or 'Not specified'}
- Program: {request.program or 'Not specified'}

APPLICABLE PRECEDENTS:
{''.join(precedent_summaries)}

KEY APPROVAL FACTORS FROM PRECEDENTS:
{factors_text}

TASK: Write a 2-4 paragraph MUA rationale that:

1. Opens with a summary statement referencing the number of precedents reviewed
2. Explains WHY this material should be approved for THIS specific application
3. Maps the key approval factors from precedents to the user's conditions
4. Cites the precedent MUA numbers (e.g., "per MUA-FIV-011") as supporting evidence
5. Addresses the specific issue ({request.issue}) and how it's mitigated
6. Uses formal NASA MUA technical writing style

IMPORTANT:
- The rationale must be ORIGINAL SYNTHESIS, not copied from precedent text
- Focus on explaining WHY the approval factors apply to THIS use case
- Be specific about conditions, limits, and mitigations
- Reference test standards where applicable (NASA-STD-6001, ASTM E595, etc.)

Write the rationale now:"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )
            rationale = response.content[0].text

            # Add precedent citations section
            citations = "\n\n**Precedent MUAs Cited:**\n"
            for p, a in applicable[:5]:
                citations += f"- {p.mua_number}: {p.material} ({p.determination}) - {a.summary}\n"

            return rationale + citations

        except Exception as e:
            logger.error(f"Rationale synthesis failed: {e}")
            # Fallback to template-based rationale
            return self._fallback_rationale(request, applicable)

    def _extract_approval_factors(
        self,
        applicable: List[Tuple[MUAPrecedent, ApplicabilityAnalysis]]
    ) -> str:
        """Extract common approval factors from applicable precedents."""
        factors = []

        for p, a in applicable:
            if p.rationale:
                # Look for common NASA approval phrases
                rationale_lower = p.rationale.lower()

                if "mass limit" in rationale_lower or "limited mass" in rationale_lower:
                    factors.append(f"- Mass limitation (per {p.mua_number})")
                if "non-habitable" in rationale_lower:
                    factors.append(f"- Non-habitable location (per {p.mua_number})")
                if "fire suppression" in rationale_lower:
                    factors.append(f"- Fire suppression available (per {p.mua_number})")
                if "enclosed" in rationale_lower or "containment" in rationale_lower:
                    factors.append(f"- Enclosed/contained configuration (per {p.mua_number})")
                if "nasa-std-6001" in rationale_lower or "std 6001" in rationale_lower:
                    factors.append(f"- NASA-STD-6001 compliance (per {p.mua_number})")
                if "astm e595" in rationale_lower:
                    factors.append(f"- ASTM E595 outgassing compliance (per {p.mua_number})")
                if "heritage" in rationale_lower or "flight history" in rationale_lower:
                    factors.append(f"- Flight heritage (per {p.mua_number})")

        # Deduplicate
        unique_factors = list(dict.fromkeys(factors))
        return "\n".join(unique_factors[:10]) if unique_factors else "No specific factors extracted"

    def _fallback_rationale(
        self,
        request: MUASynthesisRequest,
        applicable: List[Tuple[MUAPrecedent, ApplicabilityAnalysis]]
    ) -> str:
        """Generate fallback rationale when LLM fails."""
        mua_refs = ", ".join(p.mua_number for p, _ in applicable[:3])

        issue_templates = {
            "FLAM": (
                f"Material flammability for {request.material} has been assessed. "
                f"Based on review of {len(applicable)} approved MUA precedents ({mua_refs}), "
                f"the proposed use is supportable under the following conditions: "
                f"limited mass configuration, engineering controls for ignition source isolation, "
                f"and compliance with NASA-STD-6001 Test 1 requirements where applicable."
            ),
            "TVS": (
                f"Outgassing properties of {request.material} have been evaluated. "
                f"Per precedent MUAs ({mua_refs}), materials meeting ASTM E595 limits "
                f"(TML < 1.0%, CVCM < 0.1%) are acceptable for the proposed application. "
                f"Component protection or enclosure mitigates contamination risk."
            ),
            "TOX": (
                f"Toxicity of combustion products for {request.material} has been assessed. "
                f"Based on precedent ({mua_refs}), the limited mass and configuration "
                f"minimize toxic byproduct generation potential in the event of combustion."
            ),
            "SCC": (
                f"Stress corrosion cracking susceptibility of {request.material} is mitigated "
                f"through stress limits, environmental controls, or protective coatings. "
                f"Per precedent MUAs ({mua_refs}), similar materials have been approved "
                f"under comparable service conditions."
            ),
            "CORR": (
                f"Corrosion resistance of {request.material} is adequate for the service environment. "
                f"Based on precedent ({mua_refs}), appropriate protective measures "
                f"ensure material compatibility with the specified conditions."
            ),
            "FS": (
                f"Fluid service compatibility of {request.material} has been verified. "
                f"Per precedent MUAs ({mua_refs}), testing or engineering analysis "
                f"confirms suitability for the specified operating conditions."
            ),
        }

        base = issue_templates.get(request.issue, (
            f"Based on review of {len(applicable)} approved MUA precedents ({mua_refs}), "
            f"the proposed use of {request.material} is supportable for the specified application."
        ))

        return base + f"\n\n**Precedent MUAs:** {mua_refs}"

    def _route_category(
        self,
        request: MUASynthesisRequest,
        applicable: List[Tuple[MUAPrecedent, ApplicabilityAnalysis]]
    ) -> str:
        """Determine MUA category based on environment, issue, and precedents."""
        env_lower = (request.environment or "").lower()
        loc_lower = (request.location or "").lower()
        issue = request.issue.upper() if request.issue else ""

        # Check precedent categories
        precedent_categories = [p.category for p, _ in applicable if p.category]

        # Category III: Appendix B exemptions (TVS in non-habitable)
        if issue == "TVS" and "non-habitable" in loc_lower:
            return "III"

        # Category I: High risk - O2 service with flammability
        if issue == "FLAM":
            if any(kw in env_lower for kw in ["oxygen", "o2", "gox", "lox"]):
                return "I"

        # Category I: Habitable with toxicity issues
        if issue == "TOX" and ("habitable" in loc_lower or "cabin" in loc_lower):
            return "I"

        # Default to Category II for most cases
        return "II"

    def _calculate_confidence(
        self,
        applicable: List[Tuple[MUAPrecedent, ApplicabilityAnalysis]]
    ) -> float:
        """Calculate confidence score based on precedent quality."""
        if not applicable:
            return 0.3

        base = 0.50

        # Number of applicable precedents (max +0.15)
        base += min(len(applicable) * 0.05, 0.15)

        # Average relevance score (max +0.20)
        avg_relevance = sum(a.relevance_score for _, a in applicable) / len(applicable)
        base += avg_relevance * 0.20

        # Bonus for fully applicable (YES) precedents
        full_applicable = sum(1 for _, a in applicable if a.applicability == Applicability.YES)
        base += min(full_applicable * 0.05, 0.10)

        # All APPROVED bonus
        if all(p.determination == "APPROVED" for p, _ in applicable):
            base += 0.05

        return max(0.20, min(base, 0.95))


# =============================================================================
# Convenience Functions
# =============================================================================

_SYNTHESIZER: Optional[MUASynthesizer] = None


def get_mua_synthesizer(use_bedrock: bool = USE_BEDROCK) -> MUASynthesizer:
    """Get or create singleton MUA synthesizer."""
    global _SYNTHESIZER
    if _SYNTHESIZER is None:
        _SYNTHESIZER = MUASynthesizer(use_bedrock=use_bedrock)
    return _SYNTHESIZER


async def synthesize_mua(request: MUASynthesisRequest) -> MUASynthesisResult:
    """Synthesize MUA with LLM-powered analysis."""
    synthesizer = get_mua_synthesizer()
    return await synthesizer.generate_mua(request)


def synthesize_mua_sync(request: MUASynthesisRequest) -> MUASynthesisResult:
    """Synchronous MUA synthesis."""
    synthesizer = get_mua_synthesizer()
    return synthesizer.generate_mua_sync(request)


# =============================================================================
# Testing
# =============================================================================

def test_mua_synthesizer():
    """Test the MUA synthesizer."""
    print("=" * 70)
    print("MUA SYNTHESIZER V3 TEST")
    print("=" * 70)

    synthesizer = MUASynthesizer()

    if synthesizer.bok_engine is None:
        print("WARNING: BOK engine not loaded. Skipping test.")
        return

    # Test case: Nylon cable ties with FLAM issue
    request = MUASynthesisRequest(
        material="Nylon 6/6",
        issue="FLAM",
        application="Cable tie wraps in avionics bay",
        environment="Ambient, <150F",
        location="Non-habitable",
        mass_quantity="100g total",
        program="Orion",
    )

    print(f"\nTest Case:")
    print(f"  Material: {request.material}")
    print(f"  Issue: {request.issue}")
    print(f"  Application: {request.application}")
    print(f"  Environment: {request.environment}")
    print(f"  Location: {request.location}")
    print(f"  Mass: {request.mass_quantity}")

    result = synthesizer.generate_mua_sync(request)

    print(f"\nResult:")
    print(f"  Success: {result.success}")
    print(f"  Category: {result.category}")
    print(f"  Confidence: {result.confidence:.0%}")
    print(f"  Precedents: {len(result.precedents)}")

    if result.applicability_analyses:
        print(f"\nApplicability Analyses:")
        for a in result.applicability_analyses[:3]:
            print(f"  - {a.precedent_id}: {a.applicability.value} ({a.relevance_score:.2f})")
            print(f"    {a.summary}")

    if result.rationale:
        print(f"\nRationale (first 500 chars):")
        print(f"  {result.rationale[:500]}...")

    if result.warnings:
        print(f"\nWarnings:")
        for w in result.warnings:
            print(f"  - {w}")

    if result.error:
        print(f"\nError: {result.error}")

    print("\n" + "=" * 70)
    print("MUA SYNTHESIZER V3 TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    test_mua_synthesizer()
