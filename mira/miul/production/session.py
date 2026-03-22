#!/usr/bin/env python3
"""
Module: V4 Session
Purpose: File-based session management for MIUL v4 extraction + HITL review.

Stores extraction results, review state, and audit trail as JSON files
in a per-session directory under temp/miul_sessions/{extraction_id}/.

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extractor import ExtractionResult, identify_review_items

LOGGER = logging.getLogger(__name__)

# Default session storage root
_SESSION_ROOT = Path("C:/BoundState/temp/miul_sessions")
_DRAWING_VARIANT_SUFFIX_RE = re.compile(r"^(?:[A-Z]|[A-Z]?\d+(?:/\d+)?)$")
_DRAWING_TOKEN_RE = re.compile(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)+")


def get_session_root() -> Path:
    """Return session storage root, creating if needed."""
    _SESSION_ROOT.mkdir(parents=True, exist_ok=True)
    return _SESSION_ROOT


def _norm_token(value: Any) -> str:
    if value is None:
        return ""
    token = str(value).strip().upper()
    if token in {"", "NAN", "NONE", "NULL", "<NA>"}:
        return ""
    token = re.sub(r"\s+", " ", token)
    return token


def _drawing_match_keys(value: Any) -> set[str]:
    drawing = _norm_token(value)
    if not drawing:
        return set()

    keys: set[str] = {drawing}
    parts = drawing.split("-")
    while len(parts) >= 3 and _DRAWING_VARIANT_SUFFIX_RE.fullmatch(parts[-1]):
        parts = parts[:-1]
        keys.add("-".join(parts))
    return {k for k in keys if k}


def _source_file_match_keys(source_file: Any) -> set[str]:
    source = str(source_file or "").strip()
    if not source:
        return set()

    path = Path(source)
    keys: set[str] = set()
    for value in (source, path.name, path.stem):
        token = _norm_token(value)
        if token:
            keys.add(token)

    stem = _norm_token(path.stem)
    if stem:
        for sep in (".DRW", "_DRW", "_DRW_", "_DRW-"):
            if sep in stem:
                prefix = _norm_token(stem.split(sep)[0])
                if prefix:
                    keys.update(_drawing_match_keys(prefix))

        for token in _DRAWING_TOKEN_RE.findall(stem):
            norm = _norm_token(token)
            if norm:
                keys.update(_drawing_match_keys(norm))

        first_underscore = _norm_token(stem.split("_")[0])
        if first_underscore:
            keys.update(_drawing_match_keys(first_underscore))

    return keys


def _source_file_exact_tokens(source_file: Any) -> set[str]:
    source = str(source_file or "").strip()
    if not source:
        return set()

    path = Path(source)
    tokens: set[str] = set()
    for value in (source, path.name, path.stem):
        token = _norm_token(value)
        if token:
            tokens.add(token)

    stem = _norm_token(path.stem)
    if not stem:
        return tokens

    for sep in (".DRW", "_DRW", "_DRW_", "_DRW-"):
        if sep in stem:
            prefix = _norm_token(stem.split(sep)[0])
            if prefix:
                tokens.add(prefix)

    for token in _DRAWING_TOKEN_RE.findall(stem):
        norm = _norm_token(token)
        if norm:
            tokens.add(norm)

    first_underscore = _norm_token(stem.split("_")[0])
    if first_underscore:
        tokens.add(first_underscore)

    return tokens


def _material_match_keys(source_file: Any, nha: Any) -> set[str]:
    keys = set()
    keys.update(_source_file_match_keys(source_file))
    keys.update(_drawing_match_keys(nha))
    return keys


def _extract_package_source_files(pkg: Dict[str, Any]) -> List[str]:
    source_files = [
        str(sf).strip()
        for sf in (pkg.get("source_files") or [])
        if str(sf).strip()
    ]
    if source_files:
        return sorted(set(source_files))

    inferred = []
    for material in pkg.get("materials", []) or []:
        if not isinstance(material, dict):
            continue
        source = str(material.get("source_file", "") or "").strip()
        if source:
            inferred.append(source)
    return sorted(set(inferred))


def _package_match_keys(pkg: Dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    keys.update(_drawing_match_keys(pkg.get("drawing_number", "")))
    for source_file in _extract_package_source_files(pkg):
        keys.update(_source_file_match_keys(source_file))
    return keys


def _package_exact_keys(pkg: Dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    drawing_number = _norm_token(pkg.get("drawing_number", ""))
    if drawing_number:
        keys.add(drawing_number)
    for source_file in _extract_package_source_files(pkg):
        keys.update(_source_file_exact_tokens(source_file))
    return keys


def _infer_drawing_id(source_file: Any, nha: Any = "") -> str:
    source = str(source_file or "").strip()
    if source:
        stem = _norm_token(Path(source).stem)
        if stem:
            for sep in (".DRW", "_DRW", "_DRW_", "_DRW-"):
                if sep in stem:
                    prefix = _norm_token(stem.split(sep)[0])
                    if prefix:
                        return prefix

            token_matches = _DRAWING_TOKEN_RE.findall(stem)
            if token_matches:
                first_match = _norm_token(token_matches[0])
                if first_match:
                    return first_match

            first_underscore = _norm_token(stem.split("_")[0])
            if first_underscore:
                return first_underscore

            return stem

    nha_norm = _norm_token(nha)
    if nha_norm:
        return nha_norm
    return ""


def _review_item_keys(item: Dict[str, Any]) -> set[str]:
    """Return normalized lookup keys for a review item."""
    keys: set[str] = set()
    for raw in (item.get("item_id"), item.get("part_number")):
        token = _norm_token(raw)
        if token:
            keys.add(token)

    aliases = item.get("part_aliases") or []
    if isinstance(aliases, list):
        for alias in aliases:
            token = _norm_token(alias)
            if token:
                keys.add(token)
    return keys


# =============================================================================
# Session State
# =============================================================================

class V4Session:
    """
    File-backed MIUL v4 session.

    Stores three files per session:
      extraction.json  - raw ExtractionResult from vision extractor
      review.json      - review items, corrections, and approval state
      audit.json       - append-only audit trail
    """

    def __init__(self, extraction_id: str):
        self.extraction_id = extraction_id
        self._dir = get_session_root() / extraction_id
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def extraction_path(self) -> Path:
        return self._dir / "extraction.json"

    @property
    def review_path(self) -> Path:
        return self._dir / "review.json"

    @property
    def audit_path(self) -> Path:
        return self._dir / "audit.json"

    @property
    def status_path(self) -> Path:
        return self._dir / "status.json"

    @property
    def metadata_path(self) -> Path:
        return self._dir / "metadata.json"

    @property
    def exists(self) -> bool:
        return self._dir.exists()

    # ----- Status tracking -----

    def set_status(self, status: str, message: str = "", progress: int = 0,
                   summary: Optional[Dict[str, Any]] = None,
                   error: Optional[str] = None) -> None:
        """Update extraction status for polling."""
        data: Dict[str, Any] = {
            "extraction_id": self.extraction_id,
            "status": status,
            "message": message,
            "progress": progress,
            "updated_at": _now(),
        }
        if summary:
            data["summary"] = summary
        if error:
            data["error"] = error
        self._write(self.status_path, data)

    def get_status(self) -> Dict[str, Any]:
        """Read current extraction status."""
        data = self._read(self.status_path)
        if data:
            return data
        # Fallback: if no status file, check if extraction exists
        if self.extraction_path.exists():
            return {
                "extraction_id": self.extraction_id,
                "status": "complete",
                "message": "Extraction complete",
                "progress": 100,
            }
        return {
            "extraction_id": self.extraction_id,
            "status": "unknown",
            "message": "No status available",
            "progress": 0,
        }

    def set_owner_username(self, owner_username: str | None) -> None:
        """Persist the authenticated owner for authorization checks."""
        normalized = (owner_username or "").strip() or None
        metadata = self._read(self.metadata_path) or {}
        metadata["owner_username"] = normalized
        metadata.setdefault("extraction_id", self.extraction_id)
        metadata.setdefault("created_at", _now())
        metadata["updated_at"] = _now()
        self._write(self.metadata_path, metadata)

    def get_owner_username(self) -> Optional[str]:
        """Return the stored owner username, if any."""
        metadata = self._read(self.metadata_path) or {}
        raw = metadata.get("owner_username")
        if raw is None:
            return None
        normalized = str(raw).strip()
        return normalized or None

    # ----- Extraction -----

    def save_extraction(self, result: ExtractionResult) -> None:
        """Save extraction result and generate initial review state."""
        self._write(self.extraction_path, result.to_dict())

        # Generate review items from extraction
        review_data = identify_review_items(result)
        review_data["status"] = "in_review"
        review_data["approved_at"] = None
        review_data["approved_by"] = None
        self._write(self.review_path, review_data)

        # Initialize audit trail
        self._append_audit("extraction_saved", {
            "total_materials": len(result.materials),
            "drawing_packages": len(result.drawing_packages),
            "needs_review": review_data["summary"]["needs_review"],
            "auto_approved": review_data["summary"]["auto_approved"],
        })

    def load_extraction(self) -> Optional[ExtractionResult]:
        """Load extraction result from disk."""
        data = self._read(self.extraction_path)
        if data is None:
            return None
        return ExtractionResult.from_dict(data)

    # ----- Review -----

    def load_review(self) -> Optional[Dict[str, Any]]:
        """Load review state."""
        return self._read(self.review_path)

    def list_drawings(self) -> List[Dict[str, Any]]:
        """List drawing packages available in this extraction session."""
        extraction = self.load_extraction()
        if extraction is None:
            return []

        drawings: List[Dict[str, Any]] = []
        for idx, package in enumerate(extraction.drawing_packages or []):
            if not isinstance(package, dict):
                continue

            drawing_number = _norm_token(package.get("drawing_number", ""))
            source_files = _extract_package_source_files(package)
            drawing_id = drawing_number

            if not drawing_id and source_files:
                drawing_id = _norm_token(Path(source_files[0]).stem)
            if not drawing_id:
                drawing_id = f"DRAWING_{idx + 1}"

            materials = package.get("materials", []) or []
            drawings.append(
                {
                    "drawing_id": drawing_id,
                    "drawing_number": drawing_number,
                    "drawing_type": str(package.get("drawing_type") or ""),
                    "title": str(package.get("title") or ""),
                    "source_files": source_files,
                    "materials_count": len(materials),
                }
            )

        if not drawings:
            by_drawing: Dict[str, Dict[str, Any]] = {}
            for material in extraction.materials or []:
                source_file = str(getattr(material, "source_file", "") or "").strip()
                drawing_id = _infer_drawing_id(source_file, getattr(material, "nha", ""))
                if not drawing_id:
                    continue

                bucket = by_drawing.setdefault(
                    drawing_id,
                    {
                        "drawing_id": drawing_id,
                        "drawing_number": drawing_id,
                        "drawing_type": "",
                        "title": "",
                        "source_files": set(),
                        "materials_count": 0,
                    },
                )
                bucket["materials_count"] += 1
                if source_file:
                    bucket["source_files"].add(source_file)

            if not by_drawing:
                review = self.load_review() or {}
                for item in review.get("review_items", []):
                    if not isinstance(item, dict):
                        continue
                    source_file = str(item.get("source_file", "") or "").strip()
                    drawing_id = _infer_drawing_id(source_file, item.get("nha", ""))
                    if not drawing_id:
                        continue
                    bucket = by_drawing.setdefault(
                        drawing_id,
                        {
                            "drawing_id": drawing_id,
                            "drawing_number": drawing_id,
                            "drawing_type": "",
                            "title": "",
                            "source_files": set(),
                            "materials_count": 0,
                        },
                    )
                    bucket["materials_count"] += 1
                    if source_file:
                        bucket["source_files"].add(source_file)

            drawings = []
            for drawing_id in sorted(by_drawing.keys()):
                bucket = by_drawing[drawing_id]
                drawings.append(
                    {
                        "drawing_id": drawing_id,
                        "drawing_number": bucket["drawing_number"],
                        "drawing_type": bucket["drawing_type"],
                        "title": bucket["title"],
                        "source_files": sorted(bucket["source_files"]),
                        "materials_count": bucket["materials_count"],
                    }
                )

        drawings.sort(key=lambda d: d.get("drawing_id", ""))
        return drawings

    def remove_drawing(
        self,
        drawing_id: str,
        reviewer: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        """Remove one drawing package and regenerate review/extraction summaries."""
        extraction = self.load_extraction()
        if extraction is None:
            return {"removed": False, "error": "No extraction data found"}

        target = str(drawing_id or "").strip()
        if not target:
            return {"removed": False, "error": "No drawing identifier provided"}

        target_exact = _norm_token(target)
        target_exact_keys = {target_exact}
        target_exact_keys.update(_source_file_exact_tokens(target))
        target_fuzzy_keys = set(target_exact_keys)
        target_fuzzy_keys.update(_drawing_match_keys(target))
        target_fuzzy_keys.update(_source_file_match_keys(target))
        if not target_fuzzy_keys:
            return {"removed": False, "error": "Invalid drawing identifier"}

        removed_packages: List[Dict[str, Any]] = []
        kept_packages: List[Dict[str, Any]] = []
        removed_exact_keys: set[str] = set()
        removed_fuzzy_keys: set[str] = set()
        used_fuzzy_match = False

        # Pass 1: exact package key match (preferred, avoids over-broad removals).
        for package in extraction.drawing_packages or []:
            if not isinstance(package, dict):
                kept_packages.append(package)
                continue
            package_exact_keys = _package_exact_keys(package)
            if target_exact and target_exact in package_exact_keys:
                removed_packages.append(package)
                removed_exact_keys.update(package_exact_keys)
            elif target_exact_keys & package_exact_keys:
                removed_packages.append(package)
                removed_exact_keys.update(package_exact_keys)
            else:
                kept_packages.append(package)

        # Pass 2: fallback fuzzy match only if exact pass found nothing.
        if not removed_packages:
            kept_packages = []
            for package in extraction.drawing_packages or []:
                if not isinstance(package, dict):
                    kept_packages.append(package)
                    continue

                package_keys = _package_match_keys(package)
                if target_fuzzy_keys & package_keys:
                    used_fuzzy_match = True
                    removed_packages.append(package)
                    removed_fuzzy_keys.update(package_keys)
                    removed_exact_keys.update(_package_exact_keys(package))
                else:
                    kept_packages.append(package)

        if not removed_packages:
            for material in extraction.materials or []:
                source_file = getattr(material, "source_file", "")
                nha = getattr(material, "nha", "")
                material_exact_keys = set(_source_file_exact_tokens(source_file))
                material_exact_keys.update(_drawing_match_keys(nha))
                material_fuzzy_keys = _material_match_keys(source_file, nha)

                if target_exact and target_exact in material_exact_keys:
                    removed_exact_keys.update(material_exact_keys)
                    removed_fuzzy_keys.update(material_fuzzy_keys)
                elif target_exact_keys & material_exact_keys:
                    removed_exact_keys.update(material_exact_keys)
                    removed_fuzzy_keys.update(material_fuzzy_keys)

            if not removed_exact_keys:
                for material in extraction.materials or []:
                    source_file = getattr(material, "source_file", "")
                    nha = getattr(material, "nha", "")
                    material_fuzzy_keys = _material_match_keys(source_file, nha)
                    if target_fuzzy_keys & material_fuzzy_keys:
                        used_fuzzy_match = True
                        removed_fuzzy_keys.update(material_fuzzy_keys)
                        removed_exact_keys.update(_source_file_exact_tokens(source_file))
                        removed_exact_keys.update(_drawing_match_keys(nha))

            if not removed_exact_keys and not removed_fuzzy_keys:
                return {"removed": False, "error": f"Drawing '{drawing_id}' not found in extraction"}

        original_material_count = len(extraction.materials)
        filtered_materials = []
        for material in extraction.materials:
            source_file = getattr(material, "source_file", "")
            nha = getattr(material, "nha", "")
            material_exact_keys = _source_file_exact_tokens(source_file)
            material_fuzzy_keys = _material_match_keys(source_file, nha)
            if material_exact_keys & removed_exact_keys:
                continue
            if used_fuzzy_match and material_fuzzy_keys & removed_fuzzy_keys:
                continue
            filtered_materials.append(material)

        # Keep package payload aligned with filtered material set.
        for package in kept_packages:
            if not isinstance(package, dict):
                continue
            package_materials = package.get("materials", []) or []
            if not isinstance(package_materials, list):
                continue
            filtered_package_materials = []
            for material in package_materials:
                if not isinstance(material, dict):
                    continue
                material_source = material.get("source_file", "")
                material_nha = material.get("nha", "")
                material_exact_keys = _source_file_exact_tokens(material_source)
                material_fuzzy_keys = _material_match_keys(material_source, material_nha)
                if material_exact_keys & removed_exact_keys:
                    continue
                if used_fuzzy_match and material_fuzzy_keys & removed_fuzzy_keys:
                    continue
                filtered_package_materials.append(material)
            package["materials"] = filtered_package_materials

        pruned_packages = []
        for package in kept_packages:
            if not isinstance(package, dict):
                pruned_packages.append(package)
                continue
            package_materials = package.get("materials", []) or []
            if not package_materials:
                package_exact_keys = _package_exact_keys(package)
                package_fuzzy_keys = _package_match_keys(package)
                if package_exact_keys & removed_exact_keys:
                    continue
                if used_fuzzy_match and package_fuzzy_keys & removed_fuzzy_keys:
                    continue
            pruned_packages.append(package)
        kept_packages = pruned_packages

        extraction.materials = filtered_materials
        extraction.drawing_packages = kept_packages
        extraction.compute_summary()
        self._write(self.extraction_path, extraction.to_dict())

        previous_review = self.load_review() or {}
        review_data = identify_review_items(extraction)
        self._carry_review_status_forward(review_data, previous_review)

        # Any drawing removal re-opens the review gate and clears prior approval.
        review_data["status"] = "in_review"
        review_data["approved_at"] = None
        review_data["approved_by"] = None
        self._write(self.review_path, review_data)

        removed_materials = original_material_count - len(filtered_materials)
        removed_drawings = [
            _norm_token(pkg.get("drawing_number", ""))
            for pkg in removed_packages
            if isinstance(pkg, dict)
        ]
        removed_drawings = [d for d in removed_drawings if d]

        self._append_audit(
            "drawing_removed",
            {
                "drawing_id": target,
                "removed_drawings": removed_drawings,
                "removed_packages": len(removed_packages),
                "removed_materials": removed_materials,
                "remaining_packages": len(kept_packages),
                "remaining_materials": len(filtered_materials),
                "reviewer": reviewer,
                "reason": reason,
            },
        )

        return {
            "removed": True,
            "drawing_id": target,
            "removed_drawings": removed_drawings,
            "removed_packages": len(removed_packages),
            "removed_materials": removed_materials,
            "remaining_packages": len(kept_packages),
            "remaining_materials": len(filtered_materials),
        }

    def remove_part(
        self,
        part_number: str,
        reviewer: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        """Remove one part (including aliases) and regenerate review/extraction summaries."""
        extraction = self.load_extraction()
        if extraction is None:
            return {"removed": False, "error": "No extraction data found"}

        target = str(part_number or "").strip()
        if not target:
            return {"removed": False, "error": "No part identifier provided"}

        target_key = _norm_token(target)
        if not target_key:
            return {"removed": False, "error": "Invalid part identifier"}

        previous_review = self.load_review() or {}

        matched_item: Optional[Dict[str, Any]] = None
        remove_keys: set[str] = {target_key}
        for item in previous_review.get("review_items", []):
            if not isinstance(item, dict):
                continue
            item_keys = _review_item_keys(item)
            if target_key in item_keys:
                matched_item = item
                remove_keys.update(item_keys)
                break

        original_material_count = len(extraction.materials)
        removed_materials = 0
        removed_drawings: set[str] = set()
        removed_source_files: set[str] = set()

        filtered_materials = []
        for material in extraction.materials:
            material_key = _norm_token(getattr(material, "part_number", ""))
            if material_key in remove_keys:
                removed_materials += 1
                source_file = str(getattr(material, "source_file", "") or "").strip()
                if source_file:
                    removed_source_files.add(source_file)
                drawing_id = _infer_drawing_id(source_file, getattr(material, "nha", ""))
                if drawing_id:
                    removed_drawings.add(drawing_id)
                continue
            filtered_materials.append(material)

        if removed_materials == 0:
            return {"removed": False, "error": f"Part '{part_number}' not found in extraction"}

        touched_packages = 0
        for package in extraction.drawing_packages or []:
            if not isinstance(package, dict):
                continue
            package_materials = package.get("materials", []) or []
            if not isinstance(package_materials, list):
                continue

            filtered_package_materials = []
            package_removed = 0
            for material in package_materials:
                if not isinstance(material, dict):
                    continue
                material_key = _norm_token(material.get("part_number", ""))
                if material_key in remove_keys:
                    package_removed += 1
                    source_file = str(material.get("source_file", "") or "").strip()
                    if source_file:
                        removed_source_files.add(source_file)
                    drawing_id = _infer_drawing_id(source_file, material.get("nha", ""))
                    if drawing_id:
                        removed_drawings.add(drawing_id)
                    continue
                filtered_package_materials.append(material)

            if package_removed > 0:
                touched_packages += 1
            package["materials"] = filtered_package_materials

        extraction.materials = filtered_materials
        extraction.compute_summary()
        self._write(self.extraction_path, extraction.to_dict())

        review_data = identify_review_items(extraction)
        self._carry_review_status_forward(review_data, previous_review)

        # Part removal re-opens the review gate and clears prior approval.
        review_data["status"] = "in_review"
        review_data["approved_at"] = None
        review_data["approved_by"] = None
        self._write(self.review_path, review_data)

        canonical_part = str((matched_item or {}).get("part_number") or target)
        removed_aliases = sorted(remove_keys)

        self._append_audit(
            "part_removed",
            {
                "part_number": target,
                "canonical_part_number": canonical_part,
                "removed_aliases": removed_aliases,
                "removed_materials": removed_materials,
                "remaining_materials": len(filtered_materials),
                "packages_touched": touched_packages,
                "removed_drawings": sorted(removed_drawings),
                "removed_source_files": sorted(removed_source_files),
                "reviewer": reviewer,
                "reason": reason,
            },
        )

        return {
            "removed": True,
            "part_number": target,
            "canonical_part_number": canonical_part,
            "removed_aliases": removed_aliases,
            "removed_materials": removed_materials,
            "remaining_materials": len(filtered_materials),
            "packages_touched": touched_packages,
            "remaining_packages": len(extraction.drawing_packages or []),
            "removed_drawings": sorted(removed_drawings),
            "original_materials": original_material_count,
        }

    def get_review_items(
        self,
        confidence_filter: Optional[str] = None,
        field_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get review items with optional filters."""
        review = self.load_review()
        if not review:
            return []

        items = review.get("review_items", [])

        if status_filter:
            items = [i for i in items if i.get("status") == status_filter]

        if confidence_filter:
            threshold = {"low": 0.3, "medium": 0.7, "high": 1.0}.get(confidence_filter, 0.7)
            items = [i for i in items if i.get("worst_confidence", 0) < threshold]

        if field_filter:
            items = [
                i for i in items
                if field_filter in i.get("fields", {})
                and i["fields"][field_filter].get("confidence", 1.0) < 0.7
            ]

        return items

    def submit_correction(
        self,
        part_number: str,
        corrections: Dict[str, str],
        reviewer: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Apply a human correction to a review item."""
        review = self.load_review()
        if not review:
            return None

        # Find the item -- match on item_id first (unique), fall back to part_number
        item = None
        for ri in review.get("review_items", []):
            if ri.get("item_id") == part_number:
                item = ri
                break
        if item is None:
            for ri in review.get("review_items", []):
                if ri["part_number"] == part_number and ri.get("status") == "open":
                    item = ri
                    break

        if item is None:
            return None

        # Apply corrections to fields
        for field_name, new_value in corrections.items():
            if field_name in item.get("fields", {}):
                item["fields"][field_name]["value"] = new_value
                item["fields"][field_name]["confidence"] = 1.0  # Human-confirmed
                item["fields"][field_name]["corrected_by"] = reviewer

        # Update status
        item["status"] = "corrected"
        item["corrected_at"] = _now()
        item["corrected_by"] = reviewer

        # Also update the extraction data
        self._apply_correction_to_extraction(part_number, corrections)

        # Save
        self._write(self.review_path, review)
        self._append_audit("correction_submitted", {
            "part_number": part_number,
            "fields_corrected": list(corrections.keys()),
            "reviewer": reviewer,
        })

        return item

    def accept_item(
        self,
        part_number: str,
        reviewer: str = "",
        reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Accept a review item as-is (no correction needed)."""
        review = self.load_review()
        if not review:
            return None

        # Find the item -- match on item_id first (unique), fall back to part_number
        item = None
        for ri in review.get("review_items", []):
            if ri.get("item_id") == part_number:
                item = ri
                break
        if item is None:
            for ri in review.get("review_items", []):
                if ri["part_number"] == part_number and ri.get("status") == "open":
                    item = ri
                    break

        if item is None:
            return None

        item["status"] = "accepted"
        item["accepted_at"] = _now()
        item["accepted_by"] = reviewer
        item["accept_reason"] = reason

        self._write(self.review_path, review)
        self._append_audit("item_accepted", {
            "part_number": part_number,
            "reviewer": reviewer,
            "reason": reason,
        })

        return item

    def approve_build(self, reviewer: str) -> Dict[str, Any]:
        """
        Approve extraction for MIUL build.

        Checks all review items are resolved (corrected or accepted).
        Returns approval status and any unresolved items.
        """
        review = self.load_review()
        if not review:
            return {"approved": False, "error": "No review data found"}

        # Check for unresolved items
        unresolved = [
            ri for ri in review.get("review_items", [])
            if ri.get("status") == "open"
        ]

        if unresolved:
            return {
                "approved": False,
                "unresolved_count": len(unresolved),
                "unresolved_parts": [u["part_number"] for u in unresolved],
                "message": f"{len(unresolved)} items still need review before building.",
            }

        # Approve
        review["status"] = "approved"
        review["approved_at"] = _now()
        review["approved_by"] = reviewer
        self._write(self.review_path, review)

        self._append_audit("build_approved", {
            "reviewer": reviewer,
            "total_items": len(review.get("review_items", [])),
        })

        return {
            "approved": True,
            "approved_by": reviewer,
            "approved_at": review["approved_at"],
        }

    @property
    def is_approved(self) -> bool:
        review = self.load_review()
        return review is not None and review.get("status") == "approved"

    # ----- Internal helpers -----

    def _apply_correction_to_extraction(
        self, part_number: str, corrections: Dict[str, str]
    ) -> None:
        """Update the extraction JSON with human corrections."""
        data = self._read(self.extraction_path)
        if not data:
            return

        # Path parameter may be item_id; find actual part_number from review state.
        actual_part_number = part_number
        review = self._read(self.review_path) or {}
        for item in review.get("review_items", []):
            if item.get("item_id") == part_number:
                actual_part_number = str(item.get("part_number") or part_number)
                break

        for mat in data.get("materials", []):
            if mat.get("part_number") == actual_part_number:
                for field_name, new_value in corrections.items():
                    if field_name in mat:
                        mat[field_name] = new_value
                    # Update confidence to 1.0 for human-confirmed values
                    if "confidence" in mat and field_name in mat["confidence"]:
                        mat["confidence"][field_name] = 1.0
        for pkg in data.get("drawing_packages", []):
            for mat in pkg.get("materials", []):
                if mat.get("part_number") != actual_part_number:
                    continue
                for field_name, new_value in corrections.items():
                    if field_name in mat:
                        mat[field_name] = new_value
                    if "confidence" in mat and field_name in mat["confidence"]:
                        mat["confidence"][field_name] = 1.0

        self._write(self.extraction_path, data)

    def _carry_review_status_forward(
        self,
        review_data: Dict[str, Any],
        previous_review: Dict[str, Any],
    ) -> None:
        """
        Carry accepted/corrected review statuses into a regenerated review payload.

        This preserves already-reviewed parts when extraction mutations regenerate
        the review queue (e.g. remove drawing / remove part).
        """
        previous_items_by_key: Dict[str, Dict[str, Any]] = {}
        for item in previous_review.get("review_items", []):
            if not isinstance(item, dict):
                continue
            for key in _review_item_keys(item):
                previous_items_by_key.setdefault(key, item)

        for item in review_data.get("review_items", []):
            if not isinstance(item, dict):
                continue

            previous_item = None
            for key in _review_item_keys(item):
                previous_item = previous_items_by_key.get(key)
                if previous_item:
                    break
            if not previous_item:
                continue

            previous_status = previous_item.get("status")
            if previous_status not in {"accepted", "corrected"}:
                continue

            item["status"] = previous_status
            for key in ("accepted_at", "accepted_by", "accept_reason", "corrected_at", "corrected_by"):
                if key in previous_item:
                    item[key] = previous_item[key]

            previous_fields = previous_item.get("fields") or {}
            for field_name, field_data in item.get("fields", {}).items():
                prev_field_data = previous_fields.get(field_name) if isinstance(previous_fields, dict) else None
                if (
                    isinstance(prev_field_data, dict)
                    and isinstance(field_data, dict)
                    and prev_field_data.get("corrected_by")
                ):
                    field_data["corrected_by"] = prev_field_data.get("corrected_by")

    def _append_audit(self, event: str, details: Dict[str, Any]) -> None:
        """Append an event to the audit trail."""
        trail = self._read(self.audit_path) or []
        trail.append({
            "event": event,
            "timestamp": _now(),
            "extraction_id": self.extraction_id,
            **details,
        })
        self._write(self.audit_path, trail)

    def _write(self, path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _read(self, path: Path) -> Optional[Any]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            LOGGER.error(f"[V4Session] Failed to read {path}: {e}")
            return None

    def load_audit(self) -> List[Dict[str, Any]]:
        """Load audit trail."""
        return self._read(self.audit_path) or []

    def delete(self) -> bool:
        """Delete session directory and all data (sensitive-build purge)."""
        import shutil
        if self._dir.exists():
            try:
                shutil.rmtree(self._dir)
                LOGGER.info(f"[V4Session] Purged session {self.extraction_id}")
                return True
            except OSError as e:
                LOGGER.error(f"[V4Session] Failed to purge {self.extraction_id}: {e}")
                return False
        return False

    def get_created_at(self) -> Optional[str]:
        """Get session creation timestamp from extraction data or audit trail."""
        # Try extraction data first (has timestamp)
        data = self._read(self.extraction_path)
        if data and "timestamp" in data:
            return data["timestamp"]
        # Try audit trail (first event)
        audit = self._read(self.audit_path)
        if audit and len(audit) > 0:
            return audit[0].get("timestamp")
        # Fall back to directory mtime
        try:
            mtime = self._dir.stat().st_mtime
            return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            return None

    def get_project_name(self) -> Optional[str]:
        """Try to extract project name from stored data."""
        data = self._read(self.extraction_path)
        if data:
            dt_context = data.get("dt_context")
            if not isinstance(dt_context, dict):
                dt_context = {}
            return data.get("project") or dt_context.get("project")
        return None


# =============================================================================
# Session Registry
# =============================================================================

def list_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    """List all v4 extraction sessions with summary info, sorted newest first."""
    root = get_session_root()
    sessions = []
    if not root.exists():
        return sessions

    # Sort by directory modification time (newest first)
    dirs = []
    for d in root.iterdir():
        if d.is_dir() and (d / "extraction.json").exists():
            try:
                mtime = d.stat().st_mtime
            except OSError:
                mtime = 0
            dirs.append((mtime, d))

    dirs.sort(key=lambda x: x[0], reverse=True)

    for _, d in dirs[:limit]:
        session = V4Session(d.name)
        review = session.load_review()
        extraction = session._read(session.extraction_path)

        status_str = "unknown"
        if review:
            status_str = review.get("status", "unknown")

        sessions.append({
            "extraction_id": d.name,
            "status": status_str,
            "summary": review.get("summary", {}) if review else {},
            "created_at": session.get_created_at(),
            "project": session.get_project_name(),
        })

    return sessions


def get_session(extraction_id: str) -> V4Session:
    """Get or create a session by extraction ID."""
    return V4Session(extraction_id)


# =============================================================================
# Utilities
# =============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
