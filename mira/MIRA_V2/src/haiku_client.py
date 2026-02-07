#!/usr/bin/env python3
"""
Module: Haiku Client
Purpose: Claude Haiku API Client - Structured extraction for MUAs and Standards

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

import json
import os
import re
from typing import Dict, Any, Optional
from anthropic import Anthropic


class HaikuClient:
    """Claude Haiku API client for structured extraction."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Haiku client."""
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.client = Anthropic(api_key=self.api_key)
        self.model = "claude-3-haiku-20240307"

    def extract_structured_json(
        self,
        prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0
    ) -> Optional[Dict[str, Any]]:
        """
        Extract structured JSON from Haiku.

        Args:
            prompt: Full prompt with system instructions and data
            max_tokens: Max response tokens (default 1500)
            temperature: Temperature (0 for deterministic)

        Returns:
            Parsed JSON dict or None if parsing fails
        """
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            # Parse JSON from response
            return self._parse_json_response(response_text)

        except Exception as e:
            print(f"Haiku API error: {e}")
            return None

    def _parse_json_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """
        Robust JSON parsing from Haiku response.
        Handles markdown code blocks, ellipsis, and malformed JSON.
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

    def extract_mua_fields(self, pdf_text: str) -> Optional[Dict[str, Any]]:
        """
        Extract MUA fields from PDF text.
        Uses the proven robust prompt from test_claude_single_robust.py
        """
        # Truncate to reasonable length
        text_sample = pdf_text[:4500]

        prompt = f"""You are extracting data from a NASA Material Usage Agreement (MUA) form.

MUA forms have these sections (look for these labels):
- MATERIAL DESIGNATION / MATERIAL / ITEM DESCRIPTION
- SPECIFICATION (like MIL-C-5541, AMS-1234, QQ-N-290, ASTM)
- MANUFACTURER
- MATERIAL CODE (MAPTIS code, often "NA" or 5-6 digits)
- PRESSURE (PSIA) - often "Vacuum" or a number
- TEMPERATURE (F or C) - often a range like "-60 to 140"
- MEDIA - environmental media, often "NA"
- ENVIRONMENT - checkbox marked HABITABLE or NONHABITABLE
- RATIONALE - long text justifying material use
- APPLICATION - how/where material is used

CRITICAL EXTRACTION RULES:
1. For material_designation: Extract the ACTUAL MATERIAL NAME, not the label
   - Examples: "CONNECTORS", "Nylon (Polyamide)", "Stainless Steel 316", "Printed Circuit Board"
   - NOT: "MATERIAL", "ITEM DESCRIPTION", "See below"

2. For specification: Look for standard formats like MIL-*, AMS*, QQ-*, ASTM*, MS*
   - Examples: "MIL-C-5541", "AMS-1234", "QQ-N-290", "MS 3367-66"

3. For material_code: Usually "NA" or "N/A", sometimes a 5-6 digit number

4. For environment: Must be exactly "HABITABLE" or "NONHABITABLE" (check which box is marked)

5. For rationale: Extract the complete text from RATIONALE section (usually long paragraph)

6. For application: Extract complete APPLICATION section text

7. If a field is not found or unclear, use null

MUA DOCUMENT TEXT:
{text_sample}

Return ONLY a valid JSON object with these exact fields:
{{
  "material_designation": "the actual material name",
  "specification": "specification number or null",
  "material_code": "MAPTIS code or null",
  "pressure_psia": "pressure value or null",
  "temperature_f": "temperature range or null",
  "media": "media type or null",
  "environment": "HABITABLE or NONHABITABLE or null",
  "rationale": "rationale text or null",
  "application": "application text or null"
}}

Return ONLY the JSON, no markdown formatting, no explanation."""

        return self.extract_structured_json(prompt)

    def extract_standard_section(
        self,
        spec_id: str,
        section_number: str,
        heading: str,
        text: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract structured data from a standards section (e.g., NASA-STD-6016).

        Uses Haiku to enrich Python-parsed sections with:
        - Better summaries
        - Correct metadata tags (environment, phase, system, family)
        - Structured requirement predicates

        Returns JSON matching bok.sections + bok.requirements schema.
        """
        prompt = f"""You are an assistant that converts NASA standards into a structured Body of Knowledge for an oxygen/hydrogen materials constraint engine.

Input: a single section of {spec_id}, including section number, heading, and full text.
Output: a single JSON object with these fields:

* spec_id: always "{spec_id}"
* section_number: like "{section_number}"
* heading: heading text
* is_normative: true if the section imposes requirements (shall/shall not), false if it only provides rationale or background
* section_summary: 1-3 sentences, plain English summary
* applies_env: list of environments (e.g., ["oxygen"], ["hydrogen"], ["vacuum"])
* applies_phase: list of phases (e.g., ["gas"], ["liquid"])
* applies_system: list of system types (e.g., ["valve", "regulator", "tank", "line", "seal"])
* applies_family: list of material families (e.g., ["aluminum", "stainless_steel", "elastomer"])
* requirements: list of requirement objects:

  * action: one of "approve", "approve_with_limits", "prohibit", "require_test"
  * description: the requirement rewritten as one sentence
  * predicate: JSON object encoding applicable constraints:

    * env: environment string
    * phase: phase string
    * family: material family string
    * pressure_max / pressure_min: {{"lte" or "gte": number, "unit": "psia|psi|bar|kpa|mpa"}}
    * temp_max / temp_min: {{"lte" or "gte": number, "unit": "C|F|K"}}

If the section has no clear requirements, return an empty list for requirements.
If you are unsure about any field, use null or [] instead of guessing.
Return only valid JSON. No comments, no extra text.

SECTION DATA:
Spec ID: {spec_id}
Section Number: {section_number}
Heading: {heading}

Text:
{text[:3000]}

Return ONLY the JSON object:"""

        return self.extract_structured_json(prompt, max_tokens=2000)
