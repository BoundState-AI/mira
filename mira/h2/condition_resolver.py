#!/usr/bin/env python3
"""
LLM-assisted, cache-backed condition normalization for H2 evidence records.

Design:
- Resolve raw condition/material text to a canonical condition label.
- Cache in PostgreSQL (h2_knowledge.condition_aliases) when runtime backend allows.
- Avoid per-request prompt churn by memoizing in-memory.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from mira.providers.llm_provider import complete as llm_complete, resolve_model
from mira.utils.json_extract import ExtractionError, extract_json

from .runtime_db import (
    ensure_condition_alias_table,
    fetch_condition_alias,
    get_runtime_backend,
    upsert_condition_alias,
)

LOGGER = logging.getLogger(__name__)

_UNKNOWN_LABEL = "Generic/Unknown"
_UNKNOWN_VALUES = {
    "",
    "unknown",
    "generic unknown",
    "none",
    "null",
    "na",
    "n/a",
    "not specified",
    "unspecified",
    "tbd",
    "tba",
}

_CACHE_LOCK = Lock()
_MEM_CACHE: dict[str, "ConditionResolution"] = {}
_PG_TABLE_READY = False

_KNOWN_CONDITION_DISPLAY: dict[str, str] = {
    "annealed": "Annealed",
    "aged": "Aged",
    "solution_treated": "Solution Treated",
    "solution_treated_aged": "Solution Treated + Aged",
    "normalized": "Normalized",
    "quenched_tempered": "Quenched & Tempered",
    "as_received": "As Received",
    "cold_worked": "Cold Worked",
    "cold_drawn": "Cold Drawn",
    "hot_rolled": "Hot Rolled",
    "hot_finished": "Hot Finished",
    "mill_annealed": "Mill Annealed",
    "peak_aged": "Peak Aged",
    "quenched": "Quenched",
    "tempered": "Tempered",
    "wrought": "Wrought",
    "cast": "Cast",
    "forged": "Forged",
    "sintered": "Sintered",
}

_KNOWN_CONDITION_ALIASES: dict[str, str] = {
    "ann": "annealed",
    "sta": "solution_treated_aged",
    "st": "solution_treated",
    "solution treated": "solution_treated",
    "solution treated aged": "solution_treated_aged",
    "solution treated + aged": "solution_treated_aged",
    "solution treated and aged": "solution_treated_aged",
    "quenched tempered": "quenched_tempered",
    "q&t": "quenched_tempered",
    "as received": "as_received",
    "cold worked": "cold_worked",
    "cold drawn": "cold_drawn",
    "hot rolled": "hot_rolled",
    "hot finished": "hot_finished",
    "mill annealed": "mill_annealed",
    "peak aged": "peak_aged",
}


@dataclass
class ConditionResolution:
    raw_key: str
    raw_text: str
    canonical_condition: str
    display_label: str
    is_condition: bool
    confidence: float
    resolver_provider: str
    resolver_model: str
    needs_review: bool


def _resolve_known_condition(*, raw_key: str, raw_text: str) -> Optional[ConditionResolution]:
    normalized_text = normalize_condition_key(raw_text)
    candidates = (
        raw_key,
        normalized_text,
        raw_key.replace(" ", "_"),
        normalized_text.replace(" ", "_"),
    )

    canonical: Optional[str] = None
    for candidate in candidates:
        if candidate in _KNOWN_CONDITION_DISPLAY:
            canonical = candidate
            break
        mapped = _KNOWN_CONDITION_ALIASES.get(candidate)
        if mapped:
            canonical = mapped
            break

    if not canonical:
        return None

    display = _KNOWN_CONDITION_DISPLAY[canonical]
    return ConditionResolution(
        raw_key=raw_key,
        raw_text=raw_text,
        canonical_condition=canonical,
        display_label=display,
        is_condition=True,
        confidence=1.0,
        resolver_provider="deterministic",
        resolver_model="known-condition",
        needs_review=False,
    )


def _normalize_key(value: str) -> str:
    text = (value or "").strip().lower()
    return " ".join(text.split())


def normalize_condition_key(value: str) -> str:
    """Public normalizer for alias-cache keys."""
    key = _normalize_key(value)
    if key in _UNKNOWN_VALUES:
        return _UNKNOWN_LABEL.lower()
    return key


def _is_unknown_text(value: str) -> bool:
    return _normalize_key(value) in _UNKNOWN_VALUES


def clear_condition_resolution_cache(raw_key: Optional[str] = None) -> int:
    """Clear in-memory condition cache globally or for one normalized raw key."""
    with _CACHE_LOCK:
        if raw_key is None:
            size = len(_MEM_CACHE)
            _MEM_CACHE.clear()
            return size

        norm = normalize_condition_key(raw_key)
        to_remove = [k for k in _MEM_CACHE if k.split(":", 1)[-1] == norm]
        for key in to_remove:
            _MEM_CACHE.pop(key, None)
        return len(to_remove)


def _condition_provider() -> str:
    env = (os.getenv("MIRA_H2_CONDITION_RESOLVER_PROVIDER") or "").strip().lower()
    if env in {"haiku", "ollama", "off"}:
        return env
    if (os.getenv("MIRA_H2_OLLAMA_URL") or "").strip():
        return "ollama"
    if (os.getenv("LLM_PROVIDER") or "").strip():
        return "haiku"
    return "off"


def _haiku_model() -> str:
    return (os.getenv("MIRA_H2_CONDITION_RESOLVER_HAIKU_MODEL") or resolve_model("haiku")).strip()


def _ollama_model() -> str:
    return (os.getenv("MIRA_H2_CONDITION_RESOLVER_OLLAMA_MODEL") or "llama3.1:8b").strip()


def _ollama_url() -> str:
    return (os.getenv("MIRA_H2_OLLAMA_URL") or "http://localhost:11434/api/generate").strip()


def _ensure_pg_table_if_needed() -> None:
    global _PG_TABLE_READY
    if _PG_TABLE_READY:
        return
    backend = get_runtime_backend()
    if backend not in {"pg", "hybrid"}:
        return
    try:
        ensure_condition_alias_table()
        _PG_TABLE_READY = True
    except Exception as exc:
        LOGGER.warning("Condition alias table setup failed; continuing without PG cache (%s).", exc)


def _extract_json_obj(text: str) -> dict:
    try:
        return extract_json(text, expect="object")
    except ExtractionError:
        return {}


_CONDITION_RESOLVER_SYSTEM = (
    "You normalize hydrogen-material heat-treatment condition labels.\n"
    "Return only JSON with keys:\n"
    "is_condition (boolean), canonical_condition (string), display_label (string), confidence (0..1), reason (string).\n\n"
    "Rules:\n"
    "- If input is not a heat-treatment/material condition, set is_condition=false and labels to Generic/Unknown.\n"
    "- Preserve explicit ST forms (e.g., ST 1900F).\n"
    "- Normalize obvious equivalents to stable labels (Annealed, Solution Treated + Aged, Solution Treated, etc.).\n"
    "- Do not invent pressure/load/test metadata as a condition.\n\n"
    "Respond with ONLY valid JSON. No markdown fences, preamble, or commentary."
)


def _build_prompt(raw_text: str, raw_condition: str, material_name: str, source_document: str) -> str:
    return (
        f"raw_text: {raw_text}\n"
        f"raw_condition_field: {raw_condition}\n"
        f"material_name_field: {material_name}\n"
        f"source_document: {source_document}\n"
    )


def _resolve_with_haiku(prompt: str) -> tuple[dict, str]:
    model = _haiku_model()
    response = llm_complete(
        system=_CONDITION_RESOLVER_SYSTEM,
        user=prompt,
        model=model,
        max_tokens=220,
        temperature=0.0,
        timeout_s=35,
    )
    return _extract_json_obj(response.text), response.model


def _resolve_with_ollama(prompt: str) -> tuple[dict, str]:
    model = _ollama_model()
    req = urllib.request.Request(
        _ollama_url(),
        data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = str(payload.get("response", ""))
    return _extract_json_obj(text), model


def _coerce_resolution(
    *,
    raw_key: str,
    raw_text: str,
    provider: str,
    model: str,
    payload: Optional[dict] = None,
) -> ConditionResolution:
    payload = payload or {}
    is_condition = bool(payload.get("is_condition", False))
    canonical = str(payload.get("canonical_condition", "")).strip()
    display = str(payload.get("display_label", "")).strip()
    confidence_raw = payload.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except Exception:
        confidence = 0.0

    if _is_unknown_text(raw_text):
        is_condition = False
        canonical = _UNKNOWN_LABEL
        display = _UNKNOWN_LABEL
        confidence = 1.0

    if not is_condition:
        if raw_text and not _is_unknown_text(raw_text):
            # Preserve raw signal instead of dropping potentially-valid variants.
            canonical = raw_text
            display = raw_text
            confidence = max(confidence, 0.5)
        else:
            canonical = _UNKNOWN_LABEL
            display = _UNKNOWN_LABEL
    if not canonical:
        canonical = display or _UNKNOWN_LABEL
    if not display:
        display = canonical or _UNKNOWN_LABEL

    needs_review = bool(confidence < 0.75 or display == _UNKNOWN_LABEL)
    return ConditionResolution(
        raw_key=raw_key,
        raw_text=raw_text,
        canonical_condition=canonical,
        display_label=display,
        is_condition=is_condition and display != _UNKNOWN_LABEL,
        confidence=confidence,
        resolver_provider=provider,
        resolver_model=model,
        needs_review=needs_review,
    )


def _is_persisted_alias_usable(found: dict) -> bool:
    if bool(found.get("human_verified")):
        return True
    label = str(found.get("display_label") or "").strip()
    conf = found.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.0
    except Exception:
        conf_f = 0.0
    if not label or label == _UNKNOWN_LABEL:
        return False
    return conf_f >= 0.75


def _resolve_via_provider(provider: str, prompt: str) -> tuple[dict, str]:
    if provider == "haiku":
        try:
            return _resolve_with_haiku(prompt)
        except Exception as haiku_exc:
            # Fallback to local Ollama to avoid dead-end when key/model is unavailable.
            try:
                payload, model = _resolve_with_ollama(prompt)
                return payload, f"{model} (fallback-from-haiku)"
            except Exception:
                raise haiku_exc
    if provider == "ollama":
        return _resolve_with_ollama(prompt)
    raise RuntimeError(f"Unknown condition resolver provider: {provider}")


def resolve_condition_label(
    *,
    raw_condition: Optional[str],
    material_name: Optional[str],
    source_document: Optional[str],
) -> ConditionResolution:
    raw_condition = (raw_condition or "").strip()
    material_name = (material_name or "").strip()
    source_document = (source_document or "").strip()

    raw_text = raw_condition or material_name or _UNKNOWN_LABEL
    raw_key = _normalize_key(raw_text) or _UNKNOWN_LABEL.lower()
    if raw_key in _UNKNOWN_VALUES:
        raw_key = _UNKNOWN_LABEL.lower()
        raw_text = _UNKNOWN_LABEL

    provider = _condition_provider()
    mem_key = f"{provider}:{raw_key}"
    with _CACHE_LOCK:
        cached = _MEM_CACHE.get(mem_key)
    if cached:
        return cached

    backend = get_runtime_backend()
    known = _resolve_known_condition(raw_key=raw_key, raw_text=raw_text)
    _ensure_pg_table_if_needed()
    if backend in {"pg", "hybrid"}:
        try:
            found = fetch_condition_alias(raw_key)
            if found:
                persisted = _coerce_resolution(
                    raw_key=raw_key,
                    raw_text=found.get("raw_text") or raw_text,
                    provider=str(found.get("resolver_provider") or "cache"),
                    model=str(found.get("resolver_model") or "cache"),
                    payload={
                        "is_condition": found.get("is_condition"),
                        "canonical_condition": found.get("canonical_condition"),
                        "display_label": found.get("display_label"),
                        "confidence": found.get("confidence"),
                    },
                )
                if bool(found.get("human_verified")):
                    with _CACHE_LOCK:
                        _MEM_CACHE[mem_key] = persisted
                    return persisted
                if known is not None:
                    res = known
                elif _is_persisted_alias_usable(found) or provider == "off":
                    with _CACHE_LOCK:
                        _MEM_CACHE[mem_key] = persisted
                    return persisted
        except Exception as exc:
            LOGGER.warning("Condition alias fetch failed (%s).", exc)

    if known is not None:
        res = known
    elif provider == "off":
        res = _coerce_resolution(
            raw_key=raw_key,
            raw_text=raw_text,
            provider="off",
            model="off",
            payload={
                "is_condition": bool(raw_condition),
                "canonical_condition": raw_condition or _UNKNOWN_LABEL,
                "display_label": raw_condition or _UNKNOWN_LABEL,
                "confidence": 0.4 if raw_condition else 1.0,
            },
        )
    else:
        prompt = _build_prompt(raw_text, raw_condition, material_name, source_document)
        try:
            payload, model = _resolve_via_provider(provider, prompt)
            res = _coerce_resolution(
                raw_key=raw_key,
                raw_text=raw_text,
                provider=provider,
                model=model,
                payload=payload,
            )
        except Exception as exc:
            LOGGER.warning("Condition resolver %s failed for '%s': %s", provider, raw_text, exc)
            res = _coerce_resolution(
                raw_key=raw_key,
                raw_text=raw_text,
                provider=provider,
                model="fallback",
                payload={
                    "is_condition": bool(raw_condition),
                    "canonical_condition": raw_condition or _UNKNOWN_LABEL,
                    "display_label": raw_condition or _UNKNOWN_LABEL,
                    "confidence": 0.35 if raw_condition else 1.0,
                },
            )

    if backend in {"pg", "hybrid"}:
        try:
            upsert_condition_alias(
                raw_key=raw_key,
                raw_text=raw_text,
                canonical_condition=res.canonical_condition,
                display_label=res.display_label,
                is_condition=res.is_condition,
                confidence=res.confidence,
                resolver_provider=res.resolver_provider,
                resolver_model=res.resolver_model,
                source_document=source_document or None,
                material_name=material_name or None,
                details_jsonb={"needs_review": res.needs_review},
            )
        except Exception as exc:
            LOGGER.warning("Condition alias upsert failed (%s).", exc)

    with _CACHE_LOCK:
        _MEM_CACHE[mem_key] = res
    return res
