#!/usr/bin/env python3
"""
Module: Material Code Selector
Purpose: AI-Powered Material Code Selection

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Model configuration - same pattern as haiku_drawing_extractor.py
USE_BEDROCK = os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("AWS_REGION", os.getenv("BEDROCK_REGION", "us-east-1"))

# Haiku model IDs
HAIKU_MODEL_DIRECT = "claude-3-haiku-20240307"
HAIKU_MODEL_BEDROCK = "anthropic.claude-3-haiku-20240307-v1:0"


SELECTION_PROMPT = """You are a NASA materials engineer selecting the correct MAPTIS material code for a spacecraft part.

Given:
- Material designation from drawing: {designation}
- Part description: {part_description}
- Material form (if specified): {material_form}

Select the BEST matching MAPTIS code from these candidates:

{candidates_list}

Selection rules (in priority order):

1. AVOID composites/coatings UNLESS the part clearly IS a composite:
   - Reject codes with "ON ", "HONEYCOMB", "CORE", "COATING", "COATED", "CLAD", "BONDED", "LAMINATE"
   - Exception: If part description mentions honeycomb, core, or coating, then these ARE appropriate

2. MATCH material form to part type:
   - Skins, panels, covers, shims, membranes → SHEET
   - Structural plates, bulkheads, flanges, brackets, webs, ribs → PLATE
   - Shafts, rods, pins, bolts, studs, axles, spindles, spacers → BAR or ROD
   - Tubes, pipes, lines, tubing → TUBE
   - Cables, springs → WIRE
   - Fittings, brackets (thick) → FORGING
   - Shapes, angles, channels → SHAPES EXTRUDED

3. MATCH temper exactly if specified:
   - "AL 6061-T6" should match "AL 6061-T6 SHEET" not "AL 6061-T4 SHEET"
   - If no temper specified, prefer codes without temper or common tempers

4. PREFER simpler/bare alloy designations over complex ones

Respond with JSON only (no markdown, no explanation outside JSON):
{{
  "selected_code": "XXXXX",
  "selected_designation": "full MAPTIS designation exactly as shown",
  "confidence": "high|medium|low",
  "reasoning": "one sentence explanation"
}}
"""


@dataclass
class SelectionResult:
    """Result of AI-powered material code selection."""
    material_code: str
    designation: str
    confidence: str  # high, medium, low
    reasoning: str
    method: str = "ai_selection"


class MaterialCodeSelector:
    """AI-powered material code selection from MAPTIS candidates.

    Uses Claude Haiku to intelligently select the best material code
    based on part description context and materials domain knowledge.

    Includes caching to avoid repeated API calls for the same designation/description.
    """

    # Class-level cache: (designation, part_description) → SelectionResult
    _cache: Dict[Tuple[str, str], SelectionResult] = {}

    def __init__(
        self,
        use_bedrock: bool = None,
        api_key: str = None,
        enable_cache: bool = True
    ):
        """Initialize the selector.

        Args:
            use_bedrock: Use AWS Bedrock (default: USE_BEDROCK env var)
            api_key: Anthropic API key (default: ANTHROPIC_API_KEY env var)
            enable_cache: Cache results to avoid repeated API calls
        """
        self.use_bedrock = use_bedrock if use_bedrock is not None else USE_BEDROCK
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.enable_cache = enable_cache
        self._client = None
        self.model = HAIKU_MODEL_BEDROCK if self.use_bedrock else HAIKU_MODEL_DIRECT

    @property
    def client(self):
        """Lazy-load Anthropic client (Bedrock or direct API)."""
        if self._client is None:
            if self.use_bedrock:
                try:
                    from anthropic import AnthropicBedrock
                    self._client = AnthropicBedrock(aws_region=BEDROCK_REGION)
                    logger.info(f"MaterialCodeSelector using Bedrock in {BEDROCK_REGION}")
                except ImportError:
                    logger.error("anthropic package not installed")
                    raise
            else:
                try:
                    from anthropic import Anthropic
                    self._client = Anthropic(api_key=self.api_key)
                    logger.info(f"MaterialCodeSelector using direct API with {self.model}")
                except ImportError:
                    logger.error("anthropic package not installed")
                    raise
        return self._client

    def is_available(self) -> bool:
        """Check if API client is available."""
        try:
            _ = self.client
            return True
        except Exception:
            return False

    def select_best_match(
        self,
        designation: str,
        candidates: List[Dict[str, str]],
        part_description: str = "",
        material_form: str = "",
    ) -> Optional[SelectionResult]:
        """
        Use Claude Haiku to select the best material code from candidates.

        Args:
            designation: Material designation from drawing (e.g., "AL 6061-T6")
            candidates: List of MAPTIS candidate dicts with 'material_code' and 'designation'
            part_description: Part description from Document Title (e.g., "SKIN, FUSELAGE")
            material_form: Explicit material form if known (e.g., "SHEET")

        Returns:
            SelectionResult with selected code and reasoning, or None on failure
        """
        if not candidates:
            logger.warning(f"No candidates provided for '{designation}'")
            return None

        # Single candidate - no AI needed
        if len(candidates) == 1:
            c = candidates[0]
            logger.debug(f"Single candidate for '{designation}': {c['material_code']}")
            return SelectionResult(
                material_code=c["material_code"],
                designation=c["designation"],
                confidence="high",
                reasoning="Single candidate match",
                method="single_match"
            )

        # Check cache
        cache_key = (designation.upper().strip(), part_description.upper().strip())
        if self.enable_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.debug(f"Cache hit for '{designation}': {cached.material_code}")
            return cached

        # Format candidates for prompt (limit to 25 to stay within context)
        candidates_list = "\n".join([
            f"- {c['material_code']}: {c['designation']}"
            for c in candidates[:25]
        ])

        prompt = SELECTION_PROMPT.format(
            designation=designation,
            part_description=part_description or "(not specified)",
            material_form=material_form or "(not specified)",
            candidates_list=candidates_list
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                temperature=0,  # Deterministic for reproducibility
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()
            result = self._parse_response(response_text, candidates)

            if result:
                logger.info(
                    f"AI selected: '{designation}' + '{part_description}' -> "
                    f"{result.material_code} ({result.confidence}: {result.reasoning})"
                )
                # Cache the result
                if self.enable_cache:
                    self._cache[cache_key] = result
                return result
            else:
                logger.warning(f"Failed to parse AI response for '{designation}'")
                return self._fallback_selection(designation, candidates)

        except Exception as e:
            logger.warning(f"AI selection failed for '{designation}': {e}")
            return self._fallback_selection(designation, candidates)

    def _parse_response(
        self,
        response_text: str,
        candidates: List[Dict[str, str]]
    ) -> Optional[SelectionResult]:
        """Parse Haiku JSON response with robust error handling."""
        # Remove markdown code blocks if present
        if "```" in response_text:
            parts = response_text.split("```")
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                # Remove language identifier (json, JSON, etc.)
                if part.lower().startswith("json"):
                    part = part[4:].strip()
                try:
                    data = json.loads(part)
                    return self._validate_and_build_result(data, candidates)
                except json.JSONDecodeError:
                    continue

        # Try direct JSON parsing
        try:
            data = json.loads(response_text)
            return self._validate_and_build_result(data, candidates)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object from text
        json_match = re.search(r'\{[\s\S]*?\}', response_text)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return self._validate_and_build_result(data, candidates)
            except json.JSONDecodeError:
                pass

        return None

    def _validate_and_build_result(
        self,
        data: Dict[str, Any],
        candidates: List[Dict[str, str]]
    ) -> Optional[SelectionResult]:
        """Validate parsed JSON and build SelectionResult."""
        selected_code = str(data.get("selected_code", "")).strip()

        # Validate selected code is in candidates
        valid_codes = {c["material_code"] for c in candidates}
        if selected_code not in valid_codes:
            logger.warning(
                f"AI selected invalid code '{selected_code}', "
                f"valid codes: {list(valid_codes)[:5]}..."
            )
            return None

        # Find the full designation from candidates
        selected_designation = data.get("selected_designation", "")
        for c in candidates:
            if c["material_code"] == selected_code:
                selected_designation = c["designation"]
                break

        confidence = data.get("confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        return SelectionResult(
            material_code=selected_code,
            designation=selected_designation,
            confidence=confidence,
            reasoning=data.get("reasoning", "AI selection"),
            method="ai_selection"
        )

    def _fallback_selection(
        self,
        designation: str,
        candidates: List[Dict[str, str]]
    ) -> SelectionResult:
        """Fallback when AI fails: prefer bare alloys over composites.

        This is a simple heuristic that deprioritizes composite/coated materials.
        """
        composite_indicators = [
            'ON ', 'HONEYCOMB', 'CORE', 'COATING', 'COATED',
            'CLAD', 'BONDED', 'LAMINATE', 'COMPOSITE'
        ]

        # First pass: find non-composite candidates
        for c in candidates:
            desig_upper = c["designation"].upper()
            if not any(ind in desig_upper for ind in composite_indicators):
                logger.info(
                    f"Fallback selected for '{designation}': {c['material_code']} "
                    f"(first non-composite)"
                )
                return SelectionResult(
                    material_code=c["material_code"],
                    designation=c["designation"],
                    confidence="low",
                    reasoning="Fallback: first non-composite candidate (AI unavailable)",
                    method="fallback_non_composite"
                )

        # All are composites - return first one
        c = candidates[0]
        logger.warning(
            f"Fallback selected for '{designation}': {c['material_code']} "
            f"(all candidates are composites)"
        )
        return SelectionResult(
            material_code=c["material_code"],
            designation=c["designation"],
            confidence="low",
            reasoning="Fallback: all candidates are composites",
            method="fallback_first"
        )

    @classmethod
    def clear_cache(cls) -> int:
        """Clear the selection cache. Returns number of entries cleared."""
        count = len(cls._cache)
        cls._cache.clear()
        return count


# Module-level singleton for convenience
_selector: Optional[MaterialCodeSelector] = None


def get_material_code_selector() -> MaterialCodeSelector:
    """Get singleton MaterialCodeSelector instance."""
    global _selector
    if _selector is None:
        _selector = MaterialCodeSelector()
    return _selector


def reset_material_code_selector() -> None:
    """Reset singleton for testing."""
    global _selector
    _selector = None
    MaterialCodeSelector.clear_cache()


__all__ = [
    "MaterialCodeSelector",
    "SelectionResult",
    "get_material_code_selector",
    "reset_material_code_selector",
]
