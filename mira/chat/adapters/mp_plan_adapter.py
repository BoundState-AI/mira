"""
Module: MIRA Chat -- MP Plan Adapter
Purpose: Read-only chat adapter for the M&P Plan workflow.

Answers only from the active MP Plan session state and the module guidance
pack derived from NASA-STD-6016C/JSC 27301F workflow rules.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode
from mira.mp_plan.compute_loop_codex import can_generate_codex, generate_blocking_questions_codex
from mira.mp_plan.models import PlanGeneratorSession
from mira.mp_plan.session_manager import get_session_manager

_GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "mp_plan" / "data" / "guidance.json"
_WORD_RE = re.compile(r"[a-z0-9_]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "at", "be", "do", "for", "from", "how", "i", "if", "in",
    "is", "it", "me", "my", "of", "on", "or", "plan", "session", "show", "tell", "that",
    "the", "this", "to", "we", "what", "which", "with", "workflow", "you",
}


@lru_cache(maxsize=1)
def _load_guidance() -> dict[str, list[dict[str, Any]]]:
    with _GUIDANCE_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {key: value for key, value in raw.items() if isinstance(value, list)}


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall((text or "").lower())
        if len(token) > 2 and token not in _STOP_WORDS
    }


def _score_guidance_entry(query_tokens: set[str], entry: dict[str, Any]) -> int:
    haystack = " ".join(
        str(entry.get(field, ""))
        for field in ("field_id", "label", "what", "why", "guidance", "source", "question_text")
    ).lower()
    return sum(1 for token in query_tokens if token in haystack)


def _search_guidance(query: str, limit: int = 3) -> list[dict[str, Any]]:
    tokens = _tokenize(query)
    if not tokens:
        return []

    matches: list[tuple[int, dict[str, Any]]] = []
    for section, entries in _load_guidance().items():
        for entry in entries:
            score = _score_guidance_entry(tokens, entry)
            if score <= 0:
                continue
            enriched = dict(entry)
            enriched["_section"] = section
            matches.append((score, enriched))

    matches.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("label") or item[1].get("what") or item[1].get("field_id") or ""),
        ),
    )
    return [entry for _, entry in matches[:limit]]


def _review_is_resolved(det: dict[str, Any]) -> bool:
    review = det.get("human_review") or {}
    return bool(review.get("resolved"))


def _classify_query(text: str) -> str:
    query = (text or "").lower()
    if any(
        phrase in query
        for phrase in (
            "what's a m&p plan",
            "what is a m&p plan",
            "what's an m&p plan",
            "what is an m&p plan",
            "what's m&p plan",
            "what is m&p plan",
            "what's mp plan",
            "what is mp plan",
            "define m&p plan",
            "define mp plan",
            "explain m&p plan",
            "explain mp plan",
            "what does mp plan do",
            "what does this module do",
            "what is this mp plan workflow",
        )
    ):
        return "definition"
    if any(token in query for token in ("start", "begin", "create", "set up", "setup", "kick off")):
        return "getting_started"
    if any(token in query for token in ("block", "blocking", "stuck", "why can't", "why cant", "ready")):
        return "blockers"
    if any(token in query for token in ("question", "need from me", "clarify", "answer next")):
        return "questions"
    if any(token in query for token in ("next", "what should", "where do i go", "step")):
        return "next_step"
    if any(token in query for token in ("environment", "vehicle", "service")):
        return "environments"
    if any(token in query for token in ("material", "maptis", "inventory", "bom")):
        return "materials"
    if any(token in query for token in ("minor quantity", "minor-quantity", "45 g", "13 cm")):
        return "minor_quantity"
    if any(token in query for token in ("hitl", "review", "human review")):
        return "hitl"
    if any(token in query for token in ("nonconformance", "closure", "open gap", "mua")):
        return "closure"
    return "summary"


def _extract_session_id(parsed_input: dict[str, Any], session_context: dict[str, Any]) -> str | None:
    inherited = parsed_input.get("inherited_entities") or {}
    module_context = session_context.get("module_context") or {}
    for candidate in (
        module_context.get("mp_plan_session_id"),
        inherited.get("mp_plan_session_id"),
        session_context.get("mp_plan_session_id"),
        session_context.get("accumulated_entities", {}).get("mp_plan_session_id"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _summarize_session(session: PlanGeneratorSession) -> dict[str, Any]:
    working = session.model_copy(deep=True)
    can_generate, blockers = can_generate_codex(working)
    questions = working.blocking_questions or generate_blocking_questions_codex(working)
    resolved_ids = {resolution.material_id for resolution in working.maptis_resolutions}
    unresolved_materials = [material for material in working.materials if material.id not in resolved_ids]
    unresolved_hitl = [
        det
        for det in working.mpr_determinations
        if det.get("hitl_required") and not _review_is_resolved(det)
    ]
    closed_ids = {decision.gap_id for decision in working.closure_decisions}
    accepted_ids = {gap.gap_id for gap in working.accepted_open_gaps}
    open_nonconformances = [
        nc
        for nc in working.nonconformances
        if nc.nonconformance_id not in closed_ids and nc.nonconformance_id not in accepted_ids
    ]
    return {
        "can_generate": can_generate,
        "blockers": blockers,
        "questions": questions,
        "resolved_ids": resolved_ids,
        "unresolved_materials": unresolved_materials,
        "unresolved_hitl": unresolved_hitl,
        "open_nonconformances": open_nonconformances,
    }


def _blocking_actions(summary: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    blockers = [str(blocker) for blocker in summary["blockers"]]
    if any("No environments defined" in blocker for blocker in blockers):
        actions.append("Add at least one environment before re-running the MP Plan compute step.")
    if any("No materials entered" in blocker for blocker in blockers):
        actions.append("Add the material inventory for this plan before computing applicability.")
    if summary["unresolved_materials"]:
        question = _material_resolution_question(summary)
        if question is not None:
            actions.append(
                "Resolve the unresolved MAPTIS material in the materials step: "
                f"{question.question_text}"
            )
        else:
            unresolved = summary["unresolved_materials"][0]
            actions.append(
                f"Resolve the MAPTIS code for '{unresolved.name}' in the materials step."
            )
        actions.append(
            "Re-run compute after the material is resolved so downstream analysis and review work can populate."
        )
        return actions[:4]
    if summary["questions"]:
        actions.append("Work through the current blocking questions for the active workflow step.")
    if summary["unresolved_hitl"]:
        actions.append("Resolve the pending HITL determinations before generation.")
    if summary["open_nonconformances"]:
        actions.append("Select a closure path or accepted-open disposition for each open nonconformance.")
    return actions[:4]


def _guidance_lines(guidance_hits: list[dict[str, Any]]) -> list[str]:
    if not guidance_hits:
        return []
    lines = ["Relevant MP Plan guidance:"]
    for entry in guidance_hits:
        title = (
            str(entry.get("label") or entry.get("what") or entry.get("field_id") or entry.get("_section"))
            .strip()
        )
        guidance = str(entry.get("guidance") or entry.get("why") or "").strip()
        source = str(entry.get("source") or "").strip()
        line = f"- {title}: {guidance}" if guidance else f"- {title}"
        if source:
            line = f"{line} [{source}]"
        lines.append(line)
    return lines


def _guidance_entry(field_id: str) -> dict[str, Any] | None:
    for entries in _load_guidance().values():
        for entry in entries:
            key = str(entry.get("field_id") or entry.get("question_type") or "").strip()
            if key == field_id:
                return entry
    return None


def _format_guidance_step(prefix: str, field_id: str, fallback: str) -> tuple[str, str | None]:
    entry = _guidance_entry(field_id)
    if not entry:
        return prefix + fallback, None
    guidance = str(entry.get("guidance") or entry.get("what") or fallback).strip()
    source = str(entry.get("source") or "").strip() or None
    return f"{prefix}{guidance}", source


def _question_type_key(question: Any) -> str:
    question_type = getattr(question, "question_type", None)
    if question_type is None:
        return ""
    value = getattr(question_type, "value", None)
    if isinstance(value, str) and value:
        return value
    name = getattr(question_type, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(question_type).strip()


def _material_resolution_question(summary: dict[str, Any]) -> Any | None:
    for question in summary["questions"]:
        question_type = _question_type_key(question)
        if question_type in {"material_ambiguous", "MATERIAL_AMBIGUOUS"}:
            return question
    return None


def _blocker_guidance_hits(
    query_kind: str,
    raw_query: str,
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    prioritized_keys: list[str] = []
    blockers = [str(blocker) for blocker in summary["blockers"]]

    if summary["unresolved_materials"]:
        prioritized_keys.extend(["materials", "materials.maptis_code", "MATERIAL_AMBIGUOUS", "compute_question_recompute"])
    elif any("No environments defined" in blocker for blocker in blockers):
        prioritized_keys.extend(["environments", "ENVIRONMENT_MISSING", "compute_question_recompute"])
    elif any("No materials entered" in blocker for blocker in blockers):
        prioritized_keys.extend(["materials", "compute_question_recompute"])
    elif query_kind == "hitl" and summary["unresolved_hitl"]:
        for question in summary["questions"]:
            question_type = _question_type_key(question)
            if question_type in {"TAILORING_APPROVAL", "GROUPING_CONFIRMATION", "PRECEDENT_VALIDATION"}:
                prioritized_keys.append(question_type)
        prioritized_keys.append("compute_question_recompute")
    elif query_kind == "closure" and summary["open_nonconformances"]:
        prioritized_keys.extend(["configuration_analysis", "mua_closure"])

    if not prioritized_keys:
        return _search_guidance(raw_query)

    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in prioritized_keys:
        entry = _guidance_entry(key)
        if not entry:
            continue
        dedupe_key = str(entry.get("field_id") or entry.get("question_type") or entry.get("source") or key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        hits.append(dict(entry))
    return hits[:3]


def _build_getting_started_response() -> tuple[list[str], list[str], list[str]]:
    steps: list[str] = [
        "You can start an MP Plan in five steps:",
    ]
    citations: list[str] = []

    step_1, source_1 = _format_guidance_step(
        "1. Create the session with the program name and, if you know it, the current program phase. ",
        "program_name",
        "Choose the program first so the policy pack and vehicle presets are grounded correctly.",
    )
    steps.append(step_1)
    if source_1:
        citations.append(source_1)

    phase_entry = _guidance_entry("program_phase")
    if phase_entry:
        phase_guidance = str(phase_entry.get("guidance") or "").strip()
        if phase_guidance:
            steps.append(f"2. Set the program phase. {phase_guidance}")
            source = str(phase_entry.get("source") or "").strip()
            if source:
                citations.append(source)
        else:
            steps.append("2. Set the program phase so the workflow knows how aggressively open gaps must be closed.")
    else:
        steps.append("2. Set the program phase so the workflow knows how aggressively open gaps must be closed.")

    step_3, source_3 = _format_guidance_step(
        "3. Add at least one service environment. ",
        "environments",
        "Define each distinct environment the hardware sees across storage, ground, and flight operations.",
    )
    steps.append(step_3)
    if source_3:
        citations.append(source_3)

    step_4, source_4 = _format_guidance_step(
        "4. Add the material inventory. ",
        "materials",
        "Enter the BOM materials, including MAPTIS code if known, plus mass and surface area when minor quantity could matter.",
    )
    steps.append(step_4)
    if source_4:
        citations.append(source_4)

    loop_entry = _guidance_entry("compute_question_recompute")
    if loop_entry:
        steps.append(
            "5. Run compute, answer any blocking questions, and recompute until the readiness check clears. "
            + str(loop_entry.get("guidance") or "").strip()
        )
        source = str(loop_entry.get("source") or "").strip()
        if source:
            citations.append(source)
    else:
        steps.append("5. Run compute, answer any blocking questions, and recompute until the plan is ready to generate.")

    recommended_actions = [
        "Open the MP Plan page and create a session first.",
        "Add one environment and the initial material inventory before asking the scoped chat about blockers.",
        "Run compute after each major input update so the blocking questions stay current.",
    ]
    return steps, list(dict.fromkeys(citations)), recommended_actions


def _build_definition_response() -> tuple[list[str], list[str], list[str]]:
    lines = [
        "An M&P plan is the workflow and output package used to show that a hardware material set has been screened against the applicable NASA materials-and-process requirements and that any resulting gaps are either resolved as data deficiencies or closed as nonconformances.",
    ]
    citations: list[str] = []

    compute_entry = _guidance_entry("compute_question_recompute")
    if compute_entry:
        lines.append(
            "In this module, the workflow is intentionally iterative: "
            + str(compute_entry.get("what") or "").strip()
        )
        lines.append(str(compute_entry.get("guidance") or "").strip())
        source = str(compute_entry.get("source") or "").strip()
        if source:
            citations.append(source)

    engine_entry = _guidance_entry("engine_sequence")
    if engine_entry:
        lines.append(
            "The system runs four engines in order: "
            + str(engine_entry.get("what") or "").strip()
        )
        source = str(engine_entry.get("source") or "").strip()
        if source:
            citations.append(source)

    deficiency_entry = _guidance_entry("deficiency_signal")
    nonconformance_entry = _guidance_entry("nonconformance_signal")
    if deficiency_entry and nonconformance_entry:
        lines.append(
            "A deficiency means the system is missing evidence to make a decision. "
            "A nonconformance means the evidence shows a real requirement failure that needs closure."
        )
        for entry in (deficiency_entry, nonconformance_entry):
            source = str(entry.get("source") or "").strip()
            if source:
                citations.append(source)

    recommended_actions = [
        "If you want the active plan worked, ask what is blocking generation right now.",
        "If you want the workflow steps, ask how to start or what to do next in the current session.",
        "If you want the current session advanced, resolve the open blockers and rerun compute.",
    ]
    return lines, list(dict.fromkeys(citations)), recommended_actions


def _build_session_lines(
    query_kind: str,
    raw_query: str,
    session: PlanGeneratorSession,
    summary: dict[str, Any],
    module_context: dict[str, Any],
    guidance_hits: list[dict[str, Any]],
) -> list[str]:
    current_step = str(module_context.get("current_step") or "setup").strip()
    lines: list[str] = []
    if summary["can_generate"]:
        lines.append(
            f"The active MP Plan session is ready to generate right now. Session {session.session_id} "
            f"has {len(session.materials)} materials and {len(session.environments)} environments with no open generation blockers."
        )
    else:
        lines.append(
            f"The active MP Plan session is not ready to generate yet. Session {session.session_id} is currently at the {current_step} step."
        )

    if query_kind == "blockers":
        blockers = summary["blockers"]
        if blockers:
            lines.append("Current blockers:")
            lines.extend(f"- {blocker}" for blocker in blockers[:5])
        else:
            lines.append("I do not see any generation blockers in the current MP Plan session.")
    elif query_kind == "questions":
        questions = summary["questions"]
        if questions:
            lines.append("Current blocking questions:")
            for question in questions[:5]:
                lines.append(f"- [{question.question_type}] {question.question_text}")
        else:
            lines.append("There are no active blocking questions in the current MP Plan session.")
    elif query_kind == "next_step":
        actions = _blocking_actions(summary)
        if actions:
            lines.append("Best next steps:")
            lines.extend(f"- {action}" for action in actions)
        else:
            lines.append("Best next step: generate the MP Plan artifacts or review the output package.")
    elif query_kind == "environments":
        if session.environments:
            lines.append("Environments in scope:")
            for environment in session.environments[:5]:
                lines.append(
                    f"- {environment.name}: {environment.o2_pct:g}% O2 at {environment.pressure_psia:g} psia"
                )
        else:
            lines.append("No environments have been added to this MP Plan session yet.")
    elif query_kind == "materials":
        if session.materials:
            lines.append("Materials in the current inventory:")
            for material in session.materials[:5]:
                resolved = "resolved" if material.id in summary["resolved_ids"] else "unresolved"
                lines.append(f"- {material.name} for {material.application} ({resolved})")
        else:
            lines.append("No materials have been added to this MP Plan session yet.")
    elif query_kind == "minor_quantity":
        aggregation = session.minor_quantity_aggregation
        if aggregation and aggregation.groups:
            eligible = sum(1 for group in aggregation.groups if group.eligible)
            lines.append(
                f"Minor quantity analysis has been run on {len(aggregation.groups)} groups, with {eligible} currently eligible groups."
            )
        else:
            lines.append(
                "Minor quantity analysis has not produced grouped results yet. That usually means the plan still needs compute results and grounded mass/surface-area inputs."
            )
    elif query_kind == "hitl":
        pending = summary["unresolved_hitl"]
        if pending:
            lines.append(f"There are {len(pending)} HITL determinations still pending review.")
        else:
            lines.append("There are no unresolved HITL determinations in the current MP Plan session.")
    elif query_kind == "closure":
        open_nonconformances = summary["open_nonconformances"]
        lines.append(
            f"The session currently has {len(session.nonconformances)} nonconformances, "
            f"{len(open_nonconformances)} of which still need closure or accepted-open handling."
        )
    else:
        lines.append(
            f"Your question was: {raw_query.strip() or 'session summary'}. "
            f"The session currently has {len(session.materials)} materials, {len(session.environments)} environments, "
            f"{len(summary['questions'])} blocking questions, and {len(summary['open_nonconformances'])} open nonconformances."
        )

    lines.extend(_guidance_lines(guidance_hits))
    return lines


class MPPlanAdapter(EngineAdapter):
    engine_id: str = "mp_plan"
    engine_version: str = "1.0.0"
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        raw_query = str(parsed_input.get("raw_query") or "").strip()
        query_kind = _classify_query(raw_query)
        guidance_hits = _search_guidance(raw_query)

        if query_kind in {"getting_started", "definition"}:
            if query_kind == "getting_started":
                response_lines, citations, recommended_actions = _build_getting_started_response()
            else:
                response_lines, citations, recommended_actions = _build_definition_response()
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="\n".join(response_lines),
                authority_basis=["MP Plan guidance pack", "NASA-STD-6016C", "JSC 27301F"],
                citations=citations,
                recommended_actions=recommended_actions,
                domain_payload={"query_kind": query_kind, "guidance_only": True},
            )

        session_id = _extract_session_id(parsed_input, session_context)

        if not session_id:

            message_lines = [
                "MP Plan chat is scoped to an active M&P Plan session, but I do not have a session id yet.",
                "Open chat from the MP Plan page after creating or loading a session so I can ground the answer in that workflow state.",
            ]
            message_lines.extend(_guidance_lines(guidance_hits))
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text="\n".join(message_lines),
                authority_basis=["MP Plan guidance pack", "NASA-STD-6016C", "JSC 27301F"],
                citations=[
                    str(entry.get("source")).strip()
                    for entry in guidance_hits
                    if str(entry.get("source") or "").strip()
                ],
                missing_inputs=["mp_plan_session_id"],
                domain_payload={"query_kind": query_kind, "guidance_hits": guidance_hits},
            )

        manager = get_session_manager()
        session = manager.get_session(session_id)
        if session is None:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    f"I could not find MP Plan session '{session_id}'. "
                    "Reload the MP Plan page and reopen the scoped chat so I can use the active session state."
                ),
                missing_inputs=["valid_mp_plan_session"],
                authority_basis=["MP Plan session store"],
                citations=["MP Plan session state"],
                domain_payload={"query_kind": query_kind, "session_id": session_id},
            )

        summary = _summarize_session(session)
        guidance_hits = _blocker_guidance_hits(query_kind, raw_query, summary)
        module_context = session_context.get("module_context") or {}
        response_lines = _build_session_lines(
            query_kind=query_kind,
            raw_query=raw_query,
            session=session,
            summary=summary,
            module_context=module_context if isinstance(module_context, dict) else {},
            guidance_hits=guidance_hits,
        )

        citations = ["MP Plan active session state"]
        citations.extend(
            str(entry.get("source")).strip()
            for entry in guidance_hits
            if str(entry.get("source") or "").strip()
        )
        evidence: list[dict[str, Any]] = [
            {
                "source_id": session.session_id,
                "program_name": session.program_name,
                "program_phase": session.program_phase,
                "material_count": len(session.materials),
                "environment_count": len(session.environments),
                "blocking_question_count": len(summary["questions"]),
                "can_generate": summary["can_generate"],
            }
        ]
        for question in summary["questions"][:3]:
            evidence.append(
                {
                    "source_id": question.question_id,
                    "question_type": question.question_type,
                    "question_text": question.question_text,
                }
            )

        status = Status.PASS if summary["can_generate"] else Status.INSUFFICIENT_DATA
        recommended_actions = _blocking_actions(summary)
        missing_inputs = [str(blocker) for blocker in summary["blockers"][:5]]

        session_context["mp_plan_session_id"] = session.session_id

        return self.wrap_envelope(
            status=status,
            response_text="\n".join(response_lines),
            authority_basis=[
                "MP Plan active session state",
                "MP Plan guidance pack",
                "NASA-STD-6016C",
                "JSC 27301F",
            ],
            citations=list(dict.fromkeys(citations)),
            evidence=evidence,
            missing_inputs=missing_inputs,
            recommended_actions=recommended_actions,
            domain_payload={
                "query_kind": query_kind,
                "session_id": session.session_id,
                "can_generate": summary["can_generate"],
                "blockers": summary["blockers"],
                "guidance_hits": guidance_hits,
            },
        )
