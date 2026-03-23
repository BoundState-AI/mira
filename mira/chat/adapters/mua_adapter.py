"""
Module-scoped chat adapter for the MUA Writer.
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

_GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "mua" / "data" / "guidance.json"
_AUTHORITY = ["MUA guidance pack", "NASA-STD-6016C", "MSFC Form 551"]
_STEP_LABELS = {
    1: "Who / What / Where",
    2: "Ratings",
    3: "Flag Review",
    4: "Rationale",
    5: "Download",
}
_FLAG_KEYWORDS = {
    "real fail": "REAL_FAIL",
    "administrative gap": "ADMIN_GAP",
    "admin gap": "ADMIN_GAP",
    "no data": "NO_DATA",
    "untested": "NO_DATA",
    "batch": "BATCH_REQUIRED",
    "corrupt": "BAD_DATA",
    "bad data": "BAD_DATA",
    "manual review": "NEEDS_REVIEW",
    "needs review": "NEEDS_REVIEW",
    "missing data": "MISSING_DATA",
    "missing maptis": "MISSING_DATA",
}
_MUA_TYPE_KEYWORDS = {
    "thin screening": "THIN_SCREENING",
    "anti-rule": "ANTI_RULE",
    "anti rule": "ANTI_RULE",
    "incomplete pass": "INCOMPLETE_PASS",
    "real problem": "REAL_PROBLEM",
    "real gap": "REAL_GAP",
    "standard": "STANDARD",
    "flag for human": "FLAG_FOR_HUMAN",
    "category i": "category_I",
    "category 1": "category_I",
    "category ii": "category_II",
    "category 2": "category_II",
}
_SCREENING_KEYWORDS = {
    "flammability": "FLAM",
    "flam": "FLAM",
    "fluid sensitivity": "FS",
    "fluid compatibility": "FS",
    "fs": "FS",
    "tox": "TOX",
    "toxity": "TOX",
    "toxicity": "TOX",
    "tvs": "TVS",
    "outgassing": "TVS",
    "thermal vacuum": "TVS",
    "scc": "SCC",
    "stress corrosion": "SCC",
    "corr": "CORR",
    "corrosion": "CORR",
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
            "what's a mua",
            "what is a mua",
            "what is this mua",
            "what does this page do",
            "what does this module do",
            "what is a material usage agreement",
            "define mua",
            "define material usage agreement",
            "explain mua",
        )
    ):
        return "definition"
    if any(token in query for token in ("start", "begin", "set up", "setup", "how do i use", "how do i write")):
        return "getting_started"
    if any(token in query for token in ("next", "what should", "where do i go", "step")):
        return "next_step"
    if any(token in query for token in ("flag", "real fail", "admin gap", "batch", "missing data", "needs review")):
        return "flags"
    if any(token in query for token in ("anti-rule", "anti rule", "incomplete pass", "real problem", "real gap", "thin screening", "category i", "category ii", "mua type")):
        return "mua_types"
    if any(token in query for token in ("rating", "flam", "tox", "tvs", "scc", "corr", "fs", "screening column")):
        return "ratings"
    if any(token in query for token in ("precedent", "exemplar", "similar case")):
        return "precedents"
    if any(token in query for token in ("confidence", "automation", "automatable", "human required")):
        return "confidence"
    if any(token in query for token in ("workflow", "form 551", "accepted", "override", "draft")):
        return "workflow"
    return "summary"


def _guidance_hits(query_kind: str, raw_query: str, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    step = _to_int(ctx.get("workflow_step")) or 1
    query = raw_query.lower()
    keys: list[str] = []
    sections: list[str] = []

    if query_kind == "definition":
        keys = ["form_551", "step1_identify_flags", "step5_classify_type"]
    elif query_kind == "getting_started":
        keys = ["material_key", "environment.fluid_medium", "known_ratings", "step1_identify_flags", "needs_input"]
    elif query_kind == "next_step":
        if _to_int(ctx.get("resolution_candidate_count")):
            keys = ["material_key", "material_name", "needs_input"]
        elif step <= 1:
            keys = ["material_key", "material_name", "environment.fluid_medium", "known_ratings"]
        elif step == 2:
            keys = ["known_ratings", "step1_identify_flags"]
        elif step == 3:
            keys = ["step2_decode_flag", "step3_screening_applicability", "step4_hazard_applies"]
        elif step == 4:
            keys = ["step5_classify_type", "step6_assign_category", "precedent_count", "form_551"]
        else:
            keys = ["form_551", "engineer_accepted", "engineer_modified"]
    elif query_kind == "flags":
        sections = ["flag_types"]
        for token, entry_id in _FLAG_KEYWORDS.items():
            if token in query:
                keys.append(entry_id)
    elif query_kind == "mua_types":
        sections = ["mua_types", "concepts"]
        for token, entry_id in _MUA_TYPE_KEYWORDS.items():
            if token in query:
                keys.append(entry_id)
    elif query_kind == "ratings":
        sections = ["screening_columns", "inputs"]
        for token, entry_id in _SCREENING_KEYWORDS.items():
            if token in query:
                keys.append(entry_id)
        if not keys:
            keys.append("known_ratings")
    elif query_kind == "precedents":
        keys = ["precedent_count", "precedent_matching", "ANTI_RULE", "REAL_GAP"]
    elif query_kind == "confidence":
        keys = ["confidence_score", "precedent_count", "engineer_override"]
    elif query_kind == "workflow":
        keys = ["needs_input", "form_551", "engineer_accepted", "engineer_modified"]
    else:
        sections = ["workflow", "classifier_steps", "mua_types", "flag_types"]

    hits = lookup_guidance_entries(_GUIDANCE_PATH, keys)
    if hits:
        return hits[:3]
    return search_guidance(_GUIDANCE_PATH, raw_query, limit=3, sections=sections)


def _recommended_actions(ctx: dict[str, Any]) -> list[str]:
    step = _to_int(ctx.get("workflow_step")) or 1
    material_ref = str(ctx.get("material_name") or ctx.get("material_key") or "the active material").strip()
    actions: list[str] = []
    if _to_int(ctx.get("resolution_candidate_count")):
        actions.append(f"Pick the correct MAPTIS code candidate for {material_ref} before you trust the classifier output.")
        actions.append("Re-run Classify after the material code is grounded.")
        return actions
    if step <= 1:
        if not str(ctx.get("material_name") or ctx.get("material_key") or "").strip():
            actions.append("Identify the material and MAPTIS code in Step 1.")
        actions.append("Finish the service medium, environment, and oxygen context so the hazard logic is grounded.")
        actions.append("Move to Step 2 and enter the MAPTIS ratings or import a MIUL row.")
        return actions
    if step == 2:
        actions.append("Enter the applicable MAPTIS ratings, then run Classify.")
        return actions
    if step == 3:
        actions.append("Review whether each flag is actually correct before accepting the MUA type.")
        human_required = _to_int(ctx.get("human_required_count")) or 0
        if human_required > 0:
            actions.append(f"Escalate the {human_required} human-required classifications instead of auto-accepting them.")
        return actions
    if step == 4:
        actions.append("Write or confirm the Form 551 rationale for each non-standard classification.")
        automatable = _to_int(ctx.get("automatable_count")) or 0
        if automatable > 0:
            actions.append(f"Approve the {automatable} automatable draft forms only after the rationale matches the service environment.")
        if (_to_int(ctx.get("human_required_count")) or 0) > 0:
            actions.append("Engineer-only items still need manual rationale and disposition review.")
        return actions
    actions.append("Download the Form 551 output and finalize any remaining reviewer actions.")
    if (_to_int(ctx.get("no_mua_needed_count")) or 0) > 0:
        actions.append("Separate STANDARD / no-MUA-needed items from the actual Form 551 package before release.")
    return actions


def _definition_response(ctx: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    hits = _guidance_hits("definition", "what is a material usage agreement", ctx)
    lines = [
        "A Material Usage Agreement (MUA) is the formal justification package used when a material has a rating gap or non-pass condition in an applicable screening category.",
        "This module is intentionally flag-first: it starts from the MAPTIS ratings, checks whether the screening and the real service hazard apply, classifies the issue type, and then turns that into Form 551 rationale or an engineer handoff.",
    ]
    return lines, hits, [
        "If you want the current page worked, ask what to do next in this MUA workflow.",
        "If you want the logic explained, ask why the current issue is an anti-rule, incomplete pass, real gap, or real problem.",
        "If you want to proceed, ground the material code and ratings before trusting the draft forms.",
    ]


def _getting_started_response(ctx: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    hits = _guidance_hits("getting_started", "how do i start this mua writer", ctx)
    lines = [
        "You can start the MUA Writer in five steps:",
        "1. Identify the material, MAPTIS code, and service environment.",
        "2. Enter the MAPTIS ratings or import a completed MIUL row.",
        "3. Run the classifier to identify the raw flags and the candidate MUA type.",
        "4. Confirm whether the screening and the actual hazard apply in this service case.",
        "5. Draft or review the Form 551 rationale, then finalize or download the forms.",
    ]
    return lines, hits, [
        "Ground the material code first so the ratings are not ambiguous.",
        "Use MIUL import if you already have the rated row and want to skip manual rating entry.",
        "Do not finalize Form 551 output until the hazard logic matches the real service environment.",
    ]


def _context_lines(query_kind: str, raw_query: str, ctx: dict[str, Any], hits: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    step = _to_int(ctx.get("workflow_step")) or 1
    step_label = str(ctx.get("workflow_step_label") or _STEP_LABELS.get(step) or f"Step {step}")
    material_ref = str(ctx.get("material_name") or ctx.get("material_key") or "the active material").strip()
    fluid = str(ctx.get("fluid_medium") or ctx.get("service_environment") or "").strip()
    if step:
        lines.append(f"The active MUA page is at Step {step}: {step_label}.")
    if material_ref and material_ref != "the active material":
        detail = f"Current material: {material_ref}"
        if fluid:
            detail = f"{detail} in {fluid}"
        lines.append(detail + ".")

    automatable = _to_int(ctx.get("automatable_count")) or 0
    human_required = _to_int(ctx.get("human_required_count")) or 0
    no_mua_needed = _to_int(ctx.get("no_mua_needed_count")) or 0
    form_count = _to_int(ctx.get("form_count")) or 0
    ratings_entered = _to_int(ctx.get("ratings_entered_count")) or 0

    if query_kind == "next_step":
        lines.append("Best next steps:")
        lines.extend(f"- {action}" for action in _recommended_actions(ctx))
    elif query_kind == "ratings":
        lines.append(
            f"The page currently has {ratings_entered} rating column(s) entered; those values are the raw evidence that drive every downstream MUA decision."
        )
    elif query_kind == "flags":
        lines.append(
            f"The current classification set has {automatable} automatable item(s), {human_required} human-required item(s), and {no_mua_needed} item(s) that do not need a formal MUA."
        )
    elif query_kind == "mua_types":
        lines.append(
            "This module does not jump straight from a bad rating to a final verdict. It first decides whether the screening applies, whether the actual hazard applies, and only then assigns the MUA type."
        )
    elif query_kind == "precedents":
        lines.append("Precedents matter most for low-confidence, context-sensitive MUA paths like ANTI_RULE and REAL_GAP.")
    elif query_kind == "confidence":
        lines.append(
            "Confidence in this module comes from the decision trace: grounded ratings, correct hazard applicability, and enough prior-use precedent where automation depends on it."
        )
    elif query_kind == "workflow":
        lines.append(f"The page currently has {form_count} draft form(s) in play.")
    else:
        lines.append(
            f"Your question was: {raw_query.strip() or 'workflow summary'}. The current page has {ratings_entered} entered rating column(s), {form_count} draft form(s), and {human_required} engineer-only item(s)."
        )

    lines.extend(format_guidance_lines(hits, heading="Relevant MUA guidance:"))
    return lines


class MUAAdapter(EngineAdapter):
    engine_id: str = "mua"
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
                response_text="\n".join(response_lines + format_guidance_lines(hits, heading="Relevant MUA guidance:")),
                authority_basis=_AUTHORITY,
                citations=[source for source in (guidance_entry_source(entry) for entry in hits) if source],
                recommended_actions=recommended_actions,
                domain_payload={"query_kind": query_kind, "guidance_only": True},
            )

        if query_kind == "getting_started":
            response_lines, hits, recommended_actions = _getting_started_response(ctx)
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="\n".join(response_lines + format_guidance_lines(hits, heading="Relevant MUA guidance:")),
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
                    "workflow_step": ctx.get("workflow_step"),
                    "workflow_step_label": ctx.get("workflow_step_label"),
                    "material_key": ctx.get("material_key"),
                    "material_name": ctx.get("material_name"),
                    "fluid_medium": ctx.get("fluid_medium"),
                    "ratings_entered_count": ctx.get("ratings_entered_count"),
                    "automatable_count": ctx.get("automatable_count"),
                    "human_required_count": ctx.get("human_required_count"),
                    "no_mua_needed_count": ctx.get("no_mua_needed_count"),
                    "form_count": ctx.get("form_count"),
                }
            ],
            recommended_actions=_recommended_actions(ctx),
            domain_payload={
                "query_kind": query_kind,
                "module_context": ctx,
                "guidance_hits": hits,
            },
        )

