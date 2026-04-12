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


def _try_fetch_from_pg(
    raw_key: str, raw_text: str, provider: str, mem_key: str,
) -> Optional[ConditionResolution]:
    """Try to load a previously-resolved condition alias from PostgreSQL.

    WHY PG before LLM: LLM calls are expensive ($) and non-deterministic.
    If we've already resolved this condition label, reuse the stored result.
    The confidence threshold in _is_persisted_alias_usable() ensures we
    only reuse high-quality resolutions.

    Returns None if no usable alias is found.
    """
    backend = get_runtime_backend()
    _ensure_pg_table_if_needed()
    if backend not in {"pg", "hybrid"}:
        return None

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
            if _is_persisted_alias_usable(found) or provider == "off":
                with _CACHE_LOCK:
                    _MEM_CACHE[mem_key] = persisted
                return persisted
    except Exception as exc:
        LOGGER.warning("Condition alias fetch failed (%s).", exc)
    return None


def _resolve_via_llm_or_fallback(
    raw_key: str, raw_text: str, raw_condition: Optional[str],
    material_name: str, source_document: str, provider: str,
) -> ConditionResolution:
    """Resolve condition label via LLM provider, with deterministic fallback.

    WHY fallback chain: LLM providers can fail (rate limits, network, cost).
    The fallback produces a low-confidence result (0.35) that will be flagged
    for human review — never silently trusted.

    Provider "off" bypasses LLM entirely and returns a passthrough result
    with 0.4 confidence (appropriate for batch ingestion where LLM cost
    is prohibitive).
    """
    if provider == "off":
        return _coerce_resolution(
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

    prompt = _build_prompt(raw_text, raw_condition, material_name, source_document)
    try:
        payload, model = _resolve_via_provider(provider, prompt)
        return _coerce_resolution(
            raw_key=raw_key,
            raw_text=raw_text,
            provider=provider,
            model=model,
            payload=payload,
        )
    except Exception as exc:
        LOGGER.warning("Condition resolver %s failed for '%s': %s", provider, raw_text, exc)
        return _coerce_resolution(
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


def _persist_resolution(
    res: ConditionResolution, raw_key: str, raw_text: str,
    source_document: str, material_name: str, mem_key: str,
) -> None:
    """Persist resolution to PG (if enabled) and in-memory cache.

    WHY persist: Avoids re-resolving the same condition label on every
    BOK ingestion run. The PG table acts as a shared cache across
    workers and restarts.
    """
    backend = get_runtime_backend()
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


def resolve_condition_label(
    *,
    raw_condition: Optional[str],
    material_name: Optional[str],
    source_document: Optional[str],
) -> ConditionResolution:
    """Resolve a raw condition label to a canonical form.

    Pipeline (each step is a named function):
    1. Normalize — clean and key the input text
    2. Cache check — return immediately if already resolved in-memory
    3. PG fetch — check PostgreSQL for a previously-persisted resolution
    4. LLM resolve — call haiku/ollama provider (or passthrough if "off")
    5. Persist — store result in PG + in-memory cache for future calls
    """
    # Step 1: Normalize input.
    raw_condition = (raw_condition or "").strip()
    material_name = (material_name or "").strip()
    source_document = (source_document or "").strip()

    raw_text = raw_condition or material_name or _UNKNOWN_LABEL
    raw_key = _normalize_key(raw_text) or _UNKNOWN_LABEL.lower()
    if raw_key in _UNKNOWN_VALUES:
        raw_key = _UNKNOWN_LABEL.lower()
        raw_text = _UNKNOWN_LABEL

    # Step 2: In-memory cache check.
    provider = _condition_provider()
    mem_key = f"{provider}:{raw_key}"
    with _CACHE_LOCK:
        cached = _MEM_CACHE.get(mem_key)
    if cached:
        return cached

    # Step 3: Try PG-persisted alias.
    pg_result = _try_fetch_from_pg(raw_key, raw_text, provider, mem_key)
    if pg_result is not None:
        return pg_result

    # Step 4: Resolve via LLM or deterministic fallback.
    res = _resolve_via_llm_or_fallback(
        raw_key, raw_text, raw_condition, material_name, source_document, provider,
    )

    # Step 5: Persist to PG + cache.
    _persist_resolution(res, raw_key, raw_text, source_document, material_name, mem_key)
    return res
