"""
Module: MIRA Chat — Base Engine Adapter
Purpose: Abstract base class for all domain-engine adapters per BS-SPEC-MIRA-CHAT-001-REV2.

Every MIRA domain engine (OCA, H2, Galvanic, MUA, etc.) implements a
concrete subclass of EngineAdapter. The chat orchestrator dispatches to
adapters through a uniform interface so that routing, auditing, and
envelope construction are decoupled from engine internals.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from typing import Any, Optional

from .models import EngineEnvelope, SideEffectLevel, Status, TaskMode


class EngineAdapter(ABC):
    """
    Abstract base class for MIRA Chat engine adapters.

    Subclasses must set ``engine_id`` and implement ``execute`` (and
    optionally ``follow_up``).  Helper methods ``wrap_envelope``,
    ``wrap_refusal``, and ``wrap_error`` provide standardised envelope
    construction so adapters only need to worry about domain logic.
    """

    engine_id: str = "base"
    engine_version: str = "1.0.0"
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """
        Run the domain engine against *parsed_input* and return a
        normalised ``EngineEnvelope``.

        Parameters
        ----------
        parsed_input:
            Structured data extracted from the user's chat message by the
            orchestrator's intent parser.  Keys are engine-specific.
        session_context:
            Mutable dict carried across turns in the same session.
            Adapters may read or write keys (e.g. ``oca_case_id``) to
            maintain cross-turn state.

        Returns
        -------
        EngineEnvelope
        """
        ...

    async def follow_up(
        self,
        session_context: dict[str, Any],
        query: str,
    ) -> EngineEnvelope:
        """
        Handle a follow-up question within an existing session.

        Default implementation returns a refusal indicating follow-up is
        not supported.  Adapters that support conversational follow-up
        should override.
        """
        return self.wrap_refusal(
            reason=f"Follow-up queries are not yet supported by {self.engine_id}.",
        )

    # ------------------------------------------------------------------
    # Envelope helpers
    # ------------------------------------------------------------------

    def wrap_envelope(
        self,
        *,
        status: Status,
        response_text: str,
        mode: TaskMode = TaskMode.ANSWER_ONLY,
        authority_basis: Optional[list[str]] = None,
        citations: Optional[list[str]] = None,
        evidence: Optional[list[dict[str, Any]]] = None,
        assumptions: Optional[list[str]] = None,
        missing_inputs: Optional[list[str]] = None,
        recommended_actions: Optional[list[str]] = None,
        mua_disposition: Optional[str] = None,
        audit_lineage: Optional[list[dict[str, Any]]] = None,
        domain_payload: Optional[dict[str, Any]] = None,
    ) -> EngineEnvelope:
        """Build a fully populated EngineEnvelope from keyword arguments."""
        return EngineEnvelope(
            status=status,
            engine_id=self.engine_id,
            engine_version=self.engine_version,
            mode=mode,
            response_text=response_text,
            authority_basis=authority_basis or [],
            citations=citations or [],
            evidence=evidence or [],
            assumptions=assumptions or [],
            missing_inputs=missing_inputs or [],
            recommended_actions=recommended_actions or [],
            mua_disposition=mua_disposition,
            audit_lineage=audit_lineage or [],
            domain_payload=domain_payload or {},
        )

    def wrap_refusal(self, *, reason: str) -> EngineEnvelope:
        """Return a REFUSE envelope with the given *reason*."""
        return self.wrap_envelope(
            status=Status.REFUSE,
            response_text=reason,
        )

    def wrap_error(self, *, exc: BaseException) -> EngineEnvelope:
        """Return an ERROR envelope capturing exception details."""
        return self.wrap_envelope(
            status=Status.ERROR,
            response_text=f"Engine error in {self.engine_id}: {exc}",
            domain_payload={
                "error_type": type(exc).__name__,
                "error_detail": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
