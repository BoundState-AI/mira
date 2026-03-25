from __future__ import annotations

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mira.api.routers.usage import router


def test_usage_event_endpoint_records_pageview(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/usage")
    client = TestClient(app)

    logger_info = Mock()
    monkeypatch.setattr("mira.api.routers.usage.LOGGER.info", logger_info)

    response = client.post(
        "/api/usage/events",
        json={
            "event_type": "pageview",
            "path": "/oca/system-builder",
            "module_id": "oca-system-builder",
            "page_label": "OCA System Builder",
            "navigation_type": "PUSH",
            "client_session_id": "session-12345678",
            "referrer": "https://mira.boundstate.ai/",
        },
        headers={"X-Forwarded-For": "203.0.113.42", "User-Agent": "pytest-agent"},
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    logger_info.assert_called_once()
    logged_message = logger_info.call_args.args[1]
    assert '"path":"/oca/system-builder"' in logged_message
    assert '"client_ip":"203.0.113.42"' in logged_message


def test_usage_event_endpoint_rejects_non_absolute_paths() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/usage")
    client = TestClient(app)

    response = client.post(
        "/api/usage/events",
        json={
            "event_type": "pageview",
            "path": "oca/system-builder",
            "module_id": "oca-system-builder",
            "page_label": "OCA System Builder",
            "navigation_type": "PUSH",
            "client_session_id": "session-12345678",
        },
    )

    assert response.status_code == 422
