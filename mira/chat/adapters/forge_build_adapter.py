"""
Module-scoped chat adapter for the FORGE Build Console.
"""

from __future__ import annotations

from typing import Any

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

_AUTHORITY = [
    "FORGE Build Console page state",
    "FORGE compile job status",
    "FORGE generated authority pack metadata",
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
            "what is forge",
            "what's forge",
            "what is this page",
            "what does this page do",
            "what does this module do",
            "what is the forge build console",
        )
    ):
        return "definition"
    if any(token in query for token in ("start", "begin", "set up", "setup", "how do i use", "how do i start")):
        return "getting_started"
    if any(token in query for token in ("next", "what should", "what do i do next", "next step")):
        return "next_step"
    if any(token in query for token in ("status", "progress", "building", "compile", "stage")):
        return "compile_status"
    if any(token in query for token in ("authority", "rule pack", "bsms", "lineage")):
        return "authority"
    if any(token in query for token in ("bundle", "generated app", "output", "artifact")):
        return "bundle"
    if any(token in query for token in ("warning", "guardrail", "remote database")):
        return "warnings"
    return "summary"


def _recommended_actions(ctx: dict[str, Any]) -> list[str]:
    build_in_progress = bool(ctx.get("build_in_progress"))
    has_result = bool(ctx.get("has_compile_result"))
    warnings_count = _to_int(ctx.get("warnings_count")) or 0
    actions: list[str] = []
    if build_in_progress:
        actions.append("Let the current compile finish before you trust the authority pack or generated bundle.")
        actions.append("Watch the active stage and warning count instead of launching another build in parallel.")
        return actions
    if not has_result:
        actions.append("Enter the database URL and run Build Artifacts to generate the FORGE outputs.")
        actions.append("Use a local SQLite or localhost-backed database unless the backend explicitly allows remote access.")
        return actions
    if warnings_count > 0:
        actions.append("Review the compile warnings before treating the generated authority pack as production-ready.")
    actions.append("Inspect the authority pack and BSMS pipeline output before you trust downstream query behavior.")
    actions.append("Use FORGE Explorer to test whether the compiled question surface answers what you need.")
    return actions


def _context_lines(query_kind: str, raw_query: str, ctx: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    build_in_progress = bool(ctx.get("build_in_progress"))
    has_result = bool(ctx.get("has_compile_result"))
    compile_stage = str(ctx.get("compile_stage") or "").strip()
    compile_message = str(ctx.get("compile_message") or "").strip()
    progress = _to_int(ctx.get("compile_progress"))
    table_count = _to_int(ctx.get("table_count")) or 0
    question_count = _to_int(ctx.get("question_count")) or 0
    relationship_count = _to_int(ctx.get("relationship_count")) or 0
    warnings_count = _to_int(ctx.get("warnings_count")) or 0
    bundle_file_count = _to_int(ctx.get("bundle_file_count")) or 0
    database_ref = str(ctx.get("database_url_redacted") or ctx.get("database_url") or "the current database").strip()

    if query_kind == "definition":
        lines.extend(
            [
                "FORGE Build Console is the build-and-diagnostics surface for compiling a database into FORGE artifacts.",
                "This page is for running the compile, watching stage progress, inspecting the raw authority pack output, and checking the generated bundle metadata.",
            ]
        )
        return lines

    if query_kind == "getting_started":
        lines.extend(
            [
                "You start here by pointing FORGE at a database and compiling the artifacts:",
                "1. Set the database URL, app name, sample rows, and optional output directory.",
                "2. Run Build Artifacts and watch the compile stage until the job completes.",
                "3. Inspect warnings, question map, capabilities, relationships, authority pack, and bundle output before trusting the result.",
                "4. Move to FORGE Explorer when you want to probe the answer surface through BSMS queries.",
            ]
        )
        return lines

    if build_in_progress:
        lines.append(
            f"FORGE is currently building against {database_ref}. Stage: {compile_stage or 'running'}."
        )
        if compile_message:
            lines.append(f"Current status: {compile_message}.")
        if progress is not None:
            lines.append(f"Reported progress: {progress}%.")
    elif has_result:
        lines.append(
            f"The latest FORGE build compiled {table_count} table(s), {question_count} question(s), and {relationship_count} relationship(s) from {database_ref}."
        )
    else:
        lines.append("No FORGE compile result is loaded on this page yet.")

    if query_kind == "next_step":
        lines.append("Best next steps:")
        lines.extend(f"- {action}" for action in _recommended_actions(ctx))
    elif query_kind == "compile_status":
        if has_result and not build_in_progress:
            lines.append(
                f"The last compile completed with {warnings_count} warning(s) and {bundle_file_count} generated bundle file(s)."
            )
    elif query_kind == "authority":
        if has_result:
            lines.append(
                "The authority-facing outputs on this page are the question map, capability map, relationship graph, BSMS pipeline config, authority pack, and lineage schema."
            )
        else:
            lines.append("The authority pack does not exist yet because the page has not completed a compile.")
    elif query_kind == "bundle":
        if has_result:
            lines.append(
                f"The generated bundle metadata shows {bundle_file_count} file(s) in the emitted app/artifact tree."
            )
        else:
            lines.append("There is no generated bundle yet because no compile result is loaded.")
    elif query_kind == "warnings":
        if warnings_count > 0:
            lines.append(f"The current compile produced {warnings_count} warning(s); review them before you trust the emitted pack.")
        else:
            lines.append("No compile warnings are currently surfaced on this page.")
    else:
        lines.append(
            f"Your question was: {raw_query.strip() or 'build summary'}. This page is grounded only in the current compile job and artifact outputs."
        )
    return lines


class FORGEBuildAdapter(EngineAdapter):
    engine_id: str = "forge_build"
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
                    "FORGE compile job status" if ctx.get("build_in_progress") else None,
                    "FORGE compile result" if ctx.get("has_compile_result") else None,
                    "FORGE generated bundle metadata" if ctx.get("bundle_file_count") else None,
                )
                if source
            ],
            evidence=[
                {
                    "database_url_redacted": ctx.get("database_url_redacted"),
                    "compile_stage": ctx.get("compile_stage"),
                    "compile_progress": ctx.get("compile_progress"),
                    "has_compile_result": ctx.get("has_compile_result"),
                    "table_count": ctx.get("table_count"),
                    "question_count": ctx.get("question_count"),
                    "relationship_count": ctx.get("relationship_count"),
                    "warnings_count": ctx.get("warnings_count"),
                    "bundle_file_count": ctx.get("bundle_file_count"),
                }
            ],
            recommended_actions=_recommended_actions(ctx),
            domain_payload={
                "query_kind": query_kind,
                "module_context": ctx,
            },
        )
