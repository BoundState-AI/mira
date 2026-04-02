"""
Module: MIRA Chat — Response Formatter
Purpose: Claude-powered formatting of engine results for aerospace engineers
         per BS-SPEC-MIRA-CHAT-001-REV2.

The formatter takes a normalised EngineEnvelope and produces a human-readable
response using a pinned Claude model.  The system prompt embodies a senior
M&P engineer with 40+ years of experience — patient, thorough, and
conversational.  This is NOT a data dump; it's how a seasoned colleague
would walk you through the result.

If the LLM call fails for any reason, a deterministic plain-text fallback
is returned so the user always gets an answer.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from mira.providers.llm_provider import complete as llm_complete, resolve_model

from .capability_registry import get_engine
from .models import EngineEnvelope, Status, TaskMode

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_FORMATTER_MODEL = resolve_model("sonnet")
DEFAULT_FORMATTER_PROVIDER = "bedrock-converse"
FORMATTER_MAX_TOKENS = 1500
FORMATTER_TEMPERATURE = 0.3  # Enough for natural M&P engineer voice, not enough to drift
FORMATTER_TIMEOUT_S = 45

# ---------------------------------------------------------------------------
# System prompt: Senior M&P Engineer persona
# ---------------------------------------------------------------------------
#
# The spec says the formatter "formats only — never decides."  That's still
# true: it never changes a verdict, invents evidence, or overrides a REFUSE.
# But formatting means more than templating data — it means communicating
# like a senior M&P engineer would.  A good M&P engineer:
#   - Leads with the verdict, then explains why
#   - Connects the dots between the evidence and the conclusion
#   - Anticipates the engineer's next question
#   - Speaks plainly but uses correct technical terminology
#   - Never hedges on a REFUSE — the standard said no, that's the answer
#   - Is patient: if data is missing, explains exactly what's needed and why
#   - Remembers this is a conversation, not a report

_DEFAULT_EXPERT_PROFILE = {
    "display_name": "MIRA Engineering Chat",
    "role": "a senior Materials & Processes engineer",
    "specialty": (
        "Broad aerospace M&P triage across compatibility, evidence review, "
        "and standards-driven follow-up."
    ),
    "workflow_focus": (
        "Help the engineer understand the next grounded step in this workflow, "
        "not just the verdict."
    ),
    "voice": [
        "Lead with the verdict in plain language, then connect the evidence to it.",
        "Teach like a specialist mentor, but stay concise and practical.",
        "Use the domain vocabulary the engine would use, not generic safety wording.",
        "If the result is conditional or weakly supported, say what would change the answer next.",
    ],
}


FORMATTER_SYSTEM_PROMPT = """\
You are {expert_role}, the specialist behind MIRA's {engine_display_name}.

SPECIALTY:
- {expert_specialty}
- {expert_workflow_focus}

SPECIALIST STYLE FOR THIS ENGINE:
{expert_voice}

You are helping a colleague through a MIRA assessment. You are patient, \
thorough, and precise. You explain your reasoning. When a result is \
conditional or fails, you explain what it means practically — not just \
technically. You guide the engineer toward the next step.

You ONLY use information from the engine result. You never guess. But you \
explain what the engine found in a way that builds the engineer's \
understanding, not just their compliance paperwork.

Think: the best domain mentor you ever had, except they have instant access \
to every NASA standard, test result, and internal workflow note relevant to \
this engine.

GENERAL VOICE:
- Lead with the verdict in plain language: "316L gets a conditional pass here."
- Then explain the WHY — connect the evidence to the conclusion
- Use precise engineering terminology (CONDITIONAL_PASS, not "maybe okay")
- Anticipate the engineer's next question and address it proactively
- Be conversational but never chatty — engineers don't want essays
- If this is a follow-up turn, acknowledge continuity ("Looking at the same material again at the new pressure...")

RULES (non-negotiable):
- Include ALL citations from the engine output — do not omit any
- Do NOT add information not present in the engine result
- Do NOT soften, hedge, or change the verdict — if the engine said FAIL, you say FAIL and explain what it means practically
- When something is a REFUSE or INSUFFICIENT_DATA, you're direct but not dismissive — tell them exactly what's needed and why
- Suggest follow-up actions ONLY from the engine's recommended_actions list
- If recommended_actions includes a Category III note, call it out clearly
- If the result is a draft artifact, clearly label it as a draft requiring review and approval
- Never invent a confidence number — only report what the engine provided
- When the engine returns assumptions, surface them clearly so the engineer can confirm or correct them
- If module workflow context is present, answer the current active field first before giving broader workflow guidance
- Treat completed fields as already handled unless the engine result explicitly says they must be revisited
- Use current_step, blockers, and next_steps to orient the engineer toward the next grounded action

Mode: {mode}
Engine: {engine_id}
Turn: {turn_count}"""


def _get_chat_workflow(session_context: dict[str, Any] | None) -> dict[str, Any]:
    """Extract workflow context from the session when module-scoped chat is active."""
    if not session_context:
        return {}
    module_context = session_context.get("module_context")
    if not isinstance(module_context, dict):
        return {}
    workflow = module_context.get("chat_workflow")
    return workflow if isinstance(workflow, dict) else {}


def _stringify_profile_lines(value: Any, fallback: list[str]) -> list[str]:
    """Normalize manifest profile text into a non-empty list of bullet lines."""
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else list(fallback)
    if isinstance(value, list):
        lines = [str(item).strip() for item in value if str(item).strip()]
        return lines or list(fallback)
    return list(fallback)


def get_formatter_profile(engine_id: str) -> dict[str, Any]:
    """Resolve the specialist formatter profile for an engine.

    Profiles live in the engine manifest under ``expert_profile`` so the
    "panel of experts" behavior stays attached to the module declaration rather
    than being scattered across the frontend.
    """
    profile = dict(_DEFAULT_EXPERT_PROFILE)
    engine = get_engine(engine_id or "")
    if isinstance(engine, dict):
        display_name = str(engine.get("display_name") or "").strip()
        if display_name:
            profile["display_name"] = display_name

        expert_profile = engine.get("expert_profile")
        if isinstance(expert_profile, dict):
            for field in ("role", "specialty", "workflow_focus"):
                value = expert_profile.get(field)
                if isinstance(value, str) and value.strip():
                    profile[field] = value.strip()
            profile["voice"] = _stringify_profile_lines(
                expert_profile.get("voice"),
                profile["voice"],
            )

    return profile


def build_formatter_system_prompt(
    envelope: EngineEnvelope,
    session_context: dict[str, Any] | None = None,
) -> str:
    """Build the per-engine formatter system prompt."""
    turn_count = 1
    if session_context:
        turn_count = int(session_context.get("turn_count", 1) or 1)

    profile = get_formatter_profile(envelope.engine_id)
    expert_voice = "\n".join(f"- {line}" for line in profile["voice"])
    return FORMATTER_SYSTEM_PROMPT.format(
        expert_role=profile["role"],
        engine_display_name=profile["display_name"],
        expert_specialty=profile["specialty"],
        expert_workflow_focus=profile["workflow_focus"],
        expert_voice=expert_voice,
        mode=envelope.mode.value,
        engine_id=envelope.engine_id,
        turn_count=turn_count,
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_formatter_prompt(
    envelope: EngineEnvelope,
    session_context: dict[str, Any] | None = None,
) -> str:
    """Build the user-message payload sent to the formatter LLM.

    Assembles all envelope fields into a structured block that the system
    prompt instructs the model to reformat for engineers.
    """
    sections: list[str] = []

    sections.append(f"STATUS: {envelope.status.value}")
    sections.append(f"ENGINE: {envelope.engine_id} v{envelope.engine_version}")
    sections.append(f"MODE: {envelope.mode.value}")

    # Session continuity hints
    if session_context:
        turn = session_context.get("turn_count", 1)
        if turn > 1:
            sections.append(f"TURN: {turn} (this is a follow-up in an ongoing conversation)")
        accumulated = session_context.get("accumulated_entities", {})
        if accumulated:
            sections.append(f"SESSION CONTEXT: {accumulated}")
        module_context = session_context.get("module_context", {})
        if module_context:
            sections.append(f"MODULE CONTEXT: {module_context}")
        workflow = _get_chat_workflow(session_context)
        if workflow:
            workflow_lines: list[str] = []
            if workflow.get("current_step"):
                workflow_lines.append(f"  - Current step: {workflow['current_step']}")
            if workflow.get("active_field_label"):
                workflow_lines.append(f"  - Active field: {workflow['active_field_label']}")
            elif workflow.get("active_field"):
                workflow_lines.append(f"  - Active field key: {workflow['active_field']}")
            if workflow.get("completed_fields"):
                workflow_lines.append(
                    "  - Completed fields: " + ", ".join(str(field) for field in workflow["completed_fields"])
                )
            if workflow.get("incomplete_fields"):
                workflow_lines.append(
                    "  - Incomplete fields: " + ", ".join(str(field) for field in workflow["incomplete_fields"])
                )
            if workflow.get("blockers"):
                workflow_lines.append(
                    "  - Blockers: " + ", ".join(str(blocker) for blocker in workflow["blockers"])
                )
            if workflow.get("next_steps"):
                workflow_lines.append(
                    "  - Next steps: " + ", ".join(str(step) for step in workflow["next_steps"])
                )
            if workflow_lines:
                sections.append("WORKFLOW CONTEXT:\n" + "\n".join(workflow_lines))

    if envelope.response_text:
        sections.append(f"\n--- Engine Response ---\n{envelope.response_text}")

    if envelope.mua_disposition:
        sections.append(f"MUA DISPOSITION: {envelope.mua_disposition}")

    if envelope.authority_basis:
        sections.append("AUTHORITY BASIS:\n" + "\n".join(f"  - {a}" for a in envelope.authority_basis))

    if envelope.citations:
        sections.append("CITATIONS:\n" + "\n".join(f"  - {c}" for c in envelope.citations))

    if envelope.evidence:
        evidence_lines = []
        for ev in envelope.evidence:
            if isinstance(ev, dict):
                evidence_lines.append(f"  - {ev}")
            else:
                evidence_lines.append(f"  - {ev}")
        sections.append("EVIDENCE:\n" + "\n".join(evidence_lines))

    if envelope.assumptions:
        sections.append("ASSUMPTIONS:\n" + "\n".join(f"  - {a}" for a in envelope.assumptions))

    if envelope.missing_inputs:
        sections.append("MISSING INPUTS:\n" + "\n".join(f"  - {m}" for m in envelope.missing_inputs))

    if envelope.recommended_actions:
        sections.append("RECOMMENDED ACTIONS:\n" + "\n".join(f"  - {r}" for r in envelope.recommended_actions))

    # Confidence values — render only what the spec allows
    dp = envelope.domain_payload
    confidence_lines: list[str] = []

    extraction_conf = dp.get("extraction_confidence")
    if extraction_conf is not None and float(extraction_conf) < 0.9:
        confidence_lines.append(f"  Extraction confidence: {extraction_conf}")

    evidence_comp = dp.get("evidence_completeness")
    if evidence_comp is not None:
        confidence_lines.append(f"  Evidence completeness: {evidence_comp}")

    verdict_conf = dp.get("verdict_confidence")
    if verdict_conf is not None:
        confidence_lines.append(f"  Verdict confidence: {verdict_conf}")

    # routing_confidence is deliberately NOT shown (internal only)

    if confidence_lines:
        sections.append("CONFIDENCE INDICATORS:\n" + "\n".join(confidence_lines))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Follow-up extraction
# ---------------------------------------------------------------------------


def extract_follow_ups(envelope: EngineEnvelope) -> list[dict[str, str]]:
    """Extract clickable follow-up suggestions from recommended_actions.

    Returns a list of dicts with 'label' and 'query' keys suitable for
    rendering as suggestion chips in the frontend.
    """
    follow_ups: list[dict[str, str]] = []
    for action in envelope.recommended_actions:
        if isinstance(action, dict):
            action_text = str(action.get("label") or action.get("action") or "").strip()
            action_query = str(action.get("query") or action.get("action") or action_text).strip()
        else:
            action_text = str(action).strip()
            action_query = action_text
        if not action_text:
            continue
        # Truncate long actions for the chip label
        label = action_text[:80] + ("..." if len(action_text) > 80 else "")
        follow_ups.append(
            {
                "label": label,
                "query": action_query,
            }
        )
    return follow_ups


# ---------------------------------------------------------------------------
# LLM formatter
# ---------------------------------------------------------------------------


async def format_response(
    envelope: EngineEnvelope,
    session_context: dict[str, Any] | None = None,
) -> str:
    """Format an EngineEnvelope into an engineer-friendly response string.

    Calls the Claude formatter model.  If the call fails for any reason
    (missing API key, network error, rate limit, etc.), falls back to a
    deterministic plain-text rendering.
    """
    if session_context is not None:
        session_context["formatter_model_used"] = None

    if envelope.status == Status.REFUSE:
        return envelope.response_text

    try:
        provider = (
            os.environ.get("MIRA_CHAT_LLM_PROVIDER", DEFAULT_FORMATTER_PROVIDER).strip()
            or DEFAULT_FORMATTER_PROVIDER
        )
        model = (
            os.environ.get("MIRA_CHAT_FORMATTER_MODEL")
            or os.environ.get("BEDROCK_MODEL_ID")
            or os.environ.get("LLM_SONNET_MODEL")
            or DEFAULT_FORMATTER_MODEL
        ).strip()
        if session_context is not None:
            session_context["formatter_model_used"] = model

        system = build_formatter_system_prompt(envelope, session_context)
        user_prompt = build_formatter_prompt(envelope, session_context)

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: llm_complete(
                system=system,
                user=user_prompt,
                model=model,
                max_tokens=FORMATTER_MAX_TOKENS,
                temperature=FORMATTER_TEMPERATURE,
                timeout_s=FORMATTER_TIMEOUT_S,
                provider=provider,
            ),
        )
        formatted = response.text.strip()

        if not formatted:
            return _fallback_format(envelope, session_context)

        # Grade the LLM output against the envelope before returning
        from .grader import grade_and_gate
        final_text, grader_result = await grade_and_gate(
            formatted, envelope, _fallback_format, session_context
        )
        return final_text

    except Exception:
        LOGGER.exception("Formatter LLM call failed — falling back to plain-text rendering")
        return _fallback_format(envelope, session_context)


# ---------------------------------------------------------------------------
# Deterministic fallback (no LLM needed)
# ---------------------------------------------------------------------------


def _fallback_format(
    envelope: EngineEnvelope,
    session_context: dict[str, Any] | None = None,
) -> str:
    """Produce a readable plain-text response when the LLM is unavailable.

    Even without the LLM, we still write in the voice of a senior engineer
    rather than a raw data dump.
    """
    status = envelope.status
    if status == Status.REFUSE:
        return envelope.response_text

    lines: list[str] = []
    profile = get_formatter_profile(envelope.engine_id)
    engine_label = f"{profile['display_name']} v{envelope.engine_version}"

    if status == Status.PASS:
        lines.append(f"**PASS** — This checks out. [{engine_label}]")
    elif status == Status.CONDITIONAL_PASS:
        lines.append(f"**CONDITIONAL_PASS** — Acceptable with conditions. [{engine_label}]")
    elif status == Status.FAIL:
        lines.append(f"**FAIL** — This does not meet requirements. [{engine_label}]")
    elif status == Status.INSUFFICIENT_DATA:
        lines.append(f"**INSUFFICIENT_DATA** — I need more information to run this assessment. [{engine_label}]")
    else:
        lines.append(f"**{status.value}** — [{engine_label}]")

    summary = _plain_language_summary(envelope)
    if summary:
        lines.append("")
        lines.append(summary)

    workflow = _get_chat_workflow(session_context)
    workflow_note: list[str] = []
    if workflow.get("active_field_label"):
        workflow_note.append(f"Current field: {workflow['active_field_label']}")
    if workflow.get("current_step"):
        workflow_note.append(f"Workflow step: {workflow['current_step']}")
    if workflow_note:
        lines.append("")
        lines.append(" | ".join(workflow_note))
    if workflow.get("next_steps"):
        lines.append("")
        lines.append("**Next step in this module:**")
        for step in workflow["next_steps"]:
            lines.append(f"  - {step}")
    if workflow.get("blockers"):
        lines.append("")
        lines.append("**Open blockers:**")
        for blocker in workflow["blockers"]:
            lines.append(f"  - {blocker}")

    # Draft warning
    if envelope.mode == TaskMode.DRAFT_ARTIFACT:
        lines.append("")
        lines.append("**DRAFT** — This requires review and approval per your program's M&P Plan before use.")

    # Body
    if envelope.response_text:
        lines.append("")
        lines.append(envelope.response_text)

    # MUA disposition
    if envelope.mua_disposition:
        lines.append("")
        lines.append(f"**MUA disposition:** {envelope.mua_disposition}")

    # INSUFFICIENT_DATA — guide the engineer
    if status == Status.INSUFFICIENT_DATA and envelope.missing_inputs:
        lines.append("")
        lines.append("Here's what I need from you to proceed:")
        for m in envelope.missing_inputs:
            lines.append(f"  - {m}")

    # Authority and citations
    if envelope.authority_basis:
        lines.append("")
        lines.append("**Authority basis:**")
        for a in envelope.authority_basis:
            lines.append(f"  - {a}")

    if envelope.citations:
        lines.append("")
        lines.append("**Citations:**")
        for c in envelope.citations:
            lines.append(f"  - {c}")

    # Assumptions — surface them so the engineer can correct
    if envelope.assumptions:
        lines.append("")
        lines.append("**Assumptions** (let me know if these don't match your case):")
        for a in envelope.assumptions:
            lines.append(f"  - {a}")

    # Confidence indicators (per spec rules)
    dp = envelope.domain_payload
    conf_lines: list[str] = []

    extraction_conf = dp.get("extraction_confidence")
    if extraction_conf is not None and float(extraction_conf) < 0.9:
        conf_lines.append(f"  - Extraction confidence: {extraction_conf}")

    evidence_comp = dp.get("evidence_completeness")
    if evidence_comp is not None:
        conf_lines.append(f"  - Evidence completeness: {evidence_comp}")

    verdict_conf = dp.get("verdict_confidence")
    if verdict_conf is not None:
        conf_lines.append(f"  - Verdict confidence: {verdict_conf}")

    if conf_lines:
        lines.append("")
        lines.append("**Confidence indicators:**")
        lines.extend(conf_lines)

    # Recommended actions — with Category III prominence
    if envelope.recommended_actions:
        lines.append("")
        lines.append("**What you can do next:**")
        for r in envelope.recommended_actions:
            if "category iii" in str(r).lower() or "cat iii" in str(r).lower():
                lines.append(f"  **>>> {r} <<<**")
            else:
                lines.append(f"  - {r}")

    return "\n".join(lines)


def _plain_language_summary(envelope: EngineEnvelope) -> str:
    """Return a short plain-language lead-in for deterministic fallback mode."""
    if envelope.engine_id == "h2":
        if envelope.status == Status.PASS:
            return "From a hydrogen-compatibility standpoint, the current material and condition screen as acceptable as stated."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "From a hydrogen-compatibility standpoint, this is only acceptable within the stated condition limits and controls."
        if envelope.status == Status.FAIL:
            return "From a hydrogen-compatibility standpoint, the current case carries a real embrittlement or service risk."

    if envelope.engine_id == "galvanic":
        if envelope.status == Status.PASS:
            return "In plain language: this material couple screens as acceptable in the stated environment."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "In plain language: this couple may be workable, but only if you apply the listed mitigations."
        if envelope.status == Status.FAIL:
            return "In plain language: this couple carries meaningful galvanic risk in the stated environment."

    if envelope.engine_id == "fracture":
        if envelope.status == Status.PASS:
            return "From a fracture-control standpoint, the current classification and context support proceeding as stated."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "From a fracture-control standpoint, this path is only defensible if the listed controls, assumptions, or inspections hold."
        if envelope.status == Status.FAIL:
            return "From a fracture-control standpoint, the current part context does not support proceeding as stated."

    if envelope.engine_id == "gpcm":
        if envelope.status == Status.PASS:
            return "From a standards-compliance standpoint, the current case closes cleanly against the governing requirement set."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "From a standards-compliance standpoint, this can close only if the listed requirement gaps are resolved."
        if envelope.status == Status.FAIL:
            return "From a standards-compliance standpoint, the current case does not close against the governing requirements."

    if envelope.engine_id == "maptis_search":
        if envelope.status == Status.PASS:
            return "I found grounded MAPTIS evidence that directly supports this material question."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "I found useful MAPTIS evidence, but the record still needs interpretation or supplemental data."
        if envelope.status == Status.FAIL:
            return "The available MAPTIS evidence does not support the requested conclusion."

    if envelope.engine_id == "knowledge_twins":
        if envelope.status == Status.PASS:
            return "The visible Knowledge Twins evidence supports proceeding with this material pairing as stated."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "Knowledge Twins found a plausible path here, but the visible evidence still leaves conditions or heritage gaps to clear."
        if envelope.status == Status.FAIL:
            return "Knowledge Twins does not support this pairing with the currently visible evidence."

    if envelope.engine_id == "miul":
        if envelope.status == Status.PASS:
            return "From the MIUL workflow standpoint, the current extraction and review state supports moving forward."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "The MIUL workflow is on track, but there are still review conditions or missing confirmations to close first."
        if envelope.status == Status.FAIL:
            return "The current MIUL workflow state is not ready to proceed without correction."

    if envelope.engine_id == "mua":
        if envelope.status == Status.PASS:
            return "From the MUA workflow standpoint, the current material case supports the draft as stated."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "The MUA can proceed only if the listed conditions, precedents, or test assumptions are carried through."
        if envelope.status == Status.FAIL:
            return "The current MUA case does not support approval as stated."

    if envelope.engine_id == "forge_build":
        if envelope.status == Status.PASS:
            return "The current FORGE build state is healthy and the requested compile action completed as expected."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "The FORGE build is partly successful, but there are still compile conditions or follow-up actions to address."
        if envelope.status == Status.FAIL:
            return "The requested FORGE build action did not complete successfully."

    if envelope.engine_id == "forge_explorer":
        if envelope.status == Status.PASS:
            return "FORGE Explorer returned grounded results from the current compiled workspace."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "FORGE Explorer found relevant workspace evidence, but the answer still needs interpretation or more compiled coverage."
        if envelope.status == Status.FAIL:
            return "The current compiled FORGE workspace does not support the requested answer."

    if envelope.engine_id == "tocr":
        if envelope.status == Status.PASS:
            return "From the TOCR review standpoint, the current package supports the requested action as stated."
        if envelope.status == Status.CONDITIONAL_PASS:
            return "The TOCR review is directionally acceptable, but there are still compliance gaps or review conditions to close."
        if envelope.status == Status.FAIL:
            return "The TOCR review does not support proceeding as stated."

    if envelope.engine_id == "bsmh":
        structured = envelope.domain_payload.get("structured_query", {})
        intent = str(structured.get("intent") or "").replace("_", " ").strip()
        if intent:
            return f"I parsed this as a {intent} question and pulled the key inputs below."

    if envelope.status == Status.PASS:
        return "In plain language: the current engine result is acceptable as stated."
    if envelope.status == Status.CONDITIONAL_PASS:
        return "In plain language: the current engine result is acceptable only within the stated conditions."
    if envelope.status == Status.FAIL:
        return "In plain language: the current engine result does not support proceeding as stated."
    if envelope.status == Status.INSUFFICIENT_DATA:
        return "In plain language: I do not have enough grounded input to answer this yet."

    return ""
