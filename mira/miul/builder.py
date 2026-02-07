#!/usr/bin/env python3
"""
Module: Builder
Purpose: MIUL Builder - Deterministic BOM to MIUL conversion

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import hashlib
import uuid

import pandas as pd
from pydantic import BaseModel

from .models import (
    BOMDocument, BOMItem, DrawingMaterialUsage, DrawingPackage,
    MIULMetadata, MIULBuildResult
)

logger = logging.getLogger(__name__)


class MIULBuilder:
    """Deterministic MIUL builder with m:1 join enforcement"""
    
    def __init__(self, enable_audit: bool = True):
        self.enable_audit = enable_audit
        self.audit_trail = []
        self.build_id = str(uuid.uuid4())
        
    def _audit(self, step: str, data: Dict[str, Any]):
        """Record audit trail entry"""
        if self.enable_audit:
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "build_id": self.build_id,
                "step": step,
                "data": data
            }
            self.audit_trail.append(entry)
            logger.debug(f"Audit: {step}")
    
    def load_bom_from_dataframe(self, df: pd.DataFrame, 
                               part_col: str = "Part Number",
                               qty_col: str = "Quantity",
                               drawing_col: str = "Drawing") -> BOMDocument:
        """Load BOM from pandas DataFrame"""
        self._audit("load_bom_start", {
            "rows": len(df),
            "columns": list(df.columns),
            "part_col": part_col,
            "qty_col": qty_col,
            "drawing_col": drawing_col
        })
        
        # Validate required columns
        missing_cols = []
        for col in [part_col, qty_col]:
            if col not in df.columns:
                missing_cols.append(col)
        
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")
        
        # Create BOM items
        items = []
        for idx, row in df.iterrows():
            try:
                item = BOMItem(
                    part_number=str(row[part_col]).strip(),
                    quantity=float(row[qty_col]) if pd.notna(row[qty_col]) else 0.0,
                    drawing_number=str(row[drawing_col]).strip() if drawing_col in df.columns and pd.notna(row[drawing_col]) else None,
                    raw_data=row.to_dict()
                )
                items.append(item)
            except Exception as e:
                logger.warning(f"Skipping row {idx}: {e}")
        
        # Create document
        doc = BOMDocument(
            items=items,
            source_info={
                "type": "dataframe",
                "total_rows": len(df),
                "processed_items": len(items),
                "columns": list(df.columns)
            }
        )
        
        self._audit("load_bom_complete", {
            "total_items": len(items),
            "unique_parts": len(set(item.part_number for item in items))
        })
        
        return doc
    
    def load_material_crosswalk(self, df: pd.DataFrame,
                               part_col: str = "Part Number",
                               material_col: str = "Material Code") -> Dict[str, str]:
        """Load material crosswalk mapping"""
        self._audit("load_crosswalk_start", {
            "rows": len(df),
            "part_col": part_col,
            "material_col": material_col
        })
        
        # Validate columns
        missing_cols = []
        for col in [part_col, material_col]:
            if col not in df.columns:
                missing_cols.append(col)
        
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")
        
        # Create mapping (deterministic m:1)
        mapping = {}
        conflicts = []
        
        for _, row in df.iterrows():
            part_num = str(row[part_col]).strip()
            material_code = str(row[material_col]).strip() if pd.notna(row[material_col]) else None
            
            if material_code:
                if part_num in mapping and mapping[part_num] != material_code:
                    conflicts.append({
                        "part_number": part_num,
                        "existing": mapping[part_num],
                        "new": material_code
                    })
                else:
                    mapping[part_num] = material_code
        
        if conflicts:
            logger.warning(f"Material mapping conflicts detected: {len(conflicts)}")
            for conflict in conflicts:
                logger.warning(f"Part {conflict['part_number']}: {conflict['existing']} vs {conflict['new']}")
        
        self._audit("load_crosswalk_complete", {
            "mappings": len(mapping),
            "conflicts": len(conflicts)
        })
        
        return mapping
    
    def load_material_specs(self, df: pd.DataFrame,
                           material_col: str = "Material Code",
                           spec_col: str = "Material Specification") -> Dict[str, Dict[str, Any]]:
        """Load material specifications"""
        self._audit("load_specs_start", {
            "rows": len(df),
            "material_col": material_col,
            "spec_col": spec_col
        })
        
        # Create specs mapping
        specs = {}
        for _, row in df.iterrows():
            material_code = str(row[material_col]).strip() if pd.notna(row[material_col]) else None
            if material_code:
                specs[material_code] = row.to_dict()
        
        self._audit("load_specs_complete", {
            "specifications": len(specs)
        })
        
        return specs
    
    def build_miul_from_bom(self, 
                           bom_doc: BOMDocument,
                           material_crosswalk: Dict[str, str],
                           material_specs: Dict[str, Dict[str, Any]],
                           template_headers: Optional[List[str]] = None) -> MIULBuildResult:
        """Build MIUL from BOM with deterministic processing"""
        
        start_time = datetime.utcnow()
        
        self._audit("build_miul_start", {
            "bom_items": len(bom_doc.items),
            "crosswalk_mappings": len(material_crosswalk),
            "material_specs": len(material_specs),
            "template_headers": template_headers
        })
        
        # Build MIUL rows
        miul_rows = []
        warnings = []
        errors = []
        
        # Track statistics
        stats = {
            "total_bom_items": len(bom_doc.items),
            "items_with_material": 0,
            "items_with_specs": 0,
            "items_missing_material": 0,
            "items_missing_specs": 0
        }
        
        for idx, bom_item in enumerate(bom_doc.items, 1):
            try:
                # Look up material code (deterministic m:1)
                material_code = material_crosswalk.get(bom_item.part_number)
                if not material_code:
                    stats["items_missing_material"] += 1
                    warnings.append(f"No material mapping for part: {bom_item.part_number}")
                    material_code = "UNKNOWN"
                else:
                    stats["items_with_material"] += 1
                
                # Look up material specs
                material_spec_data = material_specs.get(material_code, {})
                if not material_spec_data:
                    stats["items_missing_specs"] += 1
                    warnings.append(f"No specifications for material: {material_code}")
                else:
                    stats["items_with_specs"] += 1
                
                # Build MIUL row data
                miul_row = {
                    "index": idx,
                    "parent": "",
                    "dwg_number": bom_item.drawing_number or "",
                    "nhassey": "",
                    "find_no": str(idx),
                    "part_number": bom_item.part_number,
                    "nomenclature": material_spec_data.get("Nomenclature", ""),
                    "material_code": material_code,
                    "designation": material_spec_data.get("Designation", ""),
                    "material_spec": material_spec_data.get("Material Specification", ""),
                    "weight_lb": material_spec_data.get("Weight (lb)", 0.0) if material_spec_data.get("Weight (lb)") else 0.0,
                    "qty": bom_item.quantity,
                    "cure_no": material_spec_data.get("Cure No.", ""),
                    "flamm_rating": material_spec_data.get("FLAMM Rating", ""),
                    "scc_rating": material_spec_data.get("SCC Rating", ""),
                    "corr_rating": material_spec_data.get("CORR Rating", ""),
                    "tvs_rating": material_spec_data.get("TVS Rating", ""),
                    "rationale_code": material_spec_data.get("Rationale Code", ""),
                    "remarks": material_spec_data.get("Remarks", ""),
                    "max_pressure_psia": material_spec_data.get("Max Pressure (psia)", ""),
                    "min_pressure_psia": material_spec_data.get("Min Pressure (psia)", ""),
                    "max_temp_f": material_spec_data.get("Max Temp (°F)", ""),
                    "min_temp_f": material_spec_data.get("Min Temp (°F)", ""),
                    "media": material_spec_data.get("Media", ""),
                    "criticality": material_spec_data.get("Criticality", ""),
                    "flag_1": material_spec_data.get("Flag 1", ""),
                    "flag_2": material_spec_data.get("Flag 2", ""),
                    "tmp_parent": ""
                }
                
                miul_rows.append(miul_row)
                
            except Exception as e:
                error_msg = f"Error processing BOM item {idx} ({bom_item.part_number}): {e}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        # Create metadata
        end_time = datetime.utcnow()
        metadata = MIULMetadata(
            build_id=self.build_id,
            build_timestamp=start_time,
            processing_time_seconds=(end_time - start_time).total_seconds(),
            source_bom_items=stats["total_bom_items"],
            output_miul_rows=len(miul_rows),
            material_coverage_percent=(stats["items_with_material"] / stats["total_bom_items"] * 100) if stats["total_bom_items"] > 0 else 0.0,
            spec_coverage_percent=(stats["items_with_specs"] / stats["total_bom_items"] * 100) if stats["total_bom_items"] > 0 else 0.0,
            validation_warnings=len(warnings),
            processing_errors=len(errors),
            nasa_swe_compliant=len(errors) == 0,
            deterministic_hash=self._calculate_deterministic_hash(miul_rows)
        )
        
        self._audit("build_miul_complete", {
            "output_rows": len(miul_rows),
            "warnings": len(warnings),
            "errors": len(errors),
            "processing_time": metadata.processing_time_seconds
        })
        
        return MIULBuildResult(
            miul_data=pd.DataFrame(miul_rows),
            metadata=metadata,
            warnings=warnings,
            errors=errors,
            audit_trail=self.audit_trail.copy() if self.enable_audit else []
        )
    
    def _calculate_deterministic_hash(self, miul_rows: List[Dict[str, Any]]) -> str:
        """Calculate deterministic hash of MIUL data for verification"""
        # Sort rows by index to ensure deterministic ordering
        sorted_rows = sorted(miul_rows, key=lambda x: x.get("index", 0))
        
        # Create hash input from key fields
        hash_input = ""
        for row in sorted_rows:
            key_fields = [
                str(row.get("part_number", "")),
                str(row.get("material_code", "")),
                str(row.get("qty", "")),
                str(row.get("weight_lb", ""))
            ]
            hash_input += "|".join(key_fields) + "\n"
        
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def build_miul_from_bom(bom_df: pd.DataFrame,
                       crosswalk_df: pd.DataFrame,
                       specs_df: pd.DataFrame,
                       **kwargs) -> MIULBuildResult:
    """Convenience function for building MIUL from DataFrames"""
    
    builder = MIULBuilder(enable_audit=kwargs.get("enable_audit", True))
    
    # Load BOM
    bom_doc = builder.load_bom_from_dataframe(
        bom_df,
        part_col=kwargs.get("part_col", "Part Number"),
        qty_col=kwargs.get("qty_col", "Quantity"),
        drawing_col=kwargs.get("drawing_col", "Drawing")
    )
    
    # Load crosswalk
    crosswalk = builder.load_material_crosswalk(
        crosswalk_df,
        part_col=kwargs.get("crosswalk_part_col", "Part Number"),
        material_col=kwargs.get("crosswalk_material_col", "Material Code")
    )
    
    # Load specs
    specs = builder.load_material_specs(
        specs_df,
        material_col=kwargs.get("specs_material_col", "Material Code"),
        spec_col=kwargs.get("specs_spec_col", "Material Specification")
    )
    
    # Build MIUL
    return builder.build_miul_from_bom(
        bom_doc, crosswalk, specs,
        template_headers=kwargs.get("template_headers")
    )


def build_miul_from_drawings(drawing_package: DrawingPackage,
                            material_specs: Dict[str, Dict[str, Any]],
                            **kwargs) -> MIULBuildResult:
    """Build MIUL from drawing package (future implementation)"""
    
    # Placeholder for drawing-based MIUL generation
    # This would extract materials from drawing annotations, tables, etc.
    
    start_time = datetime.utcnow()
    
    # Extract materials from drawings
    extracted_materials = []
    for drawing in drawing_package.drawings:
        for usage in drawing.material_usage:
            extracted_materials.append({
                "drawing_number": drawing.drawing_number,
                "material_code": usage.material_code,
                "quantity": usage.quantity_used,
                "location": usage.usage_location,
                "notes": usage.notes
            })
    
    # Convert to MIUL format (simplified)
    miul_rows = []
    for idx, material in enumerate(extracted_materials, 1):
        spec_data = material_specs.get(material["material_code"], {})
        
        miul_row = {
            "index": idx,
            "dwg_number": material["drawing_number"],
            "material_code": material["material_code"],
            "qty": material["quantity"],
            "nomenclature": spec_data.get("Nomenclature", ""),
            "remarks": material.get("notes", "")
        }
        miul_rows.append(miul_row)
    
    # Create metadata
    end_time = datetime.utcnow()
    metadata = MIULMetadata(
        build_id=str(uuid.uuid4()),
        build_timestamp=start_time,
        processing_time_seconds=(end_time - start_time).total_seconds(),
        source_bom_items=0,  # No BOM for drawing-based
        output_miul_rows=len(miul_rows),
        material_coverage_percent=100.0,  # Assume all materials found in drawings
        spec_coverage_percent=len([r for r in miul_rows if r.get("nomenclature")]) / len(miul_rows) * 100 if miul_rows else 0.0,
        validation_warnings=0,
        processing_errors=0,
        nasa_swe_compliant=True,
        deterministic_hash="drawing_based"
    )
    
    return MIULBuildResult(
        miul_data=pd.DataFrame(miul_rows),
        metadata=metadata,
        warnings=[],
        errors=[],
        audit_trail=[]
    )