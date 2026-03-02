#!/usr/bin/env python3
"""
H2 temporary fine-tuned model service with deterministic guardrails.

Design:
- Deterministic material-presence gate decides if model can be queried.
- Unknown materials fail safe before model call.
- Known materials are sent to the configured fine-tuned model.
- Model output is post-processed for citation extraction and classification.
"""

from __future__ import annotations

import json
import os
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mira.providers.llm_provider import complete as llm_complete, resolve_model

from core.models.answer import AnswerSeverity, EvidenceItem

from .engine import evaluate_h2_compatibility
from .models import H2CompatibilityRequest, H2CompatibilityResponse
from .runtime_db import (
    fetch_material_names,
    fetch_ratio_stats,
    get_runtime_backend,
    insert_coverage_gap,
)

LOGGER = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODEL = "ft:gpt-4.1-2025-04-14:boundstate:mira-h2-v7b-balanced:DCXuyfKW"
_DEFAULT_HAIKU_MODEL = resolve_model("haiku")
_DEFAULT_CORPUS = Path("data/H2/h2_training_corpus_complete_v7b_balanced.json")
_DEFAULT_EVIDENCE = Path("mira/data/h2_evidence_merged.json")
_DEFAULT_GAP_LOG = Path("data/H2/coverage_gaps.jsonl")

_SYSTEM_PROMPT = (
    "You are Mira, an aerospace hydrogen materials compatibility assistant. "
    "Use only supported evidence, keep safety language strict, and include "
    "source page citations in the format [Source: <document>, p. <page>]."
)

_GENERIC_MATERIAL_VALUES = {
    "",
    "general",
    "all",
    "unknown",
    "various",
    "multiple",
    "n/a",
    "na",
}

_CITATION_PATTERN = re.compile(r"\[Source:\s*([^,\]]+),\s*p\.\s*(\d+)\]")
_ENGINEERING_REVIEW_HEADING_RE = re.compile(
    r"the following engineering review is suggested:?",
    re.IGNORECASE,
)


def _simple_normalize(value: str) -> str:
    text = value.lower()
    text = re.sub(r"[-_/\\()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _simple_extract_alloy_numbers(value: str) -> set[str]:
    return {m.upper() for m in re.findall(r"\b(\d{3,4}[A-Z]?)\b", value.upper())}


try:
    from mira.knowledge_twins.h2.aliases import (
        extract_alloy_numbers as _alias_extract_alloy_numbers,
        get_canonical_name as _alias_get_canonical_name,
        normalize as _alias_normalize,
    )
except Exception:
    _alias_extract_alloy_numbers = _simple_extract_alloy_numbers
    _alias_get_canonical_name = lambda _: None  # type: ignore[assignment]
    _alias_normalize = _simple_normalize


def _resolve_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (_REPO_ROOT / path)


def _get_corpus_path() -> Path:
    return _resolve_path(os.getenv("MIRA_H2_TEMP_CORPUS", str(_DEFAULT_CORPUS)))


def _get_evidence_path() -> Path:
    return _resolve_path(os.getenv("MIRA_H2_TEMP_EVIDENCE", str(_DEFAULT_EVIDENCE)))


def _get_gap_log_path() -> Path:
    return _resolve_path(os.getenv("MIRA_H2_GAP_LOG", str(_DEFAULT_GAP_LOG)))


def _get_model_id() -> str:
    return os.getenv("MIRA_H2_TEMP_MODEL", _DEFAULT_MODEL)


def _get_haiku_model_id() -> str:
    return os.getenv("MIRA_H2_HAIKU_MODEL", _DEFAULT_HAIKU_MODEL)


def _get_nlg_provider() -> str:
    """
    Narrative provider for H2 temp responses.
    - ft: existing OpenAI FT answer path
    - haiku: deterministic classification + Haiku narrative rewrite
    """
    return (os.getenv("MIRA_H2_NLG_PROVIDER", "ft") or "ft").strip().lower()


def _get_runtime_backend() -> str:
    return get_runtime_backend()


def _normalize_material(value: str) -> str:
    return _alias_normalize(value or "")


def _is_no_data_answer(answer: str) -> bool:
    text = (answer or "").lower()
    markers = [
        "no hydrogen compatibility data",
        "no hydrogen-specific",
        "insufficient data",
        "data gap",
        "not available",
        "not listed",
        "treat compatibility as unknown",
    ]
    return any(marker in text for marker in markers)


@dataclass
class _MaterialIndex:
    known_norm: set[str] = field(default_factory=set)
    display_by_norm: dict[str, str] = field(default_factory=dict)

    def add(self, material: str) -> None:
        material = (material or "").strip()
        if not material or material.lower() in _GENERIC_MATERIAL_VALUES:
            return

        candidates = {material}
        canonical = _alias_get_canonical_name(material)
        if canonical:
            candidates.add(canonical)

        for candidate in candidates:
            norm = _normalize_material(candidate)
            if not norm or norm in _GENERIC_MATERIAL_VALUES:
                continue
            self.known_norm.add(norm)
            self.display_by_norm.setdefault(norm, candidate)

            for alloy in _alias_extract_alloy_numbers(candidate):
                alloy_norm = _normalize_material(alloy)
                if alloy_norm:
                    self.known_norm.add(alloy_norm)
                    self.display_by_norm.setdefault(alloy_norm, alloy)

    def contains(self, material: str) -> tuple[bool, Optional[str]]:
        candidates = {material.strip()}
        canonical = _alias_get_canonical_name(material)
        if canonical:
            candidates.add(canonical)

        for candidate in candidates:
            norm = _normalize_material(candidate)
            if norm in self.known_norm:
                return True, self.display_by_norm.get(norm, candidate)
            for alloy in _alias_extract_alloy_numbers(candidate):
                alloy_norm = _normalize_material(alloy)
                if alloy_norm in self.known_norm:
                    return True, self.display_by_norm.get(alloy_norm, alloy)
        return False, None


_INDEX_CACHE: Optional[_MaterialIndex] = None
_RATIO_STATS_CACHE: Optional[dict[str, tuple[float, float, int]]] = None


def _build_material_index(corpus_path: Path, evidence_path: Path) -> _MaterialIndex:
    index = _MaterialIndex()
    backend = _get_runtime_backend()

    pg_loaded = 0
    if backend in {"pg", "hybrid"}:
        try:
            for material in fetch_material_names():
                index.add(material)
                pg_loaded += 1
            LOGGER.info("H2 temp gate loaded %d material names from PG runtime.", pg_loaded)
            if backend == "pg" and pg_loaded > 0:
                return index
        except Exception as exc:
            LOGGER.warning("H2 temp gate PG material load failed, falling back to JSON (%s).", exc)

    if corpus_path.exists():
        with corpus_path.open("r", encoding="utf-8") as handle:
            rows = json.load(handle)
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                answer = str(row.get("answer", ""))
                if _is_no_data_answer(answer):
                    continue
                index.add(str(row.get("material", "")))

    if evidence_path.exists():
        with evidence_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        evidence_rows = data.get("evidence", []) if isinstance(data, dict) else []
        if isinstance(evidence_rows, list):
            for row in evidence_rows:
                if not isinstance(row, dict):
                    continue
                index.add(str(row.get("material_name", "")))

    return index


def _get_material_index() -> _MaterialIndex:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        _INDEX_CACHE = _build_material_index(
            corpus_path=_get_corpus_path(),
            evidence_path=_get_evidence_path(),
        )
    return _INDEX_CACHE


def _as_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_ratio_from_row(row: dict) -> Optional[float]:
    direct = _as_float(row.get("hee_index"))
    if direct is not None:
        return direct

    metrics = row.get("metrics")
    if isinstance(metrics, dict):
        nts = _as_float(metrics.get("nts_ratio"))
        if nts is not None:
            return nts
    return None


def _build_ratio_stats(evidence_path: Path) -> dict[str, tuple[float, float, int]]:
    backend = _get_runtime_backend()
    pg_stats: dict[str, tuple[float, float, int]] = {}
    if backend in {"pg", "hybrid"}:
        try:
            raw_pg = fetch_ratio_stats()
            for material, stats in raw_pg.items():
                key = _normalize_material(material)
                if key:
                    pg_stats[key] = stats
            if backend == "pg" and pg_stats:
                LOGGER.info("H2 temp ratio screen loaded %d materials from PG runtime.", len(pg_stats))
                return pg_stats
        except Exception as exc:
            LOGGER.warning("H2 temp ratio PG load failed, falling back to JSON (%s).", exc)

    stats: dict[str, list[float]] = {}
    if not evidence_path.exists():
        return dict(pg_stats)

    with evidence_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    evidence_rows = data.get("evidence", []) if isinstance(data, dict) else []
    if not isinstance(evidence_rows, list):
        return {}

    for row in evidence_rows:
        if not isinstance(row, dict):
            continue
        material = str(row.get("material_name", "")).strip()
        if not material:
            continue
        ratio = _extract_ratio_from_row(row)
        if ratio is None:
            continue
        key = _normalize_material(material)
        if not key:
            continue
        stats.setdefault(key, []).append(ratio)

    out: dict[str, tuple[float, float, int]] = dict(pg_stats)
    for key, values in stats.items():
        if not values:
            continue
        out[key] = (min(values), max(values), len(values))
    return out


def _get_ratio_stats(material: str) -> Optional[tuple[float, float, int]]:
    global _RATIO_STATS_CACHE
    if _RATIO_STATS_CACHE is None:
        _RATIO_STATS_CACHE = _build_ratio_stats(_get_evidence_path())

    candidates = {material.strip()}
    canonical = _alias_get_canonical_name(material)
    if canonical:
        candidates.add(canonical)

    for candidate in candidates:
        key = _normalize_material(candidate)
        if key in _RATIO_STATS_CACHE:
            return _RATIO_STATS_CACHE[key]
    return None


def _get_ratio_stats_with_condition(
    material: str,
    condition: Optional[str],
) -> Optional[tuple[float, float, int]]:
    # Condition-aware lookup:
    # 1) try exact condition-tagged aliases (e.g., "Inconel 718 (ST 1900F)")
    # 2) fuzzy key match requiring both material and condition tokens
    # 3) fall back to material-only lookup
    if not condition:
        return _get_ratio_stats(material)

    global _RATIO_STATS_CACHE
    if _RATIO_STATS_CACHE is None:
        _RATIO_STATS_CACHE = _build_ratio_stats(_get_evidence_path())

    condition = condition.strip()
    if not condition:
        return _get_ratio_stats(material)

    material_norm = _normalize_material(material)
    condition_norm = _normalize_material(condition)
    numeric_tokens = set(re.findall(r"\b\d{3,4}\b", condition_norm))
    cond_tokens = set(condition_norm.split())

    exact_candidates = {
        f"{material} ({condition})",
        f"{material} {condition}",
        f"{material_norm} {condition_norm}",
    }
    for cand in exact_candidates:
        key = _normalize_material(cand)
        stats = _RATIO_STATS_CACHE.get(key)
        if stats is not None:
            return stats

    matched: list[tuple[float, float, int]] = []
    for key, stats in _RATIO_STATS_CACHE.items():
        if material_norm not in key:
            continue
        key_nums = set(re.findall(r"\b\d{3,4}\b", key))
        if numeric_tokens and not numeric_tokens.issubset(key_nums):
            continue
        if cond_tokens:
            if not any(tok in key for tok in cond_tokens):
                continue
        matched.append(stats)

    if matched:
        min_ratio = min(s[0] for s in matched)
        max_ratio = max(s[1] for s in matched)
        count = sum(s[2] for s in matched)
        return (min_ratio, max_ratio, count)

    return _get_ratio_stats(material)


def _combine_with_ratio_screen(
    baseline_class: AnswerSeverity,
    screen_class: Optional[AnswerSeverity],
) -> AnswerSeverity:
    if screen_class is None:
        return baseline_class
    if screen_class == AnswerSeverity.PROHIBITED:
        return AnswerSeverity.PROHIBITED
    if screen_class == AnswerSeverity.UNKNOWN:
        if baseline_class == AnswerSeverity.PROHIBITED:
            return baseline_class
        return AnswerSeverity.UNKNOWN
    if screen_class == AnswerSeverity.CAUTION:
        if baseline_class in {AnswerSeverity.PROHIBITED, AnswerSeverity.UNKNOWN}:
            return baseline_class
        return AnswerSeverity.CAUTION
    return baseline_class


def _ratio_screen(
    material: str,
    condition: Optional[str] = None,
) -> tuple[Optional[AnswerSeverity], Optional[str]]:
    """
    Deterministic screen from the user rule-of-thumb:
    - <= 0.75: cannot use (PROHIBITED)
    - >= 0.76: use with engineering judgement (CAUTION)
    - crossing threshold in evidence: UNKNOWN until disposition/clarification.
    """
    stats = _get_ratio_stats_with_condition(material, condition)
    if stats is None:
        return None, None

    min_ratio, max_ratio, count = stats
    cond_suffix = f" (condition: {condition})" if condition else ""
    if max_ratio <= 0.75:
        return (
            AnswerSeverity.PROHIBITED,
            f"H2/He ratio screen{cond_suffix}: {count} record(s), max={max_ratio:.2f} (<=0.75 threshold).",
        )
    if min_ratio >= 0.76:
        return (
            AnswerSeverity.CAUTION,
            f"H2/He ratio screen{cond_suffix}: {count} record(s), range={min_ratio:.2f}-{max_ratio:.2f} (>=0.76; engineering judgement required).",
        )
    return (
        AnswerSeverity.UNKNOWN,
        f"H2/He ratio screen{cond_suffix}: {count} record(s), range={min_ratio:.2f}-{max_ratio:.2f} crosses 0.75/0.76 threshold; condition-specific review required.",
    )


def _log_coverage_gap(material: str, question: str, model_id: str) -> None:
    path = _get_gap_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    record = {
        "timestamp_utc": ts,
        "material": material,
        "question": question,
        "model": model_id,
        "event": "material_not_in_evidence_index",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    if _get_runtime_backend() in {"pg", "hybrid"}:
        try:
            insert_coverage_gap(
                material=material,
                question=question,
                model=model_id,
                event="material_not_in_evidence_index",
                timestamp_utc=ts,
            )
        except Exception as exc:
            LOGGER.warning("Failed to persist coverage gap to PG runtime (%s).", exc)


def _fail_safe_rationale(material: str) -> str:
    return (
        f"No hydrogen compatibility data is available for {material} in the current evidence base. "
        "Do not use in hydrogen service without independent qualification testing under representative "
        "pressure, temperature, and environment conditions. Escalate to materials engineering for review."
    )


def _extract_response_text(resp) -> str:
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    parts: list[str] = []
    for item in getattr(resp, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            maybe_text = getattr(content, "text", None)
            if isinstance(maybe_text, str) and maybe_text.strip():
                parts.append(maybe_text.strip())
    return "\n".join(parts).strip()


def _classify_answer(answer: str) -> AnswerSeverity:
    text = answer.lower()
    unknown_markers = [
        "no hydrogen compatibility data",
        "insufficient data",
        "data gap",
        "not available",
        "not listed",
        "treat compatibility as unknown",
        "cannot be inferred",
    ]
    prohibited_markers = [
        "do not use",
        "not recommended",
        "incompatible",
        "prohibited",
        "severe embrittlement",
        "class d",
    ]
    caution_markers = [
        "caution",
        "limited",
        "moderate",
        "class b",
        "class c",
        "requires testing",
        "qualification testing",
    ]
    ok_markers = [
        "compatible",
        "acceptable",
        "recommended",
        "class a",
    ]

    if any(marker in text for marker in unknown_markers):
        return AnswerSeverity.UNKNOWN
    if any(marker in text for marker in prohibited_markers):
        return AnswerSeverity.PROHIBITED
    if any(marker in text for marker in caution_markers):
        return AnswerSeverity.CAUTION
    if any(marker in text for marker in ok_markers):
        return AnswerSeverity.OK
    return AnswerSeverity.UNKNOWN


def _extract_evidence(answer: str) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    seen: set[tuple[str, str]] = set()
    for match in _CITATION_PATTERN.finditer(answer):
        source = match.group(1).strip()
        page = match.group(2).strip()
        key = (source, page)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            EvidenceItem(
                source_id=source,
                location=f"p. {page}",
                summary=f"Model-cited source ({source}, p. {page})",
            )
        )
    return items


def _validate_model_answer(answer: str) -> tuple[bool, str]:
    if not (answer or "").strip():
        return False, "empty_response"
    if len(answer.strip()) < 40:
        return False, "response_too_short"
    if not _extract_evidence(answer):
        return False, "missing_page_citation"
    return True, "ok"


def _query_temp_model(question: str) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("OpenAI SDK missing. Install with: pip install openai") from exc

    client = OpenAI()
    response = client.responses.create(
        model=_get_model_id(),
        instructions=_SYSTEM_PROMPT,
        input=question,
        temperature=0.0,
    )
    return _extract_response_text(response)


_HAIKU_REWRITE_SYSTEM = (
    "You are Mira, an aerospace hydrogen materials compatibility assistant.\n"
    "Rewrite the deterministic decision below into concise, engineer-facing text.\n"
    "Do not change the classification, material, condition, or technical facts.\n"
    "Do not introduce new sources or numbers.\n"
    "Policy semantics you must preserve:\n"
    "- H2/He <= 0.75: disqualifying (prohibited).\n"
    "- H2/He >= 0.76: in-range for use with engineering review (caution), not a failure condition.\n"
    "Do not frame >=0.76 as a bad exceedance, violation, or disqualifier.\n"
    "Prefer wording like 'meets the 0.76 screening threshold for use with engineering judgment'.\n"
    "Do not infer extra operating context (e.g., cryogenic/high-temperature) unless explicitly stated.\n"
    "Output plain text only (no markdown, no bold, no section symbols).\n"
    "Use exactly this template and labels:\n"
    "Classification: <Caution|Prohibited|Unknown|Ok>\n"
    "Material: <material and condition>\n"
    "Operating Conditions: <pressure psia>, <temperature K>\n"
    "Summary: <1 short paragraph>\n\n"
    "The following engineering review is suggested:\n"
    "• <bullet 1>\n"
    "• <bullet 2>\n"
    "• <bullet 3>"
)


def _rewrite_with_haiku(
    *,
    material: str,
    condition: Optional[str],
    classification: AnswerSeverity,
    rationale: str,
    pressure_psia: float,
    temperature_k: float,
) -> str:
    model = _get_haiku_model_id()
    condition_text = condition.strip() if condition else "none"
    user_prompt = (
        f"classification: {classification.value}\n"
        f"material: {material}\n"
        f"condition: {condition_text}\n"
        f"pressure_psia: {pressure_psia}\n"
        f"temperature_k: {temperature_k}\n"
        f"deterministic_rationale: {rationale}\n"
    )

    response = llm_complete(
        system=_HAIKU_REWRITE_SYSTEM,
        user=user_prompt,
        model=model,
        max_tokens=320,
        temperature=0.2,
        timeout_s=45,
    )
    text = response.text.strip()
    if not text:
        raise RuntimeError("Haiku returned empty narrative.")
    return _normalize_haiku_narrative(
        raw_text=text,
        material=material,
        condition=condition,
        classification=classification,
        pressure_psia=pressure_psia,
        temperature_k=temperature_k,
        fallback_summary=rationale,
    )


def _format_psia(value: float) -> str:
    if abs(value - round(value)) < 0.01:
        return f"{int(round(value))} psia"
    return f"{value:.1f} psia"


def _format_kelvin(value: float) -> str:
    return f"{int(round(value))} K"


def _extract_review_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines:
        item = None
        if line.startswith("•"):
            item = line.lstrip("•").strip()
        elif re.match(r"^[-*]\s+", line):
            item = re.sub(r"^[-*]\s+", "", line).strip()
        if item:
            bullets.append(item)

    if not bullets and "•" in text:
        for part in text.split("•"):
            item = part.strip()
            if item and not _ENGINEERING_REVIEW_HEADING_RE.search(item):
                bullets.append(item)

    cleaned: list[str] = []
    seen: set[str] = set()
    for bullet in bullets:
        norm = bullet.lower()
        if norm in seen:
            continue
        seen.add(norm)
        cleaned.append(bullet.rstrip("."))
    return cleaned[:3]


def _extract_summary_text(text: str) -> str:
    heading_match = _ENGINEERING_REVIEW_HEADING_RE.search(text)
    before = text[: heading_match.start()].strip() if heading_match else text.strip()
    before = before.replace("**", "")
    lines = [ln.strip() for ln in before.splitlines() if ln.strip()]

    summary_parts: list[str] = []
    in_summary = False
    for line in lines:
        lower = line.lower()
        if lower.startswith("classification:") or lower.startswith("material:") or lower.startswith("operating conditions:"):
            continue
        if lower.startswith("summary:"):
            in_summary = True
            payload = line.split(":", 1)[1].strip()
            if payload:
                summary_parts.append(payload)
            continue
        if in_summary:
            summary_parts.append(line)

    if not summary_parts:
        summary_parts = [ln for ln in lines if not _ENGINEERING_REVIEW_HEADING_RE.search(ln)]

    summary = " ".join(summary_parts)
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary


def _normalize_haiku_narrative(
    *,
    raw_text: str,
    material: str,
    condition: Optional[str],
    classification: AnswerSeverity,
    pressure_psia: float,
    temperature_k: float,
    fallback_summary: str,
) -> str:
    material_line = material.strip()
    if condition and condition.strip():
        material_line = f"{material_line} ({condition.strip()})"

    summary = _extract_summary_text(raw_text)
    if not summary:
        summary = fallback_summary.strip()

    bullets = _extract_review_bullets(raw_text)
    if len(bullets) < 3:
        defaults = [
            "Confirm stress state and loading profile align with the assessed embrittlement severity",
            "Verify fracture mechanics acceptance criteria for the specified pressure and temperature envelope",
            "Establish inspection and maintenance intervals appropriate to this classification",
        ]
        for default in defaults:
            if len(bullets) >= 3:
                break
            if default.lower() not in {b.lower() for b in bullets}:
                bullets.append(default)
    bullets = bullets[:3]

    return (
        f"Classification: {classification.value.capitalize()}\n"
        f"Material: {material_line}\n"
        f"Operating Conditions: {_format_psia(pressure_psia)}, {_format_kelvin(temperature_k)}\n"
        f"Summary: {summary}\n\n"
        "The following engineering review is suggested:\n"
        f"• {bullets[0]}\n"
        f"• {bullets[1]}\n"
        f"• {bullets[2]}"
    )


def _maybe_rewrite_rationale(
    *,
    provider: str,
    material: str,
    condition: Optional[str],
    classification: AnswerSeverity,
    rationale: str,
    pressure_psia: float,
    temperature_k: float,
) -> tuple[str, Optional[str]]:
    if provider != "haiku":
        return rationale, None
    try:
        rewritten = _rewrite_with_haiku(
            material=material,
            condition=condition,
            classification=classification,
            rationale=rationale,
            pressure_psia=pressure_psia,
            temperature_k=temperature_k,
        )
        return rewritten, None
    except Exception as exc:
        return rationale, f"H2 temp haiku narrative unavailable; baseline response returned ({exc})."


def evaluate_h2_temp_compatibility(request: H2CompatibilityRequest) -> H2CompatibilityResponse:
    """
    Evaluate H2 compatibility through deterministic-gated fine-tuned model path.

    Falls back to baseline H2 engine if model call is unavailable.
    """
    provider = _get_nlg_provider()
    provider_model_id = _get_haiku_model_id() if provider == "haiku" else _get_model_id()

    material = request.material_key.strip()
    question = (request.question or f"Is {material} compatible with hydrogen service?").strip()
    model_id = provider_model_id

    known, canonical_hit = _get_material_index().contains(material)
    if not known:
        _log_coverage_gap(material=material, question=question, model_id=model_id)
        rationale = _fail_safe_rationale(material)
        return H2CompatibilityResponse(
            classification=AnswerSeverity.UNKNOWN,
            rationale=rationale,
            evidence=[
                EvidenceItem(
                    source_id="deterministic_material_gate",
                    location="evidence_index",
                    summary="Material not found in curated H2 evidence index.",
                )
            ],
            embrittlement_risk=None,
            h2_score=None,
            notes="H2 temp gate refused model call due to missing material evidence.",
        )

    # Deterministic baseline always runs for known materials and is used as
    # the safety anchor for final classification.
    baseline = evaluate_h2_compatibility(request)
    ratio_class, ratio_note = _ratio_screen(material, request.condition)
    screened_class = _combine_with_ratio_screen(baseline.classification, ratio_class)

    # If evidence is condition-dependent, avoid model assertions and ask for
    # clarification first unless ratio-screen gives a stricter deterministic
    # verdict.
    if baseline.needs_clarification:
        if screened_class != baseline.classification:
            deterministic_rationale = baseline.rationale
            if ratio_note:
                deterministic_rationale = f"{deterministic_rationale} {ratio_note}"
            deterministic_rationale, rewrite_note = _maybe_rewrite_rationale(
                provider=provider,
                material=material,
                condition=request.condition,
                classification=screened_class,
                rationale=deterministic_rationale,
                pressure_psia=request.pressure_psia,
                temperature_k=request.temperature_k,
            )
            deterministic_note = (
                f"H2 temp mode active; model={model_id}; "
                f"material_index_hit={canonical_hit or material}; "
                f"deterministic ratio screen applied ({baseline.classification.value}->{screened_class.value}) "
                "during clarification path."
            )
            if rewrite_note:
                deterministic_note = f"{deterministic_note}; {rewrite_note}"
            return H2CompatibilityResponse(
                classification=screened_class,
                rationale=deterministic_rationale,
                evidence=baseline.evidence,
                embrittlement_risk=baseline.embrittlement_risk,
                h2_score=baseline.h2_score,
                notes=f"{baseline.notes}; {deterministic_note}" if baseline.notes else deterministic_note,
                needs_clarification=False if screened_class == AnswerSeverity.PROHIBITED else baseline.needs_clarification,
                clarification_prompt=baseline.clarification_prompt,
                available_conditions=baseline.available_conditions,
                band_distribution=baseline.band_distribution,
            )

        clarification_note = (
            f"H2 temp mode active; model={model_id}; "
            f"material_index_hit={canonical_hit or material}; "
            "temp model bypassed pending heat-treatment clarification."
        )
        if ratio_note:
            clarification_note = f"{clarification_note}; {ratio_note}"
        baseline.notes = f"{baseline.notes}; {clarification_note}" if baseline.notes else clarification_note
        return baseline

    # If ratio screen tightens the baseline verdict, return deterministic
    # result without model text to avoid contradictory rationale.
    if screened_class != baseline.classification:
        deterministic_rationale = baseline.rationale
        if ratio_note:
            deterministic_rationale = f"{baseline.rationale} {ratio_note}"
        deterministic_rationale, rewrite_note = _maybe_rewrite_rationale(
            provider=provider,
            material=material,
            condition=request.condition,
            classification=screened_class,
            rationale=deterministic_rationale,
            pressure_psia=request.pressure_psia,
            temperature_k=request.temperature_k,
        )
        deterministic_note = (
            f"H2 temp mode active; model={model_id}; "
            f"material_index_hit={canonical_hit or material}; "
            f"deterministic ratio screen applied ({baseline.classification.value}->{screened_class.value})."
        )
        if rewrite_note:
            deterministic_note = f"{deterministic_note}; {rewrite_note}"
        return H2CompatibilityResponse(
            classification=screened_class,
            rationale=deterministic_rationale,
            evidence=baseline.evidence,
            embrittlement_risk=baseline.embrittlement_risk,
            h2_score=baseline.h2_score,
            notes=f"{baseline.notes}; {deterministic_note}" if baseline.notes else deterministic_note,
            needs_clarification=baseline.needs_clarification,
            clarification_prompt=baseline.clarification_prompt,
            available_conditions=baseline.available_conditions,
            band_distribution=baseline.band_distribution,
        )

    if provider == "haiku":
        deterministic_rationale = baseline.rationale
        if ratio_note:
            deterministic_rationale = f"{deterministic_rationale} {ratio_note}"
        try:
            rewritten = _rewrite_with_haiku(
                material=material,
                condition=request.condition,
                classification=baseline.classification,
                rationale=deterministic_rationale,
                pressure_psia=request.pressure_psia,
                temperature_k=request.temperature_k,
            )
        except Exception as exc:
            fallback_note = f"H2 temp haiku narrative unavailable; baseline response returned ({exc})."
            if ratio_note:
                fallback_note = f"{fallback_note}; {ratio_note}"
            baseline.notes = f"{baseline.notes}; {fallback_note}" if baseline.notes else fallback_note
            return baseline

        notes = (
            f"H2 temp mode active; nlg=haiku; model={model_id}; "
            f"material_index_hit={canonical_hit or material}; deterministic core used."
        )
        if ratio_note:
            notes = f"{notes} {ratio_note}"
        return H2CompatibilityResponse(
            classification=baseline.classification,
            rationale=rewritten,
            evidence=baseline.evidence,
            embrittlement_risk=baseline.embrittlement_risk,
            h2_score=baseline.h2_score,
            notes=notes,
            needs_clarification=baseline.needs_clarification,
            clarification_prompt=baseline.clarification_prompt,
            available_conditions=baseline.available_conditions,
            band_distribution=baseline.band_distribution,
        )

    try:
        answer = _query_temp_model(question)
    except Exception as exc:
        fallback_note = f"H2 temp model unavailable; fell back to baseline engine ({exc})."
        if ratio_note:
            fallback_note = f"{fallback_note}; {ratio_note}"
        baseline.notes = f"{baseline.notes}; {fallback_note}" if baseline.notes else fallback_note
        return baseline

    model_class = _classify_answer(answer)
    if model_class != baseline.classification:
        mismatch_note = (
            f"H2 temp model disagreement suppressed; model={model_class.value}, "
            f"baseline={baseline.classification.value}. "
            f"material_index_hit={canonical_hit or material}."
        )
        baseline.notes = f"{baseline.notes}; {mismatch_note}" if baseline.notes else mismatch_note
        return baseline

    valid, reason = _validate_model_answer(answer)
    if not valid:
        validator_note = (
            f"H2 temp model output rejected by validator ({reason}); "
            "baseline response returned."
        )
        baseline.notes = f"{baseline.notes}; {validator_note}" if baseline.notes else validator_note
        return baseline

    evidence = _extract_evidence(answer)

    notes = (
        f"H2 temp mode active; model={model_id}; "
        f"material_index_hit={canonical_hit or material}."
    )
    if ratio_note:
        notes = f"{notes} {ratio_note}"
    return H2CompatibilityResponse(
        classification=baseline.classification,
        rationale=answer,
        evidence=evidence,
        embrittlement_risk=None,
        h2_score=None,
        notes=notes,
    )


__all__ = ["evaluate_h2_temp_compatibility"]
