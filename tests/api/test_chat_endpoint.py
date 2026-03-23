from __future__ import annotations


def test_chat_ping_reports_expected_adapters(api_client):
    response = api_client.get("/api/chat/ping")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["domain"] == "chat"
    adapters = set(payload["adapters_loaded"].split(","))
    assert {"bsmh", "fracture", "galvanic", "gpcm", "h2", "maptis_search", "mp_plan", "oca"} <= adapters


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


def test_chat_routes_mp_plan_module_context_to_mp_plan(api_client):
    create_session = api_client.post(
        "/mp-plan/v2/sessions",
        json={"program_name": "Gateway", "program_phase": "PDR"},
    )
    assert create_session.status_code == 200
    session_id = create_session.json()["session_id"]

    response = api_client.post(
        "/api/chat/",
        json={
            "message": "What is blocking this plan right now?",
            "module_context": {
                "module": "mp_plan",
                "mp_plan_session_id": session_id,
                "program_name": "Gateway",
                "program_phase": "PDR",
                "current_step": "setup",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["engine_used"] == "mp_plan"
    assert payload["verdict"] == "INSUFFICIENT_DATA"
    assert isinstance(payload["response"], str) and payload["response"]
