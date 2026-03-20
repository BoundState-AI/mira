"""Smoke tests for matchmaker router wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mira.api.app import create_app


def _session_payload() -> dict:
    return {
        "material": "6061-T6",
        "application_description": "Cabin bracket",
        "environment": {
            "o2_percent": 21.0,
            "pressure_psia": 14.7,
            "temp_min_f": 60.0,
            "temp_max_f": 90.0,
            "medium": "AIR",
            "location": "habitable",
            "application": "Cabin bracket",
        },
    }


def test_create_session_and_answer_flow() -> None:
    client = TestClient(create_app())
    created = client.post("/mua/matchmaker/sessions", json=_session_payload())
    assert created.status_code == 200
    sid = created.json()["session_id"]

    questions = client.get(f"/mua/matchmaker/sessions/{sid}/issues/FLAM/questions")
    assert questions.status_code == 200
    assert questions.json()["issue"] == "FLAM"

    answered = client.post(
        f"/mua/matchmaker/sessions/{sid}/issues/FLAM/answer",
        json={"question_id": "Q1", "answer": "A"},
    )
    assert answered.status_code == 200
    assert answered.json()["outcome"] == "PASS"
    assert answered.json()["status"] == "done"


def test_session_includes_fc_o2_h2_issues() -> None:
    client = TestClient(create_app())
    created = client.post("/mua/matchmaker/sessions", json=_session_payload())
    assert created.status_code == 200

    issues = set(created.json()["issues"].keys())
    assert {"FLUID", "O2", "HEE"}.issubset(issues)


def test_session_auto_seeds_trigger_gates() -> None:
    client = TestClient(create_app())
    created = client.post("/mua/matchmaker/sessions", json=_session_payload())
    assert created.status_code == 200

    issues = created.json()["issues"]
    assert issues["O2"]["status"] == "done"
    assert issues["O2"]["outcome"] == "PASS"
    assert issues["HEE"]["status"] == "done"
    assert issues["HEE"]["outcome"] == "PASS"
    assert issues["FLUID"]["status"] == "done"
    assert issues["FLUID"]["outcome"] == "PASS"
    assert issues["TOX"]["status"] == "in_progress"
    assert issues["FLAM"]["status"] == "in_progress"
    assert issues["SCC"]["status"] == "in_progress"
    assert issues["CORR"]["status"] == "in_progress"
    assert issues["TVS"]["status"] == "in_progress"


def test_import_miul_applies_trigger_signature(monkeypatch) -> None:
    client = TestClient(create_app())

    def _fake_parse(_contents: bytes, _filename: str):
        return [
            {
                "material_input": "A286",
                "environment": {
                    "o2_percent": 21.0,
                    "pressure_psia": 14.7,
                    "temp_min_f": 60.0,
                    "temp_max_f": 90.0,
                    "medium": "AIR",
                    "location": "habitable",
                    "application": "Bracket",
                },
                "sample_descriptions": ["Bracket"],
                "trigger_signature": "FS:U|SCC:U",
            }
        ]

    monkeypatch.setattr("mira.api.routers.matchmaker.parse_miul_upload", _fake_parse)

    uploaded = client.post(
        "/mua/matchmaker/batch/import-miul",
        files={"file": ("miul.xlsx", b"unused", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert uploaded.status_code == 200
    session_id = uploaded.json()["created_sessions"][0]

    session = client.get(f"/mua/matchmaker/sessions/{session_id}")
    assert session.status_code == 200
    issues = session.json()["issues"]

    assert issues["FLUID"]["status"] == "in_progress"
    assert issues["SCC"]["status"] == "in_progress"
    assert issues["CORR"]["status"] == "done"
    assert issues["CORR"]["outcome"] == "PASS"
    assert issues["TVS"]["status"] == "done"
    assert issues["TVS"]["outcome"] == "PASS"


def test_board_ready_export_blocks_when_incomplete() -> None:
    client = TestClient(create_app())
    created = client.post("/mua/matchmaker/sessions", json=_session_payload())
    sid = created.json()["session_id"]

    exported = client.get(f"/mua/matchmaker/sessions/{sid}/export?mode=board_ready")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["mode"] == "board_ready"
    assert payload["export_ready"] is False
    assert payload["blockers"] or payload["missing_fields"]
