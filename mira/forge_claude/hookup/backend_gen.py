"""FastAPI app generation."""

from __future__ import annotations

from mira.forge_claude.question_gen.question_map import QuestionMap


def generate_app_py(
    question_map: QuestionMap,
    router_files: list[str],
    *,
    data_quality_report: object | None = None,
) -> str:
    """Generate the main FastAPI app.py.

    Args:
        question_map: The question map from Step 2.
        router_files: List of generated router filenames.
        data_quality_report: Optional v4.1 data quality report for enriched health.
    """
    imports = []
    includes = []
    for rf in sorted(router_files):
        module_name = rf.replace(".py", "")
        imports.append(f"from routers import {module_name}")
        includes.append(f"app.include_router({module_name}.router)")

    imports_str = "\n".join(imports)
    includes_str = "\n".join(f"    {inc}" for inc in includes)

    # Build quality stats for health endpoint
    quality_entries = []
    if question_map.capability_map:
        total = len(question_map.capability_map)
        reliable = question_map.total_reliable
        caveated = question_map.total_caveated
        pct = round(reliable / total * 100) if total else 100
        quality_entries.append(
            f'"quality": {{"total_questions": {total}, '
            f'"reliable": {reliable}, "caveated": {caveated}, '
            f'"reliability_percent": {pct}}}'
        )

    extra_health = ""
    if quality_entries:
        extra_health = ", " + ", ".join(quality_entries)

    return f'''"""Auto-generated FastAPI backend for {question_map.database_name}."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
{imports_str}

app = FastAPI(
    title="{question_map.database_name} API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

{includes_str}


@app.get("/api/health")
def health():
    """Health check endpoint."""
    return {{"status": "ok", "database": "{question_map.database_name}"{extra_health}}}
'''


def generate_database_py(db_url_env: str = "DATABASE_URL") -> str:
    """Generate the database.py connection module."""
    return f'''"""SQLAlchemy database connection setup."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''


def generate_config_py(database_name: str) -> str:
    """Generate the config.py module."""
    return f'''"""Environment-based configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = "sqlite:///./{database_name}.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    class Config:
        env_file = ".env"


settings = Settings()
'''
