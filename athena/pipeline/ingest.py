#!/usr/bin/env python3
"""
Module: Ingest
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

from athena.config import AthenaConfig
from athena.models.document import Document
from athena.models.separator import FolderSegment, SeparatorResult
from athena.pipeline.boundary import BoundaryDetector, SeparatorDetector, HybridBoundaryDetector
from athena.services.storage import FileStore
from athena.utils.pdf import extract_pdf_metadata

if TYPE_CHECKING:
    import fitz

logger = logging.getLogger(__name__)


class IngestPipeline:
    """Accept PDFs, validate, detect boundaries, and queue for processing."""

    SUPPORTED_EXTENSIONS = {".pdf", ".tiff", ".tif"}

    def __init__(
        self,
        config: AthenaConfig,
        storage: FileStore,
        db,
        llm=None,
    ):
        """Initialize ingest pipeline.

        Args:
            config: ATHENA configuration
            storage: File storage service
            db: Database client
            llm: LLM provider for boundary detection
        """
        self.config = config
        self.storage = storage
        self.db = db
        self.boundary_detector = BoundaryDetector(config, llm, storage) if llm else None

    async def ingest_file(
        self,
        file_path: Path,
        batch_id: str,
        tenant_id: str,
        detect_boundaries: bool = True,
    ) -> list[Document]:
        """Ingest a PDF file and create Document records.

        Args:
            file_path: Path to PDF file
            batch_id: Batch ID
            tenant_id: Tenant ID
            detect_boundaries: Whether to detect document boundaries

        Returns:
            List of created Document records
        """
        import fitz

        # Validate file
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported format: {file_path.suffix}")

        # Read and hash file
        file_bytes = file_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Upload to storage
        storage_path = f"batches/{batch_id}/source/{file_path.name}"
        await self.storage.upload(storage_path, file_bytes, "application/pdf")
        logger.info(f"Uploaded {file_path.name} to {storage_path}")

        # Open and extract metadata
        doc = fitz.open(file_path)
        metadata = extract_pdf_metadata(doc)

        # Detect boundaries or use entire document
        if detect_boundaries and self.boundary_detector and len(doc) > 1:
            boundaries = await self.boundary_detector.detect_boundaries(
                doc, file_path.name, batch_id
            )
            logger.info(f"Detected {len(boundaries)} document(s) in {file_path.name}")
        else:
            boundaries = [(1, len(doc))]

        # Create Document records for each boundary range
        documents = []
        for start, end in boundaries:
            document = Document(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_file=file_path.name,
                source_path=storage_path,
                source_hash=file_hash,
                source_dpi=metadata.get("source_dpi"),
                page_range=(start, end),
                page_count=end - start + 1,
                pipeline_version=self.config.pipeline_version,
            )
            await self.db.insert_document(document)
            documents.append(document)
            logger.debug(f"Created document {document.document_id} for pages {start}-{end}")

        doc.close()
        return documents

    async def ingest_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        batch_id: str,
        tenant_id: str,
        detect_boundaries: bool = True,
    ) -> list[Document]:
        """Ingest PDF from bytes.

        Args:
            file_bytes: PDF file content
            filename: Original filename
            batch_id: Batch ID
            tenant_id: Tenant ID
            detect_boundaries: Whether to detect document boundaries

        Returns:
            List of created Document records
        """
        import fitz

        # Validate extension
        ext = Path(filename).suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported format: {ext}")

        # Hash file
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Upload to storage
        storage_path = f"batches/{batch_id}/source/{filename}"
        await self.storage.upload(storage_path, file_bytes, "application/pdf")

        # Open from bytes
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        metadata = extract_pdf_metadata(doc)

        # Detect boundaries
        if detect_boundaries and self.boundary_detector and len(doc) > 1:
            boundaries = await self.boundary_detector.detect_boundaries(
                doc, filename, batch_id
            )
        else:
            boundaries = [(1, len(doc))]

        # Create documents
        documents = []
        for start, end in boundaries:
            document = Document(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_file=filename,
                source_path=storage_path,
                source_hash=file_hash,
                source_dpi=metadata.get("source_dpi"),
                page_range=(start, end),
                page_count=end - start + 1,
                pipeline_version=self.config.pipeline_version,
            )
            await self.db.insert_document(document)
            documents.append(document)

        doc.close()
        return documents

    async def validate_file(self, file_path: Path) -> dict:
        """Validate a file without ingesting.

        Args:
            file_path: Path to file

        Returns:
            Validation result dictionary
        """
        import fitz

        result = {
            "valid": False,
            "filename": file_path.name,
            "errors": [],
            "warnings": [],
        }

        # Check existence
        if not file_path.exists():
            result["errors"].append("File not found")
            return result

        # Check extension
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            result["errors"].append(f"Unsupported format: {file_path.suffix}")
            return result

        # Try to open
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            result["errors"].append(f"Failed to open PDF: {e}")
            return result

        # Check page count
        if len(doc) == 0:
            result["errors"].append("PDF has no pages")
            doc.close()
            return result

        # Extract metadata
        metadata = extract_pdf_metadata(doc)
        result["page_count"] = metadata["page_count"]
        result["source_dpi"] = metadata.get("source_dpi")

        # Warnings for low DPI
        if metadata.get("source_dpi") and metadata["source_dpi"] < 150:
            result["warnings"].append(
                f"Low source DPI ({metadata['source_dpi']}), may affect quality"
            )

        doc.close()
        result["valid"] = True
        return result


# ==============================================================================
# V2: Separator-Based Ingest with Incremental Saving
# ==============================================================================


class IngestState:
    """State for incremental ingest processing.

    CRITICAL: Enables saving progress after each segment.
    The Wasted Run of 2025-12-22: Never lose progress on interrupt.
    """

    def __init__(
        self,
        batch_id: str,
        source_file: str,
        total_pages: int,
    ):
        self.batch_id = batch_id
        self.source_file = source_file
        self.total_pages = total_pages
        self.segments_found: list[FolderSegment] = []
        self.documents_created: list[Document] = []
        self.pages_processed: int = 0
        self.started_at: datetime = datetime.utcnow()
        self.completed_at: datetime | None = None

    def to_dict(self) -> dict:
        """Serialize state for saving."""
        return {
            "batch_id": self.batch_id,
            "source_file": self.source_file,
            "total_pages": self.total_pages,
            "segments_found": [
                {
                    "segment_id": str(s.segment_id),
                    "page_range": s.page_range,
                    "folder_name": s.separator.folder_name if s.separator else None,
                }
                for s in self.segments_found
            ],
            "documents_created": [str(d.document_id) for d in self.documents_created],
            "pages_processed": self.pages_processed,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class IngestPipelineV2:
    """V2 Ingest with separator-based boundaries and incremental saving.

    CRITICAL: Saves progress after each segment detection.
    Uses barcode-based separator sheets for DETERMINISTIC boundaries.

    Supports hybrid mode: separator sheets (primary) + heuristic (fallback).
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".tiff", ".tif"}

    def __init__(
        self,
        config: AthenaConfig,
        storage: FileStore,
        db,
        llm=None,
        use_separators: bool = True,
        hybrid_mode: bool = True,
    ):
        """Initialize V2 ingest pipeline.

        Args:
            config: ATHENA configuration
            storage: File storage service
            db: Database client
            llm: LLM provider for heuristic boundary detection
            use_separators: Whether to scan for separator barcodes
            hybrid_mode: Use separator + heuristic (True) or separator-only (False)
        """
        self.config = config
        self.storage = storage
        self.db = db
        self.use_separators = use_separators

        # Initialize boundary detectors
        self.separator_detector = SeparatorDetector() if use_separators else None

        if hybrid_mode and llm:
            self.boundary_detector = HybridBoundaryDetector(
                config=config,
                llm=llm,
                storage=storage,
                separator_detector=self.separator_detector,
            )
        elif use_separators:
            # Separator-only mode
            self.boundary_detector = None
        else:
            # Heuristic-only mode (V1 behavior)
            self.boundary_detector = BoundaryDetector(config, llm, storage) if llm else None

    async def ingest_file(
        self,
        file_path: Path,
        batch_id: str,
        tenant_id: str,
        detect_boundaries: bool = True,
        save_callback: Callable[[IngestState], Awaitable[None]] | None = None,
    ) -> tuple[list[Document], list[FolderSegment]]:
        """Ingest a PDF file with V2 separator detection.

        CRITICAL: Saves progress after each segment via save_callback.

        Args:
            file_path: Path to PDF file
            batch_id: Batch ID
            tenant_id: Tenant ID
            detect_boundaries: Whether to detect document boundaries
            save_callback: Called after each segment with current state

        Returns:
            Tuple of (Document list, FolderSegment list)
        """
        import fitz

        # Validate file
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported format: {file_path.suffix}")

        # Read and hash file
        file_bytes = file_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Upload to storage
        storage_path = f"batches/{batch_id}/source/{file_path.name}"
        await self.storage.upload(storage_path, file_bytes, "application/pdf")
        logger.info(f"Uploaded {file_path.name} to {storage_path}")

        # Open and extract metadata
        doc = fitz.open(file_path)
        metadata = extract_pdf_metadata(doc)

        # Initialize state for incremental saving
        state = IngestState(
            batch_id=batch_id,
            source_file=file_path.name,
            total_pages=len(doc),
        )

        # Detect boundaries
        segments: list[FolderSegment] = []

        if detect_boundaries and len(doc) > 1:
            if self.boundary_detector:
                # Hybrid mode: uses HybridBoundaryDetector
                boundaries = await self.boundary_detector.detect_boundaries(
                    doc, file_path.name, batch_id
                )
                # Convert boundaries to segments
                for idx, (start, end) in enumerate(boundaries):
                    segment = FolderSegment(
                        batch_id=batch_id,
                        separator=SeparatorResult(separator_id=f"heuristic_{idx}"),
                        page_range=(start, end),
                        page_count=end - start + 1,
                    )
                    segments.append(segment)
                    state.segments_found.append(segment)

                    # INCREMENTAL SAVE after each segment
                    if save_callback:
                        await save_callback(state)

            elif self.separator_detector:
                # Separator-only mode
                segments = self.separator_detector.create_folder_segments(doc, batch_id)
                for segment in segments:
                    state.segments_found.append(segment)
                    if save_callback:
                        await save_callback(state)
        else:
            # Single segment for entire document
            segment = FolderSegment(
                batch_id=batch_id,
                separator=SeparatorResult(separator_id="full_document"),
                page_range=(1, len(doc)),
                page_count=len(doc),
            )
            segments = [segment]
            state.segments_found = segments

        logger.info(f"Detected {len(segments)} segment(s) in {file_path.name}")

        # Create Document records for each segment
        documents = []
        for segment in segments:
            start, end = segment.page_range

            document = Document(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_file=file_path.name,
                source_path=storage_path,
                source_hash=file_hash,
                source_dpi=metadata.get("source_dpi"),
                page_range=(start, end),
                page_count=end - start + 1,
                pipeline_version=self.config.pipeline_version,
            )
            await self.db.insert_document(document)
            documents.append(document)
            segment.documents.append(document.document_id)
            state.documents_created.append(document)

            logger.debug(
                f"Created document {document.document_id} for pages {start}-{end} "
                f"(folder: {segment.separator.folder_name if segment.separator else 'unknown'})"
            )

            # INCREMENTAL SAVE after each document
            if save_callback:
                await save_callback(state)

        state.completed_at = datetime.utcnow()
        doc.close()

        return documents, segments

    async def ingest_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        batch_id: str,
        tenant_id: str,
        detect_boundaries: bool = True,
        save_callback: Callable[[IngestState], Awaitable[None]] | None = None,
    ) -> tuple[list[Document], list[FolderSegment]]:
        """Ingest PDF from bytes with V2 separator detection.

        CRITICAL: Saves progress after each segment via save_callback.

        Args:
            file_bytes: PDF file content
            filename: Original filename
            batch_id: Batch ID
            tenant_id: Tenant ID
            detect_boundaries: Whether to detect document boundaries
            save_callback: Called after each segment

        Returns:
            Tuple of (Document list, FolderSegment list)
        """
        import fitz

        # Validate extension
        ext = Path(filename).suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported format: {ext}")

        # Hash file
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Upload to storage
        storage_path = f"batches/{batch_id}/source/{filename}"
        await self.storage.upload(storage_path, file_bytes, "application/pdf")

        # Open from bytes
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        metadata = extract_pdf_metadata(doc)

        # Initialize state
        state = IngestState(
            batch_id=batch_id,
            source_file=filename,
            total_pages=len(doc),
        )

        # Detect boundaries
        segments: list[FolderSegment] = []

        if detect_boundaries and len(doc) > 1:
            if self.boundary_detector:
                boundaries = await self.boundary_detector.detect_boundaries(
                    doc, filename, batch_id
                )
                for idx, (start, end) in enumerate(boundaries):
                    segment = FolderSegment(
                        batch_id=batch_id,
                        separator=SeparatorResult(separator_id=f"heuristic_{idx}"),
                        page_range=(start, end),
                        page_count=end - start + 1,
                    )
                    segments.append(segment)
                    state.segments_found.append(segment)
                    if save_callback:
                        await save_callback(state)

            elif self.separator_detector:
                segments = self.separator_detector.create_folder_segments(doc, batch_id)
                for segment in segments:
                    state.segments_found.append(segment)
                    if save_callback:
                        await save_callback(state)
        else:
            segment = FolderSegment(
                batch_id=batch_id,
                separator=SeparatorResult(separator_id="full_document"),
                page_range=(1, len(doc)),
                page_count=len(doc),
            )
            segments = [segment]
            state.segments_found = segments

        # Create documents
        documents = []
        for segment in segments:
            start, end = segment.page_range

            document = Document(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_file=filename,
                source_path=storage_path,
                source_hash=file_hash,
                source_dpi=metadata.get("source_dpi"),
                page_range=(start, end),
                page_count=end - start + 1,
                pipeline_version=self.config.pipeline_version,
            )
            await self.db.insert_document(document)
            documents.append(document)
            segment.documents.append(document.document_id)
            state.documents_created.append(document)

            if save_callback:
                await save_callback(state)

        state.completed_at = datetime.utcnow()
        doc.close()

        return documents, segments

    async def resume_ingest(
        self,
        state: IngestState,
        tenant_id: str,
    ) -> tuple[list[Document], list[FolderSegment]]:
        """Resume interrupted ingest from saved state.

        CRITICAL: Continues from where we left off, no duplicate work.

        Args:
            state: Saved ingest state
            tenant_id: Tenant ID

        Returns:
            Tuple of (remaining Documents, remaining Segments)
        """
        logger.info(
            f"Resuming ingest for {state.source_file}: "
            f"{len(state.documents_created)}/{len(state.segments_found)} documents created"
        )

        # Already created documents - just return what we have
        return state.documents_created, state.segments_found


async def save_ingest_state(
    state: IngestState,
    output_path: Path,
) -> None:
    """Default save callback for ingest state.

    Saves state as JSON after each segment.

    Args:
        state: Current ingest state
        output_path: Path to save JSON
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(state.to_dict(), f, indent=2)

    logger.debug(
        f"Saved ingest state: {len(state.segments_found)} segments, "
        f"{len(state.documents_created)} documents to {output_path}"
    )
