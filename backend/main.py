#!/usr/bin/env python3
"""
BoundState MIRA Backend - Stub API
Minimal endpoints to support frontend deployment.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import uuid

app = FastAPI(title="BoundState MIRA API", version="0.1.0")

# CORS - allow all origins for now
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {"status": "ok", "service": "mira-backend", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Search endpoints (stub)
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    filters: Optional[dict] = None


@app.post("/api/search")
async def search(request: SearchRequest):
    """Semantic search - returns empty results for now."""
    return {
        "query": request.query,
        "results": [],
        "total": 0,
        "message": "Search not yet connected"
    }


# ---------------------------------------------------------------------------
# Knowledge Twins (O2/H2) endpoints (stub)
# ---------------------------------------------------------------------------

@app.get("/api/o2/families")
async def o2_families():
    """O2 material families - stub."""
    return {"families": [], "total": 0}


@app.get("/api/h2/families")
async def h2_families():
    """H2 material families - stub."""
    return {"families": [], "total": 0}


@app.post("/api/v1/o2/search-bok")
async def o2_search_bok(request: SearchRequest):
    """O2 Body of Knowledge search - stub."""
    return {"results": [], "total": 0}


@app.post("/api/v1/h2/search-bok")
async def h2_search_bok(request: SearchRequest):
    """H2 Body of Knowledge search - stub."""
    return {"results": [], "total": 0}


@app.get("/o2/families")
async def o2_families_alt():
    """O2 material families - alternate path."""
    return {"families": [], "total": 0}


# ---------------------------------------------------------------------------
# M&P Plan endpoints (stub)
# ---------------------------------------------------------------------------

@app.get("/api/mp-plan/vehicle-presets")
async def mp_plan_presets():
    """M&P Plan vehicle presets - stub."""
    return {"presets": [], "total": 0}


@app.post("/api/mp-plan/sessions")
async def mp_plan_create_session():
    """Create M&P Plan session - stub."""
    return {
        "session_id": str(uuid.uuid4()),
        "status": "created",
        "message": "Session created (stub mode)"
    }


@app.get("/api/mp-plan/sessions")
async def mp_plan_list_sessions():
    """List M&P Plan sessions - stub."""
    return {"sessions": [], "total": 0}


@app.get("/api/mp-plan/sessions/{session_id}")
async def mp_plan_get_session(session_id: str):
    """Get M&P Plan session - stub."""
    return {
        "session_id": session_id,
        "status": "not_found",
        "message": "Session not found (stub mode)"
    }


# ---------------------------------------------------------------------------
# Test Classes endpoints (stub)
# ---------------------------------------------------------------------------

@app.get("/api/test-classes/counts")
async def test_classes_counts():
    """Test class counts - stub."""
    return {"test_classes": [], "total": 0}


@app.get("/api/test-records/{test_type}/ratings")
async def test_record_ratings(test_type: str):
    """Test record ratings - stub."""
    return {"ratings": [], "test_type": test_type}


@app.get("/api/test-records/{test_type}")
async def test_records(test_type: str):
    """Test records - stub."""
    return {"records": [], "test_type": test_type, "total": 0}


@app.get("/api/test-records/{test_type}/export")
async def test_records_export(test_type: str):
    """Test records export - stub."""
    return {"data": [], "test_type": test_type}


# ---------------------------------------------------------------------------
# Material endpoints (stub)
# ---------------------------------------------------------------------------

@app.get("/api/material/{material_key}/summary")
async def material_summary(material_key: str):
    """Material summary - stub."""
    return {
        "materialkey": material_key,
        "name": "Unknown Material",
        "description": "Material data not yet loaded",
        "properties": {}
    }


# ---------------------------------------------------------------------------
# MIUL endpoints (stub)
# ---------------------------------------------------------------------------

@app.post("/api/miul/upload")
async def miul_upload():
    """MIUL upload - stub."""
    return {"status": "stub", "message": "MIUL upload not yet implemented"}


@app.get("/api/miul/status/{job_id}")
async def miul_status(job_id: str):
    """MIUL job status - stub."""
    return {"job_id": job_id, "status": "not_found"}


@app.post("/miul/parse")
async def miul_parse():
    """MIUL parse - stub."""
    return {"status": "stub", "message": "MIUL parse not yet implemented"}


# ---------------------------------------------------------------------------
# MUA endpoints (stub)
# ---------------------------------------------------------------------------

@app.post("/api/mua/generate")
async def mua_generate():
    """MUA generate - stub."""
    return {"status": "stub", "message": "MUA generation not yet implemented"}


@app.get("/api/mua/v6/templates")
async def mua_templates():
    """MUA templates - stub."""
    return {"templates": [], "total": 0}


@app.get("/mua/v6/templates")
async def mua_templates_alt():
    """MUA templates - alternate path."""
    return {"templates": [], "total": 0}


# ---------------------------------------------------------------------------
# Compliance endpoints (stub)
# ---------------------------------------------------------------------------

@app.get("/api/compliance/standards")
async def compliance_standards():
    """Compliance standards - stub."""
    return {"standards": [], "total": 0}


@app.post("/api/compliance/analyze")
async def compliance_analyze():
    """Compliance analysis - stub."""
    return {"status": "stub", "message": "Compliance analysis not yet implemented"}


# ---------------------------------------------------------------------------
# BOM endpoints (stub)
# ---------------------------------------------------------------------------

@app.post("/bom/parse")
async def bom_parse():
    """BOM parse - stub."""
    return {"status": "stub", "components": [], "message": "BOM parsing not yet implemented"}


# ---------------------------------------------------------------------------
# Catch-all for missing endpoints - returns 200 with stub message
# ---------------------------------------------------------------------------

@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all_api(path: str):
    """Catch-all for unimplemented /api endpoints."""
    return {
        "status": "stub",
        "path": f"/api/{path}",
        "message": "Endpoint not yet implemented",
        "data": []
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(path: str):
    """Catch-all for unimplemented endpoints."""
    return {
        "status": "stub",
        "path": f"/{path}",
        "message": "Endpoint not yet implemented",
        "data": []
    }


# ---------------------------------------------------------------------------
# Run with uvicorn
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
