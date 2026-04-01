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
import re
from functools import lru_cache
from pathlib import Path
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

_MPR_PATTERN = re.compile(r"\bMPR[-\s]?(\d{1,3})\b", re.IGNORECASE)
_MP_PLAN_PATTERN = re.compile(
    r"\b(?:m[& ]?p\s+plan|materials?\s+(?:and|&)\s+process(?:es)?\s+plan)\b",
    re.IGNORECASE,
)
_STATUS_FIELD_PATTERN = re.compile(
    r"(?P<label>Status|What this means|Why flagged|Evidence on file|What you should do|Quick actions):\s*"
    r"(?P<value>.*?)(?=(?:\n|\r|\s)+(?:Status|What this means|Why flagged|Evidence on file|"
    r"What you should do|Quick actions):|$)",
    re.IGNORECASE | re.DOTALL,
)
_POLYMER_PATTERN = re.compile(
    r"\b(?:kapton|polyimide|ptfe|teflon|peek|vespel|viton|kalrez|epdm|silicone|"
    r"fluorosilicone|kel-?f|nylon|delrin|ultem)\b",
    re.IGNORECASE,
)
_METAL_PATTERN = re.compile(
    r"\b(?:al(?:uminum|uminium)?|steel|stainless|cres|inconel|monel|hastelloy|haynes|"
    r"titanium|ti-?\d|cda\s*\d|a-286|mp35n|\d{3,4}l?)\b",
    re.IGNORECASE,
)
_TRIGGER_LABELS = {
    "metallic_material": "metallic materials",
    "composite_material": "composite materials",
    "polymeric_material": "polymeric materials",
    "nonmetallic_material": "nonmetallic materials",
}


@lru_cache(maxsize=1)
def _load_mpr_records() -> dict[int, Any]:
    from mira.compliance.models.mpr import create_mpr_index_from_yaml

    yaml_path = Path(__file__).resolve().parents[2] / "compliance" / "data" / "mprs_6016c.yaml"
    index = create_mpr_index_from_yaml(str(yaml_path))
    return dict(index.records)


def _extract_mpr_number(text: str) -> int | None:
    match = _MPR_PATTERN.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_status_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _STATUS_FIELD_PATTERN.finditer(text):
        label = match.group("label").strip().lower()
        value = re.sub(r"\s+", " ", match.group("value").strip(" .\n\r\t"))
        if value:
            fields[label] = value
    return fields


def _infer_material_family(material: str | None) -> str | None:
    if not material:
        return None
    if _POLYMER_PATTERN.search(material):
        return "polymer"
    if _METAL_PATTERN.search(material):
        return "metal"
    return None


def _format_triggers(triggers: list[str]) -> str:
    if not triggers:
        return "not specified"
    labels = [_TRIGGER_LABELS.get(trigger, trigger.replace("_", " ")) for trigger in triggers]
    return ", ".join(labels)


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

        return self._adapt_bouncer_result(result, query, parsed_input, session_context)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapt_bouncer_result(
        self,
        result: Any,  # BouncerResult
        query: str,
        parsed_input: dict[str, Any],
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

        special_answer = self._maybe_build_grounded_answer(query, sq, parsed_input)
        if special_answer is not None:
            return special_answer

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

    def _maybe_build_grounded_answer(
        self,
        query: str,
        structured_query: Any,
        parsed_input: dict[str, Any],
    ) -> EngineEnvelope | None:
        mp_plan_answer = self._maybe_build_mp_plan_answer(query)
        if mp_plan_answer is not None:
            return mp_plan_answer

        mpr_answer = self._maybe_build_mpr_answer(query, structured_query, parsed_input)
        if mpr_answer is not None:
            return mpr_answer

        return None

    def _maybe_build_mp_plan_answer(self, query: str) -> EngineEnvelope | None:
        if not _MP_PLAN_PATTERN.search(query):
            return None

        lines = [
            "An M&P plan in MIRA is a five-step workflow.",
            "",
            "1. Create the session and set the program or vehicle context.",
            "2. Add the service environment or environments you care about.",
            "3. Add materials and map each one to a MAPTIS code if you have it.",
            "4. Run compute and answer the blocking questions, especially tailoring, closure, quantity, and precedent prompts.",
            "5. Generate the artifacts after the blockers are cleared.",
            "",
            "If you are looking at a requirement card, the practical next move is usually not to upload a random document. "
            "Either answer the blocking question directly or attach the citation, analysis, or test evidence tied to the exact material and environment.",
        ]

        return self.wrap_envelope(
            status=Status.PASS,
            response_text="\n".join(lines),
            authority_basis=["MIRA MP Plan workflow"],
            citations=["MIRA MP Plan workflow"],
            recommended_actions=[
                "Start by defining the environment before adding materials.",
                "Map each material to MAPTIS before treating the plan as review-ready.",
                "Clear tailoring and closure blockers before generating artifacts.",
            ],
            domain_payload={
                "answer_type": "mp_plan_workflow",
            },
        )

    def _maybe_build_mpr_answer(
        self,
        query: str,
        structured_query: Any,
        parsed_input: dict[str, Any],
    ) -> EngineEnvelope | None:
        mpr_number = _extract_mpr_number(query)
        if mpr_number is None:
            return None

        try:
            record = _load_mpr_records().get(mpr_number)
        except Exception as exc:
            LOGGER.warning("Failed to load MPR index for BSMH answer: %s", exc)
            return None

        if record is None:
            return None

        fields = _extract_status_fields(query)
        material = (
            structured_query.material
            or parsed_input.get("material_designation")
            or parsed_input.get("material")
        )
        family = _infer_material_family(str(material) if material else None)
        applies_to = _format_triggers(list(getattr(record, "applicability_triggers", []) or []))

        lines = [
            f"{record.mpr_id} is NASA-STD-6016C section {record.section}: {record.title}.",
            str(record.shall_text).strip(),
            f"This requirement is tagged for {applies_to}.",
        ]

        if fields:
            status_value = fields.get("status")
            meaning = fields.get("what this means")
            why_flagged = fields.get("why flagged")
            evidence = fields.get("evidence on file")
            next_step = fields.get("what you should do")
            quick_actions = fields.get("quick actions")

            if status_value:
                lines.append("")
                lines.append(
                    f'For the card you pasted, "{status_value}" means the engine did not close the requirement from the evidence currently attached.'
                )
            if meaning:
                lines.append(meaning)
            if why_flagged:
                lines.append(f"Why it was flagged: {why_flagged}")
            if evidence:
                lines.append(f"Current authority on file: {evidence}")
            if next_step:
                lines.append(f"What to do next: {next_step}")
            if quick_actions:
                lines.append(f"Available closure paths: {quick_actions}")

        if material:
            lines.append("")
            if family == "polymer" and "metallic_material" in list(record.applicability_triggers or []):
                lines.append(
                    f"Material check: {material} reads as a polymer/nonmetal. "
                    f"Because {record.mpr_id} is keyed to metallic materials in the local requirement index, "
                    "that suggests the requirement may be non-applicable to a Kapton-only part unless the card is really pointing at adjacent metallic structural hardware."
                )
            elif family == "metal":
                lines.append(
                    f"Material check: {material} reads as metallic, so {record.mpr_id} is at least directionally applicable and needs a real closure basis."
                )

        recommended_actions = [
            "If the part is metallic structural hardware, attach alloy/condition-specific certs plus the cited analysis or test basis.",
            "If the part is nonmetallic, document non-applicability or the tailoring/closure rationale instead of leaving the card unresolved.",
        ]

        return self.wrap_envelope(
            status=Status.PASS,
            response_text="\n".join(lines),
            authority_basis=[f"NASA-STD-6016C §{record.section}", record.mpr_id],
            citations=[f"NASA-STD-6016C §{record.section}", record.mpr_id],
            evidence=[
                {
                    "source_id": record.mpr_id,
                    "section": record.section,
                    "title": record.title,
                    "shall_text": record.shall_text,
                }
            ],
            recommended_actions=recommended_actions,
            domain_payload={
                "answer_type": "mpr_lookup",
                "mpr_id": record.mpr_id,
                "section": record.section,
                "material": material,
                "material_family_inference": family,
                "status_fields": fields,
            },
        )
