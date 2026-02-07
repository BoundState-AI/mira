#!/usr/bin/env python3
"""
Vision Extraction Learning Module for EPL Extraction.

Claude Vision extracts part numbers from high-DPI rendered images of drawings.
This module corrects Vision's character recognition errors by:
1. Maintaining a database of known-good part numbers
2. Using fuzzy matching to suggest corrections
3. Learning from human corrections over time
4. Validating extractions against known patterns

Note: We render PDFs to images at high DPI (200-235) before sending to Vision,
rather than letting Vision convert PDFs internally. This gives us control over
image quality for better extraction accuracy.

BoundState AI 2025
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

LOGGER = logging.getLogger(__name__)

# Database connection string - use env var or default
DATABASE_URL = os.environ.get(
    "BOUNDSTATE_DB_URL",
    "postgresql://postgres@localhost:5432/boundstate"
)


# =============================================================================
# Database Schema
# =============================================================================

SCHEMA_SQL = """
-- Known good part numbers from verified sources
CREATE TABLE IF NOT EXISTS known_parts (
    part_number VARCHAR(50) PRIMARY KEY,
    description TEXT,
    cage_code VARCHAR(10),
    material VARCHAR(100),
    material_spec VARCHAR(200),
    source VARCHAR(50),  -- 'DT', 'MAPTIS', 'MANUAL', 'EPL_VERIFIED'
    project VARCHAR(50),
    verified_at TIMESTAMP DEFAULT NOW(),
    verified_by VARCHAR(100)
);

-- Index for fuzzy search
CREATE INDEX IF NOT EXISTS idx_known_parts_pn_trgm
ON known_parts USING gin (part_number gin_trgm_ops);

-- Vision extraction correction history - learned mappings
-- (Table name kept as ocr_corrections for backward compatibility)
CREATE TABLE IF NOT EXISTS ocr_corrections (
    id SERIAL PRIMARY KEY,
    raw_extraction VARCHAR(100) NOT NULL,
    corrected_to VARCHAR(50) REFERENCES known_parts(part_number),
    drawing_source VARCHAR(50),
    find_no VARCHAR(10),
    description_context TEXT,
    confidence FLOAT DEFAULT 0.5,
    correction_count INT DEFAULT 1,
    auto_correct BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(raw_extraction, corrected_to)
);

-- Index for fast lookup
CREATE INDEX IF NOT EXISTS idx_ocr_corrections_raw
ON ocr_corrections(raw_extraction);

-- Pattern rules learned from corrections
CREATE TABLE IF NOT EXISTS ocr_patterns (
    id SERIAL PRIMARY KEY,
    pattern_type VARCHAR(50),  -- 'CHAR_SWAP', 'PREFIX', 'SUFFIX', 'REGEX'
    raw_pattern VARCHAR(100),
    corrected_pattern VARCHAR(100),
    context_hint TEXT,  -- e.g., 'when description contains CONNECTING ROD'
    confidence FLOAT DEFAULT 0.5,
    hit_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Extraction audit log for learning
CREATE TABLE IF NOT EXISTS extraction_audit (
    id SERIAL PRIMARY KEY,
    drawing_number VARCHAR(50),
    find_no VARCHAR(10),
    raw_extraction VARCHAR(100),
    final_value VARCHAR(100),
    correction_applied BOOLEAN DEFAULT FALSE,
    correction_source VARCHAR(50),  -- 'AUTO', 'FUZZY', 'MANUAL', 'NONE'
    human_verified BOOLEAN DEFAULT FALSE,
    extracted_at TIMESTAMP DEFAULT NOW()
);

-- Enable trigram extension for fuzzy matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class KnownPart:
    """A verified part number from the database."""
    part_number: str
    description: str = ""
    cage_code: str = ""
    material: str = ""
    material_spec: str = ""
    source: str = ""
    project: str = ""
    verified_at: Any = None  # datetime from DB
    verified_by: str = ""


@dataclass
class CorrectionCandidate:
    """A potential correction for an OCR error."""
    raw: str
    corrected: str
    confidence: float
    source: str  # 'EXACT', 'LEARNED', 'FUZZY', 'PATTERN'
    similarity: float = 1.0
    context_match: bool = False


@dataclass
class ExtractionResult:
    """Result of extracting and correcting a part number."""
    raw: str
    corrected: str
    was_corrected: bool
    confidence: float
    correction_source: str
    candidates: List[CorrectionCandidate]


# =============================================================================
# Vision Extraction Learning Database
# =============================================================================

class OCRLearningDB:
    """
    Database-backed Vision extraction learning and correction system.

    Claude Vision extracts text from rendered drawing images. This class
    corrects Vision's character recognition errors (e.g., 0/O confusion,
    similar-looking digits) by learning from human corrections.

    Provides:
    - Known part number storage and lookup
    - Fuzzy matching for extraction error correction
    - Learning from human corrections
    - Pattern-based correction rules

    Note: Class name kept as OCRLearningDB for backward compatibility,
    but it's really correcting Vision extraction errors, not traditional OCR.
    """

    def __init__(self, database_url: str = None):
        """Initialize with database connection."""
        self.database_url = database_url or DATABASE_URL
        self._conn = None

    @property
    def conn(self):
        """Lazy database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.database_url)
        return self._conn

    def close(self):
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()

    def init_schema(self):
        """Initialize database schema."""
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        self.conn.commit()
        LOGGER.info("[Vision Learning] Database schema initialized")

    # -------------------------------------------------------------------------
    # Known Parts Management
    # -------------------------------------------------------------------------

    def add_known_part(
        self,
        part_number: str,
        description: str = "",
        cage_code: str = "",
        material: str = "",
        material_spec: str = "",
        source: str = "MANUAL",
        project: str = "",
        verified_by: str = "system"
    ) -> bool:
        """
        Add a known-good part number to the database.

        Args:
            part_number: The verified part number
            description: Part description
            cage_code: CAGE code
            material: Material designation
            material_spec: Material specification
            source: Source of truth ('DT', 'MAPTIS', 'MANUAL', 'EPL_VERIFIED')
            project: Project identifier
            verified_by: Who verified this part

        Returns:
            True if added, False if already exists
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO known_parts
                    (part_number, description, cage_code, material, material_spec,
                     source, project, verified_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (part_number) DO UPDATE SET
                        description = COALESCE(EXCLUDED.description, known_parts.description),
                        cage_code = COALESCE(EXCLUDED.cage_code, known_parts.cage_code),
                        material = COALESCE(EXCLUDED.material, known_parts.material),
                        material_spec = COALESCE(EXCLUDED.material_spec, known_parts.material_spec),
                        source = EXCLUDED.source,
                        verified_at = NOW()
                """, (part_number.strip().upper(), description, cage_code,
                      material, material_spec, source, project, verified_by))
            self.conn.commit()
            return True
        except Exception as e:
            LOGGER.error(f"[Vision Learning] Error adding known part: {e}")
            self.conn.rollback()
            return False

    def seed_from_dt_json(self, dt_json: Dict[str, Any], project: str = "") -> int:
        """
        Seed known_parts table from a Drawing Tree JSON.

        Args:
            dt_json: DT JSON with 'tree' list
            project: Project identifier

        Returns:
            Number of parts added
        """
        count = 0
        tree = dt_json.get("tree", [])

        for entry in tree:
            pn = entry.get("drawing_number", "").strip()
            if not pn:
                continue

            title = entry.get("title", "")

            if self.add_known_part(
                part_number=pn,
                description=title,
                source="DT",
                project=project
            ):
                count += 1

        LOGGER.info(f"[Vision Learning] Seeded {count} parts from DT JSON")
        return count

    def seed_from_parts_json(self, parts_json: Dict[str, Any], project: str = "") -> int:
        """
        Seed known_parts table from a Parts JSON.

        Args:
            parts_json: Parts JSON with 'parts' dict
            project: Project identifier

        Returns:
            Number of parts added
        """
        count = 0
        parts = parts_json.get("parts", {})

        for pn, info in parts.items():
            if self.add_known_part(
                part_number=pn,
                description=info.get("description", ""),
                material=info.get("material", ""),
                material_spec=info.get("material_spec", ""),
                source="EPL_VERIFIED" if info.get("source_type") == "EPL" else "DRAWING",
                project=project
            ):
                count += 1

        LOGGER.info(f"[Vision Learning] Seeded {count} parts from Parts JSON")
        return count

    def get_known_part(self, part_number: str) -> Optional[KnownPart]:
        """Look up a known part by exact match."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM known_parts WHERE part_number = %s",
                (part_number.strip().upper(),)
            )
            row = cur.fetchone()
            if row:
                return KnownPart(**row)
        return None

    def is_known_part(self, part_number: str) -> bool:
        """Check if a part number is in the known parts table."""
        return self.get_known_part(part_number) is not None

    # -------------------------------------------------------------------------
    # Fuzzy Matching
    # -------------------------------------------------------------------------

    def fuzzy_match(
        self,
        raw_pn: str,
        limit: int = 5,
        min_similarity: float = 0.6,
        project: str = None
    ) -> List[Tuple[KnownPart, float]]:
        """
        Find similar known parts using trigram similarity.

        Args:
            raw_pn: The raw extracted part number
            limit: Max results to return
            min_similarity: Minimum similarity threshold (0-1)
            project: Optional project filter

        Returns:
            List of (KnownPart, similarity) tuples, sorted by similarity
        """
        raw_upper = raw_pn.strip().upper()

        query = """
            SELECT *, similarity(part_number, %s) AS sim
            FROM known_parts
            WHERE similarity(part_number, %s) > %s
        """
        params = [raw_upper, raw_upper, min_similarity]

        if project:
            query += " AND project = %s"
            params.append(project)

        query += " ORDER BY sim DESC LIMIT %s"
        params.append(limit)

        results = []
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            for row in cur.fetchall():
                sim = row.pop("sim")
                results.append((KnownPart(**row), sim))

        return results

    # -------------------------------------------------------------------------
    # OCR Corrections
    # -------------------------------------------------------------------------

    def get_learned_correction(self, raw_pn: str) -> Optional[CorrectionCandidate]:
        """
        Look up a previously learned correction.

        Args:
            raw_pn: The raw extracted part number

        Returns:
            CorrectionCandidate if found and confident, else None
        """
        raw_upper = raw_pn.strip().upper()

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT corrected_to, confidence, correction_count, auto_correct
                FROM ocr_corrections
                WHERE raw_extraction = %s
                ORDER BY correction_count DESC, confidence DESC
                LIMIT 1
            """, (raw_upper,))
            row = cur.fetchone()

            if row:
                # Update last_used_at
                cur.execute(
                    "UPDATE ocr_corrections SET last_used_at = NOW() WHERE raw_extraction = %s",
                    (raw_upper,)
                )
                self.conn.commit()

                return CorrectionCandidate(
                    raw=raw_upper,
                    corrected=row["corrected_to"],
                    confidence=row["confidence"],
                    source="LEARNED",
                    similarity=1.0,
                    context_match=row["auto_correct"]
                )

        return None

    def record_correction(
        self,
        raw_pn: str,
        corrected_pn: str,
        drawing_source: str = "",
        find_no: str = "",
        description_context: str = "",
        confidence: float = 0.8
    ) -> bool:
        """
        Record a correction for learning.

        If the same raw->corrected mapping exists, increment count and confidence.

        Args:
            raw_pn: The raw extracted part number
            corrected_pn: The corrected part number
            drawing_source: Source drawing number
            find_no: Find number in EPL
            description_context: Description text for context
            confidence: Initial confidence (0-1)

        Returns:
            True if recorded successfully
        """
        raw_upper = raw_pn.strip().upper()
        corrected_upper = corrected_pn.strip().upper()

        # Ensure corrected_to is a known part
        if not self.is_known_part(corrected_upper):
            LOGGER.warning(
                f"[Vision Learning] Cannot record correction: {corrected_upper} not in known_parts"
            )
            return False

        try:
            with self.conn.cursor() as cur:
                # Upsert - insert or update count/confidence
                cur.execute("""
                    INSERT INTO ocr_corrections
                    (raw_extraction, corrected_to, drawing_source, find_no,
                     description_context, confidence)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (raw_extraction, corrected_to) DO UPDATE SET
                        correction_count = ocr_corrections.correction_count + 1,
                        confidence = LEAST(0.99, ocr_corrections.confidence + 0.05),
                        auto_correct = CASE
                            WHEN ocr_corrections.correction_count >= 2 THEN TRUE
                            ELSE ocr_corrections.auto_correct
                        END,
                        last_used_at = NOW()
                """, (raw_upper, corrected_upper, drawing_source, find_no,
                      description_context, confidence))
            self.conn.commit()
            LOGGER.info(f"[Vision Learning] Recorded correction: {raw_upper} -> {corrected_upper}")
            return True
        except Exception as e:
            LOGGER.error(f"[Vision Learning] Error recording correction: {e}")
            self.conn.rollback()
            return False

    # -------------------------------------------------------------------------
    # Main Correction Logic
    # -------------------------------------------------------------------------

    def correct_part_number(
        self,
        raw_pn: str,
        description: str = "",
        drawing_source: str = "",
        project: str = None,
        auto_learn: bool = True
    ) -> ExtractionResult:
        """
        Attempt to correct an extracted part number.

        Correction priority:
        1. Exact match in known_parts (no correction needed)
        2. Learned correction from ocr_corrections table
        3. Fuzzy match against known_parts
        4. No correction (return raw)

        Args:
            raw_pn: The raw extracted part number
            description: Part description for context
            drawing_source: Source drawing number
            project: Project for scoped matching
            auto_learn: If True, record high-confidence corrections

        Returns:
            ExtractionResult with correction details
        """
        raw_upper = raw_pn.strip().upper()
        candidates: List[CorrectionCandidate] = []

        # 1. Check exact match
        if self.is_known_part(raw_upper):
            return ExtractionResult(
                raw=raw_upper,
                corrected=raw_upper,
                was_corrected=False,
                confidence=1.0,
                correction_source="EXACT",
                candidates=[]
            )

        # 2. Check learned corrections
        learned = self.get_learned_correction(raw_upper)
        if learned and learned.confidence >= 0.8:
            return ExtractionResult(
                raw=raw_upper,
                corrected=learned.corrected,
                was_corrected=True,
                confidence=learned.confidence,
                correction_source="LEARNED",
                candidates=[learned]
            )
        if learned:
            candidates.append(learned)

        # 3. Fuzzy match - use lower threshold to find more candidates
        fuzzy_matches = self.fuzzy_match(raw_upper, limit=5, min_similarity=0.5, project=project)

        for known_part, similarity in fuzzy_matches:
            # Scale confidence: 0.5 sim -> 0.5 conf, 1.0 sim -> 0.95 conf
            base_conf = 0.5 + (similarity - 0.5) * 0.9
            candidate = CorrectionCandidate(
                raw=raw_upper,
                corrected=known_part.part_number,
                confidence=base_conf,
                source="FUZZY",
                similarity=similarity,
                context_match=self._context_matches(description, known_part.description)
            )
            candidates.append(candidate)

        # Boost confidence for context matches
        for c in candidates:
            if c.context_match:
                c.confidence = min(0.95, c.confidence + 0.15)

        # Sort by confidence
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        # If best candidate is reasonably confident, use it
        # Lower threshold (0.7) because trigram similarity is stricter than Levenshtein
        if candidates and candidates[0].confidence >= 0.7:
            best = candidates[0]

            # Auto-learn high-confidence fuzzy corrections
            if auto_learn and best.source == "FUZZY" and best.confidence >= 0.9:
                self.record_correction(
                    raw_upper, best.corrected, drawing_source,
                    description_context=description,
                    confidence=best.confidence
                )

            return ExtractionResult(
                raw=raw_upper,
                corrected=best.corrected,
                was_corrected=True,
                confidence=best.confidence,
                correction_source=best.source,
                candidates=candidates
            )

        # No confident correction - return raw
        return ExtractionResult(
            raw=raw_upper,
            corrected=raw_upper,
            was_corrected=False,
            confidence=0.5,
            correction_source="NONE",
            candidates=candidates
        )

    def _context_matches(self, desc1: str, desc2: str) -> bool:
        """Check if descriptions have significant overlap."""
        if not desc1 or not desc2:
            return False

        words1 = set(desc1.upper().split())
        words2 = set(desc2.upper().split())

        # Remove common words
        stopwords = {"THE", "A", "AN", "OF", "FOR", "IN", "TO", "WITH"}
        words1 -= stopwords
        words2 -= stopwords

        if not words1 or not words2:
            return False

        overlap = len(words1 & words2)
        return overlap >= 2 or overlap / min(len(words1), len(words2)) > 0.5

    # -------------------------------------------------------------------------
    # Audit Logging
    # -------------------------------------------------------------------------

    def log_extraction(
        self,
        drawing_number: str,
        find_no: str,
        raw_extraction: str,
        final_value: str,
        correction_applied: bool,
        correction_source: str
    ):
        """Log an extraction for audit trail."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO extraction_audit
                    (drawing_number, find_no, raw_extraction, final_value,
                     correction_applied, correction_source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (drawing_number, find_no, raw_extraction, final_value,
                      correction_applied, correction_source))
            self.conn.commit()
        except Exception as e:
            LOGGER.error(f"[Vision Learning] Audit log error: {e}")
            self.conn.rollback()

    def get_unverified_extractions(
        self,
        drawing_number: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get extractions that need human verification."""
        query = """
            SELECT * FROM extraction_audit
            WHERE human_verified = FALSE AND correction_applied = TRUE
        """
        params = []

        if drawing_number:
            query += " AND drawing_number = %s"
            params.append(drawing_number)

        query += " ORDER BY extracted_at DESC LIMIT %s"
        params.append(limit)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return list(cur.fetchall())

    def verify_extraction(self, audit_id: int, is_correct: bool):
        """Mark an extraction as human-verified."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE extraction_audit SET human_verified = TRUE WHERE id = %s",
                (audit_id,)
            )

            if not is_correct:
                # Decrease confidence of the correction that was wrong
                cur.execute("""
                    UPDATE ocr_corrections
                    SET confidence = GREATEST(0.1, confidence - 0.1)
                    WHERE raw_extraction = (
                        SELECT raw_extraction FROM extraction_audit WHERE id = %s
                    )
                """, (audit_id,))

        self.conn.commit()


# =============================================================================
# Standalone Functions (no DB required)
# =============================================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity_ratio(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings (0-1)."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    dist = levenshtein_distance(s1.upper(), s2.upper())
    max_len = max(len(s1), len(s2))
    return 1.0 - (dist / max_len)


def fuzzy_match_list(
    raw_pn: str,
    known_pns: List[str],
    min_similarity: float = 0.7,
    limit: int = 5
) -> List[Tuple[str, float]]:
    """
    Fuzzy match a part number against a list of known PNs.

    Standalone version that doesn't require database.

    Args:
        raw_pn: The raw extracted part number
        known_pns: List of known-good part numbers
        min_similarity: Minimum similarity threshold
        limit: Max results

    Returns:
        List of (part_number, similarity) tuples
    """
    raw_upper = raw_pn.strip().upper()
    results = []

    for known in known_pns:
        sim = similarity_ratio(raw_upper, known.upper())
        if sim >= min_similarity:
            results.append((known, sim))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print("Usage: python ocr_learning.py <command> [args]")
        print("Commands:")
        print("  init              - Initialize database schema")
        print("  seed <dt.json>    - Seed known_parts from DT JSON")
        print("  test <raw_pn>     - Test correction for a part number")
        print("  stats             - Show database stats")
        sys.exit(1)

    db = OCRLearningDB()
    cmd = sys.argv[1]

    if cmd == "init":
        db.init_schema()
        print("Schema initialized")

    elif cmd == "seed" and len(sys.argv) >= 3:
        with open(sys.argv[2], "r") as f:
            dt_json = json.load(f)
        count = db.seed_from_dt_json(dt_json, project="TEST")
        print(f"Seeded {count} parts")

    elif cmd == "test" and len(sys.argv) >= 3:
        raw_pn = sys.argv[2]
        result = db.correct_part_number(raw_pn)
        print(f"Raw: {result.raw}")
        print(f"Corrected: {result.corrected}")
        print(f"Was corrected: {result.was_corrected}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Source: {result.correction_source}")
        if result.candidates:
            print("Candidates:")
            for c in result.candidates[:3]:
                print(f"  {c.corrected} ({c.confidence:.2f}, {c.source})")

    elif cmd == "stats":
        with db.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM known_parts")
            print(f"Known parts: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM ocr_corrections")
            print(f"Learned corrections: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM extraction_audit")
            print(f"Extraction audits: {cur.fetchone()[0]}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    db.close()
