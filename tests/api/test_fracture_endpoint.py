import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


MODULE_PATH = Path(__file__).resolve().parents[2] / "mira" / "api" / "routers" / "fracture.py"
SPEC = importlib.util.spec_from_file_location("fracture_router_module", MODULE_PATH)
assert SPEC and SPEC.loader
fracture_router_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fracture_router_module)
fracture_router = fracture_router_module.router


app = FastAPI()
app.include_router(fracture_router, prefix="/mira")
client = TestClient(app)


def test_fracture_endpoints_are_mounted():
    response = client.get("/mira/fracture/ping")

    assert response.status_code == 200
    assert response.json()["domain"] == "fracture"


def test_fracture_classify_endpoint_returns_fc_path():
    response = client.post(
        "/mira/fracture/classify",
        json={
            "part_name": "Main bracket",
            "mission_class": "HUMAN_RATED",
            "hazard_consequence": "CATASTROPHIC",
            "load_path_type": "SINGLE",
            "structural_role": "PRIMARY",
            "material_system": "METALLIC",
            "specific_hardware_type": "GENERAL",
            "material_name": "Ti-6Al-4V",
            "material_context": {
                "approved_source_data_attached": True,
                "nasa_std_6016_qualified": True,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["classification"] == "FC"
    assert payload["baseline_key"] == "FC_METALLIC_GENERAL"
    assert payload["applicable_fcrs"] == [10, 12, 15, 16, 21, 22, 23, 24, 25]


def test_fracture_material_search_endpoint_returns_known_material():
    response = client.get("/mira/fracture/materials/search", params={"q": "6061"})

    assert response.status_code == 200
    payload = response.json()
    assert any(item["canonical_name"] == "Aluminum 6061-T6" for item in payload)
