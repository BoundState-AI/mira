#!/usr/bin/env python3
"""
Module: Barcode
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

from __future__ import annotations

import logging
import uuid
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz
    import numpy as np

__all__ = ["scan_barcode", "generate_separator_sheet", "SEPARATOR_BARCODE_PREFIX"]

logger = logging.getLogger(__name__)

# Barcode prefix for ATHENA separator sheets
SEPARATOR_BARCODE_PREFIX = "ATHENA-SEP-"


def scan_barcode(
    page: "fitz.Page",
    dpi: int = 150,
    prefix: str = SEPARATOR_BARCODE_PREFIX,
) -> str | None:
    """Scan page for ATHENA separator barcode.

    Uses pyzbar for barcode detection - fast and reliable.
    No LLM needed for separator detection.

    Args:
        page: PyMuPDF page to scan
        dpi: Resolution for rendering (150 is fast, sufficient)
        prefix: Expected barcode prefix

    Returns:
        Barcode data if ATHENA separator found, else None
    """
    try:
        from pyzbar import pyzbar
        import numpy as np
    except ImportError:
        logger.error("pyzbar not installed - run: pip install pyzbar")
        return None

    # Render page to image
    mat = page.get_matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)

    # Convert to numpy array
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )

    # Decode barcodes
    barcodes = pyzbar.decode(img)

    for bc in barcodes:
        try:
            data = bc.data.decode("utf-8")
            if data.startswith(prefix):
                logger.debug(f"Found separator barcode: {data}")
                return data
        except UnicodeDecodeError:
            continue

    return None


def is_separator_page(
    page: "fitz.Page",
    dpi: int = 150,
    prefix: str = SEPARATOR_BARCODE_PREFIX,
) -> bool:
    """Check if page is a separator sheet.

    Args:
        page: PyMuPDF page to check
        dpi: Resolution for rendering
        prefix: Expected barcode prefix

    Returns:
        True if page contains ATHENA separator barcode
    """
    return scan_barcode(page, dpi, prefix) is not None


def extract_separator_id(barcode_data: str) -> str | None:
    """Extract UUID from separator barcode.

    Args:
        barcode_data: Full barcode string (e.g., "ATHENA-SEP-uuid...")

    Returns:
        UUID string or None if invalid
    """
    if not barcode_data.startswith(SEPARATOR_BARCODE_PREFIX):
        return None

    return barcode_data[len(SEPARATOR_BARCODE_PREFIX):]


def generate_separator_sheet(
    output_path: Path | str | None = None,
    separator_id: str | None = None,
    folder_name: str = "",
    date_range_start: str = "",
    date_range_end: str = "",
    doc_count: str = "",
    notes: str = "",
) -> bytes:
    """Generate printable separator sheet PDF with barcode.

    Args:
        output_path: Path to save PDF (if None, returns bytes)
        separator_id: UUID for separator (generated if None)
        folder_name: Pre-filled folder name
        date_range_start: Pre-filled start date
        date_range_end: Pre-filled end date
        doc_count: Pre-filled doc count
        notes: Pre-filled notes

    Returns:
        PDF bytes
    """
    try:
        import barcode
        from barcode.writer import ImageWriter
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
    except ImportError:
        raise ImportError(
            "Required packages not installed. Run: pip install python-barcode reportlab pillow"
        )

    # Generate separator ID if not provided
    if separator_id is None:
        separator_id = str(uuid.uuid4())

    barcode_data = f"{SEPARATOR_BARCODE_PREFIX}{separator_id}"

    # Create PDF
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Title
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 1 * inch, "ATHENA SEPARATOR SHEET")

    # Generate barcode image
    code128 = barcode.get_barcode_class("code128")
    barcode_img_buffer = BytesIO()
    code128_instance = code128(barcode_data, writer=ImageWriter())
    code128_instance.write(barcode_img_buffer)
    barcode_img_buffer.seek(0)

    # Draw barcode
    from reportlab.lib.utils import ImageReader
    barcode_img = ImageReader(barcode_img_buffer)
    c.drawImage(
        barcode_img,
        1.5 * inch,
        height - 3 * inch,
        width=5 * inch,
        height=1 * inch,
        preserveAspectRatio=True,
    )

    # Barcode ID text
    c.setFont("Courier", 10)
    c.drawCentredString(width / 2, height - 3.2 * inch, barcode_data)

    # Horizontal line
    c.setStrokeColor(colors.black)
    c.setLineWidth(1)
    c.line(0.75 * inch, height - 3.5 * inch, width - 0.75 * inch, height - 3.5 * inch)

    # Form fields
    y = height - 4 * inch
    field_height = 0.6 * inch

    def draw_field(label: str, value: str, y_pos: float) -> float:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1 * inch, y_pos, label)
        c.setFont("Helvetica", 12)
        c.drawString(2.5 * inch, y_pos, value if value else "_" * 40)
        c.line(2.5 * inch, y_pos - 3, 7.5 * inch, y_pos - 3)
        return y_pos - field_height

    y = draw_field("Folder Name:", folder_name, y)
    y = draw_field("Date Range:", f"{date_range_start} to {date_range_end}" if date_range_start or date_range_end else "", y)
    y = draw_field("Doc Count:", doc_count, y)

    # Notes section
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, y, "Notes:")
    y -= 0.3 * inch
    c.setFont("Helvetica", 12)
    if notes:
        # Wrap notes
        for line in notes.split("\n")[:3]:
            c.drawString(1 * inch, y, line[:80])
            y -= 0.25 * inch
    else:
        for _ in range(3):
            c.line(1 * inch, y, 7.5 * inch, y)
            y -= 0.35 * inch

    # Bottom line
    y -= 0.5 * inch
    c.line(0.75 * inch, y, width - 0.75 * inch, y)

    # Scanned by / Date
    y -= 0.4 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, y, "Scanned by:")
    c.line(2.5 * inch, y - 3, 4 * inch, y - 3)
    c.drawString(4.5 * inch, y, "Date:")
    c.line(5.25 * inch, y - 3, 7.5 * inch, y - 3)

    # Footer
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.gray)
    c.drawCentredString(
        width / 2, 0.5 * inch,
        "ATHENA Document Intelligence - BoundState AI"
    )

    c.save()

    # Get PDF bytes
    pdf_bytes = buffer.getvalue()

    # Save if path provided
    if output_path:
        output_path = Path(output_path)
        output_path.write_bytes(pdf_bytes)
        logger.info(f"Generated separator sheet: {output_path}")

    return pdf_bytes


def generate_batch_separators(
    count: int,
    output_dir: Path | str,
    prefix: str = "separator",
) -> list[Path]:
    """Generate multiple separator sheets for batch scanning.

    Args:
        count: Number of separator sheets to generate
        output_dir: Directory for output PDFs
        prefix: Filename prefix

    Returns:
        List of generated file paths
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for i in range(count):
        sep_id = str(uuid.uuid4())
        path = output_dir / f"{prefix}_{i+1:03d}_{sep_id[:8]}.pdf"
        generate_separator_sheet(path, sep_id)
        paths.append(path)
        logger.info(f"Generated {i+1}/{count}: {path.name}")

    return paths
