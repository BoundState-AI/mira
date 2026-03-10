import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


MODULE_PATH = Path(__file__).resolve().parents[2] / "mira" / "api" / "routers" / "galvanic.py"
SPEC = importlib.util.spec_from_file_location("galvanic_router_module", MODULE_PATH)
assert SPEC and SPEC.loader
galvanic_router_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(galvanic_router_module)
galvanic_router = galvanic_router_module.router


app = FastAPI()
app.include_router(galvanic_router, prefix="/mira")
client = TestClient(app)


def test_galvanic_endpoints_are_mounted():
    response = client.get("/mira/galvanic/ping")
    assert response.status_code == 200
    assert response.json()["domain"] == "galvanic"


def test_galvanic_evaluate_endpoint_returns_result():
    response = client.post(
        "/mira/galvanic/evaluate",
        json={
            "material_a": "Al 6061-T6",
            "material_b": "316SS",
            "environment": "seawater_proxy",
            "application_type": "FLIGHT_HARDWARE",
            "couple_context": {
                "electrical_contact": "YES",
                "joint_type": "GENERAL"
            }
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["severity"] == "INCOMPATIBLE"
    assert payload["material_a"]["canonical_name"].startswith("Aluminum 6061")


def test_galvanic_material_search():
    response = client.get("/mira/galvanic/materials/search", params={"q": "6061"})
    assert response.status_code == 200
    payload = response.json()
    assert any(item["canonical_name"].startswith("Aluminum 6061") for item in payload)


def test_galvanic_unknown_material_returns_404():
    response = client.post(
        "/mira/galvanic/evaluate",
        json={
            "material_a": "does-not-exist",
            "material_b": "316SS",
            "environment": "seawater_proxy",
        },
    )
    assert response.status_code == 404
    assert "Material not found" in response.json()["detail"]


def test_galvanic_evaluate_rejects_malformed_requests():
    response = client.post(
        "/mira/galvanic/evaluate",
        json={
            "material_b": "316SS",
            "environment": "seawater_proxy",
        },
    )
    assert response.status_code == 422


def test_galvanic_evaluate_rejects_invalid_area_ratio():
    response = client.post(
        "/mira/galvanic/evaluate",
        json={
            "material_a": "Al 6061-T6",
            "material_b": "316SS",
            "environment": "seawater_proxy",
            "couple_context": {
                "cathode_to_anode_area_ratio": -1,
            },
        },
    )
    assert response.status_code == 422
