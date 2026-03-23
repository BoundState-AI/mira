"""
Module-scoped chat adapter for the MIUL Builder and Drawing Tree Editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

from ._guidance_utils import (
    format_guidance_lines,
    guidance_entry_source,
    lookup_guidance_entries,
    search_guidance,
)

_GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "miul" / "data" / "guidance.json"
_AUTHORITY = ["MIUL guidance pack", "JSC 27301F", "NASA-STD-6016C", "MAPTIS database"]
_RATING_KEYWORDS = {
    "flammability": "FLAM",
    "flam": "FLAM",
    "scc": "SCC",
    "stress corrosion": "SCC",
    "corr": "CORR",
    "corrosion": "CORR",
    "tvs": "TVS",
    "outgassing": "TVS",
    "tox": "TOX",
    "toxicity": "TOX",
    "fs": "FS",
    "fluid compatibility": "FS",
}
_FLAG_KEYWORDS = {
    "missing maptis": "missing_material_code",
    "missing code": "missing_material_code",
    "missing spec": "missing_specification",
    "environment mismatch": "environment_mismatch",
    "flammability unknown": "flammability_unknown",
}


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
            "what's a miul",
            "what is a miul",
            "what is this miul",
            "what does this module do",
            "what does this page do",
            "define miul",
            "explain miul",
            "what is a material identification and usage list",
        )
    ):
        return "definition"
    if any(token in query for token in ("start", "begin", "set up", "setup", "build a miul", "how do i use")):
        return "getting_started"
    if any(token in query for token in ("next", "what should", "where do i go", "step")):
        return "next_step"
    if any(token in query for token in ("rating", "gap", "flam", "scc", "corr", "tvs", "tox", "fs")):
        return "ratings"
    if any(token in query for token in ("criticality", "mua", "formal mua", "noncritical", "critical item")):
        return "mua_routing"
    if any(token in query for token in ("tree", "drawing tree", "hierarchy", "parent", "assembly")):
        return "drawing_tree"
    if any(token in query for token in ("review", "queued", "flagged", "open items", "resolve")):
        return "review"
    if any(token in query for token in ("export", "approve", "build workbook", "enrich")):
        return "export"
    return "summary"


def _guidance_hits(query_kind: str, raw_query: str, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    query = raw_query.lower()
    keys: list[str] = []
    sections: list[str] = []
    submodule = str(ctx.get("submodule") or "").lower()
    current_stage = str(ctx.get("current_stage") or "").lower()

    if query_kind == "definition":
        keys = ["what_is_a_miul", "drawing_cross_reference", "mua_routing"]
    elif query_kind == "getting_started":
        keys = ["detail_drawing", "material_code", "environment", "criticality", "what_is_a_miul"]
    elif query_kind == "next_step":
        if submodule == "dt_editor":
            keys = ["tree_structure", "drawing_cross_reference", "material_code"]
        elif current_stage in {"", "upload"}:
            keys = ["detail_drawing", "material_code", "environment", "tree_structure"]
        elif current_stage == "extract":
            keys = ["material_code", "drawing_cross_reference", "tree_structure"]
        elif current_stage == "review":
            keys = ["material_code", "rating_gap_values", "mua_routing"]
        else:
            keys = ["criticality_codes", "mua_routing", "rating_gap_critical_mua_required"]
    elif query_kind == "ratings":
        sections = ["ratings", "verdicts"]
        for token, entry_id in _RATING_KEYWORDS.items():
            if token in query:
                keys.append(entry_id)
        if not keys:
            keys.append("rating_gap_values")
    elif query_kind == "mua_routing":
        keys = ["criticality_codes", "mua_routing", "rating_gap_critical_mua_required", "rating_gap_noncritical"]
    elif query_kind == "drawing_tree":
        keys = ["tree_structure", "drawing_cross_reference"]
    elif query_kind == "review":
        sections = ["flags", "verdicts", "concepts"]
        for token, entry_id in _FLAG_KEYWORDS.items():
            if token in query:
                keys.append(entry_id)
        if not keys:
            keys.append("material_unresolved")
    elif query_kind == "export":
        keys = ["mua_routing", "rating_gap_values", "drawing_cross_reference"]
    else:
        sections = ["concepts", "verdicts", "flags"]

    hits = lookup_guidance_entries(_GUIDANCE_PATH, keys)
    if hits:
        return hits[:3]
    return search_guidance(_GUIDANCE_PATH, raw_query, limit=3, sections=sections)


def _recommended_actions(ctx: dict[str, Any]) -> list[str]:
    submodule = str(ctx.get("submodule") or "").lower()
    current_stage = str(ctx.get("current_stage") or "").lower()
    actions: list[str] = []

    if submodule == "dt_editor":
        tree_loaded = bool(ctx.get("tree_loaded"))
        if not tree_loaded:
            actions.append("Load an existing drawing-tree JSON or extract one from a PDF first.")
            actions.append("Review the top-level drawing number before exporting the corrected tree back into MIUL.")
            return actions
        actions.append("Review the parent-child hierarchy for assembly mistakes before export.")
        actions.append("Export the corrected tree JSON, then feed it into the MIUL builder.")
        return actions

    extraction_id = str(ctx.get("extraction_id") or "").strip()
    open_review = _to_int(ctx.get("open_review_count")) or 0

    if not extraction_id and current_stage in {"", "upload"}:
        actions.append("Upload the drawing PDFs and optional drawing-tree JSON to start extraction.")
        actions.append("Set the project and environment metadata before launching the extract/build path.")
        return actions
    if current_stage == "extract":
        actions.append("Let extraction finish, then inspect the review queue instead of trying to build immediately.")
        return actions
    if current_stage == "review":
        actions.append(f"Resolve the {open_review} open review item(s) before approving the MIUL build.")
        actions.append("Fix unresolved material codes and non-A rating gaps before you move to approve/export.")
        return actions
    if current_stage == "approve":
        actions.append("Approve the reviewed extraction output, then build the workbook.")
        return actions
    if current_stage == "export":
        actions.append("Download the built workbook and run enrich only after the base MIUL looks correct.")
        return actions

    actions.append("Ground the drawing, material code, environment, and criticality fields before trusting the MIUL output.")
    return actions


def _definition_response(ctx: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    hits = _guidance_hits("definition", "what is a miul", ctx)
    lines = [
        "A MIUL is the master list that ties each hardware material back to its drawing, MAPTIS identity, ratings, and final disposition status.",
        "In practice, it is the certification bridge between the drawing tree, the material records, and the follow-on MUA path for any critical non-A rating gaps.",
    ]
    return lines, hits, [
        "If you want the active build worked, ask what to do next in this MIUL workflow.",
        "If you want the gap logic explained, ask when a rating gap becomes a formal MUA.",
        "If you want to advance the page, resolve unresolved material codes and review items first.",
    ]


def _getting_started_response(ctx: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    hits = _guidance_hits("getting_started", "how do i start a miul", ctx)
    lines = [
        "You can start the MIUL workflow in five steps:",
        "1. Upload the drawing PDFs and, if you have it, the drawing-tree JSON.",
        "2. Set the project, environment, and pressure context for the build.",
        "3. Let extraction resolve drawing-linked material entries and their MAPTIS codes.",
        "4. Review the queued items until the unresolved and low-confidence entries are closed.",
        "5. Approve the review set, build the workbook, then route critical rating gaps into MUA as needed.",
    ]
    return lines, hits, [
        "Start with the drawing set and environment context, not the export step.",
        "Use the drawing tree when you have it; hierarchy mistakes propagate into the MIUL.",
        "Do not ignore unresolved MAPTIS codes because they block every downstream rating decision.",
    ]


def _context_lines(query_kind: str, raw_query: str, ctx: dict[str, Any], hits: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    submodule = str(ctx.get("submodule") or "").lower()
    current_stage = str(ctx.get("current_stage") or "").lower()

    if submodule == "dt_editor":
        if ctx.get("tree_loaded"):
            lines.append(
                f"The drawing tree editor currently has {ctx.get('total_nodes') or 0} nodes loaded under top-level drawing {ctx.get('top_level') or 'the active tree'}."
            )
        else:
            lines.append("The drawing tree editor does not have a tree loaded yet.")
        if query_kind == "next_step":
            lines.append("Best next steps:")
            lines.extend(f"- {action}" for action in _recommended_actions(ctx))
        elif query_kind == "drawing_tree":
            lines.append("This page exists to correct hierarchy relationships before the MIUL build consumes the tree.")
        else:
            lines.append(f"Your question was: {raw_query.strip() or 'tree summary'}.")
        lines.extend(format_guidance_lines(hits, heading="Relevant MIUL guidance:"))
        return lines

    stage_label = current_stage or "upload"
    extraction_id = str(ctx.get("extraction_id") or "").strip()
    if extraction_id:
        lines.append(f"The active MIUL build is at the {stage_label} stage. Extraction {extraction_id[:8]} is the grounded page context.")
    else:
        lines.append(f"The current MIUL page is at the {stage_label} stage.")

    if query_kind == "next_step":
        lines.append("Best next steps:")
        lines.extend(f"- {action}" for action in _recommended_actions(ctx))
    elif query_kind == "review":
        lines.append(
            f"The page currently has {ctx.get('review_item_count') or 0} review item(s), {ctx.get('open_review_count') or 0} still open, and {ctx.get('auto_approved_count') or 0} auto-approved."
        )
    elif query_kind == "ratings":
        lines.append("Any non-A rating is a gap, but the consequence depends on environment and criticality.")
    elif query_kind == "mua_routing":
        lines.append("Criticality drives whether a rating gap stays in MIUL remarks or must be escalated into a formal MUA.")
    elif query_kind == "export":
        lines.append(
            f"Build complete: {bool(ctx.get('build_complete'))}. Open review items remaining: {ctx.get('open_review_count') or 0}."
        )
    else:
        lines.append(
            f"Your question was: {raw_query.strip() or 'workflow summary'}. The page currently shows {ctx.get('drawing_count') or 0} drawing file(s), {ctx.get('review_item_count') or 0} review item(s), and {ctx.get('open_review_count') or 0} unresolved review item(s)."
        )

    lines.extend(format_guidance_lines(hits, heading="Relevant MIUL guidance:"))
    return lines


class MIULAdapter(EngineAdapter):
    engine_id: str = "miul"
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

        if query_kind == "definition":
            response_lines, hits, recommended_actions = _definition_response(ctx)
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="\n".join(response_lines + format_guidance_lines(hits, heading="Relevant MIUL guidance:")),
                authority_basis=_AUTHORITY,
                citations=[source for source in (guidance_entry_source(entry) for entry in hits) if source],
                recommended_actions=recommended_actions,
                domain_payload={"query_kind": query_kind, "guidance_only": True},
            )

        if query_kind == "getting_started":
            response_lines, hits, recommended_actions = _getting_started_response(ctx)
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="\n".join(response_lines + format_guidance_lines(hits, heading="Relevant MIUL guidance:")),
                authority_basis=_AUTHORITY,
                citations=[source for source in (guidance_entry_source(entry) for entry in hits) if source],
                recommended_actions=recommended_actions,
                domain_payload={"query_kind": query_kind, "guidance_only": True},
            )

        hits = _guidance_hits(query_kind, raw_query, ctx)
        citations = [source for source in (guidance_entry_source(entry) for entry in hits) if source]
        return self.wrap_envelope(
            status=Status.PASS,
            response_text="\n".join(_context_lines(query_kind, raw_query, ctx, hits)),
            authority_basis=_AUTHORITY,
            citations=list(dict.fromkeys(citations)),
            evidence=[
                {
                    "current_stage": ctx.get("current_stage"),
                    "submodule": ctx.get("submodule"),
                    "extraction_id": ctx.get("extraction_id"),
                    "drawing_count": ctx.get("drawing_count"),
                    "review_item_count": ctx.get("review_item_count"),
                    "open_review_count": ctx.get("open_review_count"),
                    "auto_approved_count": ctx.get("auto_approved_count"),
                    "build_complete": ctx.get("build_complete"),
                    "tree_loaded": ctx.get("tree_loaded"),
                    "total_nodes": ctx.get("total_nodes"),
                }
            ],
            recommended_actions=_recommended_actions(ctx),
            domain_payload={
                "query_kind": query_kind,
                "module_context": ctx,
                "guidance_hits": hits,
            },
        )

