#!/usr/bin/env python3
"""
Module: Service
Purpose: MIUL Service Layer - Clean Wrapper Entrypoint

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.models.answer import EvidenceItem

from .api_models import MiulBuildRequest, MiulBuildResponse, MiulEntry
from .models import BOMDocument, BOMItem

LOGGER = logging.getLogger(__name__)


def _get_material_details(material_code: str) -> Optional[Dict[str, str]]:
    """Look up material designation and details from MAPTIS by material code.

    Args:
        material_code: MAPTIS material code (e.g., "20494")

    Returns:
        Dict with 'designation' and 'composition' if found, None otherwise.
    """
    if not material_code:
        return None

    try:
        import psycopg2
        from psycopg2.extras import DictCursor
    except ImportError:
        LOGGER.warning("[MIUL Service] psycopg2 not available - using placeholder material name")
        return None

    # Get database connection params
    try:
        from mira.core.db_config import get_db_connection_params
        conn_params = get_db_connection_params()
    except ImportError:
        conn_params = {
            "host": os.environ.get("POSTGRES_HOST", "localhost"),
            "port": int(os.environ.get("POSTGRES_PORT", "5432")),
            "database": os.environ.get("POSTGRES_DB", "mira"),
            "user": os.environ.get("POSTGRES_USER", "postgres"),
            "password": os.environ.get("POSTGRES_PASSWORD", "postgres"),
        }

    try:
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor(cursor_factory=DictCursor)

        cursor.execute(
            """
            SELECT designation, composition
            FROM materials
            WHERE material_code = %s
            LIMIT 1
            """,
            (str(material_code).strip(),)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            return {
                "designation": row["designation"] or "",
                "composition": row["composition"] or "",
            }
    except Exception as e:
        LOGGER.warning(f"[MIUL Service] Material lookup failed for {material_code}: {e}")

    return None


def build_miul(request: MiulBuildRequest) -> MiulBuildResponse:
    """Build a MIUL from the provided BOM items.

    This is the CLEAN wrapper that:
    1. Validates request
    2. Delegates to internal MIULBuilder
    3. Returns structured response with evidence

    Args:
        request: MiulBuildRequest with program_name, bom_items, etc.

    Returns:
        MiulBuildResponse with entries, coverage, and evidence
    """
    build_id = str(uuid.uuid4())
    build_timestamp = datetime.utcnow()
    warnings: List[str] = []
    errors: List[str] = []
    evidence: List[EvidenceItem] = []
    audit_trail: List[Dict[str, Any]] = []

    # Evidence: Record the build request
    evidence.append(EvidenceItem(
        source_id="miul_build_request",
        location=f"build_id={build_id}",
        summary=f"MIUL build for {request.program_name} with {len(request.bom_items)} BOM items",
    ))

    try:
        # Convert request items to internal BOM format
        bom_items: List[BOMItem] = []
        for idx, item_dict in enumerate(request.bom_items):
            try:
                part_number = str(item_dict.get("part_number", "")).strip()
                if not part_number:
                    warnings.append(f"Row {idx}: Missing part_number, skipped")
                    continue

                bom_item = BOMItem(
                    part_number=part_number,
                    quantity=float(item_dict.get("quantity", 1.0)),
                    drawing_number=item_dict.get("drawing_number"),
                    description=item_dict.get("description"),
                    material_type=item_dict.get("material_type"),
                    raw_data=item_dict,
                )
                bom_items.append(bom_item)

                if request.include_audit_trail:
                    audit_trail.append({
                        "step": "parse_bom_item",
                        "index": idx,
                        "part_number": part_number,
                        "status": "ok",
                    })

            except Exception as e:
                warnings.append(f"Row {idx}: Parse error - {e}")
                if request.include_audit_trail:
                    audit_trail.append({
                        "step": "parse_bom_item",
                        "index": idx,
                        "status": "error",
                        "error": str(e),
                    })

        if not bom_items:
            errors.append("No valid BOM items parsed")
            return MiulBuildResponse(
                success=False,
                program_name=request.program_name,
                build_id=build_id,
                build_timestamp=build_timestamp,
                entries=[],
                total_entries=0,
                material_coverage_percent=0.0,
                warnings=warnings,
                errors=errors,
                evidence=evidence,
                audit_trail=audit_trail if request.include_audit_trail else None,
            )

        # Create BOM document
        bom_doc = BOMDocument(
            items=bom_items,
            document_id=f"BOM-{build_id[:8]}",
            source_info={"program": request.program_name, "build_id": build_id},
        )

        # Build MIUL entries
        miul_entries: List[MiulEntry] = []
        materials_resolved = 0

        for line_num, bom_item in enumerate(bom_items, start=1):
            # Look up material mapping
            material_code = None
            material_name = None
            specification = None
            entry_warnings: List[str] = []

            if request.material_mappings:
                material_code = request.material_mappings.get(bom_item.part_number)
                if material_code:
                    materials_resolved += 1
                    # Look up material details from MAPTIS
                    material_details = _get_material_details(material_code)
                    if material_details:
                        material_name = material_details.get("designation") or f"Material {material_code}"
                        specification = material_details.get("composition") or specification
                    else:
                        material_name = f"Material {material_code}"
                elif request.strict_mode:
                    entry_warnings.append("No material mapping found")

            miul_entry = MiulEntry(
                line_number=line_num,
                part_number=bom_item.part_number,
                material_code=material_code,
                material_name=material_name,
                quantity=bom_item.quantity,
                specification=specification,
                drawing_number=bom_item.drawing_number,
                usage_notes=bom_item.description,
                warnings=entry_warnings,
            )
            miul_entries.append(miul_entry)

        # Calculate coverage
        coverage = (materials_resolved / len(bom_items) * 100) if bom_items else 0.0

        # Add build completion evidence
        evidence.append(EvidenceItem(
            source_id="miul_build_result",
            location=f"build_id={build_id}",
            summary=f"Generated {len(miul_entries)} MIUL entries, {coverage:.1f}% material coverage",
        ))

        return MiulBuildResponse(
            success=len(errors) == 0,
            program_name=request.program_name,
            build_id=build_id,
            build_timestamp=build_timestamp,
            entries=miul_entries,
            total_entries=len(miul_entries),
            material_coverage_percent=coverage,
            warnings=warnings,
            errors=errors,
            evidence=evidence,
            audit_trail=audit_trail if request.include_audit_trail else None,
        )

    except Exception as e:
        LOGGER.exception(f"MIUL build failed: {e}")
        errors.append(f"Build failed: {e}")
        return MiulBuildResponse(
            success=False,
            program_name=request.program_name,
            build_id=build_id,
            build_timestamp=build_timestamp,
            entries=[],
            total_entries=0,
            material_coverage_percent=0.0,
            warnings=warnings,
            errors=errors,
            evidence=evidence,
            audit_trail=audit_trail if request.include_audit_trail else None,
        )


__all__ = ["build_miul"]
