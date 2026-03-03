#!/usr/bin/env python3
"""
Module: Logic Validator
Purpose: LLM-based rationale transfer validation for MUA generation.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-033 (Safety decisions)
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from .enriched_search import EnrichedMUAResult

__all__ = [
    "RationaleValidationResult",
    "LogicValidator",
]

__safety_critical__ = True

LOGGER = logging.getLogger(__name__)


class RationaleValidationResult(BaseModel):
    """Result of LLM rationale validation.

    SWE-013: Includes source field for traceability.
    SWE-033: All validation reasoning is logged.
    """
    model_config = {"extra": "forbid"}

    is_valid: bool = Field(
        default=False,
        description="True if precedent rationale transfers to target context"
    )
    synthesized_rationale: str = Field(
        default="",
        description="Generated rationale text (empty if invalid)"
    )
    citations: list[str] = Field(
        default_factory=list,
        description="MUA numbers used as precedent basis"
    )
    rejected_precedents: list[str] = Field(
        default_factory=list,
        description="MUA numbers whose rationale did not transfer"
    )
    rejection_reasons: dict[str, str] = Field(
        default_factory=dict,
        description="MUA number -> reason for rejection"
    )
    reasoning: str = Field(
        default="",
        description="Chain-of-thought explanation from validator"
    )
    source: str = Field(
        default="LogicValidator",
        description="SWE-013: Source for traceability"
    )

    @property
    def has_citations(self) -> bool:
        """True if rationale is backed by precedent citations."""
        return len(self.citations) > 0

    @property
    def all_rejected(self) -> bool:
        """True if all provided precedents were rejected."""
        return not self.is_valid and len(self.rejected_precedents) > 0


class LogicValidator:
    """LLM-based validator for precedent rationale transfer.

    Uses Claude Haiku for cost-effective structured validation.
    Evaluates whether precedent rationale applies to new target context.

    FAIL-CLOSED DESIGN: Returns is_valid=False on ANY error.

    Example:
        >>> validator = LogicValidator()
        >>> result = validator.validate(
        ...     material="INCONEL 625",
        ...     environment_desc="100% O2 at 14.7 PSIA",
        ...     precedents=supporting_results[:3],
        ... )
        >>> if result.is_valid:
        ...     print(f"Rationale: {result.synthesized_rationale}")
    """

    # Model configuration - using Haiku for speed and cost
    MODEL = "claude-3-5-haiku-20241022"
    MAX_TOKENS = 2048
    TEMPERATURE = 0  # Deterministic for safety-critical decisions

    def __init__(self, api_key: str | None = None):
        """Initialize validator with Anthropic API client.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.

        Raises:
            ValueError: If no API key available.
        """
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Provide api_key or set environment variable."
            )

        # Lazy import to avoid hard dependency when mocking
        from anthropic import Anthropic
        self._client = Anthropic(api_key=self._api_key)

    def validate(
        self,
        material: str,
        environment_desc: str,
        precedents: list[EnrichedMUAResult],
        req_id: str = "unknown",
    ) -> RationaleValidationResult:
        """Validate that precedent rationale transfers to new context.

        FAIL-CLOSED: Returns is_valid=False on any error.

        Args:
            material: Target material designation (e.g., "INCONEL 625").
            environment_desc: Target environment description
                (e.g., "100% O2 at 14.7 PSIA, 70°F").
            precedents: List of supporting precedent results from search.
            req_id: Request ID for logging/traceability.

        Returns:
            RationaleValidationResult with validation decision and rationale.
        """
        # Empty precedents = invalid
        if not precedents:
            LOGGER.warning(
                "LogicValidator called with no precedents",
                extra={"req_id": req_id},
            )
            return RationaleValidationResult(
                is_valid=False,
                reasoning="No precedents provided for validation",
                source=f"LogicValidator:{req_id}",
            )

        try:
            # Build prompt
            prompt = self._build_prompt(material, environment_desc, precedents)

            # Call LLM
            LOGGER.debug(
                f"LogicValidator calling {self.MODEL}",
                extra={"req_id": req_id, "precedent_count": len(precedents)},
            )

            message = self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                temperature=self.TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text.strip()

            # Parse JSON response
            parsed = self._parse_json_response(response_text)
            if parsed is None:
                LOGGER.error(
                    "LogicValidator failed to parse LLM response",
                    extra={"req_id": req_id, "response": response_text[:500]},
                )
                return RationaleValidationResult(
                    is_valid=False,
                    reasoning=f"Failed to parse LLM response: {response_text[:200]}",
                    source=f"LogicValidator:{req_id}",
                )

            # Build result from parsed JSON
            result = self._build_result_from_json(parsed, req_id)

            LOGGER.info(
                f"LogicValidator result: is_valid={result.is_valid}",
                extra={
                    "req_id": req_id,
                    "citations": result.citations,
                    "rejected": result.rejected_precedents,
                },
            )

            return result

        except Exception as e:
            # FAIL CLOSED on any error
            LOGGER.error(
                f"LogicValidator error: {e}",
                extra={"req_id": req_id},
                exc_info=True,
            )
            return RationaleValidationResult(
                is_valid=False,
                reasoning=f"Validation error: {str(e)}",
                source=f"LogicValidator:{req_id}",
            )

    def _build_prompt(
        self,
        material: str,
        environment_desc: str,
        precedents: list[EnrichedMUAResult],
    ) -> str:
        """Build the validation prompt.

        Prompt instructs LLM to:
        1. READ each precedent's rationale
        2. CHECK if reasoning applies to target
        3. REJECT precedents with non-transferable mitigations
        4. SYNTHESIZE rationale from valid precedents only
        """
        # Format precedents
        precedent_texts = []
        for i, p in enumerate(precedents, 1):
            rationale = p.rationale or "(no rationale provided)"
            precedent_texts.append(f"""
PRECEDENT {i}: {p.mua_number}
  Material: {p.material_designation}
  Family: {p.material_family or 'Unknown'}
  Environment: {p.environment or 'Not specified'}
  Category: {p.category or 'Not specified'}
  Determination: {p.determination}
  Rationale: {rationale}
""")

        precedents_section = "\n".join(precedent_texts)

        return f"""You are a NASA materials safety expert validating Material Usage Agreement (MUA) precedents.

TARGET REQUEST:
- Material: {material}
- Environment: {environment_desc}

PRECEDENT DOCUMENTS:
{precedents_section}

YOUR TASK:
1. READ each precedent's rationale carefully
2. EVALUATE if the rationale logic transfers to the TARGET environment
3. REJECT a precedent if:
   - Its rationale relies on mitigations NOT present in target (e.g., "sealed container", "overwrapped", "inert atmosphere")
   - The precedent's environment is LESS SEVERE than target (lower O2%, lower pressure, narrower temp range)
   - The rationale is empty or says only "see attached" or similar
   - The material family does not match
4. ACCEPT precedents whose rationale logic validly applies
5. SYNTHESIZE a rationale for the target using ONLY accepted precedents
   - Include MUA citations in the rationale text (e.g., "per MUA-1234")
   - If NO precedents are valid, set is_valid to false

IMPORTANT RULES:
- Be CONSERVATIVE - when in doubt, reject the precedent
- Empty rationale = automatic rejection
- "Approved for similar application" without specifics = reject
- Mitigation-dependent rationale (containers, covers, etc.) = reject unless target has same

Return ONLY a valid JSON object with this exact structure:
{{
  "is_valid": true or false,
  "synthesized_rationale": "Your synthesized rationale text with MUA citations, or empty string if invalid",
  "citations": ["MUA-1234", "MUA-5678"],
  "rejected_precedents": ["MUA-9999"],
  "rejection_reasons": {{"MUA-9999": "Reason for rejection"}},
  "reasoning": "Your step-by-step evaluation explaining how you reached this conclusion"
}}

Return ONLY the JSON, no markdown formatting, no explanation outside the JSON."""

    def _parse_json_response(self, response_text: str) -> Optional[dict[str, Any]]:
        """Robust JSON parsing from LLM response.

        Handles markdown code blocks, ellipsis, and malformed JSON.
        Pattern from haiku_client.py.
        """
        # Remove markdown code blocks
        if "```" in response_text:
            parts = response_text.split("```")
            for part in parts:
                if not part.strip():
                    continue
                # Remove language identifier
                if part.strip().startswith("json"):
                    part = part.strip()[4:]
                try:
                    return json.loads(part.strip())
                except json.JSONDecodeError:
                    continue

        # Try direct JSON parsing
        try:
            return json.loads(response_text.strip())
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in text
        json_match = re.search(r'\{[\s\S]*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # Try to fix common issues (ellipsis truncation)
                json_str_fixed = re.sub(r',\s*\.\.\.\s*}', '}', json_str)
                try:
                    return json.loads(json_str_fixed)
                except json.JSONDecodeError:
                    pass

        return None

    def _build_result_from_json(
        self,
        parsed: dict[str, Any],
        req_id: str,
    ) -> RationaleValidationResult:
        """Build RationaleValidationResult from parsed JSON.

        Handles missing/malformed fields gracefully.
        """
        return RationaleValidationResult(
            is_valid=bool(parsed.get("is_valid", False)),
            synthesized_rationale=str(parsed.get("synthesized_rationale", "")),
            citations=list(parsed.get("citations", [])),
            rejected_precedents=list(parsed.get("rejected_precedents", [])),
            rejection_reasons=dict(parsed.get("rejection_reasons", {})),
            reasoning=str(parsed.get("reasoning", "")),
            source=f"LogicValidator:{req_id}",
        )
