#!/usr/bin/env python3
"""
Module: Models
Purpose: MIUL System Data Models - Pydantic models for type safety and validation

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

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field, validator
import uuid


class BOMItem(BaseModel):
    """Single item from a Bill of Materials"""
    part_number: str = Field(..., description="Unique part identifier")
    quantity: float = Field(default=1.0, description="Quantity required")
    drawing_number: Optional[str] = Field(None, description="Associated drawing number")
    description: Optional[str] = Field(None, description="Part description")
    material_type: Optional[str] = Field(None, description="Material category")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="Original row data")
    
    @validator('part_number')
    def part_number_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Part number cannot be empty")
        return v.strip()
    
    @validator('quantity')
    def quantity_positive(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v


class BOMDocument(BaseModel):
    """Complete Bill of Materials document"""
    items: List[BOMItem] = Field(..., description="List of BOM items")
    document_id: Optional[str] = Field(None, description="Document identifier")
    version: Optional[str] = Field(None, description="Document version")
    created_date: Optional[datetime] = Field(None, description="Creation timestamp")
    source_info: Optional[Dict[str, Any]] = Field(None, description="Source file metadata")
    
    @validator('items')
    def items_not_empty(cls, v):
        if not v:
            raise ValueError("BOM must contain at least one item")
        return v
    
    @property
    def total_items(self) -> int:
        """Total number of items in BOM"""
        return len(self.items)
    
    @property
    def unique_parts(self) -> int:
        """Number of unique part numbers"""
        return len(set(item.part_number for item in self.items))
    
    @property
    def total_quantity(self) -> float:
        """Sum of all quantities"""
        return sum(item.quantity for item in self.items)


class DrawingMaterialUsage(BaseModel):
    """Material usage information extracted from technical drawings"""
    material_code: str = Field(..., description="Material identifier")
    material_name: Optional[str] = Field(None, description="Material common name")
    quantity_used: float = Field(..., description="Quantity specified in drawing")
    unit_of_measure: Optional[str] = Field("ea", description="Unit of measure")
    usage_location: Optional[str] = Field(None, description="Location/zone in drawing")
    specification_reference: Optional[str] = Field(None, description="Material spec reference")
    notes: Optional[str] = Field(None, description="Additional notes from drawing")
    confidence_score: Optional[float] = Field(None, description="OCR/extraction confidence")
    
    @validator('quantity_used')
    def quantity_positive(cls, v):
        if v <= 0:
            raise ValueError("Material quantity must be positive")
        return v


class DrawingDocument(BaseModel):
    """Single technical drawing document"""
    drawing_number: str = Field(..., description="Drawing identifier")
    title: Optional[str] = Field(None, description="Drawing title")
    revision: Optional[str] = Field(None, description="Drawing revision")
    sheet_number: Optional[int] = Field(None, description="Sheet number")
    total_sheets: Optional[int] = Field(None, description="Total sheets in drawing")
    material_usage: List[DrawingMaterialUsage] = Field(default_factory=list, description="Materials found in drawing")
    source_file: Optional[str] = Field(None, description="Source file path")
    extraction_metadata: Optional[Dict[str, Any]] = Field(None, description="OCR/parsing metadata")
    
    @validator('drawing_number')
    def drawing_number_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Drawing number cannot be empty")
        return v.strip()


class DrawingPackage(BaseModel):
    """Collection of related technical drawings"""
    package_id: str = Field(..., description="Package identifier")
    drawings: List[DrawingDocument] = Field(..., description="List of drawings")
    package_title: Optional[str] = Field(None, description="Package description")
    created_date: Optional[datetime] = Field(None, description="Package creation date")
    source_info: Optional[Dict[str, Any]] = Field(None, description="Source metadata")
    
    @validator('drawings')
    def drawings_not_empty(cls, v):
        if not v:
            raise ValueError("Drawing package must contain at least one drawing")
        return v
    
    @property
    def total_drawings(self) -> int:
        """Total number of drawings in package"""
        return len(self.drawings)
    
    @property
    def total_materials(self) -> int:
        """Total number of material usage entries across all drawings"""
        return sum(len(drawing.material_usage) for drawing in self.drawings)


class MIULMetadata(BaseModel):
    """Metadata for MIUL build process"""
    build_id: str = Field(..., description="Unique build identifier")
    build_timestamp: datetime = Field(..., description="When build was executed")
    processing_time_seconds: float = Field(..., description="Total processing time")
    source_bom_items: int = Field(..., description="Number of input BOM items")
    output_miul_rows: int = Field(..., description="Number of output MIUL rows")
    material_coverage_percent: float = Field(..., description="Percentage of parts with material mapping")
    spec_coverage_percent: float = Field(..., description="Percentage of materials with specifications")
    validation_warnings: int = Field(default=0, description="Number of validation warnings")
    processing_errors: int = Field(default=0, description="Number of processing errors")
    nasa_swe_compliant: bool = Field(default=False, description="Meets NASA Software Engineering requirements")
    deterministic_hash: Optional[str] = Field(None, description="Hash for reproducibility verification")
    
    @validator('material_coverage_percent', 'spec_coverage_percent')
    def percent_range(cls, v):
        if not 0 <= v <= 100:
            raise ValueError("Percentage must be between 0 and 100")
        return v
    
    @validator('processing_time_seconds')
    def time_positive(cls, v):
        if v < 0:
            raise ValueError("Processing time cannot be negative")
        return v


class MIULBuildResult(BaseModel):
    """Complete result of MIUL build process"""
    miul_data: Any = Field(..., description="Generated MIUL data (DataFrame)")  # pandas DataFrame
    metadata: MIULMetadata = Field(..., description="Build metadata")
    warnings: List[str] = Field(default_factory=list, description="Processing warnings")
    errors: List[str] = Field(default_factory=list, description="Processing errors")
    audit_trail: List[Dict[str, Any]] = Field(default_factory=list, description="Audit trail for compliance")
    
    class Config:
        arbitrary_types_allowed = True  # Allow pandas DataFrame
    
    @validator('miul_data')
    def validate_miul_data(cls, v):
        if not isinstance(v, pd.DataFrame):
            raise ValueError("MIUL data must be a pandas DataFrame")
        if len(v) == 0:
            raise ValueError("MIUL DataFrame cannot be empty")
        return v
    
    @property
    def success(self) -> bool:
        """True if build completed without errors"""
        return len(self.errors) == 0
    
    @property
    def summary_stats(self) -> Dict[str, Any]:
        """Summary statistics for the build"""
        return {
            "success": self.success,
            "input_items": self.metadata.source_bom_items,
            "output_rows": self.metadata.output_miul_rows,
            "material_coverage": f"{self.metadata.material_coverage_percent:.1f}%",
            "spec_coverage": f"{self.metadata.spec_coverage_percent:.1f}%",
            "warnings": len(self.warnings),
            "errors": len(self.errors),
            "processing_time": f"{self.metadata.processing_time_seconds:.2f}s",
            "nasa_compliant": self.metadata.nasa_swe_compliant
        }
    
    def to_excel(self, file_path: Union[str, Path], include_metadata: bool = True) -> None:
        """Export MIUL result to Excel file"""
        file_path = Path(file_path)
        
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # Write main MIUL data
            self.miul_data.to_excel(writer, sheet_name='MIUL', index=False)
            
            if include_metadata:
                # Write metadata
                metadata_dict = self.metadata.dict()
                metadata_df = pd.DataFrame([metadata_dict])
                metadata_df.to_excel(writer, sheet_name='Metadata', index=False)
                
                # Write warnings/errors if any
                if self.warnings or self.errors:
                    issues_data = []
                    for warning in self.warnings:
                        issues_data.append({"Type": "Warning", "Message": warning})
                    for error in self.errors:
                        issues_data.append({"Type": "Error", "Message": error})
                    
                    if issues_data:
                        issues_df = pd.DataFrame(issues_data)
                        issues_df.to_excel(writer, sheet_name='Issues', index=False)
    
    def to_csv(self, file_path: Union[str, Path]) -> None:
        """Export MIUL data to CSV file"""
        file_path = Path(file_path)
        self.miul_data.to_csv(file_path, index=False)


class MaterialSpecification(BaseModel):
    """Material specification data"""
    material_code: str = Field(..., description="Unique material identifier")
    material_name: str = Field(..., description="Material common name")
    specification: Optional[str] = Field(None, description="Material specification reference")
    density: Optional[float] = Field(None, description="Material density")
    strength_properties: Optional[Dict[str, float]] = Field(None, description="Mechanical properties")
    environmental_ratings: Optional[Dict[str, Any]] = Field(None, description="Environmental compatibility")
    safety_classifications: Optional[Dict[str, str]] = Field(None, description="Safety/hazard classifications")
    nasa_6016_class: Optional[str] = Field(None, description="NASA-STD-6016 classification")
    source_document: Optional[str] = Field(None, description="Source specification document")
    
    @validator('material_code')
    def material_code_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Material code cannot be empty")
        return v.strip()
    
    @validator('nasa_6016_class')
    def nasa_class_valid(cls, v):
        if v and v not in ['A', 'B', 'C', 'D']:
            raise ValueError("NASA-STD-6016 class must be A, B, C, or D")
        return v


class MaterialDatabase(BaseModel):
    """Collection of material specifications"""
    materials: List[MaterialSpecification] = Field(..., description="List of material specs")
    database_version: Optional[str] = Field(None, description="Database version")
    last_updated: Optional[datetime] = Field(None, description="Last update timestamp")
    source_info: Optional[Dict[str, Any]] = Field(None, description="Database source information")
    
    @validator('materials')
    def materials_not_empty(cls, v):
        if not v:
            raise ValueError("Material database must contain at least one material")
        return v
    
    def get_material(self, material_code: str) -> Optional[MaterialSpecification]:
        """Get material specification by code"""
        for material in self.materials:
            if material.material_code == material_code:
                return material
        return None
    
    def search_materials(self, search_term: str) -> List[MaterialSpecification]:
        """Search materials by name or code"""
        results = []
        search_lower = search_term.lower()
        for material in self.materials:
            if (search_lower in material.material_code.lower() or 
                search_lower in material.material_name.lower()):
                results.append(material)
        return results
    
    @property
    def total_materials(self) -> int:
        """Total number of materials in database"""
        return len(self.materials)


class ProcessingConfig(BaseModel):
    """Configuration for MIUL processing"""
    enable_audit_trail: bool = Field(default=True, description="Enable detailed audit logging")
    strict_material_matching: bool = Field(default=True, description="Require exact material code matches")
    allow_missing_specifications: bool = Field(default=False, description="Allow materials without full specs")
    validation_level: str = Field(default="standard", description="Validation strictness level")
    output_format: str = Field(default="excel", description="Primary output format")
    include_metadata: bool = Field(default=True, description="Include processing metadata in output")
    nasa_swe_mode: bool = Field(default=True, description="Enable NASA Software Engineering compliance")
    
    @validator('validation_level')
    def validation_level_valid(cls, v):
        valid_levels = ['minimal', 'standard', 'strict', 'nasa_critical']
        if v not in valid_levels:
            raise ValueError(f"Validation level must be one of: {valid_levels}")
        return v
    
    @validator('output_format')
    def output_format_valid(cls, v):
        valid_formats = ['excel', 'csv', 'json', 'xml']
        if v not in valid_formats:
            raise ValueError(f"Output format must be one of: {valid_formats}")
        return v


# Example model instances for testing
def create_sample_bom() -> BOMDocument:
    """Create sample BOM for testing"""
    items = [
        BOMItem(
            part_number="P001",
            quantity=4.0,
            drawing_number="DWG-001",
            description="Hex Bolt M6x20",
            material_type="Fastener"
        ),
        BOMItem(
            part_number="P002", 
            quantity=8.0,
            drawing_number="DWG-002",
            description="Flat Washer M6",
            material_type="Fastener"
        ),
        BOMItem(
            part_number="P003",
            quantity=1.0,
            drawing_number="DWG-003", 
            description="Main Structure Panel",
            material_type="Structure"
        )
    ]
    
    return BOMDocument(
        items=items,
        document_id="BOM-001",
        version="Rev A",
        created_date=datetime.utcnow(),
        source_info={"type": "sample", "purpose": "testing"}
    )


def create_sample_material_db() -> MaterialDatabase:
    """Create sample material database for testing"""
    materials = [
        MaterialSpecification(
            material_code="SS316L",
            material_name="Stainless Steel 316L",
            specification="ASTM-A276-316L",
            density=8.0,
            nasa_6016_class="A",
            environmental_ratings={"FLAMM": 1, "SCC": 1, "CORR": 1, "TVS": 1}
        ),
        MaterialSpecification(
            material_code="AL6061",
            material_name="Aluminum 6061-T6",
            specification="ASTM-B221-6061",
            density=2.7,
            nasa_6016_class="A", 
            environmental_ratings={"FLAMM": 1, "SCC": 1, "CORR": 1, "TVS": 1}
        ),
        MaterialSpecification(
            material_code="TI6AL4V",
            material_name="Titanium 6Al-4V",
            specification="AMS-4928",
            density=4.43,
            nasa_6016_class="A",
            environmental_ratings={"FLAMM": 1, "SCC": 1, "CORR": 1, "TVS": 1}
        )
    ]
    
    return MaterialDatabase(
        materials=materials,
        database_version="1.0",
        last_updated=datetime.utcnow(),
        source_info={"type": "sample", "purpose": "testing"}
    )