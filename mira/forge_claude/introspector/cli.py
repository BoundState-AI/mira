"""CLI entry point for schema introspection."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from mira.forge_claude.introspector.engine import introspect_database

app = typer.Typer(help="Schema introspection commands.")


@app.command()
def introspect(
    db_url: str = typer.Option(..., "--db-url", help="SQLAlchemy database connection string."),
    output: Path = typer.Option(
        Path("schema_manifest.json"), "--output", "-o", help="Output file path."
    ),
    sample_count: int = typer.Option(5, "--samples", help="Sample values per text column."),
) -> None:
    """Connect to a database and produce a schema manifest."""
    typer.echo(f"Introspecting database: {db_url}")

    try:
        manifest = introspect_database(db_url, sample_count=sample_count)
    except Exception as e:
        typer.echo(f"Error connecting to database: {e}", err=True)
        raise typer.Exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest.model_dump(), indent=2))
    typer.echo(
        f"Schema manifest written to {output} "
        f"({manifest.statistics.total_tables} tables, "
        f"{manifest.statistics.total_rows} rows, "
        f"{manifest.statistics.total_columns} columns)"
    )
