import pytest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mira.core.session_store import reset_session_store


@pytest.fixture(autouse=True)
def _reset_session_store_fixture():
    reset_session_store()
    yield
    reset_session_store()


@pytest.fixture
def client():
    router_path = Path(__file__).resolve().parents[2] / "mira" / "api" / "routers" / "oca.py"
    spec = spec_from_file_location("oca_router_test_module", router_path)
    module = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    router = module.router

    app = FastAPI()
    app.include_router(router, prefix="/api/oca")
    return TestClient(app)


def _request_payload(material_name: str = "316L") -> dict:
    return {
        "service_context": {
            "oxidizer_type": "gox",
            "o2_fraction": 1.0,
            "total_pressure_min_psia": 14.7,
            "total_pressure_max_psia": 500.0,
            "phase": "gas",
            "temp_min_c": 20.0,
            "temp_max_c": 25.0,
            "velocity_m_s": 15.0,
            "cleanliness_verified": True,
        },
        "materials": [
            {
                "material_name": material_name,
                "product_form": "bar",
            }
        ],
        "components": [
            {
                "component_id": "cmp-1",
                "component_class": "valve",
                "geometry_class": "bulk",
                "design_function": "pressure control",
                "seal_type": "polymer",
            }
        ],
    }


def test_oca_case_lifecycle(client: TestClient) -> None:
    create_response = client.post("/api/oca/cases", json=_request_payload())
    assert create_response.status_code == 200
    create_data = create_response.json()
    assert create_data["case_id"].startswith("oca-")

    case_id = create_data["case_id"]

    precheck_response = client.post(f"/api/oca/cases/{case_id}/precheck")
    assert precheck_response.status_code == 200
    assert "triggered_requirements" in precheck_response.json()

    evidence_response = client.post(f"/api/oca/cases/{case_id}/evidence")
    assert evidence_response.status_code == 200
    assert len(evidence_response.json()["evidence"]) >= 1

    mechanisms_response = client.post(f"/api/oca/cases/{case_id}/mechanisms")
    assert mechanisms_response.status_code == 200
    assert len(mechanisms_response.json()["mechanisms"]) == 18

    decision_response = client.post(f"/api/oca/cases/{case_id}/decision")
    assert decision_response.status_code == 200
    assert decision_response.json()["decision"]["final_disposition"] in {
        "requires_acceptance_test",
        "requires_mua",
        "compatible_with_controls",
        "compatible_as_configured",
        "requires_supplemental_testing",
        "insufficient_evidence",
        "prohibited",
    }

    requirements_response = client.get(f"/api/oca/cases/{case_id}/requirements")
    assert requirements_response.status_code == 200
    assert len(requirements_response.json()["requirements"]) == 4

    lineage_response = client.get(f"/api/oca/cases/{case_id}/lineage")
    assert lineage_response.status_code == 200
    assert len(lineage_response.json()["decision_lineage"]) >= 1

    export_response = client.post(f"/api/oca/cases/{case_id}/export")
    assert export_response.status_code == 200
    assert len(export_response.json()["artifacts"]) == 4


def test_oca_authority_manifest(client: TestClient) -> None:
    response = client.get("/api/oca/authority")
    assert response.status_code == 200
    data = response.json()
    assert data["spec_id"] == "BS-SPEC-OCA-001-REV1"
    assert len(data["sources"]) >= 4


def test_oca_ping_and_missing_case_errors(client: TestClient) -> None:
    ping = client.get("/api/oca/ping")
    assert ping.status_code == 200
    assert ping.json() == {"status": "ok", "domain": "oca"}

    for method, path in [
        ("post", "/api/oca/cases/missing/precheck"),
        ("post", "/api/oca/cases/missing/evidence"),
        ("post", "/api/oca/cases/missing/mechanisms"),
        ("post", "/api/oca/cases/missing/decision"),
        ("post", "/api/oca/cases/missing/export"),
        ("get", "/api/oca/cases/missing/requirements"),
        ("get", "/api/oca/cases/missing/lineage"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 404
        assert response.json()["detail"] == "OCA case not found"
