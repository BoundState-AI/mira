#!/usr/bin/env python3
"""
BoundState MIRA Backend - Stub API
Minimal endpoints to support frontend deployment.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any

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


class SearchResult(BaseModel):
    materialkey: str
    material_name: str
    score: float
    snippet: str


@app.post("/api/search")
async def search(request: SearchRequest):
    """Semantic search - returns empty results for now."""
    return {
        "query": request.query,
        "results": [],
        "total": 0,
        "message": "Search not yet implemented - backend stub"
    }


# ---------------------------------------------------------------------------
# Knowledge Twins (O2/H2) endpoints (stub)
# ---------------------------------------------------------------------------

@app.post("/api/v1/o2/search-bok")
async def o2_search_bok(request: SearchRequest):
    """O2 Body of Knowledge search - stub."""
    return {"results": [], "total": 0}


@app.post("/api/v1/h2/search-bok")
async def h2_search_bok(request: SearchRequest):
    """H2 Body of Knowledge search - stub."""
    return {"results": [], "total": 0}


# ---------------------------------------------------------------------------
# Test Classes endpoints (stub)
# ---------------------------------------------------------------------------

@app.get("/api/test-classes/counts")
async def test_classes_counts():
    """Test class counts - stub."""
    return {
        "test_classes": [],
        "total": 0
    }


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
# Run with uvicorn
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
