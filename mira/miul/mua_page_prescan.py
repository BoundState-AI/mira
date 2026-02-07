#!/usr/bin/env python3
"""
Module: Mua Page Prescan
Purpose: MUA PDF Page Pre-Scanner for Cost Optimization.

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

import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

import fitz  # PyMuPDF

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

LOGGER = logging.getLogger(__name__)

# Labeled markers: (label, regex_pattern)
# Labels are used for tracking which markers were found
MUA_MARKERS = [
    ("MUA_NUMBER", r"MUA\s*[-#:]?\s*\d"),
    ("TITLE", r"MATERIAL\s+USAGE\s+AGREEMENT"),
    ("CATEGORY", r"CATEGORY\s*[:\s]*[I]{1,3}"),
    ("DETERMINATION", r"DETERMINATION\s*[:\s]"),
    ("RATIONALE", r"RATIONALE\s*[:\s]"),
    ("APPLICATION", r"APPLICATION\s*[:\s]"),
    ("MATERIAL", r"MATERIAL\s+DESIGNATION"),
    ("ENVIRONMENT", r"ENVIRONMENT\s*[:\s]"),
    ("APPROVED", r"APPROVED\s*BY"),
    ("DISPOSITION", r"DISPOSITION\s*[:\s]"),
]

# Title markers indicate this is actually an MUA page (not an attachment)
TITLE_MARKERS = {"MUA_NUMBER", "TITLE", "CATEGORY"}

# Minimum text per page to consider it a text-based PDF (vs scanned image)
MIN_TEXT_PER_PAGE = 100


@dataclass
class PrescanResult:
    """Result of pre-scanning a single PDF."""

    file: str
    total_pages: int
    relevant_pages: List[int]  # 0-indexed
    markers_found: Dict[str, List[int]]  # label -> [page_nums]
    is_scanned: bool  # True if PDF appears to be scanned images
    has_title_marker: bool  # True if at least one title marker found


def prescan_pdf(pdf_path: Path) -> PrescanResult:
    """Pre-scan a PDF to identify pages with MUA content.

    Args:
        pdf_path: Path to PDF file to scan

    Returns:
        PrescanResult with 0-indexed page numbers.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    relevant_pages: Set[int] = set()
    markers_by_page: Dict[str, List[int]] = {}
    total_text_length = 0

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text()
        total_text_length += len(text)
        text_upper = text.upper()

        for label, pattern in MUA_MARKERS:
            if re.search(pattern, text_upper, re.IGNORECASE):
                relevant_pages.add(page_num)  # 0-indexed

                if label not in markers_by_page:
                    markers_by_page[label] = []
                markers_by_page[label].append(page_num)

    doc.close()

    # Detect scanned PDFs (mostly images, little extractable text)
    is_scanned = total_text_length < MIN_TEXT_PER_PAGE * total_pages

    # Check if any title marker was found (confirms this is MUA content)
    has_title_marker = any(label in markers_by_page for label in TITLE_MARKERS)

    # Fallback logic
    if is_scanned:
        # Scanned PDF: send first 3 pages (can't detect markers)
        relevant_pages = {0, 1, 2}
        LOGGER.info(f"{pdf_path.name}: scanned PDF, defaulting to pages 0-2")
    elif not has_title_marker:
        # No title marker: might be wrong PDF or all attachments
        # Conservative: send first 2 pages
        relevant_pages = {0, 1}
        LOGGER.warning(
            f"{pdf_path.name}: no title marker found, defaulting to pages 0-1"
        )
    else:
        # Always include page 0 (MUA header)
        relevant_pages.add(0)

    return PrescanResult(
        file=pdf_path.name,
        total_pages=total_pages,
        relevant_pages=sorted(relevant_pages),
        markers_found=markers_by_page,
        is_scanned=is_scanned,
        has_title_marker=has_title_marker,
    )


def batch_prescan(pdf_dir: Path, output_path: Path) -> Dict:
    """Pre-scan all PDFs in directory and save mapping file.

    Output format (JSONL):
        {"file": "1001-0021.pdf", "pages": [0, 1]}
        {"file": "1001-0022.pdf", "pages": [0, 1, 2]}

    All page numbers are 0-indexed.

    Args:
        pdf_dir: Directory containing PDF files
        output_path: Path to write JSONL mapping file

    Returns:
        Dictionary with scan statistics
    """
    pdfs = list(pdf_dir.glob("*.pdf"))
    stats: Counter = Counter()

    with open(output_path, "w", encoding="utf-8") as f:
        for pdf_path in pdfs:
            try:
                result = prescan_pdf(pdf_path)
                f.write(
                    json.dumps(
                        {
                            "file": result.file,
                            "pages": result.relevant_pages,
                            "total_pages": result.total_pages,
                            "is_scanned": result.is_scanned,
                            "has_title": result.has_title_marker,
                        }
                    )
                    + "\n"
                )

                stats["scanned"] += 1
                stats["total_pages"] += result.total_pages
                stats["relevant_pages"] += len(result.relevant_pages)
                if result.is_scanned:
                    stats["scanned_pdfs"] += 1
                if not result.has_title_marker:
                    stats["no_title"] += 1

            except Exception as e:
                LOGGER.error(f"Error scanning {pdf_path}: {e}")
                stats["errors"] += 1

    return {
        "pdfs_scanned": stats["scanned"],
        "errors": stats["errors"],
        "scanned_pdfs": stats["scanned_pdfs"],
        "no_title_marker": stats["no_title"],
        "avg_total_pages": stats["total_pages"] / max(stats["scanned"], 1),
        "avg_relevant_pages": stats["relevant_pages"] / max(stats["scanned"], 1),
        "page_reduction_pct": (
            1 - stats["relevant_pages"] / max(stats["total_pages"], 1)
        )
        * 100,
    }


def load_page_mapping(mapping_path: Path) -> Dict[str, List[int]]:
    """Load page mapping from JSONL file.

    Args:
        mapping_path: Path to JSONL mapping file

    Returns:
        Dict of {filename: [page_numbers]} with 0-indexed pages.
    """
    mapping = {}
    with open(mapping_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                mapping[record["file"]] = record["pages"]
    return mapping


def main():
    """Main entry point for CLI usage."""
    if len(sys.argv) < 2:
        print("Usage: python -m mira.miul.mua_page_prescan <pdf_dir> [output.jsonl]")
        print(
            "Example: python -m mira.miul.mua_page_prescan data/mua_pdfs data/mua_page_mapping.jsonl"
        )
        sys.exit(1)

    pdf_dir = Path(sys.argv[1])
    output = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path("data/mua_page_mapping.jsonl")
    )

    print(f"Pre-scanning PDFs in: {pdf_dir}")
    print(f"Output mapping: {output}")

    # Ensure output directory exists
    output.parent.mkdir(parents=True, exist_ok=True)

    stats = batch_prescan(pdf_dir, output)

    print(f"\n{'='*50}")
    print(f"PDFs scanned:        {stats['pdfs_scanned']}")
    print(f"Errors:              {stats['errors']}")
    print(f"Scanned (image) PDFs:{stats['scanned_pdfs']}")
    print(f"No title marker:     {stats['no_title_marker']}")
    print(f"Avg pages/PDF:       {stats['avg_total_pages']:.1f}")
    print(f"Avg relevant pages:  {stats['avg_relevant_pages']:.1f}")
    print(f"Page reduction:      {stats['page_reduction_pct']:.1f}%")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
