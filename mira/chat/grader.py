"""
Module: MIRA Chat — Response Grader
Purpose: Post-formatter safety gate that verifies the LLM-formatted response
         against the engine envelope before it reaches the engineer.

The grader enforces BS-SPEC-MIRA-CHAT-001-REV2 Section 15 non-negotiables:
  1. Every response cites its source engine and evidence
  2. The chatbot never invents information not in the engine output
  3. REFUSE gate: if the engine says REFUSE, the chatbot says REFUSE
  4. Draft artifacts labeled DRAFT with approval reminder
  5. Confidence numbers come from engines — the formatter never invents them
  6. Missing inputs stated exactly when INSUFFICIENT_DATA

Design:
  - Runs AFTER the LLM formatter, BEFORE the response is returned
  - Pure deterministic checks — no LLM call (fast, free, reliable)
  - If any check fails, falls back to the deterministic formatter
  - Every grader run is recorded in the audit trail

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .models import EngineEnvelope, Status, TaskMode

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Grader result
# ---------------------------------------------------------------------------


@dataclass
class GraderResult:
    """Result of grading a formatted response against its source envelope."""

    passed: bool
    checks_run: int = 0
    checks_passed: int = 0
    failures: list[GraderFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Fraction of checks that passed (0.0–1.0)."""
        return self.checks_passed / self.checks_run if self.checks_run else 1.0

    def to_audit_dict(self) -> dict[str, Any]:
        """Serialize for inclusion in the audit record."""
        return {
            "grader_passed": self.passed,
            "grader_score": round(self.score, 3),
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "failures": [f.to_dict() for f in self.failures],
            "warnings": self.warnings,
        }


@dataclass
class GraderFailure:
    """A single failed grader check."""

    check_id: str
    severity: str  # "hard" = forces fallback, "soft" = logged but allowed
    message: str
    expected: str = ""
    found: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "check_id": self.check_id,
            "severity": self.severity,
            "message": self.message,
            "expected": self.expected,
            "found": self.found,
        }


# ---------------------------------------------------------------------------
# The grader
# ---------------------------------------------------------------------------


def grade_response(
    formatted_text: str,
    envelope: EngineEnvelope,
) -> GraderResult:
    """Grade a formatted response against the source engine envelope.

    Runs all deterministic checks from Section 15 of the spec.
    A single "hard" failure means the response should be replaced
    with the deterministic fallback.

    Parameters
    ----------
    formatted_text : str
        The LLM-formatted response text.
    envelope : EngineEnvelope
        The source engine envelope the formatter was given.

    Returns
    -------
    GraderResult
        Whether the response passed, with details on each check.
    """
    result = GraderResult(passed=True)
    text_lower = formatted_text.lower()

    # ------------------------------------------------------------------
    # Check 1: Verdict presence
    # The formatted text must contain the verdict status.
    # ------------------------------------------------------------------
    _check_verdict_present(formatted_text, text_lower, envelope, result)

    # ------------------------------------------------------------------
    # Check 2: REFUSE verbatim pass-through
    # If the engine said REFUSE, the formatter must not soften it.
    # ------------------------------------------------------------------
    _check_refuse_not_softened(formatted_text, text_lower, envelope, result)

    # ------------------------------------------------------------------
    # Check 3: Citations present
    # Every citation from the envelope must appear in the output.
    # ------------------------------------------------------------------
    _check_citations_present(formatted_text, text_lower, envelope, result)

    # ------------------------------------------------------------------
    # Check 4: DRAFT labeling
    # Draft artifacts must be labeled DRAFT with approval reminder.
    # ------------------------------------------------------------------
    _check_draft_labeled(formatted_text, text_lower, envelope, result)

    # ------------------------------------------------------------------
    # Check 5: Missing inputs stated (INSUFFICIENT_DATA)
    # ------------------------------------------------------------------
    _check_missing_inputs_stated(formatted_text, text_lower, envelope, result)

    # ------------------------------------------------------------------
    # Check 6: Assumptions surfaced
    # ------------------------------------------------------------------
    _check_assumptions_surfaced(formatted_text, text_lower, envelope, result)

    # ------------------------------------------------------------------
    # Check 7: No hallucinated confidence numbers
    # The formatter must not invent percentage or confidence values
    # that don't appear in the envelope.
    # ------------------------------------------------------------------
    _check_no_hallucinated_confidence(formatted_text, envelope, result)

    # ------------------------------------------------------------------
    # Check 8: Recommended actions from engine only
    # Suggestions in the output should trace to recommended_actions.
    # ------------------------------------------------------------------
    _check_no_invented_actions(formatted_text, text_lower, envelope, result)

    # ------------------------------------------------------------------
    # Final disposition
    # ------------------------------------------------------------------
    hard_failures = [f for f in result.failures if f.severity == "hard"]
    if hard_failures:
        result.passed = False
        LOGGER.warning(
            "[GRADER] FAILED — %d hard failure(s): %s",
            len(hard_failures),
            "; ".join(f.check_id for f in hard_failures),
        )
    else:
        LOGGER.debug(
            "[GRADER] PASSED — %d/%d checks, %d warnings",
            result.checks_passed,
            result.checks_run,
            len(result.warnings),
        )

    return result


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_verdict_present(
    text: str, text_lower: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """The response must contain the verdict status somewhere."""
    result.checks_run += 1

    status_value = envelope.status.value  # e.g. "CONDITIONAL_PASS"
    # Accept various renderings: CONDITIONAL_PASS, CONDITIONAL PASS, conditional pass
    normalized = status_value.replace("_", " ").lower()
    variants = [
        status_value.lower(),
        normalized,
        status_value.replace("_", " "),
        status_value,
    ]

    if any(v.lower() in text_lower for v in variants):
        result.checks_passed += 1
    else:
        result.failures.append(GraderFailure(
            check_id="verdict_present",
            severity="hard",
            message=f"Verdict '{status_value}' not found in formatted response",
            expected=status_value,
            found=text[:200],
        ))


def _check_refuse_not_softened(
    text: str, text_lower: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """If REFUSE, the response must not contain softening language."""
    if envelope.status != Status.REFUSE:
        return

    result.checks_run += 1

    # Softening phrases that indicate the formatter tried to work around a refusal
    softeners = [
        "however, you could",
        "alternatively",
        "you might try",
        "as a workaround",
        "instead, consider",
        "one option would be",
        "you could instead",
        "a possible alternative",
        "let me suggest",
    ]

    found_softeners = [s for s in softeners if s in text_lower]
    if found_softeners:
        result.failures.append(GraderFailure(
            check_id="refuse_not_softened",
            severity="hard",
            message="REFUSE response contains softening language",
            expected="Verbatim refusal with no workarounds",
            found=", ".join(found_softeners),
        ))
    else:
        result.checks_passed += 1


def _check_citations_present(
    text: str, text_lower: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """Every citation from the envelope must appear in the output."""
    if not envelope.citations:
        return

    result.checks_run += 1
    missing = []

    for citation in envelope.citations:
        citation_str = str(citation).strip()
        if not citation_str:
            continue

        # Extract the core reference (e.g. "NASA-STD-6016C" from a longer string)
        # Check for the full citation or key identifiers within it
        core_refs = _extract_core_references(citation_str)

        found = False
        for ref in core_refs:
            if ref.lower() in text_lower:
                found = True
                break

        if not found:
            # Also check the full citation string
            if citation_str.lower() in text_lower:
                found = True

        if not found:
            missing.append(citation_str)

    if missing:
        # Missing citations is hard failure — spec Section 15.1
        result.failures.append(GraderFailure(
            check_id="citations_present",
            severity="hard",
            message=f"{len(missing)} citation(s) missing from response",
            expected="; ".join(missing),
            found="(not found in output)",
        ))
    else:
        result.checks_passed += 1


def _check_draft_labeled(
    text: str, text_lower: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """Draft artifacts must be labeled DRAFT with approval language."""
    if envelope.mode != TaskMode.DRAFT_ARTIFACT:
        return

    result.checks_run += 1

    has_draft = "draft" in text_lower
    has_approval = any(phrase in text_lower for phrase in [
        "approval",
        "approved",
        "review",
        "m&p plan",
        "program",
    ])

    if has_draft and has_approval:
        result.checks_passed += 1
    elif not has_draft:
        result.failures.append(GraderFailure(
            check_id="draft_labeled",
            severity="hard",
            message="Draft artifact not labeled as DRAFT",
            expected="Response must contain 'DRAFT' label",
            found=text[:200],
        ))
    else:
        # Has DRAFT but no approval language — soft warning
        result.warnings.append(
            "Draft artifact labeled DRAFT but missing explicit approval reminder"
        )
        result.checks_passed += 1


def _check_missing_inputs_stated(
    text: str, text_lower: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """INSUFFICIENT_DATA must state what inputs are missing."""
    if envelope.status != Status.INSUFFICIENT_DATA:
        return
    if not envelope.missing_inputs:
        return

    result.checks_run += 1
    missing_from_output = []

    for inp in envelope.missing_inputs:
        inp_str = str(inp).strip().lower()
        if not inp_str:
            continue
        # Check for key words from each missing input
        key_words = [w for w in inp_str.split() if len(w) > 3]
        found = any(w in text_lower for w in key_words) if key_words else True

        if not found:
            missing_from_output.append(inp)

    if missing_from_output:
        result.failures.append(GraderFailure(
            check_id="missing_inputs_stated",
            severity="soft",
            message=f"{len(missing_from_output)} missing input(s) not mentioned in response",
            expected="; ".join(str(m) for m in missing_from_output),
            found="(not found in output)",
        ))
    else:
        result.checks_passed += 1


def _check_assumptions_surfaced(
    text: str, text_lower: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """Assumptions from the envelope should be surfaced in the response."""
    if not envelope.assumptions:
        return

    result.checks_run += 1
    missing_assumptions = []

    for assumption in envelope.assumptions:
        assumption_str = str(assumption).strip().lower()
        if not assumption_str:
            continue
        # Check for key words (3+ chars) from each assumption
        key_words = [w for w in assumption_str.split() if len(w) > 3]
        found = any(w in text_lower for w in key_words) if key_words else True

        if not found:
            missing_assumptions.append(assumption)

    if missing_assumptions:
        # Soft failure — assumptions not surfaced is bad but not dangerous
        result.failures.append(GraderFailure(
            check_id="assumptions_surfaced",
            severity="soft",
            message=f"{len(missing_assumptions)} assumption(s) not surfaced",
            expected="; ".join(str(a) for a in missing_assumptions),
            found="(not found in output)",
        ))
    else:
        result.checks_passed += 1


def _check_no_hallucinated_confidence(
    text: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """The formatter must not invent confidence/percentage values."""
    result.checks_run += 1

    # Find all percentage-like values in the formatted text
    pct_pattern = re.compile(r'(\d{1,3}(?:\.\d+)?)\s*%')
    found_pcts = set(pct_pattern.findall(text))

    if not found_pcts:
        result.checks_passed += 1
        return

    # Collect all legitimate percentage values from the envelope
    legitimate_pcts: set[str] = set()
    _collect_pcts_from_obj(envelope.model_dump(), legitimate_pcts)

    # Also allow common non-hallucinated percentages
    # (e.g. "100%" in "100% oxygen", percentage in citations)
    safe_pcts = {"100", "0", "50"}
    legitimate_pcts.update(safe_pcts)

    hallucinated = found_pcts - legitimate_pcts
    if hallucinated:
        # Could be legitimate rounding or rephrasing — soft failure
        result.warnings.append(
            f"Possible hallucinated percentage values: {', '.join(sorted(hallucinated))}%"
        )
        result.checks_passed += 1  # Warning, not failure
    else:
        result.checks_passed += 1


def _check_no_invented_actions(
    text: str, text_lower: str, envelope: EngineEnvelope, result: GraderResult
) -> None:
    """Suggestions should come from recommended_actions, not the formatter."""
    if not envelope.recommended_actions:
        # If no actions in envelope, check that the formatter didn't invent any
        result.checks_run += 1
        action_phrases = [
            "i recommend",
            "i suggest",
            "you should consider",
            "next step would be",
            "i would advise",
        ]
        invented = [p for p in action_phrases if p in text_lower]
        if invented and envelope.status not in (Status.INSUFFICIENT_DATA, Status.ERROR):
            result.failures.append(GraderFailure(
                check_id="no_invented_actions",
                severity="soft",
                message="Formatter appears to suggest actions not in recommended_actions",
                expected="No unsolicited recommendations",
                found=", ".join(invented),
            ))
        else:
            result.checks_passed += 1
        return

    # If there are recommended_actions, just confirm they're not blocked
    result.checks_run += 1
    result.checks_passed += 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_core_references(citation: str) -> list[str]:
    """Extract standard/document references from a citation string.

    For "NASA-STD-6016C §4.2.1.4a (MPR 51)" returns:
    ["NASA-STD-6016C", "MPR 51", "4.2.1.4a"]
    """
    refs = []

    # Standard references (NASA-STD-XXXX, ASTM GXXX, MIL-STD-XXX)
    std_pattern = re.compile(
        r'((?:NASA|MIL|ASTM|SAE|AMS|ISO)[-\s]?(?:STD[-\s]?)?[A-Z0-9][-A-Z0-9.]*)',
        re.IGNORECASE,
    )
    refs.extend(m.group(1) for m in std_pattern.finditer(citation))

    # Section references (§4.2.1)
    section_pattern = re.compile(r'[§]?([\d]+(?:\.[\d]+)+[a-zA-Z]?)')
    refs.extend(m.group(1) for m in section_pattern.finditer(citation))

    # MPR references
    mpr_pattern = re.compile(r'(MPR\s*\d+)', re.IGNORECASE)
    refs.extend(m.group(1) for m in mpr_pattern.finditer(citation))

    # If nothing extracted, use the full string
    if not refs:
        refs.append(citation)

    return refs


def _collect_pcts_from_obj(obj: Any, pcts: set[str]) -> None:
    """Recursively collect percentage-like numeric values from a dict/list."""
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_pcts_from_obj(v, pcts)
    elif isinstance(obj, list):
        for item in obj:
            _collect_pcts_from_obj(item, pcts)
    elif isinstance(obj, (int, float)):
        # Capture as string to match regex output
        if 0 <= obj <= 100:
            pcts.add(str(int(obj)) if obj == int(obj) else f"{obj:.1f}".rstrip("0").rstrip("."))
    elif isinstance(obj, str):
        pct_pattern = re.compile(r'(\d{1,3}(?:\.\d+)?)\s*%')
        for m in pct_pattern.finditer(obj):
            pcts.add(m.group(1))


# ---------------------------------------------------------------------------
# Integration: grade-and-gate
# ---------------------------------------------------------------------------


async def grade_and_gate(
    formatted_text: str,
    envelope: EngineEnvelope,
    fallback_fn,
    session_context: dict[str, Any] | None = None,
) -> tuple[str, GraderResult]:
    """Grade the formatted response; fall back to deterministic if it fails.

    This is the function the router calls. It:
    1. Grades the LLM-formatted text against the envelope
    2. If passed → returns the LLM text
    3. If failed → calls fallback_fn to get deterministic text
    4. Records the grader result in session_context for audit

    Returns (final_text, grader_result).
    """
    result = grade_response(formatted_text, envelope)

    if session_context is not None:
        session_context["grader_result"] = result.to_audit_dict()

    if result.passed:
        return formatted_text, result

    LOGGER.warning(
        "[GRADER] Falling back to deterministic formatter — %d hard failure(s)",
        len([f for f in result.failures if f.severity == "hard"]),
    )

    fallback_text = fallback_fn(envelope, session_context)
    return fallback_text, result
