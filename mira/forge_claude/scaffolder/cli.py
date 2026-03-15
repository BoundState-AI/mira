"""CLI entry point for frontend scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from mira.forge_claude.config import DEFAULT_OUTPUT_DIR
from mira.forge_claude.introspector.manifest import SchemaManifest
from mira.forge_claude.question_gen.question_map import QuestionMap
from mira.forge_claude.scaffolder.generator import scaffold_frontend

app = typer.Typer(help="Frontend scaffolding commands.")


@app.command()
def scaffold(
    questions: Path = typer.Option(
        ..., "--questions", "-q", help="Path to question_map.json."
    ),
    manifest: Path = typer.Option(
        None, "--manifest", "-m", help="Path to schema_manifest.json (for mock data)."
    ),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output", "-o", help="Output directory."
    ),
) -> None:
    """Generate a React + Tailwind MVP frontend from a question map."""
    typer.echo(f"Reading question map from {questions}")
    question_map = QuestionMap(**json.loads(questions.read_text()))

    schema_manifest = None
    if manifest:
        typer.echo(f"Reading schema manifest from {manifest}")
        schema_manifest = SchemaManifest(**json.loads(manifest.read_text()))
    else:
        # Create a minimal manifest for scaffolding
        schema_manifest = SchemaManifest(
            database_type="unknown",
            database_name=question_map.database_name,
        )

    typer.echo(f"Scaffolding frontend for {question_map.database_name}...")
    frontend_dir = scaffold_frontend(question_map, schema_manifest, output_dir)

    typer.echo(f"Frontend scaffolded to {frontend_dir}")
    typer.echo("Next steps:")
    typer.echo(f"  cd {frontend_dir}")
    typer.echo("  npm install")
    typer.echo("  npm run dev")
