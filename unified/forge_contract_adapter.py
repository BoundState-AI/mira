from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from unified._compat import ensure_external_paths
from unified.discovery.capabilities import UnifiedCapabilities
from unified.schema import ICEvidenceItem, QueryResult

ensure_external_paths()

from forge_claude.contracts.chat_v2 import (  # type: ignore
    AnswerStatus,
    CapabilityFamily,
    ChatResponseV2,
    Citation,
    CompileStatus,
    WorkspaceCapabilitiesResponse,
    WorkspaceSummary,
)


_INTENT_TO_CAPABILITY: dict[str, dict[str, Any]] = {
    "material_lookup": {
        "key": "material_lookup",
        "label": "Material Lookup",
        "description": "Find material requirements, entities, and source-backed references across the workspace.",
        "samples": [
            "What does this workspace say about titanium requirements?",
            "Find the source material references for Inconel 718.",
        ],
    },
    "property_comparison": {
        "key": "property_comparison",
        "label": "Property Comparisons",
        "description": "Compare properties, records, and measurements across structured sources.",
        "samples": [
            "Compare the properties recorded for titanium and inconel.",
            "Which records show the strongest material values?",
        ],
    },
    "compatibility_check": {
        "key": "compatibility_check",
        "label": "Compatibility Checks",
        "description": "Evaluate compatibility and fit across document and database evidence.",
        "samples": [
            "What evidence supports compatibility for this material and environment?",
            "Which sources discuss compatibility concerns for this system?",
        ],
    },
    "compliance_check": {
        "key": "compliance_check",
        "label": "Compliance Guidance",
        "description": "Surface requirement-style evidence, standards references, and conformance guidance.",
        "samples": [
            "What standards or requirements apply here?",
            "Which cited sources define acceptance or test obligations?",
        ],
    },
    "failure_prediction": {
        "key": "failure_prediction",
        "label": "Failure Signals",
        "description": "Highlight failure-related evidence, risk factors, and warning signals in the workspace.",
        "samples": [
            "What failure risks appear in the compiled sources?",
            "Which records mention corrosion, fracture, or degradation?",
        ],
    },
    "process_guidance": {
        "key": "process_guidance",
        "label": "Process Guidance",
        "description": "Summarize process steps, handling guidance, and execution constraints from the workspace.",
        "samples": [
            "What process guidance does this workspace contain?",
            "What handling or workflow requirements are cited here?",
        ],
    },
    "substitution_analysis": {
        "key": "substitution_analysis",
        "label": "Substitution Analysis",
        "description": "Support source-backed questions about alternatives, substitutions, and tradeoff evidence.",
        "samples": [
            "What evidence exists for acceptable substitutions?",
            "Which sources compare replacement options or alternatives?",
        ],
    },
    "general_query": {
        "key": "general_query",
        "label": "General Source Search",
        "description": "Search the workspace broadly for cited evidence and supporting context.",
        "samples": [
            "Search this workspace for the main evidence on this topic.",
            "Show the strongest cited support available here.",
        ],
    },
}


def _database_name(db_url: str | None, source: str) -> str:
    if not db_url:
        return "documents" if source == "docs" else "workspace"
    if "///" in db_url:
        leaf = db_url.rsplit("///", 1)[-1]
        return Path(leaf).name or "workspace"
    return db_url.rsplit("/", 1)[-1] or "workspace"


def _coverage_level(intent: str, capabilities: UnifiedCapabilities) -> str:
    if intent in {"compatibility_check", "compliance_check"} and "hybrid" in capabilities.supported_sources:
        return "full"
    if intent in capabilities.supported_intents:
        return "partial" if capabilities.supported_sources == ["docs"] and intent == "property_comparison" else "full"
    return "limited"


def _question_count(intent: str, capabilities: UnifiedCapabilities) -> int:
    if intent in {"material_lookup", "property_comparison"}:
        return max(1, len(capabilities.db_tables) or len(capabilities.db_columns))
    if intent in {"compatibility_check", "compliance_check", "process_guidance"}:
        return max(1, len(capabilities.doc_ids) or len(capabilities.doc_entity_terms))
    if intent == "general_query":
        return max(1, len(capabilities.doc_ids) + len(capabilities.db_tables))
    return max(1, len(capabilities.overlap_terms) or len(capabilities.supported_sources))


def build_capability_families(capabilities: UnifiedCapabilities | dict[str, Any]) -> list[CapabilityFamily]:
    parsed = capabilities if isinstance(capabilities, UnifiedCapabilities) else UnifiedCapabilities.model_validate(capabilities)
    families: list[CapabilityFamily] = []

    for intent in parsed.supported_intents:
        meta = _INTENT_TO_CAPABILITY.get(intent)
        if meta is None:
            label = intent.replace("_", " ").title()
            meta = {
                "key": intent,
                "label": label,
                "description": f"Questions about {label.lower()} within this workspace.",
                "samples": [f"What does this workspace say about {label.lower()}?"],
            }
        families.append(
            CapabilityFamily(
                key=meta["key"],
                label=meta["label"],
                description=meta["description"],
                sample_questions=list(meta["samples"])[:5],
                question_count=_question_count(intent, parsed),
                coverage_level=_coverage_level(intent, parsed),
            )
        )

    families.sort(key=lambda family: family.question_count, reverse=True)
    return families


def build_workspace_summary(
    *,
    module_name: str,
    workspace_version: str,
    compiled_at: str,
    source: str,
    capabilities: UnifiedCapabilities | dict[str, Any],
    canonical_record_count: int,
    materialized_db_url: str | None,
    status: str,
) -> WorkspaceSummary:
    parsed = capabilities if isinstance(capabilities, UnifiedCapabilities) else UnifiedCapabilities.model_validate(capabilities)
    families = build_capability_families(parsed)
    compile_status = CompileStatus.READY if status == "ok" else CompileStatus.FAILED
    total_questions = sum(family.question_count for family in families)
    total_reliable = sum(1 for family in families if family.coverage_level in {"full", "partial"})
    domain_parts = []
    if parsed.doc_ids:
        domain_parts.append(f"{len(parsed.doc_ids)} documents")
    if parsed.db_tables:
        domain_parts.append(f"{len(parsed.db_tables)} tables")
    if canonical_record_count:
        domain_parts.append(f"{canonical_record_count} canonical records")

    return WorkspaceSummary(
        workspace_id=module_name,
        workspace_version=workspace_version,
        compile_status=compile_status,
        compiled_at=compiled_at,
        database_name=_database_name(materialized_db_url, source),
        domain_summary=", ".join(domain_parts) if domain_parts else "Compiled intelligence workspace",
        total_questions=total_questions,
        total_reliable=total_reliable,
        capability_families=families,
    )


def build_workspace_capabilities_response(summary: WorkspaceSummary) -> WorkspaceCapabilitiesResponse:
    return WorkspaceCapabilitiesResponse(
        workspace_id=summary.workspace_id,
        workspace_version=summary.workspace_version,
        families=list(summary.capability_families),
    )


def _citation_from_evidence(item: ICEvidenceItem) -> Citation:
    title = item.source_label or item.doc_id or item.source_id
    table_name = None
    if isinstance(item.metadata, dict):
        table_name = item.metadata.get("table")
    return Citation(
        source_id=item.evidence_id,
        title=title,
        snippet=item.snippet or item.content[:240],
        table_name=table_name,
        row_ref=item.source_id,
    )


def build_chat_response(
    *,
    query_result: QueryResult,
    workspace_version: str,
    trace_id: str | None = None,
) -> ChatResponseV2:
    citations = [_citation_from_evidence(item) for item in query_result.citations[:3]]
    bouncer_verdict = str(query_result.audit.get("bouncer_verdict", "")).lower()
    if bouncer_verdict == "rejected":
        status = AnswerStatus.REJECTED
        guidance = str(query_result.audit.get("guidance") or "").strip() or None
    elif query_result.insufficient_evidence and not query_result.citations:
        status = AnswerStatus.UNSUPPORTED
        guidance = "This compiled workspace does not appear to cover that question. Try a different capability family or add more source material."
    elif query_result.insufficient_evidence:
        status = AnswerStatus.PARTIAL
        guidance = "This workspace has limited supporting evidence for that question."
    elif query_result.confidence < 0.3:
        status = AnswerStatus.PARTIAL
        guidance = "The available evidence is weak; refine the question or switch sources."
    else:
        status = AnswerStatus.OK
        guidance = None

    return ChatResponseV2(
        status=status,
        answer=query_result.answer,
        citations=citations,
        has_more_citations=len(query_result.citations) > len(citations),
        trace_id=trace_id or f"ic-{uuid4().hex[:12]}",
        workspace_version=workspace_version,
        guidance=guidance,
        latency_ms=0.0,
    )
