#!/usr/bin/env python3
"""
BoundState MIRA Backend - Stub API
Minimal endpoints to support frontend deployment.
"""

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import uuid

# Configure logging for Railway visibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="BoundState MIRA API", version="0.1.0")

# Log startup info
@app.on_event("startup")
async def startup_event():
    port = os.environ.get("PORT", "not set")
    logger.info(f"=== MIRA Backend Starting ===")
    logger.info(f"PORT environment variable: {port}")
    logger.info(f"ANTHROPIC_API_KEY set: {'yes' if os.environ.get('ANTHROPIC_API_KEY') else 'NO'}")
    logger.info(f"Python path: {os.getcwd()}")
    logger.info(f"=== Startup complete ===")

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
    logger.info("Root endpoint called")
    return {"status": "ok", "service": "mira-backend", "version": "0.1.0"}


@app.get("/health")
async def health():
    logger.info("Health check called")
    return {"status": "healthy"}


@app.get("/api/health")
async def api_health():
    """Health check under /api path for Vercel proxy."""
    logger.info("API health check called")
    return {"status": "healthy", "service": "mira-backend"}


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
# MIUL endpoints (LIVE - using v3 vision extraction)
# ---------------------------------------------------------------------------

import base64
import tempfile
import logging
from pathlib import Path
from fastapi import UploadFile, File, HTTPException, BackgroundTasks

# MIUL imports
try:
    from miul import (
        VisionClient,
        extract_drawing_page,
        extract_drawing_tree,
        pdf_to_images,
        postprocess_extraction,
    )
    MIUL_AVAILABLE = True
except ImportError as e:
    MIUL_AVAILABLE = False
    logging.warning(f"MIUL module not available: {e}")

# In-memory job storage (replace with Redis/DB in production)
miul_jobs: Dict[str, Dict[str, Any]] = {}
dt_sessions: Dict[str, Dict[str, Any]] = {}  # DT Editor sessions


class MIULExtractRequest(BaseModel):
    """Request to extract a drawing from base64 PDF."""
    pdf_base64: str
    page_index: int = 0
    filename: Optional[str] = None


@app.post("/api/miul/upload")
async def miul_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    Upload a PDF and start extraction.
    Returns a job_id to poll for status.
    """
    if not MIUL_AVAILABLE:
        raise HTTPException(status_code=503, detail="MIUL module not available - check dependencies")

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    job_id = str(uuid.uuid4())

    # Read file content
    content = await file.read()

    # Store job
    miul_jobs[job_id] = {
        "status": "processing",
        "filename": file.filename,
        "pages": [],
        "result": None,
        "error": None
    }

    # Process in background
    background_tasks.add_task(process_miul_pdf, job_id, content, file.filename)

    return {
        "job_id": job_id,
        "status": "processing",
        "message": f"Processing {file.filename}"
    }


async def process_miul_pdf(job_id: str, pdf_content: bytes, filename: str):
    """Background task to process PDF extraction."""
    try:
        client = VisionClient()

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_content)
            tmp_path = Path(tmp.name)

        try:
            # Get page count
            images = pdf_to_images(tmp_path)
            num_pages = len(images)

            miul_jobs[job_id]["pages"] = [{"index": i, "status": "pending"} for i in range(num_pages)]

            # Extract first page (or all pages for multi-page)
            results = []
            for page_idx in range(num_pages):
                miul_jobs[job_id]["pages"][page_idx]["status"] = "processing"

                result = extract_drawing_page(tmp_path, page_idx, client)
                if result:
                    result = postprocess_extraction(result)
                    results.append(result)
                    miul_jobs[job_id]["pages"][page_idx]["status"] = "complete"
                else:
                    miul_jobs[job_id]["pages"][page_idx]["status"] = "failed"

            # Merge results
            if results:
                merged = results[0]
                for r in results[1:]:
                    # Merge EPL parts
                    merged.get("parts_list", []).extend(r.get("parts_list", []))
                    # Merge notes
                    merged.get("notes", []).extend(r.get("notes", []))

                miul_jobs[job_id]["result"] = merged
                miul_jobs[job_id]["status"] = "complete"
            else:
                miul_jobs[job_id]["status"] = "failed"
                miul_jobs[job_id]["error"] = "No extraction results"

        finally:
            # Cleanup temp file
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logging.error(f"MIUL extraction error: {e}")
        miul_jobs[job_id]["status"] = "failed"
        miul_jobs[job_id]["error"] = str(e)


@app.get("/api/miul/status/{job_id}")
async def miul_status(job_id: str):
    """Get MIUL job status and results."""
    if job_id not in miul_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = miul_jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "filename": job.get("filename"),
        "pages": job.get("pages", []),
        "result": job.get("result"),
        "error": job.get("error")
    }


@app.post("/miul/parse")
async def miul_parse(file: UploadFile = File(...)):
    """
    Parse a single PDF and return extraction immediately.
    For smaller files - synchronous extraction.
    """
    if not MIUL_AVAILABLE:
        raise HTTPException(status_code=503, detail="MIUL module not available")

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    content = await file.read()

    try:
        client = VisionClient()

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            # Extract first page
            result = extract_drawing_page(tmp_path, 0, client)
            if result:
                result = postprocess_extraction(result)
                return {
                    "status": "success",
                    "filename": file.filename,
                    "extraction": result
                }
            else:
                return {
                    "status": "failed",
                    "filename": file.filename,
                    "error": "No extraction result"
                }
        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logging.error(f"MIUL parse error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/miul/extract-base64")
async def miul_extract_base64(request: MIULExtractRequest):
    """
    Extract drawing data from a base64-encoded PDF.
    Useful for frontend that already has the file in memory.
    """
    if not MIUL_AVAILABLE:
        raise HTTPException(status_code=503, detail="MIUL module not available")

    try:
        pdf_bytes = base64.b64decode(request.pdf_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 encoding")

    try:
        client = VisionClient()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = Path(tmp.name)

        try:
            result = extract_drawing_page(tmp_path, request.page_index, client)
            if result:
                result = postprocess_extraction(result)
                return {
                    "status": "success",
                    "page_index": request.page_index,
                    "extraction": result
                }
            else:
                return {
                    "status": "failed",
                    "error": "No extraction result"
                }
        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logging.error(f"MIUL base64 extract error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Drawing Tree (DT) Editor endpoints (LIVE)
# ---------------------------------------------------------------------------

class DTNodeUpdate(BaseModel):
    """Update to a single DT node."""
    drawing_number: str
    parent: Optional[str] = None
    title: Optional[str] = None
    type: Optional[str] = None  # "ASSEMBLY" or "DETAIL"


class DTTreeUpdate(BaseModel):
    """Bulk update to DT tree."""
    top_level: Optional[str] = None
    tree: List[Dict[str, Any]]


class DTExportRequest(BaseModel):
    """Request to export DT as NHA overrides."""
    project_name: Optional[str] = None
    include_metadata: bool = True


@app.post("/api/dt/upload")
@app.post("/api/miul/extract-dt")  # Alias for frontend compatibility
async def dt_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None),
    dt_file: UploadFile = File(None),  # Frontend sends as dt_file
):
    """
    Upload a Drawing Tree PDF and extract hierarchy.
    Returns session_id to retrieve/edit the extracted tree.
    """
    if not MIUL_AVAILABLE:
        raise HTTPException(status_code=503, detail="MIUL module not available")

    # Accept either 'file' or 'dt_file' field name
    upload = file or dt_file
    if not upload:
        raise HTTPException(status_code=400, detail="No file provided")

    if not upload.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    session_id = str(uuid.uuid4())
    content = await upload.read()

    # Store session
    dt_sessions[session_id] = {
        "status": "processing",
        "filename": upload.filename,
        "tree": None,
        "top_level": None,
        "error": None,
        "created_at": None,
        "modified": False
    }

    # Process in background
    background_tasks.add_task(process_dt_pdf, session_id, content, upload.filename)

    return {
        "session_id": session_id,
        "status": "processing",
        "message": f"Extracting Drawing Tree from {upload.filename}"
    }


async def process_dt_pdf(session_id: str, pdf_content: bytes, filename: str):
    """Background task to extract Drawing Tree hierarchy."""
    import datetime

    try:
        client = VisionClient()

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_content)
            tmp_path = Path(tmp.name)

        try:
            # Extract drawing tree
            result = extract_drawing_tree(tmp_path, client)

            if result and result.get("tree"):
                dt_sessions[session_id]["tree"] = result.get("tree", [])
                dt_sessions[session_id]["top_level"] = result.get("top_level", "")
                dt_sessions[session_id]["status"] = "complete"
                dt_sessions[session_id]["created_at"] = datetime.datetime.now().isoformat()
                logging.info(f"DT extraction complete: {len(result.get('tree', []))} entries")
            else:
                dt_sessions[session_id]["status"] = "failed"
                dt_sessions[session_id]["error"] = "No tree structure found in PDF"

        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logging.error(f"DT extraction error: {e}")
        dt_sessions[session_id]["status"] = "failed"
        dt_sessions[session_id]["error"] = str(e)


@app.get("/api/dt/session/{session_id}")
async def dt_get_session(session_id: str):
    """Get DT session with extracted/edited tree."""
    if session_id not in dt_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = dt_sessions[session_id]
    return {
        "session_id": session_id,
        "status": session["status"],
        "filename": session.get("filename"),
        "top_level": session.get("top_level"),
        "tree": session.get("tree"),
        "entry_count": len(session.get("tree") or []),
        "modified": session.get("modified", False),
        "created_at": session.get("created_at"),
        "error": session.get("error")
    }


@app.put("/api/dt/session/{session_id}")
async def dt_update_session(session_id: str, update: DTTreeUpdate):
    """
    Update the DT tree (user edits).
    Replaces entire tree with provided data.
    """
    if session_id not in dt_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = dt_sessions[session_id]

    if session["status"] != "complete":
        raise HTTPException(status_code=400, detail="Session not ready for editing")

    # Update tree
    session["tree"] = update.tree
    if update.top_level is not None:
        session["top_level"] = update.top_level
    session["modified"] = True

    return {
        "session_id": session_id,
        "status": "updated",
        "entry_count": len(update.tree),
        "top_level": session["top_level"]
    }


@app.patch("/api/dt/session/{session_id}/node")
async def dt_update_node(session_id: str, node: DTNodeUpdate):
    """
    Update a single node in the DT tree.
    More efficient for individual edits.
    """
    if session_id not in dt_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = dt_sessions[session_id]

    if session["status"] != "complete":
        raise HTTPException(status_code=400, detail="Session not ready for editing")

    tree = session.get("tree", [])

    # Find and update the node
    found = False
    for entry in tree:
        if entry.get("drawing_number") == node.drawing_number:
            if node.parent is not None:
                entry["parent"] = node.parent if node.parent else None
            if node.title is not None:
                entry["title"] = node.title
            if node.type is not None:
                entry["type"] = node.type
            found = True
            break

    if not found:
        # Add new node
        new_entry = {
            "drawing_number": node.drawing_number,
            "parent": node.parent,
            "title": node.title or "",
            "type": node.type or "DETAIL"
        }
        tree.append(new_entry)

    session["modified"] = True

    return {
        "session_id": session_id,
        "status": "node_updated" if found else "node_added",
        "drawing_number": node.drawing_number
    }


@app.delete("/api/dt/session/{session_id}/node/{drawing_number}")
async def dt_delete_node(session_id: str, drawing_number: str):
    """Delete a node from the DT tree."""
    if session_id not in dt_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = dt_sessions[session_id]

    if session["status"] != "complete":
        raise HTTPException(status_code=400, detail="Session not ready for editing")

    tree = session.get("tree", [])
    original_count = len(tree)

    # Remove the node
    session["tree"] = [e for e in tree if e.get("drawing_number") != drawing_number]

    if len(session["tree"]) < original_count:
        session["modified"] = True
        return {"status": "deleted", "drawing_number": drawing_number}
    else:
        raise HTTPException(status_code=404, detail="Node not found in tree")


@app.post("/api/dt/session/{session_id}/export")
async def dt_export_nha(session_id: str, request: DTExportRequest = None):
    """
    Export DT tree as NHA overrides JSON.
    This JSON can be used with MIULBuilderV3 for accurate hierarchy.
    """
    import datetime

    if session_id not in dt_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = dt_sessions[session_id]

    if session["status"] != "complete":
        raise HTTPException(status_code=400, detail="Session not ready for export")

    tree = session.get("tree", [])
    top_level = session.get("top_level", "")

    # Build NHA overrides: child -> parent mapping
    nha_overrides = {}

    for entry in tree:
        child = entry.get("drawing_number", "").strip()
        parent = (entry.get("parent") or "").strip()

        if child and parent:
            nha_overrides[child] = parent

    # Add top-level if present
    if top_level:
        # Top level's "parent" is the project/system
        project = request.project_name if request else None
        if not project:
            # Extract prefix from top-level PN
            import re
            match = re.match(r'^([A-Z]+)', top_level.upper())
            project = match.group(1) if match else "SYSTEM"
        nha_overrides[top_level] = project

    result = {
        "nha_overrides": nha_overrides,
        "entry_count": len(nha_overrides),
        "top_level": top_level
    }

    # Add metadata if requested
    if request is None or request.include_metadata:
        result["_metadata"] = {
            "session_id": session_id,
            "filename": session.get("filename"),
            "generated": datetime.datetime.now().isoformat(),
            "project": request.project_name if request else None,
            "modified": session.get("modified", False)
        }

    return result


@app.delete("/api/dt/session/{session_id}")
async def dt_delete_session(session_id: str):
    """Delete a DT session."""
    if session_id not in dt_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    del dt_sessions[session_id]
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/dt/sessions")
async def dt_list_sessions():
    """List all DT sessions."""
    sessions = []
    for sid, session in dt_sessions.items():
        sessions.append({
            "session_id": sid,
            "status": session["status"],
            "filename": session.get("filename"),
            "top_level": session.get("top_level"),
            "entry_count": len(session.get("tree") or []),
            "modified": session.get("modified", False),
            "created_at": session.get("created_at")
        })
    return {"sessions": sessions, "total": len(sessions)}


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
