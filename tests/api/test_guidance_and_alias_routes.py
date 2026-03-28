from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mira.api.app_factory import _register_alias_routers, _register_direct_routers


def _load_router_module(filename: str, module_name: str):
    router_path = Path(__file__).resolve().parents[2] / "mira" / "api" / "routers" / filename
    spec = spec_from_file_location(module_name, router_path)
    module = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guidance_version_and_authority_registry_endpoints() -> None:
    module = _load_router_module("guidance.py", "guidance_router_test_module")
    app = FastAPI()
    app.include_router(module.router, prefix="/api/guidance")
    client = TestClient(app)

    version_response = client.get("/api/guidance/packs/mira-oca-guidance/version")
    assert version_response.status_code == 200
    version_payload = version_response.json()
    assert version_payload["pack_id"] == "mira-oca-guidance"
    assert version_payload["version"] == "2.0.0"
    assert version_payload["pack"]["guidance_pack_id"] == "mira-oca-guidance"

    authority_response = client.get("/api/guidance/packs/mira-oca-guidance/authority-registry")
    assert authority_response.status_code == 200
    authority_payload = authority_response.json()
    assert "auth-bs-spec-oca-001-rev1" in authority_payload


def test_guidance_router_hides_disabled_mua_pack(monkeypatch) -> None:
    monkeypatch.setenv("MIRA_DISABLED_RUNTIME_KEYS", "guidance:mua")
    module = _load_router_module("guidance.py", "guidance_router_disabled_pack_test_module")
    app = FastAPI()
    app.include_router(module.router, prefix="/api/guidance")
    client = TestClient(app)

    hidden_response = client.get("/api/guidance/packs/mira-mua-guidance/version")
    assert hidden_response.status_code == 404

    visible_response = client.get("/api/guidance/packs/mira-oca-guidance/version")
    assert visible_response.status_code == 200


def test_app_factory_mounts_oca_without_double_prefix() -> None:
    app = FastAPI()
    _register_alias_routers(app)
    client = TestClient(app)

    response = client.get("/api/oca/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "domain": "oca"}

    double_prefixed = client.get("/api/oca/oca/ping")
    assert double_prefixed.status_code == 404


def test_app_factory_skips_disabled_inactive_routes(monkeypatch) -> None:
    monkeypatch.setenv(
        "MIRA_DISABLED_RUNTIME_KEYS",
        "mua,mua-v6,mua-v7,mua-v10,mua-matchmaker,test-classes",
    )
    app = FastAPI()
    _register_alias_routers(app)
    _register_direct_routers(app, None)
    client = TestClient(app)

    assert client.get("/api/mua/ping").status_code == 404
    assert client.get("/api/mua/matchmaker/ping").status_code == 404
    assert client.get("/api/mua/v10/ping").status_code == 404
    assert client.get("/api/test-classes/counts").status_code == 404
    assert client.get("/api/oca/ping").status_code == 200
