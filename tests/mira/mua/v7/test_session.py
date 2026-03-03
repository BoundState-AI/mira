"""Tests for MUA v7 session management.

The MUA wizard follows a strict 5-step sequence:

  DEFINE -> INVESTIGATE -> REVIEW -> DRAFT -> FINALIZE

Sessions are identified by UUID and persist server-side so that work is
never lost if the browser closes.  Steps cannot be skipped; the wizard
must advance one step at a time.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from mira.mua.v7.session import (
    SessionManager,
    MuaSessionState,
    StepValidationError,
)
from mira.mua.v7.models import (
    SessionStatus,
    StepName,
    MaterialResolution,
    EnvironmentSpec,
    InvestigationResult,
    ReviewDecisions,
    MUADraft,
    EvidenceStrengthResult,
    MUACategory,
    ResolutionStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager():
    """Return an in-memory SessionManager for testing (no database)."""
    return SessionManager()


@pytest.fixture
def active_session(manager):
    """Create and return an active session in the DEFINE step."""
    session = manager.create_session(created_by="engineer@nasa.gov")
    return session


def _make_material_resolution(input_text: str = "6061-T6") -> MaterialResolution:
    """Helper: build a minimal MaterialResolution for gate-passing."""
    return MaterialResolution(
        input_text=input_text,
        status=ResolutionStatus.RESOLVED,
        material_code="MAT-A96061",
        resolved_name="6061-T6 Aluminum",
    )


def _make_environment_spec() -> EnvironmentSpec:
    """Helper: build a minimal EnvironmentSpec for gate-passing."""
    return EnvironmentSpec(
        o2_percent=21.0,
        pressure_psia=14.7,
        temp_min_f=70.0,
        temp_max_f=200.0,
        medium="Air",
        location="habitable",
        application="structural component",
    )


def _make_investigation_result() -> InvestigationResult:
    """Helper: build a minimal InvestigationResult for gate-passing."""
    return InvestigationResult(
        material=_make_material_resolution(),
        environment=_make_environment_spec(),
    )


def _make_review_decisions(all_reviewed: bool = True) -> ReviewDecisions:
    """Helper: build ReviewDecisions with all_items_reviewed set."""
    return ReviewDecisions(all_items_reviewed=all_reviewed)


def _make_draft() -> MUADraft:
    """Helper: build a minimal MUADraft for gate-passing."""
    return MUADraft(
        mua_id="MUA-TEST-001",
        category=MUACategory.I,
        evidence_strength=EvidenceStrengthResult(),
    )


def _populate_for_advance(manager: SessionManager, session: MuaSessionState, to_step: StepName) -> None:
    """Populate prerequisite data so the session can advance to ``to_step``.

    This fills in gate prerequisites for each step transition up to
    (but not including) ``to_step``, then advances the session through
    each intermediate step.
    """
    steps_needing_data = {
        StepName.INVESTIGATE: lambda s: _set_define_data(s),
        StepName.REVIEW: lambda s: _set_investigate_data(manager, s),
        StepName.DRAFT: lambda s: _set_review_data(manager, s),
        StepName.FINALIZE: lambda s: _set_draft_data(manager, s),
    }

    for step in [StepName.INVESTIGATE, StepName.REVIEW, StepName.DRAFT, StepName.FINALIZE]:
        if step == to_step or _step_index(step) > _step_index(to_step):
            break
        # Populate data required by the gate for this step
        populate_fn = steps_needing_data.get(step)
        if populate_fn:
            populate_fn(session)
        manager.advance_step(session.session_id, step)

    # Also populate data for the final target step's gate
    populate_fn = steps_needing_data.get(to_step)
    if populate_fn:
        populate_fn(session)


def _step_index(step: StepName) -> int:
    """Return ordinal index of a step."""
    order = [StepName.DEFINE, StepName.INVESTIGATE, StepName.REVIEW, StepName.DRAFT, StepName.FINALIZE]
    return order.index(step)


def _set_define_data(session: MuaSessionState) -> None:
    """Populate Step 1 (DEFINE) prerequisite fields."""
    session.material_resolution = _make_material_resolution()
    session.environment = _make_environment_spec()


def _set_investigate_data(manager: SessionManager, session: MuaSessionState) -> None:
    """Populate Step 2 (INVESTIGATE) prerequisite fields."""
    manager.store_investigation(session.session_id, _make_investigation_result())


def _set_review_data(manager: SessionManager, session: MuaSessionState) -> None:
    """Populate Step 3 (REVIEW) prerequisite fields."""
    manager.store_review_decisions(session.session_id, _make_review_decisions())


def _set_draft_data(manager: SessionManager, session: MuaSessionState) -> None:
    """Populate Step 4 (DRAFT) prerequisite fields."""
    manager.store_draft(session.session_id, _make_draft())


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_create_session(self, manager):
        """Creating a session must assign a UUID and start at the DEFINE
        step with ACTIVE status."""
        session = manager.create_session(created_by="engineer@nasa.gov")

        # Valid UUID
        uuid.UUID(str(session.session_id))

        assert session.current_step == StepName.DEFINE
        assert session.status == SessionStatus.ACTIVE
        assert session.created_by == "engineer@nasa.gov"
        assert session.created_at is not None
        assert session.updated_at is not None

    def test_create_multiple_sessions(self, manager):
        """Each created session must have a unique session_id."""
        s1 = manager.create_session(created_by="eng1@nasa.gov")
        s2 = manager.create_session(created_by="eng2@nasa.gov")
        assert s1.session_id != s2.session_id


# ---------------------------------------------------------------------------
# Step advancement
# ---------------------------------------------------------------------------

class TestStepAdvancement:
    def test_advance_step(self, manager, active_session):
        """The session must advance through all five steps in strict
        order: DEFINE -> INVESTIGATE -> REVIEW -> DRAFT -> FINALIZE."""
        sid = active_session.session_id

        expected_sequence = [
            StepName.INVESTIGATE,
            StepName.REVIEW,
            StepName.DRAFT,
            StepName.FINALIZE,
        ]

        for expected_step in expected_sequence:
            # Populate prerequisite data for the gate
            _populate_gate_data(manager, active_session, expected_step)
            session = manager.advance_step(sid, expected_step)
            assert session.current_step == expected_step

    def test_cannot_skip_step(self, manager, active_session):
        """It must not be possible to skip from DEFINE directly to DRAFT.
        Attempting to do so must raise a StepValidationError."""
        sid = active_session.session_id

        # Even with all prerequisite data, skipping steps is not allowed
        _set_define_data(active_session)
        with pytest.raises(StepValidationError):
            manager.advance_step(sid, StepName.DRAFT)

    def test_backward_navigation_allowed(self, manager, active_session):
        """Backward navigation (revisiting earlier steps) must be allowed."""
        sid = active_session.session_id

        # Advance to INVESTIGATE
        _set_define_data(active_session)
        manager.advance_step(sid, StepName.INVESTIGATE)

        # Go back to DEFINE -- should succeed
        session = manager.advance_step(sid, StepName.DEFINE)
        assert session.current_step == StepName.DEFINE

    def test_advance_without_prerequisites_fails(self, manager, active_session):
        """Advancing without populating prerequisite data must raise
        StepValidationError due to gate predicates."""
        sid = active_session.session_id

        # Try to advance to INVESTIGATE without setting material_resolution
        with pytest.raises(StepValidationError):
            manager.advance_step(sid, StepName.INVESTIGATE)

    def test_advance_to_finalize_sets_status(self, manager, active_session):
        """Advancing to FINALIZE must set the session status to FINALIZED."""
        sid = active_session.session_id

        _populate_for_advance(manager, active_session, StepName.FINALIZE)
        session = manager.advance_step(sid, StepName.FINALIZE)

        assert session.status == SessionStatus.FINALIZED
        assert session.finalized_at is not None

    def test_advance_to_draft_sets_draft_saved(self, manager, active_session):
        """Advancing to DRAFT must set the session status to DRAFT_SAVED."""
        sid = active_session.session_id

        _populate_for_advance(manager, active_session, StepName.DRAFT)
        session = manager.advance_step(sid, StepName.DRAFT)

        assert session.status == SessionStatus.DRAFT_SAVED


def _populate_gate_data(manager: SessionManager, session: MuaSessionState, target_step: StepName) -> None:
    """Populate just the gate data needed to advance to ``target_step`` (assumes
    the session is currently one step behind)."""
    if target_step == StepName.INVESTIGATE:
        _set_define_data(session)
    elif target_step == StepName.REVIEW:
        _set_investigate_data(manager, session)
    elif target_step == StepName.DRAFT:
        _set_review_data(manager, session)
    elif target_step == StepName.FINALIZE:
        _set_draft_data(manager, session)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class TestRetrieval:
    def test_resume_session(self, manager, active_session):
        """Fetching a session by ID must return the full state including
        the current step and any data stored during earlier steps."""
        sid = active_session.session_id

        # Populate and advance to INVESTIGATE
        _set_define_data(active_session)
        manager.advance_step(sid, StepName.INVESTIGATE)

        # Store investigation data
        manager.store_investigation(sid, _make_investigation_result())

        retrieved = manager.get_session(sid)

        assert retrieved is not None
        assert retrieved.session_id == sid
        assert retrieved.current_step == StepName.INVESTIGATE
        assert retrieved.material_resolution is not None
        assert retrieved.material_resolution.input_text == "6061-T6"

    def test_get_missing_session_returns_none(self, manager):
        """Requesting a non-existent session must return None."""
        fake_id = str(uuid.uuid4())

        result = manager.get_session(fake_id)
        assert result is None

    def test_get_current_step(self, manager, active_session):
        """get_current_step must return the current StepName."""
        sid = active_session.session_id
        assert manager.get_current_step(sid) == StepName.DEFINE

    def test_get_status(self, manager, active_session):
        """get_status must return the current SessionStatus."""
        sid = active_session.session_id
        assert manager.get_status(sid) == SessionStatus.ACTIVE

    def test_get_current_step_missing_raises(self, manager):
        """get_current_step on a non-existent session must raise KeyError."""
        with pytest.raises(KeyError):
            manager.get_current_step(str(uuid.uuid4()))

    def test_get_status_missing_raises(self, manager):
        """get_status on a non-existent session must raise KeyError."""
        with pytest.raises(KeyError):
            manager.get_status(str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Update session
# ---------------------------------------------------------------------------

class TestUpdateSession:
    def test_update_session(self, manager, active_session):
        """update_session must persist changes and bump updated_at."""
        active_session.material_input = "Inconel 718"
        updated = manager.update_session(active_session)

        assert updated.material_input == "Inconel 718"

    def test_update_nonexistent_session_raises(self, manager):
        """Updating a session that does not exist must raise KeyError."""
        fake_session = MuaSessionState(session_id="nonexistent-id")
        with pytest.raises(KeyError):
            manager.update_session(fake_session)


# ---------------------------------------------------------------------------
# Abandonment
# ---------------------------------------------------------------------------

class TestAbandonment:
    def test_abandon_session(self, manager, active_session):
        """Abandoning a session sets its status to ABANDONED.  The session
        data is preserved for auditing but the wizard can no longer
        advance."""
        sid = active_session.session_id

        result = manager.abandon_session(sid)
        assert result is True

        session = manager.get_session(sid)
        assert session is not None
        assert session.status == SessionStatus.ABANDONED

    def test_abandon_already_abandoned(self, manager, active_session):
        """Abandoning an already-abandoned session returns False."""
        sid = active_session.session_id
        manager.abandon_session(sid)
        result = manager.abandon_session(sid)
        assert result is False

    def test_abandon_nonexistent(self, manager):
        """Abandoning a non-existent session returns False."""
        result = manager.abandon_session(str(uuid.uuid4()))
        assert result is False

    def test_cannot_advance_abandoned_session(self, manager, active_session):
        """An abandoned session must not be advanceable."""
        sid = active_session.session_id
        _set_define_data(active_session)
        manager.abandon_session(sid)

        with pytest.raises(ValueError):
            manager.advance_step(sid, StepName.INVESTIGATE)


# ---------------------------------------------------------------------------
# Listing / filtering
# ---------------------------------------------------------------------------

class TestListing:
    def test_list_sessions(self, manager):
        """The session list can be filtered by status.  Creating two
        sessions and abandoning one should yield one ACTIVE and one
        ABANDONED when filtered."""
        s1 = manager.create_session(created_by="engineer1@nasa.gov")
        s2 = manager.create_session(created_by="engineer2@nasa.gov")

        manager.abandon_session(s2.session_id)

        active = manager.list_sessions(status=SessionStatus.ACTIVE)
        abandoned = manager.list_sessions(status=SessionStatus.ABANDONED)

        assert len(active) == 1
        assert active[0].session_id == s1.session_id
        assert len(abandoned) == 1
        assert abandoned[0].session_id == s2.session_id

    def test_list_sessions_by_creator(self, manager):
        """Sessions can be filtered by created_by."""
        manager.create_session(created_by="alice@nasa.gov")
        manager.create_session(created_by="bob@nasa.gov")
        manager.create_session(created_by="alice@nasa.gov")

        alice_sessions = manager.list_sessions(created_by="alice@nasa.gov")
        assert len(alice_sessions) == 2

    def test_list_sessions_empty(self, manager):
        """Listing with no sessions returns an empty list."""
        result = manager.list_sessions()
        assert result == []


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

class TestTimestamps:
    def test_session_timestamps(self, manager, active_session):
        """The updated_at timestamp must change whenever the session is
        modified (step advancement, data update, etc.)."""
        sid = active_session.session_id
        original_updated = active_session.updated_at

        # Populate and advance the step which should update the timestamp
        _set_define_data(active_session)
        updated_session = manager.advance_step(sid, StepName.INVESTIGATE)

        assert updated_session.updated_at >= original_updated


# ---------------------------------------------------------------------------
# Cleanup stale sessions
# ---------------------------------------------------------------------------

class TestCleanupStaleSessions:
    def test_cleanup_stale_sessions(self, manager):
        """Sessions inactive beyond the threshold are auto-abandoned."""
        session = manager.create_session(created_by="engineer@nasa.gov")

        # Manually backdate the updated_at to simulate staleness
        session.updated_at = datetime.utcnow() - timedelta(days=31)
        manager._sessions[session.session_id] = session

        count = manager.cleanup_stale_sessions(max_age_days=30)
        assert count == 1

        cleaned = manager.get_session(session.session_id)
        assert cleaned is not None
        assert cleaned.status == SessionStatus.ABANDONED

    def test_cleanup_skips_finalized(self, manager, active_session):
        """Finalized sessions must not be abandoned by cleanup."""
        sid = active_session.session_id

        # Advance all the way to FINALIZE
        _populate_for_advance(manager, active_session, StepName.FINALIZE)
        manager.advance_step(sid, StepName.FINALIZE)

        # Backdate
        session = manager.get_session(sid)
        session.updated_at = datetime.utcnow() - timedelta(days=31)
        manager._sessions[sid] = session

        count = manager.cleanup_stale_sessions(max_age_days=30)
        assert count == 0

    def test_cleanup_no_stale(self, manager):
        """Cleanup with no stale sessions returns 0."""
        manager.create_session(created_by="engineer@nasa.gov")
        count = manager.cleanup_stale_sessions(max_age_days=30)
        assert count == 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_get_stats_empty(self, manager):
        """Stats on empty manager returns zeroed metrics."""
        stats = manager.get_stats()
        assert stats["total_sessions"] == 0

    def test_get_stats_with_sessions(self, manager):
        """Stats correctly counts sessions by status."""
        manager.create_session(created_by="eng1@nasa.gov")
        s2 = manager.create_session(created_by="eng2@nasa.gov")
        manager.abandon_session(s2.session_id)

        stats = manager.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["sessions_by_status"].get("active") == 1
        assert stats["sessions_by_status"].get("abandoned") == 1
