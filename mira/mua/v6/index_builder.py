#!/usr/bin/env python3
"""
Module: Index Builder
Purpose: V6 FAISS Index Builder - Build semantic search index from cleaned MUA records.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation)
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .precedent_models import CleanedMUARecord

logger = logging.getLogger(__name__)

__all__ = ["V6IndexBuilder", "build_mua_index"]

# Default embedding model (matches existing BoundState infrastructure)
DEFAULT_EMBEDDING_MODEL = "all-mpnet-base-v2"

# Index paths
DEFAULT_INDEX_DIR = Path(r"C:\BoundState\mira\databases\mua_v6_faiss")


class V6IndexBuilder:
    """Build FAISS index from cleaned MUA records."""

    def __init__(
        self,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        index_dir: Path = DEFAULT_INDEX_DIR,
    ):
        """
        Args:
            embedding_model: Sentence transformer model name
            index_dir: Directory to save index files
        """
        self.embedding_model = embedding_model
        self.index_dir = Path(index_dir)
        self._encoder = None
        self._index = None
        self._metadata: List[Dict] = []

    def _get_encoder(self):
        """Lazy-load sentence transformer."""
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.embedding_model}")
            self._encoder = SentenceTransformer(self.embedding_model)
        return self._encoder

    def build_index(
        self,
        records: List[CleanedMUARecord],
        batch_size: int = 64,
    ) -> Tuple[int, int]:
        """Build FAISS index from records.

        Args:
            records: List of cleaned MUA records
            batch_size: Embedding batch size

        Returns:
            Tuple of (records_indexed, embedding_dimension)
        """
        import faiss

        if not records:
            raise ValueError("No records to index")

        encoder = self._get_encoder()

        # Generate search texts
        logger.info(f"Generating search texts for {len(records)} records...")
        search_texts = [r.search_text() for r in records]

        # Generate embeddings in batches
        logger.info(f"Generating embeddings (batch_size={batch_size})...")
        embeddings = encoder.encode(
            search_texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
        )

        # Create FAISS index
        dimension = embeddings.shape[1]
        logger.info(f"Creating FAISS index (dimension={dimension})...")

        # Use IndexFlatIP for inner product (cosine similarity with normalized vectors)
        # Normalize embeddings for cosine similarity
        faiss.normalize_L2(embeddings)
        self._index = faiss.IndexFlatIP(dimension)
        self._index.add(embeddings)

        # Store metadata
        self._metadata = [r.model_dump() for r in records]

        logger.info(f"Index built: {self._index.ntotal} vectors")
        return self._index.ntotal, dimension

    def save(self, index_dir: Optional[Path] = None):
        """Save index and metadata to disk.

        Args:
            index_dir: Directory to save to (uses default if not specified)
        """
        import faiss

        if self._index is None:
            raise ValueError("No index to save. Call build_index first.")

        save_dir = Path(index_dir) if index_dir else self.index_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        index_path = save_dir / "index.faiss"
        logger.info(f"Saving FAISS index to {index_path}")
        faiss.write_index(self._index, str(index_path))

        # Save metadata
        metadata_path = save_dir / "metadata.json"
        logger.info(f"Saving metadata to {metadata_path}")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump({
                "embedding_model": self.embedding_model,
                "total_records": len(self._metadata),
                "records": self._metadata,
            }, f, indent=2, default=str)

        logger.info(f"Index saved to {save_dir}")

    def load(self, index_dir: Optional[Path] = None) -> int:
        """Load index and metadata from disk.

        Args:
            index_dir: Directory to load from

        Returns:
            Number of records in index
        """
        import faiss

        load_dir = Path(index_dir) if index_dir else self.index_dir

        index_path = load_dir / "index.faiss"
        metadata_path = load_dir / "metadata.json"

        if not index_path.exists():
            raise FileNotFoundError(f"Index not found: {index_path}")

        logger.info(f"Loading FAISS index from {index_path}")
        self._index = faiss.read_index(str(index_path))

        logger.info(f"Loading metadata from {metadata_path}")
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._metadata = data.get("records", [])
            self.embedding_model = data.get("embedding_model", DEFAULT_EMBEDDING_MODEL)

        logger.info(f"Loaded index with {self._index.ntotal} vectors")
        return self._index.ntotal

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Tuple[CleanedMUARecord, float]]:
        """Search for similar records.

        Args:
            query: Search query text
            top_k: Number of results to return

        Returns:
            List of (record, score) tuples
        """
        import faiss

        if self._index is None:
            raise ValueError("No index loaded. Call load() or build_index() first.")

        encoder = self._get_encoder()

        # Encode query
        query_embedding = encoder.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)

        # Search
        scores, indices = self._index.search(query_embedding, top_k)

        # Build results
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx < len(self._metadata):
                record = CleanedMUARecord(**self._metadata[idx])
                results.append((record, float(score)))

        return results

    def get_stats(self) -> Dict:
        """Get index statistics."""
        if self._index is None:
            return {"status": "no_index_loaded"}

        # Count by various categories
        stats = {
            "total_records": len(self._metadata),
            "index_vectors": self._index.ntotal,
            "embedding_model": self.embedding_model,
            "by_determination": {},
            "by_environment_type": {},
            "by_material_family": {},
            "by_issue_category": {},
        }

        for record in self._metadata:
            # Determination
            det = record.get("determination", "UNKNOWN")
            stats["by_determination"][det] = stats["by_determination"].get(det, 0) + 1

            # Environment type
            env = record.get("environment", {})
            env_type = env.get("type", "unknown") if isinstance(env, dict) else "unknown"
            stats["by_environment_type"][env_type] = stats["by_environment_type"].get(env_type, 0) + 1

            # Material family
            family = record.get("material_family", "unknown")
            stats["by_material_family"][family] = stats["by_material_family"].get(family, 0) + 1

            # Issue categories
            issues = record.get("issues", [])
            for issue in issues:
                stats["by_issue_category"][issue] = stats["by_issue_category"].get(issue, 0) + 1

        return stats


def build_mua_index(
    input_path: Path,
    output_dir: Path = DEFAULT_INDEX_DIR,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> Tuple[int, Dict]:
    """Build FAISS index from cleaned MUA records.

    Args:
        input_path: Path to cleaned JSONL file
        output_dir: Directory to save index
        embedding_model: Embedding model name

    Returns:
        Tuple of (records_indexed, stats)
    """
    # Load cleaned records
    logger.info(f"Loading cleaned records from {input_path}")
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                records.append(CleanedMUARecord(**data))

    logger.info(f"Loaded {len(records)} records")

    # Build index
    builder = V6IndexBuilder(embedding_model=embedding_model, index_dir=output_dir)
    count, dim = builder.build_index(records)

    # Save
    builder.save()

    # Get stats
    stats = builder.get_stats()

    return count, stats


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Build FAISS index for MUA precedents")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(r"C:\BoundState\data\mua_v6_cleaned.jsonl"),
        help="Input cleaned JSONL file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_INDEX_DIR,
        help="Output directory for index",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"Embedding model (default: {DEFAULT_EMBEDDING_MODEL})",
    )

    args = parser.parse_args()

    count, stats = build_mua_index(args.input, args.output, args.model)

    print(f"\n{'='*50}")
    print("Index Build Complete")
    print(f"{'='*50}")
    print(f"Records indexed: {count:,}")
    print(f"Output: {args.output}")

    print(f"\n--- By Determination ---")
    for det, cnt in sorted(stats["by_determination"].items(), key=lambda x: -x[1]):
        print(f"  {det}: {cnt:,}")

    print(f"\n--- By Environment Type ---")
    for env, cnt in sorted(stats["by_environment_type"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {env}: {cnt:,}")

    print(f"\n--- By Material Family ---")
    for fam, cnt in sorted(stats["by_material_family"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {fam}: {cnt:,}")

    print(f"\n--- By Issue Category ---")
    for issue, cnt in sorted(stats["by_issue_category"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {issue}: {cnt:,}")
