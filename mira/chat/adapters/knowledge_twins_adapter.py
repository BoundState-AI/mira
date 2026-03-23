"""
Module-scoped chat adapter for Knowledge Twins.
"""

from __future__ import annotations

from typing import Any

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

_AUTHORITY = [
    "Knowledge Twins active page state",
    "Active fluid Body of Knowledge search results",
    "Hybrid query evidence summary",
]


def _module_context(session_context: dict[str, Any]) -> dict[str, Any]:
    context = session_context.get("module_context") or {}
    return context if isinstance(context, dict) else {}


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _classify_query(text: str) -> str:
    query = (text or "").lower()
    if any(
        phrase in query
        for phrase in (
            "what are knowledge twins",
            "what is knowledge twins",
            "what does this page do",
            "what does this module do",
        )
    ):
        return "definition"
    if any(token in query for token in ("start", "begin", "how do i use", "how do i start", "setup", "set up")):
        return "getting_started"
    if any(token in query for token in ("next", "what should", "what do i do next", "next step")):
        return "next_step"
    if any(token in query for token in ("browse", "search", "materials", "ratings")):
        return "browse"
    if any(token in query for token in ("ask", "decision", "verdict", "compatibility", "evidence")):
        return "ask"
    if any(token in query for token in ("bok", "source", "semantic", "citation")):
        return "evidence"
    return "summary"


def _recommended_actions(ctx: dict[str, Any]) -> list[str]:
    mode = str(ctx.get("mode") or "browse").strip()
    active_fluid = str(ctx.get("active_fluid") or "oxygen").strip()
    has_hybrid = bool(ctx.get("has_hybrid_response"))
    material_count = _to_int(ctx.get("material_result_count")) or 0
    bok_count = _to_int(ctx.get("bok_result_count")) or 0
    actions: list[str] = []
    if mode == "browse":
        if material_count == 0 and bok_count == 0:
            actions.append(f"Search for a material or term in {active_fluid} mode to load ratings and standards evidence.")
        else:
            actions.append("Use the browse results to identify candidate materials and supporting standards before asking for a decision.")
        actions.append("Switch to Ask mode when you want the hybrid evidence path to synthesize a deterministic decision.")
        return actions
    if not has_hybrid:
        actions.append("Enter a focused question in Ask mode to run the hybrid evidence pipeline.")
        actions.append("Keep the question specific to a material, fluid, and service condition so the evidence search has something to ground.")
        return actions
    actions.append("Inspect the deterministic decision and evidence summary before trusting the narrative explanation.")
    actions.append("Open the semantic and standards evidence if you need to defend the answer.")
    return actions


def _context_lines(query_kind: str, raw_query: str, ctx: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    mode = str(ctx.get("mode") or "browse").strip()
    active_fluid = str(ctx.get("active_fluid") or "oxygen").strip()
    query = str(ctx.get("query") or "").strip()
    material_count = _to_int(ctx.get("material_result_count")) or 0
    bok_count = _to_int(ctx.get("bok_result_count")) or 0
    has_hybrid = bool(ctx.get("has_hybrid_response"))
    deterministic_decision = str(ctx.get("deterministic_decision") or "").strip()
    decision_source = str(ctx.get("decision_source") or "").strip()
    semantic_results = _to_int(ctx.get("semantic_results_found")) or 0
    mua_precedents = _to_int(ctx.get("mua_precedents_found")) or 0
    test_results = _to_int(ctx.get("test_results_found")) or 0

    if query_kind == "definition":
        return [
            "Knowledge Twins is the evidence workspace for exploring oxygen or hydrogen compatibility using material ratings, standards evidence, and the hybrid query path.",
            "Browse mode helps you inspect candidate materials and BOK hits. Ask mode runs the hybrid evidence pipeline and shows the deterministic decision plus supporting evidence summary.",
        ]

    if query_kind == "getting_started":
        return [
            "You use Knowledge Twins in two passes:",
            "1. Pick the fluid domain, then browse materials and standards evidence to see what data exists.",
            "2. Switch to Ask mode for a focused compatibility question when you want the hybrid evidence pipeline to produce a decision and explanation.",
        ]

    lines.append(
        f"The active Knowledge Twins page is in {mode} mode for {active_fluid}."
    )

    if query_kind == "next_step":
        lines.append("Best next steps:")
        lines.extend(f"- {action}" for action in _recommended_actions(ctx))
    elif query_kind == "browse":
        lines.append(
            f"The current browse state has {material_count} material result(s) and {bok_count} BOK result(s) for the active query."
        )
    elif query_kind == "ask":
        if has_hybrid:
            lines.append(
                f"The current hybrid result for '{query or 'the active query'}' is {deterministic_decision or 'unscored'} from {decision_source or 'the hybrid engine'}."
            )
        else:
            lines.append("Ask mode does not currently have a hybrid result loaded.")
    elif query_kind == "evidence":
        if has_hybrid:
            lines.append(
                f"The active hybrid evidence summary includes {mua_precedents} MUA precedent(s), {test_results} test result(s), and {semantic_results} semantic result(s)."
            )
        else:
            lines.append(f"The current browse state has {bok_count} standards evidence hit(s) available.")
    else:
        lines.append(
            f"Your question was: {raw_query.strip() or 'knowledge twins summary'}. This chat is grounded only in the active fluid, mode, and visible page evidence."
        )
    return lines


class KnowledgeTwinsAdapter(EngineAdapter):
    engine_id: str = "knowledge_twins"
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
        ctx = _module_context(session_context)

        citations = [
            source
            for source in (ctx.get("bok_sources") or [])[:5]
            if isinstance(source, str) and source.strip()
        ]
        semantic_sources = [
            source
            for source in (ctx.get("semantic_sources") or [])[:5]
            if isinstance(source, str) and source.strip()
        ]

        return self.wrap_envelope(
            status=Status.PASS,
            response_text="\n".join(_context_lines(query_kind, raw_query, ctx)),
            authority_basis=_AUTHORITY,
            citations=list(dict.fromkeys(citations + semantic_sources)),
            evidence=[
                {
                    "mode": ctx.get("mode"),
                    "active_fluid": ctx.get("active_fluid"),
                    "query": ctx.get("query"),
                    "material_result_count": ctx.get("material_result_count"),
                    "bok_result_count": ctx.get("bok_result_count"),
                    "has_hybrid_response": ctx.get("has_hybrid_response"),
                    "deterministic_decision": ctx.get("deterministic_decision"),
                    "decision_source": ctx.get("decision_source"),
                    "semantic_results_found": ctx.get("semantic_results_found"),
                    "mua_precedents_found": ctx.get("mua_precedents_found"),
                    "test_results_found": ctx.get("test_results_found"),
                }
            ],
            recommended_actions=_recommended_actions(ctx),
            domain_payload={
                "query_kind": query_kind,
                "module_context": ctx,
            },
        )
