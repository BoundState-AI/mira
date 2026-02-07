# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
SENTINEL API - FastAPI application.

The Grounded Precision Translation Layer deployed as a service.

Philosophy:
    "We don't retrieve truth. We eliminate impossibility—then show our work."

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gptl.api.routes import query, audit, domains, health
from gptl.api.deps import get_settings, init_providers

__safety_critical__: bool = True

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan handler."""
    # Startup
    logger.info("SENTINEL API starting up...")
    settings = get_settings()
    init_providers(settings)
    logger.info(f"SENTINEL API ready. Default domain: {settings.default_domain}")
    yield
    # Shutdown
    logger.info("SENTINEL API shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="SENTINEL",
        description="""
## Grounded Precision Translation Layer

SENTINEL is GPTL deployed as a service - a negative selection intelligence engine that:

- Accepts documents + questions
- Eliminates the 80% that CANNOT be relevant
- Produces bounded, auditable intelligence
- Refuses deterministically when evidence is insufficient
- Shows its work completely

**Philosophy:** *"We don't retrieve truth. We eliminate impossibility—then show our work."*

### API Endpoints

- `POST /api/v1/query` - Execute a SENTINEL query
- `GET /api/v1/audit/{trace_id}` - Retrieve audit trail
- `GET /api/v1/domains` - List available domain packs
- `GET /api/v1/domains/{id}` - Get domain pack details
- `GET /health` - Liveness check
- `GET /ready` - Readiness check

### Authentication

Set `X-API-Key` header if auth is enabled (`SENTINEL_AUTH_MODE=api_key`).

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
*Co-Authored-By: Dr. Joseph Wilde, BoundState AI*
        """,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    origins = settings.cors_origins.split(",") if settings.cors_origins else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(health.router, tags=["Health"])
    app.include_router(query.router, prefix="/api/v1", tags=["Query"])
    app.include_router(audit.router, prefix="/api/v1", tags=["Audit"])
    app.include_router(domains.router, prefix="/api/v1", tags=["Domains"])

    return app


# Create the app instance
app = create_app()


# For running with uvicorn directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "gptl.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


__all__ = ["app", "create_app"]
