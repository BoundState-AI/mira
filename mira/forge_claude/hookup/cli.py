"""CLI entry point for hook-up wizard."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from mira.forge_claude.config import DEFAULT_OUTPUT_DIR
from mira.forge_claude.hookup.wizard import run_hookup_wizard
from mira.forge_claude.introspector.manifest import SchemaManifest
from mira.forge_claude.question_gen.question_map import QuestionMap

app = typer.Typer(help="Hook-up wizard commands.")


@app.command()
def hookup(
    project: str = typer.Option(..., "--project", "-p", help="Project/database name."),
    questions: Path = typer.Option(
        None, "--questions", "-q", help="Path to question_map.json."
    ),
    manifest: Path = typer.Option(
        None, "--manifest", "-m", help="Path to schema_manifest.json."
    ),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output", "-o", help="Output directory."
    ),
    db_url: str = typer.Option(
        None, "--db-url", help="Production database URL."
    ),
) -> None:
    """Generate FastAPI backend and deployment configs."""
    # Try to find files automatically if not specified
    if questions is None:
        questions = Path("question_map.json")
    if manifest is None:
        manifest = Path("schema_manifest.json")

    if not questions.exists():
        typer.echo(f"Question map not found: {questions}", err=True)
        raise typer.Exit(1)
    if not manifest.exists():
        typer.echo(f"Schema manifest not found: {manifest}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Setting up backend for project: {project}")

    question_map = QuestionMap(**json.loads(questions.read_text()))
    schema_manifest = SchemaManifest(**json.loads(manifest.read_text()))

    project_dir = run_hookup_wizard(
        question_map=question_map,
        manifest=schema_manifest,
        output_dir=output_dir,
        db_url=db_url,
    )

    typer.echo(f"Backend generated at {project_dir / 'backend'}")
    typer.echo(f"Deployment configs generated at {project_dir}")
    typer.echo("")
    typer.echo("To run locally:")
    typer.echo(f"  docker-compose -f {project_dir}/docker-compose.yml up")
    typer.echo("")
    typer.echo("To deploy:")
    typer.echo(f"  Backend: Push {project_dir}/backend to Railway")
    typer.echo(f"  Frontend: Push {project_dir}/frontend to Vercel")
