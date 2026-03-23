"""
Module-scoped chat adapter for the FORGE Explorer.
"""

from __future__ import annotations

from typing import Any

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

_AUTHORITY = [
    "FORGE Explorer page state",
    "FORGE compile result",
    "FORGE BSMS query result",
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
            "what is forge explorer",
            "what's forge explorer",
            "what does this page do",
            "what does this module do",
            "what can this database answer",
        )
    ):
        return "definition"
    if any(token in query for token in ("start", "begin", "set up", "setup", "how do i use", "how do i start")):
        return "getting_started"
    if any(token in query for token in ("next", "what should", "what do i do next", "next step")):
        return "next_step"
    if any(token in query for token in ("bsms", "query", "answer", "bouncer", "rules", "lineage")):
        return "bsms_query"
    if any(token in query for token in ("question map", "question surface", "question catalog")):
        return "questions"
    if any(token in query for token in ("relationship", "join", "latent")):
        return "relationships"
    if any(token in query for token in ("capability", "archetype")):
        return "capabilities"
    if any(token in query for token in ("status", "progress", "compile", "stage")):
        return "compile_status"
    return "summary"


def _recommended_actions(ctx: dict[str, Any]) -> list[str]:
    build_in_progress = bool(ctx.get("build_in_progress"))
    has_compile_result = bool(ctx.get("has_compile_result"))
    has_query_result = bool(ctx.get("has_query_result"))
    actions: list[str] = []
    if build_in_progress:
        actions.append("Let the compile finish so the question catalog and BSMS pipeline are stable.")
        return actions
    if not has_compile_result:
        actions.append("Compile the database first so FORGE can discover the question surface.")
        actions.append("After compile, click a generated question or run a BSMS query to test the answer path.")
        return actions
    if not has_query_result:
        actions.append("Pick a compiled question or type a query to test the BSMS path against the generated surface.")
        actions.append("Inspect the question catalog before widening the database scope or regenerating the pack.")
        return actions
    actions.append("Review the bouncer, parsed intent, and rules verdict before you trust the rendered BSMS answer.")
    actions.append("Open lineage when you need to prove how the answer was produced.")
    return actions


def _context_lines(query_kind: str, raw_query: str, ctx: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    build_in_progress = bool(ctx.get("build_in_progress"))
    has_compile_result = bool(ctx.get("has_compile_result"))
    has_query_result = bool(ctx.get("has_query_result"))
    question_count = _to_int(ctx.get("question_count")) or 0
    table_count = _to_int(ctx.get("table_count")) or 0
    relationship_count = _to_int(ctx.get("relationship_count")) or 0
    capability_count = _to_int(ctx.get("capability_count")) or 0
    candidate_archetype_count = _to_int(ctx.get("candidate_archetype_count")) or 0
    compile_mode = str(ctx.get("compile_mode") or "curated").strip()
    current_query = str(ctx.get("current_query") or "").strip()
    bsms_status = str(ctx.get("bsms_status") or "").strip()
    bouncer_status = str(ctx.get("bouncer_status") or "").strip()
    rules_verdict = str(ctx.get("rules_verdict") or "").strip()

    if query_kind == "definition":
        return [
            "FORGE Explorer is the page for testing what a compiled database can actually answer.",
            "It uses the FORGE question surface, relationship map, capability coverage, and BSMS pipeline output to show whether a query is grounded and how the answer was produced.",
        ]

    if query_kind == "getting_started":
        return [
            "You use FORGE Explorer in three phases:",
            "1. Compile the database so FORGE can discover tables, joins, capabilities, and questions.",
            "2. Inspect the generated question catalog and structural summaries.",
            "3. Run BSMS queries against that compiled answer surface and inspect bouncer, rules, and lineage before trusting the result.",
        ]

    if build_in_progress:
        lines.append("A FORGE compile is still running, so the answer surface may change before the job finishes.")
    elif has_compile_result:
        lines.append(
            f"The current explorer surface was compiled in {compile_mode} mode and exposes {question_count} question(s) over {table_count} table(s) and {relationship_count} relationship(s)."
        )
    else:
        lines.append("The explorer does not have a compiled database surface yet.")

    if query_kind == "next_step":
        lines.append("Best next steps:")
        lines.extend(f"- {action}" for action in _recommended_actions(ctx))
    elif query_kind == "bsms_query":
        if has_query_result:
            lines.append(
                f"The last BSMS query was '{current_query or 'the active query'}' with status {bsms_status or 'unknown'}."
            )
            if bouncer_status or rules_verdict:
                lines.append(
                    f"Bouncer: {bouncer_status or 'n/a'}. Rules verdict: {rules_verdict or 'n/a'}."
                )
        else:
            lines.append("No BSMS query result is loaded on this page yet.")
    elif query_kind == "questions":
        if has_compile_result:
            lines.append(
                f"FORGE currently surfaced {question_count} question(s); that catalog is the bounded answer surface this database is allowed to claim."
            )
        else:
            lines.append("The question catalog does not exist yet because the database has not been compiled.")
    elif query_kind == "relationships":
        if has_compile_result:
            lines.append(
                f"The compiled graph currently includes {relationship_count} relationship(s) and {_to_int(ctx.get('latent_relationship_count')) or 0} latent join(s)."
            )
        else:
            lines.append("Relationships and latent joins are not available until the compile finishes.")
    elif query_kind == "capabilities":
        if has_compile_result:
            lines.append(
                f"Capability coverage currently shows {capability_count} capability entries and {candidate_archetype_count} candidate archetype(s)."
            )
        else:
            lines.append("Capability coverage is not available until the compile finishes.")
    elif query_kind == "compile_status":
        if has_compile_result:
            lines.append("The compile is complete and the explorer is ready for question-surface testing.")
        elif build_in_progress:
            lines.append("The compile is still in progress, so the surface is not stable yet.")
    else:
        lines.append(
            f"Your question was: {raw_query.strip() or 'explorer summary'}. This chat is grounded only in the active FORGE Explorer state."
        )
    return lines


class FORGEExplorerAdapter(EngineAdapter):
    engine_id: str = "forge_explorer"
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

        return self.wrap_envelope(
            status=Status.PASS,
            response_text="\n".join(_context_lines(query_kind, raw_query, ctx)),
            authority_basis=_AUTHORITY,
            citations=[
                source
                for source in (
                    "FORGE compile result" if ctx.get("has_compile_result") else None,
                    "FORGE BSMS query result" if ctx.get("has_query_result") else None,
                )
                if source
            ],
            evidence=[
                {
                    "compile_mode": ctx.get("compile_mode"),
                    "table_count": ctx.get("table_count"),
                    "question_count": ctx.get("question_count"),
                    "relationship_count": ctx.get("relationship_count"),
                    "capability_count": ctx.get("capability_count"),
                    "candidate_archetype_count": ctx.get("candidate_archetype_count"),
                    "has_query_result": ctx.get("has_query_result"),
                    "current_query": ctx.get("current_query"),
                    "bsms_status": ctx.get("bsms_status"),
                    "bouncer_status": ctx.get("bouncer_status"),
                    "rules_verdict": ctx.get("rules_verdict"),
                    "lineage_available": ctx.get("lineage_available"),
                }
            ],
            recommended_actions=_recommended_actions(ctx),
            domain_payload={
                "query_kind": query_kind,
                "module_context": ctx,
            },
        )
