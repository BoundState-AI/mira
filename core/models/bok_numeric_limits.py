#!/usr/bin/env python3
"""
Module: Bok Numeric Limits
Purpose: BOK Numeric Limits Data Model

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (traceability), SWE-033 (deterministic safety)
Safety Critical: False
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum
import uuid


class LimitType(str, Enum):
    """Type of numeric limit."""
    MAX_PRESSURE = "max_pressure"
    MIN_PRESSURE = "min_pressure"
    MAX_TEMPERATURE = "max_temperature"
    MIN_TEMPERATURE = "min_temperature"
    MAX_CONCENTRATION = "max_concentration"
    MIN_CONCENTRATION = "min_concentration"
    MAX_VELOCITY = "max_velocity"
    MAX_ENERGY = "max_energy"


class LimitUnits(str, Enum):
    """Units for numeric limits."""
    PSIA = "psia"
    PSIG = "psig"
    BAR = "bar"
    KPA = "kpa"
    DEG_F = "degF"
    DEG_C = "degC"
    KELVIN = "K"
    PERCENT = "percent"
    PPM = "ppm"
    FT_PER_SEC = "ft/s"
    M_PER_SEC = "m/s"
    JOULES = "J"
    FT_LBS = "ft-lbs"


class Configuration(str, Enum):
    """Material configuration affecting limits."""
    STATIC = "static"
    DYNAMIC = "dynamic"
    MESH = "mesh"
    FILTER = "filter"
    SOLID = "solid"
    WIRE = "wire"
    TUBE = "tube"
    TANK = "tank"
    VALVE = "valve"
    REGULATOR = "regulator"
    ALL = "all"  # Applies to all configurations


class Environment(str, Enum):
    """Operating environment."""
    OXYGEN = "oxygen"
    GOX = "gox"
    LOX = "lox"
    HYDROGEN = "hydrogen"
    GH2 = "gh2"
    LH2 = "lh2"
    CRYOGENIC = "cryogenic"
    VACUUM = "vacuum"
    AIR = "air"


class BOKNumericLimit(BaseModel):
    """
    Single numeric limit from BOK standard.

    This is the structured data format used by BoundaryChecker.
    These records are extracted from BOK sections using the BOKLimitParser.
    """
    limit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Material identification
    material_family: str = Field(..., description="Material family (e.g., 'aluminum', 'titanium', 'stainless_steel_300')")
    material_variants: List[str] = Field(default_factory=list, description="Specific alloys (e.g., ['6061', '7075'])")

    # Environment
    environment: Environment = Field(..., description="Operating environment")

    # Limit specification
    limit_type: LimitType = Field(..., description="Type of limit (max_pressure, min_temp, etc.)")
    limit_value: float = Field(..., description="Numeric value of limit")
    units: LimitUnits = Field(..., description="Units for the limit value")

    # Configuration (if applicable)
    configuration: Optional[Configuration] = Field(None, description="Material configuration (static, dynamic, mesh, etc.)")

    # Traceability
    source_doc: str = Field(..., description="Source document (e.g., 'NASA-STD-6016C')")
    section_ref: Optional[str] = Field(None, description="Section reference (e.g., '4.3.2.1')")
    section_id: Optional[str] = Field(None, description="UUID of BOK section")
    page_ref: Optional[str] = Field(None, description="Page number if applicable")

    # Context
    prohibition_text: Optional[str] = Field(None, description="Original prohibition text from document")
    notes: Optional[str] = Field(None, description="Additional notes")
    confidence: float = Field(0.9, ge=0.0, le=1.0, description="Parser confidence in extraction")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    parsed_by: str = Field("manual", description="Parser version or 'manual' for human entry")
    is_reviewed: bool = Field(False, description="Has been human-reviewed")

    model_config = {"extra": "forbid"}


class BOKNumericLimitCreate(BaseModel):
    """Request model for creating a new BOK numeric limit."""
    material_family: str
    material_variants: List[str] = []
    environment: Environment
    limit_type: LimitType
    limit_value: float
    units: LimitUnits
    configuration: Optional[Configuration] = None
    source_doc: str
    section_ref: Optional[str] = None
    prohibition_text: Optional[str] = None
    notes: Optional[str] = None


class BOKNumericLimitResponse(BaseModel):
    """Response model for BOK numeric limit."""
    limit_id: str
    material_family: str
    environment: str
    limit_type: str
    limit_value: float
    units: str
    configuration: Optional[str]
    source_doc: str
    section_ref: Optional[str]
    is_reviewed: bool


class BOKNumericLimitsListResponse(BaseModel):
    """Response model for list of BOK numeric limits."""
    limits: List[BOKNumericLimitResponse]
    total_count: int
    page: int = 1
    limit: int = 50


# ============================================================================
# STUB PARSER - To be implemented with actual BOK section parsing
# ============================================================================

class BOKLimitParser:
    """
    Parser for extracting numeric limits from BOK sections.

    STUB IMPLEMENTATION - Returns hardcoded critical limits.
    Full implementation should parse bok.sections table and extract limits.
    """

    # Known prohibition patterns
    PROHIBITION_PATTERNS = [
        r"shall not be used above (\d+(?:\.\d+)?)\s*(psia|psig|psi)",
        r"shall not be used in.*above (\d+(?:\.\d+)?)\s*(psia|psig|psi)",
        r"prohibited.*above (\d+(?:\.\d+)?)\s*(psia|psig|psi)",
        r"maximum (?:operating )?pressure.*?(\d+(?:\.\d+)?)\s*(psia|psig|psi)",
        r"not.*exceed (\d+(?:\.\d+)?)\s*(psia|psig|psi)",
    ]

    def __init__(self, db_url: Optional[str] = None):
        """Initialize parser with database connection."""
        self.db_url = db_url

    def get_hardcoded_limits(self) -> List[BOKNumericLimit]:
        """
        Return hardcoded critical limits.

        These are the most critical limits from NASA-STD-6016C and JSC-27301F.
        In production, these should be parsed from the database.
        """
        return [
            # Aluminum limits
            BOKNumericLimit(
                material_family="aluminum",
                material_variants=["6061", "7075", "2024", "2219"],
                environment=Environment.OXYGEN,
                limit_type=LimitType.MAX_PRESSURE,
                limit_value=3000.0,
                units=LimitUnits.PSIA,
                configuration=Configuration.STATIC,
                source_doc="NASA-STD-6016C",
                section_ref="4.3.2.1",
                prohibition_text="Aluminum alloys shall not be used above 3000 psia in static oxygen service",
                notes="Static service only; dynamic service limit is 100 psia",
                is_reviewed=True
            ),
            BOKNumericLimit(
                material_family="aluminum",
                material_variants=["6061", "7075", "2024", "2219"],
                environment=Environment.OXYGEN,
                limit_type=LimitType.MAX_PRESSURE,
                limit_value=100.0,
                units=LimitUnits.PSIA,
                configuration=Configuration.DYNAMIC,
                source_doc="NASA-STD-6016C",
                section_ref="4.3.2.1",
                prohibition_text="Aluminum alloys shall not be used above 100 psia in dynamic oxygen service",
                notes="Dynamic service (valves, regulators, flow conditions)",
                is_reviewed=True
            ),

            # Titanium limits
            BOKNumericLimit(
                material_family="titanium",
                material_variants=["6Al-4V", "Ti-6-4", "CP-Ti"],
                environment=Environment.OXYGEN,
                limit_type=LimitType.MAX_PRESSURE,
                limit_value=100.0,
                units=LimitUnits.PSIA,
                configuration=Configuration.ALL,
                source_doc="NASA-STD-6016C",
                section_ref="4.3.3",
                prohibition_text="Titanium and titanium alloys shall not be used above 100 psia in oxygen service",
                notes="All configurations - titanium is highly reactive with oxygen",
                is_reviewed=True
            ),

            # Stainless steel 300-series (generally compatible)
            BOKNumericLimit(
                material_family="stainless_steel_300",
                material_variants=["316", "316L", "304", "304L", "321", "347"],
                environment=Environment.OXYGEN,
                limit_type=LimitType.MAX_PRESSURE,
                limit_value=10000.0,
                units=LimitUnits.PSIA,
                configuration=Configuration.ALL,
                source_doc="NASA-STD-6016C",
                section_ref="4.3.1",
                prohibition_text="Austenitic stainless steels are generally compatible with oxygen to 10,000 psia",
                notes="Austenitic (300-series) stainless steels are preferred for oxygen service",
                is_reviewed=True
            ),

            # Carbon steel hydrogen limits
            BOKNumericLimit(
                material_family="carbon_steel",
                material_variants=["A36", "1018", "4130", "4340"],
                environment=Environment.HYDROGEN,
                limit_type=LimitType.MAX_PRESSURE,
                limit_value=1000.0,
                units=LimitUnits.PSIA,
                configuration=Configuration.ALL,
                source_doc="NASA-STD-8719.17",
                section_ref="5.2.1",
                prohibition_text="Carbon steel susceptible to hydrogen embrittlement above 1000 psia",
                notes="High-strength variants more susceptible to embrittlement",
                is_reviewed=True
            ),

            # Nickel alloys (generally good for H2)
            BOKNumericLimit(
                material_family="nickel_alloy",
                material_variants=["Inconel 625", "Inconel 718", "Monel 400", "Hastelloy C-276"],
                environment=Environment.HYDROGEN,
                limit_type=LimitType.MAX_PRESSURE,
                limit_value=15000.0,
                units=LimitUnits.PSIA,
                configuration=Configuration.ALL,
                source_doc="NASA-STD-8719.17",
                section_ref="5.3.2",
                prohibition_text="Nickel alloys are compatible with hydrogen to 15,000 psia",
                notes="Preferred materials for high-pressure hydrogen service",
                is_reviewed=True
            ),
        ]

    def parse_section(self, section_text: str, metadata: dict) -> List[BOKNumericLimit]:
        """
        Parse a BOK section to extract numeric limits.

        STUB: Returns empty list. Full implementation should use regex patterns
        to extract limits from section text.

        Args:
            section_text: Full text of BOK section
            metadata: Section metadata (spec_id, section_number, etc.)

        Returns:
            List of extracted BOKNumericLimit objects
        """
        # TODO: Implement actual parsing logic
        # 1. Search for prohibition patterns
        # 2. Extract material mentions
        # 3. Extract numeric values and units
        # 4. Create BOKNumericLimit objects
        return []

    def load_all_limits(self) -> List[BOKNumericLimit]:
        """
        Load all limits from database and combine with hardcoded.

        Returns hardcoded limits for now. Full implementation should
        query bok_numeric_limits table.
        """
        return self.get_hardcoded_limits()


# ============================================================================
# DATABASE SCHEMA (for reference - to be created via migration)
# ============================================================================

BOK_NUMERIC_LIMITS_SCHEMA = """
-- BOK Numeric Limits Table
-- Stores structured numeric limits extracted from BOK standards

CREATE TABLE IF NOT EXISTS bok.numeric_limits (
    limit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Material identification
    material_family VARCHAR(100) NOT NULL,
    material_variants JSONB DEFAULT '[]'::jsonb,

    -- Environment
    environment VARCHAR(50) NOT NULL,

    -- Limit specification
    limit_type VARCHAR(50) NOT NULL,
    limit_value NUMERIC(12, 4) NOT NULL,
    units VARCHAR(20) NOT NULL,

    -- Configuration
    configuration VARCHAR(50),

    -- Traceability
    source_doc VARCHAR(100) NOT NULL,
    section_ref VARCHAR(50),
    section_id UUID REFERENCES bok.sections(section_id),
    page_ref VARCHAR(20),

    -- Context
    prohibition_text TEXT,
    notes TEXT,
    confidence NUMERIC(3, 2) DEFAULT 0.9,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    parsed_by VARCHAR(50) DEFAULT 'manual',
    is_reviewed BOOLEAN DEFAULT FALSE,

    -- Indexes
    CONSTRAINT valid_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_bok_limits_material ON bok.numeric_limits(material_family);
CREATE INDEX IF NOT EXISTS idx_bok_limits_environment ON bok.numeric_limits(environment);
CREATE INDEX IF NOT EXISTS idx_bok_limits_source ON bok.numeric_limits(source_doc);
CREATE INDEX IF NOT EXISTS idx_bok_limits_type ON bok.numeric_limits(limit_type);

-- Combined index for boundary checker lookups
CREATE INDEX IF NOT EXISTS idx_bok_limits_lookup
ON bok.numeric_limits(material_family, environment, configuration);
"""
