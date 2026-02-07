#!/usr/bin/env python3
"""
Module: Image Search
Purpose: Hybrid image search engine combining CLIP similarity, OCR text, and entity validation.

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

from typing import List, Dict, Any, Optional, Union
import numpy as np
import json
import logging
from pathlib import Path
import time

# CLIP for text embeddings
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("ERROR: sentence-transformers not installed. Run: pip install sentence-transformers")
    exit(1)

# FAISS for vector search
try:
    import faiss
except ImportError:
    print("ERROR: faiss not installed. Run: pip install faiss-cpu (or faiss-gpu)")
    exit(1)

logger = logging.getLogger(__name__)

class ImageSearchEngine:
    """
    Hybrid image search engine combining CLIP similarity, OCR text, and entity validation.

    Uses weighted scoring to balance:
    - Visual similarity (CLIP text→image)
    - OCR text matching (semantic similarity)
    - Validated entity matches (part numbers, standards, etc.)
    """

    def __init__(self,
                 image_index_dir: str,
                 ocr_store_path: Optional[str] = None,
                 model_name: str = "clip-ViT-B-32",
                 alpha: float = 0.6,  # Weight for text→image similarity
                 beta: float = 0.3,   # Weight for query↔OCR text
                 gamma: float = 0.1): # Weight for validated entity boost
        """
        Initialize image search engine.

        Args:
            image_index_dir: Directory containing FAISS index and metadata
            ocr_store_path: Optional path to OCR results JSON
            model_name: CLIP model name (must match index)
            alpha: Weight for visual similarity (text→image)
            beta: Weight for OCR text similarity
            gamma: Weight for entity validation boost
        """
        self.image_index_dir = Path(image_index_dir)
        self.ocr_store_path = ocr_store_path
        self.model_name = model_name
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma

        # Load CLIP model for text embeddings
        logger.info(f"Loading CLIP model: {model_name}")
        self.model = SentenceTransformer(model_name)

        # Load image index
        self._load_image_index()

        # Load OCR store if available
        self._load_ocr_store()

        logger.info(f"ImageSearchEngine initialized: {len(self.image_meta)} images, "
                   f"OCR: {len(self.ocr_store)} entries")

    def _load_image_index(self) -> None:
        """Load FAISS index and metadata."""
        # Load FAISS index
        faiss_path = self.image_index_dir / "image.faiss"
        if not faiss_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {faiss_path}")

        self.faiss_index = faiss.read_index(str(faiss_path))

        # Load metadata
        meta_path = self.image_index_dir / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {meta_path}")

        with open(meta_path, 'r') as f:
            self.image_meta = json.load(f)

        logger.info(f"Loaded image index: {self.faiss_index.ntotal} vectors, {len(self.image_meta)} metadata entries")

    def _load_ocr_store(self) -> None:
        """Load OCR results store."""
        self.ocr_store = {}

        if not self.ocr_store_path:
            logger.info("No OCR store path provided - OCR scoring disabled")
            return

        ocr_path = Path(self.ocr_store_path)
        if not ocr_path.exists():
            logger.info(f"OCR store not found: {ocr_path} - OCR scoring disabled")
            return

        try:
            with open(ocr_path, 'r') as f:
                self.ocr_store = json.load(f)
            logger.info(f"Loaded OCR store: {len(self.ocr_store)} entries")
        except Exception as e:
            logger.error(f"Failed to load OCR store: {e}")
            self.ocr_store = {}

    def _embed_text(self, text: str) -> np.ndarray:
        """
        Generate normalized CLIP text embedding.

        Args:
            text: Input text query

        Returns:
            Normalized embedding vector
        """
        embedding = self.model.encode([text], normalize_embeddings=True)
        return embedding[0].astype("float32")

    def _calculate_visual_similarity(self, query_embedding: np.ndarray, k_oversample: int = 100) -> List[tuple]:
        """
        Calculate visual similarity using CLIP text→image matching.

        Args:
            query_embedding: Query text embedding
            k_oversample: Number of candidates to retrieve for reranking

        Returns:
            List of (index, similarity_score) tuples
        """
        # Search FAISS index
        scores, indices = self.faiss_index.search(
            query_embedding.reshape(1, -1),
            min(k_oversample, self.faiss_index.ntotal)
        )

        # Return as list of tuples
        results = []
        for idx, score in zip(indices[0], scores[0]):
            if idx >= 0:  # Valid index
                results.append((int(idx), float(score)))

        return results

    def _calculate_ocr_similarity(self, query_embedding: np.ndarray, doc_id: str) -> float:
        """
        Calculate similarity between query and OCR text for specific document.

        Args:
            query_embedding: Query text embedding
            doc_id: Document ID to check

        Returns:
            OCR similarity score (0.0 if no OCR available)
        """
        if not self.ocr_store or doc_id not in self.ocr_store:
            return 0.0

        ocr_data = self.ocr_store[doc_id]

        # Use precomputed OCR embedding if available
        if "ocr_vec" in ocr_data and ocr_data["ocr_vec"]:
            ocr_embedding = np.array(ocr_data["ocr_vec"], dtype="float32")
            if ocr_embedding.size > 0:
                # Dot product (both embeddings are normalized)
                return float(np.dot(query_embedding, ocr_embedding))

        # Fallback: compute OCR embedding on-the-fly if text available
        if "ocr_text" in ocr_data and ocr_data["ocr_text"]:
            ocr_text = ocr_data["ocr_text"]
            ocr_embedding = self._embed_text(ocr_text)
            return float(np.dot(query_embedding, ocr_embedding))

        return 0.0

    def _calculate_entity_boost(self, query_entities: List[Dict[str, Any]], doc_id: str) -> float:
        """
        Calculate boost score based on validated entity matches.

        IMPORTANT: Only uses validated entities with validated=True flag.
        No string matching for materials/compositions per BoundState design rules.

        Args:
            query_entities: List of validated entities from query
                           Format: [{"type": "part_number", "norm": "VAT-2-3215", "validated": True}, ...]
            doc_id: Document ID to check

        Returns:
            Entity boost score (0.0 to 1.0)
        """
        if not query_entities or not self.ocr_store or doc_id not in self.ocr_store:
            return 0.0

        # Only use validated entities
        validated_query_entities = [e for e in query_entities if e.get("validated", False)]
        if not validated_query_entities:
            return 0.0

        ocr_data = self.ocr_store[doc_id]
        doc_entities = ocr_data.get("entities", [])

        if not doc_entities:
            return 0.0

        # Build set of (type, normalized_value) tuples for validated entities only
        doc_entity_set = set()
        for entity in doc_entities:
            entity_type = entity.get("type")
            entity_norm = entity.get("norm")
            entity_validated = entity.get("validated", False)

            # Only include validated entities
            if entity_type and entity_norm and entity_validated:
                doc_entity_set.add((entity_type, entity_norm))

        # Count validated matches only
        matches = 0
        for query_entity in validated_query_entities:
            query_type = query_entity.get("type")
            query_norm = query_entity.get("norm")
            if query_type and query_norm:
                if (query_type, query_norm) in doc_entity_set:
                    matches += 1

        # Convert to score (cap at 1.0, give 0.2 per validated match)
        boost_score = min(1.0, 0.2 * matches)
        return boost_score

    def search(self,
               query: str,
               k: int = 24,
               query_entities: Optional[List[Dict[str, Any]]] = None,
               min_score_threshold: float = 0.0,
               class_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Search for images using hybrid scoring.

        Args:
            query: Text query
            k: Number of results to return
            query_entities: Optional validated entities from query
            min_score_threshold: Minimum score threshold
            class_filter: Optional list of image classes to filter by

        Returns:
            List of search results with metadata and scores
        """
        start_time = time.time()

        # Generate query embedding
        query_embedding = self._embed_text(query)

        # Get visual similarity candidates (oversample for reranking)
        k_oversample = min(k * 4, 200)  # Oversample but cap to avoid excessive computation
        visual_candidates = self._calculate_visual_similarity(query_embedding, k_oversample)

        # Hybrid scoring
        scored_results = []

        for idx, visual_score in visual_candidates:
            if idx >= len(self.image_meta):
                continue

            metadata = self.image_meta[idx]
            doc_id = metadata["doc_id"]

            # Apply class filter if specified
            if class_filter:
                image_class = metadata.get("class", "unknown")
                if image_class not in class_filter:
                    continue

            # Calculate component scores
            ocr_score = self._calculate_ocr_similarity(query_embedding, doc_id)
            entity_score = self._calculate_entity_boost(query_entities or [], doc_id)

            # Hybrid score calculation
            hybrid_score = (
                self.alpha * visual_score +
                self.beta * ocr_score +
                self.gamma * entity_score
            )

            # Apply threshold
            if hybrid_score < min_score_threshold:
                continue

            # Build result
            result = {
                "doc_id": doc_id,
                "path": metadata.get("path", ""),
                "filename": metadata.get("filename", ""),
                "title": metadata.get("filename", metadata.get("path", "")),
                "class": metadata.get("class", "unknown"),
                "class_confidence": metadata.get("class_confidence", 0.0),
                "score": hybrid_score,
                "score_breakdown": {
                    "visual": visual_score,
                    "ocr": ocr_score,
                    "entity": entity_score,
                    "weights": {"alpha": self.alpha, "beta": self.beta, "gamma": self.gamma}
                },
                "metadata": metadata
            }

            # Add OCR overlays if available
            if doc_id in self.ocr_store:
                ocr_data = self.ocr_store[doc_id]
                if "bboxes" in ocr_data:
                    result["overlays"] = ocr_data["bboxes"]

            scored_results.append(result)

        # Sort by hybrid score (descending)
        scored_results.sort(key=lambda x: x["score"], reverse=True)

        # Return top k results
        final_results = scored_results[:k]

        # Add search metadata
        search_time = time.time() - start_time
        for result in final_results:
            result["search_metadata"] = {
                "query": query,
                "search_time_ms": round(search_time * 1000, 2),
                "total_candidates": len(visual_candidates),
                "filtered_candidates": len(scored_results),
                "rank": final_results.index(result) + 1
            }

        logger.info(f"Search completed: query='{query}', results={len(final_results)}, "
                   f"time={search_time:.2f}s")

        return final_results

    def search_by_class(self, image_class: str, k: int = 24) -> List[Dict[str, Any]]:
        """
        Search for images by classification.

        Args:
            image_class: Image class to search for
            k: Number of results to return

        Returns:
            List of images matching the class
        """
        results = []

        for metadata in self.image_meta:
            if metadata.get("class") == image_class:
                result = {
                    "doc_id": metadata["doc_id"],
                    "path": metadata.get("path", ""),
                    "filename": metadata.get("filename", ""),
                    "class": metadata.get("class", "unknown"),
                    "class_confidence": metadata.get("class_confidence", 0.0),
                    "metadata": metadata
                }
                results.append(result)

        # Sort by class confidence
        results.sort(key=lambda x: x["class_confidence"], reverse=True)

        return results[:k]

    def get_statistics(self) -> Dict[str, Any]:
        """Get search engine statistics."""
        # Count by class
        class_counts = {}
        for metadata in self.image_meta:
            image_class = metadata.get("class", "unknown")
            class_counts[image_class] = class_counts.get(image_class, 0) + 1

        # OCR coverage
        ocr_coverage = 0
        if self.ocr_store:
            ocr_coverage = len([doc_id for doc_id in self.ocr_store
                               if self.ocr_store[doc_id].get("ocr_text")])

        return {
            "total_images": len(self.image_meta),
            "faiss_index_size": self.faiss_index.ntotal if self.faiss_index else 0,
            "ocr_entries": len(self.ocr_store),
            "ocr_coverage": ocr_coverage,
            "class_distribution": class_counts,
            "search_weights": {
                "alpha": self.alpha,
                "beta": self.beta,
                "gamma": self.gamma
            },
            "model_name": self.model_name
        }

    def update_weights(self, alpha: float, beta: float, gamma: float) -> None:
        """Update scoring weights."""
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        logger.info(f"Updated weights: α={alpha}, β={beta}, γ={gamma}")

# Utility functions for entity processing

def extract_query_entities(query: str, entity_resolver=None, dev_mode: bool = False) -> List[Dict[str, Any]]:
    """
    Extract and validate entities from query text.

    PRODUCTION: Only returns validated entities from entity_resolver.
    DEV MODE: Falls back to regex patterns for demo purposes.

    Args:
        query: Query text
        entity_resolver: Entity resolution system (required for production)
        dev_mode: Enable regex fallback for demos (NOT for production)

    Returns:
        List of validated entities with validated=True flag
    """
    entities = []

    # Production path: use entity resolver
    if entity_resolver:
        try:
            # Entity resolver should return validated entities
            resolved_entities = entity_resolver.resolve(query)
            for entity in resolved_entities:
                entity["validated"] = True  # Mark as validated by resolver
                entities.append(entity)
            return entities
        except Exception as e:
            logger.warning(f"Entity resolver failed: {e}")

    # Development/demo fallback (when explicitly enabled)
    if dev_mode:
        logger.warning("Using dev_mode entity extraction - NOT for production")
        import re

        # Part numbers (validated pattern match)
        part_pattern = r'\b[A-Z]{2,4}[-_]?\d{3,8}[-_]?[A-Z]?\d*\b'
        for match in re.finditer(part_pattern, query, re.IGNORECASE):
            entities.append({
                "type": "part_number",
                "norm": match.group().upper(),
                "confidence": 0.8,
                "validated": True,  # Consider pattern match as validated for demo
                "source": "regex_pattern"
            })

        # NASA standards (high confidence pattern)
        nasa_pattern = r'\b(NASA[-_]?(STD|HDBK|TM|SP)[-_]?\d+[A-Z]?)\b'
        for match in re.finditer(nasa_pattern, query, re.IGNORECASE):
            entities.append({
                "type": "nasa_standard",
                "norm": match.group().upper(),
                "confidence": 0.9,
                "validated": True,  # NASA standards pattern is reliable
                "source": "regex_pattern"
            })

        # Temperatures (validated format)
        temp_pattern = r'\b\d+\.?\d*\s*[°]?\s*[FfCc]\b'
        for match in re.finditer(temp_pattern, query):
            entities.append({
                "type": "temperature",
                "norm": match.group().replace(" ", "").upper(),
                "confidence": 0.7,
                "validated": True,  # Temperature format is standardized
                "source": "regex_pattern"
            })

        # NOTE: Materials are NOT included in dev mode per BoundState design rules
        # Materials must come from validated resolver only

    return entities

# CLI for testing search
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description="Test EM32 image search")
    parser.add_argument("--index", required=True, help="Image index directory")
    parser.add_argument("--ocr", help="OCR store JSON file")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--k", type=int, default=10, help="Number of results")
    parser.add_argument("--class-filter", nargs="*", help="Filter by image classes")
    parser.add_argument("--model", default="clip-ViT-B-32", help="CLIP model name")

    args = parser.parse_args()

    # Initialize search engine
    engine = ImageSearchEngine(
        image_index_dir=args.index,
        ocr_store_path=args.ocr,
        model_name=args.model
    )

    # Extract entities from query
    query_entities = extract_query_entities(args.query)
    if query_entities:
        print(f"Extracted entities: {query_entities}")

    # Search
    results = engine.search(
        query=args.query,
        k=args.k,
        query_entities=query_entities,
        class_filter=args.class_filter
    )

    # Display results
    print(f"\nSearch results for '{args.query}':")
    print("=" * 60)

    for i, result in enumerate(results, 1):
        print(f"{i:2d}. {result['filename']}")
        print(f"    Class: {result['class']} (conf: {result['class_confidence']:.3f})")
        print(f"    Score: {result['score']:.3f} "
              f"(visual: {result['score_breakdown']['visual']:.3f}, "
              f"ocr: {result['score_breakdown']['ocr']:.3f}, "
              f"entity: {result['score_breakdown']['entity']:.3f})")
        print(f"    Path: {result['path']}")
        if 'overlays' in result:
            print(f"    OCR regions: {len(result['overlays'])}")
        print()

    # Display statistics
    stats = engine.get_statistics()
    print("Search Engine Statistics:")
    print("=" * 60)
    for key, value in stats.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for k, v in value.items():
                print(f"  {k}: {v}")
        else:
            print(f"{key}: {value}")