from __future__ import annotations

import sys
import importlib
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_app_factory():
    for name in list(sys.modules):
        if name == "mira" or name.startswith("mira."):
            sys.modules.pop(name, None)

    mira_pkg = types.ModuleType("mira")
    mira_pkg.__path__ = [str(PROJECT_ROOT / "mira")]
    sys.modules["mira"] = mira_pkg

    api_pkg = types.ModuleType("mira.api")
    api_pkg.__path__ = [str(PROJECT_ROOT / "mira" / "api")]
    sys.modules["mira.api"] = api_pkg

    importlib.invalidate_caches()
    module_path = PROJECT_ROOT / "mira" / "api" / "app_factory.py"
    spec = spec_from_file_location("mira.api.app_factory", module_path)
    module = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules["mira.api.app_factory"] = module
    spec.loader.exec_module(module)
    return module


def test_app_factory_mounts_ic_routes() -> None:
    module = _load_app_factory()
    app = module.create_app(app_identity_file=__file__)
    client = TestClient(app)

    response = client.get("/api/ic/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ic_routes_accept_allowed_client_ids(monkeypatch) -> None:
    monkeypatch.setenv("MIRA_AUTH_MODE", "cognito")
    monkeypatch.setenv("MIRA_ENV", "development")
    monkeypatch.setenv("COGNITO_REGION", "us-gov-west-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-gov-west-1_example")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "mira-client")
    monkeypatch.setenv("IC_ALLOWED_CLIENT_IDS", "forge-client")

    module = _load_app_factory()
    cognito_module = importlib.import_module("mira.api.auth.cognito")

    async def fake_verify(token: str, *, path: str | None = None):
        assert token == "token"
        assert path == "/api/ic/health"
        return {
            "sub": "123",
            "cognito:username": "forge-user",
            "email": "forge@example.com",
            "token_use": "access",
            "client_id": "forge-client",
        }

    monkeypatch.setattr(cognito_module, "_verify_token_string", fake_verify)

    app = module.create_app(app_identity_file=__file__)
    client = TestClient(app)

    response = client.get("/api/ic/health", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
