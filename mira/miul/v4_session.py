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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vision_extractor import ExtractionResult, identify_review_items

LOGGER = logging.getLogger(__name__)

# Default session storage root
_SESSION_ROOT = Path("C:/BoundState/temp/miul_sessions")


def get_session_root() -> Path:
    """Return session storage root, creating if needed."""
    _SESSION_ROOT.mkdir(parents=True, exist_ok=True)
    return _SESSION_ROOT


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

        for mat in data.get("materials", []):
            if mat.get("part_number") == part_number:
                for field_name, new_value in corrections.items():
                    if field_name in mat:
                        mat[field_name] = new_value
                    # Update confidence to 1.0 for human-confirmed values
                    if "confidence" in mat and field_name in mat["confidence"]:
                        mat["confidence"][field_name] = 1.0
                break

        self._write(self.extraction_path, data)

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
            return data.get("project") or data.get("dt_context", {}).get("project")
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
