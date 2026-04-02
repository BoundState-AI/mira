"""
Tests for MIUL v4 session persistence through the shared SessionStore.

Verifies:
  - Session state persists across separate V4Session instances
  - Status, metadata, extraction, review, audit all round-trip
  - list_sessions works through the shared store
  - delete removes all session documents
  - Owner/auth metadata persists

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import pytest

from mira.core.session_store import reset_session_store
from mira.miul.production.session import V4Session, list_sessions, get_session


@pytest.fixture(autouse=True)
def _clean_store():
    reset_session_store()
    yield
    reset_session_store()


class TestV4SessionPersistence:
    def test_status_round_trip(self):
        """Status set on one V4Session instance is readable on another."""

        s1 = V4Session("test-status-1")
        s1.set_status("extracting", message="Phase 1", progress=25)

        # New instance, same ID — proves persistence
        s2 = V4Session("test-status-1")
        status = s2.get_status()
        assert status["status"] == "extracting"
        assert status["message"] == "Phase 1"
        assert status["progress"] == 25

    def test_owner_username_round_trip(self):
        """Owner metadata persists across instances."""

        s1 = V4Session("test-owner-1")
        s1.set_owner_username("engineer@nasa.gov")

        s2 = V4Session("test-owner-1")
        assert s2.get_owner_username() == "engineer@nasa.gov"

    def test_owner_username_none(self):
        """Empty/None owner username round-trips as None."""

        s1 = V4Session("test-owner-none")
        s1.set_owner_username(None)

        s2 = V4Session("test-owner-none")
        assert s2.get_owner_username() is None

    def test_exists_property(self):
        """exists is False before metadata is written, True after."""

        session = V4Session("test-exists-1")
        assert not session.exists

        session.set_owner_username("test-user")
        assert session.exists

    def test_audit_trail_accumulates(self):
        """Audit events accumulate across separate calls."""

        s = V4Session("test-audit-1")
        s._append_audit("event_1", {"detail": "first"})
        s._append_audit("event_2", {"detail": "second"})

        trail = V4Session("test-audit-1").load_audit()
        assert len(trail) == 2
        assert trail[0]["event"] == "event_1"
        assert trail[1]["event"] == "event_2"
        assert trail[0]["extraction_id"] == "test-audit-1"

    def test_review_state_persists(self):
        """Review data written by one instance is readable by another."""

        s = V4Session("test-review-1")
        review_data = {
            "status": "in_review",
            "summary": {"total_materials": 5, "needs_review": 2, "auto_approved": 3},
            "review_items": [
                {"part_number": "P-001", "status": "open"},
                {"part_number": "P-002", "status": "accepted"},
            ],
        }
        s._write("review", review_data)

        s2 = V4Session("test-review-1")
        loaded = s2.load_review()
        assert loaded["status"] == "in_review"
        assert loaded["summary"]["total_materials"] == 5
        assert len(loaded["review_items"]) == 2

    def test_delete_removes_all_documents(self):
        """delete() removes all 5 document types for a session."""

        s = V4Session("test-delete-1")
        s.set_owner_username("user")
        s.set_status("complete", progress=100)
        s._write("extraction", {"materials": []})
        s._write("review", {"status": "in_review"})
        s._append_audit("created", {})

        assert s.exists
        result = s.delete()
        assert result is True

        s2 = V4Session("test-delete-1")
        assert not s2.exists
        assert s2.get_status()["status"] == "unknown"
        assert s2.load_review() is None
        assert s2.load_audit() == []


class TestListSessions:
    def test_list_sessions_empty(self):
        """list_sessions returns empty list when no sessions exist."""

        assert list_sessions() == []

    def test_list_sessions_finds_created_sessions(self):
        """list_sessions finds sessions created through the shared store."""
        pass  # V4Session imported at module level, list_sessions

        s1 = V4Session("list-test-1")
        s1.set_owner_username("user1")
        s1._write("extraction", {"timestamp": "2026-01-01T00:00:00Z", "materials": []})
        s1._write("review", {"status": "in_review", "summary": {"total_materials": 3}})

        s2 = V4Session("list-test-2")
        s2.set_owner_username("user2")
        s2._write("extraction", {"timestamp": "2026-01-02T00:00:00Z", "materials": []})
        s2._write("review", {"status": "complete", "summary": {"total_materials": 7}})

        sessions = list_sessions()
        eids = {s["extraction_id"] for s in sessions}
        assert "list-test-1" in eids
        assert "list-test-2" in eids

    def test_list_sessions_respects_limit(self):
        """list_sessions respects the limit parameter."""
        pass  # V4Session imported at module level, list_sessions

        for i in range(5):
            s = V4Session(f"limit-test-{i}")
            s.set_owner_username("user")
            s._write("extraction", {"timestamp": f"2026-01-0{i+1}T00:00:00Z"})

        sessions = list_sessions(limit=3)
        assert len(sessions) <= 3

    def test_list_sessions_uses_status_document_when_review_missing(self):
        """In-flight sessions should not show up as unknown before review exists."""

        session = V4Session("status-only-1")
        session.set_owner_username("user")
        session.set_status("extracting", message="Working", progress=35)

        sessions = list_sessions()
        listed = next(item for item in sessions if item["extraction_id"] == "status-only-1")
        assert listed["status"] == "extracting"

    def test_get_session_returns_v4session(self):
        """get_session returns a V4Session for any extraction ID."""

        session = get_session("any-id")
        assert session.extraction_id == "any-id"


class TestCreatedAtAndProject:
    def test_created_at_from_extraction(self):
        """get_created_at reads timestamp from extraction data."""

        s = V4Session("ts-test-1")
        s._write("extraction", {"timestamp": "2026-03-15T10:30:00Z", "materials": []})

        assert V4Session("ts-test-1").get_created_at() == "2026-03-15T10:30:00Z"

    def test_created_at_from_metadata(self):
        """get_created_at falls back to metadata when no extraction."""

        s = V4Session("ts-test-2")
        s.set_owner_username("user")

        created = V4Session("ts-test-2").get_created_at()
        assert created is not None  # Should have metadata.created_at

    def test_project_name_from_extraction(self):
        """get_project_name reads from extraction data."""

        s = V4Session("proj-test-1")
        s._write("extraction", {"project": "Artemis III", "materials": []})

        assert V4Session("proj-test-1").get_project_name() == "Artemis III"
