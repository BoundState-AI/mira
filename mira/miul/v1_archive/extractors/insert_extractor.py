#!/usr/bin/env python3
"""
Module: Insert Extractor
Purpose: Insert/Helicoil Extractor for Engineering Drawings.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import uuid

LOGGER = logging.getLogger(__name__)


@dataclass
class InsertCallout:
    """Represents a threaded insert callout from a drawing."""

    quantity: int
    thread_size: str  # e.g., ".2500-20", ".3125-18"
    thread_class: str  # e.g., "UNC-3B"
    insert_type: str  # e.g., "HELICAL COIL", "KEY-LOCKING"
    spec_number: str  # e.g., "NASM33537", "MS21209"
    min_thread_depth: Optional[str] = None  # e.g., ".43 MIN FULL THD DEPTH"
    source_file: str = ""
    raw_text: str = ""
    source: str = ""  # NASA SWE-013 traceability


    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BOM integration."""
        return {
            "quantity": self.quantity,
            "thread_size": self.thread_size,
            "thread_class": self.thread_class,
            "insert_type": self.insert_type,
            "spec_number": self.spec_number,
            "min_thread_depth": self.min_thread_depth,
            "source_file": self.source_file,
            "raw_text": self.raw_text,
        }

    def to_bom_item(self) -> Dict[str, Any]:
        """Convert to BOM item format for MIUL integration."""
        # Generate a designation from the insert spec
        designation = f"{self.insert_type} {self.thread_size} {self.thread_class}"

        return {
            "quantity": self.quantity,
            "designation": designation,
            "material_spec": self.spec_number,
            "material_form": "INSERT",
            "source_file": self.source_file,
            "is_insert": True,
            "insert_details": self.to_dict(),
        }


class InsertExtractor:
    """Extracts threaded insert callouts from engineering drawing text."""

    # Common insert specs and their patterns
    INSERT_SPECS = {
        "NASM33537": "Helical Coil Screw Thread Inserts",
        "MS33537": "Helical Coil Screw Thread Inserts (legacy)",
        "MS21209": "Key-Locking Thread Inserts",
        "NAS1130": "Thin Wall Helical Coil Inserts",
        "MS124651": "Helical Coil Inserts, Screw-Locking",
    }

    # Thread sizes to standard part number mapping (partial)
    HELICOIL_PART_MAP = {
        ".2500-20": "MS122076",  # 1/4-20 free-running
        ".2500-28": "MS122077",  # 1/4-28 free-running
        ".3125-18": "MS122078",  # 5/16-18 free-running
        ".3125-24": "MS122079",  # 5/16-24 free-running
        ".3750-16": "MS122080",  # 3/8-16 free-running
        ".3750-24": "MS122081",  # 3/8-24 free-running
    }

    def __init__(self):
        """Initialize the insert extractor."""
        # Main pattern for helical coil inserts
        # Matches: "4X .3125-18 UNC-3B HELICAL COIL INSERT THD PER NASM33537"
        # Uses lookbehind to ensure qty isn't part of a decimal (e.g., ".34524X")
        self.helicoil_pattern = re.compile(
            r'(?<![.\d])'  # Not preceded by decimal point or digit (avoid ".34524X")
            r'(\d{1,2})X\s+'  # Quantity 1-99 (e.g., "4X", "24X")
            r'\.?(\d{3,4})-(\d+)\s+'  # Thread size (e.g., ".3125-18" or "3125-18")
            r'(UNC|UNF)-(\d[AB])\s+'  # Thread class (e.g., "UNC-3B")
            r'(HELICAL\s+COIL|HELI-COIL|HELICOIL)\s*'  # Insert type
            r'INSERT\s+THD\s+PER\s+'  # Standard phrase
            r'(NASM?\d+|MS\d+|NAS\d+)',  # Spec number
            re.IGNORECASE
        )

        # Pattern for thread depth callout (often on next line)
        self.depth_pattern = re.compile(
            r'\.(\d+)\s+MIN\s+FULL\s+THD\s+DEPTH',
            re.IGNORECASE
        )

        # Alternative pattern for inline format
        self.inline_pattern = re.compile(
            r'(\d+)X\s*'  # Quantity
            r'\.?(\d{3,4})-(\d+)\s*'  # Thread size
            r'(UNC|UNF)-?(\d[AB])?\s*'  # Thread class
            r'(?:THRU\s+)?'  # Optional THRU
            r'(HELICAL\s+COIL|HELI-?COIL)\s*'
            r'INSERT',
            re.IGNORECASE
        )

        # Pattern for "TAP FOR #X-XX HELICOIL INSERT" callouts (no spec number)
        # Matches: "59X .147 .193 TAP FOR #6-40 HELICOIL INSERT = 1.0 * DIA"
        self.tap_for_pattern = re.compile(
            r'(?<![.\d])'  # Not preceded by decimal
            r'(\d{1,3})X\s*'  # Quantity (e.g., "59X", "30X")
            r'[\d.\s]*'  # Optional dimensions
            r'TAP\s+FOR\s+'  # "TAP FOR"
            r'#?(\d+)-(\d+)\s*'  # Thread size (#6-40 or 6-40)
            r'(?:UNC|UNF)?-?\d*[AB]?\s*'  # Optional thread class
            r'(HELICOIL|HELI-COIL|HELICAL\s+COIL)\s*INSERT',
            re.IGNORECASE
        )

        # Pattern for HCC part numbers in BOM tables
        # Matches: "HCC-138-40-138" (Heli-Coil Corporation part numbers)
        self.hcc_pattern = re.compile(
            r'\b(HCC-\d{2,4}-\d{1,3}-\d{1,4})\b',
            re.IGNORECASE
        )

    def _preprocess_text(self, text: str) -> str:
        """Pre-process text to fix common PDF extraction issues.

        PDF extraction often concatenates dimension values with quantity callouts.
        For example: ".34524X .2500-20" should be ".345 24X .2500-20"

        This method adds spaces before likely quantity patterns.
        """
        # Pattern: digit(s) followed by "X " then thread size
        # We insert a space before the quantity if preceded by typical decimal endings
        # Common decimal endings: 0, 5, 00, 05, 90, 95, etc.

        # Fix patterns like ".34524X .2500" → ".345 24X .2500"
        # Look for: decimal + 1-2 digits + "X " + thread pattern
        text = re.sub(
            r'(\.\d{2,3})'  # Decimal like .34, .345, .090
            r'(\d{1,2}X\s+\.?\d{3,4}-\d+)',  # Quantity + thread like "24X .2500-20"
            r'\1 \2',  # Add space between
            text
        )

        # Fix patterns like "5.0905X .2500" → "5.090 5X .2500"
        text = re.sub(
            r'(\d\.\d{2,3})'  # Number like 5.09, 5.090
            r'(\d{1,2}X\s+\.?\d{3,4}-\d+)',
            r'\1 \2',
            text
        )

        # Fix patterns like "2X 1.96X .2500" → "2X 1.9 6X .2500"
        # (dimension callout followed by quantity)
        text = re.sub(
            r'(\d\.\d)'  # Short decimal like 1.9
            r'(\d{1,2}X\s+\.?\d{3,4}-\d+)',
            r'\1 \2',
            text
        )

        return text

    def extract_inserts(self, text: str, source_file: str = "") -> List[InsertCallout]:
        """Extract all insert callouts from drawing text.

        Args:
            text: Raw text extracted from engineering drawing
            source_file: Name of source file for tracking

        Returns:
            List of InsertCallout objects
        """
        # Pre-process to fix concatenated text from PDF extraction
        text = self._preprocess_text(text)

        inserts: List[InsertCallout] = []

        # Find all matches with the main pattern
        for match in self.helicoil_pattern.finditer(text):
            qty = int(match.group(1))
            thread_major = match.group(2)
            thread_pitch = match.group(3)
            thread_series = match.group(4).upper()
            thread_class = match.group(5)
            insert_type = match.group(6).upper().replace("-", " ")
            spec_number = match.group(7).upper()

            # Normalize thread size
            thread_size = f".{thread_major}-{thread_pitch}"
            thread_class_full = f"{thread_series}-{thread_class}"

            # Look for depth callout nearby
            depth = None
            end_pos = match.end()
            nearby_text = text[end_pos:end_pos + 100]
            depth_match = self.depth_pattern.search(nearby_text)
            if depth_match:
                depth = f".{depth_match.group(1)} MIN FULL THD DEPTH"

            insert = InsertCallout(
                quantity=qty,
                thread_size=thread_size,
                thread_class=thread_class_full,
                insert_type=insert_type,
                spec_number=spec_number,
                min_thread_depth=depth,
                source_file=source_file,
                raw_text=match.group(0),
            )
            inserts.append(insert)

            LOGGER.debug(
                f"Found insert: {qty}X {thread_size} {thread_class_full} "
                f"{insert_type} per {spec_number}"
            )

        # Also find "TAP FOR #X-XX HELICOIL INSERT" callouts (no spec number)
        for match in self.tap_for_pattern.finditer(text):
            qty = int(match.group(1))
            thread_major = match.group(2)  # e.g., "6" from "#6-40"
            thread_pitch = match.group(3)  # e.g., "40"
            insert_type = match.group(4).upper().replace("-", " ")

            # Convert thread number to decimal format
            # #6 = .138, #8 = .164, #10 = .190
            thread_num_map = {
                '2': '.086', '3': '.099', '4': '.112', '5': '.125',
                '6': '.138', '8': '.164', '10': '.190', '12': '.216'
            }
            thread_dec = thread_num_map.get(thread_major, f'.{thread_major:0>3}')
            thread_size = f"{thread_dec}-{thread_pitch}"

            insert = InsertCallout(
                quantity=qty,
                thread_size=thread_size,
                thread_class="UNC-2B",  # Default for helicoil taps
                insert_type="HELICAL COIL",
                spec_number="HCC",  # Heli-Coil generic (will look up material)
                min_thread_depth=None,
                source_file=source_file,
                raw_text=match.group(0),
            )
            inserts.append(insert)

            LOGGER.debug(
                f"Found TAP FOR insert: {qty}X {thread_size} HELICOIL"
            )

        # Find HCC part numbers in text (e.g., "HCC-138-40-138")
        for match in self.hcc_pattern.finditer(text):
            hcc_pn = match.group(1).upper()
            # Parse HCC-XXX-YY-ZZZ format
            parts = hcc_pn.split('-')
            if len(parts) == 4:
                # HCC-138-40-138: 138=size code, 40=pitch, 138=length
                # This is a BOM reference, qty will come from BOM table
                insert = InsertCallout(
                    quantity=1,  # Will be updated from BOM qty
                    thread_size=f"#{parts[1][:1]}-{parts[2]}",  # Approximate
                    thread_class="UNC-2B",
                    insert_type="HELICAL COIL",
                    spec_number=hcc_pn,  # Full HCC part number
                    min_thread_depth=None,
                    source_file=source_file,
                    raw_text=match.group(0),
                )
                inserts.append(insert)
                LOGGER.debug(f"Found HCC part number: {hcc_pn}")

        # Deduplicate by combining quantities for identical inserts
        inserts = self._consolidate_inserts(inserts)

        return inserts

    def _consolidate_inserts(
        self, inserts: List[InsertCallout]
    ) -> List[InsertCallout]:
        """Consolidate identical inserts by summing quantities.

        Different callouts on the same drawing may specify the same insert
        in different locations. We consolidate these into a single entry
        with combined quantity.
        """
        consolidated: Dict[Tuple[str, str, str], InsertCallout] = {}

        for insert in inserts:
            key = (insert.thread_size, insert.thread_class, insert.spec_number)

            if key in consolidated:
                # Add quantity to existing
                existing = consolidated[key]
                existing.quantity += insert.quantity
                existing.raw_text += f"; {insert.raw_text}"
            else:
                consolidated[key] = InsertCallout(
                    quantity=insert.quantity,
                    thread_size=insert.thread_size,
                    thread_class=insert.thread_class,
                    insert_type=insert.insert_type,
                    spec_number=insert.spec_number,
                    min_thread_depth=insert.min_thread_depth,
                    source_file=insert.source_file,
                    raw_text=insert.raw_text,
                )

        result = list(consolidated.values())

        if len(result) < len(inserts):
            LOGGER.info(
                f"Consolidated {len(inserts)} insert callouts into {len(result)} "
                f"unique insert types"
            )

        return result

    def get_part_number(self, insert: InsertCallout) -> Optional[str]:
        """Look up standard part number for an insert.

        Args:
            insert: InsertCallout to look up

        Returns:
            Standard part number if known, None otherwise
        """
        return self.HELICOIL_PART_MAP.get(insert.thread_size)


def extract_inserts_from_text(text: str, source_file: str = "") -> List[Dict[str, Any]]:
    """Convenience function to extract inserts and return as dicts.

    Args:
        text: Raw text from engineering drawing
        source_file: Source file name

    Returns:
        List of insert dictionaries ready for BOM integration
    """
    extractor = InsertExtractor()
    inserts = extractor.extract_inserts(text, source_file)
    return [insert.to_bom_item() for insert in inserts]
