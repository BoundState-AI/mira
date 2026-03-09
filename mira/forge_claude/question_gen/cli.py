"""CLI entry point for question generation."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from mira.forge_claude.introspector.manifest import SchemaManifest
from mira.forge_claude.question_gen.deterministic import generate_questions_deterministic
from mira.forge_claude.question_gen.llm_refiner import refine_questions_with_llm

app = typer.Typer(help="Question generation commands.")


@app.command()
def questions(
    manifest: Path = typer.Option(
        ..., "--manifest", "-m", help="Path to schema_manifest.json."
    ),
    output: Path = typer.Option(
        Path("question_map.json"), "--output", "-o", help="Output file path."
    ),
    use_llm: bool = typer.Option(
        False, "--llm", help="Use LLM refinement pass (requires BSMH provider)."
    ),
) -> None:
    """Analyze a schema manifest and generate a question map."""
    typer.echo(f"Reading schema manifest from {manifest}")

    data = json.loads(manifest.read_text())
    schema = SchemaManifest(**data)

    typer.echo(f"Generating questions for {schema.database_name}...")
    question_map = generate_questions_deterministic(schema)

    if use_llm:
        typer.echo("Refining questions with LLM...")
        question_map = refine_questions_with_llm(schema, question_map)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(question_map.model_dump(), indent=2))

    total_questions = sum(
        len(cat.questions) for cat in question_map.question_categories
    )
    typer.echo(
        f"Question map written to {output} "
        f"({total_questions} questions in {len(question_map.question_categories)} categories)"
    )
