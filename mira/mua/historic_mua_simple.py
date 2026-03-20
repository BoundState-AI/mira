#!/usr/bin/env python3
"""
Module: Historic Mua Simple
Purpose: Simple historic MUA loader without FAISS dependency.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

LOGGER = logging.getLogger(__name__)

DEFAULT_HISTORIC_INDEX_DIR = Path(os.getenv("MUA_HISTORIC_INDEX_DIR", "mira/databases/mua_faiss_db"))


class SimpleHistoricMUALoader:
    """Lightweight loader for historic MUA metadata (no FAISS)."""

    def __init__(self, index_dir: Optional[Path] = None):
        self.index_dir = Path(index_dir or DEFAULT_HISTORIC_INDEX_DIR)

        # Load historic MUA records (JSONL)
        jsonl_path = self.index_dir / "historic_mua.jsonl"
        if not jsonl_path.exists():
            raise FileNotFoundError(f"Historic MUA JSONL not found: {jsonl_path}")

        self.mua_records: Dict[str, Dict[str, Any]] = {}
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    file_hash = record.get("file_hash")
                    if file_hash:
                        self.mua_records[file_hash] = record
                except json.JSONDecodeError:
                    continue

        LOGGER.info(f"Loaded {len(self.mua_records)} historic MUA records")

    @property
    def records(self) -> List[Dict[str, Any]]:
        """Get all MUA records as a list."""
        return list(self.mua_records.values())

    def get_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Get MUA record by file hash."""
        return self.mua_records.get(file_hash)


_SIMPLE_LOADER: Optional[SimpleHistoricMUALoader] = None
_LOADER_ERROR: Optional[Exception] = None


def get_simple_historic_loader() -> Optional[SimpleHistoricMUALoader]:
    """Get or create the singleton simple historic MUA loader."""
    global _SIMPLE_LOADER, _LOADER_ERROR

    if os.getenv("MUA_DISABLE_HISTORIC_RETRIEVAL") == "1":
        return None

    if _SIMPLE_LOADER is not None:
        return _SIMPLE_LOADER
    if _LOADER_ERROR is not None:
        return None

    try:
        index_dir = Path(os.getenv("MUA_HISTORIC_INDEX_DIR", DEFAULT_HISTORIC_INDEX_DIR))
        _SIMPLE_LOADER = SimpleHistoricMUALoader(index_dir=index_dir)
        LOGGER.info("Loaded simple historic MUA loader from %s", index_dir)
    except Exception as exc:
        _LOADER_ERROR = exc
        LOGGER.warning("Failed to load simple historic MUA loader: %s", exc)
        return None

    return _SIMPLE_LOADER


__all__ = [
    "SimpleHistoricMUALoader",
    "get_simple_historic_loader",
]
