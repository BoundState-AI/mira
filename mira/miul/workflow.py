#!/usr/bin/env python3
"""
Module: Workflow
Purpose: MIUL Workflow Orchestrator.

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

import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from mira.miul.v1_archive.extractors import ExtractorService, get_extractor_service
from mira.miul.v1_archive.extractors.haiku_drawing_extractor import HaikuDrawingExtractor
from mira.miul.enrichment import MIULEnrichmentService, get_enrichment_service
from mira.miul.maptis_ratings import get_ratings_bulk, RATING_COLUMNS as MAPTIS_RATING_COLUMNS
from mira.miul.aggregated_ratings import get_aggregated_ratings, AggregatedRatingsClient
from mira.miul.interfaces import SafetyCriticalError
from mira.miul.v1_archive.tree_builder import MIULTreeBuilder, is_noise_part

# Import material code lookup service from local boundstate module
import uuid

try:
    from mira.miul.material_code_lookup import (
        MaterialCodeLookupService,
        MaterialMatch,
        get_lookup_service,
    )
    MATERIAL_LOOKUP_AVAILABLE = True
except ImportError:
    MATERIAL_LOOKUP_AVAILABLE = False
    MaterialCodeLookupService = None
    MaterialMatch = None
    get_lookup_service = None

# Import material form inference
from mira.miul.material_form_inference import infer_material_form

# Import MUA remarks generator for populating rationale
from mira.miul.mua_remarks_generator import populate_miul_remarks, generate_remark

# Audit logger for material code lookup decisions
AUDIT_LOGGER = logging.getLogger("miul.material_audit")

LOGGER = logging.getLogger(__name__)

# JSC 27301F Section 4.2.1 MIUL columns (38 total)
MIUL_COLUMNS = [
    # MAPTIS Tree Structure
    "Index",
    "Parent",
    # JSC 27301F 4.2.1 Fields
    "Detail Drawing",           # (1)
    "Next Assembly",            # (2)
    "Change Letter",            # (3)
    "Drawing Source",           # (4)
    "Material Form",            # (5)
    "Material Manufacturer",    # (6)
    "Designation",              # (7) Material designation/alloy name
    "Material Specification",   # (8)
    "Process Specification",    # (9)
    "Environment",              # (10)
    "Material Code",            # (12)
    "Standard Part Number",     # (13)
    "Contractor",               # (14)
    "System",                   # (15)
    "Subsystem",                # (16)
    "Max Temperature",          # (17)
    "Min Temperature",          # (18)
    "Fluid Type",               # (19)
    "Associate Contractor",     # (21)
    "Project",                  # (22)
    "Document Title",           # (23)
    "Criticality",              # (24)
    "Line Number",              # (25)
    "Overall Evaluation",       # (26)
    "Configuration Test",       # (27)
    "Max Pressure",             # (28)
    "Min Pressure",             # (29)
    "MUA Rationale",            # (30)
    "Cure Codes",               # (31)
    # (32) Ratings - expanded per MAPTIS practice
    "FLAM",
    "SCC",
    "CORR",
    "TVS",
    "TOX",
    "FS",
    "Remarks",                  # (33)
]

# Rating columns for gap detection
RATING_COLUMNS = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]

# Ratings that indicate a gap (need rationale)
GAP_VALUES = {"", None, "U", "I", "X", "N"}

# Material code placeholders that should be treated as missing values.
# Normalization removes whitespace and uppercases before comparison.
MATERIAL_CODE_PLACEHOLDERS = {
    "N/A",
    "NA",
    "NONE",
    "NONEASSIGNED",
    "NULL",
    "NAN",
    "<NA>",
    "UNASSIGNED",
    "UNKNOWN",
}


class MIULWorkflow:
    """Orchestrates the complete MIUL generation pipeline.

    Implements Single Responsibility by delegating to specialized services:
    - ExtractorService for PDF extraction
    - EnrichmentService for material code lookup and ratings
    - Transformer logic for format conversion

    Implements Dependency Inversion by accepting interfaces, not concrete classes.
    """

    def __init__(
        self,
        extractor_service: Optional[ExtractorService] = None,
        enrichment_service: Optional[MIULEnrichmentService] = None,
        tree_builder: Optional[MIULTreeBuilder] = None,
    ):
        """Initialize workflow with optional service injection.

        Args:
            extractor_service: BOM extraction service (uses default if None)
            enrichment_service: MAPTIS enrichment service (uses default if None)
            tree_builder: Tree structure builder (uses default if None)
        """
        self._extractor = extractor_service or get_extractor_service()
        self._enrichment = enrichment_service or get_enrichment_service()
        self._tree_builder = tree_builder or MIULTreeBuilder()

    @staticmethod
    def _normalize_material_code(value: Any) -> str:
        """Normalize a Material Code cell value to a comparable string."""
        if value is None:
            return ""
        if pd.isna(value):
            return ""
        return str(value).strip()

    @classmethod
    def is_usable_material_code(cls, value: Any) -> bool:
        """True when value is a meaningful material code (not blank/placeholder)."""
        code = cls._normalize_material_code(value)
        if not code:
            return False

        normalized = code.upper().replace(" ", "")
        if normalized in MATERIAL_CODE_PLACEHOLDERS:
            return False

        # Common spreadsheet placeholders like "-", "--", "-----", "____".
        if normalized and all(ch in "-_.~" for ch in normalized):
            return False

        return True

    async def extract_from_pdfs(self, pdf_paths: List[Path]) -> pd.DataFrame:
        """Step 1: Extract parts from PDFs and transform to MIUL format.

        Uses DT-first strategy when Drawing Tree file is available:
        1. Parse -DT file as master parts list with hierarchy
        2. Extract materials from DETAIL drawings
        3. Merge material data into DT parts
        4. Build proper Index/Parent tree structure

        Falls back to flat extraction if no DT file found.

        Args:
            pdf_paths: List of PDF file paths

        Returns:
            MIUL DataFrame with extracted parts and tree structure

        Raises:
            SafetyCriticalError: If extraction fails completely
        """
        LOGGER.info(f"[Workflow] Step 1: Extracting parts from {len(pdf_paths)} PDF(s)")

        # Determine directory from first PDF path
        if pdf_paths:
            directory = pdf_paths[0].parent
        else:
            raise SafetyCriticalError("No PDF paths provided for extraction")

        # Try DT-first extraction strategy
        dt_path = self._tree_builder.find_drawing_tree(directory)

        if dt_path:
            LOGGER.info(f"[Workflow] Found Drawing Tree: {dt_path.name}")

            # Step 1a: Parse DT as master parts list
            dt_data = self._tree_builder.parse_drawing_tree(dt_path)
            dt_parts = dt_data.get("parts", [])
            LOGGER.info(f"[Workflow] DT contains {len(dt_parts)} parts")

            # Step 1b: Extract materials from detail drawings
            detail_paths = [p for p in pdf_paths if p != dt_path]
            material_data, nha_map = await self._extract_materials_from_details(detail_paths)
            LOGGER.info(
                f"[Workflow] Extracted materials from {len(detail_paths)} detail drawings, "
                f"NHA map has {len(nha_map)} entries"
            )

            # Step 1c: Merge material data into DT parts
            merged_parts = self._tree_builder.merge_material_data(dt_parts, material_data)

            # Step 1d: Build tree structure using NHA relationships
            tree_parts = self._tree_builder.build_tree(merged_parts, nha_map)

            # Filter noise parts
            tree_parts = [p for p in tree_parts if not is_noise_part(p)]

            # Transform to MIUL format
            miul_df = self._transform_parts_to_miul(tree_parts)
            LOGGER.info(f"[Workflow] DT-first extraction: {len(miul_df)} parts with tree structure")

        else:
            LOGGER.info("[Workflow] No Drawing Tree found, using flat extraction")

            # Fallback: Extract directly from all PDFs
            parts = await self._extractor.extract(pdf_paths, require_extraction=True)

            # Filter noise parts
            parts = [p for p in parts if not is_noise_part(p)]

            # Transform to MIUL format
            miul_df = self._transform_parts_to_miul(parts)
            LOGGER.info(f"[Workflow] Flat extraction: {len(miul_df)} parts")

        return miul_df

    async def _extract_materials_from_details(
        self, detail_paths: List[Path]
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        """Extract material data and NHA from detail drawings.

        Uses HaikuDrawingExtractor (Bedrock Sonnet 4.5 vision) to extract
        primary materials from title blocks and embedded hardware.

        Args:
            detail_paths: List of detail drawing PDF paths

        Returns:
            Tuple of:
            - material_data: {drawing_number: {designation, material_spec, ...}}
            - nha_map: {drawing_number: next_higher_assembly}
        """
        material_data: Dict[str, Dict[str, Any]] = {}
        nha_map: Dict[str, str] = {}

        if not detail_paths:
            return material_data, nha_map

        # Use HaikuDrawingExtractor for vision-based extraction from drawings
        drawing_extractor = HaikuDrawingExtractor()

        for pdf_path in detail_paths:
            try:
                LOGGER.info(f"[Workflow] Extracting materials from: {pdf_path.name}")
                result = drawing_extractor.extract_from_pdf(pdf_path)

                drawing_number = result.drawing_number
                if not drawing_number or drawing_number == "UNKNOWN":
                    # Try to get from filename
                    drawing_number = pdf_path.stem.split(".")[0].split("_")[0]

                # Store primary material data
                if result.primary_material:
                    material_data[drawing_number] = {
                        "designation": result.primary_material.designation or "",
                        "material_spec": result.primary_material.specification or "",
                        "material_form": "",
                        "description": result.title or "",
                        "source_file": pdf_path.name,
                    }
                    LOGGER.info(
                        f"  Found material: {result.primary_material.designation} "
                        f"({result.primary_material.specification})"
                    )

                # Also add embedded hardware materials
                for hw in result.embedded_hardware:
                    if hw.inferred_material:
                        hw_key = f"{drawing_number}_{hw.standard}"
                        material_data[hw_key] = {
                            "designation": hw.inferred_material,
                            "material_spec": hw.inferred_spec or "",
                            "material_form": "INSERT",
                            "description": f"{hw.standard} insert",
                            "source_file": pdf_path.name,
                        }

            except Exception as e:
                LOGGER.warning(f"[Workflow] Failed to extract from {pdf_path.name}: {e}")

        return material_data, nha_map

    async def _extract_drawing_nhas(
        self, detail_paths: List[Path], nha_map: Dict[str, str]
    ) -> None:
        """Extract each drawing's own NHA from its title block.

        For assembly drawings like MER07570-001, the drawing itself has an NHA
        (MER07540-001) but may have no parts list. This captures those relationships.

        NOTE: NHA relationships should primarily come from the Drawing Tree (DT) file,
        which is the authoritative source per MSFC drawing practices. This method is
        a fallback for cases where DT is not available.

        Args:
            detail_paths: List of PDF paths
            nha_map: NHA map to populate (modified in place)
        """
        # The new vision-based HaikuBOMExtractor uses base64 images, not text.
        # NHA extraction from individual drawings is expensive and less reliable
        # than using the Drawing Tree. Skip this method - rely on DT parsing.
        #
        # If DT is not available, the tree_builder will create a flat structure
        # and materials can still be extracted from detail drawings.
        LOGGER.debug(
            "[Workflow] NHA extraction from individual drawings skipped - use Drawing Tree instead"
        )

    def lookup_material_codes(
        self, miul_df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, int, List[Dict[str, Any]]]:
        """Step 2: Lookup Material Code from Manufacturer Designation.

        Uses MaterialCodeLookupService for UNS-based deterministic matching
        with family-filtered partial match. Quarantines ambiguous/low-confidence
        matches for human review.

        Args:
            miul_df: MIUL DataFrame with Manufacturer Designation column

        Returns:
            Tuple of (updated DataFrame, count of codes found, quarantine list)

        Quarantine list entries contain:
            - row_idx: DataFrame index
            - designation: Original designation string
            - candidates: List of candidate MaterialMatch objects
            - method: How the match was attempted
            - score: Confidence score
        """
        LOGGER.info("[Workflow] Step 2: Looking up material codes from designations")

        codes_found = 0
        quarantine: List[Dict[str, Any]] = []

        # Use MaterialCodeLookupService for authoritative lookup
        if MATERIAL_LOOKUP_AVAILABLE and get_lookup_service:
            lookup_service = get_lookup_service()
            try:
                for idx, row in miul_df.iterrows():
                    material_code = row.get("Material Code")
                    normalized_existing = self._normalize_material_code(material_code)
                    if normalized_existing and not self.is_usable_material_code(material_code):
                        # Normalize placeholders like "-----" to truly blank values.
                        miul_df.at[idx, "Material Code"] = None
                        material_code = None

                    # Skip if already has a material code
                    if self.is_usable_material_code(material_code):
                        continue

                    # Try to look up from designation
                    designation = row.get("Designation", "")
                    if not pd.notna(designation) or not str(designation).strip():
                        continue

                    designation_str = str(designation).strip()

                    # Pass form context for AI-powered selection
                    part_description = str(row.get("Document Title", "")).strip()
                    material_form = str(row.get("Material Form", "")).strip()

                    match = lookup_service.lookup_material_code(
                        designation_str,
                        part_description=part_description,
                        material_form=material_form,
                    )

                    # CRITICAL: Only apply if material_code is not None
                    if match.material_code is None:
                        # Quarantine - ambiguous or unresolved
                        quarantine.append({
                            "row_idx": idx,
                            "designation": designation_str,
                            "candidates": [
                                {
                                    "material_code": c.material_code,
                                    "designation": c.designation,
                                    "score": c.score,
                                }
                                for c in (match.candidates or [])
                            ],
                            "method": match.method,
                            "score": match.score,
                        })
                        self._log_audit(designation_str, match, "quarantined")
                    elif match.score >= 0.7:
                        # High confidence - auto-apply
                        miul_df.at[idx, "Material Code"] = match.material_code
                        codes_found += 1
                        self._log_audit(designation_str, match, "auto_applied")
                        LOGGER.debug(
                            f"[high] '{designation_str}' -> {match.material_code} "
                            f"(method={match.method}, score={match.score:.2f})"
                        )
                    elif match.score >= 0.5:
                        # Medium confidence - apply with warning
                        miul_df.at[idx, "Material Code"] = match.material_code
                        codes_found += 1
                        self._log_audit(designation_str, match, "applied_with_warning")
                        LOGGER.warning(
                            f"[medium] '{designation_str}' -> {match.material_code} "
                            f"(method={match.method}, score={match.score:.2f})"
                        )
                    else:
                        # Low score with code (shouldn't happen, but quarantine)
                        quarantine.append({
                            "row_idx": idx,
                            "designation": designation_str,
                            "candidates": [{
                                "material_code": match.material_code,
                                "designation": match.designation,
                                "score": match.score,
                            }],
                            "method": match.method,
                            "score": match.score,
                        })
                        self._log_audit(designation_str, match, "quarantined_low_score")

            except Exception as e:
                LOGGER.error(f"[Workflow] Error in material code lookup: {e}")
        else:
            # Fallback to enrichment service (legacy path)
            LOGGER.warning("[Workflow] MaterialCodeLookupService not available, using fallback")
            for idx, row in miul_df.iterrows():
                material_code = row.get("Material Code")
                normalized_existing = self._normalize_material_code(material_code)
                if normalized_existing and not self.is_usable_material_code(material_code):
                    # Normalize placeholders like "-----" to truly blank values.
                    miul_df.at[idx, "Material Code"] = None
                    material_code = None

                # Skip if already has a material code
                if self.is_usable_material_code(material_code):
                    continue

                # Try to look up from designation
                designation = row.get("Designation", "")
                if pd.notna(designation) and str(designation).strip():
                    found_code = self._enrichment.find_material_code_by_designation(
                        str(designation).strip()
                    )
                    if found_code:
                        miul_df.at[idx, "Material Code"] = found_code
                        codes_found += 1

        LOGGER.info(
            f"[Workflow] Found {codes_found} material codes, "
            f"{len(quarantine)} quarantined for review"
        )
        return miul_df, codes_found, quarantine

    def _log_audit(
        self, designation: str, match: "MaterialMatch", action: str
    ) -> None:
        """Log material lookup decision for audit trail."""
        import json
        from datetime import datetime

        audit_record = {
            "event": "material_code_lookup",
            "designation": designation,
            "lookup_stage": match.method,
            "candidates": [
                {"code": c.material_code, "designation": c.designation}
                for c in (match.candidates or [])
            ],
            "selected_code": match.material_code,
            "confidence": match.confidence,
            "score": match.score,
            "action": action,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        AUDIT_LOGGER.info(json.dumps(audit_record))

    def fetch_ratings(self, miul_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Step 3: Fetch ratings using Material Code.

        Uses thin maptis_ratings module for PostgreSQL lookup.
        Material codes must already be resolved (step 2).

        Args:
            miul_df: MIUL DataFrame with Material Code column

        Returns:
            Tuple of (enriched DataFrame, stats dict)
        """
        LOGGER.info("[Workflow] Step 3: Fetching ratings from MAPTIS")

        # Ensure rating columns exist
        for col in RATING_COLUMNS:
            if col not in miul_df.columns:
                miul_df[col] = ""

        # Collect material codes that need rating lookup
        codes_to_lookup: List[str] = []
        code_to_indices: Dict[str, List[int]] = {}

        for idx, row in miul_df.iterrows():
            material_code = row.get("Material Code")
            if self.is_usable_material_code(material_code):
                code = self._normalize_material_code(material_code)
                codes_to_lookup.append(code)
                if code not in code_to_indices:
                    code_to_indices[code] = []
                code_to_indices[code].append(idx)

        if not codes_to_lookup:
            LOGGER.warning("[Workflow] No Material Codes to look up ratings for")
            return miul_df, {
                "total_materials": 0,
                "enriched_count": 0,
                "coverage_pct": 0.0,
            }

        # Bulk fetch ratings using thin module
        unique_codes = list(set(codes_to_lookup))
        all_ratings = get_ratings_bulk(unique_codes)

        # Apply ratings to DataFrame
        enriched_count = 0
        total_ratings_added = 0

        for code, ratings in all_ratings.items():
            if not ratings:
                continue

            indices = code_to_indices.get(code, [])
            for idx in indices:
                for rating_col, rating_val in ratings.items():
                    if rating_col in RATING_COLUMNS:
                        miul_df.at[idx, rating_col] = rating_val
                        total_ratings_added += 1
                enriched_count += 1

        # Dedupe enriched_count (count unique rows, not all indices)
        enriched_codes = len([c for c in all_ratings if all_ratings[c]])

        stats = {
            "total_materials": len(unique_codes),
            "enriched_count": enriched_codes,
            "coverage_pct": (enriched_codes / len(unique_codes) * 100) if unique_codes else 0.0,
            "total_ratings_added": total_ratings_added,
            "ratings_by_type": {
                col: int(miul_df[col].notna().sum()) for col in RATING_COLUMNS
            },
        }

        LOGGER.info(
            f"[Workflow] Enriched {stats['enriched_count']}/{stats['total_materials']} "
            f"materials ({stats['coverage_pct']:.1f}% coverage), {total_ratings_added} ratings added"
        )

        return miul_df, stats

    def fill_gaps_with_aggregated_ratings(
        self, miul_df: pd.DataFrame, use_inheritance: bool = True
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Step 3b: Fill rating gaps using inherited ratings from related materials.

        For materials with missing ratings, attempts to inherit ratings from
        related materials (same alloy family) using chemistry-based rules.

        Args:
            miul_df: MIUL DataFrame with rating columns (after fetch_ratings)
            use_inheritance: Whether to use rating inheritance (default True)

        Returns:
            Tuple of (enriched DataFrame, stats dict with inheritance info)
        """
        if not use_inheritance:
            return miul_df, {"inherited_count": 0, "skipped": "inheritance disabled"}

        LOGGER.info("[Workflow] Step 3b: Filling gaps with aggregated ratings")

        inherited_count = 0
        inheritance_details = []

        # Find rows with gaps
        for idx, row in miul_df.iterrows():
            material_code = row.get("Material Code")
            if pd.isna(material_code) or not str(material_code).strip():
                continue

            material_code = str(material_code).strip()
            material_form = row.get("Form", "")

            # Check which ratings are missing
            gaps = []
            for col in RATING_COLUMNS:
                val = row.get(col, "")
                if pd.isna(val) or str(val).strip() in GAP_VALUES:
                    gaps.append(col)

            if not gaps:
                continue  # No gaps to fill

            # Get aggregated ratings with inheritance
            try:
                agg_result = get_aggregated_ratings(material_code, material_form)

                if not agg_result.ratings:
                    continue

                # Fill gaps with inherited ratings
                for gap_col in gaps:
                    if gap_col not in agg_result.ratings:
                        continue

                    agg_rating = agg_result.ratings[gap_col]
                    if not agg_rating.rating or agg_rating.rating in GAP_VALUES:
                        continue

                    # Only use inherited ratings (not exact match - those should already be filled)
                    source = agg_rating.primary_source
                    if source and not source.is_exact_match:
                        miul_df.at[idx, gap_col] = agg_rating.rating
                        inherited_count += 1

                        inheritance_details.append({
                            "row_index": idx,
                            "material_code": material_code,
                            "rating_type": gap_col,
                            "inherited_from": source.material_code,
                            "inherited_rating": agg_rating.rating,
                            "confidence": source.confidence,
                            "source_designation": source.designation,
                        })

                        LOGGER.debug(
                            f"[Workflow] Inherited {gap_col}={agg_rating.rating} for {material_code} "
                            f"from {source.material_code}"
                        )

            except Exception as e:
                LOGGER.warning(f"[Workflow] Aggregation failed for {material_code}: {e}")
                continue

        stats = {
            "inherited_count": inherited_count,
            "materials_with_inheritance": len(set(d["material_code"] for d in inheritance_details)),
            "inheritance_details": inheritance_details[:50],  # Limit for logging
        }

        LOGGER.info(
            f"[Workflow] Inherited {inherited_count} ratings for "
            f"{stats['materials_with_inheritance']} materials"
        )

        return miul_df, stats

    def identify_rating_gaps(self, miul_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Step 4: Identify parts needing rationale selection.

        Args:
            miul_df: MIUL DataFrame with rating columns

        Returns:
            List of parts needing rationale (with gap details)
        """
        LOGGER.info("[Workflow] Step 4: Identifying rating gaps")

        parts_needing_rationale = []

        for idx, row in miul_df.iterrows():
            gaps = []

            for rating_col in RATING_COLUMNS:
                value = row.get(rating_col, "")
                if pd.isna(value) or str(value).strip() in GAP_VALUES:
                    gaps.append(rating_col)

            if gaps:
                parts_needing_rationale.append({
                    "index": idx,
                    "line_number": row.get("Line Number", idx + 1),
                    "detail_drawing": row.get("Detail Drawing", ""),
                    "designation": row.get("Designation", ""),
                    "material_code": row.get("Material Code", ""),
                    "gaps": gaps,
                    "current_ratings": {
                        col: str(row.get(col, "")) for col in RATING_COLUMNS
                    },
                })

        LOGGER.info(
            f"[Workflow] Found {len(parts_needing_rationale)} parts with rating gaps"
        )

        return parts_needing_rationale

    def apply_rationale(
        self,
        miul_df: pd.DataFrame,
        resolutions: List[Dict[str, Any]],
    ) -> pd.DataFrame:
        """Step 5: Apply user-selected rationale codes.

        Args:
            miul_df: MIUL DataFrame
            resolutions: List of resolution dicts with index, rat_code, rat_text

        Returns:
            Updated DataFrame with rationale applied
        """
        LOGGER.info(f"[Workflow] Step 5: Applying {len(resolutions)} rationale resolutions")

        for res in resolutions:
            idx = res.get("index")
            if idx is None or idx not in miul_df.index:
                LOGGER.warning(f"Invalid resolution index: {idx}")
                continue

            rat_code = res.get("rat_code", "")
            rat_text = res.get("rat_text", "")

            # Apply to MUA Rationale column
            existing = str(miul_df.at[idx, "MUA Rationale"] or "")
            if existing and rat_code:
                miul_df.at[idx, "MUA Rationale"] = f"{existing}; {rat_code}"
            elif rat_code:
                miul_df.at[idx, "MUA Rationale"] = rat_code

            # Add text to remarks if provided
            if rat_text:
                existing_remarks = str(miul_df.at[idx, "Remarks"] or "")
                if existing_remarks:
                    miul_df.at[idx, "Remarks"] = f"{existing_remarks}; {rat_text}"
                else:
                    miul_df.at[idx, "Remarks"] = rat_text

        return miul_df

    def populate_mua_remarks(
        self,
        miul_df: pd.DataFrame,
        max_chars: int = 200,
        overwrite: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Step 5b: Populate Remarks column with MUA rationale for non-A ratings.

        Uses historic MUA precedents from BOK to generate brief but complete
        justifications explaining why materials with non-A ratings can be used.

        Args:
            miul_df: MIUL DataFrame with rating columns
            max_chars: Maximum characters per remark (default 200)
            overwrite: If True, overwrite existing remarks; if False, append

        Returns:
            Tuple of (updated DataFrame, stats dict)

        Stats include:
            - rows_with_gaps: Number of rows with non-A ratings
            - remarks_added: Number of remarks generated
            - precedents_found: Count of MUA precedents found
        """
        LOGGER.info("[Workflow] Step 5b: Populating MUA remarks for non-A ratings")

        rows_with_gaps = 0
        remarks_added = 0
        precedents_found = 0

        # Use the remarks generator module
        for idx, row in miul_df.iterrows():
            # Skip if already has remarks and not overwriting
            existing_remarks = row.get("Remarks", "")
            if existing_remarks and not overwrite:
                continue

            # Convert row to dict for processing
            row_dict = row.to_dict()

            # Generate remark using BOK engine
            result = generate_remark(row_dict, max_chars=max_chars)

            if result.gaps:
                rows_with_gaps += 1

            if result.remarks:
                if existing_remarks and not overwrite:
                    # Append to existing
                    miul_df.at[idx, "Remarks"] = f"{existing_remarks} {result.remarks}".strip()
                else:
                    miul_df.at[idx, "Remarks"] = result.remarks
                remarks_added += 1

                if result.has_precedent:
                    precedents_found += 1

        stats = {
            "rows_with_gaps": rows_with_gaps,
            "remarks_added": remarks_added,
            "precedents_found": precedents_found,
            "coverage_pct": (remarks_added / rows_with_gaps * 100) if rows_with_gaps > 0 else 0.0,
        }

        LOGGER.info(
            f"[Workflow] Added {remarks_added} remarks for {rows_with_gaps} rows with gaps "
            f"({stats['coverage_pct']:.1f}% coverage), {precedents_found} with precedents"
        )

        return miul_df, stats

    def export_to_excel(self, miul_df: pd.DataFrame) -> BytesIO:
        """Generate final MIUL Excel file.

        Args:
            miul_df: Final MIUL DataFrame

        Returns:
            BytesIO buffer containing Excel file
        """
        LOGGER.info(f"[Workflow] Exporting MIUL with {len(miul_df)} rows to Excel")

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            miul_df.to_excel(writer, sheet_name="MIUL", index=False)

        output.seek(0)
        return output

    async def run_full_pipeline(
        self,
        pdf_paths: List[Path],
        auto_enrich: bool = True,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Run complete extraction and enrichment pipeline.

        Convenience method that runs steps 1-4 in sequence.

        Args:
            pdf_paths: List of PDF file paths
            auto_enrich: Whether to run enrichment (steps 2-4)

        Returns:
            Tuple of (MIUL DataFrame, pipeline stats)

        Pipeline stats include:
            - pdf_count: Number of PDFs processed
            - parts_extracted: Total parts extracted
            - codes_found: Material codes successfully resolved
            - quarantine_count: Materials needing human review
            - quarantine_list: Details of quarantined items
            - enrichment_stats: Rating enrichment statistics
            - gaps_found: Rating gaps requiring rationale
        """
        stats = {
            "pdf_count": len(pdf_paths),
            "parts_extracted": 0,
            "codes_found": 0,
            "quarantine_count": 0,
            "quarantine_list": [],
            "enrichment_stats": {},
            "gaps_found": 0,
        }

        # Step 1: Extract
        miul_df = await self.extract_from_pdfs(pdf_paths)
        stats["parts_extracted"] = len(miul_df)

        if auto_enrich:
            # Step 2: Lookup codes (with quarantine for ambiguous matches)
            miul_df, codes_found, quarantine = self.lookup_material_codes(miul_df)
            stats["codes_found"] = codes_found
            stats["quarantine_count"] = len(quarantine)
            stats["quarantine_list"] = quarantine

            # Step 3: Fetch ratings
            miul_df, enrichment_stats = self.fetch_ratings(miul_df)
            stats["enrichment_stats"] = enrichment_stats

            # Step 3b: Fill gaps with aggregated/inherited ratings
            miul_df, inheritance_stats = self.fill_gaps_with_aggregated_ratings(miul_df)
            stats["inheritance_stats"] = inheritance_stats

            # Step 4: Identify gaps
            gaps = self.identify_rating_gaps(miul_df)
            stats["gaps_found"] = len(gaps)
            stats["parts_needing_rationale"] = gaps

            # Step 5b: Populate MUA remarks for non-A ratings
            miul_df, remarks_stats = self.populate_mua_remarks(miul_df)
            stats["remarks_stats"] = remarks_stats

        LOGGER.info(f"[Workflow] Pipeline complete: {stats}")
        return miul_df, stats

    def _transform_parts_to_miul(self, parts: List[Dict[str, Any]]) -> pd.DataFrame:
        """Transform extracted parts to MIUL DataFrame format.

        Args:
            parts: List of part dicts from extractor or tree builder

        Returns:
            MIUL-formatted DataFrame

        Note:
            When parts come from tree builder, they include:
            - index: Tree position index (1-based)
            - parent_index: Parent's index (0 for root)
            - next_assembly: NHA drawing number
        """
        rows = []

        for i, part in enumerate(parts, 1):
            # Use tree builder Index/Parent if available, else generate sequentially
            # Note: tree_builder.py uses capital keys: Index, Parent, Next Assembly
            index = part.get("Index", i)
            parent = part.get("Parent", 0)

            # Extract fields needed for form inference
            description = part.get("description", "")
            designation = part.get("designation", part.get("material", ""))
            material_spec = part.get("material_spec", "")
            existing_form = part.get("material_form", "")

            # Infer material form if not already specified
            form_result = infer_material_form(
                nomenclature=description,  # Use description as nomenclature
                part_description=description,
                designation=designation,
                material_spec=material_spec,
                existing_form=existing_form,
            )
            material_form = form_result.form

            if form_result.form and form_result.source != "existing":
                LOGGER.debug(
                    f"[FormInference] {part.get('part_number', 'UNKNOWN')}: "
                    f"form='{form_result.form}' (source={form_result.source})"
                )

            rows.append({
                "Index": index,
                "Parent": parent,
                "Detail Drawing": part.get("part_number", ""),
                "Next Assembly": part.get("Next Assembly", part.get("next_assembly", "")),
                "Change Letter": "",
                "Drawing Source": part.get("source_file", ""),
                "Material Form": material_form,
                "Material Manufacturer": "",
                # Support both old 'material' key and new 'designation' key
                "Designation": designation,
                "Material Specification": material_spec,
                "Process Specification": part.get("process_spec", ""),
                "Environment": "",
                "Material Code": "",
                "Standard Part Number": "",
                "Contractor": "",
                "System": "",
                "Subsystem": "",
                "Max Temperature": "",
                "Min Temperature": "",
                "Fluid Type": "",
                "Associate Contractor": "",
                "Project": "",
                "Document Title": description,
                "Criticality": "",
                "Line Number": index,
                "Overall Evaluation": "",
                "Configuration Test": "",
                "Max Pressure": "",
                "Min Pressure": "",
                "MUA Rationale": "",
                "Cure Codes": "",
                "FLAM": "",
                "SCC": "",
                "CORR": "",
                "TVS": "",
                "TOX": "",
                "FS": "",
                "Remarks": "",
            })

        return pd.DataFrame(rows, columns=MIUL_COLUMNS)


# Global workflow instance
_workflow: Optional[MIULWorkflow] = None


def get_miul_workflow() -> MIULWorkflow:
    """Get singleton workflow instance."""
    global _workflow
    if _workflow is None:
        _workflow = MIULWorkflow()
    return _workflow


def reset_workflow() -> None:
    """Reset singleton for testing."""
    global _workflow
    _workflow = None


__all__ = [
    "MIULWorkflow",
    "get_miul_workflow",
    "reset_workflow",
    "MIUL_COLUMNS",
    "RATING_COLUMNS",
]
