from __future__ import annotations

import asyncio
import os

import pytest

import mira.core.session_store as session_store_module
from mira.core.session_store import (
    DynamoDBSessionStore,
    MemorySessionStore,
    PostgresSessionStore,
    SessionData,
    SessionStore,
    get_session_store,
    reset_session_store,
    validate_session_backend_configuration,
)


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
        restored = SessionData(**dumped)
        assert restored == data

    def test_protocol_compliance(self):
        assert isinstance(MemorySessionStore(), SessionStore)
        assert isinstance(DynamoDBSessionStore(), SessionStore)
        assert isinstance(PostgresSessionStore(), SessionStore)


class TestMemorySessionStore:
    @pytest.fixture
    def store(self):
        return MemorySessionStore(max_sessions=3, max_history=10)

    async def _assert_get_creates_new_session(self, store):
        data = await store.get("new-session")
        assert data.session_id == "new-session"
        assert data.turn_count == 0

    async def _assert_save_persists_data(self, store):
        data = SessionData(session_id="s1", engine_context={"key": "value"}, turn_count=3)
        await store.save("s1", data)
        restored = await store.get("s1")
        assert restored.engine_context == {"key": "value"}
        assert restored.turn_count == 3

    async def _assert_eviction_at_capacity(self, store):
        await store.get("s1")
        await store.get("s2")
        await store.get("s3")
        await store.get("s4")
        assert not await store.exists("s1")
        assert await store.exists("s4")

    async def _assert_module_data_round_trip(self, store):
        await store.save_module_data("oca", "case-1", {"status": "PASS"})
        assert await store.get_module_data("oca", "case-1") == {"status": "PASS"}
        assert await store.list_module_keys("oca") == ["case-1"]

    def test_get_creates_new_session_sync(self, store):
        asyncio.run(self._assert_get_creates_new_session(store))

    def test_save_persists_data_sync(self, store):
        asyncio.run(self._assert_save_persists_data(store))

    def test_eviction_at_capacity_sync(self, store):
        asyncio.run(self._assert_eviction_at_capacity(store))

    def test_module_data_round_trip_sync(self, store):
        asyncio.run(self._assert_module_data_round_trip(store))


class TestSessionStoreFactory:
    def setup_method(self):
        reset_session_store()

    def teardown_method(self):
        reset_session_store()
        for name in (
            "ENVIRONMENT",
            "MIRA_SESSION_BACKEND",
            "MIRA_ENV",
            "MIRA_CHAT_DATABASE_URL",
            "POSTGRES_HOST",
            "POSTGRES_PASSWORD",
        ):
            os.environ.pop(name, None)

    def test_default_is_memory(self):
        assert isinstance(get_session_store(), MemorySessionStore)

    def test_explicit_memory(self):
        os.environ["MIRA_SESSION_BACKEND"] = "memory"
        assert isinstance(get_session_store(), MemorySessionStore)

    def test_explicit_postgres_with_database_url(self):
        os.environ["MIRA_SESSION_BACKEND"] = "postgres"
        os.environ["MIRA_CHAT_DATABASE_URL"] = "postgresql://user:pass@db.internal:5432/mira"
        assert isinstance(get_session_store(), PostgresSessionStore)

    def test_explicit_postgres_with_component_credentials(self):
        os.environ["MIRA_SESSION_BACKEND"] = "postgres"
        os.environ["POSTGRES_HOST"] = "db.internal"
        os.environ["POSTGRES_PASSWORD"] = "real-secret"
        assert isinstance(get_session_store(), PostgresSessionStore)

    def test_postgres_without_password_falls_back_to_memory(self):
        os.environ["MIRA_SESSION_BACKEND"] = "postgres"
        os.environ["POSTGRES_HOST"] = "db.internal"
        assert isinstance(get_session_store(), MemorySessionStore)

    def test_postgres_with_placeholder_password_falls_back_to_memory(self):
        os.environ["MIRA_SESSION_BACKEND"] = "postgres"
        os.environ["POSTGRES_HOST"] = "db.internal"
        os.environ["POSTGRES_PASSWORD"] = "restored"
        assert isinstance(get_session_store(), MemorySessionStore)

    def test_postgres_without_usable_credentials_raises_in_production(self):
        os.environ["MIRA_SESSION_BACKEND"] = "postgres"
        os.environ["MIRA_ENV"] = "production"
        os.environ["POSTGRES_HOST"] = "db.internal"
        with pytest.raises(RuntimeError):
            get_session_store()

    def test_validate_session_backend_configuration_is_noop_for_memory(self):
        os.environ["MIRA_SESSION_BACKEND"] = "memory"
        validate_session_backend_configuration()

    def test_validate_session_backend_configuration_supports_running_event_loop(self, monkeypatch):
        os.environ["MIRA_SESSION_BACKEND"] = "postgres"
        os.environ["POSTGRES_HOST"] = "db.internal"
        os.environ["POSTGRES_PASSWORD"] = "real-secret"

        store = PostgresSessionStore()
        called = {"count": 0}

        async def fake_preflight():
            called["count"] += 1

        monkeypatch.setattr(store, "preflight", fake_preflight)
        monkeypatch.setattr(session_store_module, "get_session_store", lambda: store)
        monkeypatch.setattr(
            session_store_module,
            "_has_usable_postgres_configuration",
            lambda: True,
        )

        async def _run():
            validate_session_backend_configuration()

        asyncio.run(_run())
        assert called["count"] == 1

    def test_dynamodb_scaffolded(self):
        os.environ["MIRA_SESSION_BACKEND"] = "dynamodb"
        assert isinstance(get_session_store(), DynamoDBSessionStore)
