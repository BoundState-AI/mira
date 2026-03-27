#!/usr/bin/env python3
"""
Module: Document
Purpose: Metadata for a document in the discovery index.

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

import os
import json
import hashlib
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import defaultdict
import pickle

try:
    import numpy as np
    import faiss
    from sentence_transformers import SentenceTransformer
    from tinydb import TinyDB, Query
except ImportError as e:
    print(f"Missing dependencies: {e}")
    print("Install with: pip install sentence-transformers faiss-cpu tinydb numpy")
    exit(1)

from config_manager import get_config

logger = logging.getLogger(__name__)

@dataclass
class DocumentMetadata:
    """Metadata for a document in the discovery index."""
    doc_id: str
    filename: str
    file_path: str
    relative_path: str
    file_size_mb: float
    file_extension: str
    processing_mode: str  # 'pre_chunk', 'doc_level', 'metadata_only', 'skip'
    indexed_at: str
    content_hash: str
    duplicate_of: Optional[str] = None
    text_preview: str = ""
    tag_suggestions: List[str] = None
    classification_confidence: float = 0.0
    depth: int = 0

    def __post_init__(self):
        if self.tag_suggestions is None:
            self.tag_suggestions = []

@dataclass
class SearchResult:
    """Result from document discovery search."""
    doc_id: str
    score: float
    metadata: DocumentMetadata
    text_snippet: str = ""

class DocumentDiscoveryIndex:
    """Lightweight document-level embedding index for massive repositories."""

    def __init__(self, index_path: str = "discovery_index"):
        self.index_path = Path(index_path)
        self.index_path.mkdir(exist_ok=True)

        self.config = get_config()

        # Initialize components
        self.metadata_db = TinyDB(self.index_path / "metadata.json")
        self.embeddings: Optional[List[np.ndarray]] = None
        self.faiss_index: Optional[faiss.Index] = None
        self.doc_ids: List[str] = []
        self.embedder = None

        # Deduplication tracking
        self.content_hashes = {}
        self.duplicate_chains = defaultdict(list)

        # Statistics
        self.stats = {
            'total_documents': 0,
            'duplicates_found': 0,
            'processing_modes': defaultdict(int),
            'file_types': defaultdict(int),
            'total_size_mb': 0.0
        }

        self._initialize_embedder()
        self._load_existing_index()

    def _initialize_embedder(self):
        """Initialize the embedding model."""
        try:
            model_name = "nomic-ai/nomic-embed-text-v1.5"
            device = self.config.performance.embedding_device

            self.embedder = SentenceTransformer(
                model_name,
                device=device,
                trust_remote_code=True
            )
            logger.info(f"Initialized embedder: {model_name} on {device}")

        except Exception as e:
            logger.error(f"Failed to initialize embedder: {e}")
            raise

    def _load_existing_index(self):
        """Load existing FAISS index and metadata."""
        faiss_path = self.index_path / "faiss_index.bin"
        embeddings_path = self.index_path / "embeddings.pkl"
        doc_ids_path = self.index_path / "doc_ids.json"

        try:
            if all(p.exists() for p in [faiss_path, embeddings_path, doc_ids_path]):
                # Load FAISS index
                self.faiss_index = faiss.read_index(str(faiss_path))

                # Load embeddings
                with open(embeddings_path, 'rb') as f:
                    loaded_embeddings = pickle.load(f)

                # Ensure embeddings stored as list for mutability
                if isinstance(loaded_embeddings, np.ndarray):
                    self.embeddings = [loaded_embeddings[i] for i in range(loaded_embeddings.shape[0])]
                else:
                    self.embeddings = list(loaded_embeddings)

                # Load doc IDs
                with open(doc_ids_path, 'r') as f:
                    loaded_doc_ids = json.load(f)
                self.doc_ids = list(loaded_doc_ids)

                logger.info(f"Loaded existing index with {len(self.doc_ids)} documents")
                self._update_stats_from_db()
            else:
                logger.info("No existing index found, starting fresh")

        except Exception as e:
            logger.error(f"Error loading existing index: {e}")
            # Reset to fresh state
            self.faiss_index = None
            self.embeddings = None
            self.doc_ids = []

    def _update_stats_from_db(self):
        """Update statistics from metadata database."""
        all_docs = self.metadata_db.all()
        self.stats['total_documents'] = len(all_docs)

        for doc in all_docs:
            meta = DocumentMetadata(**doc)
            self.stats['processing_modes'][meta.processing_mode] += 1
            self.stats['file_types'][meta.file_extension] += 1
            self.stats['total_size_mb'] += meta.file_size_mb

            if meta.duplicate_of:
                self.stats['duplicates_found'] += 1

    def _extract_text_preview(self, file_path: str, max_tokens: int = 5000) -> Tuple[str, str]:
        """Extract text preview from document (title + first N tokens)."""
        try:
            # Import parsers here to avoid circular imports
            import sys
            sys.path.append('..')
            from boundstate.parsers import get_parser

            # Get file extension
            ext = Path(file_path).suffix.lower()

            # Try to extract text
            with open(file_path, 'rb') as f:
                file_bytes = f.read()

            parser = get_parser(file_path, file_bytes=file_bytes)
            sections = parser.parse()

            if not sections:
                return "", ""

            # Combine all text
            full_text = "\n\n".join(section.get('text', '') for section in sections)

            # Create title from filename and first line
            title = Path(file_path).stem.replace('_', ' ').replace('-', ' ')
            first_line = full_text.split('\n')[0].strip() if full_text else ""
            if first_line and len(first_line) < 100:
                title = f"{title}: {first_line}"

            # Truncate to token budget (rough approximation: 1 token ≈ 4 chars)
            max_chars = max_tokens * 4
            if len(full_text) > max_chars:
                full_text = full_text[:max_chars] + "..."

            # Combine title and text for embedding
            embed_text = f"{title}\n\n{full_text}".strip()

            return embed_text, full_text[:1000]  # Preview is first 1000 chars

        except Exception as e:
            logger.debug(f"Error extracting text from {file_path}: {e}")
            # Fallback to filename as title
            title = Path(file_path).stem.replace('_', ' ').replace('-', ' ')
            return title, ""

    def _compute_content_hash(self, file_path: str, size_mb: float, text_preview: str) -> str:
        """Compute content hash for deduplication."""
        # Use path, size, and first part of text for hash
        hash_input = f"{Path(file_path).name}|{size_mb}|{text_preview[:2000]}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    def _find_duplicate(self, content_hash: str) -> Optional[str]:
        """Find if this content hash already exists."""
        return self.content_hashes.get(content_hash)

    def add_document(self, file_path: str, relative_path: str = None,
                     commit: bool = True) -> bool:
        """Add a document to the discovery index.

        Args:
            file_path: Absolute or relative path to file
            relative_path: Optional logical path for metadata
            commit: When True, persist index immediately; when False, caller
                is responsible for batching and calling save_index().
        """
        try:
            file_path = str(Path(file_path).resolve())

            if not os.path.exists(file_path):
                logger.warning(f"File not found: {file_path}")
                return False

            # Get basic file info
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            filename = os.path.basename(file_path)
            extension = Path(filename).suffix.lower()
            rel_path = relative_path or filename

            # Determine processing mode
            processing_mode = self.config.get_processing_mode(filename, file_size_mb)

            if processing_mode == 'skip':
                logger.debug(f"Skipping file: {filename}")
                return False

            # Generate doc ID
            doc_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]

            # Check if already indexed
            existing = self.metadata_db.search(Query().doc_id == doc_id)
            if existing:
                logger.debug(f"Document already indexed: {filename}")
                return False

            # Extract text if needed
            embed_text = ""
            text_preview = ""

            if processing_mode in ['pre_chunk', 'doc_level']:
                embed_text, text_preview = self._extract_text_preview(
                    file_path,
                    self.config.indexing.doc_level_embed['text_budget_tokens']
                )

            # Compute content hash for deduplication
            content_hash = self._compute_content_hash(file_path, file_size_mb, text_preview)
            duplicate_of = self._find_duplicate(content_hash)

            if duplicate_of and duplicate_of != doc_id:
                # This is a duplicate
                logger.debug(f"Found duplicate: {filename} -> {duplicate_of}")
                self.duplicate_chains[duplicate_of].append(doc_id)
                self.stats['duplicates_found'] += 1
            else:
                # Store as canonical version
                self.content_hashes[content_hash] = doc_id
                duplicate_of = None

            # Create metadata
            metadata = DocumentMetadata(
                doc_id=doc_id,
                filename=filename,
                file_path=file_path,
                relative_path=rel_path,
                file_size_mb=round(file_size_mb, 3),
                file_extension=extension,
                processing_mode=processing_mode,
                indexed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                content_hash=content_hash,
                duplicate_of=duplicate_of,
                text_preview=text_preview,
                depth=len(Path(rel_path).parts) - 1
            )

            # Store metadata
            self.metadata_db.insert(asdict(metadata))

            # Generate embedding for non-duplicate, non-metadata-only documents
            if not duplicate_of and processing_mode != 'metadata_only' and embed_text:
                embedding = self._generate_embedding(embed_text)
                self._add_to_vector_index(doc_id, embedding)

            # Update statistics
            self.stats['total_documents'] += 1
            self.stats['processing_modes'][processing_mode] += 1
            self.stats['file_types'][extension] += 1
            self.stats['total_size_mb'] += file_size_mb

            # Persist if requested (allows batching for efficiency)
            if commit:
                self.save_index()

            logger.debug(f"Added document: {filename} (mode: {processing_mode})")
            return True

        except Exception as e:
            logger.error(f"Error adding document {file_path}: {e}")
            return False

    def add_document_metadata(self, metadata: Dict[str, Any], commit: bool = True) -> bool:
        """Add a metadata-only or text-provided document record.

        If ``metadata`` includes a non-empty ``text`` field, a document-level
        embedding is generated from that text. Otherwise, the record is
        inserted as metadata-only.

        Args:
            metadata: Dictionary with keys like doc_id, filename, text, etc.
            commit: Persist index artifacts to disk when True.

        Returns:
            True if added successfully; False otherwise.
        """
        try:
            doc_id = str(metadata.get('doc_id') or metadata.get('filename') or '')
            if not doc_id:
                logger.warning("add_document_metadata called without doc_id/filename")
                return False

            # Skip if already indexed
            existing = self.metadata_db.search(Query().doc_id == doc_id)
            if existing:
                logger.debug(f"Metadata document already indexed: {doc_id}")
                return False

            filename = str(metadata.get('filename') or Path(doc_id).name)
            file_path = str(metadata.get('file_path') or doc_id)
            ext = Path(filename).suffix.lower()

            # Try to compute file size
            try:
                size_bytes = Path(file_path).stat().st_size
                file_size_mb = round(size_bytes / (1024 * 1024), 3)
            except Exception:
                file_size_mb = 0.0

            rel_path = str(metadata.get('relative_path') or filename)

            text: str = str(metadata.get('text') or '')
            text_preview = text[:1000] if text else ''
            processing_mode = 'doc_level' if text else 'metadata_only'

            # Content hash
            content_hash = hashlib.sha256(
                f"{filename}|{file_size_mb}|{text_preview[:2000]}".encode()
            ).hexdigest()[:16]

            # Build and store metadata record
            record = DocumentMetadata(
                doc_id=doc_id,
                filename=filename,
                file_path=file_path,
                relative_path=rel_path,
                file_size_mb=file_size_mb,
                file_extension=ext,
                processing_mode=processing_mode,
                indexed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                content_hash=content_hash,
                duplicate_of=None,
                text_preview=text_preview,
                depth=len(Path(rel_path).parts) - 1
            )

            self.metadata_db.insert(asdict(record))

            # Optional embedding from provided text
            if text:
                try:
                    embedding = self._generate_embedding(text)
                    self._add_to_vector_index(doc_id, embedding)
                except Exception as e:
                    logger.warning(f"Failed to embed metadata document {doc_id}: {e}")

            if commit:
                try:
                    self.save_index()
                except Exception as e:
                    logger.debug(f"save_index failed in add_document_metadata: {e}")

            logger.debug(f"Added metadata document: {filename} (mode: {processing_mode})")
            return True

        except Exception as e:
            logger.error(f"Error in add_document_metadata for {metadata}: {e}")
            return False

    def _generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for text."""
        # Add search_document prefix for Nomic model
        prefixed_text = f"search_document: {text}"
        embedding = self.embedder.encode(
            [prefixed_text],
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=1,
            show_progress_bar=False
        )[0]
        return embedding

    def _add_to_vector_index(self, doc_id: str, embedding: np.ndarray):
        """Add embedding to FAISS vector index."""
        if self.faiss_index is None:
            # Initialize FAISS index
            dimension = embedding.shape[0]
            self.faiss_index = faiss.IndexFlatIP(dimension)  # Inner product for normalized embeddings
            self.embeddings = []
            self.doc_ids = []

        # Handle mutable storage
        if self.embeddings is None:
            self.embeddings = []
        elif isinstance(self.embeddings, np.ndarray):
            self.embeddings = [self.embeddings[i] for i in range(self.embeddings.shape[0])]

        if not isinstance(self.doc_ids, list):
            self.doc_ids = list(self.doc_ids)

        # Add to FAISS index
        self.faiss_index.add(embedding.reshape(1, -1))
        self.embeddings.append(embedding)
        self.doc_ids.append(doc_id)

    def search(self, query: str, k: int = 10, include_metadata_only: bool = False) -> List[SearchResult]:
        """Search the document discovery index."""
        if not self.faiss_index or len(self.doc_ids) == 0:
            logger.warning("No documents in index for search")
            return []

        try:
            # Generate query embedding
            query_prefixed = f"search_query: {query}"
            query_embedding = self.embedder.encode(
                [query_prefixed],
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=1,
                show_progress_bar=False
            )[0]

            # Search FAISS index
            search_k = min(k * 2, len(self.doc_ids))  # Over-retrieve for filtering
            scores, indices = self.faiss_index.search(query_embedding.reshape(1, -1), search_k)

            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx == -1:  # FAISS returns -1 for empty slots
                    continue

                doc_id = self.doc_ids[idx]

                # Get metadata
                doc_data = self.metadata_db.search(Query().doc_id == doc_id)
                if not doc_data:
                    continue

                metadata = DocumentMetadata(**doc_data[0])

                # Skip metadata-only documents unless explicitly requested
                if not include_metadata_only and metadata.processing_mode == 'metadata_only':
                    continue

                # Skip duplicates (point to canonical version)
                if metadata.duplicate_of:
                    continue

                results.append(SearchResult(
                    doc_id=doc_id,
                    score=float(score),
                    metadata=metadata,
                    text_snippet=metadata.text_preview[:200] + "..." if len(metadata.text_preview) > 200 else metadata.text_preview
                ))

            # Sort by score (descending) and limit to k
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:k]

        except Exception as e:
            logger.error(f"Error searching index: {e}")
            return []

    def get_document_metadata(self, doc_id: str) -> Optional[DocumentMetadata]:
        """Get metadata for a specific document."""
        doc_data = self.metadata_db.search(Query().doc_id == doc_id)
        if doc_data:
            return DocumentMetadata(**doc_data[0])
        return None

    def get_statistics(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            'total_documents': self.stats['total_documents'],
            'vector_indexed_documents': len(self.doc_ids) if self.doc_ids else 0,
            'duplicates_found': self.stats['duplicates_found'],
            'total_size_gb': round(self.stats['total_size_mb'] / 1024, 2),
            'processing_modes': dict(self.stats['processing_modes']),
            'file_types': dict(self.stats['file_types']),
            'index_size_mb': self.get_index_size_mb()
        }

    def get_index_size_mb(self) -> float:
        """Calculate approximate index size in MB."""
        try:
            total_size = 0
            for file in self.index_path.glob("*"):
                if file.is_file():
                    total_size += file.stat().st_size
            return round(total_size / (1024 * 1024), 2)
        except OSError:
            return 0.0

    def save_index(self):
        """Save FAISS index and embeddings to disk."""
        if self.faiss_index is None:
            logger.debug("save_index skipped: no FAISS index in memory")
            return

        if not self.doc_ids:
            logger.debug("save_index skipped: no document IDs loaded")
            return

        if not self.embeddings:
            logger.debug("save_index skipped: no embeddings to persist")
            return

        try:
            faiss_path = self.index_path / "faiss_index.bin"
            embeddings_path = self.index_path / "embeddings.pkl"
            doc_ids_path = self.index_path / "doc_ids.json"

            # Ensure parent directory exists
            self.index_path.mkdir(parents=True, exist_ok=True)

            # Save FAISS index
            faiss.write_index(self.faiss_index, str(faiss_path))

            # Save embeddings (persist as list of numpy arrays)
            embeddings_array = np.stack(self.embeddings)
            with open(embeddings_path, 'wb') as f:
                pickle.dump(embeddings_array, f)

            # Save doc IDs
            with open(doc_ids_path, 'w') as f:
                json.dump(self.doc_ids, f, indent=2)

            logger.info(f"Saved index with {len(self.doc_ids)} documents to {self.index_path}")

        except Exception as e:
            logger.error(f"Error saving index: {e}")

    def batch_index_directory(self, directory_path: str, recursive: bool = True,
                            max_files: int = None, progress_callback=None) -> Dict[str, Any]:
        """Batch index an entire directory."""
        directory_path = Path(directory_path)

        if not directory_path.exists():
            raise ValueError(f"Directory does not exist: {directory_path}")

        logger.info(f"Starting batch indexing of {directory_path}")
        start_time = time.time()

        # Collect all files
        files_to_process = []
        for root, dirs, files in os.walk(directory_path):
            # Skip unwanted directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in {'cache', 'temp', '__pycache__'}]

            for filename in files:
                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, directory_path)
                files_to_process.append((file_path, relative_path))

                if max_files and len(files_to_process) >= max_files:
                    break

            if max_files and len(files_to_process) >= max_files:
                break

        logger.info(f"Found {len(files_to_process)} files to process")

        # Process files
        processed = 0
        successful = 0
        batch_size = self.config.performance.doc_level_batch_size

        for i in range(0, len(files_to_process), batch_size):
            batch = files_to_process[i:i + batch_size]

            for file_path, relative_path in batch:
                if self.add_document(file_path, relative_path):
                    successful += 1
                processed += 1

                if progress_callback and processed % 100 == 0:
                    progress_callback(processed, len(files_to_process))

            # Save progress periodically
            if i % (batch_size * 10) == 0 and i > 0:
                self.save_index()
                logger.info(f"Processed {processed}/{len(files_to_process)} files...")

        # Final save
        self.save_index()

        duration = time.time() - start_time

        results = {
            'files_processed': processed,
            'files_successful': successful,
            'files_failed': processed - successful,
            'duration_seconds': round(duration, 2),
            'files_per_second': round(processed / duration, 2),
            'final_statistics': self.get_statistics()
        }

        logger.info(f"Batch indexing complete: {results}")
        return results

if __name__ == "__main__":
    # Test the document discovery index
    logging.basicConfig(level=logging.INFO)

    # Create test index
    index = DocumentDiscoveryIndex("test_discovery_index")

    # Print statistics
    stats = index.get_statistics()
    print(f"Index statistics: {stats}")

    # Test search if index has documents
    if stats['vector_indexed_documents'] > 0:
        results = index.search("NASA standards flammability", k=5)
        print(f"\nSearch results for 'NASA standards flammability':")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result.metadata.filename} (score: {result.score:.3f})")
            print(f"   Mode: {result.metadata.processing_mode}, Size: {result.metadata.file_size_mb:.1f}MB")
            print(f"   Path: {result.metadata.relative_path}")
            if result.text_snippet:
                print(f"   Preview: {result.text_snippet[:100]}...")
            print()
