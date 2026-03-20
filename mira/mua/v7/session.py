"""MUA v7 Session Manager.

Manages server-side session state for the 5-step MUA wizard.
State persisted in PostgreSQL with JSONB columns for complex data.
Pydantic models as the serialization layer.

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

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

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

    In production: PostgreSQL with JSONB columns.
    In sandbox: In-memory dict (same async interface).

    All public methods are ``async`` so the production implementation
    can use ``asyncpg`` / ``SQLAlchemy`` without changing callers.
    """

    def __init__(self) -> None:
        # Sandbox: in-memory storage keyed by session_id.
        self._sessions: dict[str, MuaSessionState] = {}

    # -- CRUD ---------------------------------------------------------------

    def create_session(
        self,
        created_by: Optional[str] = None,
        center: Center = Center.MSFC,
    ) -> MuaSessionState:
        """Create a new session and persist it.

        Parameters
        ----------
        created_by:
            Badge / email of the engineer who initiated the session.
        center:
            NASA center where the MUA is being generated.

        Returns
        -------
        MuaSessionState
            The newly created session.
        """
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
        self._sessions[session.session_id] = session
        logger.info(
            "Created MUA session %s for user=%s center=%s",
            session.session_id,
            created_by,
            center.value,
        )
        return session

    def get_session(self, session_id: str) -> Optional[MuaSessionState]:
        """Retrieve a session by ID, or ``None`` if not found.

        Parameters
        ----------
        session_id:
            UUID of the session.

        Returns
        -------
        MuaSessionState or None
        """
        session = self._sessions.get(session_id)
        if session is None:
            logger.debug("Session %s not found", session_id)
        return session

    def update_session(
        self,
        session: MuaSessionState,
    ) -> MuaSessionState:
        """Persist updated session state.

        Automatically bumps ``updated_at``.

        Parameters
        ----------
        session:
            The session with updated fields.

        Returns
        -------
        MuaSessionState
            The session as stored (with refreshed ``updated_at``).

        Raises
        ------
        KeyError
            If the session does not already exist in the store.
        """
        if session.session_id not in self._sessions:
            raise KeyError(
                f"Session {session.session_id!r} does not exist.  "
                f"Use create_session() first."
            )
        session.updated_at = datetime.utcnow()
        self._sessions[session.session_id] = session
        logger.debug("Updated session %s (step=%s)", session.session_id, session.current_step.value)
        return session

    def advance_step(
        self,
        session_id: str,
        to_step: StepName,
    ) -> MuaSessionState:
        """Validate and advance a session to the given step.

        Step ordering is enforced:
        - Backward navigation is allowed (revisiting earlier steps).
        - Forward advancement is restricted to +1 step at a time.
        - Each forward transition has a gate predicate that checks
          prerequisite data has been populated.

        Parameters
        ----------
        session_id:
            UUID of the session.
        to_step:
            Target step to move to.

        Returns
        -------
        MuaSessionState
            The session at the new step.

        Raises
        ------
        KeyError
            If the session does not exist.
        StepValidationError
            If the step transition is illegal.
        ValueError
            If the session is not in ACTIVE or DRAFT_SAVED status.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session {session_id!r} not found.")

        # Only active or draft-saved sessions can transition steps.
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

        # If we are advancing to FINALIZE, set the status.
        if to_step == StepName.FINALIZE:
            session.status = SessionStatus.FINALIZED
            session.finalized_at = datetime.utcnow()

        # If we generate a draft, mark as draft-saved.
        if to_step == StepName.DRAFT and session.status == SessionStatus.ACTIVE:
            session.status = SessionStatus.DRAFT_SAVED

        self._sessions[session.session_id] = session
        logger.info(
            "Session %s advanced: %s -> %s",
            session_id,
            previous_step.value,
            to_step.value,
        )
        return session

    # -- Queries ------------------------------------------------------------

    def list_sessions(
        self,
        created_by: Optional[str] = None,
        status: Optional[SessionStatus] = None,
    ) -> list[MuaSessionState]:
        """List sessions, optionally filtered by creator and/or status.

        Parameters
        ----------
        created_by:
            If provided, only return sessions created by this user.
        status:
            If provided, only return sessions with this status.

        Returns
        -------
        list[MuaSessionState]
            Matching sessions, ordered by ``updated_at`` descending.
        """
        results: list[MuaSessionState] = []
        for session in self._sessions.values():
            if created_by is not None and session.created_by != created_by:
                continue
            if status is not None and session.status != status:
                continue
            results.append(session)

        # Most recently updated first.
        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results

    # -- Lifecycle ----------------------------------------------------------

    def abandon_session(self, session_id: str) -> bool:
        """Mark a session as abandoned.

        Abandoned sessions are retained for audit purposes but are
        no longer editable.

        Parameters
        ----------
        session_id:
            UUID of the session.

        Returns
        -------
        bool
            ``True`` if the session was found and abandoned;
            ``False`` if the session does not exist or was already
            finalized/abandoned.
        """
        session = self._sessions.get(session_id)
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
        self._sessions[session.session_id] = session
        logger.info("Abandoned session %s", session_id)
        return True

    def cleanup_stale_sessions(self, max_age_days: int = 30) -> int:
        """Auto-abandon sessions that have been inactive beyond the threshold.

        In production this would be a scheduled background task or
        database trigger.  In the sandbox we scan the in-memory dict.

        Parameters
        ----------
        max_age_days:
            Maximum days of inactivity before a session is abandoned.
            Defaults to 30.

        Returns
        -------
        int
            Number of sessions that were abandoned.
        """
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        abandoned_count = 0

        for session in list(self._sessions.values()):
            if session.status in (SessionStatus.FINALIZED, SessionStatus.ABANDONED):
                continue
            if session.updated_at < cutoff:
                session.status = SessionStatus.ABANDONED
                session.updated_at = datetime.utcnow()
                self._sessions[session.session_id] = session
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

    # -- Field accessors (used by router) -----------------------------------

    def _get(self, session_id: str) -> MuaSessionState:
        """Return session or raise KeyError."""
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session {session_id!r} not found.")
        return session

    def get_current_step(self, session_id: str) -> StepName:
        return self._get(session_id).current_step

    def get_status(self, session_id: str) -> SessionStatus:
        return self._get(session_id).status

    def get_material_input(self, session_id: str) -> Optional[str]:
        return self._get(session_id).material_input

    def get_center(self, session_id: str) -> Optional[Center]:
        return self._get(session_id).center

    def get_created_by(self, session_id: str) -> Optional[str]:
        return self._get(session_id).created_by

    def get_created_at(self, session_id: str) -> Optional[datetime]:
        return self._get(session_id).created_at

    def get_updated_at(self, session_id: str) -> Optional[datetime]:
        return self._get(session_id).updated_at

    def get_investigation(self, session_id: str) -> Optional[InvestigationResult]:
        return self._get(session_id).investigation_result

    def get_review_decisions(self, session_id: str) -> Optional[ReviewDecisions]:
        return self._get(session_id).review_decisions

    def get_draft(self, session_id: str) -> Optional[MUADraft]:
        return self._get(session_id).draft

    def get_finalized_mua(self, session_id: str) -> Optional[FinalizedMUA]:
        # FinalizedMUA is stored externally; store on session state
        return getattr(self._get(session_id), '_finalized_mua', None)

    def get_approved_cat3_codes(self, session_id: str) -> Optional[list[str]]:
        return self._get(session_id).approved_cat3_codes

    # -- Field mutators (used by router) ------------------------------------

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
        session = self._get(session_id)
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

    def store_investigation(self, session_id: str, investigation: InvestigationResult) -> None:
        session = self._get(session_id)
        session.investigation_result = investigation
        session.updated_at = datetime.utcnow()

    def store_review_decisions(self, session_id: str, decisions: ReviewDecisions) -> None:
        session = self._get(session_id)
        session.review_decisions = decisions
        session.updated_at = datetime.utcnow()

    def store_draft(self, session_id: str, draft: MUADraft) -> None:
        session = self._get(session_id)
        session.draft = draft
        session.updated_at = datetime.utcnow()

    def store_finalized_mua(self, session_id: str, mua: FinalizedMUA) -> None:
        session = self._get(session_id)
        # Store on session object as a non-model attribute for now
        session.__dict__['_finalized_mua'] = mua
        session.updated_at = datetime.utcnow()

    def update_status(self, session_id: str, status: SessionStatus) -> None:
        session = self._get(session_id)
        session.status = status
        session.updated_at = datetime.utcnow()

    def get_stats(self) -> dict:
        """Return aggregate usage stats."""
        sessions = list(self._sessions.values())
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
