"""Minimal server for test-classes endpoints only.

Avoids importing the full app (and its heavy dependencies like boto3, numpy).
Reads .env for POSTGRES_PORT=5433 (USB drive PG instance).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env before anything else
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mira.api.routers.test_classes import router

app = FastAPI(title="MIRA Test Classes (minimal)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("TEST_CLASSES_PORT", "8001"))
    print(f"Starting test-classes server on :{port}")
    print(f"  POSTGRES_PORT={os.environ.get('POSTGRES_PORT')}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
