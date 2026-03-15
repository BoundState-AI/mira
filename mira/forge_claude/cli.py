"""FORGE CLI — single entry point for all commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from mira.forge_claude.config import DEFAULT_OUTPUT_DIR

app = typer.Typer(
    name="forge",
    help="FORGE — BoundState Database Intelligence Scaffolder.",
    no_args_is_help=True,
)


@app.command()
def introspect(
    db_url: str = typer.Option(..., "--db-url", help="SQLAlchemy database connection string."),
    output: Path = typer.Option(
        Path("schema_manifest.json"), "--output", "-o", help="Output file path."
    ),
    samples: int = typer.Option(5, "--samples", help="Sample values per text column."),
) -> None:
    """Step 1: Connect to a database and produce a schema manifest."""
    from mira.forge_claude.introspector.engine import introspect_database

    typer.echo(f"Introspecting database: {db_url}")

    try:
        manifest = introspect_database(db_url, sample_count=samples)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest.model_dump(), indent=2))
    typer.echo(
        f"Schema manifest: {output} "
        f"({manifest.statistics.total_tables} tables, "
        f"{manifest.statistics.total_rows} rows)"
    )


@app.command()
def questions(
    manifest: Path = typer.Option(
        Path("schema_manifest.json"), "--manifest", "-m", help="Schema manifest path."
    ),
    output: Path = typer.Option(
        Path("question_map.json"), "--output", "-o", help="Output file path."
    ),
    llm: bool = typer.Option(False, "--llm", help="Use LLM refinement pass."),
) -> None:
    """Step 2: Generate questions from a schema manifest."""
    from mira.forge_claude.question_gen.deterministic import generate_questions_deterministic
    from mira.forge_claude.question_gen.llm_refiner import refine_questions_with_llm
    from mira.forge_claude.introspector.manifest import SchemaManifest

    if not manifest.exists():
        typer.echo(f"Manifest not found: {manifest}", err=True)
        raise typer.Exit(1)

    data = json.loads(manifest.read_text())
    schema = SchemaManifest(**data)

    typer.echo(f"Generating questions for {schema.database_name}...")
    question_map = generate_questions_deterministic(schema)

    if llm:
        typer.echo("Refining with LLM...")
        question_map = refine_questions_with_llm(schema, question_map)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(question_map.model_dump(), indent=2))

    total = sum(len(c.questions) for c in question_map.question_categories)
    typer.echo(f"Question map: {output} ({total} questions)")


@app.command()
def scaffold(
    questions_path: Path = typer.Option(
        Path("question_map.json"), "--questions", "-q", help="Question map path."
    ),
    manifest: Path = typer.Option(
        Path("schema_manifest.json"), "--manifest", "-m", help="Schema manifest path."
    ),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output", "-o", help="Output directory."
    ),
) -> None:
    """Step 3: Scaffold a React + Tailwind MVP frontend."""
    from mira.forge_claude.introspector.manifest import SchemaManifest
    from mira.forge_claude.question_gen.question_map import QuestionMap
    from mira.forge_claude.scaffolder.generator import scaffold_frontend

    if not questions_path.exists():
        typer.echo(f"Question map not found: {questions_path}", err=True)
        raise typer.Exit(1)

    question_map = QuestionMap(**json.loads(questions_path.read_text()))

    if manifest.exists():
        schema = SchemaManifest(**json.loads(manifest.read_text()))
    else:
        schema = SchemaManifest(
            database_type="unknown", database_name=question_map.database_name
        )

    typer.echo(f"Scaffolding frontend for {question_map.database_name}...")
    frontend_dir = scaffold_frontend(question_map, schema, output_dir)
    typer.echo(f"Frontend: {frontend_dir}")


@app.command()
def hookup(
    project: str = typer.Option(..., "--project", "-p", help="Project/database name."),
    questions_path: Path = typer.Option(
        Path("question_map.json"), "--questions", "-q", help="Question map path."
    ),
    manifest: Path = typer.Option(
        Path("schema_manifest.json"), "--manifest", "-m", help="Schema manifest path."
    ),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output", "-o", help="Output directory."
    ),
    db_url: str = typer.Option(None, "--db-url", help="Production database URL."),
) -> None:
    """Step 4: Generate FastAPI backend and deployment configs."""
    from mira.forge_claude.introspector.manifest import SchemaManifest
    from mira.forge_claude.question_gen.question_map import QuestionMap
    from mira.forge_claude.hookup.wizard import run_hookup_wizard

    if not questions_path.exists():
        typer.echo(f"Question map not found: {questions_path}", err=True)
        raise typer.Exit(1)
    if not manifest.exists():
        typer.echo(f"Schema manifest not found: {manifest}", err=True)
        raise typer.Exit(1)

    question_map = QuestionMap(**json.loads(questions_path.read_text()))
    schema = SchemaManifest(**json.loads(manifest.read_text()))

    typer.echo(f"Generating backend for {project}...")
    project_dir = run_hookup_wizard(question_map, schema, output_dir, db_url)
    typer.echo(f"Project: {project_dir}")


@app.command()
def pack(
    questions_path: Path = typer.Option(
        Path("question_map.json"), "--questions", "-q", help="Question map path."
    ),
    manifest: Path = typer.Option(
        Path("schema_manifest.json"), "--manifest", "-m", help="Schema manifest path."
    ),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output", "-o", help="Output directory."
    ),
) -> None:
    """Step 5: Generate an Authority Pack (rules, evidence schemas, human gates)."""
    from mira.forge_claude.introspector.manifest import SchemaManifest
    from mira.forge_claude.question_gen.question_map import QuestionMap
    from mira.forge_claude.authority.pack_gen import generate_authority_pack

    if not questions_path.exists():
        typer.echo(f"Question map not found: {questions_path}", err=True)
        raise typer.Exit(1)
    if not manifest.exists():
        typer.echo(f"Schema manifest not found: {manifest}", err=True)
        raise typer.Exit(1)

    question_map = QuestionMap(**json.loads(questions_path.read_text()))
    schema = SchemaManifest(**json.loads(manifest.read_text()))

    typer.echo(f"Generating authority pack for {question_map.database_name}...")
    pack_dir = generate_authority_pack(question_map=question_map, manifest=schema, output_dir=output_dir)
    typer.echo(f"Authority pack: {pack_dir}")


@app.command()
def build(
    db_url: str = typer.Option(..., "--db-url", help="SQLAlchemy database connection string."),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output", "-o", help="Output directory."
    ),
    llm: bool = typer.Option(False, "--llm", help="Use LLM refinement pass."),
) -> None:
    """Run the full pipeline: introspect -> questions -> scaffold -> hookup -> pack."""
    from mira.forge_claude.introspector.engine import introspect_database_full
    from mira.forge_claude.question_gen.deterministic import generate_questions_deterministic
    from mira.forge_claude.question_gen.llm_refiner import refine_questions_with_llm
    from mira.forge_claude.scaffolder.generator import scaffold_frontend
    from mira.forge_claude.hookup.wizard import run_hookup_wizard
    from mira.forge_claude.authority.pack_gen import generate_authority_pack

    # Step 1: Introspect (full v4.1)
    typer.echo("Step 1/5: Introspecting database...")
    try:
        result = introspect_database_full(db_url)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    manifest = result.manifest
    db_name = manifest.database_name
    typer.echo(
        f"  Found {manifest.statistics.total_tables} tables, "
        f"{manifest.statistics.total_rows} rows"
    )

    # Save all Step 1 artifacts
    artifact_dir = output_dir / db_name
    artifact_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = artifact_dir / "schema_manifest.json"
    manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2))

    (artifact_dir / "semantic_map.json").write_text(
        json.dumps(result.semantic_map.model_dump(), indent=2)
    )
    (artifact_dir / "relationship_graph.json").write_text(
        json.dumps(result.relationship_graph.model_dump(), indent=2)
    )
    (artifact_dir / "latent_relationships.json").write_text(
        json.dumps(result.latent_relationships.model_dump(), indent=2)
    )
    (artifact_dir / "data_quality_report.json").write_text(
        json.dumps(result.data_quality_report.model_dump(), indent=2)
    )
    typer.echo(
        f"  Semantic fields: {len(result.semantic_map.fields)}, "
        f"Quality flags: {result.data_quality_report.summary.get('total_flags', 0)}"
    )

    # Step 2: Generate questions (v4.1 enhanced)
    typer.echo("Step 2/5: Generating questions...")
    from mira.forge_claude.question_gen.enhanced import generate_questions_enhanced
    question_map = generate_questions_enhanced(
        manifest,
        semantic_map=result.semantic_map,
        relationship_graph=result.relationship_graph,
        latent_relationships=result.latent_relationships,
        data_quality_report=result.data_quality_report,
    )
    if llm:
        question_map = refine_questions_with_llm(manifest, question_map)

    total_q = sum(len(c.questions) for c in question_map.question_categories)
    typer.echo(
        f"  Generated {total_q} questions "
        f"({question_map.total_reliable} reliable, {question_map.total_caveated} caveated)"
    )

    # Save question map
    qmap_path = output_dir / db_name / "question_map.json"
    qmap_path.write_text(json.dumps(question_map.model_dump(), indent=2))

    # Step 3: Scaffold frontend
    typer.echo("Step 3/5: Scaffolding frontend...")
    frontend_dir = scaffold_frontend(
        question_map, manifest, output_dir,
        data_quality_report=result.data_quality_report,
    )
    typer.echo(f"  Frontend: {frontend_dir}")

    # Step 4: Hook-up backend (v4.1 enriched)
    typer.echo("Step 4/5: Generating backend...")
    project_dir = run_hookup_wizard(
        question_map, manifest, output_dir, db_url,
        semantic_map=result.semantic_map,
        data_quality_report=result.data_quality_report,
    )
    typer.echo(f"  Backend: {project_dir / 'backend'}")

    # Step 5: Authority Pack (v4.1 enriched)
    typer.echo("Step 5/5: Generating authority pack...")
    pack_dir = generate_authority_pack(
        manifest, question_map, output_dir,
        semantic_map=result.semantic_map,
        data_quality_report=result.data_quality_report,
    )
    typer.echo(f"  Authority pack: {pack_dir}")

    typer.echo("")
    typer.echo(f"Build complete! Project at {project_dir}")
    typer.echo("")
    typer.echo("Quick start:")
    typer.echo(f"  docker-compose -f {project_dir}/docker-compose.yml up")
