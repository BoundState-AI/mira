import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mira.api.routers import mua_v7 as mua_v7_module
from mira.core.session_store import MemorySessionStore
from mira.mua.v7.models import MaterialResolution, ResolutionStatus


class SuspendingMemorySessionStore(MemorySessionStore):
    async def get_module_data(self, module: str, key: str):
        await asyncio.sleep(0)
        return await super().get_module_data(module, key)

    async def save_module_data(self, module: str, key: str, data: dict):
        await asyncio.sleep(0)
        await super().save_module_data(module, key, data)

    async def delete_module_data(self, module: str, key: str) -> bool:
        await asyncio.sleep(0)
        return await super().delete_module_data(module, key)

    async def list_module_keys(self, module: str) -> list[str]:
        await asyncio.sleep(0)
        return await super().list_module_keys(module)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(mua_v7_module.router, prefix="/api/mua/v7")

    monkeypatch.setattr(
        mua_v7_module.session_manager,
        "_store",
        SuspendingMemorySessionStore(),
    )
    mua_v7_module._investigation_progress.clear()

    def _resolve_material(material: str, **_: object) -> MaterialResolution:
        return MaterialResolution(
            input_text=material,
            status=ResolutionStatus.RESOLVED,
            material_code="MAT-A96061",
            resolved_name="6061-T6 Aluminum",
        )

    async def _noop_investigation_background(**_: object) -> None:
        return None

    monkeypatch.setattr(mua_v7_module, "resolve_material", _resolve_material)
    monkeypatch.setattr(
        mua_v7_module,
        "_run_investigation_background",
        _noop_investigation_background,
    )

    return TestClient(app)


def test_mua_v7_investigate_persists_session_with_suspending_store(client: TestClient) -> None:
    payload = {
        "material": "6061-T6",
        "environment": {
            "o2_percent": 21.0,
            "pressure_psia": 14.7,
            "temp_min_f": 70.0,
            "temp_max_f": 200.0,
            "medium": "Air",
            "location": "habitable",
            "application": "structural component",
        },
        "center": "MSFC",
    }

    kickoff = client.post("/api/mua/v7/investigate", json=payload)
    assert kickoff.status_code == 200

    session_id = kickoff.json()["session_id"]

    detail = client.get(f"/api/mua/v7/session/{session_id}")
    assert detail.status_code == 200
    detail_body = detail.json()

    assert detail_body["session_id"] == session_id
    assert detail_body["material_input"] == "6061-T6"
    assert detail_body["current_step"] == "define"
    assert detail_body["status"] == "active"
    assert detail_body["center"] == "MSFC"

    listing = client.get("/api/mua/v7/sessions")
    assert listing.status_code == 200
    listing_body = listing.json()

    assert listing_body["total"] == 1
    assert listing_body["sessions"][0]["session_id"] == session_id
