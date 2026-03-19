"""
Module: MIRA Chat — OCA Engine Adapter
Purpose: Adapts the OCA (Oxygen Compatibility Assessment) engine to the
         unified MIRA Chat interface per BS-SPEC-MIRA-CHAT-001-REV2.

OCA is case-ID-driven.  The adapter manages the full assessment lifecycle:
  1. Create a case  (create_case)
  2. Run precheck   (get_case_precheck) — if blocked, return refusal
  3. Get evidence   (get_case_evidence)
  4. Get decision   (get_case_decision)
  5. Store case_id in session context for follow-ups
  6. Wrap everything in a standard EngineEnvelope

Case records are engine-internal operational state, not user artifacts.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from mira.oca import (
    create_case,
    get_case_decision,
    get_case_evidence,
    get_case_precheck,
)
from mira.oca.models import (
    BlockedState,
    ComponentInput,
    CreateOcaCaseRequest,
    CreateOcaCaseResponse,
    FinalDisposition,
    IgnitionContextInput,
    MaterialInput,
    OcaDecisionResponse,
    OcaEvidenceResponse,
    OcaPrecheckResponse,
    OxygenServiceContextInput,
)

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode


# ---------------------------------------------------------------------------
# Disposition → Status mapping
# ---------------------------------------------------------------------------

_DISPOSITION_TO_STATUS: dict[FinalDisposition, Status] = {
    FinalDisposition.COMPATIBLE_AS_CONFIGURED: Status.PASS,
    FinalDisposition.COMPATIBLE_WITH_CONTROLS: Status.CONDITIONAL_PASS,
    FinalDisposition.REQUIRES_MUA: Status.CONDITIONAL_PASS,
    FinalDisposition.REQUIRES_ACCEPTANCE_TEST: Status.CONDITIONAL_PASS,
    FinalDisposition.REQUIRES_SUPPLEMENTAL_TESTING: Status.CONDITIONAL_PASS,
    FinalDisposition.INSUFFICIENT_EVIDENCE: Status.INSUFFICIENT_DATA,
    FinalDisposition.PROHIBITED: Status.FAIL,
}

# OCA authority standards referenced by the engine
_OCA_AUTHORITY_BASIS: list[str] = [
    "NASA-STD-6001B",
    "NASA-STD-6016C",
    "NASA-TM-2019-220137",
    "ASTM G94",
    "ASTM G63",
]


def _disposition_to_status(disposition: FinalDisposition) -> Status:
    return _DISPOSITION_TO_STATUS.get(disposition, Status.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# OCA Adapter
# ---------------------------------------------------------------------------


class OcaAdapter(EngineAdapter):
    """
    OCA case-lifecycle adapter.

    Supported tasks: ``answer_only`` — the adapter runs the full OCA
    assessment pipeline (create → precheck → evidence → decision) and
    returns a read-only envelope.  No artifacts are persisted beyond the
    in-process case store.
    """

    engine_id: str = "oca"
    engine_version: str = "1.0.0"
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """
        Run the full OCA assessment lifecycle and return a normalised envelope.

        Expected keys in *parsed_input*:

        - ``service_context`` (dict): maps to OxygenServiceContextInput fields
        - ``materials`` (list[dict]): each item maps to MaterialInput fields
        - ``components`` (list[dict], optional): maps to ComponentInput fields
        - ``ignition_context`` (dict, optional): maps to IgnitionContextInput fields
        """
        try:
            request = self._build_case_request(parsed_input)
        except Exception as exc:
            return self.wrap_error(exc=exc)

        try:
            # --- Step 1: Create case ---
            create_resp = await self._run_sync(create_case, request)

            case_id = create_resp.case_id

            # --- Step 2: Precheck ---
            precheck_resp = await self._run_sync(get_case_precheck, case_id)

            # If any blocked state has severity "red" we refuse immediately
            if self._has_blocking_refusal(precheck_resp):
                return self._build_refusal_envelope(case_id, precheck_resp)

            # --- Step 3: Evidence ---
            evidence_resp = await self._run_sync(get_case_evidence, case_id)

            # --- Step 4: Decision ---
            decision_resp = await self._run_sync(get_case_decision, case_id)

            # --- Step 5: Persist case_id in session for follow-ups ---
            # Case records are engine-internal operational state, not user artifacts.
            session_context["oca_case_id"] = case_id
            session_context["oca_revision"] = decision_resp.revision

            # --- Step 6: Wrap in envelope ---
            return self._build_success_envelope(
                case_id=case_id,
                create_resp=create_resp,
                precheck_resp=precheck_resp,
                evidence_resp=evidence_resp,
                decision_resp=decision_resp,
            )

        except KeyError as exc:
            return self.wrap_refusal(reason=f"OCA case not found: {exc}")
        except Exception as exc:
            return self.wrap_error(exc=exc)

    async def follow_up(
        self,
        session_context: dict[str, Any],
        query: str,
    ) -> EngineEnvelope:
        """
        Handle a follow-up question for an existing OCA case.

        Re-fetches evidence and decision from the existing case_id stored
        in *session_context*.
        """
        case_id = session_context.get("oca_case_id")
        if not case_id:
            return self.wrap_refusal(
                reason=(
                    "No active OCA case in this session. "
                    "Please start a new assessment first."
                ),
            )

        try:
            precheck_resp = await self._run_sync(get_case_precheck, case_id)
            evidence_resp = await self._run_sync(get_case_evidence, case_id)
            decision_resp = await self._run_sync(get_case_decision, case_id)

            return self._build_success_envelope(
                case_id=case_id,
                create_resp=None,
                precheck_resp=precheck_resp,
                evidence_resp=evidence_resp,
                decision_resp=decision_resp,
            )

        except KeyError:
            return self.wrap_refusal(
                reason=f"OCA case '{case_id}' no longer exists in the case store.",
            )
        except Exception as exc:
            return self.wrap_error(exc=exc)

    # ------------------------------------------------------------------
    # Internal: request construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_case_request(parsed_input: dict[str, Any]) -> CreateOcaCaseRequest:
        """Convert orchestrator-parsed input into a CreateOcaCaseRequest."""
        service_raw = parsed_input.get("service_context", {})
        materials_raw = parsed_input.get("materials", [])
        components_raw = parsed_input.get("components", [])
        ignition_raw = parsed_input.get("ignition_context", {})
        case_name = parsed_input.get("case_name")
        free_text = parsed_input.get("free_text_intake")

        if not materials_raw:
            raise ValueError(
                "OCA assessment requires at least one material. "
                "Provide a 'materials' list in the parsed input."
            )

        service_context = OxygenServiceContextInput(**service_raw)
        materials = [MaterialInput(**m) for m in materials_raw]
        components = [ComponentInput(**c) for c in components_raw]
        ignition_context = IgnitionContextInput(**ignition_raw)

        return CreateOcaCaseRequest(
            case_name=case_name,
            free_text_intake=free_text,
            service_context=service_context,
            materials=materials,
            components=components,
            ignition_context=ignition_context,
        )

    # ------------------------------------------------------------------
    # Internal: blocking-state detection
    # ------------------------------------------------------------------

    @staticmethod
    def _has_blocking_refusal(precheck: OcaPrecheckResponse) -> bool:
        """True if any blocked state has severity 'red' (hard block)."""
        return any(
            bs.severity == "red" for bs in precheck.blocked_states
        )

    # ------------------------------------------------------------------
    # Internal: envelope builders
    # ------------------------------------------------------------------

    def _build_refusal_envelope(
        self,
        case_id: str,
        precheck: OcaPrecheckResponse,
    ) -> EngineEnvelope:
        """Build a REFUSE envelope from precheck blocked states."""
        blocking = [
            bs for bs in precheck.blocked_states if bs.severity == "red"
        ]
        details = "; ".join(
            f"[{bs.code.value if bs.code else 'UNKNOWN'}] {bs.detail or ''}"
            for bs in blocking
        )
        hints = [
            bs.resolution_hint
            for bs in blocking
            if bs.resolution_hint
        ]

        return self.wrap_envelope(
            status=Status.REFUSE,
            response_text=(
                f"OCA assessment blocked for case {case_id}: {details}"
            ),
            missing_inputs=[
                field
                for bs in blocking
                for field in bs.missing_fields
            ],
            recommended_actions=hints,
            domain_payload={
                "case_id": case_id,
                "blocked_states": [
                    bs.model_dump(mode="json") for bs in blocking
                ],
            },
        )

    def _build_success_envelope(
        self,
        *,
        case_id: str,
        create_resp: Optional[CreateOcaCaseResponse],
        precheck_resp: OcaPrecheckResponse,
        evidence_resp: OcaEvidenceResponse,
        decision_resp: OcaDecisionResponse,
    ) -> EngineEnvelope:
        """Build a full success envelope from OCA lifecycle responses."""
        decision = decision_resp.decision
        disposition = decision.final_disposition
        status = _disposition_to_status(disposition)

        # Build human-readable response text
        response_parts = [
            f"**OCA Assessment — {disposition.value.replace('_', ' ').title()}**",
            "",
            decision.summary_rationale,
        ]

        # Append actions if present
        if decision.actions:
            response_parts.append("")
            response_parts.append("**Recommended actions:**")
            for action in decision.actions:
                response_parts.append(f"- {action.label}: {action.rationale}")

        # Append gaps
        if decision.unresolved_gaps:
            response_parts.append("")
            response_parts.append("**Unresolved gaps:**")
            for gap in decision.unresolved_gaps:
                response_parts.append(f"- {gap}")

        # Warnings from precheck
        warnings = precheck_resp.precheck_warnings
        if warnings:
            response_parts.append("")
            response_parts.append("**Warnings:**")
            for w in warnings:
                response_parts.append(f"- [{w.code}] {w.message}")

        response_text = "\n".join(response_parts)

        # Serialise evidence cards
        evidence_dicts = [
            card.model_dump(mode="json") for card in evidence_resp.evidence
        ]

        # Citations from triggered requirements
        citations = [
            req.citation
            for req in precheck_resp.triggered_requirements
            if req.triggered
        ]

        # Recommended actions from decision
        recommended_actions = [
            f"{a.label}: {a.rationale}" for a in decision.actions
        ]

        # Build audit lineage from precheck warnings + blocked states
        audit_lineage: list[dict[str, Any]] = []
        for bs in precheck_resp.blocked_states:
            audit_lineage.append({
                "stage": "precheck",
                "type": "blocked_state",
                "code": bs.code.value if bs.code else None,
                "detail": bs.detail,
                "severity": bs.severity,
            })
        for w in warnings:
            audit_lineage.append({
                "stage": "precheck",
                "type": "warning",
                "code": w.code,
                "message": w.message,
            })

        return self.wrap_envelope(
            status=status,
            response_text=response_text,
            mode=TaskMode.ANSWER_ONLY,
            authority_basis=_OCA_AUTHORITY_BASIS,
            citations=citations,
            evidence=evidence_dicts,
            assumptions=[],
            missing_inputs=evidence_resp.gaps,
            recommended_actions=recommended_actions,
            mua_disposition=disposition.value,
            audit_lineage=audit_lineage,
            domain_payload={
                "case_id": case_id,
                "revision": decision_resp.revision,
                "final_disposition": disposition.value,
                "overall_confidence": decision.overall_confidence,
                "authority_level": decision.authority_level.value,
                "kindling_chain_present": decision.kindling_chain_present,
                "reaction_effect": decision.reaction_effect,
                "governing_prohibition": decision.governing_prohibition,
                "acceptance_test_required": decision.acceptance_test_required,
                "reviewer_required": decision.reviewer_required,
                "mua_seed": decision.mua_seed,
                "blocked_states": [
                    bs.model_dump(mode="json")
                    for bs in precheck_resp.blocked_states
                ],
            },
        )

    # ------------------------------------------------------------------
    # Internal: sync-to-async bridge
    # ------------------------------------------------------------------

    @staticmethod
    async def _run_sync(func, *args, **kwargs):
        """
        Run a synchronous OCA engine function in the default executor.

        The OCA engine functions (create_case, get_case_precheck, etc.)
        are synchronous and use an RLock internally.  We offload them to
        a thread so we don't block the async event loop.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
