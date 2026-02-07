#!/usr/bin/env python3
"""
Module: Ingest
Purpose: MIUL Builder v2.2 - Phase 1: Ingest

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

import base64
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

from .models import PageMetadata, RenderParams


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_DPI = 150
MAX_PIXELS = 7500  # Claude's 8000px limit with margin


# =============================================================================
# Page Image Container
# =============================================================================

@dataclass
class PageImage:
    """A rendered page image with metadata."""
    page_id: str               # sha256(image_bytes)[:16]
    metadata: PageMetadata
    image_bytes: bytes         # PNG image data
    image_base64: str          # Base64-encoded for API calls


# =============================================================================
# Core Functions
# =============================================================================

def compute_page_id(image_bytes: bytes) -> str:
    """
    Generate content-based page ID from image bytes.

    Per spec v2.2: page_id = sha256(image_bytes)[:16]
    """
    return hashlib.sha256(image_bytes).hexdigest()[:16]


def calculate_scale_factor(
    page_width: float,
    page_height: float,
    target_dpi: int,
    max_pixels: int = MAX_PIXELS,
) -> tuple[float, int]:
    """
    Calculate the scale factor needed to keep image within max_pixels.

    Args:
        page_width: Page width in points (72 points = 1 inch)
        page_height: Page height in points
        target_dpi: Requested DPI
        max_pixels: Maximum dimension in pixels

    Returns:
        (effective_scale, effective_dpi)
    """
    # Calculate dimensions at target DPI
    # Points to inches: width_inches = width_points / 72
    # Inches to pixels: width_px = width_inches * dpi
    scale = target_dpi / 72.0
    width_px = page_width * scale
    height_px = page_height * scale

    max_dim = max(width_px, height_px)

    if max_dim <= max_pixels:
        return (1.0, target_dpi)

    # Need to downscale
    downscale_factor = max_pixels / max_dim
    effective_dpi = int(target_dpi * downscale_factor)
    effective_scale = downscale_factor

    return (effective_scale, effective_dpi)


def render_page_to_image(
    page: 'fitz.Page',
    target_dpi: int = DEFAULT_DPI,
    max_pixels: int = MAX_PIXELS,
) -> tuple[bytes, RenderParams, int, int]:
    """
    Render a PDF page to PNG image bytes.

    Args:
        page: PyMuPDF page object
        target_dpi: Requested DPI
        max_pixels: Maximum dimension in pixels

    Returns:
        (image_bytes, render_params, width_px, height_px)
    """
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required for PDF rendering")

    rect = page.rect
    page_width = rect.width
    page_height = rect.height

    # Calculate scale factor
    effective_scale, effective_dpi = calculate_scale_factor(
        page_width, page_height, target_dpi, max_pixels
    )

    # Create transformation matrix
    mat = fitz.Matrix(effective_dpi / 72.0, effective_dpi / 72.0)

    # Render to pixmap
    pixmap = page.get_pixmap(matrix=mat, alpha=False)

    # Convert to PNG bytes
    image_bytes = pixmap.tobytes("png")

    render_params = RenderParams(
        requested_dpi=target_dpi,
        effective_scale=effective_scale,
        rotation=int(page.rotation),
    )

    return (image_bytes, render_params, pixmap.width, pixmap.height)


# =============================================================================
# PDF Ingestion
# =============================================================================

def ingest_pdf(
    pdf_path: Path,
    target_dpi: int = DEFAULT_DPI,
    max_pixels: int = MAX_PIXELS,
) -> Iterator[PageImage]:
    """
    Ingest a PDF and yield PageImage for each page.

    Args:
        pdf_path: Path to PDF file
        target_dpi: Target DPI for rendering (default 150)
        max_pixels: Maximum dimension in pixels (default 7500)

    Yields:
        PageImage for each page

    Raises:
        RuntimeError: If PyMuPDF is not available
        FileNotFoundError: If PDF file doesn't exist
        ValueError: If PDF is corrupt or unreadable
    """
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required for PDF ingestion")

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise ValueError(f"Failed to open PDF {pdf_path}: {e}")

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]

            # Render page to image
            image_bytes, render_params, width_px, height_px = render_page_to_image(
                page, target_dpi, max_pixels
            )

            # Generate content-based page ID
            page_id = compute_page_id(image_bytes)

            # Create metadata
            metadata = PageMetadata(
                page_id=page_id,
                pdf_path=pdf_path,
                page_number=page_index,
                render_params=render_params,
                width_px=width_px,
                height_px=height_px,
            )

            # Encode image to base64
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')

            yield PageImage(
                page_id=page_id,
                metadata=metadata,
                image_bytes=image_bytes,
                image_base64=image_base64,
            )

    finally:
        doc.close()


def ingest_directory(
    directory: Path,
    pattern: str = "*.pdf",
    target_dpi: int = DEFAULT_DPI,
    max_pixels: int = MAX_PIXELS,
) -> Iterator[tuple[Path, list[PageImage]]]:
    """
    Ingest all PDFs from a directory.

    Args:
        directory: Directory to search
        pattern: Glob pattern for PDF files
        target_dpi: Target DPI for rendering
        max_pixels: Maximum dimension in pixels

    Yields:
        (pdf_path, list of PageImage) tuples
    """
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    for pdf_path in sorted(directory.glob(pattern)):
        try:
            pages = list(ingest_pdf(pdf_path, target_dpi, max_pixels))
            yield pdf_path, pages
        except ValueError as e:
            # Skip corrupt files but log the error
            print(f"Warning: Skipping {pdf_path}: {e}")
            continue


# =============================================================================
# Utility Functions
# =============================================================================

def get_pdf_page_count(pdf_path: Path) -> int:
    """Get the number of pages in a PDF."""
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required")

    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def get_pdf_metadata(pdf_path: Path) -> dict:
    """Get PDF document metadata."""
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required")

    doc = fitz.open(pdf_path)
    try:
        return {
            "page_count": len(doc),
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "producer": doc.metadata.get("producer", ""),
            "creation_date": doc.metadata.get("creationDate", ""),
            "mod_date": doc.metadata.get("modDate", ""),
        }
    finally:
        doc.close()


def extract_text_from_page(pdf_path: Path, page_index: int) -> str:
    """
    Extract raw text from a specific PDF page.

    This is used for ground truth anchoring in Phase 2.
    """
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required")

    doc = fitz.open(pdf_path)
    try:
        if page_index >= len(doc):
            raise ValueError(f"Page index {page_index} out of range for {pdf_path}")

        page = doc[page_index]
        return page.get_text()
    finally:
        doc.close()


def extract_text_from_pdf(pdf_path: Path) -> list[str]:
    """
    Extract raw text from all pages of a PDF.

    Returns:
        List of text strings, one per page
    """
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required")

    doc = fitz.open(pdf_path)
    try:
        texts = []
        for page in doc:
            texts.append(page.get_text())
        return texts
    finally:
        doc.close()


# =============================================================================
# Batch Processing
# =============================================================================

@dataclass
class IngestResult:
    """Result of batch PDF ingestion."""
    pdf_path: Path
    page_images: list[PageImage]
    page_count: int
    success: bool
    error: Optional[str] = None


def ingest_pdfs_batch(
    pdf_paths: list[Path],
    target_dpi: int = DEFAULT_DPI,
    max_pixels: int = MAX_PIXELS,
) -> Iterator[IngestResult]:
    """
    Ingest multiple PDFs and yield results.

    Args:
        pdf_paths: List of PDF file paths
        target_dpi: Target DPI for rendering
        max_pixels: Maximum dimension in pixels

    Yields:
        IngestResult for each PDF
    """
    for pdf_path in pdf_paths:
        try:
            pages = list(ingest_pdf(pdf_path, target_dpi, max_pixels))
            yield IngestResult(
                pdf_path=pdf_path,
                page_images=pages,
                page_count=len(pages),
                success=True,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            yield IngestResult(
                pdf_path=pdf_path,
                page_images=[],
                page_count=0,
                success=False,
                error=str(e),
            )
