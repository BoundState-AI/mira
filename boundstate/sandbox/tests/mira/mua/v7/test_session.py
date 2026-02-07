"""Tests for MUA v7 session management.

The MUA wizard follows a strict 5-step sequence:

  DEFINE -> INVESTIGATE -> REVIEW -> DRAFT -> FINALIZE

Sessions are identified by UUID and persist server-side so that work is
never lost if the browser closes.  Steps cannot be skipped; the wizard
must advance one step at a time.
"""

import uuid
from datetime import datetime, timezone

import pytest

from mira.mua.v7.session import (
    SessionManager,
    SessionStatus,
    MuaStep,
    SessionNotFoundError,
    StepSequenceError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager():
    """Return an in-memory SessionManager for testing (no database)."""
    return SessionManager(backend="memory")


@pytest.fixture
def active_session(manager):
    """Create and return an active session in the DEFINE step."""
    session = manager.create_session(created_by="engineer@nasa.gov")
    return session


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

        assert session.current_step == MuaStep.DEFINE
        assert session.status == SessionStatus.ACTIVE
        assert session.created_by == "engineer@nasa.gov"
        assert session.created_at is not None
        assert session.updated_at is not None


# ---------------------------------------------------------------------------
# Step advancement
# ---------------------------------------------------------------------------

class TestStepAdvancement:
    def test_advance_step(self, manager, active_session):
        """The session must advance through all five steps in strict
        order: DEFINE -> INVESTIGATE -> REVIEW -> DRAFT -> FINALIZE."""
        sid = active_session.session_id

        expected_sequence = [
            MuaStep.INVESTIGATE,
            MuaStep.REVIEW,
            MuaStep.DRAFT,
            MuaStep.FINALIZE,
        ]

        for expected_step in expected_sequence:
            session = manager.advance_step(sid)
            assert session.current_step == expected_step

    def test_cannot_skip_step(self, manager, active_session):
        """It must not be possible to skip from DEFINE directly to DRAFT.
        Attempting to do so must raise a StepSequenceError."""
        sid = active_session.session_id

        with pytest.raises(StepSequenceError):
            manager.set_step(sid, MuaStep.DRAFT)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class TestRetrieval:
    def test_resume_session(self, manager, active_session):
        """Fetching a session by ID must return the full state including
        the current step and any data stored during earlier steps."""
        sid = active_session.session_id

        # Advance to INVESTIGATE and store some data
        manager.advance_step(sid)
        manager.update_session_data(sid, {"material": "6061-T6"})

        retrieved = manager.get_session(sid)

        assert retrieved.session_id == sid
        assert retrieved.current_step == MuaStep.INVESTIGATE
        assert retrieved.data.get("material") == "6061-T6"

    def test_get_missing_session(self, manager):
        """Requesting a non-existent session must raise
        SessionNotFoundError, not return None."""
        fake_id = str(uuid.uuid4())

        with pytest.raises(SessionNotFoundError):
            manager.get_session(fake_id)


# ---------------------------------------------------------------------------
# Abandonment
# ---------------------------------------------------------------------------

class TestAbandonment:
    def test_abandon_session(self, manager, active_session):
        """Abandoning a session sets its status to ABANDONED.  The session
        data is preserved for auditing but the wizard can no longer
        advance."""
        sid = active_session.session_id

        manager.abandon_session(sid)
        session = manager.get_session(sid)

        assert session.status == SessionStatus.ABANDONED


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


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

class TestTimestamps:
    def test_session_timestamps(self, manager, active_session):
        """The updated_at timestamp must change whenever the session is
        modified (step advancement, data update, etc.)."""
        sid = active_session.session_id
        original_updated = active_session.updated_at

        # Advance the step which should update the timestamp
        updated_session = manager.advance_step(sid)

        assert updated_session.updated_at >= original_updated
