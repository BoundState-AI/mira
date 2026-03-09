#!/usr/bin/env python3
"""Shared BSMS LLM runtime helpers for the active FORGE API path."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mira.providers.llm_provider import complete as llm_complete
from mira.providers.llm_provider import resolve_model


class BSMSRuntimePolicyError(RuntimeError):
    """Raised when required LLM-backed BSMS stages cannot run."""


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def llm_status(*, require_llm: bool | None = None) -> dict[str, Any]:
    """Return the effective FORGE BSMS LLM runtime policy."""
    provider = (os.environ.get("FORGE_LLM_PROVIDER") or os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    model = (
        os.environ.get("FORGE_BSMS_MODEL")
        or os.environ.get("FORGE_LLM_MODEL")
        or os.environ.get("LLM_SONNET_MODEL")
        or ("claude-sonnet-4-20250514" if provider == "anthropic" else resolve_model("sonnet"))
    ).strip()
    configured = True
    if provider == "anthropic":
        configured = bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())
    elif provider in {"openai-compat", "ollama"}:
        configured = bool((os.environ.get("OPENAI_API_KEY") or "").strip())

    enabled_default = _env_flag("FORGE_BSMS_ENABLE_LLM", True)
    effective_require_llm = require_llm if require_llm is not None else _env_flag("FORGE_BSMS_REQUIRE_LLM", True)

    return {
        "provider": provider,
        "configured": configured,
        "enabled": enabled_default and configured,
        "model": model,
        "require_llm": effective_require_llm,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(fenced)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload

    raise ValueError("LLM did not return a valid JSON object")


def complete_json(
    system: str,
    user: str,
    *,
    require_llm: bool | None = None,
    max_tokens: int = 900,
    temperature: float = 0.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute a FORGE BSMS JSON completion under the active runtime policy."""
    status = llm_status(require_llm=require_llm)
    if not status["enabled"]:
        raise BSMSRuntimePolicyError(
            "FORGE BSMS LLM runtime is unavailable. "
            f"provider={status['provider']} configured={status['configured']} enabled={status['enabled']}"
        )

    response = llm_complete(
        system=system,
        user=user,
        model=str(status["model"]),
        max_tokens=max_tokens,
        temperature=temperature,
        provider=str(status["provider"]),
    )
    return _extract_json_object(response.text), {
        "provider": status["provider"],
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
    }


def record_lineage(payload: dict[str, Any], *, lineage_dir: str | None = None) -> dict[str, Any]:
    """Persist a BSMS decision-lineage record to JSONL."""
    line_dir = Path(lineage_dir or os.environ.get("FORGE_BSMS_LINEAGE_DIR") or "./forge_runtime/lineage")
    line_dir.mkdir(parents=True, exist_ok=True)
    line_log = line_dir / "decision_lineage.jsonl"
    enriched = {
        **payload,
        "lineage_id": payload.get("lineage_id") or f"forge-bsms-{uuid4().hex}",
        "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "lineage_log": str(line_log.resolve()),
    }
    with line_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(enriched, default=str) + "\n")
    return enriched
