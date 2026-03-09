#!/usr/bin/env python3
"""Tests for the Codex versioned M&P plan router."""

import pytest
from fastapi.testclient import TestClient

from mira.mp_plan.generation.plan_json_codex import generate_mp_plan_json_bytes_codex
from mira.mp_plan.models import AcceptedOpenGap, MaterialResolutionResult, UserDecision
from mira.mp_plan.session_manager import get_session_manager


@pytest.fixture
def client():
    from mira.api.app_codex import app

    return TestClient(app)


def test_ping(client):
    response = client.get("/mp-plan/v2/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["domain"] == "mp_plan_v2_codex"


def test_vehicle_presets(client):
    response = client.get("/mp-plan/v2/vehicle-presets")
    assert response.status_code == 200
    payload = response.json()
    assert "presets" in payload
    assert payload["presets"]
    assert all("preset_id" in preset for preset in payload["presets"])


def test_compute_and_questions(client):
    create = client.post(
        "/mp-plan/v2/sessions",
        json={"program_name": "Codex Test", "vehicle_preset": "ISS"},
    )
    assert create.status_code == 200
    session_id = create.json()["session_id"]

    add_materials = client.post(
        f"/mp-plan/v2/sessions/{session_id}/materials",
        json={"materials": [{"name": "Kapton Tape", "application": "Wire harness wrap"}]},
    )
    assert add_materials.status_code == 200
    assert add_materials.json()["count"] == 1

    compute = client.post(f"/mp-plan/v2/sessions/{session_id}/compute")
    assert compute.status_code == 200
    payload = compute.json()
    assert payload["status"] == "computed"
    assert payload["determinations"] > 0
    assert payload["materials"] == 1
    assert payload["environments"] == 1

    q_resp = client.get(f"/mp-plan/v2/sessions/{session_id}/questions")
    assert q_resp.status_code == 200
    q_payload = q_resp.json()
    assert q_payload["count"] >= 1
    review_questions = [
        q
        for q in q_payload["questions"]
        if q.get("question_type") == "tailoring_approval"
    ]
    assert review_questions
    assert "ADD_TEST_CITATION" in review_questions[0].get("options", [])


def test_export_json(client):
    create = client.post(
        "/mp-plan/v2/sessions",
        json={"program_name": "Export Test", "vehicle_preset": "ISS"},
    )
    session_id = create.json()["session_id"]

    client.post(
        f"/mp-plan/v2/sessions/{session_id}/materials",
        json={"materials": [{"name": "PTFE", "application": "Insulation"}]},
    )
    client.post(f"/mp-plan/v2/sessions/{session_id}/compute")

    export = client.get(f"/mp-plan/v2/sessions/{session_id}/export/mp-plan-json")
    assert export.status_code == 200
    payload = export.json()
    assert payload["session"]["session_id"] == session_id
    assert "mpr_determinations" in payload
    assert "statistics" in payload


def test_citation_helper_endpoint(client):
    create = client.post(
        "/mp-plan/v2/sessions",
        json={"program_name": "Helper Test", "vehicle_preset": "ISS"},
    )
    session_id = create.json()["session_id"]

    client.post(
        f"/mp-plan/v2/sessions/{session_id}/materials",
        json={"materials": [{"name": "Unknown Alloy", "application": "Bracket"}]},
    )
    client.post(f"/mp-plan/v2/sessions/{session_id}/compute")

    session_resp = client.get(f"/mp-plan/v2/sessions/{session_id}")
    assert session_resp.status_code == 200
    dets = session_resp.json().get("mpr_determinations", [])
    assert dets
    det_id = dets[0]["determination_id"]

    helper = client.get(f"/mp-plan/v2/sessions/{session_id}/citation-helper/{det_id}")
    assert helper.status_code == 200
    payload = helper.json()
    assert payload["determination_id"] == det_id
    assert "citation_helper" in payload
    assert "quick_actions" in payload


def test_submit_answer_no_500_on_none_human_review(client):
    create = client.post(
        "/mp-plan/v2/sessions",
        json={"program_name": "Answer Path Test", "vehicle_preset": "ISS"},
    )
    assert create.status_code == 200
    session_id = create.json()["session_id"]

    add_materials = client.post(
        f"/mp-plan/v2/sessions/{session_id}/materials",
        json={"materials": [{"name": "Kapton Tape", "application": "Wire harness wrap"}]},
    )
    assert add_materials.status_code == 200

    compute = client.post(f"/mp-plan/v2/sessions/{session_id}/compute")
    assert compute.status_code == 200

    q_resp = client.get(f"/mp-plan/v2/sessions/{session_id}/questions")
    assert q_resp.status_code == 200
    questions = q_resp.json()["questions"]
    review_q = next(
        (q for q in questions if q.get("question_type") == "tailoring_approval"),
        None,
    )
    assert review_q is not None

    answer = client.post(
        f"/mp-plan/v2/sessions/{session_id}/answer",
        json={
            "question_id": review_q["question_id"],
            "answer": "ADD_TEST_CITATION",
            "rationale": "Need explicit use-condition test reference.",
        },
    )
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["status"] == "applied"

    # Follow-up citation question should now be generated
    q_after = client.get(f"/mp-plan/v2/sessions/{session_id}/questions")
    assert q_after.status_code == 200
    citation_q = next(
        (q for q in q_after.json()["questions"] if q.get("source") == "citation_request"),
        None,
    )
    assert citation_q is not None

    submit_citation = client.post(
        f"/mp-plan/v2/sessions/{session_id}/answer",
        json={
            "question_id": citation_q["question_id"],
            "answer": "TR-2026-114 | Sec 5.2 | Passes NASA-STD-6001 test at 30% O2, 14.7 psia",
            "rationale": "Direct test evidence.",
        },
    )
    assert submit_citation.status_code == 200


def test_generate_mp_plan_json_bytes_handles_datetime():
    manager = get_session_manager()
    session = manager.create_session(program_name="JSON Datetime Test", vehicle_preset="ISS")
    session.user_decisions.append(
        UserDecision(
            question_id="q1",
            decision="ADD_TEST_CITATION",
            rationale="Need evidence",
            decided_by="tester",
            source="test",
        )
    )
    session.accepted_open_gaps.append(
        AcceptedOpenGap(
            gap_id="gap-1",
            gap_type="nonconformance",
            accepted_by="tester",
            acceptance_rationale="Accepted for tracking",
            owner="tester",
            due_date=session.created_at.date(),
            risk_statement="Test risk statement",
        )
    )
    payload = generate_mp_plan_json_bytes_codex(session)
    assert payload
    assert b"JSON Datetime Test" in payload


def test_generate_endpoint_mp_plan_json_no_datetime_crash(client):
    create = client.post(
        "/mp-plan/v2/sessions",
        json={"program_name": "Generate Endpoint Test", "vehicle_preset": "ISS"},
    )
    assert create.status_code == 200
    session_id = create.json()["session_id"]

    add_mat = client.post(
        f"/mp-plan/v2/sessions/{session_id}/materials",
        json={
            "materials": [
                {"name": "A286", "application": "Fastener", "maptis_code": "A286-TEST"}
            ]
        },
    )
    assert add_mat.status_code == 200
    mat_id = add_mat.json()["materials"][0]["id"]

    manager = get_session_manager()
    session = manager.get_session(session_id)
    session.maptis_resolutions = [
        MaterialResolutionResult(
            material_id=mat_id,
            maptis_code="A286-TEST",
            flam_rating="A",
            tvs_rating="A",
            tox_rating="A",
            test_o2_pct=30.0,
            source="test",
        )
    ]
    session.user_decisions.append(
        UserDecision(
            question_id="q2",
            decision="ACCEPT",
            rationale="regression coverage",
            decided_by="tester",
            source="test",
        )
    )
    manager.update_session(session)

    generate = client.post(
        f"/mp-plan/v2/sessions/{session_id}/generate",
        json={"artifacts": ["mp_plan_json"]},
    )
    assert generate.status_code == 200
    payload = generate.json()
    assert payload["status"] == "generated"
    assert payload["artifacts"][0]["name"] == "mp_plan_json"
