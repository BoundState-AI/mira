#!/usr/bin/env python3
"""
Module: Semantic Search
Purpose: Unified Semantic Search Module for MIRA

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path
import json
import logging
import os

import numpy as np

# -----------------------------------------------------------------------------
# Optional deps
# -----------------------------------------------------------------------------
try:
    import faiss  # type: ignore
    FAISS_AVAILABLE = True
except ImportError:  # pragma: no cover - env dependent
    FAISS_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    TRANSFORMERS_AVAILABLE = True
except ImportError:  # pragma: no cover - env dependent
    TRANSFORMERS_AVAILABLE = False

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    # Default console handler if not configured by app
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------------
# Data models
# -----------------------------------------------------------------------------
@dataclass
class SearchResult:
    """
    A single search result from semantic search.

    Attributes:
        doc_id: Unique document identifier
        content: Document text content
        metadata: Document metadata (source, section, etc.)
        score: Similarity score (0.0-1.0, higher is better)
        source_index: Which index this came from (standards_idx, applications_idx, material_cards_idx)
        rank: Rank within the source index (0-based within that index's results)
    """
    doc_id: str
    content: str
    metadata: Dict[str, Any]
    score: float
    source_index: str
    rank: int

    def __repr__(self) -> str:
        return (
            f"SearchResult(doc_id='{self.doc_id}', "
            f"score={self.score:.3f}, "
            f"source='{self.source_index}', "
            f"rank={self.rank})"
        )


@dataclass
class MultiIndexSearchResults:
    """
    Combined results from searching across multiple indexes.

    Attributes:
        query: The original query text
        results_by_index: Results organized by source index
        merged_results: All results merged and sorted by score
        num_results_per_index: Number of results from each index
    """
    query: str
    results_by_index: Dict[str, List[SearchResult]]
    merged_results: List[SearchResult]
    num_results_per_index: Dict[str, int]

    def get_top_k(self, k: int = 10) -> List[SearchResult]:
        """Get top-K results across all indexes."""
        return self.merged_results[:k]

    def get_top_k_per_index(self, k: int = 5) -> Dict[str, List[SearchResult]]:
        """Get top-K results from each index separately."""
        return {
            index_name: results[:k]
            for index_name, results in self.results_by_index.items()
        }

    def __repr__(self) -> str:
        return (
            f"MultiIndexSearchResults(query='{self.query}', "
            f"total_results={len(self.merged_results)}, "
            f"by_index={self.num_results_per_index})"
        )


# -----------------------------------------------------------------------------
# Unified Semantic Search
# -----------------------------------------------------------------------------
class UnifiedSemanticSearch:
    """
    Unified semantic search across three FAISS indexes.

    This class manages loading and querying three separate FAISS indexes:

      - standards_idx: BOK standards sections
      - applications_idx: Material Use Applications (MUAs)
      - material_cards_idx: Material reference cards

    All indexes use all-MiniLM-L6-v2 embeddings (384 dimensions).
    """

    # Actual FAISS index names (matching data/faiss_indexes/)
    INDEX_NAMES = ["bok", "mua", "maptis"]

    # Friendly names for display/logging
    INDEX_DISPLAY_NAMES = {
        "bok": "BOK Standards",
        "mua": "MUA Precedents",
        "maptis": "MAPTIS Material/Test Data"
    }

    EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384

    def __init__(self, index_dir: Optional[Path] = None):
        """
        Initialize the unified semantic search.

        Args:
            index_dir: Directory containing FAISS index files (.faiss and .json)
                       If None, uses env var MIRA_INDEX_DIR or './indexes'
        """
        if index_dir is None:
            env_dir = os.getenv("MIRA_INDEX_DIR", "data/faiss_indexes")
            index_dir = Path(env_dir)

        self.index_dir = Path(index_dir)

        # Storage for loaded indexes
        self.indexes: Dict[str, Any] = {}          # index_name -> faiss.Index
        self.documents: Dict[str, List[Dict]] = {} # index_name -> list of documents
        self.doc_id_to_idx: Dict[str, Dict[str, int]] = {}  # index_name -> {doc_id -> pos}

        # Encoder for query embeddings
        self.encoder: Optional[Any] = None

        # Stats
        self.stats: Dict[str, Any] = {
            "loaded_indexes": [],
            "total_documents": 0,
            "documents_per_index": {},
        }

        logger.info(f"UnifiedSemanticSearch initialized with index_dir={self.index_dir}")

    # -------------------------------------------------------------------------
    # Factory
    # -------------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "UnifiedSemanticSearch":
        """
        Convenience constructor that honors MIRA_INDEX_DIR.
        """
        return cls(index_dir=None)

    # -------------------------------------------------------------------------
    # Encoder
    # -------------------------------------------------------------------------
    def load_encoder(self, model_name: str = EMBEDDING_MODEL) -> None:
        """
        Load the sentence transformer encoder.

        Args:
            model_name: Name of the sentence-transformers model to use
        """
        if not TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "sentence-transformers not available. "
                "Install with: pip install sentence-transformers"
            )

        if self.encoder is not None:
            return

        logger.info(f"Loading encoder: {model_name}")
        self.encoder = SentenceTransformer(model_name)
        dim = self.encoder.get_sentence_embedding_dimension()
        if dim != self.EMBEDDING_DIM:
            logger.warning(
                f"Encoder dimension {dim} != expected {self.EMBEDDING_DIM}. "
                "Make sure all FAISS indexes use the same embedding model."
            )
        logger.info("Encoder loaded.")

    # -------------------------------------------------------------------------
    # Index loading
    # -------------------------------------------------------------------------
    def load_index(self, index_name: str, documents_path: Optional[Path] = None) -> bool:
        """
        Load a FAISS index and its associated documents.

        Args:
            index_name: Name of the index (e.g., 'standards_idx')
            documents_path: Optional path to documents JSON file.
                            If None, looks for {index_name}.json in index_dir

        Returns:
            True if successful, False otherwise
        """
        if not FAISS_AVAILABLE:
            raise RuntimeError(
                "faiss not available. Install with: pip install faiss-cpu"
            )

        # Use actual file naming convention: {name}_faiss_index.bin
        index_path = self.index_dir / f"{index_name}_faiss_index.bin"
        if documents_path is None:
            documents_path = self.index_dir / f"{index_name}_index_metadata.json"

        if not index_path.exists():
            logger.warning(f"Index file not found: {index_path}")
            return False

        if not documents_path.exists():
            logger.warning(f"Documents file not found: {documents_path}")
            return False

        # Load index
        try:
            logger.info(f"Loading FAISS index: {index_path}")
            index = faiss.read_index(str(index_path))
            self.indexes[index_name] = index
            logger.info(
                f"Loaded index '{index_name}' with {index.ntotal} vectors "
                f"(dimension={index.d})"
            )
        except Exception as e:  # pragma: no cover - I/O failure path
            logger.exception(f"Error loading FAISS index '{index_name}': {e}")
            return False

        # Load documents
        try:
            logger.info(f"Loading documents for '{index_name}': {documents_path}")
            with open(documents_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Handle our metadata structure: source_metadata.{sections|muas|metadata}
            documents = None
            if isinstance(data, dict):
                if "source_metadata" in data:
                    # Our format: source_metadata.sections (BOK), source_metadata.muas (MUA), source_metadata.metadata (MAPTIS)
                    source_meta = data["source_metadata"]
                    if "sections" in source_meta:
                        documents = source_meta["sections"]
                    elif "muas" in source_meta:
                        documents = source_meta["muas"]
                    elif "metadata" in source_meta:
                        documents = source_meta["metadata"]
                elif "documents" in data:
                    documents = data["documents"]
                elif "metadata" in data:
                    # MAPTIS uses top-level metadata array
                    documents = data["metadata"]
            elif isinstance(data, list):
                documents = data

            if not documents or not isinstance(documents, list):
                raise ValueError(f"Could not find documents in metadata JSON for '{index_name}'")

            self.documents[index_name] = documents
            logger.info(f"Loaded {len(documents)} documents for '{index_name}'")

            # Build doc_id map
            doc_id_map: Dict[str, int] = {}
            for idx, doc in enumerate(documents):
                doc_id = doc.get("doc_id", doc.get("id", str(idx)))
                doc_id_map[doc_id] = idx

            self.doc_id_to_idx[index_name] = doc_id_map

        except Exception as e:  # pragma: no cover - I/O failure path
            logger.exception(f"Error loading documents for '{index_name}': {e}")
            return False

        # Update stats
        self.stats["loaded_indexes"].append(index_name)
        self.stats["documents_per_index"][index_name] = len(documents)
        self.stats["total_documents"] = sum(
            self.stats["documents_per_index"].values()
        )

        return True

    def load_all_indexes(self) -> Dict[str, bool]:
        """
        Load all known FAISS indexes (if present).

        Returns:
            Dict[index_name, bool] indicating success per index.
        """
        results: Dict[str, bool] = {}
        for index_name in self.INDEX_NAMES:
            results[index_name] = self.load_index(index_name)

        # If any index loaded, ensure encoder is available
        if any(results.values()):
            self.load_encoder()

        logger.info(f"Index load summary: {results}")
        return results

    # -------------------------------------------------------------------------
    # Embeddings
    # -------------------------------------------------------------------------
    def encode_query(self, query: str) -> np.ndarray:
        """
        Encode a query string to an embedding vector.

        Args:
            query: Natural language query

        Returns:
            Embedding vector as numpy array of shape [1, EMBEDDING_DIM]
        """
        if self.encoder is None:
            raise RuntimeError(
                "Encoder not loaded. Call load_encoder() or load_all_indexes() first."
            )

        embedding = self.encoder.encode(query)
        if len(getattr(embedding, "shape", [])) == 1:
            embedding = embedding.reshape(1, -1)

        return np.asarray(embedding, dtype="float32")

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------
    def search_index(
        self,
        index_name: str,
        query: Optional[str] = None,
        top_k: int = 10,
        metadata_filter: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[np.ndarray] = None,
    ) -> List[SearchResult]:
        """
        Search a single FAISS index.

        Args:
            index_name: Name of the index to search
            query: Query text (optional if query_embedding provided)
            top_k: Number of results to return
            metadata_filter: Optional metadata filter criteria
            query_embedding: Precomputed query embedding (preferred for multi-index calls)

        Returns:
            List of SearchResult objects.
        """
        if index_name not in self.indexes:
            logger.warning(f"Index '{index_name}' not loaded")
            return []

        if query_embedding is None:
            if query is None:
                raise ValueError("Either query or query_embedding must be provided")
            query_embedding = self.encode_query(query)

        faiss_index = self.indexes[index_name]
        documents = self.documents[index_name]

        # If filtering, ask FAISS for more hits as a buffer
        search_k = max(top_k, 1)
        if metadata_filter:
            search_k = max(top_k * 3, top_k)  # more candidates to survive filters

        distances, indices = faiss_index.search(query_embedding, search_k)

        # Convert L2 distance → similarity in [0, 1)
        similarities = 1.0 / (1.0 + distances[0])

        results: List[SearchResult] = []
        for rank, (idx, score) in enumerate(zip(indices[0], similarities)):
            if idx < 0 or idx >= len(documents):
                continue

            doc = documents[idx]

            # BOK uses flat metadata structure (no nested "metadata" field)
            # MUA and MAPTIS use nested structure
            if index_name == "bok":
                # For BOK, the entire document IS the metadata
                meta = doc
            else:
                # For MUA/MAPTIS, metadata is nested
                meta = doc.get("metadata", {})

            if metadata_filter and not self._matches_filter(meta, metadata_filter):
                continue

            # Extract actual database ID from metadata based on index type
            # FIX: FAISS metadata stores array indices as doc_id, but we need database UUIDs
            # Always return string to ensure compatibility with content fetchers
            if index_name == "bok":
                # BOK uses section_id as the database UUID
                doc_id = str(doc.get("section_id", doc.get("doc_id", str(idx))))
            elif index_name == "mua":
                # MUA uses mua_id as the database ID (integer from mua_normalized)
                doc_id = str(doc.get("mua_id", doc.get("doc_id", str(idx))))
            elif index_name == "maptis":
                # MAPTIS uses row_uid as the database UUID
                doc_id = str(doc.get("row_uid", doc.get("doc_id", str(idx))))
            else:
                # Fallback for unknown indexes
                doc_id = str(doc.get("doc_id", doc.get("id", str(idx))))

            result = SearchResult(
                doc_id=doc_id,  # Now contains actual database UUID
                content=doc.get("content", doc.get("text", "")),
                metadata=meta,
                score=float(score),
                source_index=index_name,
                rank=rank,
            )
            results.append(result)

            if len(results) >= top_k:
                break

        return results

    def search_all(
        self,
        query: str,
        top_k_per_index: int = 10,
        metadata_filters: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> MultiIndexSearchResults:
        """
        Search across all loaded FAISS indexes.

        Args:
            query: Natural language query
            top_k_per_index: Number of results to retrieve from each index
            metadata_filters: Optional per-index filters, e.g.:
                              {'standards_idx': {'source': 'JSC-27301F'}}

        Returns:
            MultiIndexSearchResults with merged + per-index results.
        """
        if metadata_filters is None:
            metadata_filters = {}

        if not self.stats["loaded_indexes"]:
            logger.warning("No FAISS indexes loaded; returning empty results.")
            return MultiIndexSearchResults(
                query=query,
                results_by_index={},
                merged_results=[],
                num_results_per_index={},
            )

        # Encode query once
        query_embedding = self.encode_query(query)

        results_by_index: Dict[str, List[SearchResult]] = {}
        for index_name in self.stats["loaded_indexes"]:
            filter_criteria = metadata_filters.get(index_name)
            results = self.search_index(
                index_name=index_name,
                query=query,
                top_k=top_k_per_index,
                metadata_filter=filter_criteria,
                query_embedding=query_embedding,
            )
            results_by_index[index_name] = results

        merged_results = self._merge_and_rank_results(results_by_index)

        num_results_per_index = {
            index_name: len(results)
            for index_name, results in results_by_index.items()
        }

        return MultiIndexSearchResults(
            query=query,
            results_by_index=results_by_index,
            merged_results=merged_results,
            num_results_per_index=num_results_per_index,
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _merge_and_rank_results(
        self, results_by_index: Dict[str, List[SearchResult]]
    ) -> List[SearchResult]:
        """
        Merge results from multiple indexes and rank by similarity score.
        """
        all_results: List[SearchResult] = []
        for res in results_by_index.values():
            all_results.extend(res)

        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results

    def _matches_filter(self, metadata: Dict[str, Any], filter_criteria: Dict[str, Any]) -> bool:
        """
        Check if document metadata matches filter criteria.

        Supports:
          - scalar == scalar
          - scalar ∈ list
          - list ∩ list (any overlap)
          - string substring matches
        """
        for key, value in filter_criteria.items():
            if key not in metadata:
                return False

            meta_value = metadata[key]

            # Normalize to lists for simpler logic
            meta_list = meta_value if isinstance(meta_value, list) else [meta_value]
            filter_list = value if isinstance(value, list) else [value]

            matched = False
            for fv in filter_list:
                for mv in meta_list:
                    # If filter is a string, do substring compare
                    if isinstance(fv, str):
                        if fv.lower() in str(mv).lower():
                            matched = True
                            break
                    else:
                        # Non-string: exact match
                        if mv == fv:
                            matched = True
                            break
                if matched:
                    break

            if not matched:
                return False

        return True

    # -------------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------------
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about loaded indexes and encoder.

        Returns:
            Dict with stats suitable for logging or debugging.
        """
        stats = {
            "loaded_indexes": list(self.stats["loaded_indexes"]),
            "total_documents": self.stats["total_documents"],
            "documents_per_index": dict(self.stats["documents_per_index"]),
            "encoder_model": self.EMBEDDING_MODEL if self.encoder else None,
            "embedding_dimension": self.EMBEDDING_DIM,
        }

        index_details: Dict[str, Any] = {}
        for index_name in self.stats["loaded_indexes"]:
            idx = self.indexes.get(index_name)
            if idx is not None:
                index_details[index_name] = {
                    "ntotal": idx.ntotal,
                    "dimension": idx.d,
                    "is_trained": bool(getattr(idx, "is_trained", True)),
                }
        stats["index_details"] = index_details
        return stats

    def log_statistics(self) -> None:
        """Log statistics at INFO level."""
        stats = self.get_statistics()
        logger.info("UnifiedSemanticSearch statistics:")
        logger.info(f"  Encoder: {stats['encoder_model']}")
        logger.info(f"  Embedding dimension: {stats['embedding_dimension']}")
        logger.info(f"  Total documents: {stats['total_documents']}")
        logger.info(f"  Loaded indexes: {stats['loaded_indexes']}")
        for name, count in stats["documents_per_index"].items():
            logger.info(f"    - {name}: {count} docs")
        for name, details in stats["index_details"].items():
            logger.info(
                f"    - {name}: vectors={details['ntotal']}, "
                f"dim={details['dimension']}, trained={details['is_trained']}"
            )


# -----------------------------------------------------------------------------
# Example harness (dev only)
# -----------------------------------------------------------------------------
def _create_example_indexes(output_dir: Path) -> None:
    """
    Create example FAISS indexes for local testing ONLY.

    This seeds small in-memory examples for:
      - standards_idx
      - applications_idx
      - material_cards_idx
    """
    if not (FAISS_AVAILABLE and TRANSFORMERS_AVAILABLE):
        logger.error("faiss and sentence-transformers required to create example indexes")
        return

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Creating example FAISS indexes in {output_dir}...")

    encoder = SentenceTransformer(UnifiedSemanticSearch.EMBEDDING_MODEL)
    dim = encoder.get_sentence_embedding_dimension()

    # 1. standards_idx
    standards_docs = [
        {
            "doc_id": "jsc_27301f_5_1_4",
            "content": (
                "JSC-27301F Section 5.1.4 - Materials Selection for Oxygen Systems\n\n"
                "Aluminum alloys are highly flammable in oxygen-enriched atmospheres. "
                "Restrictions: Aluminum valves shall not be used above 100 psia in GOX service. "
                "Aluminum pressure vessels approved up to 3,000 psia with proper design."
            ),
            "metadata": {
                "source": "JSC-27301F",
                "section": "5.1.4",
                "title": "Materials Selection for Oxygen Systems",
                "document_type": "standard",
                "applies_env": ["oxygen", "gox"],
                "applies_system": ["valve", "pressure_vessel"],
            },
        },
        {
            "doc_id": "nasa_std_6001b_4_5",
            "content": (
                "NASA-STD-6001B Section 4.5 - Flammability Requirements\n\n"
                "Materials in oxygen systems shall be evaluated for flammability. "
                "Approved metals include stainless steel 316, Monel 400, Inconel 718. "
                "Titanium alloys prohibited above 200 psi due to flammability."
            ),
            "metadata": {
                "source": "NASA-STD-6001B",
                "section": "4.5",
                "title": "Flammability Requirements",
                "document_type": "standard",
                "applies_env": ["oxygen"],
                "applies_family": ["metal"],
            },
        },
    ]
    texts = [d["content"] for d in standards_docs]
    emb = encoder.encode(texts, show_progress_bar=False)
    standards_index = faiss.IndexFlatL2(dim)
    standards_index.add(np.asarray(emb, dtype="float32"))
    faiss.write_index(standards_index, str(output_dir / "standards_idx.faiss"))
    with open(output_dir / "standards_idx.json", "w", encoding="utf-8") as f:
        json.dump({"documents": standards_docs}, f, indent=2)

    # 2. applications_idx (MUAs)
    applications_docs = [
        {
            "doc_id": "mua_2024_001",
            "content": (
                "Viton A Fluoroelastomer used as valve_seat in oxygen gas "
                "at 3000 psia, -40 to 150°C. Status: approved. "
                "Rationale: Passed O2 compatibility testing per ASTM G63."
            ),
            "metadata": {
                "mua_number": "MUA-2024-001",
                "material": "Viton A Fluoroelastomer",
                "system_type": "valve_seat",
                "environment": "oxygen",
                "phase": "gas",
                "pressure_max_psia": 3000,
                "approval_status": "approved",
            },
        },
        {
            "doc_id": "mua_2024_002",
            "content": (
                "Stainless Steel 316 used as pressure_vessel in oxygen gas "
                "at 5000 psia, -65 to 200°C. Status: approved. "
                "Rationale: Standard material for high-pressure oxygen systems."
            ),
            "metadata": {
                "mua_number": "MUA-2024-002",
                "material": "Stainless Steel 316",
                "system_type": "pressure_vessel",
                "environment": "oxygen",
                "phase": "gas",
                "pressure_max_psia": 5000,
                "approval_status": "approved",
            },
        },
    ]
    texts = [d["content"] for d in applications_docs]
    emb = encoder.encode(texts, show_progress_bar=False)
    applications_index = faiss.IndexFlatL2(dim)
    applications_index.add(np.asarray(emb, dtype="float32"))
    faiss.write_index(applications_index, str(output_dir / "applications_idx.faiss"))
    with open(output_dir / "applications_idx.json", "w", encoding="utf-8") as f:
        json.dump({"documents": applications_docs}, f, indent=2)

    # 3. material_cards_idx
    material_cards_docs = [
        {
            "doc_id": "mat_ss316",
            "content": (
                "Stainless Steel 316 (ASTM A240)\n"
                "Family: stainless_steel, Form: sheet\n"
                "Test Summary: Rated A for O2 compatibility, A for flammability, "
                "approved for all oxygen pressures.\nPFAS: No"
            ),
            "metadata": {
                "material_id": "mat_ss316",
                "name": "Stainless Steel 316",
                "spec_number": "ASTM A240",
                "family": "stainless_steel",
                "form": "sheet",
                "contains_pfas": False,
            },
        },
    ]
    texts = [d["content"] for d in material_cards_docs]
    emb = encoder.encode(texts, show_progress_bar=False)
    material_cards_index = faiss.IndexFlatL2(dim)
    material_cards_index.add(np.asarray(emb, dtype="float32"))
    faiss.write_index(material_cards_index, str(output_dir / "material_cards_idx.faiss"))
    with open(output_dir / "material_cards_idx.json", "w", encoding="utf-8") as f:
        json.dump({"documents": material_cards_docs}, f, indent=2)

    logger.info("Example indexes created.")


def _example_usage() -> None:
    """
    Local/dev usage example.

    Run:
        python semantic_search.py

    This will:
      - create example indexes if none exist
      - run a few demo queries
      - print results to stdout
    """
    index_dir = Path("./indexes")
    if not (index_dir / "standards_idx.faiss").exists():
        _create_example_indexes(index_dir)

    search = UnifiedSemanticSearch(index_dir=index_dir)
    search.load_all_indexes()
    search.log_statistics()

    queries = [
        "aluminum oxygen compatibility pressure limits",
        "fluoroelastomer O-ring valve seat oxygen",
        "stainless steel oxygen service high pressure",
    ]

    for q in queries:
        print("\n" + "=" * 80)
        print(f"QUERY: {q}")
        print("=" * 80)
        results = search.search_all(q, top_k_per_index=3)
        print(results)
        print("\nTop-5 merged results:")
        for i, r in enumerate(results.get_top_k(5), 1):
            snippet = r.content[:120] + "..." if len(r.content) > 120 else r.content
            print(f"{i}. [{r.source_index}] {r.doc_id} (score={r.score:.4f})")
            print(f"   {snippet}")


if __name__ == "__main__":
    _example_usage()
