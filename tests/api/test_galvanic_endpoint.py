from fastapi.testclient import TestClient

from mira.api.app import app


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
