from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mira.api.routers.o2 import router as o2_router
from mira.o2.engine import get_o2_engine


def test_o2_bok_assets_load_and_search_returns_results() -> None:
    engine = get_o2_engine(force_new=True)
    assert engine.o2_bok_index is not None
    assert engine.o2_bok_metadata
    assert engine.o2_bok_text_lookup

    app = FastAPI()
    app.include_router(o2_router, prefix="/api/o2")
    client = TestClient(app)

    response = client.post(
        "/api/o2/search",
        json={"query": "oxygen compatibility stainless steel", "k": 3, "use_hybrid": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_results"] >= 1
    first = payload["results"][0]
    assert first["source"]
    assert first["text"]
