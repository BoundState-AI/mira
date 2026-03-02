#!/usr/bin/env python3
"""
Sonnet/Haiku/local response formatting stage for temporary BSMH path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List

from data_laundering.bedrock_client import LLMClient
from mira.providers.llm_provider import complete as llm_complete, resolve_model

from .models import RuleDecisionPacket

LOGGER = logging.getLogger(__name__)

_FORMATTER_SYSTEM_PROMPT = """You are a senior NASA Materials & Processes engineer writing assessment responses.
Given a deterministic decision packet, write a concise engineering assessment.

STRUCTURE (in this order):
1. First line MUST be exactly: VERDICT_EXACT: <decision.verdict>
2. One-sentence engineering answer: state the recommendation a working engineer needs.
3. Material-by-material summary: evidence strength, test volume, MUA heritage, key caveats.
4. Limitations and next steps (if any).

MANDATORY RULES:
- Treat decision.verdict and decision.confidence_pct as authoritative. Never override them.
- Associated materials are supplementary context only; never let them change the verdict.
- Write as a materials engineer, not as software reporting its internals.
- Front-load the engineering answer. Lead with what the engineer should do, not how the system computed it.
- If `bok_evidence_top5` is present, cite 1-2 BoK sources by document name and page as supporting literature.
- BoK evidence supports context only; it does not override the deterministic verdict.

LINKAGE GAP HANDLING:
- When a material has linkage_gap=true, it means substantial MUA heritage exists but MAPTIS test records are sparse.
- This is a database coverage gap, NOT an untested material.
- Say: "MAPTIS-linked test documentation is limited; however, [N] MUA precedents demonstrate established use."
- NEVER say a linkage-gap material "requires additional qualification testing" -- it is already in service.

WHEN SCORE AND VERDICT DIVERGE:
- A material can have a high evidence score (strong test history overall) but a CONDITIONAL verdict
  (missing environment-specific test data). When this happens, explain WHY:
  "Strong overall test documentation but no hydrogen-specific test records limits the verdict under
  conservative hydrogen service policy."

PROHIBITED -- never use these in the response:
- "signal" or "compatibility signal" (say "test data" or "test records")
- "determination set" (list materials naturally in prose)
- Raw decimal scores like "0.618" or "0.81" (use evidence_strength values: "strong", "moderate", "limited")
- "score" as a noun (say "evidence strength" or "confidence")
- material_key numbers in prose (keep them in metadata only)
- "evidence volume is below minimum threshold" (say how many records exist and how many are recommended)
- "safety context" (say "hydrogen service" or "oxygen service" directly)

GOOD EXAMPLE (hydrogen comparison):
"VERDICT_EXACT: CONDITIONAL

Both 316L and Inconel 625 are suitable for hydrogen service at -423 F, but Inconel 625 has stronger
direct evidence. Inconel 625 bar stock carries hydrogen compatibility test data with 27 MUA precedents
across NASA programs -- strong evidence for cryogenic hydrogen use. 316L has extensive flight heritage
(114 MUA precedents) but limited MAPTIS-linked hydrogen test documentation; its suitability is
well-established in practice. For new designs, Inconel 625 is the lower-risk selection; for heritage
systems using 316L, the MUA record supports continued use.

Supporting literature: Sandia SAND2012-7321 (p.267) confirms nickel alloy performance in cryogenic
hydrogen environments. Overall confidence: 67%."

BAD EXAMPLE (do NOT write like this):
"VERDICT_EXACT: CONDITIONAL
Determination set used: INCONEL 625 BAR (60965), ...
Material 60965 shows dedicated hydrogen/fluid compatibility signal present with score 0.618.
Material 60448 has no dedicated hydrogen signal, resulting in CONDITIONAL verdict (score 0.468).
Safety context 'hydrogen' has limited dedicated evidence rows."

Keep response compact: 150-250 words. Never invent evidence.
"""


def _packet_for_prompt(
    query: str,
    decision: RuleDecisionPacket,
    materials: List[Dict[str, Any]],
    primary_materials: List[Dict[str, Any]],
    associated_materials: List[Dict[str, Any]],
    bok_evidence: List[Dict[str, Any]],
    requested_materials: List[str],
    missing_requested_materials: List[str],
) -> Dict[str, Any]:
    def _top(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        output: List[Dict[str, Any]] = []
        for m in rows[:5]:
            output.append(
                {
                    "designation": m.get("designation"),
                    "total_tests": m.get("total_tests"),
                    "mua_count": m.get("mua_count"),
                    "oxygen_compatible": m.get("oxygen_compatible"),
                    "oxygen_rating": m.get("oxygen_rating"),
                    "latest_test_year": m.get("latest_test_year"),
                }
            )
        return output

    # Build per-material summaries with new fields for the formatter.
    material_summaries = []
    for m in decision.materials[:10]:
        material_summaries.append(
            {
                "designation": m.material_name,
                "verdict": m.verdict,
                "evidence_strength": m.evidence_strength,
                "linkage_gap": m.linkage_gap,
                "score_pct": round(m.score * 100),
                "oxygen_rating": m.oxygen_rating,
                "hydrogen_test_data": m.hydrogen_signal_present,
                "warnings": m.warnings,
            }
        )

    return {
        "query": query,
        "decision": {
            "verdict": decision.verdict,
            "confidence_pct": round(decision.confidence * 100),
            "aggregation_scope": decision.aggregation_scope,
            "primary_material_count": decision.primary_material_count,
            "associated_material_count": decision.associated_material_count,
            "bok_context_used": decision.bok_context_used,
            "bok_evidence_count": decision.bok_evidence_count,
            "bok_sources": decision.bok_sources,
            "standards_category": decision.standards_category,
            "evidence_gaps": decision.evidence_gaps,
        },
        "material_assessments": material_summaries,
        "primary_materials_top5": _top(primary_materials),
        "associated_materials_top5": _top(associated_materials),
        "bok_evidence_top5": bok_evidence[:5],
        "requested_materials": requested_materials,
        "missing_requested_materials": missing_requested_materials,
    }


def _template_response(
    query: str,
    decision: RuleDecisionPacket,
    missing_requested_materials: List[str],
) -> str:
    lines = [
        f"VERDICT_EXACT: {decision.verdict}",
        "",
        f"Query: {query}",
        f"Overall confidence: {decision.confidence:.0%}",
    ]
    if missing_requested_materials:
        lines.append(
            "Requested material(s) not found in MAPTIS evidence: "
            + ", ".join(missing_requested_materials)
        )
    if decision.standards_category:
        lines.append(f"Standards category: {decision.standards_category}")
    if decision.bok_context_used:
        lines.append(
            "Supporting literature: "
            f"{decision.bok_evidence_count} section(s)"
            + (
                f" from {', '.join(decision.bok_sources[:3])}"
                if decision.bok_sources
                else ""
            )
        )
    if decision.materials:
        lines.append("")
        for material in decision.materials[:5]:
            linkage_note = " [database linkage gap]" if material.linkage_gap else ""
            lines.append(
                f"- {material.material_name}: {material.verdict} "
                f"({material.evidence_strength} evidence{linkage_note})"
            )
            for warning in material.warnings[:1]:
                lines.append(f"  * {warning}")
    if decision.evidence_gaps:
        lines.append("")
        for gap in decision.evidence_gaps:
            lines.append(f"Note: {gap}")
    return "\n".join(lines)


def _prepend_missing_notice(answer: str, missing_requested_materials: List[str]) -> str:
    if not missing_requested_materials:
        return answer
    notice = (
        "Requested material(s) not found in MAPTIS evidence: "
        + ", ".join(missing_requested_materials)
        + "."
    )
    existing = answer.lower()
    if "not found in maptis evidence" in existing:
        return answer
    return f"{notice}\n\n{answer}"


def _extract_reported_verdict(text: str) -> str | None:
    match = re.search(
        r"\bVERDICT_EXACT\s*:\s*(COMPATIBLE|INCOMPATIBLE|CONDITIONAL|INSUFFICIENT[_ ]DATA)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).upper().replace(" ", "_")
    return "INSUFFICIENT_DATA" if value == "INSUFFICIENT_DATA" else value


def _apply_term_corrections(text: str, corrections: dict[str, str]) -> str:
    """
    Case-insensitive literal string replacement. No regex.

    Applies longest-match-first to avoid partial substitution.
    This function is pack-portable: corrections dict can be loaded
    from pack config.yaml term_corrections section.
    """
    # Sort by length descending so longer patterns match before substrings.
    sorted_corrections = sorted(corrections.items(), key=lambda kv: len(kv[0]), reverse=True)
    for src, dst in sorted_corrections:
        # Case-insensitive find-and-replace without regex.
        src_lower = src.lower()
        result_parts: list[str] = []
        remaining = text
        while remaining:
            idx = remaining.lower().find(src_lower)
            if idx == -1:
                result_parts.append(remaining)
                break
            result_parts.append(remaining[:idx])
            result_parts.append(dst)
            remaining = remaining[idx + len(src):]
        text = "".join(result_parts)
    return text


def _finalize_answer(
    *,
    answer: str,
    query: str,
    decision: RuleDecisionPacket,
    missing_requested_materials: List[str],
) -> str:
    reported = _extract_reported_verdict(answer)
    if reported and reported != decision.verdict:
        raise RuntimeError(
            f"Sonnet formatter verdict mismatch: {reported} != {decision.verdict}"
        )

    text = _prepend_missing_notice(answer, missing_requested_materials)

    # --- Jargon cleanup (pack-portable) ---
    # These are literal term replacements, not regex patterns.
    # For domain packs, this dict moves into pack config.yaml under term_corrections.
    _TERM_CORRECTIONS = {
        "dedicated hydrogen/fluid compatibility signal": "hydrogen compatibility test data",
        "hydrogen/fluid compatibility signal": "hydrogen compatibility test data",
        "dedicated hydrogen signal": "direct hydrogen test data",
        "compatibility signal": "compatibility test data",
        "signal present": "test data on record",
        "no dedicated hydrogen signal": "no direct hydrogen test data",
        "evidence volume is below minimum threshold": "limited test data available",
        "safety context 'hydrogen' has limited dedicated evidence rows": (
            "limited dedicated test evidence for hydrogen service conditions"
        ),
        "safety context 'oxygen' has limited dedicated evidence rows": (
            "limited dedicated test evidence for oxygen service conditions"
        ),
        "determination set used:": "Materials assessed:",
        "deterministic confidence:": "Overall confidence:",
        "aggregation scope:": "Assessment scope:",
    }
    text = _apply_term_corrections(text, _TERM_CORRECTIONS)

    # Safety net: strip any material_key references that leak through despite
    # not being included in the formatter payload. Belt-and-suspenders only.
    text = re.sub(r"\s*\(material_key:\s*\d+\)", "", text)
    text = re.sub(r"\s*\(\d{5,6}\)", "", text)
    if "VERDICT_EXACT:" not in text:
        text = f"VERDICT_EXACT: {decision.verdict}\n\n{text}"
    return text


async def format_decision_local(
    *,
    query: str,
    decision: RuleDecisionPacket,
    materials: List[Dict[str, Any]],
    primary_materials: List[Dict[str, Any]],
    associated_materials: List[Dict[str, Any]],
    bok_evidence: List[Dict[str, Any]],
    requested_materials: List[str],
    missing_requested_materials: List[str],
) -> str:
    """
    Format deterministic decision output using local LLM first, template fallback.
    """

    payload = _packet_for_prompt(
        query,
        decision,
        materials,
        primary_materials,
        associated_materials,
        bok_evidence,
        requested_materials=requested_materials,
        missing_requested_materials=missing_requested_materials,
    )
    prompt = json.dumps(payload, indent=2)

    base_url = os.environ.get("BSMH_HAIKU_BASE_URL", os.environ.get("LLM_BASE_URL", "http://localhost:11434"))
    api_format = os.environ.get("BSMH_HAIKU_API_FORMAT", os.environ.get("LLM_API_FORMAT", "ollama"))
    model = os.environ.get("BSMH_HAIKU_MODEL", os.environ.get("DL_PRESENTER_MODEL", "llama3.1:8b"))
    max_tokens = int(os.environ.get("BSMH_HAIKU_MAX_TOKENS", "900"))

    client = LLMClient(base_url=base_url, api_format=api_format)
    try:
        response = await client.invoke_local(
            prompt=prompt,
            system=_FORMATTER_SYSTEM_PROMPT,
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        text = (response.text or "").strip()
        if text:
            return _finalize_answer(
                answer=text,
                query=query,
                decision=decision,
                missing_requested_materials=missing_requested_materials,
            )
        LOGGER.warning("[BSMH] Formatter returned empty text; using template fallback")
    except Exception as exc:
        LOGGER.warning("[BSMH] Formatter local-LLM call failed; using template fallback: %s", exc)
    finally:
        await client.close()

    return _template_response(query, decision, missing_requested_materials)


async def format_decision_haiku(
    *,
    query: str,
    decision: RuleDecisionPacket,
    materials: List[Dict[str, Any]],
    primary_materials: List[Dict[str, Any]],
    associated_materials: List[Dict[str, Any]],
    bok_evidence: List[Dict[str, Any]],
    requested_materials: List[str],
    missing_requested_materials: List[str],
) -> str:
    """
    Format deterministic decision output using Anthropic Haiku, template fallback.
    """

    payload = _packet_for_prompt(
        query,
        decision,
        materials,
        primary_materials,
        associated_materials,
        bok_evidence,
        requested_materials=requested_materials,
        missing_requested_materials=missing_requested_materials,
    )
    user_message = json.dumps(payload, indent=2)

    use_bedrock = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
    bedrock_region = os.environ.get("AWS_REGION", os.environ.get("BEDROCK_REGION", "us-east-1"))
    model_bedrock = os.environ.get(
        "BSMH_HAIKU_BEDROCK_MODEL",
        resolve_model("haiku"),
    )
    model_direct = os.environ.get(
        "BSMH_HAIKU_DIRECT_MODEL",
        resolve_model("haiku"),
    )
    max_tokens = int(os.environ.get("BSMH_HAIKU_MAX_TOKENS", "900"))

    def _call_haiku() -> str:
        try:
            model = model_bedrock if use_bedrock else model_direct
            response = llm_complete(
                system=_FORMATTER_SYSTEM_PROMPT,
                user=user_message,
                model=model,
                max_tokens=max_tokens,
                temperature=0.0,
                provider="bedrock-converse" if use_bedrock else None,
            )
            return response.text.strip()
        except Exception as exc:
            LOGGER.warning("[BSMH] Haiku formatter call failed; using template fallback: %s", exc)
            return ""

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _call_haiku)
    if text:
        return _finalize_answer(
            answer=text,
            query=query,
            decision=decision,
            missing_requested_materials=missing_requested_materials,
        )
    return _template_response(query, decision, missing_requested_materials)


async def format_decision_sonnet(
    *,
    query: str,
    decision: RuleDecisionPacket,
    materials: List[Dict[str, Any]],
    primary_materials: List[Dict[str, Any]],
    associated_materials: List[Dict[str, Any]],
    bok_evidence: List[Dict[str, Any]],
    requested_materials: List[str],
    missing_requested_materials: List[str],
) -> str:
    """
    Format deterministic decision output using Anthropic Sonnet, template fallback.
    """

    payload = _packet_for_prompt(
        query,
        decision,
        materials,
        primary_materials,
        associated_materials,
        bok_evidence,
        requested_materials=requested_materials,
        missing_requested_materials=missing_requested_materials,
    )
    user_message = json.dumps(payload, indent=2)

    use_bedrock = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
    model_bedrock = os.environ.get(
        "BSMH_SONNET_BEDROCK_MODEL",
        resolve_model("sonnet"),
    )
    model_direct = os.environ.get(
        "BSMH_SONNET_DIRECT_MODEL",
        resolve_model("sonnet"),
    )
    max_tokens = int(os.environ.get("BSMH_SONNET_MAX_TOKENS", "1200"))

    def _call_sonnet() -> str:
        model = model_bedrock if use_bedrock else model_direct
        response = llm_complete(
            system=_FORMATTER_SYSTEM_PROMPT,
            user=user_message,
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            provider="bedrock-converse" if use_bedrock else None,
        )
        text = response.text.strip()
        if not text:
            raise RuntimeError("Sonnet formatter returned empty response.")
        return text

    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(None, _call_sonnet)
    except Exception as exc:
        raise RuntimeError(f"Sonnet formatter failed: {exc}") from exc
    return _finalize_answer(
        answer=text,
        query=query,
        decision=decision,
        missing_requested_materials=missing_requested_materials,
    )


async def format_decision(
    *,
    query: str,
    decision: RuleDecisionPacket,
    materials: List[Dict[str, Any]],
    primary_materials: List[Dict[str, Any]],
    associated_materials: List[Dict[str, Any]],
    bok_evidence: List[Dict[str, Any]],
    requested_materials: List[str],
    missing_requested_materials: List[str],
    mode: str = "sonnet",
) -> str:
    """
    Backward-compatible wrapper returning a single answer by requested mode.
    """

    if mode == "sonnet":
        return await format_decision_sonnet(
            query=query,
            decision=decision,
            materials=materials,
            primary_materials=primary_materials,
            associated_materials=associated_materials,
            bok_evidence=bok_evidence,
            requested_materials=requested_materials,
            missing_requested_materials=missing_requested_materials,
        )
    if mode == "haiku":
        return await format_decision_haiku(
            query=query,
            decision=decision,
            materials=materials,
            primary_materials=primary_materials,
            associated_materials=associated_materials,
            bok_evidence=bok_evidence,
            requested_materials=requested_materials,
            missing_requested_materials=missing_requested_materials,
        )
    return await format_decision_local(
        query=query,
        decision=decision,
        materials=materials,
        primary_materials=primary_materials,
        associated_materials=associated_materials,
        bok_evidence=bok_evidence,
        requested_materials=requested_materials,
        missing_requested_materials=missing_requested_materials,
    )


# =============================================================================
# Fracture Control Response Formatter
# =============================================================================

_FC_FORMATTER_SYSTEM_PROMPT = """You are a senior NASA structural engineer writing fracture control assessments.
Given a deterministic fracture classification result, write a concise engineering response.

STRUCTURE:
1. First line MUST be exactly: FC_VERDICT: <decision.verdict>
2. One-sentence classification: state the part classification and what it means.
3. Applicable FCRs: list fracture control requirements that apply.
4. NDE requirements: what inspection is required (or exempted and why).
5. Required documentation: what deliverables are needed (see DOCUMENTATION below).
6. If NEEDS_CLARIFICATION: list exactly what information is needed and why.

DOCUMENTATION GUIDANCE (per 5019A Section 5):
Based on the part classification, specify which deliverables are required:
- Fracture-Critical parts: Fracture Control Plan (FCP), Fracture Control Summary Report (FCSR),
  detailed damage tolerance or safe-life analysis, and flight rationale for any deviations.
- Non-Fracture-Critical parts: Classification rationale documenting why the part does not meet
  fracture-critical criteria. If exempt per 5019A Section 4.2, state the exemption basis.
- Low-Risk Fracture parts: Limited analysis package per FCR requirements; FCSR entry required
  but full damage tolerance analysis is not.
- Legacy/Heritage parts: Legacy Part Analysis if the part predates current 5019A revision.
  Reference prior FCSR documentation.

MANDATORY RULES:
- ONLY cite sections/figures that appear in the classification packet's citations list.
  If no citations are provided in the packet, reference "NASA-STD-5019A Figure 2" as the
  classification basis and do not fabricate specific section numbers.
- If center-specific overrides applied, note which center and what changed.
- Never override the deterministic classification — it is authoritative.
- Write as a structural engineer, not as software reporting its internals.
- If verdict is NEEDS_CLARIFICATION, be specific about what fields are missing
  and explain why each is needed for fracture classification.
- Response length: 100-300 words for CLASSIFIED verdicts, 50-100 for NEEDS_CLARIFICATION.
  Complex cases (center overrides + multiple FCRs + NDE requirements) may need the full 300.

PROHIBITED:
- "safety context" (say "fracture control" directly)
- Raw internal field names (translate to engineering language)
- Mentioning rule codes or priority orders
- Speculating about classification when data is missing
- Fabricating 5019A section/figure references not present in the packet
"""


def _fc_template_response(decision) -> str:
    """Template fallback when Sonnet is unavailable for fracture formatting."""
    from .models import FractureDecisionPacket

    if not isinstance(decision, FractureDecisionPacket):
        return "FC_VERDICT: ERROR\n\nUnable to process fracture classification."

    if decision.verdict == "NEEDS_CLARIFICATION":
        fields = decision.classification.clarify_fields if decision.classification else []
        field_list = ", ".join(fields) if fields else "unknown"
        return (
            f"FC_VERDICT: NEEDS_CLARIFICATION\n\n"
            f"Cannot classify this part without additional information.\n"
            f"Required fields: {field_list}\n\n"
            f"Please provide these details for fracture control classification "
            f"per NASA-STD-5019A Section 6."
        )

    if decision.verdict == "CLASSIFIED" and decision.classification:
        cls = decision.classification
        fcrs = ", ".join(cls.fcr_set) if cls.fcr_set else "None"
        nde = ", ".join(cls.nde_methods) if cls.nde_methods else "None required"
        return (
            f"FC_VERDICT: CLASSIFIED\n\n"
            f"Part classified as: {cls.part_class} per NASA-STD-5019A Figure 2.\n\n"
            f"Applicable FCRs: {fcrs}\n"
            f"NDE required: {'Yes' if cls.nde_required else 'No'}\n"
            f"NDE methods: {nde}\n\n"
            f"Classification confidence: {cls.classification_confidence:.0%}"
        )

    return f"FC_VERDICT: {decision.verdict}\n\nUnable to classify part. Review required."


async def format_fracture_decision_sonnet(
    *,
    query: str,
    decision,
) -> str:
    """Format fracture classification using Sonnet, with template fallback."""
    from .models import FractureDecisionPacket

    if not isinstance(decision, FractureDecisionPacket):
        return _fc_template_response(decision)

    payload = {
        "original_query": query,
        "verdict": decision.verdict,
        "classification": decision.classification.model_dump(mode="json") if decision.classification else None,
        "context_provided": decision.context_provided.model_dump(mode="json"),
        "citations": [c.model_dump(mode="json") for c in decision.citations],
        "derived_values": decision.derived_values,
        "warnings": decision.warnings,
        "evidence_gaps": decision.evidence_gaps,
        "rules_applied": decision.rules_applied,
    }
    user_message = json.dumps(payload, indent=2)

    use_bedrock = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
    model_bedrock = os.environ.get(
        "BSMH_SONNET_BEDROCK_MODEL",
        resolve_model("sonnet"),
    )
    model_direct = os.environ.get("BSMH_SONNET_DIRECT_MODEL", resolve_model("sonnet"))
    max_tokens = int(os.environ.get("BSMH_SONNET_MAX_TOKENS", "1200"))

    def _call_sonnet() -> str:
        model = model_bedrock if use_bedrock else model_direct
        response = llm_complete(
            system=_FC_FORMATTER_SYSTEM_PROMPT,
            user=user_message,
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            provider="bedrock-converse" if use_bedrock else None,
        )
        return response.text.strip()

    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(None, _call_sonnet)
        if text:
            return text
    except Exception as exc:
        LOGGER.warning("[FC] Sonnet formatter failed; using template: %s", exc)

    return _fc_template_response(decision)
