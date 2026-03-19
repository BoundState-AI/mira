"""
Module: MIRA Chat -- BSMH Bouncer Adapter
Purpose: Adapter bridging the BoundState Material Helper (BSMH) bouncer into
         the MIRA Chat unified envelope per BS-SPEC-MIRA-CHAT-001-REV2.

Calls ``mira.bsmh.bouncer.run_bouncer`` (async) for domain gating and
structured query extraction, then maps the ``BouncerResult`` to a standard
``EngineEnvelope``.

Used for the "help" intent, general M&P questions, and as a pre-filter
before routing to specialised engines.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from __future__ import annotations

__version__ = "1.0.0"
__safety_critical__ = False

import logging
from typing import Any, Optional

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import check
# ---------------------------------------------------------------------------

_BSMH_AVAILABLE: Optional[bool] = None


def _ensure_bsmh_imports() -> bool:
    """Verify that the BSMH bouncer module is importable."""
    global _BSMH_AVAILABLE
    if _BSMH_AVAILABLE is not None:
        return _BSMH_AVAILABLE
    try:
        from mira.bsmh.bouncer import run_bouncer  # noqa: F401
        from mira.bsmh.bouncer import heuristic_bouncer  # noqa: F401
        from mira.bsmh.models import BouncerResult, BSMHStructuredQuery  # noqa: F401

        _BSMH_AVAILABLE = True
    except Exception as exc:
        LOGGER.warning("BSMH bouncer not available: %s", exc)
        _BSMH_AVAILABLE = False
    return _BSMH_AVAILABLE


# ---------------------------------------------------------------------------
# Intent -> Chat Status mapping
# ---------------------------------------------------------------------------

_INTENT_DESCRIPTIONS: dict[str, str] = {
    "compatibility_check": "Material compatibility evaluation",
    "lookup": "Material / evidence lookup",
    "comparison": "Material comparison",
    "recommendation": "Material recommendation",
    "mua_precedent": "MUA precedent search",
    "general": "General M&P question",
}


# ---------------------------------------------------------------------------
# BSMH Adapter
# ---------------------------------------------------------------------------


class BSMHAdapter(EngineAdapter):
    """
    Adapter for the BSMH domain bouncer and structured query extractor.

    Expects ``parsed_input`` keys:

    * ``query`` (str, required) -- raw natural-language M&P question
    * ``use_llm`` (bool, optional) -- whether to use the full LLM bouncer
      (default True). When False, only the fast heuristic bouncer is used.
    """

    engine_id: str = "bsmh"
    engine_version: str = __version__
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Run the BSMH bouncer and return a normalised envelope."""
        if not _ensure_bsmh_imports():
            return self.wrap_error(
                exc=RuntimeError("BSMH bouncer module is not available on this instance."),
            )

        from mira.bsmh.bouncer import heuristic_bouncer, run_bouncer
        from mira.bsmh.models import BouncerResult

        query = (parsed_input.get("query") or "").strip()
        if not query:
            return self.wrap_refusal(
                reason="A query is required for the BSMH material helper.",
            )

        use_llm = parsed_input.get("use_llm", True)

        try:
            if use_llm:
                result: BouncerResult = await run_bouncer(query)
            else:
                result = heuristic_bouncer(query)
        except Exception as exc:
            LOGGER.error("BSMH bouncer raised: %s", exc, exc_info=True)
            return self.wrap_error(exc=exc)

        return self._adapt_bouncer_result(result, query, session_context)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapt_bouncer_result(
        self,
        result: Any,  # BouncerResult
        query: str,
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Map a BouncerResult to an EngineEnvelope."""
        if result.status == "rejected":
            return self.wrap_envelope(
                status=Status.REFUSE,
                response_text=(
                    result.rejection_reason
                    or "This question is outside the scope of MIRA materials intelligence."
                ),
                domain_payload={
                    "bouncer_status": "rejected",
                    "bouncer_source": result.source,
                    "rejection_reason": result.rejection_reason,
                },
            )

        # status == "accepted"
        sq = result.structured_query  # BSMHStructuredQuery or None
        if sq is None:
            # Accepted but no structured query -- treat as a thin pass-through
            return self.wrap_envelope(
                status=Status.PASS,
                response_text="Query accepted by domain bouncer.",
                domain_payload={
                    "bouncer_status": "accepted",
                    "bouncer_source": result.source,
                },
            )

        # Populate session context for downstream adapters
        if sq.material:
            session_context["bsmh_material"] = sq.material
        if sq.materials:
            session_context["bsmh_materials"] = sq.materials
        if sq.environment:
            session_context["bsmh_environment"] = sq.environment
        if sq.intent:
            session_context["bsmh_intent"] = sq.intent

        # Build response text
        intent_label = _INTENT_DESCRIPTIONS.get(sq.intent, sq.intent)
        material_label = sq.material or "not specified"
        env_label = sq.environment or "not specified"

        lines: list[str] = [
            f"Query accepted: {intent_label}.",
            f"  Material: {material_label}",
        ]
        if sq.materials and len(sq.materials) > 1:
            lines.append(f"  All materials: {', '.join(sq.materials)}")
        lines.append(f"  Environment: {env_label}")
        if sq.pressure_psi is not None:
            lines.append(f"  Pressure: {sq.pressure_psi} psi")
        if sq.temperature_f is not None:
            lines.append(f"  Temperature: {sq.temperature_f} F")
        if sq.o2_pct is not None:
            lines.append(f"  O2 concentration: {sq.o2_pct}%")

        response_text = "\n".join(lines)

        # Evidence -- the structured query itself serves as extracted evidence
        evidence: list[dict[str, Any]] = [
            {
                "source_id": "BSMH-bouncer",
                "location": f"source={result.source}",
                "summary": f"Intent: {sq.intent}, material: {sq.material or 'none'}, "
                           f"environment: {sq.environment or 'none'}",
            }
        ]

        # Missing inputs
        missing: list[str] = []
        if not sq.material and sq.intent in ("compatibility_check", "comparison"):
            missing.append("Material name or identifier is required for this intent.")
        if not sq.environment and sq.intent == "compatibility_check":
            missing.append("Service environment (e.g. LOX, GH2) is recommended.")

        # Recommended actions based on intent
        actions: list[str] = []
        if sq.intent == "compatibility_check" and sq.environment:
            env_upper = (sq.environment or "").upper()
            if env_upper in {"LH2", "GH2", "HYDROGEN"}:
                actions.append(
                    "Consider routing to the H2 Knowledge Twin for detailed HEE evaluation."
                )
            elif env_upper in {"LOX", "GOX", "OXYGEN"}:
                actions.append(
                    "Consider routing to the O2 Knowledge Twin for oxygen compatibility."
                )

        # Domain payload with full structured query for orchestrator/frontend
        domain_payload: dict[str, Any] = {
            "bouncer_status": "accepted",
            "bouncer_source": result.source,
            "structured_query": sq.model_dump(),
        }

        return self.wrap_envelope(
            status=Status.PASS,
            response_text=response_text,
            evidence=evidence,
            missing_inputs=missing,
            recommended_actions=actions,
            domain_payload=domain_payload,
        )
