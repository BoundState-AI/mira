from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mira.core.session_store import MemorySessionStore, reset_session_store


@pytest.fixture
def system_module():
    reset_session_store()
    router_path = Path(__file__).resolve().parents[2] / "mira" / "api" / "routers" / "oca_systems.py"
    spec = spec_from_file_location("oca_systems_router_test_module", router_path)
    module = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    yield module
    reset_session_store()


@pytest.fixture
def client(system_module) -> TestClient:
    app = FastAPI()
    app.include_router(system_module.router, prefix="/api/oca/systems")
    return TestClient(app)


def _create_system(client: TestClient) -> str:
    response = client.post(
        "/api/oca/systems",
        json={
            "name": "Ground Test System",
            "inputs": {
                "o2_fraction": 1.0,
                "system_pressure_min_psia": 14.7,
                "system_pressure_max_psia": 600.0,
                "phase": "gox",
                "oxygen_phase": "gas",
                "mission_phase": "ground_test",
                "bi_directional_flow_risk": False,
            },
        },
    )
    assert response.status_code == 200
    return response.json()["system_id"]


def _add_component(client: TestClient, system_id: str, archetype: str, label: str) -> str:
    response = client.post(
        f"/api/oca/systems/{system_id}/components",
        json={
            "archetype": archetype,
            "label": label,
            "position_x": 100,
            "position_y": 120,
            "materials": [{"slot_name": "body", "material": {"material_name": "316L"}}],
            "config": {"inner_diameter_mm": 12.0, "length_m": 1.5} if archetype == "line" else {},
        },
    )
    assert response.status_code == 200
    return response.json()["component_id"]


def test_system_builder_endpoints_cover_crud_assessment_and_exports(client: TestClient) -> None:
    ping = client.get("/api/oca/systems/ping")
    assert ping.status_code == 200
    assert ping.json()["domain"] == "oca-systems"

    system_id = _create_system(client)

    get_response = client.get(f"/api/oca/systems/{system_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Ground Test System"

    update_inputs = client.put(
        f"/api/oca/systems/{system_id}/inputs",
        json={"design_flow_rate_m3_s": 0.02, "cleanliness_spec": "Level 100"},
    )
    assert update_inputs.status_code == 200

    filter_id = _add_component(client, system_id, "filter", "Primary Filter")
    valve_id = _add_component(client, system_id, "valve", "Isolation Valve")
    line_id = _add_component(client, system_id, "line", "Transfer Line")

    update_component = client.put(
        f"/api/oca/systems/{system_id}/components/{valve_id}",
        json={
            "label": "Main Isolation Valve",
            "materials": [
                {"slot_name": "body", "material": {"material_name": "316L"}},
                {"slot_name": "seat", "material": {"material_name": "PTFE"}},
            ],
            "config": {"seal_type": "PTFE"},
            "is_all_metal_seal": False,
        },
    )
    assert update_component.status_code == 200

    first_connection = client.post(
        f"/api/oca/systems/{system_id}/connections",
        json={"source_component_id": filter_id, "target_component_id": valve_id},
    )
    assert first_connection.status_code == 200
    connection_id = first_connection.json()["connection_id"]
    assert valve_id in first_connection.json()["affected_component_ids"]

    second_connection = client.post(
        f"/api/oca/systems/{system_id}/connections",
        json={"source_component_id": valve_id, "target_component_id": line_id},
    )
    assert second_connection.status_code == 200

    topology = client.get(f"/api/oca/systems/{system_id}/topology")
    assert topology.status_code == 200
    assert valve_id in topology.json()["zones"]

    assessment = client.post(f"/api/oca/systems/{system_id}/assess")
    assert assessment.status_code == 200
    assessment_payload = assessment.json()
    assert assessment_payload["system_id"] == system_id
    assert len(assessment_payload["components"]) == 3

    kindling = client.get(f"/api/oca/systems/{system_id}/kindling-chain")
    assert kindling.status_code == 200
    assert kindling.json()["system_id"] == system_id

    path = client.get(f"/api/oca/systems/{system_id}/path/{valve_id}")
    assert path.status_code == 200
    assert path.json()["component_id"] == valve_id

    export = client.post(f"/api/oca/systems/{system_id}/export")
    assert export.status_code == 200
    assert export.json()["system_name"] == "Ground Test System"

    library = client.get(f"/api/oca/systems/{system_id}/library")
    assert library.status_code == 200
    assert len(library.json()["archetypes"]) >= 4

    remove_connection = client.delete(f"/api/oca/systems/{system_id}/connections/{connection_id}")
    assert remove_connection.status_code == 200

    remove_component = client.delete(f"/api/oca/systems/{system_id}/components/{line_id}")
    assert remove_component.status_code == 200

    lock = client.post(f"/api/oca/systems/{system_id}/lock")
    assert lock.status_code == 200
    assert lock.json()["locked"] is True

    locked_update = client.put(f"/api/oca/systems/{system_id}/inputs", json={"system_pressure_max_psia": 700})
    assert locked_update.status_code == 409

    locked_add_component = client.post(
        f"/api/oca/systems/{system_id}/components",
        json={"archetype": "valve", "label": "Locked Valve"},
    )
    assert locked_add_component.status_code == 409

    locked_update_component = client.put(
        f"/api/oca/systems/{system_id}/components/{valve_id}",
        json={"label": "Locked Update"},
    )
    assert locked_update_component.status_code == 409

    locked_remove_component = client.delete(f"/api/oca/systems/{system_id}/components/{filter_id}")
    assert locked_remove_component.status_code == 409

    locked_add_connection = client.post(
        f"/api/oca/systems/{system_id}/connections",
        json={"source_component_id": filter_id, "target_component_id": valve_id},
    )
    assert locked_add_connection.status_code == 409

    locked_remove_connection = client.delete(f"/api/oca/systems/{system_id}/connections/{connection_id}")
    assert locked_remove_connection.status_code == 409


def test_system_builder_endpoints_surface_not_found_conditions(client: TestClient) -> None:
    missing_system = client.get("/api/oca/systems/missing-system")
    assert missing_system.status_code == 404

    system_id = _create_system(client)
    valve_id = _add_component(client, system_id, "valve", "Valve")

    missing_component = client.put(
        f"/api/oca/systems/{system_id}/components/missing-component",
        json={"label": "Ghost"},
    )
    assert missing_component.status_code == 404

    missing_source = client.post(
        f"/api/oca/systems/{system_id}/connections",
        json={"source_component_id": "missing", "target_component_id": valve_id},
    )
    assert missing_source.status_code == 404

    missing_target = client.post(
        f"/api/oca/systems/{system_id}/connections",
        json={"source_component_id": valve_id, "target_component_id": "missing"},
    )
    assert missing_target.status_code == 404

    empty_path = client.get(f"/api/oca/systems/{system_id}/path/missing-component")
    assert empty_path.status_code == 200
    assert empty_path.json() == {
        "component_id": "missing-component",
        "upstream_contributors": [],
        "local_mechanism_triggers": [],
        "downstream_propagation_risk": [],
        "controls_that_would_change": [],
    }


def test_system_builder_lazy_assessment_paths(client: TestClient) -> None:
    system_id = _create_system(client)
    valve_id = _add_component(client, system_id, "valve", "Valve")
    line_id = _add_component(client, system_id, "line", "Line")
    connect = client.post(
        f"/api/oca/systems/{system_id}/connections",
        json={"source_component_id": valve_id, "target_component_id": line_id},
    )
    assert connect.status_code == 200

    kindling = client.get(f"/api/oca/systems/{system_id}/kindling-chain")
    assert kindling.status_code == 200
    assert kindling.json()["system_id"] == system_id

    export = client.post(f"/api/oca/systems/{system_id}/export")
    assert export.status_code == 200
    assert export.json()["system_id"] == system_id


def test_system_builder_vision_mockup_preview_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    system_id = _create_system(client)

    class FakeVisionService:
        def build_mockup(self, **kwargs):
            assert kwargs["system_id"] == system_id
            assert kwargs["media_type"] == "image/png"
            return {
                "system_id": system_id,
                "model_used": "claude-sonnet-4-5-20250929",
                "suggested_inputs_patch": {"hardware_name": "Imported Test System"},
                "components": [
                    {
                        "temp_id": "cmp_vision_1",
                        "archetype": "filter",
                        "label": "Imported Filter",
                        "position_x": 120.0,
                        "position_y": 120.0,
                        "materials": [{"slot_name": "housing_material", "material": {"material_name": "316L"}}],
                        "config": {"micron_rating": 10},
                        "is_provisional": True,
                        "human_confirmed": False,
                        "inferred_facts": [],
                        "confidence": "medium",
                    }
                ],
                "connections": [],
                "questions": [
                    {
                        "question_id": "vision-q-1",
                        "severity": "blocking",
                        "prompt": "Confirm wetted materials for Imported Filter.",
                        "target_temp_id": "cmp_vision_1",
                        "field_path": "materials",
                    }
                ],
                "warnings": ["Preview only"],
            }

    import mira.oca.system_vision as system_vision

    monkeypatch.setattr(system_vision, "OCASystemVisionService", FakeVisionService)

    response = client.post(
        f"/api/oca/systems/{system_id}/vision/mockup",
        files={"image": ("system.png", b"fake-image-bytes", "image/png")},
        data={"flow_direction_hint": "left_to_right", "notes": "import this"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["system_id"] == system_id
    assert payload["components"][0]["label"] == "Imported Filter"
    assert payload["questions"][0]["severity"] == "blocking"
    assert payload["warnings"] == ["Preview only"]


# ---------------------------------------------------------------------------
# Phase 2a: Cross-request persistence tests
# ---------------------------------------------------------------------------


def test_oca_system_persists_across_separate_requests(client: TestClient) -> None:
    """Verify state survives multiple requests via the shared store, not local dict."""
    system_id = _create_system(client)

    # Add a component in one request
    valve_id = _add_component(client, system_id, "valve", "Persistence Test Valve")

    # Fetch the system in a separate request and verify component is there
    get_resp = client.get(f"/api/oca/systems/{system_id}")
    assert get_resp.status_code == 200
    components = get_resp.json()["components"]
    assert len(components) == 1
    assert components[0]["component_id"] == valve_id
    assert components[0]["label"] == "Persistence Test Valve"


def test_oca_system_mutation_persists_after_update(client: TestClient) -> None:
    """Verify that update_inputs persists through a subsequent fetch."""
    system_id = _create_system(client)

    # Mutate inputs
    client.put(
        f"/api/oca/systems/{system_id}/inputs",
        json={"design_flow_rate_m3_s": 0.05},
    )

    # Fetch again — should see the updated inputs
    get_resp = client.get(f"/api/oca/systems/{system_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["inputs"]["design_flow_rate_m3_s"] == 0.05


def test_oca_system_lock_persists_across_requests(client: TestClient) -> None:
    """Lock state survives a round-trip through the store."""
    system_id = _create_system(client)

    lock_resp = client.post(f"/api/oca/systems/{system_id}/lock")
    assert lock_resp.status_code == 200

    # Verify locked state persisted — attempt mutation should 409
    add_resp = client.post(
        f"/api/oca/systems/{system_id}/components",
        json={"archetype": "valve", "label": "Should Fail"},
    )
    assert add_resp.status_code == 409


def test_oca_system_audit_log_grows_across_requests(client: TestClient) -> None:
    """Audit log entries accumulate across multiple requests."""
    system_id = _create_system(client)

    _add_component(client, system_id, "valve", "V1")
    _add_component(client, system_id, "filter", "F1")

    get_resp = client.get(f"/api/oca/systems/{system_id}")
    assert get_resp.status_code == 200
    audit_log = get_resp.json()["audit_log"]
    add_actions = [e for e in audit_log if e["action"] == "add_component"]
    assert len(add_actions) == 2
