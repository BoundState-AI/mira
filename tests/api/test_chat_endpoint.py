from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


def _oracle_fixture_root() -> Path:
    root = Path(__file__).resolve().parents[1] / ".tmp" / "oracle_chat"
    root.mkdir(parents=True, exist_ok=True)
    return root


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


def _write_oracle_fixture_pack(
    *,
    standard_id: str = "NASA-STD-5009C",
    standard_title: str = "NASA-STD-5009C Fracture Control Requirements",
    rule_pack_id: str = "oracle-fixture-5009c",
    rules: list[dict] | None = None,
) -> Path:
    fixture_root = _oracle_fixture_root()
    pack_path = fixture_root / f"oracle_fixture_pack_{uuid.uuid4().hex}.json"
    effective_rules = rules or [
        {
            "rule_id": "5009-001",
            "obligation_type": "prohibition",
            "obligation_keyword": "shall not",
            "section": "5.8.4",
            "statement_text": "Pure tin finishes shall not be used on spaceflight hardware because tin whiskers can create reliability risk.",
            "subject": "Tin whiskers",
            "requirement": "Avoid pure tin finishes on spaceflight hardware.",
            "severity": "high",
            "keywords": ["tin", "whiskers", "pure tin", "finishes"],
            "page": 42,
        },
        {
            "rule_id": "5009-002",
            "obligation_type": "mandatory",
            "obligation_keyword": "shall",
            "section": "5.8.5",
            "statement_text": "Programs shall document mitigation controls when a prohibited finish exception is approved.",
            "subject": "Mitigation documentation",
            "requirement": "Document approved mitigation controls.",
            "severity": "medium",
            "keywords": ["mitigation", "documentation", "exception"],
            "page": 43,
        },
    ]
    pack_path.write_text(
        json.dumps(
            {
                "schema_version": "oracle_generic/v1",
                "rule_pack_id": rule_pack_id,
                "standard_id": standard_id,
                "standard_title": standard_title,
                "version": "1.0.0",
                "generated_at": "2026-04-08T00:00:00Z",
                "total_rules": len(effective_rules),
                "oracle_metadata": {
                    "name": standard_id,
                    "slug": standard_id.lower().replace("-", "_").replace(" ", "_"),
                    "status": "draft",
                    "added_at": "2026-04-08T00:00:00Z",
                },
                "rules": effective_rules,
            }
        ),
        encoding="utf-8",
    )
    return pack_path


def _make_oracle_library_dir() -> Path:
    library_dir = _oracle_fixture_root() / f"library_{uuid.uuid4().hex}"
    library_dir.mkdir(parents=True, exist_ok=True)
    return library_dir


def test_chat_ping_reports_expected_adapters(api_client):
    response = api_client.get("/api/chat/ping")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["domain"] == "chat"
    adapters = set(payload["adapters_loaded"].split(","))
    assert {"bsmh", "fracture", "galvanic", "gpcm", "h2", "maptis_search", "oca", "oracle"} <= adapters


def test_oracle_pack_catalog_endpoint(api_client, monkeypatch):
    pack_path = _write_oracle_fixture_pack()
    try:
        monkeypatch.setenv("ORACLE_CHAT_PACK_PATHS", str(pack_path))

        response = api_client.get("/api/chat/oracle/packs")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert any(item["standard_id"] == "NASA-STD-5009C" for item in payload["packs"])
    finally:
        pack_path.unlink(missing_ok=True)


def test_oracle_import_pack_endpoint(api_client, monkeypatch):
    library_dir = _make_oracle_library_dir()
    pack_path = _write_oracle_fixture_pack()
    try:
        monkeypatch.setenv("ORACLE_CHAT_LIBRARY_DIR", str(library_dir))
        response = api_client.post(
            "/api/chat/oracle/import-pack",
            files={"pack_file": ("fixture_pack.json", pack_path.read_bytes(), "application/json")},
            data={"overwrite": "true", "allow_partial": "true"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert any(item["standard_id"] == "NASA-STD-5009C" for item in payload["packs"])
        assert any(candidate.suffix == ".json" for candidate in library_dir.iterdir())
    finally:
        pack_path.unlink(missing_ok=True)


def test_oracle_refresh_endpoint_picks_up_new_pack_without_restart(api_client, monkeypatch):
    library_dir = _make_oracle_library_dir()
    first_pack = _write_oracle_fixture_pack()
    second_pack = _write_oracle_fixture_pack(
        standard_id="MSFC-STD-3012A",
        standard_title="MSFC-STD-3012A EEE Parts Management Requirements",
        rule_pack_id="oracle-fixture-3012a",
        rules=[
            {
                "rule_id": "3012-001",
                "obligation_type": "mandatory",
                "obligation_keyword": "shall",
                "section": "Table V Note 6",
                "statement_text": "Connector plating shall avoid pure tin in high-reliability spaceflight use.",
                "subject": "Connector plating",
                "requirement": "Avoid pure tin plating.",
                "severity": "high",
                "keywords": ["connector", "plating", "pure tin"],
                "page": 88,
            },
        ],
    )
    try:
        monkeypatch.setenv("ORACLE_CHAT_LIBRARY_DIR", str(library_dir))

        import_response = api_client.post(
            "/api/chat/oracle/import-pack",
            files={"pack_file": ("fixture_pack.json", first_pack.read_bytes(), "application/json")},
            data={"overwrite": "true", "allow_partial": "true"},
        )
        assert import_response.status_code == 200

        initial = api_client.get("/api/chat/oracle/packs").json()
        initial_count = len(initial["packs"])
        assert any(item["standard_id"] == "NASA-STD-5009C" for item in initial["packs"])

        target = library_dir / "msfc_std_3012a.json"
        target.write_bytes(second_pack.read_bytes())

        stale = api_client.get("/api/chat/oracle/packs").json()
        assert len(stale["packs"]) == initial_count

        refreshed = api_client.post("/api/chat/oracle/refresh").json()
        assert refreshed["status"] == "ok"
        assert len(refreshed["packs"]) == initial_count + 1
        assert any(item["standard_id"] == "MSFC-STD-3012A" for item in refreshed["packs"])
    finally:
        first_pack.unlink(missing_ok=True)
        second_pack.unlink(missing_ok=True)


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


def test_chat_routes_standards_lookup_to_oracle(api_client, monkeypatch):
    pack_path = _write_oracle_fixture_pack()
    try:
        monkeypatch.setenv("ORACLE_CHAT_PACK_PATHS", str(pack_path))

        response = api_client.post(
            "/api/chat/",
            json={"message": "What does NASA-STD-5009C say about tin whiskers?"},
        )

        assert response.status_code == 200
        payload = response.json()

        assert payload["engine_used"] == "oracle"
        assert payload["verdict"] == "PASS"
        assert "NASA-STD-5009C" in payload["response"]
        assert "tin whiskers" in payload["response"].lower()
        assert payload["entities"]["standard_ref"] == "NASA-STD-5009C"
    finally:
        pack_path.unlink(missing_ok=True)


def test_chat_module_context_keeps_oracle_scoped_follow_up(api_client, monkeypatch):
    pack_path = _write_oracle_fixture_pack()
    try:
        monkeypatch.setenv("ORACLE_CHAT_PACK_PATHS", str(pack_path))

        response = api_client.post(
            "/api/chat/",
            json={
                "message": "What does section 5.8.4 say?",
                "module_context": {
                    "module": "oracle",
                    "standard_ref": "NASA-STD-5009C",
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()

        assert payload["engine_used"] == "oracle"
        assert payload["entities"]["standard_ref"] == "NASA-STD-5009C"
        assert "5.8.4" in payload["response"]
    finally:
        pack_path.unlink(missing_ok=True)


def test_chat_module_context_compare_only_uses_multiple_packs(api_client, monkeypatch):
    first_pack = _write_oracle_fixture_pack()
    second_pack = _write_oracle_fixture_pack(
        standard_id="MSFC-STD-3012A",
        standard_title="MSFC-STD-3012A EEE Parts Management Requirements",
        rule_pack_id="oracle-fixture-3012a",
        rules=[
            {
                "rule_id": "3012-001",
                "obligation_type": "mandatory",
                "obligation_keyword": "shall",
                "section": "Table V Note 6",
                "statement_text": "Pure tin finishes shall not be used on connectors for spaceflight hardware.",
                "subject": "Tin whiskers",
                "requirement": "Avoid pure tin on connectors.",
                "severity": "high",
                "keywords": ["tin", "whiskers", "pure tin", "connectors"],
                "page": 88,
            },
        ],
    )
    try:
        monkeypatch.setenv("ORACLE_CHAT_PACK_PATHS", f"{first_pack}{os.pathsep}{second_pack}")

        response = api_client.post(
            "/api/chat/",
            json={
                "message": "How do these standards treat tin whiskers?",
                "module_context": {
                    "module": "oracle",
                    "standard_ref": "NASA-STD-5009C",
                    "compare_standard_refs": ["NASA-STD-5009C", "MSFC-STD-3012A"],
                    "compare_only": True,
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()

        assert payload["engine_used"] == "oracle"
        assert "NASA-STD-5009C" in payload["response"]
        assert "MSFC-STD-3012A" in payload["response"]
    finally:
        first_pack.unlink(missing_ok=True)
        second_pack.unlink(missing_ok=True)


def test_chat_stream_oracle_exposes_citations_and_advisory(api_client, monkeypatch):
    pack_path = _write_oracle_fixture_pack()
    try:
        monkeypatch.setenv("ORACLE_CHAT_PACK_PATHS", str(pack_path))

        with api_client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "What does NASA-STD-5009C say about tin whiskers?"},
        ) as response:
            assert response.status_code == 200
            raw_stream = "".join(response.iter_text())

        events = _parse_sse_events(raw_stream)
        done_event = next(event for event in events if event["type"] == "done")

        assert done_event["advisory_only"] is True
        assert any("NASA-STD-5009C" in citation for citation in done_event["citations"])
    finally:
        pack_path.unlink(missing_ok=True)


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
