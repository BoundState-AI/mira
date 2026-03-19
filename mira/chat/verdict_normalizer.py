"""
Module: MIRA Chat — Verdict Normalizer
Purpose: Wraps raw engine output in the standard EngineEnvelope per BS-SPEC-MIRA-CHAT-001-REV2.

Takes heterogeneous engine results and normalises them into the unified
envelope contract so that the formatter, audit writer, and frontend never
need to know which engine produced the answer.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from .models import EngineEnvelope, Status, TaskMode

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine-specific status mapping
# ---------------------------------------------------------------------------

# Engines may return bespoke status strings. This table maps them to the
# canonical Status enum. Keys are lowercased for resilient matching.
_STATUS_ALIASES: dict[str, Status] = {
    "pass": Status.PASS,
    "passed": Status.PASS,
    "compatible": Status.PASS,
    "ok": Status.PASS,
    "conditional_pass": Status.CONDITIONAL_PASS,
    "conditional": Status.CONDITIONAL_PASS,
    "conditionally_compatible": Status.CONDITIONAL_PASS,
    "fail": Status.FAIL,
    "failed": Status.FAIL,
    "incompatible": Status.FAIL,
    "not_compatible": Status.FAIL,
    "refuse": Status.REFUSE,
    "refused": Status.REFUSE,
    "insufficient_data": Status.INSUFFICIENT_DATA,
    "insufficient": Status.INSUFFICIENT_DATA,
    "missing_data": Status.INSUFFICIENT_DATA,
    "error": Status.ERROR,
    "internal_error": Status.ERROR,
}


def _resolve_status(raw_status: Any) -> Status:
    """Map a raw status value to the canonical Status enum.

    Accepts a Status instance, a matching string, or a known alias.
    Falls back to ERROR for unrecognised values.
    """
    if isinstance(raw_status, Status):
        return raw_status
    raw = str(raw_status).strip().lower()
    if raw in {s.value.lower() for s in Status}:
        return Status(raw_status.strip().upper())
    return _STATUS_ALIASES.get(raw, Status.ERROR)


def _resolve_mode(raw_mode: Any) -> TaskMode:
    """Map a raw mode value to TaskMode, defaulting to ANSWER_ONLY."""
    if isinstance(raw_mode, TaskMode):
        return raw_mode
    raw = str(raw_mode).strip().lower()
    for member in TaskMode:
        if raw == member.value.lower():
            return member
    return TaskMode.ANSWER_ONLY


def _content_hash(data: dict[str, Any]) -> str:
    """Deterministic SHA-256 fingerprint of the envelope payload."""
    import json

    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_verdict(
    raw_output: dict[str, Any],
    engine_id: str,
    mode: str,
    request_id: str,
) -> EngineEnvelope:
    """
    Normalise heterogeneous engine output into a standard EngineEnvelope.

    Parameters
    ----------
    raw_output:
        Dictionary returned by the domain engine. Field names vary by engine.
    engine_id:
        Identifier of the engine that produced the result (e.g. "oca", "h2").
    mode:
        Task mode string — mapped to TaskMode enum.
    request_id:
        Opaque identifier for the originating chat request (used in lineage).

    Returns
    -------
    EngineEnvelope
        A fully populated, normalised envelope ready for formatting and audit.
    """
    now = datetime.now(timezone.utc)

    status = _resolve_status(raw_output.get("status", "error"))
    task_mode = _resolve_mode(mode)

    # Build response text — engines may use different keys
    response_text = (
        raw_output.get("response_text")
        or raw_output.get("summary")
        or raw_output.get("result_text")
        or raw_output.get("message")
        or ""
    )

    # Safe list extraction with fallback to empty lists
    def _list(key: str) -> list:
        val = raw_output.get(key)
        if isinstance(val, list):
            return val
        return []

    authority_basis = _list("authority_basis") or _list("standards")
    citations = _list("citations") or _list("references")
    evidence = _list("evidence")
    assumptions = _list("assumptions")
    missing_inputs = _list("missing_inputs") or _list("missing_data")
    recommended_actions = _list("recommended_actions") or _list("actions")

    # Engine version — fall back to "1.0.0"
    engine_version = str(raw_output.get("engine_version", "1.0.0"))

    # MUA disposition (OCA-specific)
    mua_disposition = raw_output.get("mua_disposition") or raw_output.get("disposition")

    # Domain payload — anything not captured by standard fields
    domain_payload: dict[str, Any] = raw_output.get("domain_payload", {})
    if not isinstance(domain_payload, dict):
        domain_payload = {}

    # Confidence values forwarded untouched when present
    for conf_key in (
        "routing_confidence",
        "extraction_confidence",
        "evidence_completeness",
        "verdict_confidence",
    ):
        if conf_key in raw_output and conf_key not in domain_payload:
            domain_payload[conf_key] = raw_output[conf_key]

    # Build audit lineage trace
    content_fingerprint = _content_hash(raw_output)
    audit_lineage = raw_output.get("audit_lineage", [])
    if not isinstance(audit_lineage, list):
        audit_lineage = []
    audit_lineage.append(
        {
            "stage": "verdict_normalizer",
            "timestamp": now.isoformat(),
            "request_id": request_id,
            "engine_id": engine_id,
            "content_hash": content_fingerprint,
        }
    )

    envelope = EngineEnvelope(
        status=status,
        engine_id=engine_id,
        engine_version=engine_version,
        mode=task_mode,
        response_text=response_text,
        authority_basis=authority_basis,
        citations=citations,
        evidence=evidence,
        assumptions=assumptions,
        missing_inputs=missing_inputs,
        recommended_actions=recommended_actions,
        mua_disposition=mua_disposition,
        audit_lineage=audit_lineage,
        domain_payload=domain_payload,
    )

    LOGGER.debug(
        "Normalised verdict: engine=%s status=%s mode=%s hash=%s",
        engine_id,
        status.value,
        task_mode.value,
        content_fingerprint,
    )
    return envelope
