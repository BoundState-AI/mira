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


def test_fracture_material_search_endpoint_resolves_real_aliases():
    response = client.get("/mira/fracture/materials/search", params={"q": "Ti64"})

    assert response.status_code == 200
    payload = response.json()
    assert any(item["canonical_name"] == "Ti-6Al-4V" for item in payload)


def test_fracture_fcrs_endpoint_returns_26_entries():
    response = client.get("/mira/fracture/fcrs")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["fcrs"]) == 26


def test_fracture_materials_screen_endpoint_standalone():
    response = client.post(
        "/mira/fracture/materials/screen",
        json={
            "material_name": "Ti-6Al-4V",
            "material_system": "METALLIC",
            "classification": "FC",
            "specific_hardware_type": "GENERAL",
            "material_context": {
                "nasa_std_6016_qualified": False,
                "mua_present": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    finding_ids = {item["finding_id"]: item for item in payload["findings"]}
    assert finding_ids["mua_required"]["status"] == "FAIL"


def test_fracture_materials_screen_flags_am_low_risk_disqualification():
    response = client.post(
        "/mira/fracture/materials/screen",
        json={
            "material_name": "Ti64",
            "material_system": "METALLIC",
            "classification": "NFC_METALLIC",
            "specific_hardware_type": "GENERAL",
            "material_context": {
                "low_risk_candidate": True,
                "additive_manufactured": True,
                "kic_fty_ratio": 0.5,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    finding_ids = {item["finding_id"]: item for item in payload["findings"]}
    assert finding_ids["am_low_risk_disallowed"]["status"] == "FAIL"


def test_fracture_api_missing_required_fields_returns_422():
    response = client.post("/mira/fracture/classify", json={"mission_class": "HUMAN_RATED"})
    assert response.status_code == 422


def test_fracture_api_rejects_zero_kic_ratio_with_422():
    response = client.post(
        "/mira/fracture/classify",
        json={
            "part_name": "Low-risk clip",
            "mission_class": "HUMAN_RATED",
            "hazard_consequence": "CRITICAL",
            "load_path_type": "REDUNDANT",
            "structural_role": "PRIMARY",
            "material_system": "METALLIC",
            "material_name": "Al 6061-T6",
            "material_context": {
                "low_risk_candidate": True,
                "kic_fty_ratio": 0.0,
            },
        },
    )

    assert response.status_code == 422
