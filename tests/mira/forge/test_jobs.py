from __future__ import annotations

import time
from pathlib import Path

import pytest

from mira.forge.jobs import (
    ForgeCompileJobManager,
    _ForgeJobState,
    _SQLiteJobStore,
    _utc_now,
)
from mira.forge.models import (
    ForgeCompilationSummary,
    ForgeCompileJobEvent,
    ForgeCompileRequest,
    ForgeCompileResponse,
)


class _StubCompiler:
    def __init__(self) -> None:
        self.calls = 0

    def compile_database(self, request: ForgeCompileRequest, *, progress_callback=None) -> ForgeCompileResponse:
        self.calls += 1
        if progress_callback is not None:
            progress_callback("question_generation", "Generating curated questions.", 55.0)
        return ForgeCompileResponse(
            status="ok",
            summary=ForgeCompilationSummary(
                app_name=request.app_name,
                database_url_redacted="sqlite:///fixture.sqlite",
                dialect="sqlite",
                schemas=[],
                table_count=1,
                column_count=2,
                relationship_count=0,
                latent_relationship_count=0,
                generated_question_count=3,
            ),
        )


def _wait_for_status(manager: ForgeCompileJobManager, job_id: str, expected: str, timeout_s: float = 5.0):
    deadline = time.monotonic() + timeout_s
    payload = None
    while time.monotonic() < deadline:
        payload = manager.get(job_id)
        if payload is not None and payload.status == expected:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for FORGE job {job_id} to reach {expected!r}")


def test_completed_job_survives_manager_restart(tmp_path: Path) -> None:
    store_path = tmp_path / "forge_jobs.sqlite3"
    request = ForgeCompileRequest(
        database_url="sqlite:///fixture.sqlite",
        app_name="Persistent Forge",
        require_llm_refinement=False,
    )

    compiler = _StubCompiler()
    manager = ForgeCompileJobManager(compiler, store_path=store_path)
    accepted = manager.submit(request)

    completed = _wait_for_status(manager, accepted.job_id, "completed")
    assert completed.result is not None
    assert compiler.calls == 1

    restarted_compiler = _StubCompiler()
    restarted_manager = ForgeCompileJobManager(restarted_compiler, store_path=store_path)
    persisted = restarted_manager.get(accepted.job_id)

    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.result is not None
    assert persisted.result.summary.app_name == "Persistent Forge"
    assert restarted_compiler.calls == 0


def test_running_job_is_marked_interrupted_on_manager_startup_by_default(tmp_path: Path) -> None:
    store_path = tmp_path / "forge_jobs_resume.sqlite3"
    request = ForgeCompileRequest(
        database_url="sqlite:///fixture.sqlite",
        app_name="Resumed Forge",
        require_llm_refinement=False,
    )
    timestamp = _utc_now()

    store = _SQLiteJobStore(store_path)
    store.upsert(
        _ForgeJobState(
            job_id="resume-me",
            request=request,
            status="running",
            stage="introspection",
            message="Inspecting schema.",
            progress=33.0,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=timestamp,
            events=[
                ForgeCompileJobEvent(
                    timestamp=timestamp,
                    status="running",
                    stage="introspection",
                    message="Inspecting schema.",
                    progress=33.0,
                )
            ],
        )
    )

    compiler = _StubCompiler()
    manager = ForgeCompileJobManager(compiler, store_path=store_path)
    interrupted = _wait_for_status(manager, "resume-me", "failed")

    assert interrupted.error == "FORGE compile interrupted by application restart"
    assert compiler.calls == 0
    assert any("interrupted by application restart" in event.message.lower() for event in interrupted.events)


def test_running_job_can_auto_resume_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_AUTO_RESUME_JOBS", "true")
    store_path = tmp_path / "forge_jobs_auto_resume.sqlite3"
    request = ForgeCompileRequest(
        database_url="sqlite:///fixture.sqlite",
        app_name="Resumed Forge",
        require_llm_refinement=False,
    )
    timestamp = _utc_now()

    store = _SQLiteJobStore(store_path)
    store.upsert(
        _ForgeJobState(
            job_id="resume-me",
            request=request,
            status="running",
            stage="introspection",
            message="Inspecting schema.",
            progress=33.0,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=timestamp,
            events=[
                ForgeCompileJobEvent(
                    timestamp=timestamp,
                    status="running",
                    stage="introspection",
                    message="Inspecting schema.",
                    progress=33.0,
                )
            ],
        )
    )

    compiler = _StubCompiler()
    manager = ForgeCompileJobManager(compiler, store_path=store_path)
    completed = _wait_for_status(manager, "resume-me", "completed")

    assert completed.result is not None
    assert completed.result.summary.app_name == "Resumed Forge"
    assert compiler.calls == 1
    assert any("resumed after application restart" in event.message.lower() for event in completed.events)
