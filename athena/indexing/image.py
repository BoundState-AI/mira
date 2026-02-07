#!/usr/bin/env python3
"""
Module: Image
Purpose: CLIP-based image indexing system for semantic search.

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

from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import numpy as np
import json
import time
import logging
from PIL import Image
import hashlib

# CLIP embedding via sentence-transformers
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("ERROR: sentence-transformers not installed. Run: pip install sentence-transformers")
    exit(1)

# FAISS for vector indexing
try:
    import faiss
except ImportError:
    print("ERROR: faiss not installed. Run: pip install faiss-cpu (or faiss-gpu)")
    exit(1)

logger = logging.getLogger(__name__)

class ImageIndex:
    """
    CLIP-based image indexing system for semantic search.

    Builds FAISS index of normalized image embeddings for fast similarity search.
    Stores metadata for each image including classification hints and OCR readiness.
    """

    def __init__(self, index_dir: str, model_name: str = "clip-ViT-B-32"):
        """
        Initialize image index.

        Args:
            index_dir: Directory to store index files
            model_name: CLIP model name (clip-ViT-B-32, clip-ViT-L-14, etc.)
        """
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        # Load CLIP model
        logger.info(f"Loading CLIP model: {model_name}")
        self.model = SentenceTransformer(model_name)

        # Storage
        self.vecs: Optional[np.ndarray] = None
        self.meta: List[Dict[str, Any]] = []
        self.faiss_index: Optional[faiss.Index] = None

        logger.info(f"Initialized ImageIndex at {self.index_dir}")

    def _embed_image(self, image_path: str) -> np.ndarray:
        """
        Generate CLIP embedding for single image.

        Args:
            image_path: Path to image file

        Returns:
            Normalized embedding vector as float32 array
        """
        try:
            # Load and convert to RGB
            img = Image.open(image_path).convert("RGB")

            # Generate embedding (sentence-transformers handles normalization)
            embedding = self.model.encode([img], normalize_embeddings=True)
            return embedding[0].astype("float32")

        except Exception as e:
            logger.error(f"Failed to embed image {image_path}: {e}")
            raise

    def add_images(self, image_files: List[str], meta_hook: Optional[Callable[[str], Dict[str, Any]]] = None) -> int:
        """
        Add images to index with embeddings and metadata.

        Args:
            image_files: List of image file paths
            meta_hook: Optional function to generate additional metadata per image

        Returns:
            Number of images successfully added
        """
        logger.info(f"Adding {len(image_files)} images to index...")

        embeddings = []
        added_count = 0

        for i, file_path in enumerate(image_files):
            try:
                # Generate embedding
                embedding = self._embed_image(file_path)

                # Base metadata
                metadata = {
                    "doc_id": file_path,  # Use file path as doc_id
                    "path": file_path,
                    "filename": Path(file_path).name,
                    "size_bytes": Path(file_path).stat().st_size if Path(file_path).exists() else 0,
                    "added_timestamp": time.time()
                }

                # Add custom metadata if hook provided
                if meta_hook:
                    try:
                        custom_meta = meta_hook(file_path)
                        metadata.update(custom_meta)
                    except Exception as e:
                        logger.warning(f"Meta hook failed for {file_path}: {e}")

                # Store
                self.meta.append(metadata)
                embeddings.append(embedding)
                added_count += 1

                # Progress logging
                if (i + 1) % 100 == 0:
                    logger.info(f"Processed {i + 1}/{len(image_files)} images...")

            except Exception as e:
                logger.error(f"Failed to process image {file_path}: {e}")
                continue

        if not embeddings:
            logger.warning("No images were successfully processed")
            return 0

        # Stack embeddings
        new_embeddings = np.vstack(embeddings)

        # Combine with existing embeddings if present
        if self.vecs is None:
            self.vecs = new_embeddings
        else:
            self.vecs = np.vstack([self.vecs, new_embeddings])

        logger.info(f"Successfully added {added_count} images. Total embeddings: {len(self.vecs)}")
        return added_count

    def build_faiss_index(self, index_type: str = "Flat", nlist: Optional[int] = None) -> None:
        """
        Build FAISS index from embeddings.

        Args:
            index_type: Type of FAISS index ("Flat" for exact search, "IVF" for approximate)
            nlist: Number of centroids for IVF index (auto-calculated if None)
        """
        if self.vecs is None or len(self.vecs) == 0:
            raise ValueError("No embeddings available. Add images first.")

        logger.info(f"Building FAISS {index_type} index with {len(self.vecs)} vectors...")

        dimension = self.vecs.shape[1]
        num_vectors = len(self.vecs)

        if index_type == "Flat":
            # Exact search using inner product (embeddings are normalized, so IP = cosine similarity)
            self.faiss_index = faiss.IndexFlatIP(dimension)

        elif index_type == "IVF":
            # Calculate optimal nlist based on dataset size if not provided
            if nlist is None:
                if num_vectors < 1000:
                    nlist = min(64, num_vectors // 4)
                elif num_vectors < 10000:
                    nlist = min(512, num_vectors // 10)
                elif num_vectors < 100000:
                    nlist = min(2048, num_vectors // 20)
                else:
                    nlist = min(8192, num_vectors // 40)

            nlist = max(1, nlist)  # Ensure at least 1 centroid

            logger.info(f"Building IVF index with {nlist} centroids for {num_vectors} vectors")

            # Create IVF index
            quantizer = faiss.IndexFlatIP(dimension)
            self.faiss_index = faiss.IndexIVFFlat(quantizer, dimension, nlist)

            # Train the index
            logger.info(f"Training IVF index...")
            self.faiss_index.train(self.vecs)

            # Set default search parameters (can be tuned later)
            # nprobe should be roughly sqrt(nlist) for good recall/speed balance
            default_nprobe = max(1, min(nlist, int(np.sqrt(nlist))))
            self.faiss_index.nprobe = default_nprobe
            logger.info(f"Set default nprobe to {default_nprobe}")

        else:
            raise ValueError(f"Unsupported index type: {index_type}. Use 'Flat' or 'IVF'")

        # Add vectors to index
        self.faiss_index.add(self.vecs)

        logger.info(f"FAISS index built successfully. Total vectors: {self.faiss_index.ntotal}")

        # Store index configuration for later use
        self.index_config = {
            "index_type": index_type,
            "dimension": dimension,
            "num_vectors": num_vectors
        }

        if index_type == "IVF":
            self.index_config.update({
                "nlist": nlist,
                "nprobe": self.faiss_index.nprobe
            })

    def save(self) -> None:
        """Save index and metadata to disk."""
        if self.faiss_index is None:
            raise ValueError("No FAISS index to save. Build index first.")

        logger.info(f"Saving index to {self.index_dir}")

        # Save FAISS index
        faiss_path = self.index_dir / "image.faiss"
        faiss.write_index(self.faiss_index, str(faiss_path))

        # Save metadata
        meta_path = self.index_dir / "meta.json"
        with open(meta_path, 'w') as f:
            json.dump(self.meta, f, indent=2, default=str)

        # Save embeddings for future use
        embeddings_path = self.index_dir / "embeddings.npy"
        np.save(embeddings_path, self.vecs)

        # Save index info
        info = {
            "num_images": len(self.meta),
            "embedding_dim": self.vecs.shape[1] if self.vecs is not None else 0,
            "model_name": getattr(self.model, 'model_name', "clip-ViT-B-32"),
            "created_timestamp": time.time(),
            "version": "1.0"
        }
        info_path = self.index_dir / "index_info.json"
        with open(info_path, 'w') as f:
            json.dump(info, f, indent=2)

        logger.info(f"Index saved: {len(self.meta)} images, {faiss_path}")

    @classmethod
    def load(cls, index_dir: str, model_name: str = "clip-ViT-B-32") -> 'ImageIndex':
        """
        Load existing index from disk.

        Args:
            index_dir: Directory containing saved index
            model_name: CLIP model name (must match saved index)

        Returns:
            Loaded ImageIndex instance
        """
        index_dir_path = Path(index_dir)

        if not index_dir_path.exists():
            raise FileNotFoundError(f"Index directory not found: {index_dir}")

        # Create instance
        instance = cls(index_dir, model_name)

        # Load FAISS index
        faiss_path = index_dir_path / "image.faiss"
        if not faiss_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {faiss_path}")

        logger.info(f"Loading FAISS index from {faiss_path}")
        instance.faiss_index = faiss.read_index(str(faiss_path))

        # Load metadata
        meta_path = index_dir_path / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata not found: {meta_path}")

        with open(meta_path, 'r') as f:
            instance.meta = json.load(f)

        # Load embeddings if available
        embeddings_path = index_dir_path / "embeddings.npy"
        if embeddings_path.exists():
            instance.vecs = np.load(embeddings_path)

        logger.info(f"Loaded index: {len(instance.meta)} images")
        return instance

    def search(self, query_embedding: np.ndarray, k: int = 10) -> List[Dict[str, Any]]:
        """
        Search for similar images using embedding.

        Args:
            query_embedding: Query embedding vector
            k: Number of results to return

        Returns:
            List of search results with metadata and scores
        """
        if self.faiss_index is None:
            raise ValueError("No FAISS index loaded. Build or load index first.")

        # Ensure query is 2D and normalized
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        # Search
        scores, indices = self.faiss_index.search(query_embedding, min(k, self.faiss_index.ntotal))

        # Build results
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:  # FAISS returns -1 for invalid indices
                continue

            result = self.meta[idx].copy()
            result['similarity_score'] = float(score)
            result['rank'] = len(results) + 1
            results.append(result)

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            "total_images": len(self.meta),
            "embedding_dim": self.vecs.shape[1] if self.vecs is not None else 0,
            "faiss_index_size": self.faiss_index.ntotal if self.faiss_index else 0,
            "index_dir": str(self.index_dir),
            "model_loaded": self.model is not None,
        }

def create_classification_meta_hook() -> Callable[[str], Dict[str, Any]]:
    """
    Create metadata hook for basic image classification based on filename patterns.

    Returns:
        Function that extracts classification metadata from image path
    """
    def meta_hook(image_path: str) -> Dict[str, Any]:
        filename_lower = Path(image_path).name.lower()

        # Basic classification based on filename patterns
        image_class = "general_technical"
        class_confidence = 0.5

        if any(keyword in filename_lower for keyword in
               ['drawing', 'dwg', 'schematic', 'diagram', 'blueprint', 'sketch']):
            image_class = "technical_drawing"
            class_confidence = 0.8
        elif any(keyword in filename_lower for keyword in
                 ['test', 'setup', 'experiment', 'specimen', 'sample']):
            image_class = "test_photo"
            class_confidence = 0.7
        elif any(keyword in filename_lower for keyword in
                 ['weld', 'fsw', 'joint', 'cross', 'section', 'macro', 'micro']):
            image_class = "weld_analysis"
            class_confidence = 0.8
        elif any(keyword in filename_lower for keyword in
                 ['tool', 'equipment', 'machine', 'fixture', 'instrument', 'panel']):
            image_class = "equipment_photo"
            class_confidence = 0.7
        elif any(keyword in filename_lower for keyword in
                 ['chart', 'graph', 'plot', 'data', 'result']):
            image_class = "data_visualization"
            class_confidence = 0.7

        return {
            "class": image_class,
            "class_confidence": class_confidence,
            "should_ocr": image_class in ["technical_drawing", "equipment_photo", "data_visualization"],
            "priority_score": class_confidence * (3 if image_class == "technical_drawing" else
                                                 2 if image_class in ["equipment_photo", "test_photo"] else 1)
        }

    return meta_hook

# CLI for building index
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description="Build CLIP image index for EM32 visual search")
    parser.add_argument("--images", required=True, help="Directory containing images")
    parser.add_argument("--index", default="./image_index", help="Output index directory")
    parser.add_argument("--model", default="clip-ViT-B-32", help="CLIP model name")
    parser.add_argument("--index-type", default="Flat", choices=["Flat", "IVF"], help="FAISS index type")
    parser.add_argument("--limit", type=int, help="Limit number of images (for testing)")
    parser.add_argument("--extensions", default="png,jpg,jpeg,tif,tiff,bmp", help="Image extensions to process")

    args = parser.parse_args()

    # Find images
    image_extensions = {f".{ext.lower()}" for ext in args.extensions.split(",")}
    image_dir = Path(args.images)

    if not image_dir.exists():
        print(f"Error: Image directory not found: {image_dir}")
        exit(1)

    image_files = [str(p) for p in image_dir.rglob("*") if p.suffix.lower() in image_extensions]

    if args.limit:
        image_files = image_files[:args.limit]

    print(f"Found {len(image_files)} images in {image_dir}")

    if not image_files:
        print("No images found!")
        exit(1)

    # Build index
    index = ImageIndex(args.index, args.model)

    # Add images with classification metadata
    meta_hook = create_classification_meta_hook()
    added_count = index.add_images(image_files, meta_hook)

    if added_count == 0:
        print("No images were successfully processed!")
        exit(1)

    # Build FAISS index
    index.build_faiss_index(args.index_type)

    # Save
    index.save()

    # Print stats
    stats = index.get_stats()
    print(f"\nIndex built successfully:")
    print(f"  Total images: {stats['total_images']}")
    print(f"  Embedding dimension: {stats['embedding_dim']}")
    print(f"  Index saved to: {stats['index_dir']}")