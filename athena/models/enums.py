#!/usr/bin/env python3
"""
Module: Enums
Purpose: ATHENA Enumeration Types.

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

from enum import Enum


class DeploymentMode(str, Enum):
    """Deployment environment mode."""
    CLOUD = "cloud"          # Commercial Anthropic API
    GOVCLOUD = "govcloud"    # AWS Bedrock GovCloud
    ON_PREM = "on_prem"      # Local model server


class DocumentStatus(str, Enum):
    """Document processing status."""
    PENDING = "pending"
    TRIAGED = "triaged"
    EXTRACTED = "extracted"
    RECONCILED = "reconciled"
    INDEXED = "indexed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"
    RESCAN_REQUESTED = "rescan_requested"


class RoutingDecision(str, Enum):
    """Triage routing decision."""
    EXTRACT_FULL = "extract_full"       # Sonnet, full schema
    EXTRACT_LIGHT = "extract_light"     # Haiku, basic schema
    EXTRACT_STANDARD = "extract_standard"     # Standards → RequirementRecord
    EXTRACT_DATA_TABLE = "extract_data_table" # Data tables → FlammabilityRecord/EmbrittlementRecord
    EXTRACT_DRAWING = "extract_drawing"       # Drawings → title block metadata only (Haiku)
    MANUAL_REVIEW = "manual_review"
    RESCAN = "rescan"
    SKIP = "skip"


class EntityType(str, Enum):
    """Entity classification type."""
    PERSON = "person"
    EQUIPMENT = "equipment"
    LOCATION = "location"
    ORGANIZATION = "organization"
    DATE = "date"
    REFERENCE = "reference"             # Serial#, part#, doc#
    EVENT = "event"
    MATERIAL = "material"
    PROCEDURE = "procedure"


class EntityLinkStatus(str, Enum):
    """Status of entity link proposal."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


class QualityIssue(str, Enum):
    """Document quality issues."""
    FADED = "faded"
    SKEWED = "skewed"
    HANDWRITTEN = "handwritten"
    TORN = "torn"
    BLURRY = "blurry"
    STAINED = "stained"
    LOW_CONTRAST = "low_contrast"
    MIXED_ORIENTATION = "mixed_orientation"


class BoundarySignal(str, Enum):
    """Signals indicating document boundary."""
    BLANK_OR_SEPARATOR_LIKELY = "blank_or_separator_likely"
    PAGE_NUMBERING_RESET = "page_numbering_reset"
    LETTERHEAD_CHANGE = "letterhead_change"
    DATE_DISCONTINUITY = "date_discontinuity"
    FORM_NUMBER_CHANGE = "form_number_change"
    ORIENTATION_CHANGE = "orientation_change"
    CLASSIFICATION_CHANGE = "classification_change"
    BARCODE_DIVIDER = "barcode_divider"


# V2 Enums for ABBYY OCR Integration

class OCRSource(str, Enum):
    """Source of OCR text extraction."""
    ABBYY = "abbyy"
    TESSERACT = "tesseract"
    VISION = "vision"


class VisionTrigger(str, Enum):
    """Conditions that trigger vision model fallback."""
    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    HANDWRITTEN_DETECTED = "handwritten_detected"
    COMPLEX_TABLE = "complex_table"
    DRAWING_DIAGRAM = "drawing_diagram"
    FORM_CHECKBOXES = "form_checkboxes"
    MANUAL_REQUEST = "manual_request"
