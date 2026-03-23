"""
Module-scoped chat adapter for TOCR Review.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

_GUIDANCE_PATH = Path(__file__).resolve().parents[3] / "sentinel" / "tocr" / "data" / "guidance.json"
_AUTHORITY = [
    "TOCR Review page state",
    "TOCR guidance pack",
    "TOCR compliance report",
]


def _module_context(session_context: dict[str, Any]) -> dict[str, Any]:
    context = session_context.get("module_context") or {}
    return context if isinstance(context, dict) else {}


@lru_cache(maxsize=1)
def _load_guidance_pack() -> dict[str, Any]:
    return json.loads(_GUIDANCE_PATH.read_text(encoding="utf-8"))


def _guidance_entries() -> dict[str, dict[str, str]]:
    raw = _load_guidance_pack()
    entries = raw.get("entries", {})
    return entries if isinstance(entries, dict) else {}


def _lookup_guidance(rule_ids: list[str]) -> list[tuple[str, dict[str, str]]]:
    entries = _guidance_entries()
    hits: list[tuple[str, dict[str, str]]] = []
    for rule_id in rule_ids:
        entry = entries.get(rule_id)
        if isinstance(entry, dict):
            hits.append((rule_id, entry))
    return hits[:3]


def _search_guidance(text: str) -> list[tuple[str, dict[str, str]]]:
    query = (text or "").lower()
    hits: list[tuple[int, str, dict[str, str]]] = []
    for rule_id, entry in _guidance_entries().items():
        haystack = " ".join(
            str(entry.get(field, ""))
            for field in ("what_it_means", "why_it_matters", "what_to_do", "who_needs_to_act")
        ).lower()
        score = sum(1 for token in query.split() if len(token) > 3 and token in haystack)
        if score > 0:
            hits.append((score, rule_id, entry))
    hits.sort(key=lambda item: (-item[0], item[1]))
    return [(rule_id, entry) for _, rule_id, entry in hits[:3]]


def _guidance_lines(hits: list[tuple[str, dict[str, str]]]) -> list[str]:
    if not hits:
        return []
    lines = ["Relevant TOCR guidance:"]
    for rule_id, entry in hits:
        lines.append(f"- {rule_id}: {entry.get('what_it_means', '').strip()} [{rule_id}]")
    return lines


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
            "what is tocr",
            "what's tocr",
            "what is task order compliance review",
            "what does this page do",
            "what does this module do",
        )
    ):
        return "definition"
    if any(token in query for token in ("start", "begin", "set up", "setup", "how do i use", "how do i start")):
        return "getting_started"
    if any(token in query for token in ("next", "what should", "what do i do next", "next step")):
        return "next_step"
    if any(token in query for token in ("scan", "review", "difference", "compare")):
        return "workflow_mode"
    if any(token in query for token in ("finding", "rule", "verdict", "score")):
        return "findings"
    if any(token in query for token in ("remediation", "fix", "what do i fix", "who needs to act")):
        return "remediation"
    if any(token in query for token in ("parser", "docx", "pdf", "atoms", "essca")):
        return "parser"
    return "summary"


def _recommended_actions(ctx: dict[str, Any]) -> list[str]:
    mode = str(ctx.get("mode") or "scan").strip()
    has_result = bool(ctx.get("has_result"))
    findings_count = _to_int(ctx.get("findings_count")) or 0
    remediation_count = _to_int(ctx.get("remediation_count")) or 0
    if not has_result:
        return [
            f"Choose {mode} mode, supply the required document file(s), then run TOCR.",
            "Set the agency, vehicle, policy pack, and clause context before you trust the review output.",
        ]
    actions: list[str] = []
    if findings_count > 0:
        actions.append(f"Work the {findings_count} finding(s) before treating the task order as clean.")
    if remediation_count > 0:
        actions.append(f"Use the {remediation_count} remediation step(s) as the action list for the task lead and contracts team.")
    actions.append("Check the relevant rule guidance before you rewrite the task order language.")
    return actions


def _context_lines(query_kind: str, raw_query: str, ctx: dict[str, Any], hits: list[tuple[str, dict[str, str]]]) -> list[str]:
    lines: list[str] = []
    mode = str(ctx.get("mode") or "scan").strip()
    has_result = bool(ctx.get("has_result"))
    findings_count = _to_int(ctx.get("findings_count")) or 0
    remediation_count = _to_int(ctx.get("remediation_count")) or 0
    verdict = str(ctx.get("verdict") or "").strip()
    raw_score = ctx.get("raw_score")
    rules_fired = _to_int(ctx.get("rules_fired")) or 0
    parser_summary = str(ctx.get("parser_summary") or "").strip()

    if query_kind == "definition":
        return [
            "TOCR is the Task Order Compliance Review workflow for reviewing one task order or comparing prior versus proposed revisions.",
            "It checks for undisclosed scope, funding gaps, QMS misses, parser issues, and contract-review findings, then produces plain-English remediation steps.",
        ]

    if query_kind == "getting_started":
        return [
            "You start TOCR by choosing the review mode and loading the right task order documents:",
            "1. Use Standalone Scan for one task order in isolation, or Revision Review when you need prior-versus-proposed comparison.",
            "2. Set agency, vehicle, policy pack, clauses, and revision status context.",
            "3. Pick parser hints only when auto-detect is wrong or you already know the source format.",
            "4. Run TOCR, then work findings and remediation from the generated report.",
        ]

    if has_result:
        lines.append(
            f"The current TOCR result is in {mode} mode with verdict {verdict or 'UNSCORED'}, score {raw_score if raw_score is not None else 'n/a'}, and {findings_count} finding(s)."
        )
        if parser_summary:
            lines.append(f"Parsed document context: {parser_summary}.")
    else:
        lines.append(f"The TOCR page is currently set to {mode} mode and does not have a completed report yet.")

    if query_kind == "next_step":
        lines.append("Best next steps:")
        lines.extend(f"- {action}" for action in _recommended_actions(ctx))
    elif query_kind == "workflow_mode":
        lines.append(
            "Standalone scan evaluates one document in isolation. Revision review compares prior versus proposed revisions and looks for undisclosed changes."
        )
    elif query_kind == "findings":
        lines.append(f"The current report fired {rules_fired} rule(s) and surfaced {findings_count} finding(s).")
    elif query_kind == "remediation":
        lines.append(f"The current report includes {remediation_count} remediation step(s).")
    elif query_kind == "parser":
        if parser_summary:
            lines.append(f"The current parser summary is: {parser_summary}.")
        else:
            lines.append("No parser output is available until TOCR has processed a document.")
    else:
        lines.append(
            f"Your question was: {raw_query.strip() or 'TOCR summary'}. This chat is grounded only in the active TOCR page state and guidance pack."
        )
    lines.extend(_guidance_lines(hits))
    return lines


class TOCRAdapter(EngineAdapter):
    engine_id: str = "tocr"
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
        active_rule_ids = [
            str(rule_id).strip()
            for rule_id in (ctx.get("active_rule_ids") or [])
            if str(rule_id).strip()
        ]
        hits = _lookup_guidance(active_rule_ids) if active_rule_ids else _search_guidance(raw_query)

        return self.wrap_envelope(
            status=Status.PASS,
            response_text="\n".join(_context_lines(query_kind, raw_query, ctx, hits)),
            authority_basis=_AUTHORITY,
            citations=[rule_id for rule_id, _ in hits],
            evidence=[
                {
                    "mode": ctx.get("mode"),
                    "agency": ctx.get("agency"),
                    "vehicle": ctx.get("vehicle"),
                    "policy_pack": ctx.get("policy_pack"),
                    "has_result": ctx.get("has_result"),
                    "verdict": ctx.get("verdict"),
                    "raw_score": ctx.get("raw_score"),
                    "findings_count": ctx.get("findings_count"),
                    "remediation_count": ctx.get("remediation_count"),
                    "rules_fired": ctx.get("rules_fired"),
                    "active_rule_ids": active_rule_ids,
                }
            ],
            recommended_actions=_recommended_actions(ctx),
            domain_payload={
                "query_kind": query_kind,
                "module_context": ctx,
                "guidance_hits": [rule_id for rule_id, _ in hits],
            },
        )
