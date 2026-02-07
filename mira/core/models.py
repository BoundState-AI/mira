#!/usr/bin/env python3
"""
Module: Models
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: - SWE-032: Data validation
Safety Critical: True
"""

__version__ = "3.0.0"
import logging
import json
from datetime import datetime
from typing import Optional, List, Union, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


class SafetyCriticalError(Exception):
    """Base exception for safety-critical failures per NASA-STD-8739.8B.
    
    Used for failures that could impact system safety or data integrity.
    All safety-critical errors must be logged with full context.
    
    Examples:
        >>> raise SafetyCriticalError(
        ...     "Oxygen test data validation failed",
        ...     error_code="OXY-001",
        ...     req_id="abc-123",
        ...     severity="CRITICAL"
        ... )
    
    Compliance: SWE-061, SWE-134
    """
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        req_id: Optional[str] = None,
        severity: str = "HIGH",
        affected_material: Optional[str] = None,
        safety_domain: Optional[str] = None
    ):
        """Initialize safety-critical error.
        
        Args:
            message: Human-readable error description
            error_code: Machine-readable error identifier (e.g., OXY-001)
            req_id: Request ID for traceability
            severity: Error severity level (HIGH, CRITICAL)
            affected_material: Material ID if error is material-specific
            safety_domain: Safety domain (OXYGEN, CHEMICAL, STRUCTURAL)
        """
        super().__init__(message)
        self.error_code = error_code
        self.req_id = req_id
        self.severity = severity
        self.affected_material = affected_material
        self.safety_domain = safety_domain
        self.timestamp = datetime.utcnow()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/API responses."""
        return {
            "message": str(self),
            "error_code": self.error_code,
            "req_id": self.req_id,
            "severity": self.severity,
            "affected_material": self.affected_material,
            "safety_domain": self.safety_domain,
            "timestamp": self.timestamp.isoformat()
        }


class Availability(str, Enum):
    """Material availability status."""
    AVAILABLE = "AVAILABLE"
    LIMITED = "LIMITED"
    RESTRICTED = "RESTRICTED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"

class FlexModel(BaseModel):
    """Base model allowing extra fields and name/alias population.
    
    populate_by_name=True ensures that when a field defines an alias
    (e.g., TestReports), payloads using the actual field name (test_reports)
    still populate correctly. This fixes missing test_reports when synthetic
    data uses lowercase keys.
    """
    model_config = {
        "extra": "allow",
        "populate_by_name": True,
    }

class TestConditions(FlexModel):
    """
    Test conditions for material testing.
    
    Examples:
        >>> conditions = TestConditions(
        ...     temperature_c=500,
        ...     pressure_kpa=3000,
        ...     test_fluid="LOX"
        ... )
        
    Compliance: SWE-032 (Data validation)
    """
    strain_rate_mm_min: Optional[float] = Field(None, ge=0, description="Strain rate in mm/min")
    temperature_c: Optional[float] = Field(None, description="Temperature in Celsius")
    pressure_kpa: Optional[float] = Field(None, ge=0, description="Pressure in kPa")
    test_fluid: Optional[str] = Field(None, description="Test fluid (e.g., LOX, GOX, HYDROGEN)")
    oxygen_percent: Optional[float] = Field(None, ge=0, le=100, description="Oxygen concentration %")
    
    @field_validator("test_fluid", mode="before")
    @classmethod
    def normalize_test_fluid(cls, v):
        """Normalize test_fluid and validate against known aerospace fluids."""
        if v is None:
            return None
        v_str = str(v).strip().upper()
        
        # Normalized fluid mappings for common variants
        fluid_mapping = {
            'LIQUID OXYGEN': 'LOX',
            'O2': 'LOX',
            'L02': 'LOX',
            'LIQUID O2': 'LOX',
            'GASEOUS OXYGEN': 'GOX',
            'GO2': 'GOX',
            'GASEOUS O2': 'GOX',
            'H2': 'HYDROGEN',
            'HYDROGEN GAS': 'HYDROGEN',
            'GASEOUS HYDROGEN': 'HYDROGEN',
            'LIQUID HYDROGEN': 'HYDROGEN',
            'HE': 'HELIUM',
            'HELIUM GAS': 'HELIUM',
            'GASEOUS HELIUM': 'HELIUM',
            'N2H4': 'DISSOCIATED HYDRAZINE',
            'HYDRAZINE': 'DISSOCIATED HYDRAZINE'
        }
        
        # Check for normalized mapping first
        if v_str in fluid_mapping:
            logger.debug(f"Normalized test_fluid: '{v}' -> '{fluid_mapping[v_str]}'")
            return fluid_mapping[v_str]
        
        # Valid aerospace test fluids (normalized forms)
        valid_fluids = {
            'LOX', 'GOX', 'HYDROGEN', 'HELIUM', 'DISSOCIATED HYDRAZINE',
            'NITROGEN', 'ARGON', 'METHANE', 'PROPANE', 'ACETYLENE',
            'FLUORINE', 'CHLORINE TRIFLUORIDE', 'NITROUS OXIDE'
        }
        
        if v_str in valid_fluids:
            return v_str
        
        # Log warning but don't reject - allow unknown fluids for flexibility
        logger.debug(f"Unknown test_fluid value: '{v}' (preserved as-is)")
        return v_str
    
    @field_validator("oxygen_percent", mode="before")
    @classmethod
    def normalize_oxygen_percent(cls, v):
        """Normalize oxygen_percent, converting strings to floats."""
        if v is None:
            return None
        try:
            v_float = float(v)
            return v_float
        except (ValueError, TypeError):
            logger.warning(f"Invalid oxygen_percent value: '{v}' (set to None)")
            return None
    
    @model_validator(mode='after')
    def validate_oxygen_test_conditions(self):
        """Validate oxygen test conditions have required parameters."""
        # Silently handle missing pressure/temperature data for oxygen tests
        # This is common in the dataset and doesn't need to be logged
        return self

class TestReport(FlexModel):
    """
    Material test report with comprehensive test data.
    
    Examples:
        >>> report = TestReport(
        ...     test_type="OXYGEN_COMPATIBILITY",
        ...     test_standard="NASA-STD-6001",
        ...     test_result="PASS",
        ...     test_conditions=TestConditions(
        ...         temperature_c=500,
        ...         pressure_kpa=3000,
        ...         test_fluid="LOX"
        ...     )
        ... )
        
    Compliance: SWE-032 (Data validation), NASA-STD-6001
    """
    test_id: Optional[str] = Field("", description="Unique test identifier")
    test_type: Optional[str] = Field("GENERAL", description="Type of test performed")
    test_standard: Optional[str] = Field("", description="Test standard (e.g., NASA-STD-6001)")
    test_year: Optional[int] = Field(None, ge=1900, le=2100, description="Year test was performed")
    test_facility: Optional[str] = Field("", description="Testing facility name")
    test_conditions: TestConditions = Field(default_factory=TestConditions, description="Test conditions")
    measured_values: Dict[str, Any] = Field(default_factory=dict, description="Measured test values")
    test_result: str = Field("UNKNOWN", description="Test outcome: PASS/FAIL/UNKNOWN")
    report_number: Optional[str] = Field("", description="Test report number")
    source: Optional[str] = Field(default="MAPTIS", description="Data provenance")

    @model_validator(mode='before')
    @classmethod
    def normalize_test_report_fields(cls, values):
        """Normalize test report fields and validate oxygen tests."""
        if isinstance(values, dict):
            normalized_values = {}
            measured_values = {}
            field_mappings = {
                'TestId': 'test_id',
                'TestType': 'test_type',
                'TestStandard': 'test_standard',
                'TestYear': 'test_year',
                'TestFacility': 'test_facility',
                'TestConditions': 'test_conditions',
                'MeasuredValues': 'measured_values',
                'TestResult': 'test_result',
                'ReportNumber': 'report_number'
            }
            
            test_conditions = values.get('test_conditions', {})
            test_id = values.get('test_id', 'unknown')
            test_type = values.get('test_type', '').lower()
            
            if test_type == 'mechanical_impact':
                test_fluid = test_conditions.get('test_fluid')
                if test_fluid not in ['LOX', 'GOX', None]:
                    logger.warning(f"Invalid test_fluid '{test_fluid}' for mechanical_impact test {test_id} (set to None)")
                    test_conditions['test_fluid'] = None
            elif test_type == 'promoted_combustion':
                oxygen_percent = test_conditions.get('oxygen_percent')
                if oxygen_percent is not None:
                    try:
                        if abs(float(oxygen_percent) - 100.0) >= 0.001:
                            logger.warning(f"Invalid oxygen_percent '{oxygen_percent}' for promoted_combustion test {test_id} (set to None)")
                            test_conditions['oxygen_percent'] = None
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid oxygen_percent '{oxygen_percent}' for promoted_combustion test {test_id} (set to None)")
                        test_conditions['oxygen_percent'] = None
            
            # Normalize common condition aliases
            if isinstance(test_conditions, dict):
                # If explicit test_fluid missing or empty, use 'media' as source (common in synthetic data)
                tf = test_conditions.get('test_fluid')
                if (tf is None or str(tf).strip() == '' or str(tf).strip().upper() == 'NONE') and 'media' in test_conditions:
                    test_conditions['test_fluid'] = test_conditions.get('media')

            for key, value in values.items():
                normalized_key = field_mappings.get(key, key)
                if normalized_key == 'measured_values' and isinstance(value, dict):
                    value = {field_mappings.get(k, k): v for k, v in value.items()}
                    measured_values.update(value)
                else:
                    normalized_values[normalized_key] = value
            
            if measured_values:
                existing_measured = normalized_values.get('measured_values', {})
                if isinstance(existing_measured, dict):
                    existing_measured.update(measured_values)
                    normalized_values['measured_values'] = existing_measured
                else:
                    normalized_values['measured_values'] = measured_values
            
            normalized_values['test_conditions'] = test_conditions
            
            # Handle lists in measured_values by extracting first element
            if 'measured_values' in normalized_values and isinstance(normalized_values['measured_values'], dict):
                cleaned_measured = {}
                for key, value in normalized_values['measured_values'].items():
                    if isinstance(value, list) and value:
                        # Extract first non-None element from list
                        for v in value:
                            if v is not None:
                                cleaned_measured[key] = v
                                break
                        else:
                            cleaned_measured[key] = None
                    else:
                        cleaned_measured[key] = value
                normalized_values['measured_values'] = cleaned_measured
            
            return normalized_values
        return values
    
    @model_validator(mode='after')
    def validate_test_report_requirements(self):
        """Validate test report has required data based on test type."""
        # Oxygen compatibility tests require specific data
        if self.test_type and 'OXYGEN' in self.test_type.upper():
            if self.test_standard == "":
                logger.warning(f"Oxygen test {self.test_id} missing test standard")
            if self.test_result == "UNKNOWN":
                logger.warning(f"Oxygen test {self.test_id} has unknown result")
            if not self.test_conditions.test_fluid:
                logger.warning(f"Oxygen test {self.test_id} missing test fluid")
        
        # Mechanical tests require measured values
        if self.test_type and 'MECHANICAL' in self.test_type.upper():
            if not self.measured_values:
                logger.warning(f"Mechanical test {self.test_id} missing measured values")
        
        return self

class Material(FlexModel):
    """
    Material data model with comprehensive testing information.
    
    Examples:
        >>> material = Material(
        ...     material_id="MAT-001",
        ...     name="Aluminum 6061-T6",
        ...     composition="Al-Mg-Si alloy",
        ...     test_reports=[TestReport(...)]
        ... )
        
    Compliance: SWE-032 (Data validation), NASA-STD-6016
    """
    material_id: str = Field(..., min_length=1, description="Unique material identifier")
    source: Optional[str] = Field(default="MAPTIS", description="Data provenance")
    designation: Optional[str] = Field("", description="Material designation/name", alias='Designation')
    name: Optional[str] = Field("", description="Material name (alias for designation)", alias='material_name')
    material_type: Optional[str] = Field("", description="Material category (e.g., METAL, POLYMER)", alias='MaterialType')
    material_subtype: Optional[str] = Field("", description="Material subcategory", alias='MaterialSubtype')
    composition: Optional[str] = Field("", description="Chemical composition", alias='Composition')
    form: Optional[str] = Field("", description="Material form (e.g., Sheet, Bar, Rod)")
    specification: Optional[str] = Field("", description="Material specification")
    manufacturer: Optional[str] = Field("", description="Manufacturer name", alias='Manufacturer')
    heat_lot_batch: Optional[str] = Field("", description="Heat/lot/batch number")
    test_reports: List[TestReport] = Field(default_factory=list, description="Associated test reports", alias='TestReports')
    notes: Optional[str] = Field("", description="Additional notes", alias='Notes')
    availability: Optional[Availability] = Field(None, description="Availability status")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")
    search_text: Optional[str] = Field("", description="Searchable text for indexing")
    oxygen_tests: Optional[int] = Field(None, ge=0, description="Number of oxygen compatibility tests")
    oxygen_a_ratings: Optional[int] = Field(None, ge=0, description="Number of A-ratings for oxygen")
    similarity_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Search similarity score", alias='SimilarityScore')
    
    @model_validator(mode='after')
    def validate_material_integrity(self):
        """Validate material data integrity and compute derived fields."""
        # Sync name and designation fields
        if self.designation and not self.name:
            self.name = self.designation
        elif self.name and not self.designation:
            self.designation = self.name
            
        # Count oxygen tests and A-ratings if not provided
        if self.test_reports and (self.oxygen_tests is None or self.oxygen_a_ratings is None):
            oxygen_test_count = 0
            oxygen_a_count = 0
            
            for report in self.test_reports:
                if report.test_type and 'OXYGEN' in report.test_type.upper():
                    oxygen_test_count += 1
                    if report.test_result == "PASS" and report.test_standard == "NASA-STD-6001":
                        oxygen_a_count += 1
            
            if self.oxygen_tests is None:
                self.oxygen_tests = oxygen_test_count
            if self.oxygen_a_ratings is None:
                self.oxygen_a_ratings = oxygen_a_count
        
        # Warn if material lacks critical data
        if not self.name and not self.designation and not self.composition:
            logger.warning(f"Material {self.material_id} lacks name/designation and composition")
            
        # Build search text if not provided
        if not self.search_text:
            parts = []
            for field in [self.designation, self.composition, self.form, self.manufacturer, self.notes]:
                if field:
                    parts.append(field.lower())
            self.search_text = " ".join(parts)
        
        return self

# Response models required by main.py
class MaterialResponse(BaseModel):
    """
    Single material response with metadata.
    
    Examples:
        >>> response = MaterialResponse(
        ...     material_id="MAT-001",
        ...     name="Aluminum 6061-T6",
        ...     oxygen_tests=5,
        ...     oxygen_a_ratings=3
        ... )
        
    Compliance: SWE-049 (Standardized response models)
    """
    material_id: str = Field(..., description="Material identifier")
    name: str = Field(..., description="Material name")
    material_type: Optional[str] = Field(None, description="Material type")
    material_subtype: Optional[str] = Field(None, description="Material subtype")
    composition: Optional[str] = Field(None, description="Chemical composition")
    test_reports: List[TestReport] = Field(default_factory=list, description="Test reports")
    oxygen_tests: Optional[int] = Field(None, ge=0, description="Oxygen test count")
    oxygen_a_ratings: Optional[int] = Field(None, ge=0, description="Oxygen A-rating count")
    similarity_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Search similarity")
    
    model_config = {"extra": "allow"}  # Allow extra fields for response flexibility
    
    @classmethod
    def from_material(cls, material: Material) -> 'MaterialResponse':
        """Create MaterialResponse from Material object"""
        response = cls(
            material_id=material.material_id,
            name=material.name or "",
            material_type=material.material_type or "",
            material_subtype=material.material_subtype,
            composition=material.composition,
            test_reports=material.test_reports,
            oxygen_tests=getattr(material, 'oxygen_tests', None),
            oxygen_a_ratings=getattr(material, 'oxygen_a_ratings', None),
            similarity_score=getattr(material, 'similarity_score', None)
        )
        # Add extra fields if present
        response_dict = response.model_dump()
        for field in ['source', 'designation', 'form', 'specification', 'manufacturer', 'heat_lot_batch', 'notes', 'availability', 'created_at', 'updated_at', 'search_text']:
            if hasattr(material, field):
                response_dict[field] = getattr(material, field)
        # Add aliases if not present
        if 'designation' not in response_dict and hasattr(material, 'Designation'):
            response_dict['designation'] = material.Designation
        if 'form' not in response_dict and hasattr(material, 'Form'):
            response_dict['form'] = material.Form
        return cls(**response_dict)

class MaterialsListResponse(BaseModel):
    """
    Collection of materials response.
    
    Compliance: SWE-049 (Standardized response models)
    """
    materials: List[Material] = Field(..., description="List of materials")
    total_count: int = Field(..., ge=0, description="Total material count")
    page: int = Field(1, ge=1, description="Current page number")
    limit: int = Field(50, ge=1, le=1000, description="Items per page")
    has_next: bool = Field(False, description="Has next page")
    
    model_config = {"extra": "forbid"}

class SearchResponse(BaseModel):
    """
    Search response with results and metadata.
    
    Examples:
        >>> response = SearchResponse(
        ...     query="aluminum sheet",
        ...     total_results=10,
        ...     results=[...],
        ...     search_type="semantic",
        ...     processing_time_ms=45.2
        ... )
        
    Compliance: SWE-049, SWE-055 (Performance tracking)
    """
    query: str = Field(..., description="Original search query")
    total_results: int = Field(..., ge=0, description="Total results found")
    results: List[MaterialResponse] = Field(..., description="Search results")
    search_type: str = Field(..., description="Search algorithm used")
    processing_time_ms: float = Field(..., ge=0, description="Processing time in milliseconds")
    interpretation: Optional[str] = Field(None, description="Query interpretation")
    answer: Optional[str] = Field(None, description="Direct answer if applicable")
    filters: Optional[dict] = Field(None, description="Applied filters")
    comparison_data: Optional[dict] = Field(None, description="Comparison data for versus queries")
    
    model_config = {"extra": "forbid"}

class RiskAssessmentResponse(BaseModel):
    """
    Risk assessment response for material analysis.
    
    Compliance: SWE-134 (Safety-critical assessment)
    """
    material_id: str = Field(..., description="Material being assessed")
    risk_level: str = Field(..., description="Risk level: LOW/MEDIUM/HIGH/CRITICAL")
    risk_factors: List[str] = Field(..., description="Identified risk factors")
    recommendations: List[str] = Field(..., description="Risk mitigation recommendations")
    pfas_detected: bool = Field(False, description="PFAS contamination detected")
    
    model_config = {"extra": "forbid"}
    
    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str) -> str:
        """Validate risk level is valid."""
        valid_levels = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Invalid risk level: {v}. Must be one of {valid_levels}")
        return v_upper

# Compliance record models
class MIULDocument(BaseModel):
    """
    MIUL (Materials Identification and Usage List) document metadata.
    
    Examples:
        >>> doc = MIULDocument(
        ...     miul_id="MIUL-001",
        ...     title="Oxygen Compatible Materials",
        ...     responsible_center="JSC"
        ... )
        
    Compliance: SWE-049, NASA-STD-6016
    """
    miul_id: str = Field(..., description="Unique MIUL identifier")
    title: str = Field(..., description="Document title")
    revision: Optional[str] = Field(None, description="Document revision")
    creation_date: Optional[str] = Field(None, description="Creation date")
    last_review: Optional[str] = Field(None, description="Last review date")
    next_review: Optional[str] = Field(None, description="Next review date")
    responsible_center: Optional[str] = Field(None, description="Responsible NASA center")
    center_description: Optional[str] = Field(None, description="Center description")
    category: Optional[str] = Field(None, description="Document category")
    classification: Optional[str] = Field(None, description="Classification level")
    status: Optional[str] = Field(None, description="Document status")
    document_info: Optional[Dict[str, Any]] = Field(None, description="Additional document info")
    materials_list: Optional[List[Dict[str, Any]]] = Field(None, description="Associated materials")
    pdf_path: Optional[str] = Field(None, description="Path to PDF document")
    tags: Optional[List[str]] = Field(None, description="Document tags")
    contacts: Optional[Dict[str, str]] = Field(None, description="Contact information")
    
    model_config = {"extra": "allow"}

class MIULRecord(BaseModel):
    """
    MIUL material relationship record.
    
    Links materials to MIUL documents with usage restrictions.
    
    Examples:
        >>> record = MIULRecord(
        ...     material_id="MAT-001",
        ...     miul_id="MIUL-001",
        ...     approval_status="APPROVED",
        ...     restrictions=["Max temperature 500°C"]
        ... )
        
    Compliance: SWE-049, NASA-STD-6016
    """
    material_id: str = Field(..., description="Material identifier")
    miul_id: str = Field(..., description="MIUL document identifier")
    miul_title: Optional[str] = Field(None, description="MIUL document title")
    status_in_miul: Optional[str] = Field(None, description="Material status in MIUL")
    usage_category: Optional[str] = Field(None, description="Usage category")
    usage_level: Optional[str] = Field(None, description="Usage level/rating")
    restrictions: List[str] = Field(default_factory=list, description="Usage restrictions")
    approval_status: Optional[str] = Field(None, description="Approval status")
    last_updated: Optional[str] = Field(None, description="Last update timestamp")
    
    model_config = {"extra": "forbid"}
    
    @field_validator("approval_status")
    @classmethod
    def validate_approval_status(cls, v: Optional[str]) -> Optional[str]:
        """Validate approval status is valid."""
        if v is None:
            return v
        valid_statuses = {"APPROVED", "CONDITIONAL", "RESTRICTED", "PENDING", "REJECTED"}
        v_upper = v.upper()
        if v_upper not in valid_statuses:
            logger.warning(f"Unknown approval status: {v}")
        return v_upper

class MUADocument(BaseModel):
    """
    MUA (Materials Usage Agreement) document metadata.
    
    Examples:
        >>> doc = MUADocument(
        ...     mua_id="MUA-2024-001",
        ...     title="Advanced Composites Usage Agreement",
        ...     responsible_center="MSFC"
        ... )
        
    Compliance: SWE-049, NASA-STD-6016
    """
    mua_id: str = Field(..., description="Unique MUA identifier")
    title: str = Field(..., description="Document title")
    revision: Optional[str] = Field(None, description="Document revision")
    creation_date: Optional[str] = Field(None, description="Creation date")
    last_review: Optional[str] = Field(None, description="Last review date")
    next_review: Optional[str] = Field(None, description="Next review date")
    responsible_center: Optional[str] = Field(None, description="Responsible NASA center")
    center_description: Optional[str] = Field(None, description="Center description")
    category: Optional[str] = Field(None, description="Document category")
    classification: Optional[str] = Field(None, description="Classification level")
    status: Optional[str] = Field(None, description="Document status")
    document_info: Optional[Dict[str, Any]] = Field(None, description="Additional document info")
    materials_list: Optional[List[Dict[str, Any]]] = Field(None, description="Associated materials")
    pdf_path: Optional[str] = Field(None, description="Path to PDF document")
    tags: Optional[List[str]] = Field(None, description="Document tags")
    contacts: Optional[Dict[str, str]] = Field(None, description="Contact information")
    
    model_config = {"extra": "forbid"}

class MUARecord(BaseModel):
    """
    MUA material relationship record.
    
    Links materials to MUA documents with usage authorizations.
    
    Examples:
        >>> record = MUARecord(
        ...     material_id="MAT-002",
        ...     mua_id="MUA-2024-001",
        ...     usage_authorization="AUTHORIZED",
        ...     conditions=["Vacuum environment only"],
        ...     expiry_date="2025-12-31"
        ... )
        
    Compliance: SWE-049, NASA-STD-6016
    """
    material_id: str = Field(..., description="Material identifier")
    mua_id: str = Field(..., description="MUA document identifier")
    mua_title: Optional[str] = Field(None, description="MUA document title")
    usage_authorization: Optional[str] = Field(None, description="Authorization status")
    conditions: List[str] = Field(default_factory=list, description="Usage conditions")
    expiry_date: Optional[str] = Field(None, description="Authorization expiry date")
    last_updated: Optional[str] = Field(None, description="Last update timestamp")
    
    model_config = {"extra": "forbid"}
    
    @model_validator(mode='after')
    def validate_authorization(self):
        """Validate authorization and expiry."""
        if self.usage_authorization == "AUTHORIZED" and self.expiry_date:
            try:
                from datetime import datetime
                expiry = datetime.fromisoformat(self.expiry_date.replace('Z', '+00:00'))
                if expiry < datetime.now():
                    logger.warning(f"MUA {self.mua_id} authorization expired on {self.expiry_date}")
            except Exception as e:
                logger.debug(f"Could not parse expiry date: {e}")
        return self

# Request/Query models
class QueryRequest(BaseModel):
    """
    Search query request.
    
    Examples:
        >>> query = QueryRequest(
        ...     query="aluminum oxygen compatible",
        ...     limit=10,
        ...     filters={"material_type": "METAL"}
        ... )
        
    Compliance: SWE-049
    """
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    limit: int = Field(25, ge=1, le=100, description="Number of results")
    offset: int = Field(0, ge=0, description="Result offset for pagination")
    filters: Optional[Dict[str, Any]] = Field(None, description="Search filters")
    
    model_config = {"extra": "forbid"}

class HealthResponse(BaseModel):
    """
    System health check response.
    
    Compliance: SWE-055
    """
    status: str = Field(..., description="System status")
    version: str = Field(..., description="API version")
    timestamp: str = Field(..., description="Current timestamp")
    services: Dict[str, bool] = Field(..., description="Service status")
    
    model_config = {"extra": "forbid"}

# Data loading function
def load_data(file_path: str) -> List[Material]:
    """Load materials data from file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle if data is a list instead of dict
        if isinstance(data, list):
            materials_data = data
        else:
            materials_data = data.get('materials', [])

        materials = []
        for item in materials_data:
            try:
                material = Material.model_validate(item)
                materials.append(material)
            except Exception as e:
                logger.warning(f"Failed to validate material {item.get('material_id', 'unknown')}: {e}")
                continue
        
        logger.info(f"Loaded {len(materials)} materials from {file_path}")
        return materials

    except Exception as e:
        logger.error(f"Failed to load data from {file_path}: {e}")
        return []


def extract_material_properties(test_reports):
    """Extract material properties from test reports.
    
    Args:
        test_reports: List of TestReport objects
        
    Returns:
        Dictionary of extracted properties
    """
    if not test_reports:
        return {}
    
    properties = {}
    
    try:
        for report in test_reports:
            if hasattr(report, 'measured_values') and report.measured_values:
                # Extract measured values from test reports
                for prop_name, value in report.measured_values.items():
                    if value is not None and value != '':
                        properties[prop_name] = value
                        
            # Also check for direct properties on the report object
            for attr in ['test_result', 'test_type', 'test_standard']:
                if hasattr(report, attr):
                    attr_value = getattr(report, attr)
                    if attr_value and attr_value != 'UNKNOWN':
                        properties[attr] = attr_value
                        
    except Exception as e:
        logger.warning(f"Error extracting properties from test reports: {e}")

    return properties


# ============================================================================
# API Request Models
# ============================================================================

class ReactSearchRequest(BaseModel):
    """Request model for React frontend search endpoint.

    Compliance: SWE-032 (Data validation)
    """
    query: str = Field("", min_length=0, description="Search query (empty for browsing all materials)")
    top_k: int = Field(25, ge=1, le=100, description="Maximum number of results")
    contract_filter: Optional[List[str]] = Field(None, description="Filter by contract IDs")
    rating_filter: Optional[str] = Field(None, description="Filter by material rating")
    min_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum similarity score")
