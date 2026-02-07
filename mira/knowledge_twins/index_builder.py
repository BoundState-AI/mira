#!/usr/bin/env python3
"""
Module: Index Builder
Purpose: index_builder

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .compatibility_models import (
    CompatibilityRecord,
    GasType,
)


logger = logging.getLogger(__name__)

__all__ = [
    "H2_BOK_INDEX_CONFIG",
    "O2_BOK_INDEX_CONFIG",
    "create_embedding_text",
    "normalize_embedding",
    "TwinIndexBuilder",
    "TwinIndexSearcher",
]


# ---------------------------------------------------------------------------
# Index Configuration
# ---------------------------------------------------------------------------


H2_BOK_INDEX_CONFIG = {
    "name": "h2_bok_v2",
    "dimension": 768,  # Nomic embeddings
    "index_type": "IVF256,Flat",
    "nprobe": 32,
    "metric": "IP",  # Cosine via normalized embeddings
    "expected_vectors": 5_000,
}
"""Configuration for H2 BOK FAISS index."""


O2_BOK_INDEX_CONFIG = {
    "name": "o2_bok_v1",
    "dimension": 768,  # Nomic embeddings
    "index_type": "IVF256,Flat",
    "nprobe": 32,
    "metric": "IP",  # Cosine via normalized embeddings
    "expected_vectors": 8_000,
}
"""Configuration for O2 BOK FAISS index."""


# ---------------------------------------------------------------------------
# Embedding Text Generation
# ---------------------------------------------------------------------------


def create_embedding_text(record: CompatibilityRecord) -> str:
    """Generate text for embedding from a CompatibilityRecord.

    The embedding text is used for semantic search only - compatibility
    decisions use validated fields, not text matching.

    Args:
        record: CompatibilityRecord to embed

    Returns:
        Text string for embedding generation
    """
    env = record.environment

    # Build property text
    prop_parts = []
    for p in record.properties:
        prop_parts.append(f"{p.property_key.value} {p.get_display_value()}")
    prop_text = " ".join(prop_parts)

    # Build envelope text with null handling
    temp_text = (
        f"temp {env.temp_min_f} to {env.temp_max_f} F"
        if env.temp_min_f is not None
        else "temp unknown"
    )
    pressure_text = (
        f"pressure {env.pressure_min_psia} to {env.pressure_max_psia} psia"
        if env.pressure_min_psia is not None
        else "pressure unknown"
    )
    conc_text = (
        f"concentration {env.concentration_pct} pct"
        if env.concentration_pct is not None
        else ""
    )

    # Assemble embedding text
    text = (
        f"{record.material_name} "
        f"material_key {record.material_key} "
        f"{record.gas_type.value} service "
        f"{temp_text} "
        f"{pressure_text} "
        f"phase {env.phase.value} "
        f"{conc_text} "
        f"compatibility {record.compatibility.value} "
        f"reason {record.reason} "
        f"mitigation {record.mitigation or ''} "
        f"{prop_text}"
    ).strip()

    # Clean up multiple spaces
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Embedding Normalization
# ---------------------------------------------------------------------------


def normalize_embedding(vec: List[float]) -> List[float]:
    """L2-normalize embedding for cosine similarity via inner product.

    CRITICAL: Both stored vectors AND query vectors MUST be normalized.
    Normalize BEFORE insertion, not after storage.

    Args:
        vec: Raw embedding vector

    Returns:
        Normalized embedding vector

    Raises:
        ValueError: If vector has zero norm
    """
    v = np.array(vec, dtype=float)
    n = float(np.linalg.norm(v))

    if n < 1e-10:
        raise ValueError("Zero-norm embedding cannot be normalized")

    out = (v / n).tolist()

    # CI assertion - verify normalization
    result_norm = float(np.linalg.norm(out))
    assert abs(result_norm - 1.0) < 1e-6, f"Normalization failed: norm={result_norm}"

    return out


# ---------------------------------------------------------------------------
# FAISS Index Builder
# ---------------------------------------------------------------------------


class TwinIndexBuilder:
    """Builds FAISS twin indices for H2/O2 BOK.

    Handles:
    - Embedding generation (via provided embedding function)
    - Normalization (BEFORE insertion)
    - FAISS index creation (IVF256,Flat with IP metric)
    - PostgreSQL mapping storage (faiss_id -> record_id)
    """

    def __init__(
        self,
        gas_type: GasType,
        output_dir: Path,
        embed_fn: Optional[callable] = None,
    ) -> None:
        """Initialize index builder.

        Args:
            gas_type: H2 or O2
            output_dir: Directory for index files
            embed_fn: Function to generate embeddings (text -> List[float])
        """
        self.gas_type = gas_type
        self.output_dir = Path(output_dir)
        self.embed_fn = embed_fn

        # Select config based on gas type
        self.config = (
            H2_BOK_INDEX_CONFIG if gas_type == GasType.H2 else O2_BOK_INDEX_CONFIG
        )

        self._records: List[CompatibilityRecord] = []
        self._embeddings: List[List[float]] = []
        self._record_ids: List[str] = []

    def add_record(self, record: CompatibilityRecord) -> None:
        """Add a record to the index.

        Args:
            record: CompatibilityRecord to add

        Raises:
            ValueError: If record gas_type doesn't match builder
        """
        if record.gas_type != self.gas_type:
            raise ValueError(
                f"Record gas_type {record.gas_type} doesn't match "
                f"builder gas_type {self.gas_type}"
            )

        self._records.append(record)
        self._record_ids.append(record.record_id)

    def add_records(self, records: List[CompatibilityRecord]) -> None:
        """Add multiple records to the index.

        Args:
            records: List of CompatibilityRecords to add
        """
        for record in records:
            self.add_record(record)

    def build_embeddings(self) -> None:
        """Generate embeddings for all added records.

        Uses the provided embed_fn to generate embeddings, then normalizes.
        """
        if self.embed_fn is None:
            raise ValueError("embed_fn must be provided to generate embeddings")

        logger.info(f"Generating embeddings for {len(self._records)} records...")

        self._embeddings = []
        for i, record in enumerate(self._records):
            text = create_embedding_text(record)
            raw_embedding = self.embed_fn(text)

            # CRITICAL: Normalize BEFORE storage
            normalized = normalize_embedding(raw_embedding)
            self._embeddings.append(normalized)

            if (i + 1) % 100 == 0:
                logger.info(f"Generated {i + 1}/{len(self._records)} embeddings")

        logger.info(f"Generated {len(self._embeddings)} embeddings")

    def set_embeddings(self, embeddings: List[List[float]]) -> None:
        """Set pre-computed embeddings.

        Args:
            embeddings: List of normalized embeddings (must match record count)
        """
        if len(embeddings) != len(self._records):
            raise ValueError(
                f"Embedding count ({len(embeddings)}) doesn't match "
                f"record count ({len(self._records)})"
            )

        # Verify normalization
        for i, emb in enumerate(embeddings):
            norm = float(np.linalg.norm(emb))
            if abs(norm - 1.0) > 0.01:
                raise ValueError(
                    f"Embedding {i} is not normalized (norm={norm})"
                )

        self._embeddings = embeddings

    def build_index(self) -> Tuple[Any, Dict[int, str]]:
        """Build the FAISS index.

        Returns:
            Tuple of (faiss_index, faiss_id_to_record_id_map)
        """
        try:
            import faiss
        except ImportError:
            raise ImportError(
                "FAISS is required for index building. "
                "Install with: pip install faiss-cpu"
            )

        if not self._embeddings:
            raise ValueError("No embeddings available. Call build_embeddings() first.")

        dimension = self.config["dimension"]
        n_vectors = len(self._embeddings)

        logger.info(
            f"Building {self.config['name']} index: "
            f"{n_vectors} vectors, {dimension} dimensions"
        )

        # Convert to numpy array
        vectors = np.array(self._embeddings, dtype=np.float32)

        # Create index based on config
        if "IVF" in self.config["index_type"]:
            # IVF index needs training
            n_clusters = int(self.config["index_type"].split(",")[0].replace("IVF", ""))
            n_clusters = min(n_clusters, n_vectors)  # Can't have more clusters than vectors

            # Create quantizer
            quantizer = faiss.IndexFlatIP(dimension)

            # Create IVF index
            index = faiss.IndexIVFFlat(
                quantizer,
                dimension,
                n_clusters,
                faiss.METRIC_INNER_PRODUCT,
            )

            # Train index
            logger.info(f"Training index with {n_clusters} clusters...")
            index.train(vectors)

            # Add vectors
            index.add(vectors)

            # Set nprobe
            index.nprobe = self.config["nprobe"]
        else:
            # Flat index (no training needed)
            index = faiss.IndexFlatIP(dimension)
            index.add(vectors)

        # Build mapping
        faiss_id_map = {i: self._record_ids[i] for i in range(n_vectors)}

        logger.info(f"Index built: {index.ntotal} vectors")

        return index, faiss_id_map

    def save(self) -> Tuple[Path, Path, Path]:
        """Build and save the index to disk.

        Returns:
            Tuple of (index_path, metadata_path, mapping_path)
        """
        try:
            import faiss
        except ImportError:
            raise ImportError(
                "FAISS is required for index building. "
                "Install with: pip install faiss-cpu"
            )

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Build index
        index, faiss_id_map = self.build_index()

        # Define paths
        index_name = self.config["name"]
        index_path = self.output_dir / f"{index_name}.faiss"
        metadata_path = self.output_dir / f"{index_name}_metadata.json"
        mapping_path = self.output_dir / f"{index_name}_mapping.json"

        # Save FAISS index
        faiss.write_index(index, str(index_path))
        logger.info(f"Saved index to {index_path}")

        # Save metadata (records as JSON)
        metadata = {
            "config": self.config,
            "record_count": len(self._records),
            "records": [r.model_dump() for r in self._records],
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        logger.info(f"Saved metadata to {metadata_path}")

        # Save mapping
        with open(mapping_path, "w") as f:
            json.dump(faiss_id_map, f, indent=2)
        logger.info(f"Saved mapping to {mapping_path}")

        return index_path, metadata_path, mapping_path


# ---------------------------------------------------------------------------
# FAISS Index Searcher
# ---------------------------------------------------------------------------


class TwinIndexSearcher:
    """Search FAISS twin indices for compatibility records.

    Handles:
    - Query embedding generation and normalization
    - FAISS search with configurable top_k
    - Record retrieval via faiss_id -> record_id mapping
    """

    def __init__(
        self,
        index_path: Path,
        metadata_path: Path,
        mapping_path: Path,
        embed_fn: Optional[callable] = None,
    ) -> None:
        """Initialize index searcher.

        Args:
            index_path: Path to FAISS index file
            metadata_path: Path to metadata JSON file
            mapping_path: Path to mapping JSON file
            embed_fn: Function to generate embeddings (text -> List[float])
        """
        try:
            import faiss
        except ImportError:
            raise ImportError(
                "FAISS is required for searching. "
                "Install with: pip install faiss-cpu"
            )

        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.mapping_path = Path(mapping_path)
        self.embed_fn = embed_fn

        # Load FAISS index
        self._index = faiss.read_index(str(self.index_path))
        logger.info(f"Loaded index with {self._index.ntotal} vectors")

        # Load metadata
        with open(self.metadata_path, "r") as f:
            self._metadata = json.load(f)

        # Load mapping
        with open(self.mapping_path, "r") as f:
            self._mapping = json.load(f)

        # Build record lookup
        self._records_by_id: Dict[str, CompatibilityRecord] = {}
        for record_dict in self._metadata.get("records", []):
            try:
                record = CompatibilityRecord.model_validate(record_dict)
                self._records_by_id[record.record_id] = record
            except Exception as e:
                logger.warning(f"Failed to load record: {e}")

    @property
    def config(self) -> Dict[str, Any]:
        """Get index configuration."""
        return self._metadata.get("config", {})

    @property
    def record_count(self) -> int:
        """Get number of records in index."""
        return len(self._records_by_id)

    def search(
        self,
        query_text: str,
        top_k: int = 10,
    ) -> List[Tuple[CompatibilityRecord, float]]:
        """Search for matching records.

        Args:
            query_text: Query text to embed and search
            top_k: Number of results to return

        Returns:
            List of (record, score) tuples sorted by score descending
        """
        if self.embed_fn is None:
            raise ValueError("embed_fn must be provided for searching")

        # Generate and normalize query embedding
        raw_embedding = self.embed_fn(query_text)
        normalized = normalize_embedding(raw_embedding)
        query_vector = np.array([normalized], dtype=np.float32)

        # Search
        scores, indices = self._index.search(query_vector, top_k)

        # Retrieve records
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue  # FAISS returns -1 for no match

            record_id = self._mapping.get(str(idx))
            if record_id and record_id in self._records_by_id:
                record = self._records_by_id[record_id]
                results.append((record, float(score)))

        return results

    def search_by_material(
        self,
        material_key: str,
        environment_text: str = "",
        top_k: int = 10,
    ) -> List[Tuple[CompatibilityRecord, float]]:
        """Search for records by material key.

        Args:
            material_key: Canonical material identifier
            environment_text: Optional environment description
            top_k: Number of results to return

        Returns:
            List of (record, score) tuples sorted by score descending
        """
        query = f"material_key {material_key} {environment_text}".strip()
        return self.search(query, top_k)

    def get_record_by_id(self, record_id: str) -> Optional[CompatibilityRecord]:
        """Get a record by ID.

        Args:
            record_id: Record identifier

        Returns:
            CompatibilityRecord or None if not found
        """
        return self._records_by_id.get(record_id)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def build_h2_index(
    records: List[CompatibilityRecord],
    output_dir: Path,
    embed_fn: callable,
) -> Tuple[Path, Path, Path]:
    """Build H2 BOK index from records.

    Args:
        records: List of H2 compatibility records
        output_dir: Directory for index files
        embed_fn: Embedding function

    Returns:
        Tuple of (index_path, metadata_path, mapping_path)
    """
    builder = TwinIndexBuilder(GasType.H2, output_dir, embed_fn)
    builder.add_records(records)
    builder.build_embeddings()
    return builder.save()


def build_o2_index(
    records: List[CompatibilityRecord],
    output_dir: Path,
    embed_fn: callable,
) -> Tuple[Path, Path, Path]:
    """Build O2 BOK index from records.

    Args:
        records: List of O2 compatibility records
        output_dir: Directory for index files
        embed_fn: Embedding function

    Returns:
        Tuple of (index_path, metadata_path, mapping_path)
    """
    builder = TwinIndexBuilder(GasType.O2, output_dir, embed_fn)
    builder.add_records(records)
    builder.build_embeddings()
    return builder.save()
