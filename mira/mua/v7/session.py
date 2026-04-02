"""MUA v7 Session Manager.

Manages server-side session state for the 5-step MUA wizard.
State persisted through the shared ``SessionStore`` from
``mira.core.session_store``.  Pydantic models as the serialization
layer — ``MuaSessionState.model_dump(mode="json")`` / ``model_validate()``.

Session lifecycle:
- Created on Step 1 completion (DEFINE)
- Updated at each step transition
- Can be saved/resumed at any point
- Finalized at Step 5
- Auto-abandoned after 30 days of inactivity

Step ordering and validation:
    DEFINE -> INVESTIGATE -> REVIEW -> DRAFT -> FINALIZE

Each step requires the previous step to be completed before advancing.
Backward navigation is allowed (engineer can revisit earlier steps),
but forward skips are blocked.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field

from .models import (
    CategoryRoutingResult,
    Center,
    DraftEdit,
    EnvironmentSpec,
    EvidenceStrengthResult,
    FinalizedMUA,
    InvestigationResult,
    MaterialResolution,
    MUADraft,
    ProcessParams,
    ReviewDecisions,
    SessionStatus,
    StepName,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step ordering
# ---------------------------------------------------------------------------

# Canonical step order. Index position defines the order.
_STEP_ORDER: list[StepName] = [
    StepName.DEFINE,
    StepName.INVESTIGATE,
    StepName.REVIEW,
    StepName.DRAFT,
    StepName.FINALIZE,
]

_STEP_INDEX: dict[StepName, int] = {step: idx for idx, step in enumerate(_STEP_ORDER)}


def _step_index(step: StepName) -> int:
    """Return the ordinal index of a step (0-based)."""
    return _STEP_INDEX[step]


# ---------------------------------------------------------------------------
# Session state model
# ---------------------------------------------------------------------------


class MuaSessionState(BaseModel):
    """Full session state -- serialized to/from PostgreSQL.

    In production the flat scalar fields map to regular columns and
    the complex nested objects are stored in JSONB columns.  The
    Pydantic model serves as the single serialization boundary so
    the rest of the codebase never touches raw dicts.
    """

    # -- Identity / metadata ------------------------------------------------
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    current_step: StepName = StepName.DEFINE
    status: SessionStatus = SessionStatus.ACTIVE
    center: Center = Center.MSFC

    # -- Step 1: Define -----------------------------------------------------
    material_input: Optional[str] = None
    material_resolution: Optional[MaterialResolution] = None
    environment: Optional[EnvironmentSpec] = None
    process_params: Optional[ProcessParams] = None
    application: Optional[str] = None
    program: Optional[str] = None
    hardware: Optional[str] = None
    miul_ref: Optional[str] = None
    approved_cat3_codes: Optional[list[str]] = None

    # -- Step 2: Investigate ------------------------------------------------
    investigation_result: Optional[InvestigationResult] = None

    # -- Step 3: Review -----------------------------------------------------
    review_decisions: Optional[ReviewDecisions] = None
    divergence_labels: list[dict] = Field(default_factory=list)  # Silent gold labels

    # -- Step 4: Draft ------------------------------------------------------
    draft: Optional[MUADraft] = None
    draft_metadata: Optional[dict] = None
    edit_history: list[DraftEdit] = Field(default_factory=list)
    fact_check_report: Optional[list] = None

    # -- Step 5: Finalize ---------------------------------------------------
    category_routing: Optional[CategoryRoutingResult] = None
    finalized_at: Optional[datetime] = None
    reviewer: Optional[str] = None
    applied_standard_version: str = "NASA-STD-6016C"
    dependency_links: list[str] = Field(default_factory=list)
    export_format: Optional[str] = None
    finalized_mua: Optional[FinalizedMUA] = None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class StepValidationError(Exception):
    """Raised when a step transition violates ordering rules."""


def _validate_step_advancement(
    session: MuaSessionState,
    to_step: StepName,
) -> None:
    """Ensure ``to_step`` is reachable from the current session state.

    Rules
    -----
    1. Backward navigation is always allowed (revisiting earlier steps).
    2. You may advance to the *next* step only -- no skipping.
    3. Each step has a gate predicate that must be satisfied before
       advancing past it.

    Raises
    ------
    StepValidationError
        If the transition is illegal.
    """
    current_idx = _step_index(session.current_step)
    target_idx = _step_index(to_step)

    # Backward navigation -- always okay.
    if target_idx <= current_idx:
        return

    # Forward skip detection -- only +1 allowed.
    if target_idx > current_idx + 1:
        raise StepValidationError(
            f"Cannot skip from {session.current_step.value!r} to "
            f"{to_step.value!r}.  Steps must be completed in order."
        )

    # Gate predicates for each forward transition.
    if to_step == StepName.INVESTIGATE:
        # Gate: DEFINE must have material + environment populated.
        if session.material_resolution is None:
            raise StepValidationError(
                "Cannot advance to INVESTIGATE: material has not been resolved.  "
                "Complete the DEFINE step first."
            )
        if session.environment is None:
            raise StepValidationError(
                "Cannot advance to INVESTIGATE: environment has not been specified.  "
                "Complete the DEFINE step first."
            )

    elif to_step == StepName.REVIEW:
        # Gate: INVESTIGATE must have produced a result.
        if session.investigation_result is None:
            raise StepValidationError(
                "Cannot advance to REVIEW: investigation has not been completed.  "
                "Complete the INVESTIGATE step first."
            )

    elif to_step == StepName.DRAFT:
        # Gate: REVIEW must have all items reviewed.
        if session.review_decisions is None:
            raise StepValidationError(
                "Cannot advance to DRAFT: no review decisions recorded.  "
                "Complete the REVIEW step first."
            )
        if not session.review_decisions.all_items_reviewed:
            raise StepValidationError(
                "Cannot advance to DRAFT: not all evidence items have been "
                "reviewed.  Complete reviewing all precedents, gaps, and "
                "conflicts before generating a draft."
            )

    elif to_step == StepName.FINALIZE:
        # Gate: DRAFT must exist.
        if session.draft is None:
            raise StepValidationError(
                "Cannot advance to FINALIZE: no draft has been generated.  "
                "Complete the DRAFT step first."
            )


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


class SessionManager:
    """Manages MUA v7 sessions.

    Persists session state through the shared ``SessionStore`` from
    ``mira.core.session_store``.  All data is serialized via
    ``MuaSessionState.model_dump(mode="json")`` and deserialized
    via ``model_validate()`` on every read — no process-local cache.

    Async methods are the primary API for FastAPI handlers and real
    async backends.  Sync wrappers remain available for tests and
    non-async callers.
    """

    _MODULE = "mua_v7"

    def __init__(self) -> None:
        from mira.core.session_store import get_session_store
        self._store = get_session_store()

    # -- sync/async bridge --------------------------------------------------

    @staticmethod
    def _run_sync(coro: Any) -> Any:
        """Execute an async coroutine synchronously for non-async callers."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "SessionManager sync methods cannot be used inside a running event loop. "
            "Use the async SessionManager methods instead."
        )

    # -- internal helpers ---------------------------------------------------

    async def _save_async(self, session: MuaSessionState) -> None:
        """Persist a session to the shared store."""
        from mira.core.session_store import save_model
        await save_model(self._MODULE, session.session_id, session, self._store)

    async def _load_async(self, session_id: str) -> Optional[MuaSessionState]:
        """Load a session from the shared store."""
        from mira.core.session_store import load_model
        return await load_model(self._MODULE, session_id, MuaSessionState, self._store)

    async def _load_all_keys_async(self) -> list[str]:
        """List all session keys from the shared store."""
        return await self._store.list_module_keys(self._MODULE)

    async def _load_all_async(self) -> list[MuaSessionState]:
        """Load all sessions from the shared store."""
        sessions: list[MuaSessionState] = []
        for key in await self._load_all_keys_async():
            session = await self._load_async(key)
            if session is not None:
                sessions.append(session)
        return sessions

    async def _get_async(self, session_id: str) -> MuaSessionState:
        """Return session or raise KeyError."""
        session = await self._load_async(session_id)
        if session is None:
            raise KeyError(f"Session {session_id!r} not found.")
        return session

    def _save(self, session: MuaSessionState) -> None:
        self._run_sync(self._save_async(session))

    def _load(self, session_id: str) -> Optional[MuaSessionState]:
        return self._run_sync(self._load_async(session_id))

    def _load_all_keys(self) -> list[str]:
        return self._run_sync(self._load_all_keys_async())

    def _load_all(self) -> list[MuaSessionState]:
        return self._run_sync(self._load_all_async())

    # -- CRUD ---------------------------------------------------------------

    async def acreate_session(
        self,
        created_by: Optional[str] = None,
        center: Center = Center.MSFC,
    ) -> MuaSessionState:
        """Create a new session and persist it."""
        now = datetime.utcnow()
        session = MuaSessionState(
            session_id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            created_by=created_by,
            center=center,
            current_step=StepName.DEFINE,
            status=SessionStatus.ACTIVE,
        )
        await self._save_async(session)
        logger.info(
            "Created MUA session %s for user=%s center=%s",
            session.session_id,
            created_by,
            center.value,
        )
        return session

    async def aget_session(self, session_id: str) -> Optional[MuaSessionState]:
        """Retrieve a session by ID, or ``None`` if not found."""
        session = await self._load_async(session_id)
        if session is None:
            logger.debug("Session %s not found", session_id)
        return session

    async def aupdate_session(
        self,
        session: MuaSessionState,
    ) -> MuaSessionState:
        """Persist updated session state.  Bumps ``updated_at``."""
        existing = await self._load_async(session.session_id)
        if existing is None:
            raise KeyError(
                f"Session {session.session_id!r} does not exist.  "
                f"Use create_session() first."
            )
        session.updated_at = datetime.utcnow()
        await self._save_async(session)
        logger.debug("Updated session %s (step=%s)", session.session_id, session.current_step.value)
        return session

    async def aadvance_step(
        self,
        session_id: str,
        to_step: StepName,
    ) -> MuaSessionState:
        """Validate and advance a session to the given step."""
        session = await self._load_async(session_id)
        if session is None:
            raise KeyError(f"Session {session_id!r} not found.")

        if session.status not in (SessionStatus.ACTIVE, SessionStatus.DRAFT_SAVED):
            raise ValueError(
                f"Session {session_id!r} has status {session.status.value!r} "
                f"and cannot transition steps.  Only ACTIVE or DRAFT_SAVED "
                f"sessions may advance."
            )

        _validate_step_advancement(session, to_step)

        previous_step = session.current_step
        session.current_step = to_step
        session.updated_at = datetime.utcnow()

        if to_step == StepName.FINALIZE:
            session.status = SessionStatus.FINALIZED
            session.finalized_at = datetime.utcnow()

        if to_step == StepName.DRAFT and session.status == SessionStatus.ACTIVE:
            session.status = SessionStatus.DRAFT_SAVED

        await self._save_async(session)
        logger.info(
            "Session %s advanced: %s -> %s",
            session_id,
            previous_step.value,
            to_step.value,
        )
        return session

    def create_session(
        self,
        created_by: Optional[str] = None,
        center: Center = Center.MSFC,
    ) -> MuaSessionState:
        return self._run_sync(self.acreate_session(created_by=created_by, center=center))

    def get_session(self, session_id: str) -> Optional[MuaSessionState]:
        return self._run_sync(self.aget_session(session_id))

    def update_session(self, session: MuaSessionState) -> MuaSessionState:
        return self._run_sync(self.aupdate_session(session))

    def advance_step(self, session_id: str, to_step: StepName) -> MuaSessionState:
        return self._run_sync(self.aadvance_step(session_id, to_step))

    # -- Queries ------------------------------------------------------------

    async def alist_sessions(
        self,
        created_by: Optional[str] = None,
        status: Optional[SessionStatus] = None,
    ) -> list[MuaSessionState]:
        """List sessions, optionally filtered by creator and/or status."""
        results: list[MuaSessionState] = []
        for session in await self._load_all_async():
            if created_by is not None and session.created_by != created_by:
                continue
            if status is not None and session.status != status:
                continue
            results.append(session)
        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results

    def list_sessions(
        self,
        created_by: Optional[str] = None,
        status: Optional[SessionStatus] = None,
    ) -> list[MuaSessionState]:
        return self._run_sync(self.alist_sessions(created_by=created_by, status=status))

    # -- Lifecycle ----------------------------------------------------------

    async def aabandon_session(self, session_id: str) -> bool:
        """Mark a session as abandoned."""
        session = await self._load_async(session_id)
        if session is None:
            logger.warning("Cannot abandon session %s: not found", session_id)
            return False

        if session.status in (SessionStatus.FINALIZED, SessionStatus.ABANDONED):
            logger.info(
                "Session %s already in terminal state %s; no-op",
                session_id,
                session.status.value,
            )
            return False

        session.status = SessionStatus.ABANDONED
        session.updated_at = datetime.utcnow()
        await self._save_async(session)
        logger.info("Abandoned session %s", session_id)
        return True

    async def acleanup_stale_sessions(self, max_age_days: int = 30) -> int:
        """Auto-abandon sessions inactive beyond the threshold."""
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        abandoned_count = 0

        for session in await self._load_all_async():
            if session.status in (SessionStatus.FINALIZED, SessionStatus.ABANDONED):
                continue
            if session.updated_at < cutoff:
                session.status = SessionStatus.ABANDONED
                session.updated_at = datetime.utcnow()
                await self._save_async(session)
                abandoned_count += 1
                logger.info(
                    "Auto-abandoned stale session %s (last updated %s)",
                    session.session_id,
                    session.updated_at.isoformat(),
                )

        if abandoned_count:
            logger.info(
                "Stale session cleanup: %d session(s) abandoned (cutoff=%s)",
                abandoned_count,
                cutoff.isoformat(),
            )
        return abandoned_count

    def abandon_session(self, session_id: str) -> bool:
        return self._run_sync(self.aabandon_session(session_id))

    def cleanup_stale_sessions(self, max_age_days: int = 30) -> int:
        return self._run_sync(self.acleanup_stale_sessions(max_age_days=max_age_days))

    # -- Field accessors (used by router) -----------------------------------

    async def aget_current_step(self, session_id: str) -> StepName:
        return (await self._get_async(session_id)).current_step

    async def aget_status(self, session_id: str) -> SessionStatus:
        return (await self._get_async(session_id)).status

    async def aget_material_input(self, session_id: str) -> Optional[str]:
        return (await self._get_async(session_id)).material_input

    async def aget_center(self, session_id: str) -> Optional[Center]:
        return (await self._get_async(session_id)).center

    async def aget_created_by(self, session_id: str) -> Optional[str]:
        return (await self._get_async(session_id)).created_by

    async def aget_created_at(self, session_id: str) -> Optional[datetime]:
        return (await self._get_async(session_id)).created_at

    async def aget_updated_at(self, session_id: str) -> Optional[datetime]:
        return (await self._get_async(session_id)).updated_at

    async def aget_investigation(self, session_id: str) -> Optional[InvestigationResult]:
        return (await self._get_async(session_id)).investigation_result

    async def aget_review_decisions(self, session_id: str) -> Optional[ReviewDecisions]:
        return (await self._get_async(session_id)).review_decisions

    async def aget_draft(self, session_id: str) -> Optional[MUADraft]:
        return (await self._get_async(session_id)).draft

    async def aget_finalized_mua(self, session_id: str) -> Optional[FinalizedMUA]:
        return (await self._get_async(session_id)).finalized_mua

    async def aget_approved_cat3_codes(self, session_id: str) -> Optional[list[str]]:
        return (await self._get_async(session_id)).approved_cat3_codes

    def get_current_step(self, session_id: str) -> StepName:
        return self._run_sync(self.aget_current_step(session_id))

    def get_status(self, session_id: str) -> SessionStatus:
        return self._run_sync(self.aget_status(session_id))

    def get_material_input(self, session_id: str) -> Optional[str]:
        return self._run_sync(self.aget_material_input(session_id))

    def get_center(self, session_id: str) -> Optional[Center]:
        return self._run_sync(self.aget_center(session_id))

    def get_created_by(self, session_id: str) -> Optional[str]:
        return self._run_sync(self.aget_created_by(session_id))

    def get_created_at(self, session_id: str) -> Optional[datetime]:
        return self._run_sync(self.aget_created_at(session_id))

    def get_updated_at(self, session_id: str) -> Optional[datetime]:
        return self._run_sync(self.aget_updated_at(session_id))

    def get_investigation(self, session_id: str) -> Optional[InvestigationResult]:
        return self._run_sync(self.aget_investigation(session_id))

    def get_review_decisions(self, session_id: str) -> Optional[ReviewDecisions]:
        return self._run_sync(self.aget_review_decisions(session_id))

    def get_draft(self, session_id: str) -> Optional[MUADraft]:
        return self._run_sync(self.aget_draft(session_id))

    def get_finalized_mua(self, session_id: str) -> Optional[FinalizedMUA]:
        return self._run_sync(self.aget_finalized_mua(session_id))

    def get_approved_cat3_codes(self, session_id: str) -> Optional[list[str]]:
        return self._run_sync(self.aget_approved_cat3_codes(session_id))

    # -- Field mutators (used by router) ------------------------------------

    async def astore_define_inputs(
        self,
        session_id: str,
        material_resolution: MaterialResolution,
        environment: EnvironmentSpec,
        *,
        process_params: Optional[ProcessParams] = None,
        material_input: Optional[str] = None,
        application: Optional[str] = None,
        program: Optional[str] = None,
        hardware: Optional[str] = None,
        miul_ref: Optional[str] = None,
        approved_cat3_codes: Optional[list[str]] = None,
    ) -> None:
        session = await self._get_async(session_id)
        session.material_resolution = material_resolution
        session.environment = environment
        session.process_params = process_params
        session.material_input = material_input
        session.application = application
        session.program = program
        session.hardware = hardware
        session.miul_ref = miul_ref
        session.approved_cat3_codes = approved_cat3_codes
        session.updated_at = datetime.utcnow()
        await self._save_async(session)

    async def astore_investigation(self, session_id: str, investigation: InvestigationResult) -> None:
        session = await self._get_async(session_id)
        session.investigation_result = investigation
        session.updated_at = datetime.utcnow()
        await self._save_async(session)

    async def astore_review_decisions(self, session_id: str, decisions: ReviewDecisions) -> None:
        session = await self._get_async(session_id)
        session.review_decisions = decisions
        session.updated_at = datetime.utcnow()
        await self._save_async(session)

    async def astore_draft(self, session_id: str, draft: MUADraft) -> None:
        session = await self._get_async(session_id)
        session.draft = draft
        session.updated_at = datetime.utcnow()
        await self._save_async(session)

    async def astore_finalized_mua(self, session_id: str, mua: FinalizedMUA) -> None:
        session = await self._get_async(session_id)
        session.finalized_mua = mua
        session.updated_at = datetime.utcnow()
        await self._save_async(session)

    async def aupdate_status(self, session_id: str, status: SessionStatus) -> None:
        session = await self._get_async(session_id)
        session.status = status
        session.updated_at = datetime.utcnow()
        await self._save_async(session)

    def store_define_inputs(
        self,
        session_id: str,
        material_resolution: MaterialResolution,
        environment: EnvironmentSpec,
        *,
        process_params: Optional[ProcessParams] = None,
        material_input: Optional[str] = None,
        application: Optional[str] = None,
        program: Optional[str] = None,
        hardware: Optional[str] = None,
        miul_ref: Optional[str] = None,
        approved_cat3_codes: Optional[list[str]] = None,
    ) -> None:
        self._run_sync(
            self.astore_define_inputs(
                session_id,
                material_resolution,
                environment,
                process_params=process_params,
                material_input=material_input,
                application=application,
                program=program,
                hardware=hardware,
                miul_ref=miul_ref,
                approved_cat3_codes=approved_cat3_codes,
            )
        )

    def store_investigation(self, session_id: str, investigation: InvestigationResult) -> None:
        self._run_sync(self.astore_investigation(session_id, investigation))

    def store_review_decisions(self, session_id: str, decisions: ReviewDecisions) -> None:
        self._run_sync(self.astore_review_decisions(session_id, decisions))

    def store_draft(self, session_id: str, draft: MUADraft) -> None:
        self._run_sync(self.astore_draft(session_id, draft))

    def store_finalized_mua(self, session_id: str, mua: FinalizedMUA) -> None:
        self._run_sync(self.astore_finalized_mua(session_id, mua))

    def update_status(self, session_id: str, status: SessionStatus) -> None:
        self._run_sync(self.aupdate_status(session_id, status))

    async def aget_stats(self) -> dict:
        """Return aggregate usage stats."""
        sessions = await self._load_all_async()
        total = len(sessions)
        by_status: dict[str, int] = {}
        for s in sessions:
            by_status[s.status.value] = by_status.get(s.status.value, 0) + 1

        finalized = [s for s in sessions if s.status == SessionStatus.FINALIZED]
        avg_time: Optional[float] = None
        if finalized:
            times = []
            for s in finalized:
                if s.finalized_at and s.created_at:
                    delta = (s.finalized_at - s.created_at).total_seconds()
                    times.append(delta)
            if times:
                avg_time = sum(times) / len(times)

        return {
            "total_sessions": total,
            "sessions_by_status": by_status,
            "avg_completion_time_seconds": avg_time,
            "sessions_finalized_last_30d": len(finalized),
            "most_common_materials": [],
            "most_common_centers": [],
        }

    def get_stats(self) -> dict:
        return self._run_sync(self.aget_stats())
