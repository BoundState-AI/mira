#!/usr/bin/env python3
"""
Module: Mua Cli
Purpose: Search for historic MUA precedents using semantic similarity.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import typer
from typing import Optional
from pathlib import Path

app = typer.Typer(
    name="mua",
    help="MUA Precedent System - Find and reuse historic Material Usage Agreements"
)


@app.command()
def search(
    material: str = typer.Argument(..., help="Material designation (e.g., 'INCONEL 625')"),
    environment: Optional[str] = typer.Option(None, "--env", "-e", help="Environment (e.g., 'Oxygen')"),
    application: Optional[str] = typer.Option(None, "--app", "-a", help="Application context"),
    limit: int = typer.Option(5, "--limit", "-n", help="Number of results"),
):
    """Search for historic MUA precedents using semantic similarity."""
    from mira.miul.mua_faiss_search import MUAFAISSSearch

    typer.echo("Loading FAISS index...")
    search_engine = MUAFAISSSearch()
    results = search_engine.search(material, environment, application, k=limit)

    if not results:
        typer.echo("No precedents found.")
        raise typer.Exit(1)

    typer.echo(f"\n{'='*60}")
    typer.echo(f"Precedents for: {material}" + (f" in {environment}" if environment else ""))
    typer.echo(f"{'='*60}\n")

    for r in results:
        typer.echo(f"{r.rank}. {r.file} (Score: {r.score:.3f}, String: {r.string_score:.0%})")
        typer.echo(f"   Material: {r.material_designation}")
        typer.echo(f"   Family: {r.material_family or 'unknown'}")
        typer.echo(f"   Environment: {r.environment or 'N/A'}")
        typer.echo(f"   Category: {r.category or 'N/A'}")
        typer.echo(f"   Determination: {r.determination}")
        if r.rationale:
            preview = r.rationale[:150] + "..." if len(r.rationale) > 150 else r.rationale
            typer.echo(f"   Rationale: {preview}")
        typer.echo("")


@app.command()
def draft(
    material: str = typer.Argument(..., help="Material designation"),
    environment: str = typer.Argument(..., help="Environment"),
    application: str = typer.Argument(..., help="Application context"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file"),
):
    """Generate a draft MUA based on historic precedents."""
    from mira.miul.mua_faiss_search import MUAFAISSSearch

    typer.echo("Loading FAISS index...")
    search_engine = MUAFAISSSearch()
    precedents = search_engine.search(material, environment, application, k=5)

    if not precedents:
        typer.echo("No precedents found. Manual MUA required.")
        raise typer.Exit(1)

    best = precedents[0]

    draft_text = f"""DRAFT MUA - Based on {len(precedents)} Precedent(s)

{'='*60}
PRIMARY PRECEDENT
{'='*60}
File: {best.file}
MUA Number: {best.mua_number or 'N/A'}
Material: {best.material_designation}
Material Family: {best.material_family or 'unknown'}
Environment: {best.environment}
Category: {best.category}
Determination: {best.determination}
Match Score: {best.score:.3f} (String Match: {best.string_score:.0%})

PRECEDENT RATIONALE:
{best.rationale or 'N/A'}

{'='*60}
DRAFT FOR NEW MUA
{'='*60}
Material: {material}
Environment: {environment}
Application: {application}

SUGGESTED RATIONALE:
[Adapt from precedent above - verify current test data]

REVIEWER NOTES:
- Primary precedent: {best.file}
- Match quality: {best.string_score:.0%} string match, {best.score:.3f} combined score
- Precedent determination: {best.determination}
- Review and update rationale for specific application
- Verify all test data is current

ADDITIONAL PRECEDENTS:
"""
    for i, p in enumerate(precedents[1:4], 2):
        draft_text += f"\n{i}. {p.file} - {p.material_designation} ({p.determination})"

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(draft_text)
        typer.echo(f"Draft saved to: {output}")
    else:
        typer.echo(draft_text)


@app.command()
def stats():
    """Show MUA index statistics."""
    from mira.miul.mua_faiss_search import MUAFAISSSearch
    from collections import Counter

    typer.echo("Loading FAISS index...")
    search_engine = MUAFAISSSearch()
    meta = search_engine.metadata

    families = Counter(m.get("material_family") for m in meta)
    determinations = Counter(m.get("determination") for m in meta)
    categories = Counter(m.get("category") for m in meta if m.get("category"))
    umbrella_count = sum(1 for m in meta if m.get("is_umbrella"))

    typer.echo(f"\n{'='*40}")
    typer.echo("MUA FAISS Index Statistics")
    typer.echo(f"{'='*40}")
    typer.echo(f"Total MUAs indexed: {len(meta)}")
    typer.echo(f"Umbrella MUAs: {umbrella_count} (filtered by default)")
    typer.echo(f"Searchable MUAs: {len(meta) - umbrella_count}")

    typer.echo(f"\nMaterial Families:")
    for fam, count in families.most_common(12):
        typer.echo(f"  {fam or 'unknown'}: {count}")

    typer.echo(f"\nDeterminations:")
    for det, count in determinations.most_common():
        typer.echo(f"  {det or 'unknown'}: {count}")

    typer.echo(f"\nCategories:")
    for cat, count in categories.most_common():
        typer.echo(f"  {cat}: {count}")


if __name__ == "__main__":
    app()
