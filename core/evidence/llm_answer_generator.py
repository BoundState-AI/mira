#!/usr/bin/env python3
"""
Module: Llm Answer Generator
Purpose: LLM Answer Generator for MIRA V2 (REFACTORED)

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (traceability), SWE-033 (deterministic safety)
Safety Critical: True
"""

from __future__ import annotations

import os
import re
import requests
import logging
from enum import Enum
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field

from .boundary_checker import BoundaryCheckResult, BoundaryVerdict

logger = logging.getLogger(__name__)

# NASA-STD-8739.8B: Safety-critical module flag
__safety_critical__: bool = True

__all__ = [
    "LLMAnswerGenerator",
    "MaterialDecision",
    "EvidenceBundle",
    "EXPLANATION_SYSTEM_PROMPT",
    "explain_material_decision",
    "ValidationResult",
    "ValidationIssue",
    "ValidationSeverity",
]


# ============================================================================
# HALLUCINATION DETECTION PATTERNS
# ============================================================================

# Patterns that indicate LLM is trying to make/change a decision
DECISION_LANGUAGE_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"\b(I recommend|I suggest|I would|I believe|my analysis|in my opinion)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(should be|could be|might be) (approved|rejected|used|avoided)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(recommend|suggesting|advise) (against|for|that)\b", re.IGNORECASE
    ),
    re.compile(
        r"\bhowever,?\s*(this|the|I)\s*(should|could|might|would)\b", re.IGNORECASE
    ),
    re.compile(r"\b(my|this) (recommendation|suggestion|advice)\b", re.IGNORECASE),
]

# Patterns that indicate LLM is contradicting the decision
CONTRADICTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "decision_override",
        re.compile(
            r"should (be|really be) (NO|YES|REQUIRES|CONDITIONAL)", re.IGNORECASE
        ),
    ),
    (
        "decision_wrong",
        re.compile(
            r"(incorrect|wrong|erroneous|mistaken).{0,20}decision", re.IGNORECASE
        ),
    ),
    (
        "should_not_be",
        re.compile(r"should not be (YES|NO|APPROVED|REJECTED)", re.IGNORECASE),
    ),
    (
        "override_attempt",
        re.compile(
            r"override.{0,15}(decision|determination|verdict)", re.IGNORECASE
        ),
    ),
    (
        "disagree",
        re.compile(
            r"\b(disagree|dispute|challenge).{0,15}(decision|finding)", re.IGNORECASE
        ),
    ),
]

# Standard reference patterns for validation
BOK_REFERENCE_PATTERN = re.compile(
    r"(NASA-STD-\d+[A-Z]?|ASTM [A-Z]\d+|MIL-STD-\d+|SAE [A-Z]+\d+)"
    r"(?:[,\s]+[Ss]ection\s+)?(\d+(?:\.\d+)*)?",
    re.IGNORECASE,
)
MUA_REFERENCE_PATTERN = re.compile(r"MUA[-\s]?[\w\-]+", re.IGNORECASE)


# ============================================================================
# VALIDATION CLASSES
# ============================================================================


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationIssue:
    """A single validation issue detected in LLM output."""

    category: str
    message: str
    severity: ValidationSeverity
    matched_text: Optional[str] = None


@dataclass
class ValidationResult:
    """Complete validation result for LLM output."""

    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    hallucinated_muas: list[str] = field(default_factory=list)
    hallucinated_standards: list[str] = field(default_factory=list)
    hallucinated_values: list[str] = field(default_factory=list)
    decision_language_found: bool = False
    contradiction_found: bool = False

    def has_errors(self) -> bool:
        """Check if any error-level issues exist."""
        return any(i.severity == ValidationSeverity.ERROR for i in self.issues)

    def has_warnings(self) -> bool:
        """Check if any warning-level issues exist."""
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)

    def summary(self) -> str:
        """Generate human-readable summary of issues."""
        parts = []
        if self.hallucinated_muas:
            parts.append(f"Hallucinated MUAs: {self.hallucinated_muas}")
        if self.hallucinated_standards:
            parts.append(f"Hallucinated standards: {self.hallucinated_standards}")
        if self.hallucinated_values:
            parts.append(f"Hallucinated values: {self.hallucinated_values}")
        if self.decision_language_found:
            parts.append("Decision language detected")
        if self.contradiction_found:
            parts.append("Contradiction detected")
        return "; ".join(parts) if parts else "No issues"


# ============================================================================
# EXPLANATION-ONLY SYSTEM PROMPT (NO DECISION AUTHORITY)
# ============================================================================

EXPLANATION_SYSTEM_PROMPT = """# MIRA Explanation Generator Contract

You are a TECHNICAL WRITER, not a decision maker.

## YOUR ROLE

You receive:
1. A DECISION that has ALREADY BEEN MADE by deterministic rules
2. EVIDENCE that supports that decision
3. A USER QUESTION for context

Your job is to EXPLAIN the decision in clear, professional language.
You do NOT have authority to change, override, or second-guess the decision.

## WHAT YOU MUST DO

1. Accept the decision exactly as provided (YES, NO, CONDITIONAL, REQUIRES_TESTING)
2. Explain WHY this decision was made, citing the evidence provided
3. Quote specific limits, standards, and precedents from the evidence
4. Describe any caveats or conditions mentioned in the evidence
5. Summarize in professional aerospace engineering language

## WHAT YOU MUST NOT DO

- DO NOT override the decision
- DO NOT suggest the decision might be wrong
- DO NOT add qualifications that change the decision
- DO NOT invent MUA numbers, pressure limits, or standards
- DO NOT convert units - quote exactly as provided
- DO NOT extrapolate from one environment to another

## OUTPUT FORMAT

Your explanation should be 2-4 paragraphs covering:
1. The decision and its primary basis
2. The specific evidence supporting the decision (cite MUA numbers, standards)
3. Any conditions, limitations, or mitigations from the evidence
4. A clear summary statement

Write in professional technical style suitable for NASA engineering review.
"""


# ============================================================================
# EVIDENCE BUNDLE FORMATTER
# ============================================================================

@dataclass
class EvidenceBundle:
    """
    Formatted evidence bundle for LLM explanation.

    Pre-formatted with:
    - Rounded numeric values
    - Explicit unit fields
    - Unit status flags
    - Environment compatibility flags
    """
    material_id: str
    material_name: str

    # Requirements from query
    required_env: Optional[str] = None
    required_pressure_psia: Optional[float] = None
    required_temp_c: Optional[float] = None

    # Test data (pre-formatted)
    tested_env: Optional[str] = None
    tested_pressure_psia: Optional[float] = None
    tested_temp_c: Optional[float] = None

    # Unit status
    unit_status: Dict[str, str] = field(default_factory=lambda: {"temperature": "ok", "pressure": "ok"})

    # Flags
    env_mismatch: bool = False
    unit_ambiguous: bool = False

    # Supporting evidence
    bok_requirements: List[Dict[str, Any]] = field(default_factory=list)
    mua_precedents: List[Dict[str, Any]] = field(default_factory=list)

    # Boundary check results (from deterministic checker)
    boundary_results: List[BoundaryCheckResult] = field(default_factory=list)

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
            lines.append(f"  Max Temperature: {self.required_temp_c:.1f} C")
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
            lines.append(f"  Tested Temperature: {self.tested_temp_c:.1f} C")
        else:
            lines.append(f"  Tested Temperature: MISSING")
        lines.append("")

        # Unit status warnings
        lines.append("UNIT STATUS:")
        for field_name, status in self.unit_status.items():
            if status != "ok":
                lines.append(f"  WARNING {field_name}: {status.upper()}")
            else:
                lines.append(f"  OK {field_name}: {status}")
        lines.append("")

        # Environment mismatch warning
        if self.env_mismatch:
            lines.append("WARNING: ENVIRONMENT MISMATCH DETECTED")
            lines.append(f"    Tested in: {self.tested_env}")
            lines.append(f"    Required for: {self.required_env}")
            lines.append("")

        # Boundary check results (deterministic)
        if self.boundary_results:
            lines.append("BOUNDARY CHECK RESULTS (DETERMINISTIC):")
            for result in self.boundary_results:
                lines.append(f"  Verdict: {result.verdict.value}")
                lines.append(f"  Rationale: {result.rationale}")
                if result.limit_checked:
                    limit = result.limit_checked
                    lines.append(f"  Limit: {limit.limit_value} {limit.units} ({limit.source_doc})")
                if result.margin is not None:
                    lines.append(f"  Margin: {result.margin:.1f}")
            lines.append("")

        # BOK requirements
        if self.bok_requirements:
            lines.append("BOK REQUIREMENTS:")
            for req in self.bok_requirements[:5]:  # Top 5
                spec_id = req.get('spec_id', 'UNKNOWN')
                section = req.get('section_number', '')
                summary = req.get('description', req.get('summary', ''))[:150]
                lines.append(f"  - {spec_id} S{section}: {summary}")
            lines.append("")

        # MUA precedents
        if self.mua_precedents:
            lines.append("MUA PRECEDENTS:")
            for mua in self.mua_precedents[:3]:  # Top 3
                mua_num = mua.get('mua_number', 'UNKNOWN')
                env = mua.get('inferred_environment', mua.get('env_class', 'unknown'))
                pressure = mua.get('pressure_psi_max', 'N/A')
                determination = mua.get('determination', 'unknown')
                lines.append(f"  - {mua_num}: {env} environment")
                lines.append(f"    Pressure: {pressure} psi, Status: {determination}")
                if mua.get('rationale_summary'):
                    lines.append(f"    Summary: {mua['rationale_summary'][:100]}")
            lines.append("")

        return "\n".join(lines)


@dataclass
class MaterialDecision:
    """
    Deterministic material decision from MaterialDecider or BoundaryChecker.

    This decision is FINAL - LLM only explains it.
    """
    material_name: str
    decision: str  # YES, NO, CONDITIONAL, REQUIRES_TESTING, NEEDS_REVIEW
    rationale: str
    evidence_sources: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    confidence: float = 0.0
    boundary_result: Optional[BoundaryCheckResult] = None


class LLMAnswerGenerator:
    """
    Generates natural language EXPLANATIONS of decisions.

    IMPORTANT: This class does NOT make decisions.
    All decisions come from MaterialDecider and BoundaryChecker.
    """

    # Regex to extract numeric limits with units from evidence
    NUMERIC_LIMIT_PATTERN = re.compile(
        r"""
        (?P<value>-?\d+(?:\.\d+)?)        # number (with optional negative and decimal)
        \s*
        (?P<unit>
            psia|psi|bar|torr|mmHg|kPa|MPa|Pa|
            C|F|K|
            percent|%|
            atm|atmospheres?|
            psig
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "llama3.1:8b-instruct-q4_K_M",
        provider: str = "ollama"
    ):
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
            try:
                from .haiku_client import HaikuClient
                self.haiku_client = HaikuClient()
                logger.info("Using Claude Haiku for explanations")
            except ImportError:
                logger.warning("Haiku client not available, falling back to Ollama")
                self.provider = "ollama"
                self.haiku_client = None
        else:
            self.haiku_client = None
            logger.info(f"Using local model: {self.model} at {self.base_url}")

    def _is_numeric_value_sane(self, value: float, unit: str) -> bool:
        """Sanity check numeric values to filter out obviously invalid data."""
        unit_lower = unit.lower()

        # Temperature checks
        if any(temp_unit in unit_lower for temp_unit in ['c', 'f', 'k']):
            if 'f' in unit_lower:
                value_c = (value - 32) * 5/9
            elif 'k' in unit_lower:
                value_c = value - 273.15
            else:
                value_c = value

            if abs(value_c) > 2000:
                return False

        # Pressure checks
        if any(press_unit in unit_lower for press_unit in ['psi', 'bar', 'pa', 'kpa', 'mpa', 'torr', 'mmhg', 'atm']):
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

            if value_psi > 50000:
                return False

        # Floating-point garbage check
        if abs(value) > 1e6:
            return False

        return True

    def _extract_numeric_limits(self, evidence_texts: List[str]) -> List[str]:
        """Extract literal numeric + unit snippets from evidence."""
        snippets: List[str] = []
        seen: Set[str] = set()

        for text in evidence_texts:
            for match in self.NUMERIC_LIMIT_PATTERN.finditer(text):
                snippet = match.group(0).strip()
                value_str = match.group('value')
                unit = match.group('unit')

                try:
                    value = float(value_str)
                    if not self._is_numeric_value_sane(value, unit):
                        continue
                    if snippet not in seen:
                        seen.add(snippet)
                        snippets.append(snippet)
                except ValueError:
                    continue

        return snippets

    def _validate_mua_references(self, answer: str, allowed_mua_ids: Set[str]) -> list[str]:
        """Validate that LLM answer only references MUAs from the evidence."""
        referenced_muas = set(MUA_REFERENCE_PATTERN.findall(answer))

        invalid_muas = []
        for mua_ref in referenced_muas:
            if not any(mua_ref.lower() == allowed.lower() for allowed in allowed_mua_ids):
                invalid_muas.append(mua_ref)

        if invalid_muas:
            logger.warning("Answer contains hallucinated MUA IDs: %s", invalid_muas)

        return invalid_muas

    def _detect_decision_language(self, answer: str) -> list[ValidationIssue]:
        """Detect patterns indicating LLM is trying to make decisions."""
        issues = []
        for pattern in DECISION_LANGUAGE_PATTERNS:
            match = pattern.search(answer)
            if match:
                issues.append(
                    ValidationIssue(
                        category="decision_language",
                        message=f"LLM attempting to make decision: '{match.group()}'",
                        severity=ValidationSeverity.WARNING,
                        matched_text=match.group(),
                    )
                )
        return issues

    def _detect_contradiction(self, answer: str, original_decision: str) -> list[ValidationIssue]:
        """Detect patterns indicating LLM is contradicting the decision."""
        issues = []
        for pattern_name, pattern in CONTRADICTION_PATTERNS:
            match = pattern.search(answer)
            if match:
                issues.append(
                    ValidationIssue(
                        category="contradiction",
                        message=f"LLM contradicting decision ({pattern_name}): '{match.group()}'",
                        severity=ValidationSeverity.ERROR,
                        matched_text=match.group(),
                    )
                )
        return issues

    def _validate_bok_references(self, answer: str, evidence: "EvidenceBundle") -> list[str]:
        """Validate that BOK references in answer exist in evidence."""
        referenced_standards = set(
            m.group(1) for m in BOK_REFERENCE_PATTERN.finditer(answer)
        )

        allowed_standards = set()
        for req in evidence.bok_requirements:
            spec_id = req.get("spec_id", "")
            if spec_id:
                allowed_standards.add(spec_id.upper())

        invalid_standards = []
        for std_ref in referenced_standards:
            std_upper = std_ref.upper()
            if not any(std_upper in allowed.upper() for allowed in allowed_standards):
                invalid_standards.append(std_ref)

        if invalid_standards:
            logger.warning("Answer contains potentially hallucinated standards: %s", invalid_standards)

        return invalid_standards

    def _validate_numeric_values(self, answer: str, allowed_limits: list[str]) -> list[str]:
        """Validate numeric values in answer against allowed limits."""
        answer_values = set()
        for match in self.NUMERIC_LIMIT_PATTERN.finditer(answer):
            value_str = match.group("value")
            unit = match.group("unit")
            answer_values.add(f"{value_str} {unit}".lower())

        invalid_values = []
        for val in answer_values:
            val_normalized = val.replace(" ", "")
            is_allowed = any(
                val_normalized in allowed.replace(" ", "").lower()
                or allowed.replace(" ", "").lower() in val_normalized
                for allowed in allowed_limits
            )
            if not is_allowed:
                invalid_values.append(val)

        if invalid_values:
            logger.debug("Potentially hallucinated values: %s", invalid_values)

        return invalid_values

    def validate_answer(
        self,
        answer: str,
        decision: "MaterialDecision",
        evidence: "EvidenceBundle",
        allowed_limits: list[str],
    ) -> ValidationResult:
        """Perform comprehensive validation of LLM-generated answer."""
        issues: list[ValidationIssue] = []

        decision_issues = self._detect_decision_language(answer)
        issues.extend(decision_issues)

        contradiction_issues = self._detect_contradiction(answer, decision.decision)
        issues.extend(contradiction_issues)

        allowed_mua_ids = {
            str(mua.get("mua_number", ""))
            for mua in evidence.mua_precedents
            if mua.get("mua_number")
        }
        hallucinated_muas = self._validate_mua_references(answer, allowed_mua_ids)
        hallucinated_standards = self._validate_bok_references(answer, evidence)
        hallucinated_values = self._validate_numeric_values(answer, allowed_limits)

        is_valid = (
            not any(i.severity == ValidationSeverity.ERROR for i in issues)
            and not hallucinated_muas
        )

        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            hallucinated_muas=hallucinated_muas,
            hallucinated_standards=hallucinated_standards,
            hallucinated_values=hallucinated_values,
            decision_language_found=len(decision_issues) > 0,
            contradiction_found=len(contradiction_issues) > 0,
        )

    def _sanitize_answer(
        self, answer: str, validation: ValidationResult, decision: "MaterialDecision"
    ) -> str:
        """Sanitize LLM answer by adding warnings for detected issues."""
        warnings = []

        if validation.hallucinated_muas:
            warnings.append(f"WARNING: References to unverified MUA(s): {validation.hallucinated_muas}")

        if validation.contradiction_found:
            warnings.append(
                f"WARNING: The predetermined decision is {decision.decision}. "
                "Some language in this explanation may appear contradictory."
            )

        if validation.decision_language_found:
            warnings.append("NOTE: This is an EXPLANATION of a predetermined decision, not a recommendation.")

        if warnings:
            prefix = "\n".join(warnings) + "\n\n---\n\n"
            return prefix + answer

        return answer

    def explain_decision(self, decision: MaterialDecision, evidence: EvidenceBundle, query: str) -> str:
        """Generate natural language explanation of a PREDETERMINED decision."""
        evidence_texts: List[str] = []
        for mua in evidence.mua_precedents:
            if mua.get('rationale'):
                evidence_texts.append(str(mua['rationale']))
            if mua.get('rationale_summary'):
                evidence_texts.append(str(mua['rationale_summary']))

        for req in evidence.bok_requirements:
            if req.get('content'):
                evidence_texts.append(str(req['content']))
            if req.get('summary'):
                evidence_texts.append(str(req['summary']))

        numeric_limits = self._extract_numeric_limits(evidence_texts)

        full_prompt = f"""{EXPLANATION_SYSTEM_PROMPT}

## THE DECISION (ALREADY MADE - DO NOT CHANGE)

DECISION: {decision.decision}
MATERIAL: {decision.material_name}
RATIONALE: {decision.rationale}
CONFIDENCE: {decision.confidence:.2f}

EVIDENCE SOURCES:
{chr(10).join('- ' + src for src in decision.evidence_sources) or '- None specified'}

CAVEATS:
{chr(10).join('- ' + caveat for caveat in decision.caveats) or '- None'}

## USER QUESTION (for context)

{query}

## SUPPORTING EVIDENCE

{evidence.to_llm_prompt()}

## ALLOWED NUMERIC LIMITS (quote exactly)

{chr(10).join('- ' + lim for lim in numeric_limits) or '- (None found in evidence)'}

## TASK

Write a clear, professional explanation of WHY this decision was made.
Cite specific evidence. Do NOT change the decision.

EXPLANATION:
"""

        allowed_mua_ids = set()
        for mua in evidence.mua_precedents:
            if mua.get('mua_number'):
                allowed_mua_ids.add(str(mua['mua_number']))

        try:
            if self.provider == "haiku" and self.haiku_client:
                message = self.haiku_client.client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1500,
                    temperature=0.0,
                    messages=[{"role": "user", "content": full_prompt}]
                )
                llm_answer = message.content[0].text.strip()
            else:
                response = requests.post(
                    self.endpoint,
                    json={
                        "model": self.model,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {"temperature": 0.0, "num_predict": 1500, "repeat_penalty": 1.1, "top_p": 0.9}
                    },
                    timeout=120
                )
                response.raise_for_status()
                result = response.json()
                llm_answer = result.get('response', 'Error: No response from LLM')

            validation = self.validate_answer(llm_answer, decision, evidence, numeric_limits)

            if validation.has_warnings() or validation.has_errors():
                logger.warning("Validation issues: %s", validation.summary())
                llm_answer = self._sanitize_answer(llm_answer, validation, decision)

            return llm_answer

        except requests.exceptions.ConnectionError:
            return f"DECISION: {decision.decision}\n\nUnable to generate detailed explanation (LLM unavailable). Rationale: {decision.rationale}"
        except Exception as e:
            logger.error(f"LLM explanation error: {e}")
            return f"DECISION: {decision.decision}\n\nExplanation generation failed: {str(e)}\n\nRationale: {decision.rationale}"

    def generate_answer(
        self, query: str, mua_precedents: List[Dict], semantic_evidence: Optional[Dict],
        decisions: List[Dict], requirements: List[Dict]
    ) -> str:
        """DEPRECATED: Legacy method for backward compatibility."""
        logger.warning("generate_answer() is deprecated. Use explain_decision() instead.")

        if not decisions:
            return "Unable to generate answer: No material decision provided."

        top_decision_dict = decisions[0]
        decision = MaterialDecision(
            material_name=top_decision_dict.get('material_name', 'Unknown'),
            decision=top_decision_dict.get('decision', 'NEEDS_REVIEW'),
            rationale=top_decision_dict.get('rationale', 'No rationale provided'),
            evidence_sources=top_decision_dict.get('evidence_sources', []),
            caveats=top_decision_dict.get('caveats', []),
            confidence=top_decision_dict.get('confidence', 0.0)
        )

        evidence = EvidenceBundle(
            material_id=top_decision_dict.get('material_id', 'unknown'),
            material_name=decision.material_name,
            mua_precedents=mua_precedents or [],
            bok_requirements=requirements or []
        )

        if semantic_evidence:
            bok_high = semantic_evidence.get('bok_standards', {}).get('high', [])
            for result in bok_high[:5]:
                if hasattr(result, 'content') and result.content:
                    content = result.content.get('text', result.content.get('content', ''))
                    if content:
                        evidence.bok_requirements.append({'content': content})
                elif isinstance(result, dict) and result.get('content'):
                    evidence.bok_requirements.append(result)

        return self.explain_decision(decision, evidence, query)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def explain_material_decision(
    decision: MaterialDecision, evidence: EvidenceBundle, query: str, provider: str = "ollama"
) -> str:
    """Convenience function to generate explanation."""
    generator = LLMAnswerGenerator(provider=provider)
    return generator.explain_decision(decision, evidence, query)
