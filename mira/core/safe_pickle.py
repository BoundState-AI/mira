#!/usr/bin/env python3
"""
Module: Safe Pickle Loader
Purpose: SHA-256 validated pickle deserialization for FAISS companion files.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements)
Safety Critical: True

All pickle files loaded at runtime SHOULD use safe_pickle_load() to validate
integrity via a sidecar .sha256 file before deserialization.

Sidecar format:  <hex_sha256>  <filename>
Example:         a1b2c3...  mua_bok_v2_metadata.pkl

Build scripts that produce .pkl files SHOULD call write_checksum_sidecar()
to generate the sidecar. This ties into the runtime_assets.py manifest
pattern used across the MIRA platform.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum_sidecar(pkl_path: Path) -> Path:
    """Write a .sha256 sidecar file alongside a pickle file.

    Call this from build/indexing scripts after writing a .pkl file.

    Returns:
        Path to the sidecar file.
    """
    pkl_path = Path(pkl_path)
    sidecar = pkl_path.with_suffix(pkl_path.suffix + ".sha256")
    sha = _sha256_file(pkl_path)
    sidecar.write_text(f"{sha}  {pkl_path.name}\n", encoding="utf-8")
    logger.info("[SAFE_PICKLE] Wrote checksum sidecar: %s", sidecar)
    return sidecar


def safe_pickle_load(
    pkl_path: Path,
    *,
    require_checksum: bool = False,
) -> Any:
    """Load a pickle file with optional SHA-256 sidecar validation.

    Args:
        pkl_path: Path to the .pkl file.
        require_checksum: If True, raise FileNotFoundError when the sidecar
            is missing instead of falling through with a warning.

    Returns:
        Deserialized Python object.

    Raises:
        FileNotFoundError: If pkl_path doesn't exist, or if require_checksum
            is True and the sidecar is missing.
        RuntimeError: If checksum validation fails (possible tampering).
    """
    pkl_path = Path(pkl_path)
    if not pkl_path.exists():
        raise FileNotFoundError(f"Pickle file not found: {pkl_path}")

    sidecar = pkl_path.with_suffix(pkl_path.suffix + ".sha256")

    if sidecar.exists():
        expected_sha = sidecar.read_text(encoding="utf-8").strip().split()[0]
        actual_sha = _sha256_file(pkl_path)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Pickle integrity check FAILED for {pkl_path.name}: "
                f"expected {expected_sha}, got {actual_sha}. "
                f"File may have been tampered with. Re-run the build script "
                f"to regenerate this artifact."
            )
        logger.debug("[SAFE_PICKLE] Checksum verified: %s", pkl_path.name)
    elif require_checksum:
        raise FileNotFoundError(
            f"Checksum sidecar required but not found: {sidecar}. "
            f"Re-run the build script with write_checksum_sidecar() enabled."
        )
    else:
        logger.warning(
            "[SAFE_PICKLE] No checksum sidecar for %s — loading without "
            "integrity validation. Run build script to generate sidecar.",
            pkl_path.name,
        )

    with pkl_path.open("rb") as f:
        return pickle.load(f)  # noqa: S301
