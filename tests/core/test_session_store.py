"""
Tests for mira.core.session_store — shared session abstraction.

Covers:
  - MemorySessionStore CRUD operations
  - SessionData Pydantic model serialization
  - Factory function and backend selection
  - Eviction behavior
  - Chat session/history round-trip through the abstraction

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import os
import pytest

from mira.core.session_store import (
    DynamoDBSessionStore,
    MemorySessionStore,
    PostgresSessionStore,
    SessionData,
    SessionStore,
    get_session_store,
    reset_session_store,
)


# ---------------------------------------------------------------------------
# SessionData model tests
# ---------------------------------------------------------------------------


class TestSessionData:
    def test_default_construction(self):
        data = SessionData(session_id="s1")
        assert data.session_id == "s1"
        assert data.engine_context == {}
        assert data.accumulated_entities == {}
        assert data.history == []
        assert data.turn_count == 0
        assert data.last_assessment is None

    def test_model_dump_json_roundtrip(self):
        data = SessionData(
            session_id="s1",
            engine_context={"oca_case_id": "case-123"},
            accumulated_entities={"material_designation": "316L"},
            history=[
                {"role": "user", "content": "hello", "entities": {}},
                {"role": "assistant", "content": "hi", "engine_used": "oca", "entities": {}},
            ],
            turn_count=1,
            last_assessment={"engine_id": "oca", "status": "PASS"},
        )
        dumped = data.model_dump(mode="json")
        assert isinstance(dumped, dict)
        assert dumped["session_id"] == "s1"
        assert dumped["engine_context"]["oca_case_id"] == "case-123"
        assert len(dumped["history"]) == 2

        # Round-trip
        restored = SessionData(**dumped)
        assert restored == data

    def test_protocol_compliance(self):
        """MemorySessionStore satisfies the SessionStore protocol."""
        store = MemorySessionStore()
        assert isinstance(store, SessionStore)

    def test_dynamodb_protocol_compliance(self):
        """DynamoDBSessionStore satisfies the SessionStore protocol."""
        store = DynamoDBSessionStore()
        assert isinstance(store, SessionStore)

    def test_postgres_protocol_compliance(self):
        """PostgresSessionStore satisfies the SessionStore protocol."""
        store = PostgresSessionStore()
        assert isinstance(store, SessionStore)


# ---------------------------------------------------------------------------
# MemorySessionStore CRUD tests
# ---------------------------------------------------------------------------


class TestMemorySessionStoreCRUD:
    @pytest.fixture
    def store(self):
        return MemorySessionStore(max_sessions=10, max_history=10)

    @pytest.mark.asyncio
    async def test_get_creates_new_session(self, store):
        data = await store.get("new-session")
        assert data.session_id == "new-session"
        assert data.turn_count == 0

    @pytest.mark.asyncio
    async def test_get_returns_same_session(self, store):
        data1 = await store.get("s1")
        data1.turn_count = 5
        # MemorySessionStore returns reference, so mutation is visible
        data2 = await store.get("s1")
        assert data2.turn_count == 5

    @pytest.mark.asyncio
    async def test_save_persists_data(self, store):
        data = SessionData(
            session_id="s1",
            engine_context={"key": "value"},
            turn_count=3,
        )
        await store.save("s1", data)
        retrieved = await store.get("s1")
        assert retrieved.engine_context == {"key": "value"}
        assert retrieved.turn_count == 3

    @pytest.mark.asyncio
    async def test_delete_existing(self, store):
        await store.get("s1")
        assert await store.exists("s1")
        result = await store.delete("s1")
        assert result is True
        assert not await store.exists("s1")

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        result = await store.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists(self, store):
        assert not await store.exists("s1")
        await store.get("s1")
        assert await store.exists("s1")

    @pytest.mark.asyncio
    async def test_session_count(self, store):
        assert store.session_count == 0
        await store.get("s1")
        await store.get("s2")
        assert store.session_count == 2

    @pytest.mark.asyncio
    async def test_eviction_at_capacity(self, store):
        """When max_sessions is reached, oldest session is evicted."""
        small_store = MemorySessionStore(max_sessions=3)
        await small_store.get("s1")
        await small_store.get("s2")
        await small_store.get("s3")
        assert small_store.session_count == 3

        # Adding a 4th should evict s1
        await small_store.get("s4")
        assert small_store.session_count == 3
        assert not await small_store.exists("s1")
        assert await small_store.exists("s2")
        assert await small_store.exists("s4")

    @pytest.mark.asyncio
    async def test_get_moves_to_end_lru(self, store):
        """Accessing a session moves it to end (most recently used)."""
        small_store = MemorySessionStore(max_sessions=3)
        await small_store.get("s1")
        await small_store.get("s2")
        await small_store.get("s3")

        # Access s1 to make it recently used
        await small_store.get("s1")

        # Now s2 is oldest — adding s4 should evict s2, not s1
        await small_store.get("s4")
        assert await small_store.exists("s1")
        assert not await small_store.exists("s2")


# ---------------------------------------------------------------------------
# Chat history round-trip through the abstraction
# ---------------------------------------------------------------------------


class TestChatHistoryRoundTrip:
    @pytest.fixture
    def store(self):
        return MemorySessionStore()

    @pytest.mark.asyncio
    async def test_history_append_and_retrieve(self, store):
        """Simulate the chat router appending history entries."""
        data = await store.get("chat-session")
        data.history.append({
            "role": "user",
            "content": "Is 316L compatible with GOX?",
            "entities": {"material_designation": "316L"},
        })
        data.history.append({
            "role": "assistant",
            "content": "Yes, 316L is compatible.",
            "engine_used": "oca",
            "entities": {"material_designation": "316L"},
        })
        data.turn_count = 1
        await store.save("chat-session", data)

        # Retrieve and verify
        restored = await store.get("chat-session")
        assert len(restored.history) == 2
        assert restored.history[0]["role"] == "user"
        assert restored.history[1]["engine_used"] == "oca"
        assert restored.turn_count == 1

    @pytest.mark.asyncio
    async def test_multi_turn_entity_accumulation(self, store):
        """Simulate multi-turn entity accumulation as the router does."""
        data = await store.get("multi-turn")

        # Turn 1: user asks about 316L in GOX
        data.accumulated_entities["material_designation"] = "316L"
        data.accumulated_entities["gas_service"] = "oxygen"
        data.turn_count = 1
        await store.save("multi-turn", data)

        # Turn 2: user asks "what about at 1500 psi?" — pressure added
        data = await store.get("multi-turn")
        data.accumulated_entities["pressure_value"] = 1500.0
        data.turn_count = 2
        await store.save("multi-turn", data)

        # Verify all entities accumulated
        final = await store.get("multi-turn")
        assert final.accumulated_entities == {
            "material_designation": "316L",
            "gas_service": "oxygen",
            "pressure_value": 1500.0,
        }
        assert final.turn_count == 2

    @pytest.mark.asyncio
    async def test_engine_context_persistence(self, store):
        """Engine context (e.g. oca_case_id) persists across turns."""
        data = await store.get("ctx-session")
        data.engine_context["oca_case_id"] = "case-abc"
        await store.save("ctx-session", data)

        restored = await store.get("ctx-session")
        assert restored.engine_context["oca_case_id"] == "case-abc"

    @pytest.mark.asyncio
    async def test_last_assessment_round_trip(self, store):
        """last_assessment dict round-trips through save/get."""
        data = await store.get("assess")
        data.last_assessment = {
            "engine_id": "oca",
            "status": "PASS",
            "entities": {"material_designation": "316L"},
        }
        await store.save("assess", data)

        restored = await store.get("assess")
        assert restored.last_assessment["engine_id"] == "oca"
        assert restored.last_assessment["status"] == "PASS"

    @pytest.mark.asyncio
    async def test_serialization_boundary(self, store):
        """SessionData serializes cleanly via model_dump(mode='json')."""
        data = await store.get("serial")
        data.engine_context = {"oca_case_id": "case-1"}
        data.accumulated_entities = {"material_designation": "316L"}
        data.history = [
            {"role": "user", "content": "hello", "entities": {}},
        ]
        data.turn_count = 1
        await store.save("serial", data)

        restored = await store.get("serial")
        json_dict = restored.model_dump(mode="json")
        assert isinstance(json_dict, dict)
        assert json_dict["session_id"] == "serial"

        # Can reconstruct from JSON dict
        from_json = SessionData(**json_dict)
        assert from_json == restored


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestGetSessionStore:
    def setup_method(self):
        reset_session_store()

    def teardown_method(self):
        reset_session_store()
        os.environ.pop("MIRA_SESSION_BACKEND", None)

    def test_default_is_memory(self):
        store = get_session_store()
        assert isinstance(store, MemorySessionStore)

    def test_explicit_memory(self):
        os.environ["MIRA_SESSION_BACKEND"] = "memory"
        store = get_session_store()
        assert isinstance(store, MemorySessionStore)

    def test_explicit_postgres(self):
        os.environ["MIRA_SESSION_BACKEND"] = "postgres"
        store = get_session_store()
        assert isinstance(store, PostgresSessionStore)

    def test_dynamodb_scaffolded(self):
        os.environ["MIRA_SESSION_BACKEND"] = "dynamodb"
        store = get_session_store()
        assert isinstance(store, DynamoDBSessionStore)

    def test_database_env_auto_selects_postgres(self):
        os.environ["POSTGRES_HOST"] = "db.internal"
        store = get_session_store()
        assert isinstance(store, PostgresSessionStore)

    def test_unknown_backend_falls_back_to_memory(self):
        os.environ["MIRA_SESSION_BACKEND"] = "redis"
        store = get_session_store()
        assert isinstance(store, MemorySessionStore)

    def test_singleton_behavior(self):
        store1 = get_session_store()
        store2 = get_session_store()
        assert store1 is store2

    @pytest.mark.asyncio
    async def test_dynamodb_raises_not_implemented(self):
        os.environ["MIRA_SESSION_BACKEND"] = "dynamodb"
        store = get_session_store()
        with pytest.raises(NotImplementedError):
            await store.get("test")
