#!/usr/bin/env python3
"""
Module: MIRA v4 Decision Lineage API
Purpose: FastAPI router exposing the MIRA v4 decision lineage pipeline.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-032, SWE-033
Safety Critical: True

Endpoints:
    GET  /ping              Health check
    POST /query             Full decision lineage pipeline (single query)
    POST /query/batch       Batch mode with safety-critical REFUSE gate
    POST /heritage/override Engineer acknowledgment for heritage vetoes
    GET  /schema/validate   CI schema validation job

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mira.providers.llm_provider import complete as llm_complete, resolve_model
from mira.utils.json_extract import ExtractionError, extract_json

LOGGER = logging.getLogger(__name__)
router = APIRouter()

# Thread pool for blocking Bedrock calls
_executor = ThreadPoolExecutor(max_workers=4)

# Heritage table initialization flag.  Protected by _heritage_lock so
# concurrent requests don't race through table creation.
_heritage_table_checked = False
_heritage_lock = threading.Lock()


def _ensure_heritage_table_ready() -> bool:
    """Best-effort heritage DB initialization.

    The public site must stay bootable even when the heritage database has been
    intentionally purged. We therefore avoid import-time DB access and only
    attempt table creation on heritage-specific flows.
    """
    global _heritage_table_checked
    if _heritage_table_checked:
        return True

    with _heritage_lock:
        if _heritage_table_checked:
            return True

        if os.getenv("MIRA_DISABLE_HERITAGE_DB", "").strip().lower() in {"1", "true", "yes"}:
            LOGGER.info("[MIRA_V4] Heritage DB disabled; skipping table ensure.")
            return False

        try:
            from mira.api.models.heritage_db import ensure_table as _ensure_heritage_table

            _ensure_heritage_table()
            _heritage_table_checked = True
            return True
        except Exception as exc:
            LOGGER.warning("[MIRA_V4] Heritage DB unavailable; override flow disabled: %s", exc)
            return False


# =============================================================================
# Request / Response Models
# =============================================================================


class V4QueryRequest(BaseModel):
    """Request for the full MIRA v4 decision lineage pipeline."""

    query: str = Field(..., min_length=1, description="Natural language query")
    batch_mode: bool = Field(False, description="Enable batch mode safety gate")
    material_key: Optional[str] = Field(None, description="Target material identifier")
    temperature_c: Optional[float] = Field(None, description="Temperature in Celsius")
    pressure_kpa: Optional[float] = Field(None, ge=0, description="Pressure in kPa")
    o2_pct: Optional[float] = Field(None, ge=0, le=100, description="O2 concentration %")
    fluid_medium: Optional[str] = Field(None, description="Fluid medium (LOX, GOX, LH2, etc.)")
    duration_hr: Optional[float] = Field(None, ge=0, description="Exposure duration hours")
    cycles: Optional[int] = Field(None, ge=0, description="Thermal/pressure cycles")
    llm_model: Optional[str] = Field(
        None,
        description="Requested response model hint (kept for UI backward compatibility)",
    )

    model_config = {"extra": "forbid"}


class V4PenaltyDetailResponse(BaseModel):
    """Single penalty breakdown entry."""

    penalty_type: str
    penalty_value: float
    explanation: str


class V4ConfidenceResponse(BaseModel):
    """Confidence calculation result."""

    score: float
    penalties: Dict[str, float]
    penalty_details: List[V4PenaltyDetailResponse]
    gate_action: str
    safety_critical: bool
    explanation: str


class V4BatchGateResponse(BaseModel):
    """Batch safety gate result."""

    action: str
    penalty: float
    missing_fields: List[str]
    safety_context: str
    reason: str


class V4DirtyDataResponse(BaseModel):
    """Dirty data tier classification."""

    tier: str
    dirty_fraction: float
    total_records: int
    dirty_records: int
    user_message: Optional[str] = None


class V4HeritageVetoResponse(BaseModel):
    """Heritage veto check result."""

    vetoed: bool
    veto_type: Optional[str] = None
    heritage_failure_ids: List[str] = Field(default_factory=list)
    requires_acknowledgment: bool = False
    rank_penalty: float = 0.0
    envelope_match_details: Dict[str, Any] = Field(default_factory=dict)


class V4IntentDisagreementResponse(BaseModel):
    """Intent classifier disagreement record."""

    sonnet_intent: str
    heuristic_intent: str
    chosen_intent: str
    penalty_applied: float
    explanation: str


class V4MaterialResponse(BaseModel):
    """Enriched material result with test data summary."""

    material_key: Any  # int from DB
    material_code: Optional[Any] = None
    designation: str = ""
    composition: Optional[str] = None
    material_type_key: Optional[int] = None
    material_type_name: Optional[str] = None
    use_temp_min_f: Optional[float] = None
    use_temp_max_f: Optional[float] = None
    use_temp_min_c: Optional[float] = None
    use_temp_max_c: Optional[float] = None
    test_counts: Dict[str, int] = Field(default_factory=dict)
    total_tests: int = 0
    latest_test_year: Optional[int] = None
    mua_count: int = 0
    has_mua_precedent: bool = False
    oxygen_compatible: bool = False
    similarity_score: Optional[float] = None


class V4QueryResponse(BaseModel):
    """Full decision lineage response."""

    lineage_id: str
    query_hash: str
    snapshot_hash: str
    confidence: V4ConfidenceResponse
    gate_action: str
    batch_gate: Optional[V4BatchGateResponse] = None
    dirty_data: Optional[V4DirtyDataResponse] = None
    heritage_veto: Optional[V4HeritageVetoResponse] = None
    intent_disagreement: Optional[V4IntentDisagreementResponse] = None
    answer: str = ""
    materials: List[Dict[str, Any]] = Field(default_factory=list)
    all_materials: List[Dict[str, Any]] = Field(default_factory=list)
    all_material_count: int = 0
    materials_focus_applied: bool = False
    material_families: List[str] = Field(default_factory=list)
    search_source: str = ""
    parsed_query: Dict[str, Any] = Field(default_factory=dict)
    schema_version: str = ""
    timestamp: str = ""
    total_test_records: int = 0
    materials_with_tests: int = 0
    materials_with_mua: int = 0


class V4BatchQueryRequest(BaseModel):
    """Batch mode request with multiple queries."""

    queries: List[V4QueryRequest] = Field(..., min_length=1, max_length=100)

    model_config = {"extra": "forbid"}


class V4BatchQueryResponse(BaseModel):
    """Batch mode response."""

    results: List[V4QueryResponse]
    total: int
    refused_count: int


class V4HeritageOverrideRequest(BaseModel):
    """Engineer acknowledgment for heritage veto."""

    material_key: str = Field(..., min_length=1, description="Material identifier")
    heritage_failure_id: str = Field(..., min_length=1, description="Heritage failure record ID")
    failure_environment: Dict[str, Any] = Field(..., description="Failure environment (EnvironmentSpec-compatible)")
    query_environment: Dict[str, Any] = Field(..., description="Query environment (EnvironmentSpec-compatible)")
    engineer_name: str = Field(..., min_length=1, description="Engineer name")
    engineer_rationale: str = Field(..., min_length=10, description="Rationale for override (min 10 chars)")
    lineage_hash: str = Field(..., min_length=64, max_length=64, description="Parent decision lineage query_hash")

    model_config = {"extra": "forbid"}


class V4HeritageOverrideResponse(BaseModel):
    """Created heritage override record."""

    override_id: str
    material_key: str
    heritage_failure_id: str
    engineer_name: str
    timestamp: str
    acknowledged: bool


class V4SchemaValidationResponse(BaseModel):
    """Schema validation result for CI."""

    passed: bool
    schema_version: str
    changes: List[Dict[str, Any]] = Field(default_factory=list)
    requires_faiss_rebuild: bool = False
    requires_regression: bool = False


# =============================================================================
# Sonnet / Bedrock Integration
# =============================================================================

_PARSE_SYSTEM_PROMPT = """You are a NASA materials engineer AI for the MIRA system.
Your job: given a query about materials for a specific application/environment,
RECOMMEND specific materials that would work, AND extract the environment details.

Return ONLY valid JSON with these fields:
{
  "intent": "<one of: compatibility_query, risk_query, materials_query, property_query, comparison, recommendation, general_search>",
  "safety_context": "<one of: oxygen, hydrogen, cryogenic, high_pressure, general>",
  "domain_scope": "<one of: in_scope, out_of_scope, uncertain>",
  "scope_reason": "<short reason for scope classification>",
  "material_key": "<specific material name/spec if user named one, or null>",
  "candidate_materials": [
    "<specific material designations that would work for this application>"
  ],
  "material_families": ["<broader material families to search>"],
  "material_type": "<one of: Metal, Polymer, Adhesive, Coating, Composite, Foam, null>",
  "environment": {
    "temperature_c": <number or null>,
    "pressure_kpa": <number or null>,
    "o2_pct": <number or null>,
    "fluid_medium": "<string or null>",
    "duration_hr": <number or null>,
    "cycles": <number or null>
  },
  "reasoning": "<1-2 sentences explaining why these materials were chosen>",
  "filters": {}
}

CRITICAL RULES:
- candidate_materials is the MOST IMPORTANT field. List 5-15 specific materials
  that an aerospace engineer would actually recommend for this application.
  Use real designations: "Inconel 718", "Monel 400", "CRES 316L", "Teflon (PTFE)",
  "Viton A", "Kel-F 81", "Ti-6Al-4V", "Hastelloy C-276", "Waspaloy", etc.
- If the user names a specific material ("Can I use Inconel 718 for..."),
  put that material in material_key AND in candidate_materials.
  Also add similar/alternative materials to candidate_materials.
- material_families: broader families for fallback search (e.g. "stainless steel",
  "nickel alloy", "fluoropolymer"). 2-5 entries.
- Convert temperatures to Celsius, pressures to kPa.
- safety_context: "oxygen" if O2/LOX/GOX, "hydrogen" if H2/LH2/GH2,
  "cryogenic" if T < -73C, "high_pressure" if P > 20684 kPa, else "general".
- domain_scope:
  * "in_scope" for NASA materials/process questions (compatibility, ratings,
    test data, MUA/MIUL, standards, material selection).
  * "out_of_scope" for unrelated prompts (jokes, trivia, personal advice,
    coding tasks not about M&P, etc.).
  * "uncertain" only if the query is ambiguous.
- Use your aerospace/materials engineering knowledge. Think about:
  * Oxygen compatibility (ASTM G94, NASA-STD-6001)
  * Hydrogen embrittlement resistance
  * Cryogenic toughness
  * Corrosion resistance in the stated environment
  * Common NASA/aerospace material selections for the application

Respond with ONLY valid JSON. No markdown fences, preamble, or commentary.
"""


async def _parse_query_with_sonnet(raw_query: str) -> Dict[str, Any]:
    """Parse a natural language query into structured fields via LLM provider.

    Falls back to a heuristic parse if the provider call fails.
    Uses LLM_PROVIDER env var for backend selection; set USE_BEDROCK=1
    to force AWS Bedrock.
    """
    use_bedrock = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
    model_bedrock = os.environ.get(
        "MIRA_V4_SONNET_BEDROCK_MODEL",
        resolve_model("sonnet"),
    )
    model_direct = os.environ.get(
        "MIRA_V4_SONNET_DIRECT_MODEL",
        resolve_model("sonnet"),
    )

    def _call_sonnet() -> Dict[str, Any]:
        try:
            model = model_bedrock if use_bedrock else model_direct
            response = llm_complete(
                system=_PARSE_SYSTEM_PROMPT,
                user=raw_query,
                model=model,
                max_tokens=1024,
                temperature=0.0,
                provider="bedrock-converse" if use_bedrock else None,
            )

            try:
                return extract_json(response.text, expect="object")
            except ExtractionError:
                LOGGER.warning("[MIRA_V4] Sonnet returned non-JSON: %s", response.text[:200])
                return {}

        except Exception as exc:
            LOGGER.warning(
                "[MIRA_V4] Sonnet call failed, using heuristic fallback: %s", exc
            )
            return {}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _call_sonnet)
    return result


# =============================================================================
# Response Engine — Sonnet answers the user's question using DB evidence
# =============================================================================

_RESPONSE_SYSTEM_PROMPT = """You are MIRA, a NASA materials engineer AI assistant.
You have been given a user's question and the materials data retrieved from the
MAPTIS database. Your job is to ANSWER THE QUESTION using ONLY the evidence provided.

CRITICAL — EVIDENCE-ONLY RULE:
You may ONLY state facts that appear explicitly in the evidence below.
- If a material is tagged [O₂ COMPATIBLE], you may say it has an O₂ rating.
- If a material is tagged [NO O₂ RATING IN MAPTIS], you MUST say the database
  does not contain an oxygen compatibility rating for it. Do NOT claim it is
  "rated for oxygen service" based on MUA records or test counts alone.
- If a material has [MUA precedent: N records], say it has N MUA precedent records.
  MUA records indicate prior usage approval, NOT oxygen compatibility ratings.
- If data is absent or marked "no test data", say so. Do not infer.
- If a "Focus material" is provided, answer ONLY for that material using
  matching designation evidence. Do not substitute other materials.

ANSWER FORMAT:
- Lead with a direct YES/NO/CONDITIONAL when the question is about compatibility.
  Use CONDITIONAL when evidence is incomplete (e.g., tests exist but no O₂ rating).
- Cite specific numbers from the evidence: test counts, test types, MUA count.
- If the confidence score is low, explain what data is missing.
- Keep it under 200 words. Engineers want facts, not fluff.
- Use Markdown formatting (bold, bullets) for readability.
- End with a one-line recommendation or caveat.

DO NOT:
- Claim a material is "oxygen compatible" unless it is tagged [O₂ COMPATIBLE].
- Claim a material has a NASA-STD-6001 A/B rating unless explicitly tagged.
- Infer compatibility from MUA records, test counts, or material family alone.
- Make up test data or ratings that aren't in the evidence.
- Include disclaimers about being an AI — answer like an engineer would.
"""


async def _generate_answer(
    raw_query: str,
    materials: List[Dict[str, Any]],
    confidence_score: float,
    gate_action: str,
    safety_context: str,
    focus_material_key: Optional[str] = None,
) -> str:
    """Generate a natural language answer using Sonnet + DB evidence.

    Falls back to a template-based answer if Sonnet is unavailable.
    """
    # Build evidence summary for Sonnet — explicit about what IS and ISN'T in the data
    top_materials = materials[:10]  # Don't overwhelm the prompt
    source_set = {
        str(m.get("data_source") or "MAPTIS").upper()
        for m in top_materials
    }
    if source_set and source_set == {"H2_KNOWLEDGE"}:
        evidence_source_label = "H2 knowledge corpus"
    elif source_set and source_set <= {"MAPTIS", "MAPTIS_FAISS"}:
        evidence_source_label = "MAPTIS database"
    else:
        evidence_source_label = "materials databases"

    evidence_lines = []
    for m in top_materials:
        line = f"- {m.get('designation', '?')}"
        total = m.get("total_tests", 0)
        if total > 0:
            tc = m.get("test_counts", {})
            parts = [f"{k}={v}" for k, v in tc.items() if v]
            line += f" — {total} tests ({', '.join(parts)})"
        else:
            line += " — no test data found"
        # O₂ compatibility: EXPLICITLY tag both present AND absent
        if safety_context == "oxygen":
            if m.get("oxygen_compatible"):
                line += " [O₂ COMPATIBLE - NASA-STD-6001 A/B rated]"
            else:
                line += " [NO O₂ RATING IN DATA]"
        # MUA precedent
        if m.get("has_mua_precedent"):
            line += f" [MUA precedent: {m.get('mua_count', 0)} records]"
        # Temperature range
        temp_min = m.get("use_temp_min_c")
        temp_max = m.get("use_temp_max_c")
        if temp_min is not None or temp_max is not None:
            line += f" [temp: {temp_min or '?'}°C to {temp_max or '?'}°C]"
        yr = m.get("latest_test_year")
        if yr:
            line += f" [latest: {yr}]"
        evidence_lines.append(line)

    evidence_text = "\n".join(evidence_lines)

    user_message = f"""Question: {raw_query}

Confidence: {confidence_score:.0%} ({gate_action})
Safety context: {safety_context}
Focus material: {focus_material_key or "none"}
Materials found: {len(materials)} ({len(top_materials)} shown)

Evidence from {evidence_source_label}:
{evidence_text}
"""

    use_bedrock = os.environ.get("USE_BEDROCK", "0").lower() in ("1", "true", "yes")

    def _call_sonnet() -> str:
        try:
            model = os.environ.get(
                "MIRA_V4_SONNET_BEDROCK_MODEL",
                resolve_model("sonnet"),
            ) if use_bedrock else os.environ.get(
                "MIRA_V4_SONNET_DIRECT_MODEL",
                resolve_model("sonnet"),
            )
            response = llm_complete(
                system=_RESPONSE_SYSTEM_PROMPT,
                user=user_message,
                model=model,
                max_tokens=1024,
                temperature=0.0,
                provider="bedrock-converse" if use_bedrock else None,
            )
            return response.text

        except Exception as exc:
            LOGGER.warning("[MIRA_V4] Response engine Sonnet call failed: %s", exc)
            return ""

    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(_executor, _call_sonnet)

    # Fallback: template-based answer if Sonnet failed
    if not answer:
        if not materials:
            answer = "No matching materials found in available data for this query."
        else:
            top = materials[0]
            name = top.get("designation", "Unknown")
            tests = top.get("total_tests", 0)
            o2 = " O₂ compatible." if top.get("oxygen_compatible") else ""
            mua = " Has MUA precedent." if top.get("has_mua_precedent") else ""
            answer = (
                f"Found **{len(materials)} materials** in {evidence_source_label}. "
                f"Top result: **{name}** with {tests} test records.{o2}{mua} "
                f"Confidence: {confidence_score:.0%} ({gate_action})."
            )

    return answer


def _heuristic_parse(raw_query: str) -> Dict[str, Any]:
    """Minimal heuristic fallback when Sonnet is unavailable."""
    query_upper = raw_query.upper()
    query_lower = raw_query.lower()

    safety_context = "general"
    if any(kw in query_upper for kw in ["LOX", "GOX", "OXYGEN", " O2 "]):
        safety_context = "oxygen"
    elif any(kw in query_upper for kw in ["LH2", "GH2", "HYDROGEN", " H2 "]):
        safety_context = "hydrogen"
    elif "CRYOGENIC" in query_upper or "CRYO" in query_upper:
        safety_context = "cryogenic"

    # Extract material_key if a known material is explicitly named
    material_key = None
    # Ordered: check multi-word patterns first, then single words
    _KNOWN_MATERIALS = [
        # Multi-word / spec designations (check first)
        "inconel 718", "inconel 625", "inconel 600",
        "monel 400", "monel k-500",
        "hastelloy c-276", "hastelloy x",
        "al 6061", "al 2024", "al 7075",
        "ti-6al-4v",
        "ss 316l", "ss 316", "ss 304l", "ss 304", "ss 321", "ss 347",
        "17-4 ph", "17-4ph",
        # Alloy numbers (common shorthand)
        "316l", "316", "304l", "304", "321", "347",
        "6061", "2024", "7075",
        "718", "625",
        # Single-word names
        "inconel", "monel", "hastelloy", "waspaloy", "stellite",
        "teflon", "ptfe", "viton", "kel-f", "vespel", "kapton",
        "kovar", "invar", "nimonic",
    ]
    for mat in _KNOWN_MATERIALS:
        if mat in query_lower:
            material_key = mat
            break

    # Infer material families from keywords
    material_families = []
    _FAMILY_KEYWORDS = {
        "aluminum": ["aluminum", "aluminium", " al ", "al-", "6061", "2024", "7075"],
        "stainless steel": ["stainless", "ss ", "316", "304", "321", "347", "17-4", "cres"],
        "titanium": ["titanium", "ti-6al", "ti ", "ti6al"],
        "inconel": ["inconel", "alloy 625", "alloy 718", "in718", "in625"],
        "monel": ["monel", "monel 400"],
        "hastelloy": ["hastelloy", "c-276"],
        "copper": ["copper", "cu ", "ofhc"],
        "nickel": ["nickel", "ni "],
        "teflon": ["teflon", "ptfe"],
        "viton": ["viton"],
        "kel-f": ["kel-f", "pctfe"],
        "vespel": ["vespel"],
        "kapton": ["kapton"],
    }
    for family, keywords in _FAMILY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            material_families.append(family)

    # If no specific families found, infer from structural context
    if not material_families:
        structural_kw = ["rack", "bracket", "frame", "structure", "mount",
                         "support", "hardware", "panel"]
        seal_kw = ["seal", "gasket", "o-ring", "oring", "seat", "packing"]
        tube_kw = ["tube", "tubing", "pipe", "piping", "line", "fitting",
                   "valve body", "manifold", "regulator"]

        if any(kw in query_lower for kw in structural_kw):
            material_families = ["aluminum", "stainless steel", "titanium"]
        elif any(kw in query_lower for kw in seal_kw):
            material_families = ["teflon", "viton", "kel-f", "silicone"]
        elif any(kw in query_lower for kw in tube_kw):
            material_families = ["stainless steel", "inconel", "monel"]

    # Determine material type
    material_type = None
    if any(kw in query_lower for kw in ["metal", "steel", "aluminum", "titanium",
                                         "inconel", "monel", "alloy", "nickel"]):
        material_type = "Metal"
    elif any(kw in query_lower for kw in ["polymer", "plastic", "teflon",
                                           "viton", "nylon", "polyethylene"]):
        material_type = "Polymer"

    # Build candidate_materials from known material + families
    # (Heuristic can't recommend like Sonnet, but it can list what it knows)
    candidate_materials = []
    if material_key:
        candidate_materials.append(material_key)
    # Add common materials per safety context when families are broad
    if safety_context == "oxygen" and not material_key:
        candidate_materials.extend([
            "Monel 400", "Monel K-500", "Inconel 600", "Inconel 718",
            "CRES 316", "Teflon", "Kel-F", "Hastelloy C-276",
        ])
    elif safety_context == "hydrogen" and not material_key:
        candidate_materials.extend([
            "CRES 316L", "CRES 304L", "Inconel 718", "Inconel 625",
            "Monel 400", "Ti-6Al-4V",
        ])
    elif safety_context == "cryogenic" and not material_key:
        candidate_materials.extend([
            "CRES 304L", "CRES 316L", "Inconel 718",
            "Ti-6Al-4V", "Aluminum 6061",
        ])

    return {
        "intent": "general_search",
        "safety_context": safety_context,
        "domain_scope": "uncertain",
        "scope_reason": "Heuristic fallback parser cannot reliably classify domain scope.",
        "material_key": material_key,
        "candidate_materials": candidate_materials,
        "material_families": material_families,
        "material_type": material_type,
        "environment": {},
        "filters": {},
    }


def _normalize_domain_scope(raw_scope: Any) -> str:
    """Normalize Sonnet domain scope label into a strict tri-state."""
    if raw_scope is None:
        return "uncertain"

    scope = str(raw_scope).strip().lower()
    if scope in {"in_scope", "out_of_scope", "uncertain"}:
        return scope
    return "uncertain"


def _is_out_of_scope(parsed: Dict[str, Any]) -> bool:
    """Return True only when Sonnet explicitly classifies as out_of_scope."""
    return _normalize_domain_scope(parsed.get("domain_scope")) == "out_of_scope"


def _build_out_of_scope_answer(parsed: Dict[str, Any]) -> str:
    """User-facing response for non-materials questions."""
    reason = str(parsed.get("scope_reason") or "").strip()
    if not reason:
        reason = (
            "This question is not about NASA materials or processes decisions."
        )

    return (
        "# MIRA Response: Out of Scope\n"
        "This question is outside the MIRA materials and processes domain.\n\n"
        f"Reason: {reason}\n\n"
        "Ask about material compatibility, MAPTIS ratings/test data, "
        "or MUA/MIUL decisions."
    )


def _tokenize_material_text(value: str) -> set:
    """Tokenize material strings for robust designation matching."""
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _select_answer_materials_for_focus(
    materials: List[Dict[str, Any]],
    focus_material_key: Optional[str],
) -> List[Dict[str, Any]]:
    """Select answer-evidence materials matching the user-requested material.

    Returns the original list when no reliable focus match exists.
    """
    if not materials or not focus_material_key:
        return materials

    focus_norm = str(focus_material_key).strip().lower()
    focus_tokens = _tokenize_material_text(focus_norm)
    if not focus_tokens:
        return materials

    # Tier 1: strict direct-designation matches (preferred when available).
    # Example: "Inconel 718" should prefer "INCONEL 718 BAR AGED" over
    # multi-material records containing "INCONEL 718" in a join note.
    direct_matches = []
    for row in materials:
        designation = str(row.get("designation", "") or "")
        des_norm = designation.strip().lower()
        if des_norm.startswith(focus_norm):
            direct_matches.append(row)

    if direct_matches:
        return sorted(
            direct_matches,
            key=lambda r: (-r.get("total_tests", 0), str(r.get("designation", ""))),
        )

    numeric_focus_tokens = {t for t in focus_tokens if t.isdigit()}
    matches: List[tuple] = []

    for row in materials:
        designation = str(row.get("designation", "") or "")
        des_tokens = _tokenize_material_text(designation)
        if not des_tokens:
            continue

        # If the requested material includes numeric identity (e.g., 718),
        # require those numeric tokens to be present.
        if numeric_focus_tokens and not numeric_focus_tokens.issubset(des_tokens):
            continue

        overlap = len(focus_tokens.intersection(des_tokens))
        coverage = overlap / max(1, len(focus_tokens))
        full_substring = focus_norm in designation.lower()

        if full_substring or coverage >= 1.0:
            score = (100 if full_substring else 0) + overlap
            matches.append((score, row.get("total_tests", 0), designation, row))

    if not matches:
        return materials

    matches.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in matches]


# =============================================================================
# Pipeline Helpers
# =============================================================================


def _build_parsed_query(
    raw_query: str,
    sonnet_parsed: Dict[str, Any],
    request: V4QueryRequest,
) -> "ParsedQuery":
    """Build a ParsedQuery from Sonnet output + user overrides."""
    from mira_v4.models import EnvironmentSpec, ParsedQuery, SafetyContext

    # Environment: merge Sonnet-parsed with user-supplied overrides
    sonnet_env = sonnet_parsed.get("environment", {}) or {}
    env_kwargs = {}
    for field in ["temperature_c", "pressure_kpa", "o2_pct", "fluid_medium", "duration_hr", "cycles"]:
        # User-supplied fields take precedence
        user_val = getattr(request, field, None)
        sonnet_val = sonnet_env.get(field)
        env_kwargs[field] = user_val if user_val is not None else sonnet_val

    environment = EnvironmentSpec(**env_kwargs)

    # Safety context
    raw_context = sonnet_parsed.get("safety_context", "general")
    try:
        safety_context = SafetyContext(raw_context)
    except ValueError:
        safety_context = SafetyContext.GENERAL

    # Intent
    sonnet_intent = sonnet_parsed.get("intent", "general_search")
    material_key = request.material_key or sonnet_parsed.get("material_key")
    filters = dict(sonnet_parsed.get("filters", {}) or {})
    filters["domain_scope"] = _normalize_domain_scope(sonnet_parsed.get("domain_scope"))
    scope_reason = sonnet_parsed.get("scope_reason")
    if scope_reason:
        filters["scope_reason"] = str(scope_reason)

    return ParsedQuery(
        raw_query=raw_query,
        intent=sonnet_intent,
        safety_context=safety_context,
        environment=environment,
        material_key=material_key,
        filters=filters,
        sonnet_intent=sonnet_intent,
        heuristic_intent=None,  # filled by guardrail
        batch_mode=request.batch_mode,
    )


def _classify_dirty_data(evidence_rows: list) -> tuple:
    """Classify dirty data tier from evidence rows.

    Returns:
        (dirty_fraction, dirty_data_tier, dirty_data_result)
    """
    from mira_v4.granta_client import DirtyDataClassifier

    classifier = DirtyDataClassifier()
    result = classifier.classify_records(evidence_rows)

    return result.dirty_fraction, result.tier, result


def _serialize_lineage(
    lineage,
    materials: list,
    all_materials: Optional[List[Dict[str, Any]]] = None,
    material_families: Optional[List[str]] = None,
    search_source: str = "",
    answer: str = "",
) -> V4QueryResponse:
    """Convert a DecisionLineage + materials into the API response model."""
    conf = lineage.confidence

    confidence_resp = V4ConfidenceResponse(
        score=conf.score,
        penalties=conf.penalties,
        penalty_details=[
            V4PenaltyDetailResponse(
                penalty_type=pd.penalty_type,
                penalty_value=pd.penalty_value,
                explanation=pd.explanation,
            )
            for pd in conf.penalty_details
        ],
        gate_action=conf.gate_action.value,
        safety_critical=conf.safety_critical,
        explanation=conf.explanation,
    )

    batch_gate_resp = None
    if lineage.batch_gate is not None:
        bg = lineage.batch_gate
        batch_gate_resp = V4BatchGateResponse(
            action=bg.action.value,
            penalty=bg.penalty,
            missing_fields=bg.missing_fields,
            safety_context=bg.safety_context.value,
            reason=bg.reason,
        )

    dirty_data_resp = None
    if lineage.dirty_data_result is not None:
        dd = lineage.dirty_data_result
        dirty_data_resp = V4DirtyDataResponse(
            tier=dd.tier.value,
            dirty_fraction=dd.dirty_fraction,
            total_records=dd.total_records,
            dirty_records=dd.dirty_records,
            user_message=dd.user_message,
        )
    elif lineage.dirty_data_tier is not None:
        dirty_data_resp = V4DirtyDataResponse(
            tier=lineage.dirty_data_tier.value,
            dirty_fraction=0.0,
            total_records=0,
            dirty_records=0,
            user_message=None,
        )

    heritage_resp = None
    if lineage.heritage_veto is not None:
        hv = lineage.heritage_veto
        heritage_resp = V4HeritageVetoResponse(
            vetoed=hv.vetoed,
            veto_type=hv.veto_type.value if hv.veto_type else None,
            heritage_failure_ids=hv.heritage_failure_ids,
            requires_acknowledgment=hv.requires_acknowledgment,
            rank_penalty=hv.rank_penalty,
            envelope_match_details=hv.envelope_match_details,
        )

    intent_resp = None
    if lineage.intent_disagreement is not None:
        idis = lineage.intent_disagreement
        intent_resp = V4IntentDisagreementResponse(
            sonnet_intent=idis.sonnet_intent,
            heuristic_intent=idis.heuristic_intent,
            chosen_intent=idis.chosen_intent,
            penalty_applied=idis.penalty_applied,
            explanation=idis.explanation,
        )

    full_materials = all_materials if all_materials is not None else materials
    used_keys = [m.get("material_key") for m in materials]
    full_keys = [m.get("material_key") for m in full_materials]
    focus_applied = used_keys != full_keys

    # Compute aggregate stats from answer-evidence material rows
    total_test_records = sum(m.get("total_tests", 0) for m in materials)
    materials_with_tests = sum(1 for m in materials if m.get("total_tests", 0) > 0)
    materials_with_mua = sum(1 for m in materials if m.get("has_mua_precedent", False))

    return V4QueryResponse(
        lineage_id=lineage.lineage_id,
        query_hash=lineage.query_hash,
        snapshot_hash=lineage.snapshot_hash,
        confidence=confidence_resp,
        gate_action=conf.gate_action.value,
        batch_gate=batch_gate_resp,
        dirty_data=dirty_data_resp,
        heritage_veto=heritage_resp,
        intent_disagreement=intent_resp,
        answer=answer,
        materials=materials,
        all_materials=full_materials,
        all_material_count=len(full_materials),
        materials_focus_applied=focus_applied,
        material_families=material_families or [],
        search_source=search_source,
        parsed_query=lineage.parsed_query.model_dump(),
        schema_version=lineage.schema_version,
        timestamp=lineage.timestamp,
        total_test_records=total_test_records,
        materials_with_tests=materials_with_tests,
        materials_with_mua=materials_with_mua,
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/ping")
async def ping() -> Dict[str, str]:
    """Health check for MIRA v4 endpoint."""
    return {"status": "ok", "domain": "mira-v4", "version": "4.0.0"}


@router.post("/query", response_model=V4QueryResponse, deprecated=True)
async def query_v4(request: V4QueryRequest) -> V4QueryResponse:
    """Execute the full MIRA v4 decision lineage pipeline.

    Deprecated:
    Use `POST /mira/query` for the canonical B-S-M-S query path.

    Steps:
    1. Parse NL query with Sonnet (Bedrock)
    2. Validate intent with IntentGuardrail
    3. Check batch safety gate (if batch_mode)
    4. Classify dirty data
    5. Check heritage veto
    6. Build decision lineage (confidence + provenance)
    7. Return lineage + material results

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """
    try:
        LOGGER.info("[MIRA_V4] Query received: '%s'", request.query[:100])

        # Lazy imports to avoid circular dependency at module load
        from mira_v4.decision_lineage import DecisionLineageBuilder
        from mira_v4.heritage_veto import HeritageVetoEngine
        from mira_v4.intent_guardrail import IntentGuardrail
        from mira_v4.models import EvidenceRow

        # --- Step 1: Parse query with Sonnet ---
        sonnet_parsed = await _parse_query_with_sonnet(request.query)
        if not sonnet_parsed:
            sonnet_parsed = _heuristic_parse(request.query)
            LOGGER.info("[MIRA_V4] Using heuristic fallback parser")

        parsed_query = _build_parsed_query(request.query, sonnet_parsed, request)

        # --- Step 1b: Intelligent domain-scope bouncer (LLM-based) ---
        if _is_out_of_scope(sonnet_parsed):
            scope_reason = str(sonnet_parsed.get("scope_reason") or "").strip()
            LOGGER.info(
                "[MIRA_V4] Out-of-scope query blocked before retrieval. reason='%s'",
                scope_reason or "n/a",
            )

            parsed_query = parsed_query.model_copy(update={
                "intent": "out_of_scope",
                "filters": {
                    **parsed_query.filters,
                    "domain_scope": "out_of_scope",
                    "scope_reason": scope_reason,
                },
            })

            builder = DecisionLineageBuilder()
            lineage = builder.build(
                parsed_query=parsed_query,
                evidence_rows=[],
                schema_version="1.0.0",
            )

            return _serialize_lineage(
                lineage=lineage,
                materials=[],
                all_materials=[],
                material_families=[],
                search_source="out_of_scope",
                answer=_build_out_of_scope_answer(sonnet_parsed),
            )

        # --- Step 2: Intent guardrail ---
        intent_disagreement = None
        try:
            guardrail = IntentGuardrail()
            resolved_intent, intent_disagreement = guardrail.validate(
                sonnet_intent=parsed_query.intent,
                raw_query=request.query,
            )
            # Update parsed query with resolved intent
            parsed_query = parsed_query.model_copy(update={
                "intent": resolved_intent,
                "heuristic_intent": resolved_intent if intent_disagreement else parsed_query.heuristic_intent,
            })
        except ImportError as exc:
            LOGGER.warning("[MIRA_V4] IntentGuardrail unavailable: %s", exc)
        except Exception as exc:
            LOGGER.warning("[MIRA_V4] IntentGuardrail error: %s", exc)

        # --- Step 3: Query materials ---
        # Sonnet-first architecture: Sonnet recommends materials, we look them up.
        #
        #   Tier 0 (Sonnet candidates): Sonnet recommended specific materials
        #           (candidate_materials). Look each one up in MAPTIS by name.
        #           This is the PRIMARY path — Sonnet does the materials
        #           engineering, we just validate "do we have data?"
        #
        #   Tier 1 (exact key):   If user specified a material_key directly,
        #           search by that name (Sonnet may not have been called).
        #
        #   Tier 2 (families):    Broader family search from material_families.
        #
        #   Tier 3 (FAISS):       Semantic fallback if all above returned 0.
        materials = []
        evidence_rows = []
        search_source = "none"

        # Material type key lookup for optional type filtering
        _TYPE_KEY_MAP = {
            "metal": 235, "polymer": 239, "adhesive": 229,
            "coating": 231, "composite": 232, "foam": 233,
            "thermal protection": 240, "minerals": 237,
        }
        sonnet_material_type = sonnet_parsed.get("material_type")
        type_filter_key = (
            _TYPE_KEY_MAP.get(sonnet_material_type.lower())
            if sonnet_material_type else None
        )

        # Unit conversion helpers (DB stores F/psia, v4 canonical = C/kPa)
        def _f_to_c(f_val):
            """Fahrenheit → Celsius."""
            if f_val is None:
                return None
            return round((float(f_val) - 32.0) * 5.0 / 9.0, 2)

        def _psia_to_kpa(psia_val):
            """psia → kPa."""
            if psia_val is None:
                return None
            return round(float(psia_val) * 6.89476, 2)

        query_fluid = str(
            request.fluid_medium or parsed_query.environment.fluid_medium or ""
        ).strip().lower()
        safety_context_value = str(parsed_query.safety_context or "").strip().lower()
        prefer_h2_knowledge = (
            safety_context_value == "hydrogen"
            or safety_context_value.endswith(".hydrogen")
            or "hydrogen" in query_fluid
            or query_fluid in {"h2", "gh2", "lh2"}
            or bool(re.search(r"\b(hydrogen|h2|gh2|lh2)\b", request.query.lower()))
        )

        def _table_exists(cur, relation_name: str) -> bool:
            """Check if a relation is visible to the current DB user."""
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS exists", (relation_name,))
            row = cur.fetchone()
            if not row:
                return False
            return bool(row["exists"] if isinstance(row, dict) else row[0])

        def _get_data_source_capabilities() -> Dict[str, bool]:
            """Detect which material corpora are available in the connected DB."""
            from psycopg2.extras import RealDictCursor
            from mira.core.db_config import open_db_connection

            conn = open_db_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    return {
                        "has_primary": _table_exists(cur, "materials"),
                        "has_h2_knowledge": _table_exists(cur, "h2_knowledge.materials"),
                    }
            finally:
                conn.close()

        source_caps = _get_data_source_capabilities()
        h2_only_mode = source_caps["has_h2_knowledge"] and not source_caps["has_primary"]
        if h2_only_mode and not prefer_h2_knowledge:
            LOGGER.info(
                "[MIRA_V4] H2-only dataset active; refusing non-hydrogen query."
            )

            parsed_query = parsed_query.model_copy(update={
                "intent": "out_of_scope",
                "filters": {
                    **parsed_query.filters,
                    "domain_scope": "out_of_scope",
                    "scope_reason": (
                        "H2-only dataset is active; this endpoint accepts hydrogen "
                        "compatibility queries only."
                    ),
                },
            })

            builder = DecisionLineageBuilder()
            lineage = builder.build(
                parsed_query=parsed_query,
                evidence_rows=[],
                schema_version="1.0.0",
            )

            return _serialize_lineage(
                lineage=lineage,
                materials=[],
                all_materials=[],
                material_families=[],
                search_source="h2_only_refuse",
                answer=(
                    "This compatibility path is currently configured for **hydrogen (H2)** "
                    "data only. Non-hydrogen queries are refused. Use an H2 query "
                    "(e.g., include hydrogen/H2/GH2/LH2) or switch to the O2 path."
                ),
            )

        def _run_primary_search(cur, pattern: str, limit: int) -> list:
            """Primary MAPTIS-style search against materials + test tables."""
            type_clause = "AND m.material_type_key = %s" if type_filter_key else ""
            params: list = [f"%{pattern.lower()}%"]
            if type_filter_key:
                params.append(type_filter_key)
            params.append(limit)

            cur.execute(
                f"""
                SELECT
                    m.material_key,
                    m.material_code,
                    m.designation,
                    m.composition,
                    m.material_type_key,
                    m.material_type_name,
                    m.use_temp_min_f,
                    m.use_temp_max_f,
                    -- Test counts per type
                    (SELECT COUNT(*) FROM flammability_tests ft
                     WHERE ft.material_code = m.material_key) AS flammability_tests,
                    (SELECT COUNT(*) FROM mechanical_impact_tests mt
                     WHERE mt.material_code = m.material_key) AS impact_tests,
                    (SELECT COUNT(*) FROM tvs_outgassing_tests tv
                     WHERE tv.material_code = m.material_key) AS outgassing_tests,
                    (SELECT COUNT(*) FROM toxicity_tests tx
                     WHERE tx.material_code = m.material_key) AS toxicity_tests,
                    (SELECT COUNT(*) FROM corrosion_tests ct
                     WHERE ct.material_code = m.material_key) AS corrosion_tests,
                    (SELECT COUNT(*) FROM tensile_strength_tests ts
                     WHERE ts.material_code = m.material_key) AS tensile_tests,
                    (SELECT COUNT(*) FROM fluid_compatibility_tests fc
                     WHERE fc.material_code = m.material_key) AS fluid_compat_tests,
                    (SELECT COUNT(*) FROM high_cycle_fatigue_tests hc
                     WHERE hc.material_code = m.material_key) AS fatigue_tests,
                    -- Latest test year across all test types
                    (SELECT MAX(dt) FROM (
                        SELECT MAX(date_tested) AS dt FROM flammability_tests
                            WHERE material_code = m.material_key
                        UNION ALL
                        SELECT MAX(date_tested) FROM mechanical_impact_tests
                            WHERE material_code = m.material_key
                        UNION ALL
                        SELECT MAX(date_tested) FROM tvs_outgassing_tests
                            WHERE material_code = m.material_key
                        UNION ALL
                        SELECT MAX(date_tested) FROM toxicity_tests
                            WHERE material_code = m.material_key
                        UNION ALL
                        SELECT MAX(date_tested) FROM corrosion_tests
                            WHERE material_code = m.material_key
                        UNION ALL
                        SELECT MAX(date_tested) FROM tensile_strength_tests
                            WHERE material_code = m.material_key
                        UNION ALL
                        SELECT MAX(date_tested) FROM fluid_compatibility_tests
                            WHERE material_code = m.material_key
                    ) sub) AS latest_test_date,
                    -- MUA precedent count (smart match: use CRES/alloy
                    -- identifier from parenthetical, e.g. "CRES 347"
                    -- from "STAINLESS STEEL 347 (CRES 347) BAR ANNEALED",
                    -- or fall back to first two words if no parens)
                    (SELECT COUNT(*) FROM public.mua_precedents_v7 mp
                     WHERE LOWER(mp.material_designation) LIKE
                           '%%' || LOWER(
                               CASE
                                   WHEN m.designation LIKE '%%(%%)%%' THEN
                                       TRIM(SUBSTRING(m.designation FROM '\\(([^)]+)\\)'))
                                   ELSE
                                       CONCAT(
                                           SPLIT_PART(m.designation, ' ', 1), ' ',
                                           SPLIT_PART(m.designation, ' ', 2)
                                       )
                               END
                           ) || '%%'
                     AND LENGTH(TRIM(COALESCE(
                           SUBSTRING(m.designation FROM '\\(([^)]+)\\)'),
                           CONCAT(SPLIT_PART(m.designation, ' ', 1), ' ', SPLIT_PART(m.designation, ' ', 2))
                     ))) >= 4
                    ) AS mua_count,
                    -- Oxygen compatibility flags (flammability + promoted combustion)
                    COALESCE(
                        (SELECT bool_or(
                            nasa_6001_rating IN ('A', 'B')
                            OR nasa_6001b_rating IN ('A', 'B')
                         ) FROM flammability_tests
                         WHERE material_code = m.material_key
                        ),
                        (SELECT bool_or(
                            prom_rating IN ('A', 'B')
                            OR prom_rtg_6001b IN ('A', 'B')
                         ) FROM maptis.promoted_combustion_tests
                         WHERE CAST(materialkey AS INTEGER) = m.material_key
                        )
                    ) AS oxygen_flam_compatible,
                    'MAPTIS'::text AS data_source
                FROM materials m
                WHERE LOWER(m.designation) LIKE %s
                {type_clause}
                ORDER BY m.designation
                LIMIT %s
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

        def _run_h2_knowledge_search(cur, pattern: str, limit: int) -> list:
            """Fallback search against h2_knowledge corpus tables."""
            cur.execute(
                """
                SELECT
                    m.material_key,
                    NULL::text AS material_code,
                    TRIM(CONCAT_WS(' ', m.common_name, NULLIF(m.form, ''), NULLIF(m.temper, ''))) AS designation,
                    m.specification AS composition,
                    NULL::integer AS material_type_key,
                    'H2_KNOWLEDGE'::text AS material_type_name,
                    NULL::double precision AS use_temp_min_f,
                    NULL::double precision AS use_temp_max_f,
                    COALESCE(agg.total_tests, 0) AS total_tests,
                    COALESCE(agg.h2_tests, 0) AS h2_tests,
                    COALESCE(agg.fracture_tests, 0) AS fracture_tests,
                    COALESCE(agg.fatigue_tests, 0) AS fatigue_tests,
                    COALESCE(agg.tensile_tests, 0) AS tensile_tests,
                    NULL::integer AS mua_count,
                    FALSE AS oxygen_flam_compatible,
                    'H2_KNOWLEDGE'::text AS data_source
                FROM h2_knowledge.materials m
                LEFT JOIN (
                    SELECT
                        pr.material_key,
                        COUNT(*) AS total_tests,
                        COUNT(*) FILTER (WHERE UPPER(COALESCE(pr.gas, '')) LIKE 'H2%%') AS h2_tests,
                        COUNT(*) FILTER (WHERE pr.record_type = 'fracture_toughness') AS fracture_tests,
                        COUNT(*) FILTER (WHERE pr.record_type LIKE 'fatigue%%') AS fatigue_tests,
                        COUNT(*) FILTER (WHERE pr.record_type = 'tensile_properties') AS tensile_tests
                    FROM h2_knowledge.property_records pr
                    GROUP BY pr.material_key
                ) agg ON agg.material_key = m.material_key
                WHERE LOWER(
                    CONCAT_WS(
                        ' ',
                        COALESCE(m.common_name, ''),
                        COALESCE(m.form, ''),
                        COALESCE(m.temper, ''),
                        COALESCE(m.specification, ''),
                        COALESCE(m.material_key, '')
                    )
                ) LIKE %s
                ORDER BY COALESCE(agg.h2_tests, 0) DESC, COALESCE(agg.total_tests, 0) DESC, m.common_name
                LIMIT %s
                """,
                (f"%{pattern.lower()}%", limit),
            )
            return [dict(r) for r in cur.fetchall()]

        def _normalize_material_row(row: Dict[str, Any], decimal_type: Any) -> Dict[str, Any]:
            """Normalize heterogeneous DB rows into v4 material response shape."""
            normalized = dict(row)
            for key, value in list(normalized.items()):
                if isinstance(value, decimal_type):
                    normalized[key] = float(value)

            data_source = str(normalized.get("data_source") or "MAPTIS").upper()
            if data_source == "H2_KNOWLEDGE":
                test_counts = {
                    "hydrogen": normalized.pop("h2_tests", 0) or 0,
                    "fracture_toughness": normalized.pop("fracture_tests", 0) or 0,
                    "fatigue": normalized.pop("fatigue_tests", 0) or 0,
                    "tensile": normalized.pop("tensile_tests", 0) or 0,
                }
                normalized["total_tests"] = int(normalized.pop("total_tests", 0) or 0)
                normalized["latest_test_year"] = None
                normalized["mua_count"] = 0
                normalized["has_mua_precedent"] = False
                normalized["oxygen_compatible"] = False
                normalized["use_temp_min_c"] = None
                normalized["use_temp_max_c"] = None
            else:
                test_counts = {
                    "flammability": normalized.pop("flammability_tests", 0) or 0,
                    "impact": normalized.pop("impact_tests", 0) or 0,
                    "outgassing": normalized.pop("outgassing_tests", 0) or 0,
                    "toxicity": normalized.pop("toxicity_tests", 0) or 0,
                    "corrosion": normalized.pop("corrosion_tests", 0) or 0,
                    "tensile": normalized.pop("tensile_tests", 0) or 0,
                    "fluid_compatibility": normalized.pop("fluid_compat_tests", 0) or 0,
                    "fatigue": normalized.pop("fatigue_tests", 0) or 0,
                }
                normalized["total_tests"] = sum(test_counts.values())
                latest_date = normalized.pop("latest_test_date", None)
                normalized["latest_test_year"] = latest_date.year if latest_date else None
                mua_count = normalized.pop("mua_count", 0) or 0
                normalized["mua_count"] = mua_count
                normalized["has_mua_precedent"] = mua_count > 0
                normalized["oxygen_compatible"] = bool(
                    normalized.pop("oxygen_flam_compatible", False)
                )
                normalized["use_temp_min_c"] = _f_to_c(normalized.get("use_temp_min_f"))
                normalized["use_temp_max_c"] = _f_to_c(normalized.get("use_temp_max_f"))

            normalized["test_counts"] = test_counts
            normalized["data_source"] = data_source
            return normalized

        def _db_rich_search(pattern: str, limit: int = 25) -> list:
            """Search materials with hydrogen-aware source selection."""
            from decimal import Decimal as _Decimal
            from psycopg2.extras import RealDictCursor
            from mira.core.db_config import open_db_connection

            conn = open_db_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    rows: list = []
                    has_primary = _table_exists(cur, "materials")
                    has_h2 = _table_exists(cur, "h2_knowledge.materials")
                    use_h2_only = prefer_h2_knowledge

                    if use_h2_only and has_h2:
                        rows = _run_h2_knowledge_search(cur, pattern, limit)
                    if not rows and has_primary and not use_h2_only:
                        try:
                            rows = _run_primary_search(cur, pattern, limit)
                        except Exception as exc:
                            LOGGER.warning(
                                "[MIRA_V4] Primary MAPTIS search failed for '%s': %s",
                                pattern,
                                exc,
                            )
                    return [_normalize_material_row(r, _Decimal) for r in rows]
            finally:
                conn.close()

        # Backward-compatible thin wrapper for simple lookups
        def _db_ilike_search(pattern: str, limit: int = 25) -> list:
            """Thin ILIKE search (delegates to rich search)."""
            return _db_rich_search(pattern, limit)

        def _db_batch_search(patterns: List[str], per_pattern_limit: int = 5) -> list:
            """Search multiple patterns using one connection."""
            from decimal import Decimal as _Decimal
            from psycopg2.extras import RealDictCursor
            from mira.core.db_config import open_db_connection

            all_rows = []
            conn = open_db_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    has_primary = _table_exists(cur, "materials")
                    has_h2 = _table_exists(cur, "h2_knowledge.materials")
                    use_h2_only = prefer_h2_knowledge

                    for pattern in patterns:
                        rows_for_pattern: list = []
                        if use_h2_only and has_h2:
                            rows_for_pattern = _run_h2_knowledge_search(
                                cur,
                                pattern,
                                per_pattern_limit,
                            )

                        if not rows_for_pattern and has_primary and not use_h2_only:
                            try:
                                rows_for_pattern = _run_primary_search(
                                    cur,
                                    pattern,
                                    per_pattern_limit,
                                )
                            except Exception as exc:
                                LOGGER.warning(
                                    "[MIRA_V4] Primary batch search failed for '%s': %s",
                                    pattern,
                                    exc,
                                )

                        all_rows.extend(
                            _normalize_material_row(r, _Decimal)
                            for r in rows_for_pattern
                        )
            finally:
                conn.close()
            return all_rows

        # Helper: add rows to materials + evidence, deduplicating by material_key
        seen_keys: set = set()

        def _add_rows(rows: list) -> None:
            for row in rows:
                mk = row["material_key"]
                if mk not in seen_keys:
                    seen_keys.add(mk)
                    materials.append(row)

                    # Build evidence row from actual test data
                    total_tests = row.get("total_tests", 0)
                    latest_year = row.get("latest_test_year")

                    # data_class: direct_test if tests exist, else derived
                    data_class = "direct_test" if total_tests > 0 else "derived"

                    # dirty_flag: True if no test data at all (unknown quality)
                    dirty_flag = total_tests == 0

                    evidence_rows.append(EvidenceRow(
                        record_id=str(mk),
                        source=str(row.get("data_source") or "MAPTIS"),
                        data_class=data_class,
                        dirty_flag=dirty_flag,
                        test_year=latest_year,
                    ))

        def _rows_include_h2(rows: list) -> bool:
            return any(str(r.get("data_source") or "").upper() == "H2_KNOWLEDGE" for r in rows)

        # — Tier 0: Sonnet candidate_materials lookup (PRIMARY PATH) —
        # Uses _db_batch_search for single-connection efficiency
        candidate_materials = sonnet_parsed.get("candidate_materials") or []
        if candidate_materials:
            try:
                rows = _db_batch_search(candidate_materials, per_pattern_limit=5)
                _add_rows(rows)

                if materials:
                    search_source = (
                        "h2_knowledge_candidates"
                        if _rows_include_h2(rows)
                        else "sonnet_candidates"
                    )
                    LOGGER.info(
                        "[MIRA_V4] Tier-0 Sonnet candidates: searched %d candidates, "
                        "found %d materials (source=%s)",
                        len(candidate_materials), len(materials),
                        search_source,
                    )
            except Exception as exc:
                LOGGER.warning("[MIRA_V4] Tier-0 candidate search error: %s", exc)

        # — Tier 1: exact material_key ILIKE (user-specified) —
        if not materials and parsed_query.material_key:
            try:
                rows = _db_ilike_search(parsed_query.material_key, limit=25)
                _add_rows(rows)
                if materials:
                    search_source = "h2_knowledge" if _rows_include_h2(rows) else "postgresql"
                    LOGGER.info(
                        "[MIRA_V4] Tier-1 DB search for '%s': %d results (source=%s)",
                        parsed_query.material_key, len(materials), search_source,
                    )
            except Exception as exc:
                LOGGER.warning("[MIRA_V4] Tier-1 DB search error: %s", exc)

        # — Tier 2: material_families ILIKE (single connection) —
        material_families = sonnet_parsed.get("material_families") or []
        if not materials and material_families:
            try:
                per_family = max(5, 25 // len(material_families))
                family_rows = _db_batch_search(material_families, per_pattern_limit=per_family)
                _add_rows(family_rows)

                if materials:
                    search_source = (
                        "h2_knowledge_families"
                        if _rows_include_h2(family_rows)
                        else "postgresql_families"
                    )
                    LOGGER.info(
                        "[MIRA_V4] Tier-2 family search for %s: %d results (source=%s)",
                        material_families, len(materials), search_source,
                    )
            except Exception as exc:
                LOGGER.warning("[MIRA_V4] Tier-2 family search error: %s", exc)

        # — Tier 3: FAISS semantic fallback (safety net) —
        if not materials and not prefer_h2_knowledge:
            try:
                from mira.api.routers.ui_endpoints import get_semantic_search

                search_engine = get_semantic_search()
                if search_engine is not None:
                    search_results = search_engine.search(
                        query=request.query,
                        top_k=25,
                    )
                    raw_results = search_results if isinstance(search_results, list) else []

                    for idx, sr in enumerate(raw_results):
                        mat = sr.get("material", {})
                        orig = sr.get("original_material", {})
                        mk = mat.get("material_key") or orig.get("material_key")
                        materials.append({
                            "material_key": mk,
                            "material_code": mat.get("material_code") or orig.get("material_code"),
                            "designation": (
                                mat.get("designation") or mat.get("name")
                                or orig.get("designation") or orig.get("name")
                                or f"Material {idx + 1}"
                            ),
                            "composition": orig.get("composition"),
                            "material_type_key": orig.get("material_type_key"),
                            "material_type_name": orig.get("material_type_name"),
                            "use_temp_min_f": orig.get("use_temp_min_f"),
                            "use_temp_max_f": orig.get("use_temp_max_f"),
                            "use_temp_min_c": _f_to_c(orig.get("use_temp_min_f")),
                            "use_temp_max_c": _f_to_c(orig.get("use_temp_max_f")),
                            "test_counts": {},
                            "total_tests": orig.get("test_count", 0) or 0,
                            "latest_test_year": orig.get("test_year"),
                            "mua_count": 0,
                            "has_mua_precedent": False,
                            "oxygen_compatible": False,
                            "data_source": "MAPTIS_FAISS",
                            "similarity_score": sr.get("similarity_score"),
                        })
                        evidence_rows.append(EvidenceRow(
                            record_id=str(mk or f"result-{idx}"),
                            source="MAPTIS",
                            data_class="direct_test" if orig.get("test_count", 0) > 0 else "derived",
                            dirty_flag=orig.get("test_count", 0) == 0,
                            test_year=orig.get("test_year"),
                        ))

                    search_source = "semantic"
                    LOGGER.info(
                        "[MIRA_V4] Tier-3 FAISS semantic fallback: %d results",
                        len(materials),
                    )
                else:
                    LOGGER.warning("[MIRA_V4] SemanticSearchEngine not available")
            except ImportError:
                LOGGER.warning("[MIRA_V4] Semantic search not importable")
            except Exception as exc:
                LOGGER.warning("[MIRA_V4] Tier-3 FAISS search error: %s", exc)
        elif not materials and prefer_h2_knowledge:
            LOGGER.info(
                "[MIRA_V4] Skipping MAPTIS/FAISS fallback for hydrogen query; "
                "using H2 corpus only."
            )

        # Sort materials: prioritize those with more test data, then by designation
        materials.sort(
            key=lambda m: (-m.get("total_tests", 0), m.get("designation", "")),
        )

        LOGGER.info(
            "[MIRA_V4] Final material count: %d (source=%s) "
            "with_tests=%d total_test_records=%d",
            len(materials), search_source,
            sum(1 for m in materials if m.get("total_tests", 0) > 0),
            sum(m.get("total_tests", 0) for m in materials),
        )

        # --- Step 4: Classify dirty data ---
        dirty_fraction = 0.0
        dirty_data_tier = None
        dirty_data_result = None
        try:
            dirty_fraction, dirty_data_tier, dirty_data_result = _classify_dirty_data(
                evidence_rows
            )
        except Exception as exc:
            LOGGER.warning("[MIRA_V4] Dirty data classification error: %s", exc)

        # --- Step 5: Heritage veto ---
        heritage_veto_result = None
        try:
            if parsed_query.material_key:
                from mira.api.models.heritage_db import get_heritage_records

                heritage_records = get_heritage_records(parsed_query.material_key)
                if heritage_records:
                    veto_engine = HeritageVetoEngine()
                    heritage_veto_result = veto_engine.check_heritage(
                        material_key=parsed_query.material_key,
                        query_env=parsed_query.environment,
                        heritage_records=heritage_records,
                        safety_context=parsed_query.safety_context,
                    )

                    # Apply rank sink if non-safety veto
                    if heritage_veto_result.vetoed and not heritage_veto_result.requires_acknowledgment:
                        vetoed_keys = {parsed_query.material_key}
                        materials = HeritageVetoEngine.apply_rank_sink(materials, vetoed_keys)
        except Exception as exc:
            LOGGER.warning("[MIRA_V4] Heritage veto error: %s", exc)

        # --- Step 6: Build decision lineage ---
        builder = DecisionLineageBuilder()
        lineage = builder.build(
            parsed_query=parsed_query,
            evidence_rows=evidence_rows,
            schema_version="1.0.0",
            dirty_fraction=dirty_fraction,
            dirty_data_tier=dirty_data_tier,
            heritage_veto_result=heritage_veto_result,
            intent_disagreement=intent_disagreement,
        )

        # Attach dirty_data_result to lineage for serialization
        if dirty_data_result is not None:
            lineage = lineage.model_copy(update={"dirty_data_result": dirty_data_result})

        LOGGER.info(
            "[MIRA_V4] Pipeline complete: lineage_id=%s confidence=%.3f gate=%s",
            lineage.lineage_id,
            lineage.confidence.score,
            lineage.confidence.gate_action.value,
        )

        # --- Step 7: Generate natural language answer ---
        answer = ""
        answer_materials = _select_answer_materials_for_focus(
            materials,
            parsed_query.material_key,
        )

        if parsed_query.material_key and answer_materials is not materials:
            LOGGER.info(
                "[MIRA_V4] Answer/response scope anchored to '%s': %d of %d materials kept",
                parsed_query.material_key,
                len(answer_materials),
                len(materials),
            )

        try:
            answer = await _generate_answer(
                raw_query=request.query,
                materials=answer_materials,
                confidence_score=lineage.confidence.score,
                gate_action=lineage.confidence.gate_action.value,
                safety_context=parsed_query.safety_context.value,
                focus_material_key=parsed_query.material_key,
            )
        except Exception as exc:
            LOGGER.warning("[MIRA_V4] Response engine error: %s", exc)

        return _serialize_lineage(
            lineage, answer_materials,
            all_materials=materials,
            material_families=material_families,
            search_source=search_source,
            answer=answer,
        )

    except ImportError as exc:
        LOGGER.error("[MIRA_V4] Import error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"MIRA v4 module not available: {exc}",
        ) from exc
    except Exception as exc:
        LOGGER.error("[MIRA_V4] Pipeline error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"MIRA v4 pipeline error: {str(exc)}",
        ) from exc


@router.post("/query/laundered")
async def query_v4_laundered(request: V4QueryRequest) -> Dict[str, Any]:
    """Execute query through the four-layer data laundering pipeline.

    This endpoint runs the same query through the data laundering
    architecture: Sanitize -> Reason -> Validate -> Present.

    Uses the MAPTIS database for Layer 3 ground-truth validation
    (same search logic as the standard /query endpoint).

    Returns the full PipelineEnvelope as JSON for audit purposes,
    PLUS a v4-compatible response for the UI.

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """
    import sys
    sys.path.insert(0, r"C:\BoundState")

    try:
        from data_laundering.pipeline import DataLaunderingPipeline
        from data_laundering.granta_adapter import GrantaValidatorAdapter
        from data_laundering.domain_pack import create_mira_pack
        from data_laundering.bedrock_client import LLMClient
        from data_laundering.models import PipelineStatus

        LOGGER.info("[MIRA_V4_DL] Laundered query received: '%s'", request.query[:100])

        # --- Build the database search function (reuses v4 search logic) ---
        def _f_to_c(f_val):
            if f_val is None:
                return None
            return round((float(f_val) - 32.0) * 5.0 / 9.0, 2)

        def _db_batch_search_for_pipeline(
            patterns: list, per_pattern_limit: int = 5
        ) -> list:
            """MAPTIS batch search — injected into the validator adapter."""
            from decimal import Decimal as _Decimal
            from psycopg2.extras import RealDictCursor
            from mira.core.db_config import open_db_connection

            all_rows = []
            conn = open_db_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    for pattern in patterns:
                        params: list = [f"%{pattern.lower()}%"]
                        params.append(per_pattern_limit)

                        cur.execute(
                            """
                            SELECT
                                m.material_key, m.material_code, m.designation,
                                m.composition, m.material_type_key, m.material_type_name,
                                m.use_temp_min_f, m.use_temp_max_f,
                                (SELECT COUNT(*) FROM flammability_tests ft
                                 WHERE ft.material_code = m.material_key) AS flammability_tests,
                                (SELECT COUNT(*) FROM mechanical_impact_tests mt
                                 WHERE mt.material_code = m.material_key) AS impact_tests,
                                (SELECT COUNT(*) FROM tvs_outgassing_tests tv
                                 WHERE tv.material_code = m.material_key) AS outgassing_tests,
                                (SELECT COUNT(*) FROM toxicity_tests tx
                                 WHERE tx.material_code = m.material_key) AS toxicity_tests,
                                (SELECT COUNT(*) FROM corrosion_tests ct
                                 WHERE ct.material_code = m.material_key) AS corrosion_tests,
                                (SELECT COUNT(*) FROM tensile_strength_tests ts
                                 WHERE ts.material_code = m.material_key) AS tensile_tests,
                                (SELECT COUNT(*) FROM fluid_compatibility_tests fc
                                 WHERE fc.material_code = m.material_key) AS fluid_compat_tests,
                                (SELECT COUNT(*) FROM high_cycle_fatigue_tests hc
                                 WHERE hc.material_code = m.material_key) AS fatigue_tests,
                                (SELECT MAX(dt) FROM (
                                    SELECT MAX(date_tested) AS dt FROM flammability_tests
                                        WHERE material_code = m.material_key
                                    UNION ALL SELECT MAX(date_tested) FROM mechanical_impact_tests
                                        WHERE material_code = m.material_key
                                    UNION ALL SELECT MAX(date_tested) FROM tvs_outgassing_tests
                                        WHERE material_code = m.material_key
                                    UNION ALL SELECT MAX(date_tested) FROM toxicity_tests
                                        WHERE material_code = m.material_key
                                    UNION ALL SELECT MAX(date_tested) FROM corrosion_tests
                                        WHERE material_code = m.material_key
                                    UNION ALL SELECT MAX(date_tested) FROM tensile_strength_tests
                                        WHERE material_code = m.material_key
                                    UNION ALL SELECT MAX(date_tested) FROM fluid_compatibility_tests
                                        WHERE material_code = m.material_key
                                ) sub) AS latest_test_date,
                                (SELECT COUNT(*) FROM public.mua_precedents_v7 mp
                                 WHERE LOWER(mp.material_designation) LIKE
                                       '%%' || LOWER(SPLIT_PART(m.designation, ' ', 1)) || '%%'
                                 AND LENGTH(SPLIT_PART(m.designation, ' ', 1)) >= 4
                                ) AS mua_count,
                                -- Oxygen compatibility flags (flammability + promoted combustion)
                                COALESCE(
                                    (SELECT bool_or(
                                        nasa_6001_rating IN ('A', 'B')
                                        OR nasa_6001b_rating IN ('A', 'B')
                                     ) FROM flammability_tests
                                     WHERE material_code = m.material_key
                                    ),
                                    (SELECT bool_or(
                                        prom_rating IN ('A', 'B')
                                        OR prom_rtg_6001b IN ('A', 'B')
                                     ) FROM maptis.promoted_combustion_tests
                                     WHERE CAST(materialkey AS INTEGER) = m.material_key
                                    )
                                ) AS oxygen_flam_compatible
                            FROM materials m
                            WHERE LOWER(m.designation) LIKE %s
                            ORDER BY m.designation
                            LIMIT %s
                            """,
                            params,
                        )

                        for r in cur.fetchall():
                            row = dict(r)
                            for k, v in row.items():
                                if isinstance(v, _Decimal):
                                    row[k] = float(v)
                            test_counts = {
                                "flammability": row.pop("flammability_tests", 0) or 0,
                                "impact": row.pop("impact_tests", 0) or 0,
                                "outgassing": row.pop("outgassing_tests", 0) or 0,
                                "toxicity": row.pop("toxicity_tests", 0) or 0,
                                "corrosion": row.pop("corrosion_tests", 0) or 0,
                                "tensile": row.pop("tensile_tests", 0) or 0,
                                "fluid_compatibility": row.pop("fluid_compat_tests", 0) or 0,
                                "fatigue": row.pop("fatigue_tests", 0) or 0,
                            }
                            row["test_counts"] = test_counts
                            row["total_tests"] = sum(test_counts.values())
                            latest_date = row.pop("latest_test_date", None)
                            row["latest_test_year"] = (
                                latest_date.year if latest_date else None
                            )
                            mua_count = row.pop("mua_count", 0) or 0
                            row["mua_count"] = mua_count
                            row["has_mua_precedent"] = mua_count > 0
                            row["oxygen_compatible"] = bool(
                                row.pop("oxygen_flam_compatible", False)
                            )
                            row["use_temp_min_c"] = _f_to_c(row.get("use_temp_min_f"))
                            row["use_temp_max_c"] = _f_to_c(row.get("use_temp_max_f"))
                            all_rows.append(row)
            finally:
                conn.close()
            return all_rows

        # --- Create pipeline components ---
        adapter = GrantaValidatorAdapter(
            schema_version="4.0.0",
            db_search_fn=_db_batch_search_for_pipeline,
        )
        pack = create_mira_pack(adapter)

        # Use local LLM client (Ollama or OpenAI-compatible)
        llm_client = LLMClient(
            base_url=os.environ.get("LLM_BASE_URL", "http://localhost:11434"),
            api_format=os.environ.get("LLM_API_FORMAT", "ollama"),
        )

        pipeline = DataLaunderingPipeline(
            pack=pack,
            llm_client=llm_client,
            sanitizer_model=os.environ.get("DL_SANITIZER_MODEL", "llama3.1:8b"),
            reasoner_model=os.environ.get("DL_REASONER_MODEL", "llama3.1:8b"),
            presenter_model=os.environ.get("DL_PRESENTER_MODEL", "llama3.1:8b"),
        )

        # --- Run the pipeline ---
        envelope = await pipeline.process(request.query)

        # --- Build response ---
        envelope_dict = envelope.model_dump(mode="json")

        # Extract materials from Layer 3 validated records for UI compatibility
        materials = []
        if envelope.layer_3_output:
            for rec in envelope.layer_3_output.records:
                materials.append({
                    "material_key": rec.material_key,
                    "record_id": rec.record_id,
                    "source": rec.source,
                    "confidence_score": rec.confidence_score,
                    "dirty_flag": rec.dirty_flag,
                    "heritage_vetoed": rec.heritage_vetoed,
                    "properties": rec.properties,
                })

        answer = ""
        if envelope.layer_4_output:
            answer = envelope.layer_4_output.response_text

        response = {
            "pipeline_status": envelope.status.value,
            "envelope_id": envelope.envelope_id,
            "input_hash": envelope.input_hash,
            "answer": answer,
            "materials": materials,
            "layer_timings": [t.model_dump(mode="json") for t in envelope.layer_timings],
            "total_duration_ms": envelope.total_duration_ms,
            "layer_1": envelope_dict.get("layer_1_output"),
            "layer_2": envelope_dict.get("layer_2_output"),
            "layer_3": envelope_dict.get("layer_3_output"),
            "layer_4": envelope_dict.get("layer_4_output"),
            "rejection_reason": envelope.rejection_reason.value if envelope.rejection_reason else None,
            "rejection_detail": envelope.rejection_detail,
        }

        await llm_client.close()

        LOGGER.info(
            "[MIRA_V4_DL] Pipeline %s: status=%s, materials=%d, duration=%.0fms",
            envelope.envelope_id[:8],
            envelope.status.value,
            len(materials),
            envelope.total_duration_ms or 0,
        )

        return response

    except ImportError as exc:
        LOGGER.error("[MIRA_V4_DL] Import error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Data laundering pipeline not available: {exc}",
        ) from exc
    except Exception as exc:
        LOGGER.error("[MIRA_V4_DL] Pipeline error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Data laundering pipeline error: {str(exc)}",
        ) from exc


@router.post("/query/batch", response_model=V4BatchQueryResponse)
async def query_v4_batch(request: V4BatchQueryRequest) -> V4BatchQueryResponse:
    """Execute MIRA v4 pipeline in batch mode.

    Each query is forced into batch_mode=True. Safety-critical queries
    with missing required fields get REFUSE responses individually.

    Compliance: SWE-013, NASA-STD-6016 S4.2.1, S5.1.4
    """
    LOGGER.info("[MIRA_V4] Batch request received: %d queries", len(request.queries))

    results = []
    refused_count = 0

    for idx, query_req in enumerate(request.queries):
        # Force batch mode
        batch_req = query_req.model_copy(update={"batch_mode": True})
        try:
            result = await query_v4(batch_req)
            results.append(result)
            if result.batch_gate and result.batch_gate.action == "REFUSE":
                refused_count += 1
        except HTTPException as exc:
            LOGGER.warning(
                "[MIRA_V4] Batch query %d failed: %s", idx, exc.detail
            )
            # Return a minimal error response for this query
            results.append(V4QueryResponse(
                lineage_id=f"batch-error-{idx}",
                query_hash="",
                snapshot_hash="",
                confidence=V4ConfidenceResponse(
                    score=0.0,
                    penalties={},
                    penalty_details=[],
                    gate_action="REFUSE",
                    safety_critical=False,
                    explanation=f"Batch query {idx} failed: {exc.detail}",
                ),
                gate_action="REFUSE",
                materials=[],
                schema_version="1.0.0",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            refused_count += 1

    return V4BatchQueryResponse(
        results=results,
        total=len(results),
        refused_count=refused_count,
    )


@router.post("/heritage/override", response_model=V4HeritageOverrideResponse)
async def heritage_override(request: V4HeritageOverrideRequest) -> V4HeritageOverrideResponse:
    """Create an immutable heritage veto override record.

    Records an engineer's acknowledgment that they have reviewed a
    heritage failure and accept the risk for the current query context.

    The override record is IMMUTABLE once created (frozen=True on the
    Pydantic model) and linked to the parent Decision Lineage via
    lineage_hash.

    Compliance: SWE-013, SWE-033, NASA-STD-6016 S4.2.1
    """
    try:
        if not _ensure_heritage_table_ready():
            raise HTTPException(
                status_code=503,
                detail="Heritage override unavailable in no-data runtime",
            )

        from mira_v4.heritage_veto import HeritageVetoEngine
        from mira_v4.models import EnvironmentSpec

        LOGGER.info(
            "[MIRA_V4] Heritage override requested: material='%s' "
            "failure_id='%s' engineer='%s'",
            request.material_key,
            request.heritage_failure_id,
            request.engineer_name,
        )

        engine = HeritageVetoEngine()
        override = engine.create_override(
            material_key=request.material_key,
            heritage_failure_id=request.heritage_failure_id,
            failure_env=EnvironmentSpec(**request.failure_environment),
            query_env=EnvironmentSpec(**request.query_environment),
            engineer_name=request.engineer_name,
            engineer_rationale=request.engineer_rationale,
            lineage_hash=request.lineage_hash,
        )

        return V4HeritageOverrideResponse(
            override_id=override.override_id,
            material_key=override.material_key,
            heritage_failure_id=override.heritage_failure_id,
            engineer_name=override.engineer_name,
            timestamp=override.timestamp,
            acknowledged=override.acknowledged,
        )

    except ImportError as exc:
        LOGGER.error("[MIRA_V4] Heritage veto module not available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Heritage veto module not available",
        ) from exc
    except ValueError as exc:
        LOGGER.error("[MIRA_V4] Invalid override request: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error("[MIRA_V4] Heritage override error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Heritage override error: {str(exc)}",
        ) from exc


@router.get("/schema/validate", response_model=V4SchemaValidationResponse)
async def schema_validate() -> V4SchemaValidationResponse:
    """Run schema validation for CI pipeline.

    Compares the expected schema dictionary against the live schema.
    Used by CI/CD to detect schema drift before deployment.

    Compliance: SWE-032, NASA-STD-8739.8B
    """
    try:
        from mira_v4.schema_validation import SchemaValidator

        validator = SchemaValidator()

        # Load expected schema from the repository
        expected_schema: Dict[str, str] = {}
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "data", "schema_dictionary.json"
        )
        if os.path.exists(schema_path):
            with open(schema_path, "r") as f:
                expected_schema = json.load(f)
        else:
            LOGGER.warning(
                "[MIRA_V4] Schema dictionary not found at %s; using empty schema",
                schema_path,
            )

        # For now, live schema defaults to expected (no Granta connection yet)
        live_schema = dict(expected_schema)

        result = validator.compare_schemas(
            expected_schema=expected_schema,
            live_schema=live_schema,
        )

        return V4SchemaValidationResponse(
            passed=result.passed,
            schema_version=result.schema_version,
            changes=[c.model_dump() for c in result.changes],
            requires_faiss_rebuild=result.requires_faiss_rebuild,
            requires_regression=result.requires_regression,
        )

    except ImportError as exc:
        LOGGER.error("[MIRA_V4] Schema validation module not available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Schema validation module not available",
        ) from exc
    except Exception as exc:
        LOGGER.error("[MIRA_V4] Schema validation error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Schema validation error: {str(exc)}",
        ) from exc


__safety_critical__ = True  # NASA SWE-032 compliance
