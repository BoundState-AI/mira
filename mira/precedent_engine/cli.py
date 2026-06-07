#!/usr/bin/env python3
"""
Module: Cli
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer

from mira.precedent_engine.models.config import EngineConfig
from mira.precedent_engine.models.raw import RawMUARecord
import uuid

app = typer.Typer(
    name="mua-precedent",
    help="MUA Precedent Engine CLI - NASA Material Usage Agreement precedent reuse system",
)


def load_config(config_path: Path | None) -> EngineConfig:
    """Load configuration from file or use defaults."""
    if config_path and config_path.exists():
        with open(config_path) as f:
            config_data = json.load(f)
        return EngineConfig(**config_data)
    return EngineConfig()


@app.command()
def init_collection(
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON file"
    ),
) -> None:
    """Initialize Qdrant collection for MUA storage."""
    config = load_config(config_path)

    from mira.precedent_engine.core.storage import VectorStore

    with VectorStore(config) as store:
        asyncio.run(store.ensure_collection())

    typer.echo(f"Collection '{config.collection_name}' initialized at {config.qdrant_path}")


@app.command()
def index_corpus(
    jsonl_path: Path = typer.Argument(..., help="Path to parsed MUA JSONL file"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON file"
    ),
    batch_size: int = typer.Option(100, "--batch-size", "-b", help="Batch size for indexing"),
    use_mock_llm: bool = typer.Option(
        False, "--mock-llm", help="Use mock LLM for enrichment (testing)"
    ),
) -> None:
    """Index MUA corpus from JSONL file into vector store."""
    config = load_config(config_path)

    async def run_indexing():
        from mira.precedent_engine.core.enrichment import enrich_mua_record
        from mira.precedent_engine.core.storage import VectorStore
        from mira.precedent_engine.utils.bedrock import create_bedrock_llm_call, create_mock_llm_call
        from mira.precedent_engine.utils.maptis import MAPTISClient, MockMAPTISClient

        # Create LLM call function
        if use_mock_llm:
            llm_call = create_mock_llm_call()
        else:
            llm_call = create_bedrock_llm_call(config)

        # MAPTIS client: real DB-backed client unless mock mode is requested.
        maptis = MockMAPTISClient() if use_mock_llm else MAPTISClient()

        # Initialize storage
        store = VectorStore(config)
        await store.ensure_collection()

        # Process JSONL
        count = 0
        batch = []

        with open(jsonl_path) as f:
            for line in f:
                if not line.strip():
                    continue

                try:
                    record_data = json.loads(line)
                    raw = RawMUARecord(**record_data)

                    if not raw.success:
                        continue

                    # Enrich
                    enriched_list = await enrich_mua_record(raw, llm_call, maptis.lookup)
                    batch.extend(enriched_list)

                    # Batch upsert
                    if len(batch) >= batch_size:
                        await store.upsert(batch)
                        count += len(batch)
                        typer.echo(f"Indexed {count} MUAs...")
                        batch = []

                except Exception as e:
                    typer.echo(f"Error processing record: {e}", err=True)

        # Final batch
        if batch:
            await store.upsert(batch)
            count += len(batch)

        store.close()
        maptis.close()

        return count

    count = asyncio.run(run_indexing())
    typer.echo(f"Indexed {count} MUAs total.")


@app.command()
def cluster(
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON file"
    ),
) -> None:
    """Assign precedent families via HDBSCAN clustering."""
    config = load_config(config_path)

    if not config.enable_clustering:
        typer.echo("Clustering disabled in config.")
        raise typer.Exit(0)

    typer.echo("Clustering not yet implemented for persisted data.")
    typer.echo("Use during indexing for in-memory clustering.")
    raise typer.Exit(1)


@app.command()
def process_case(
    case_json: Path = typer.Argument(..., help="Path to case JSON file"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON file"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output path for result JSON"
    ),
    use_mock_llm: bool = typer.Option(
        False, "--mock-llm", help="Use mock LLM (testing)"
    ),
) -> None:
    """Process a new MUA case and generate precedent-based draft."""
    config = load_config(config_path)

    async def run_processing():
        from mira.precedent_engine.core.enrichment import enrich_mua_record
        from mira.precedent_engine.core.narrator import MockNarratorLLM, NarratorLLM
        from mira.precedent_engine.core.runner import MUAPrecedentRunner
        from mira.precedent_engine.core.storage import VectorStore
        from mira.precedent_engine.utils.bedrock import create_bedrock_llm_call, create_mock_llm_call
        from mira.precedent_engine.utils.maptis import MAPTISClient, MockMAPTISClient

        # Load case
        with open(case_json) as f:
            case_data = json.load(f)

        raw = RawMUARecord(**case_data)

        # Create components
        if use_mock_llm:
            llm_call = create_mock_llm_call()
            narrator = MockNarratorLLM(config)
        else:
            llm_call = create_bedrock_llm_call(config)
            narrator = NarratorLLM(config)

        maptis = MockMAPTISClient() if use_mock_llm else MAPTISClient()
        store = VectorStore(config)

        # Enrich case
        enriched_list = await enrich_mua_record(raw, llm_call, maptis.lookup)

        if not enriched_list:
            typer.echo("Invalid material designation.", err=True)
            raise typer.Exit(1)

        enriched = enriched_list[0]

        # Process
        runner = MUAPrecedentRunner(config, store, narrator)
        result = await runner.process_case(enriched)

        # Cleanup
        runner.close()
        maptis.close()

        return result

    result = asyncio.run(run_processing())

    # Output
    result_json = result.model_dump_json(indent=2)

    if output:
        with open(output, "w") as f:
            f.write(result_json)
        typer.echo(f"Result written to {output}")
    else:
        typer.echo(result_json)


@app.command()
def stats(
    material: str = typer.Argument(..., help="Material designation to query"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON file"
    ),
) -> None:
    """Show precedent statistics for a material."""
    config = load_config(config_path)

    async def run_stats():
        from mira.precedent_engine.core.embeddings import EmbeddingModel
        from mira.precedent_engine.core.precedent_engine import PrecedentEngine
        from mira.precedent_engine.core.storage import VectorStore
        from mira.precedent_engine.models.enriched import EnrichedMUA

        # Create minimal query
        query = EnrichedMUA(
            contract_id="QUERY",
            source_file="",
            material_name=material,
            material_key=None,
        )

        # Search
        store = VectorStore(config)
        candidates = await store.search(query, top_k=1000, score_threshold=0.0)

        # Compute stats
        engine = PrecedentEngine(config.equivalence, config.adequacy)
        stats = engine._compute_statistics(query, candidates)

        store.close()

        return stats

    stats_result = asyncio.run(run_stats())

    typer.echo(f"\nPrecedent Statistics for: {material}")
    typer.echo("=" * 50)
    typer.echo(f"Total MUAs: {stats_result.n_total_with_material}")
    typer.echo(f"Approved: {stats_result.n_approved}")
    typer.echo(f"Rejected: {stats_result.n_rejected}")
    typer.echo(f"Deferred: {stats_result.n_deferred}")
    typer.echo(f"Similar Environment: {stats_result.n_similar_environment}")
    typer.echo(f"Same Deviation: {stats_result.n_same_deviation}")
    typer.echo(f"Approval Rate: {stats_result.approval_rate:.1%}")
    typer.echo(f"Rejection Rate Upper Bound (95% CI): {stats_result.rejection_rate_upper_bound:.1%}")


@app.command()
def export_config(
    output: Path = typer.Argument(..., help="Output path for config JSON"),
) -> None:
    """Export default configuration to JSON file."""
    config = EngineConfig()
    config_json = config.model_dump_json(indent=2)

    with open(output, "w") as f:
        f.write(config_json)

    typer.echo(f"Default config exported to {output}")


@app.command()
def info() -> None:
    """Show package information and version."""
    from mua_precedent_engine import __author__, __version__

    typer.echo("MUA Precedent Engine")
    typer.echo(f"Version: {__version__}")
    typer.echo(f"Authors: {__author__}")
    typer.echo("")
    typer.echo("This is a precedent reuse system for NASA Material Usage Agreements.")
    typer.echo("It transforms MUA generation from a manual process into automated draft")
    typer.echo("with full provenance tracking.")
    typer.echo("")
    typer.echo("IMPORTANT: All decisions remain with human engineers.")
    typer.echo("The system cannot approve, reject, or make compliance determinations.")


if __name__ == "__main__":
    app()
