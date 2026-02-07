#!/usr/bin/env python3
"""
Module: Pipeline
Purpose: from __future__ import annotations

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

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .builder import MIULBuilder
from .mua_builder import MUABuilder, MUABuildStats
from .models import BOMDocument
from src.api.miul_enrichment import MIULEnrichmentService
from src.api.material_code_lookup import MaterialCodeLookupService
import uuid

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Container for pipeline outputs and stats.

    Compliance: SWE-061
    """

    miul_df: pd.DataFrame
    mua_df: pd.DataFrame
    miul_stats: Dict[str, Any]
    mua_stats: MUABuildStats
    audit_trail: List[Dict[str, Any]]
    source: str = ""  # NASA SWE-013 traceability



class MIULMUAPipeline:
    """Integrated MIUL + MUA generation pipeline.

    Steps:
    - Load BOM (or prebuilt MIUL)
    - Build MIUL via MIULBuilder
    - Enrich MIUL with MAPTIS ratings (MIULEnrichmentService)
    - Summarize MUA per unique material (MUABuilder)

    Compliance: SWE-056, SWE-061
    """

    def __init__(self) -> None:
        self.miul_builder = MIULBuilder(enable_audit=True)
        self.enricher = MIULEnrichmentService()
        self.mua_builder = MUABuilder()
        self.lookup = MaterialCodeLookupService()

    def _load_bom(self, bom_path: Path) -> pd.DataFrame:
        """Load BOM file (Excel or CSV) into a DataFrame.

        Args:
            bom_path: Path to input BOM.

        Returns:
            DataFrame with at least Part Number/Quantity columns.
        """
        if not bom_path.exists():
            raise FileNotFoundError(f"BOM not found: {bom_path}")

        suffix = bom_path.suffix.lower()
        if suffix in ('.xlsx', '.xlsm', '.xls'):
            return pd.read_excel(bom_path)
        if suffix in ('.csv', '.txt'):
            return pd.read_csv(bom_path)
        raise ValueError(f"Unsupported BOM format: {bom_path.suffix}")

    def _make_crosswalk_from_bom(self, bom_df: pd.DataFrame) -> pd.DataFrame:
        """Derive a part->material code crosswalk from the BOM.

        Prefers an existing 'Material Code' column. If absent, attempts a
        conservative spec-based lookup using MaterialCodeLookupService.

        Returns:
            DataFrame with columns ['Part Number', 'Material Code'].
        """
        cols = {c.lower(): c for c in bom_df.columns}
        has_code = 'material code' in cols
        has_part = 'part number' in cols
        spec_col = cols.get('material spec.') or cols.get('material specification')

        if not has_part:
            raise ValueError("BOM must include 'Part Number' column")

        if has_code:
            return bom_df[[cols['part number'], cols['material code']]].rename(
                columns={cols['part number']: 'Part Number', cols['material code']: 'Material Code'}
            )

        # Fallback: attempt spec-based lookup
        if spec_col is None:
            # Nothing we can do deterministically; return empty crosswalk
            logger.warning("No 'Material Code' or spec column present; crosswalk will be empty")
            return pd.DataFrame(columns=['Part Number', 'Material Code'])

        records: List[Dict[str, Any]] = []
        for _, row in bom_df.iterrows():
            part = str(row[cols['part number']]).strip()
            spec = str(row[spec_col]).strip() if pd.notna(row.get(spec_col)) else ''
            if not part:
                continue
            code: Optional[str] = None
            if spec:
                extracted = self.lookup.extract_specs(spec)
                # Try exact spec lookups in a stable order
                for key in ('ams', 'uns', 'mil', 'astm', 'sae'):
                    for code_fragment in extracted.get(key, []):
                        matches = self.lookup.lookup_by_spec(key, code_fragment)
                        if matches:
                            code = matches[0].material_code
                            break
                    if code:
                        break
            records.append({'Part Number': part, 'Material Code': code or ''})

        return pd.DataFrame.from_records(records)

    def _safe_specs_df(self, specs_path: Optional[Path]) -> pd.DataFrame:
        """Load material specs DataFrame or provide an empty placeholder."""
        if specs_path is None:
            return pd.DataFrame(columns=['Material Code'])
        if not specs_path.exists():
            raise FileNotFoundError(f"Specs file not found: {specs_path}")
        if specs_path.suffix.lower() in ('.xlsx', '.xlsm', '.xls'):
            return pd.read_excel(specs_path)
        if specs_path.suffix.lower() in ('.csv', '.txt'):
            return pd.read_csv(specs_path)
        raise ValueError(f"Unsupported specs format: {specs_path.suffix}")

    def run_from_bom(
        self,
        bom_path: Path,
        crosswalk_path: Optional[Path] = None,
        specs_path: Optional[Path] = None,
    ) -> PipelineResult:
        """Execute the pipeline starting from a BOM file.

        Args:
            bom_path: Path to BOM (Excel/CSV).
            crosswalk_path: Optional path to part->material code mapping.
            specs_path: Optional path to material specs table.

        Returns:
            PipelineResult with MIUL and MUA DataFrames and stats.
        """
        bom_df = self._load_bom(bom_path)

        # Crosswalk: prefer provided, else derive
        if crosswalk_path and crosswalk_path.exists():
            if crosswalk_path.suffix.lower() in ('.xlsx', '.xlsm', '.xls'):
                crosswalk_df = pd.read_excel(crosswalk_path)
            elif crosswalk_path.suffix.lower() in ('.csv', '.txt'):
                crosswalk_df = pd.read_csv(crosswalk_path)
            else:
                raise ValueError(f"Unsupported crosswalk format: {crosswalk_path.suffix}")
        else:
            crosswalk_df = self._make_crosswalk_from_bom(bom_df)

        specs_df = self._safe_specs_df(specs_path)

        # MIUL build
        bom_doc: BOMDocument = self.miul_builder.load_bom_from_dataframe(bom_df)
        crosswalk = self.miul_builder.load_material_crosswalk(crosswalk_df) if not crosswalk_df.empty else {}
        specs = self.miul_builder.load_material_specs(specs_df) if not specs_df.empty else {}
        miul_result = self.miul_builder.build_miul_from_bom(
            bom_doc=bom_doc,
            material_crosswalk=crosswalk,
            material_specs=specs,
        )

        # Enrich MIUL with ratings
        enriched_miul_df, miul_stats = self.enricher.enrich_miul_dataframe(miul_result.miul_data.copy())

        # Build MUA summary
        mua_df, mua_stats = self.mua_builder.build_from_miul(enriched_miul_df)

        return PipelineResult(
            miul_df=enriched_miul_df,
            mua_df=mua_df,
            miul_stats=miul_stats,
            mua_stats=mua_stats,
            audit_trail=miul_result.audit_trail,
        )

    def run_from_dataframes(
        self,
        bom_df: pd.DataFrame,
        crosswalk_df: Optional[pd.DataFrame] = None,
        specs_df: Optional[pd.DataFrame] = None,
    ) -> PipelineResult:
        """Execute the pipeline from in-memory DataFrames.

        Args:
            bom_df: BOM DataFrame.
            crosswalk_df: Optional part->material code mapping.
            specs_df: Optional material specs table.

        Returns:
            PipelineResult with MIUL and MUA DataFrames and stats.
        """
        # MIUL build
        bom_doc: BOMDocument = self.miul_builder.load_bom_from_dataframe(bom_df)
        crosswalk = (
            self.miul_builder.load_material_crosswalk(crosswalk_df)
            if crosswalk_df is not None and not crosswalk_df.empty
            else {}
        )
        specs = (
            self.miul_builder.load_material_specs(specs_df)
            if specs_df is not None and not specs_df.empty
            else {}
        )
        miul_result = self.miul_builder.build_miul_from_bom(
            bom_doc=bom_doc,
            material_crosswalk=crosswalk,
            material_specs=specs,
        )

        # Enrich MIUL with ratings
        enriched_miul_df, miul_stats = self.enricher.enrich_miul_dataframe(miul_result.miul_data.copy())

        # Build MUA summary
        mua_df, mua_stats = self.mua_builder.build_from_miul(enriched_miul_df)

        return PipelineResult(
            miul_df=enriched_miul_df,
            mua_df=mua_df,
            miul_stats=miul_stats,
            mua_stats=mua_stats,
            audit_trail=miul_result.audit_trail,
        )

    def write_excel(self, result: PipelineResult, output_path: Path) -> Path:
        """Persist MIUL and MUA outputs to an Excel workbook.

        Sheets:
        - MIUL (enriched)
        - MUA (summary per material)
        - Metadata (build + enrichment stats)
        - Audit (optional audit events)

        Args:
            result: PipelineResult to serialize.
            output_path: Destination Excel file path.

        Returns:
            The path written.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            result.miul_df.to_excel(writer, sheet_name='MIUL', index=False)
            result.mua_df.to_excel(writer, sheet_name='MUA', index=False)

            # Metadata sheet (flatten stats)
            meta_rows: List[Dict[str, Any]] = []
            meta_rows.append({'key': 'miul_total_rows', 'value': int(len(result.miul_df))})
            meta_rows.append({'key': 'mua_total_materials', 'value': int(result.mua_stats.total_materials)})
            meta_rows.append({'key': 'mua_coverage_pct', 'value': float(result.mua_stats.coverage_pct)})
            for k, v in result.miul_stats.get('ratings_by_type', {}).items():
                meta_rows.append({'key': f"miul_{k.replace(' ', '_').lower()}", 'value': int(v)})
            for k, v in result.mua_stats.ratings_by_type.items():
                meta_rows.append({'key': f"mua_{k.replace(' ', '_').lower()}", 'value': int(v)})
            pd.DataFrame(meta_rows).to_excel(writer, sheet_name='Metadata', index=False)

            # Optional audit trail
            if result.audit_trail:
                pd.DataFrame(result.audit_trail).to_excel(writer, sheet_name='Audit', index=False)

        logger.info("Wrote MIUL+MUA workbook: %s", output_path)
        return output_path
