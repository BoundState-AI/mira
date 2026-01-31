#!/usr/bin/env python3
"""
Module: Llm Answer Generator
Purpose: LLM Answer Generator for MIRA V2

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

import os
import re
import requests
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass


# ============================================================================
# ENHANCED SYSTEM PROMPT WITH HARD SAFETY RULES
# ============================================================================

DECISION_SYSTEM_PROMPT = """# MIRA LLM CONTRACT - DO NOT VIOLATE

This is the strict rulebook for answer generation in MIRA.
If you violate any clause, the answer must be rejected.

## SECTION 1 - EVIDENCE BOUNDARY (MOST IMPORTANT)

**You may ONLY use information that appears in the EVIDENCE block.**
You may not invent, infer, or embellish beyond what is explicitly stated.

### 1.1 Allowed references:

You may ONLY mention:
* MUA IDs that appear *verbatim* in EVIDENCE
* Material names/families EXACTLY as listed in EVIDENCE
* Numeric limits EXACTLY as written in EVIDENCE
* Standard/spec numbers that appear in EVIDENCE
* Compatibility outcomes (approved / conditional / denied) from EVIDENCE

If something is **not** in EVIDENCE, **you must not mention it.**

### 1.2 Prohibited:

The following are **strictly forbidden**:
* Inventing new MUAs (e.g., "MUA-1234" if not in EVIDENCE)
* Inventing numeric limits
* Mentioning standards not in evidence
* Inferring oxygen compatibility from non-oxygen MUAs
* Generalizing from one alloy to another

If an answer requires information not in EVIDENCE, you must say:
> "This cannot be determined from the available evidence."

## SECTION 2 - MATERIAL MATCHING

The question's material MUST match the evidence.

### 2.1 Hard material lock:

If the question is about **316 stainless steel**, you may ONLY consider evidence rows whose:
* normalized material
* alloy
* spec number
* or material family

match *316 stainless*.

Evidence about *other alloys* (e.g., 15-5PH, Hastelloy, Aluminum 6061) **must be excluded**.

### 2.2 If no matching material exists:

Then the only allowed decision outcomes are:
* **REQUIRES_TESTING**
* **NEEDS_REVIEW**

Not **YES** or **NO**.

## SECTION 3 - ENVIRONMENT MATCHING

### 3.1 Environment must match exactly:

You may NOT infer oxygen compatibility from:
* air
* nitrogen
* vacuum
* generic "clean gas"
* unspecified environments

If the question environment != evidence environment, your answer must say:
> "Environment mismatch: no direct oxygen evidence."

Allowed decisions:
* **REQUIRES_TESTING**
* **CONDITIONAL (with explicit mismatch callout)**

### 3.2 EXCEPTION - BOK Prohibitions Override Environment Mismatch:

**CRITICAL SAFETY RULE:** If a BOK Standard contains explicit prohibition language ("shall not be used", "prohibited for use", "must not be used") with a numeric limit for the EXACT environment in the question (e.g., "shall not be used in oxygen above 100 psia"), you MUST answer **NO** even if MUA precedents show environment mismatch.

BOK Standards are authoritative safety requirements that supersede MUA historical data.

Example: If question asks about aluminum in oxygen at 200 psi, and JSC-27301 says "shall not be used above 100 psia in GOX", answer must be **NO**, regardless of air/vacuum MUA precedents.

### 3.3 "GOX" and "LOX" are distinct environments:

You must not treat GOX <-> LOX as equivalent.

## SECTION 4 - NUMERIC LIMITS (STRICT RULES)

### 4.1 Quote-only rule:

You may ONLY quote numeric limits that:
* appear explicitly in EVIDENCE
* have units validated by the evidence metadata

If the evidence unit is missing, ambiguous, or mismatched, you must say:
> "Unit reliability: numeric limit cannot be used."

### 4.2 Sanity filter:

You must ignore numeric values that are obviously invalid, including:
* Temperature > 2000°C
* Pressure > 50,000 psi
* Negative pressures
* Floating-point garbage values (e.g., 12545 C, 3.402e38)

If insane values appear in EVIDENCE, explicitly state:
> "Discarding invalid numeric values per unit sanity rules."

## SECTION 5 - DECISION RULES

### CRITICAL: Decision Priority Order (check in this order):

**STEP 1 - Check BOK Prohibitions FIRST (highest priority):**
* Check if a BOK Standard explicitly prohibits the material for the exact environment in question
* **CRITICAL BOUNDARY LOGIC** - When BOK says "shall not be used above X psia":
  * "above X" means > X, so X is the MAXIMUM ALLOWED value
  * Query pressure > stated limit → **NO** (EXCEEDS the limit - prohibited)
  * Query pressure = stated limit → **CONDITIONAL** (AT the boundary - needs engineering review)
  * Query pressure < stated limit → Continue to Step 2 (within allowed range)
* Example: BOK says "shall not be used above 100 psia in GOX"
  * Query asks 200 psi → **NO** (200 > 100, exceeds limit)
  * Query asks 100 psi → **CONDITIONAL** (100 = 100, at the limit boundary)
  * Query asks 50 psi → Continue to Step 2 (50 < 100, within limit)
* **OVERRIDES all MUA environment mismatches** - even if MUAs show air/vacuum approval
* If BOK says NO for oxygen, answer is NO regardless of other evidence

**STEP 2 - Then check environment matching:**
* If question environment does NOT match evidence environment:
  * Check if STEP 1 found a BOK prohibition for the correct environment
  * If yes → answer is **NO** (BOK prohibition applies)
  * If no BOK prohibition exists → answer is **REQUIRES_TESTING** (cannot infer across environments)

**STEP 3 - Then evaluate positive evidence:**
* **YES** - only if:
  * direct material match AND
  * direct environment match AND
  * unit-verified numeric limit >= requested limit

* **CONDITIONAL** - allowed if:
  * evidence suggests plausibility but data incomplete
  * material match exists but limits unclear

### Summary of allowed decisions:

* **NO** - BOK Standard explicitly prohibits it OR failure data directly matches material + environment
* **YES** - Direct material + environment match with verified numeric limits
* **CONDITIONAL** - Plausible but incomplete data
* **REQUIRES_TESTING** - Environment mismatch exists and no BOK prohibition found

### Everything else:

If no rule gives a definitive decision:
> "NEEDS_REVIEW"

## SECTION 6 - PROHIBITED BEHAVIORS

You MUST NOT:
* Make up MUAs
* Make up temperatures
* Make up pressures
* Rename materials
* Infer from unrelated alloys
* Use generic "engineering intuition"
* Provide advice not grounded in evidence
* Speculate about design solutions
* Offer opinions (only evidence logic)

## SECTION 7 - SAFETY PRINCIPLE

When in doubt:
> **"Favor uncertainty over invention."**

If you cannot prove it from evidence, the answer must default to:
* **REQUIRES_TESTING**
* **NEEDS_REVIEW**

Not **YES** and not **NO**.

## OUTPUT FORMAT

```
DECISION: <YES | NO | CONDITIONAL | REQUIRES_TESTING | NEEDS_REVIEW>

REASONING:

**STEP 1 - BOK Prohibition Check (HIGHEST PRIORITY):**
- Does any BOK Standard explicitly prohibit this material for this exact environment?
- Apply BOUNDARY LOGIC when BOK states "above X psia" or "below X":
  * Query > limit → DECISION must be **NO** (exceeds the stated limit)
  * Query = limit → DECISION must be **CONDITIONAL** (at the boundary, needs review)
  * Query < limit → Continue to Step 2 (within allowed range)
- Example: JSC-27301F says "aluminum shall not be used above 100 psia in GOX"
  * Query asks 200 psi → **NO** (200 > 100)
  * Query asks 100 psi → **CONDITIONAL** (100 = 100, at boundary)
  * Query asks 50 psi → Continue to Step 2 (50 < 100)

**STEP 2 - Environment Matching:**
- Only perform this check if STEP 1 found NO prohibition
- Does MUA/test data environment match the question environment?
- If NO match and NO prohibition from STEP 1 → REQUIRES_TESTING

**STEP 3 - Material and Numeric Analysis:**
- Material match check: Does material exactly match evidence?
- Unit reliability check: Are numeric limits unit-validated?
- Margin analysis: Do limits exceed requested values?
- Evidence citations: List MUA IDs and BOK standards used

Limitations:
- List gaps in evidence, ambiguities, assumptions made

Mitigations:
- List any mitigation strategies mentioned in evidence (if none, state "None")

Final Statement:
- One sentence final decision based on STEPS 1-3 above
```

During MIRA reasoning, you must be literal, precise, conservative, evidence-bound, and standard-driven. No storytelling, no metaphors, no invented content, no hallucinated references.
"""


# ============================================================================
# EVIDENCE BUNDLE FORMATTER
# ============================================================================

@dataclass
class EvidenceBundle:
    """
    Formatted evidence bundle for LLM decision-making.

    Pre-formatted with:
    - Rounded numeric values
    - Explicit unit fields
    - Unit status flags
    - Environment compatibility flags
    """
    material_id: str
    material_name: str

    # Requirements
    required_env: Optional[str]
    required_pressure_psia: Optional[float]
    required_temp_c: Optional[float]

    # Test data (pre-formatted)
    tested_env: Optional[str]
    tested_pressure_psia: Optional[float]
    tested_temp_c: Optional[float]

    # Unit status
    unit_status: Dict[str, str]  # "ok" / "missing" / "ambiguous"

    # Flags
    env_mismatch: bool
    unit_ambiguous: bool

    # Supporting evidence
    bok_requirements: List[Dict[str, Any]]
    mua_precedents: List[Dict[str, Any]]

    def to_llm_prompt(self) -> str:
        """
        Format evidence bundle as LLM prompt.

        Includes explicit warnings about unit status and environment mismatch.
        """
        lines = []

        lines.append(f"MATERIAL: {self.material_name} (ID: {self.material_id})")
        lines.append("")

        lines.append("REQUIREMENTS:")
        lines.append(f"  Environment: {self.required_env or 'not specified'}")

        if self.required_pressure_psia is not None:
            lines.append(f"  Max Pressure: {self.required_pressure_psia:.1f} psia")
        else:
            lines.append(f"  Max Pressure: not specified")

        if self.required_temp_c is not None:
            lines.append(f"  Max Temperature: {self.required_temp_c:.1f} °C")
        else:
            lines.append(f"  Max Temperature: not specified")
        lines.append("")

        lines.append("TEST DATA:")
        lines.append(f"  Tested Environment: {self.tested_env or 'UNKNOWN'}")

        if self.tested_pressure_psia is not None:
            lines.append(f"  Tested Pressure: {self.tested_pressure_psia:.1f} psia")
        else:
            lines.append(f"  Tested Pressure: MISSING")

        if self.tested_temp_c is not None:
            lines.append(f"  Tested Temperature: {self.tested_temp_c:.1f} °C")
        else:
            lines.append(f"  Tested Temperature: MISSING")
        lines.append("")

        # CRITICAL: Unit status warnings
        lines.append("UNIT STATUS:")
        for field, status in self.unit_status.items():
            if status != "ok":
                lines.append(f"  ⚠️  {field}: {status.upper()}")
                lines.append(f"      → Cannot use as reliable limit!")
            else:
                lines.append(f"  ✓ {field}: {status}")
        lines.append("")

        # CRITICAL: Environment mismatch warning
        if self.env_mismatch:
            lines.append("⚠️  ENVIRONMENT MISMATCH DETECTED")
            lines.append(f"    Tested in: {self.tested_env}")
            lines.append(f"    Required for: {self.required_env}")
            lines.append(f"    → Do NOT infer compatibility across environments")
            lines.append("")

        # BOK requirements
        if self.bok_requirements:
            lines.append("BOK REQUIREMENTS:")
            for req in self.bok_requirements[:5]:  # Top 5
                spec_id = req.get('spec_id', 'UNKNOWN')
                section = req.get('section_number', '')
                summary = req.get('description', req.get('summary', ''))[:100]
                lines.append(f"  • {spec_id} § {section}: {summary}")
            lines.append("")

        # MUA precedents
        if self.mua_precedents:
            lines.append("MUA PRECEDENTS:")
            for mua in self.mua_precedents[:3]:  # Top 3
                mua_num = mua.get('mua_number', 'UNKNOWN')
                env = mua.get('inferred_environment', mua.get('env_class', 'unknown'))
                pressure = mua.get('pressure_psi_max', 'N/A')
                determination = mua.get('determination', 'unknown')
                is_primary = mua.get('is_primary_for_env', False)
                match_str = "✓ MATCHES" if is_primary else "⚠️ NON-MATCHING"
                lines.append(f"  • {mua_num} - {env} environment ({match_str})")
                lines.append(f"    Pressure: {pressure} psi, Status: {determination}")
            lines.append("")

        return "\n".join(lines)


class LLMAnswerGenerator:
    """
    Generates natural language answers using LOCAL LLM based on evidence collected.
    """

    # Regex to extract numeric limits with units from evidence
    NUMERIC_LIMIT_PATTERN = re.compile(
        r"""
        (?P<value>-?\d+(?:\.\d+)?)        # number (with optional negative and decimal)
        \s*
        (?P<unit>
            psia|psi|bar|torr|mmHg|kPa|MPa|Pa|
            °C|C|°F|F|K|
            percent|%|
            atm|atmospheres?|
            psig
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def __init__(self, base_url: Optional[str] = None, model: str = "llama3.1:8b-instruct-q4_K_M", provider: str = "ollama"):
        """
        Initialize with local LLM endpoint or Haiku.

        Args:
            base_url: Ollama endpoint (default: http://localhost:11434)
            model: Model name (default: llama3.1:8b-instruct-q4_K_M)
            provider: "ollama" or "haiku" (default: ollama)
        """
        self.provider = provider
        self.base_url = base_url or os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        self.model = model
        self.endpoint = f"{self.base_url}/api/generate"

        if provider == "haiku":
            from .haiku_client import HaikuClient
            self.haiku_client = HaikuClient()
            print(f"[LLM] Using Claude Haiku (claude-3-haiku-20240307)")
        else:
            self.haiku_client = None
            print(f"[LLM] Using local model: {self.model} at {self.base_url}")

    def _is_numeric_value_sane(self, value: float, unit: str) -> bool:
        """
        Sanity check numeric values to filter out obviously invalid data.

        Per llm_fix.md Section 4.2 Sanity filter:
        - Temperature > 2000°C
        - Pressure > 50,000 psi
        - Negative pressures
        - Floating-point garbage values

        Args:
            value: Numeric value to check
            unit: Unit string

        Returns:
            True if value is sane, False otherwise
        """
        unit_lower = unit.lower()

        # Temperature checks
        if any(temp_unit in unit_lower for temp_unit in ['c', '°c', 'f', '°f', 'k']):
            # Convert to Celsius for checking
            if 'f' in unit_lower:
                value_c = (value - 32) * 5/9
            elif 'k' in unit_lower:
                value_c = value - 273.15
            else:
                value_c = value

            # Reject temperatures > 2000°C or < -273°C (absolute zero)
            if abs(value_c) > 2000:
                return False

        # Pressure checks
        if any(press_unit in unit_lower for press_unit in ['psi', 'bar', 'pa', 'kpa', 'mpa', 'torr', 'mmhg', 'atm']):
            # Reject negative pressures
            if value < 0:
                return False

            # Convert to psi for checking
            if 'mpa' in unit_lower:
                value_psi = value * 145.038
            elif 'kpa' in unit_lower:
                value_psi = value * 0.145038
            elif 'pa' in unit_lower and 'mpa' not in unit_lower and 'kpa' not in unit_lower:
                value_psi = value * 0.000145038
            elif 'bar' in unit_lower:
                value_psi = value * 14.5038
            elif 'torr' in unit_lower or 'mmhg' in unit_lower:
                value_psi = value * 0.0193368
            elif 'atm' in unit_lower:
                value_psi = value * 14.6959
            else:
                value_psi = value

            # Reject pressures > 50,000 psi
            if value_psi > 50000:
                return False

        # Check for floating-point garbage (e.g., 3.402e38, very large numbers)
        if abs(value) > 1e6:  # Suspiciously large
            return False

        return True

    def _extract_numeric_limits(self, evidence_texts: List[str]) -> List[str]:
        """
        Extract literal numeric + unit snippets from evidence.

        These are the ONLY limits the LLM is allowed to quote.
        We deliberately keep them in their original units.

        Now includes sanity checking per llm_fix.md to filter out:
        - Temperature > 2000°C
        - Pressure > 50,000 psi
        - Negative pressures
        - Floating-point garbage values
        """
        snippets: List[str] = []
        seen: Set[str] = set()
        rejected_count = 0

        for text in evidence_texts:
            for match in self.NUMERIC_LIMIT_PATTERN.finditer(text):
                snippet = match.group(0).strip()
                value_str = match.group('value')
                unit = match.group('unit')

                try:
                    value = float(value_str)

                    # Sanity check the value
                    if not self._is_numeric_value_sane(value, unit):
                        rejected_count += 1
                        print(f"[LLM] Rejected insane numeric value: {snippet}")
                        continue

                    if snippet not in seen:
                        seen.add(snippet)
                        snippets.append(snippet)

                except ValueError:
                    # Skip if value can't be parsed as float
                    continue

        if rejected_count > 0:
            print(f"[LLM] Filtered out {rejected_count} insane numeric value(s)")

        return snippets

    def _validate_mua_references(self, answer: str, allowed_mua_ids: Set[str]) -> bool:
        """
        Validate that LLM answer only references MUAs from the evidence.

        Per llm_fix.md: "any string matching MUA- must be in that list;
        otherwise, the answer is rejected or the LLM is re-prompted."

        Args:
            answer: LLM-generated answer
            allowed_mua_ids: Set of MUA IDs that appeared in evidence

        Returns:
            True if valid (all MUA refs are in allowed set), False if invalid
        """
        # Extract all MUA references from answer
        mua_pattern = re.compile(r'MUA-[\w\-]+', re.IGNORECASE)
        referenced_muas = set(mua_pattern.findall(answer))

        # Check if any referenced MUA is not in allowed set
        invalid_muas = []
        for mua_ref in referenced_muas:
            # Normalize for case-insensitive comparison
            if not any(mua_ref.lower() == allowed.lower() for allowed in allowed_mua_ids):
                invalid_muas.append(mua_ref)

        if invalid_muas:
            print(f"[LLM] WARNING: Answer contains hallucinated MUA IDs: {invalid_muas}")
            print(f"[LLM] Allowed MUAs were: {allowed_mua_ids}")
            return False

        return True

    def generate_answer(
        self,
        query: str,
        mua_precedents: List[Dict],
        semantic_evidence: Optional[Dict],
        decisions: List[Dict],
        requirements: List[Dict]
    ) -> str:
        """
        Generate a natural language answer based on all available evidence.

        Args:
            query: The user's original question
            mua_precedents: MUA precedent records found
            semantic_evidence: Semantic search results
            decisions: Material decisions generated
            requirements: BOK requirements evaluated

        Returns:
            Natural language answer as a string
        """
        # Extract numeric limits from all evidence (MUA + BOK)
        evidence_texts: List[str] = []

        # Add MUA rationales
        for mua in (mua_precedents or []):
            if mua.get('rationale'):
                evidence_texts.append(str(mua['rationale']))
            if mua.get('rationale_summary'):
                evidence_texts.append(str(mua['rationale_summary']))

        # Add BOK high-confidence results (CRITICAL: includes prohibitions like JSC-27301F)
        if semantic_evidence:
            print(f"[DEBUG] semantic_evidence keys: {semantic_evidence.keys()}")
            bok_high = semantic_evidence.get('bok_standards', {}).get('high', [])
            print(f"[DEBUG] Found {len(bok_high)} BOK high-confidence results")
            for result in bok_high[:10]:  # Top 10 BOK results
                # Extract content text
                if hasattr(result, 'content') and result.content:
                    content_text = result.content.get('text', result.content.get('content', ''))
                    if content_text:
                        print(f"[DEBUG] Added BOK content (hasattr): {len(content_text)} chars")
                        evidence_texts.append(str(content_text))
                elif isinstance(result, dict) and result.get('content'):
                    content = result['content']
                    content_text = content.get('text', content.get('content', ''))
                    if content_text:
                        print(f"[DEBUG] Added BOK content (dict): {len(content_text)} chars")
                        evidence_texts.append(str(content_text))
        else:
            print("[DEBUG] No semantic_evidence provided!")

        print(f"[DEBUG] Total evidence_texts: {len(evidence_texts)}")
        numeric_limits = self._extract_numeric_limits(evidence_texts)
        print(f"[DEBUG] Extracted numeric_limits: {numeric_limits}")

        # Build context using legacy method (for backward compatibility)
        context = self._build_context(
            mua_precedents,
            semantic_evidence,
            decisions,
            requirements
        )

        # Extract unit status and environment info from decisions (if available)
        # MaterialDecider will provide these fields in future
        unit_status = {"temperature": "ok", "pressure": "ok"}  # Default to ok
        env_mismatch = False

        # Check if any decision indicates environment mismatch or unit issues
        for decision in (decisions or []):
            if decision.get('caveats'):
                caveats = decision['caveats']
                if any('environment' in str(c).lower() for c in caveats):
                    env_mismatch = True
                if any('unit' in str(c).lower() or 'ambiguous' in str(c).lower() for c in caveats):
                    unit_status = {"temperature": "ambiguous", "pressure": "ambiguous"}

        # Build enhanced evidence bundle for top material (if available)
        if decisions and len(decisions) > 0:
            top_decision = decisions[0]

            # Try to build EvidenceBundle for structured prompting
            bundle = EvidenceBundle(
                material_id=top_decision.get('material_id', 'unknown'),
                material_name=top_decision.get('material_name', 'Unknown Material'),
                required_env=None,  # TODO: Extract from query parse
                required_pressure_psia=None,  # TODO: Extract from constraints
                required_temp_c=None,  # TODO: Extract from constraints
                tested_env=None,  # TODO: Get from material test data
                tested_pressure_psia=None,  # TODO: Get from material test data
                tested_temp_c=None,  # TODO: Get from material test data
                unit_status=unit_status,
                env_mismatch=env_mismatch,
                unit_ambiguous=any(status != 'ok' for status in unit_status.values()),
                bok_requirements=requirements[:5] if requirements else [],
                mua_precedents=mua_precedents[:3] if mua_precedents else [],
            )

            # Get structured evidence prompt
            evidence_prompt = bundle.to_llm_prompt()

            # Combine with query and context
            full_prompt = f"""{DECISION_SYSTEM_PROMPT}

QUESTION: {query}

{evidence_prompt}

ADDITIONAL CONTEXT:
{context}

ALLOWED NUMERIC LIMITS (from evidence - DO NOT convert units):
"""
            if numeric_limits:
                print(f"[DEBUG] Adding {len(numeric_limits)} numeric limits to prompt")
                for item in numeric_limits:
                    full_prompt += f"  - {item}\n"
            else:
                print("[DEBUG] WARNING: No numeric limits found!")
                full_prompt += "  - (None found in evidence)\n"

            print(f"[DEBUG] ALLOWED NUMERIC LIMITS section contains: {numeric_limits}")

            full_prompt += """
TASK: Provide a comprehensive technical answer based on the evidence above. Your answer should:
- Start with a clear YES/NO/CONDITIONAL/REQUIRES_TESTING answer
- Cite specific MUA precedent numbers and their determinations
- ONLY quote numeric limits that appear in the ALLOWED list above
- Quote or summarize the full rationale from MUA precedents
- Note if the MUA environment matches or does NOT match the question environment
- List any limitations, conditions, or mitigations
- Be thorough and detailed (3-4 paragraphs minimum)

This answer will be used for critical NASA engineering decisions, so accuracy is paramount.

ANSWER:
"""
        else:
            # Fallback to legacy prompt if no decisions available
            full_prompt = self._create_prompt(query, context, numeric_limits)

        # Build allowed MUA ID set for validation
        allowed_mua_ids = set()
        for mua in (mua_precedents or []):
            if mua.get('mua_number'):
                allowed_mua_ids.add(str(mua['mua_number']))

        # Call LLM (Haiku or Ollama)
        try:
            if self.provider == "haiku":
                # Call Claude Haiku API
                message = self.haiku_client.client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=2000,
                    temperature=0.0,
                    messages=[{"role": "user", "content": full_prompt}]
                )
                llm_answer = message.content[0].text.strip()
            else:
                # Call local LLM (Ollama)
                response = requests.post(
                    self.endpoint,
                    json={
                        "model": self.model,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.0,  # Deterministic for consistent responses
                            "num_predict": 2000,  # Increased for longer answers
                            "repeat_penalty": 1.1,  # Prevent early stopping
                            "top_p": 0.9  # Nucleus sampling
                        }
                    },
                    timeout=120  # Increased timeout for longer responses
                )

                response.raise_for_status()
                result = response.json()
                llm_answer = result.get('response', 'Error: No response from LLM')

            # Validate MUA references (per llm_fix.md)
            if not self._validate_mua_references(llm_answer, allowed_mua_ids):
                # Prepend warning to answer if validation fails
                llm_answer = (
                    "WARNING: This answer may contain hallucinated MUA references. "
                    "Verify all MUA citations against the evidence.\n\n" +
                    llm_answer
                )

            return llm_answer

        except requests.exceptions.ConnectionError:
            return "ERROR: Cannot connect to local LLM. Is Ollama running? (ollama serve)"
        except Exception as e:
            return f"ERROR: {str(e)}"

    def _build_context(
        self,
        mua_precedents: List[Dict],
        semantic_evidence: Optional[Dict],
        decisions: List[Dict],
        requirements: List[Dict]
    ) -> str:
        """Build evidence context for the LLM."""
        parts = []

        # MUA Precedents (highest priority)
        if mua_precedents:
            parts.append("## MUA Precedents (NASA Historic Decisions)\n")
            for mua in mua_precedents[:3]:  # Top 3
                parts.append(f"**{mua.get('mua_number', 'Unknown')}**: {mua.get('material_name', 'Unknown')}")
                parts.append(f"- Determination: {mua.get('determination', 'Unknown')}")
                if mua.get('pressure_psi_max'):
                    parts.append(f"- Max Pressure: {mua.get('pressure_psi_max')} psi")
                if mua.get('temp_c_max'):
                    parts.append(f"- Max Temp: {mua.get('temp_c_max')}°C")
                if mua.get('rationale'):
                    # Include full rationale for comprehensive answers
                    rationale = mua['rationale']
                    parts.append(f"- Rationale: {rationale}")
                if mua.get('mitigations'):
                    parts.append(f"- Mitigations: {mua['mitigations']}")
                if mua.get('rationale_summary'):
                    parts.append(f"- Summary: {mua['rationale_summary']}")
                parts.append("")

        # Material Decisions
        if decisions:
            parts.append("## Material Decisions\n")
            for decision in decisions[:2]:  # Top 2
                parts.append(f"**{decision.get('material_name', 'Unknown')}**")
                parts.append(f"- Confidence: {decision.get('confidence', 'N/A')}")
                parts.append(f"- Rationale: {decision.get('rationale', 'N/A')}")
                parts.append("")

        # BOK Standards (high priority safety requirements)
        if semantic_evidence and semantic_evidence.get('bok_standards'):
            bok_high = semantic_evidence['bok_standards'].get('high', [])
            if bok_high:
                parts.append("## BOK Standards (NASA Safety Requirements)\n")
                for i, result in enumerate(bok_high[:10], 1):  # Top 10 high-confidence BOK
                    # Handle both dict and ScoredResult object
                    if hasattr(result, 'metadata'):
                        spec_id = result.metadata.get('spec_id', 'Unknown')
                        section = result.metadata.get('section_number', '')
                        heading = result.metadata.get('heading', 'Untitled')
                        score = result.score
                        content_obj = result.content
                    else:
                        spec_id = result.get('metadata', {}).get('spec_id', 'Unknown')
                        section = result.get('metadata', {}).get('section_number', '')
                        heading = result.get('metadata', {}).get('heading', 'Untitled')
                        score = result.get('score', 0)
                        content_obj = result.get('content')

                    parts.append(f"**{i}. {spec_id} Section {section}** (score: {score:.3f})")
                    parts.append(f"   {heading}")

                    # Include content snippet
                    if content_obj:
                        content = content_obj.get('text', content_obj.get('content', '')) if isinstance(content_obj, dict) else str(content_obj)
                        if content:
                            # First 400 chars to keep prompt manageable
                            snippet = content[:400].strip()
                            if len(content) > 400:
                                snippet += "..."
                            parts.append(f"   {snippet}")
                    parts.append("")

        # Semantic Evidence summary
        if semantic_evidence and semantic_evidence.get('total_results', 0) > 0:
            parts.append(f"## Additional Context ({semantic_evidence['total_results']} related documents found)")
            parts.append(f"- High confidence matches: {semantic_evidence['stats'].get('high_confidence', 0)}")
            parts.append(f"- Medium confidence matches: {semantic_evidence['stats'].get('medium_confidence', 0)}")
            parts.append("")

        # Requirements (if critical)
        if requirements:
            parts.append(f"## Applicable Requirements: {len(requirements)} BOK requirements evaluated")
            parts.append("")

        return "\n".join(parts)

    def _create_prompt(self, query: str, context: str, numeric_limits: List[str]) -> str:
        """Create the LLM prompt with numeric limits safety policy."""

        # Build allowed numeric limits section
        numeric_section = "\nALLOWED NUMERIC LIMITS (from evidence - DO NOT convert units):\n"
        if numeric_limits:
            for item in numeric_limits:
                numeric_section += f"  - {item}\n"
        else:
            numeric_section += "  - (None found in evidence)\n"

        return f"""You are MIRA (Materials Information Resource Assistant), a NASA materials compatibility expert system.

QUESTION: {query}

EVIDENCE:
{context}

{numeric_section}

CRITICAL SAFETY RULES:
1. You MUST NOT invent or convert numeric limits (pressure, temperature, concentration).
2. You MUST NOT convert units. If evidence says "760 Torr", you MUST say "760 Torr", NOT "760 psi" or any other unit.
3. You may ONLY mention numeric limits from the "ALLOWED NUMERIC LIMITS" list above.
4. If no relevant numeric limit exists for the question, state this explicitly.
5. Do not extrapolate compatibility from one environment (e.g., air/vacuum) to another (e.g., oxygen).

TASK: Provide a comprehensive technical answer based on the evidence above. Your answer should:
- Start with a clear YES/NO/CONDITIONAL/REQUIRES_TESTING answer
- Cite specific MUA precedent numbers and their determinations
- ONLY quote numeric limits that appear in the ALLOWED list above
- Quote or summarize the full rationale from MUA precedents
- Note if the MUA environment matches or does NOT match the question environment
- List any limitations, conditions, or mitigations
- Be thorough and detailed (3-4 paragraphs minimum)

This answer will be used for critical NASA engineering decisions, so accuracy is paramount.

ANSWER:
"""


if __name__ == "__main__":
    # Quick test
    generator = LLMAnswerGenerator()

    # Simulated evidence
    mua = [{
        'mua_number': 'MUA-mdm-010',
        'material_name': 'Aluminum 6061-T6',
        'determination': 'APPROVED',
        'pressure_psi_max': '760.0',
        'rationale': 'Material reviewed and approved for oxygen service per NASA standards.'
    }]

    decision = [{
        'material_name': 'Aluminum 6061-T6',
        'confidence': 0.95,
        'rationale': 'Approved per MUA MUA-mdm-010'
    }]

    answer = generator.generate_answer(
        query="Can aluminum 6061 be used with oxygen at 200 psi?",
        mua_precedents=mua,
        semantic_evidence=None,
        decisions=decision,
        requirements=[]
    )

    print(answer)
