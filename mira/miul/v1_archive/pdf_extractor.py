#!/usr/bin/env python3
"""
Module: Pdf Extractor
Purpose: PDF BOM Extraction utilities for MIUL pipeline.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-134 (Error handling)
Safety Critical: False
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import pandas as pd

# Timeout for pdfplumber operations (pdfminer can hang on certain PDFs)
PDFPLUMBER_TIMEOUT_SECONDS = 10

# Suppress pdfminer DEBUG logging which floods output and looks like an endless loop
logging.getLogger('pdfminer').setLevel(logging.WARNING)
logging.getLogger('pdfminer.psparser').setLevel(logging.WARNING)
logging.getLogger('pdfminer.pdfparser').setLevel(logging.WARNING)
logging.getLogger('pdfminer.pdfinterp').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def _try_import_camelot():
    try:
        import camelot  # type: ignore
        return camelot
    except Exception:
        return None


def _try_import_pdfplumber():
    try:
        import pdfplumber  # type: ignore
        return pdfplumber
    except Exception:
        return None


def _try_import_ocr():
    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore
        return pytesseract, convert_from_path
    except Exception:
        return None


class BOMExtractor:
    """Extract indentured BOM tables from drawing PDFs."""

    def __init__(self, max_pages: int = 10, silence_logs: bool = True) -> None:
        self.camelot = _try_import_camelot()
        self.pdfplumber = _try_import_pdfplumber()
        self.max_pages = max(1, int(max_pages))
        if silence_logs:
            # Reduce noisy third‑party logging (avoids apparent "infinite" loops of debug output)
            for name in (
                "pdfminer",
                "pdfminer.psparser",
                "pdfminer.pdfparser",
                "pdfplumber",
                "camelot",
                "python_multipart",
            ):
                try:
                    logging.getLogger(name).setLevel(logging.WARNING)
                except Exception:
                    pass
        # Optional OCR stack
        self._ocr = _try_import_ocr()

    def extract_tables(self, path: Path) -> List[pd.DataFrame]:
        """Extract tables as DataFrames using Camelot when available.

        Returns an empty list when no tables found or Camelot unavailable.
        """
        dfs: List[pd.DataFrame] = []
        if not self.camelot:
            return dfs

        # Only parse the first N pages to avoid long runs on large PDFs
        page_sel = f"1-{self.max_pages}"
        for flavor in ["lattice", "stream"]:
            try:
                tables = self.camelot.read_pdf(str(path), pages=page_sel, flavor=flavor)
                for t in tables:
                    try:
                        df = t.df
                        if not df.empty:
                            dfs.append(df)
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Camelot {flavor} failed for {path}: {e}")
        return dfs

    def _normalize_headers(self, row: List[Any]) -> List[str]:
        headers: List[str] = []
        for c in row:
            s = str(c or "").strip().lower()
            s = re.sub(r"\s+", " ", s)
            headers.append(s)
        return headers

    def _parse_bom_table(self, df: pd.DataFrame, drawing_name: str) -> pd.DataFrame:
        """Parse a table into a BOM DataFrame if it contains part/qty headers."""
        if df.empty:
            return pd.DataFrame(columns=["Part Number", "Quantity", "Drawing"])

        header_idx = None
        for i in range(min(6, len(df))):
            headers = self._normalize_headers(df.iloc[i].tolist())
            row_text = " ".join(headers)
            if ("part" in row_text) and ("qty" in row_text or "quantity" in row_text):
                header_idx = i
                break

        if header_idx is None:
            return pd.DataFrame(columns=["Part Number", "Quantity", "Drawing"])

        headers = self._normalize_headers(df.iloc[header_idx].tolist())

        # Map headers to canonical fields
        col_map = {}
        for j, h in enumerate(headers):
            if "part" in h and ("no" in h or "number" in h):
                col_map[j] = "Part Number"
            elif "qty" in h or "quantity" in h:
                col_map[j] = "Quantity"

        if not col_map:
            return pd.DataFrame(columns=["Part Number", "Quantity", "Drawing"])

        rows: List[dict] = []
        for i in range(header_idx + 1, len(df)):
            row = df.iloc[i].tolist()
            if not any(str(c).strip() for c in row):
                continue
            out: dict = {"Drawing": drawing_name}
            for j, val in enumerate(row):
                if j in col_map:
                    key = col_map[j]
                    sval = str(val).strip()
                    if sval and sval.lower() != "nan":
                        if key == "Quantity":
                            try:
                                out[key] = float(sval)
                            except Exception:
                                out[key] = sval
                        else:
                            out[key] = sval
            if out.get("Part Number"):
                rows.append(out)

        if not rows:
            return pd.DataFrame(columns=["Part Number", "Quantity", "Drawing"])

        bom_df = pd.DataFrame(rows)
        # Ensure required columns exist
        for col in ["Part Number", "Quantity", "Drawing"]:
            if col not in bom_df.columns:
                bom_df[col] = "" if col != "Quantity" else 0
        return bom_df[["Part Number", "Quantity", "Drawing"]]

    def extract_bom(self, path: Path) -> pd.DataFrame:
        """High-level: extract BOM from a single PDF drawing."""
        drawing_name = path.stem
        # Try tables via Camelot
        for table_df in self.extract_tables(path):
            bom = self._parse_bom_table(table_df, drawing_name)
            if not bom.empty:
                return bom

        # Fallback: pdfplumber text parsing (very heuristic, capped by max_pages)
        # Wrapped in timeout to prevent pdfminer hangs
        if self.pdfplumber:
            def _extract_with_pdfplumber():
                import pdfplumber  # type: ignore
                rows: List[dict] = []
                with pdfplumber.open(str(path)) as pdf:
                    for idx, page in enumerate(pdf.pages):
                        if idx >= self.max_pages:
                            break
                        text = page.extract_text() or ""
                        # Simple heuristic: lines with 'PN' and quantity tokens
                        for line in text.splitlines():
                            line_l = line.lower()
                            if re.search(r"\b(qty|quantity)\b", line_l) and re.search(r"\b(part|pn)\b", line_l):
                                # skip header lines
                                continue
                            m = re.search(r"(pn|part)\s*[:#-]?\s*([A-Z0-9\-_/]+).*?(qty|quantity)\s*[:#-]?\s*([0-9]+(?:\.[0-9]+)?)",
                                          line_l)
                            if m:
                                pn = m.group(2).upper()
                                qty = m.group(4)
                                try:
                                    qty_v: Any = float(qty)
                                except Exception:
                                    qty_v = qty
                                rows.append({"Part Number": pn, "Quantity": qty_v, "Drawing": drawing_name})
                return rows

            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_extract_with_pdfplumber)
                    try:
                        rows = future.result(timeout=PDFPLUMBER_TIMEOUT_SECONDS)
                        if rows:
                            return pd.DataFrame(rows)
                    except FuturesTimeoutError:
                        logger.warning(f"pdfplumber timed out after {PDFPLUMBER_TIMEOUT_SECONDS}s on {path}")
            except Exception as e:
                logger.debug(f"pdfplumber fallback failed for {path}: {e}")

        # OCR fallback if enabled and available
        if self._ocr:
            try:
                pytesseract, convert_from_path = self._ocr
                rows: List[dict] = []
                images = convert_from_path(str(path), first_page=1, last_page=self.max_pages, dpi=300)
                for img in images:
                    text = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
                    text = re.sub(r"\s+", " ", text)
                    for line in text.split("\n"):
                        line_l = line.lower()
                        if re.search(r"\b(qty|quantity)\b", line_l) and re.search(r"\b(part|pn)\b", line_l):
                            continue
                        m = re.search(r"(pn|part)\s*[:#-]?\s*([A-Z0-9\-_/]+).*?(qty|quantity)\s*[:#-]?\s*([0-9]+(?:\.[0-9]+)?)",
                                      line_l)
                        if m:
                            pn = m.group(2).upper()
                            qty = m.group(4)
                            try:
                                qty_v: Any = float(qty)
                            except Exception:
                                qty_v = qty
                            rows.append({"Part Number": pn, "Quantity": qty_v, "Drawing": drawing_name})
                if rows:
                    return pd.DataFrame(rows)
            except Exception as e:
                logger.debug(f"OCR fallback failed for {path}: {e}")

        # Nothing found
        return pd.DataFrame(columns=["Part Number", "Quantity", "Drawing"])
