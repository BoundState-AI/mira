from __future__ import annotations

import json
import uuid


def _parse_sse_events(raw_stream: str) -> list[dict]:
    events: list[dict] = []
    for block in raw_stream.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[len("data:"):].strip()
            for line in block.split("\n")
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        events.append(json.loads("\n".join(data_lines)))
    return events


def test_chat_ping_reports_expected_adapters(api_client):
    response = api_client.get("/api/chat/ping")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["domain"] == "chat"
    adapters = set(payload["adapters_loaded"].split(","))
    assert {"bsmh", "fracture", "galvanic", "gpcm", "h2", "maptis_search", "oca"} <= adapters


def test_chat_returns_structured_response(api_client):
    response = api_client.post(
        "/api/chat/",
        json={"message": "Is 316L compatible with GOX at 3000 psi?"},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["session_id"]
    assert payload["engine_used"] == "oca"
    assert payload["verdict"] in {
        "PASS",
        "CONDITIONAL_PASS",
        "FAIL",
        "INSUFFICIENT_DATA",
    }
    assert isinstance(payload["response"], str) and payload["response"]
    assert isinstance(payload["follow_up_suggestions"], list)
    assert payload["entities"]["material_designation"] == "316L"
    assert payload["entities"]["gas_service"] == "oxygen"


def test_chat_can_resume_from_frontend_history_without_server_session(api_client):
    first_response = api_client.post(
        "/api/chat/",
        json={"message": "Is 316L compatible with GOX at 3000 psi?"},
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()

    history = [
        {
            "role": "user",
            "content": "Is 316L compatible with GOX at 3000 psi?",
            "entities": first_payload["entities"],
        },
        {
            "role": "assistant",
            "content": first_payload["response"],
            "engine_used": first_payload["engine_used"],
            "entities": first_payload["entities"],
        },
    ]

    second_response = api_client.post(
        "/api/chat/",
        json={
            "session_id": "frontend-history-only",
            "message": "What about at 1500 psi?",
            "history": history,
        },
    )

    assert second_response.status_code == 200
    second_payload = second_response.json()

    assert second_payload["engine_used"] == "oca"
    assert second_payload["entities"]["material_designation"] == "316L"
    assert second_payload["entities"]["pressure_value"] == 1500.0


def test_chat_can_resume_from_server_side_session_without_frontend_history(api_client):
    session_id = f"server-side-{uuid.uuid4().hex}"

    first_response = api_client.post(
        "/api/chat/",
        json={
            "session_id": session_id,
            "message": "Is 316L compatible with GOX at 3000 psi?",
        },
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()
    assert first_payload["entities"]["material_designation"] == "316L"

    second_response = api_client.post(
        "/api/chat/",
        json={
            "session_id": session_id,
            "message": "What about at 1500 psi?",
        },
    )

    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload["engine_used"] == "oca"
    assert second_payload["entities"]["material_designation"] == "316L"
    assert second_payload["entities"]["pressure_value"] == 1500.0


def test_chat_routes_hydrogen_shorthand_to_h2(api_client):
    response = api_client.post(
        "/api/chat/",
        json={"message": "is A286 ok in H2"},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["engine_used"] == "h2"
    assert payload["verdict"] in {
        "PASS",
        "CONDITIONAL_PASS",
        "FAIL",
        "INSUFFICIENT_DATA",
    }
    assert payload["entities"]["material_designation"] == "A286"
    assert payload["entities"]["gas_service"] == "hydrogen"


def test_chat_routes_galvanic_pair_questions_to_galvanic(api_client):
    response = api_client.post(
        "/api/chat/",
        json={"message": "What galvanic risk do I have between 7075-T73 and CRES 304 in seawater proxy?"},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["engine_used"] == "galvanic"
    assert payload["verdict"] in {"PASS", "CONDITIONAL_PASS", "FAIL", "INSUFFICIENT_DATA"}
    assert payload["entities"]["material_designation"] == "7075-T73"
    assert payload["entities"]["second_material"] == "CRES 304"
    assert payload["entities"]["environment"] == "seawater_proxy"
    assert "7075" in payload["response"]
    assert "304" in payload["response"]


def test_chat_module_context_keeps_follow_up_in_module(api_client):
    response = api_client.post(
        "/api/chat/",
        json={
            "message": "What about this material at 1500 psi?",
            "module_context": {
                "module": "oca",
                "material": "316L",
                "environment": "GOX",
                "pressure_psi": 3000,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["engine_used"] == "oca"
    assert payload["entities"]["material_designation"] == "316L"
    assert payload["entities"]["pressure_value"] == 1500.0


def test_chat_module_context_allows_explicit_cross_domain_override(api_client):
    response = api_client.post(
        "/api/chat/",
        json={
            "message": "What about hydrogen compatibility for this material at 1500 psi?",
            "module_context": {
                "module": "oca",
                "material": "316L",
                "environment": "GOX",
                "pressure_psi": 3000,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["engine_used"] == "h2"
    assert payload["entities"]["material_designation"] == "316L"
    assert payload["entities"]["gas_service"] == "hydrogen"


def test_chat_stream_returns_sse_events(api_client):
    with api_client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "Is 316L compatible with GOX at 3000 psi?"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw_stream = "".join(response.iter_text())

    events = _parse_sse_events(raw_stream)
    assert events
    assert events[0]["type"] == "meta"
    assert events[0]["engine_id"] == "oca"
    assert any(event["type"] == "text" for event in events)

    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["session_id"]
    assert done_event["entities"]["material_designation"] == "316L"
    assert done_event["entities"]["gas_service"] == "oxygen"


def test_chat_stream_can_resume_from_frontend_history(api_client):
    first_response = api_client.post(
        "/api/chat/",
        json={"message": "Is 316L compatible with GOX at 3000 psi?"},
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()

    history = [
        {
            "role": "user",
            "content": "Is 316L compatible with GOX at 3000 psi?",
            "entities": first_payload["entities"],
        },
        {
            "role": "assistant",
            "content": first_payload["response"],
            "engine_used": first_payload["engine_used"],
            "entities": first_payload["entities"],
        },
    ]

    with api_client.stream(
        "POST",
        "/api/chat/stream",
        json={
            "session_id": "frontend-history-only-stream",
            "message": "What about at 1500 psi?",
            "history": history,
        },
    ) as response:
        assert response.status_code == 200
        raw_stream = "".join(response.iter_text())

    events = _parse_sse_events(raw_stream)
    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["entities"]["material_designation"] == "316L"
    assert done_event["entities"]["pressure_value"] == 1500.0
