#!/usr/bin/env python3
"""
Module: Legacy Engine
Purpose: Legacy FAISS-based Hydrogen Compatibility Engine for MIRA.

This module contains the original HydrogenCompatibilityEngine class that
uses MAPTIS FAISS metadata and H2 BOK vector search. It has been superseded
by the H2 Knowledge Twin v3 (engine_simple.py) for compatibility verdicts,
but is still used by:
  - mira/bsmh/bok_adapter.py (H2 BOK vector search)
  - mira/core/search_engine.py (material recommendation)

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

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

LOGGER = logging.getLogger(__name__)

# H2 compatibility ratings based on NSS 1740.16 and test data
# A = Excellent (austenitic stainless, nickel alloys)
# B = Good (some aluminum alloys, copper alloys with caution)
# C = Fair (limited use, may require special treatment)
# D = Poor (not recommended, high embrittlement risk)
# U = Unknown (insufficient data)

class HydrogenCompatibilityEngine:
    """
    Filter and score materials for hydrogen service compatibility.

    Post-processes FAISS search results to prioritize materials with
    proven hydrogen compatibility based on test data and reference standards.
    """

    def __init__(self, maptis_metadata_path: Optional[Path] = None, h2_bok_dir: Optional[Path] = None):
        """
        Initialize H2 engine with MAPTIS test data and H2 BOK.

        Args:
            maptis_metadata_path: Path to MAPTIS FAISS metadata.json
            h2_bok_dir: Path to H2 BOK database directory
        """
        self.h2_database: Dict[int, Dict[str, Any]] = {}
        self.h2_materials: Set[int] = set()

        # H2 BOK components
        self.h2_bok_index = None
        self.h2_bok_metadata = None
        self.h2_bok_text_lookup = None
        self.h2_bok_model = None

        # Load MAPTIS test data if provided
        if maptis_metadata_path and maptis_metadata_path.exists():
            self._load_maptis_h2_data(maptis_metadata_path)

        # Load H2 BOK (NSS 1740.16, SAND2012_7321, etc.)
        if h2_bok_dir is None:
            # Try default path
            h2_bok_dir = Path(__file__).parent.parent.parent / "mira" / "databases" / "h2_bok"

        if h2_bok_dir and h2_bok_dir.exists():
            self._load_h2_bok(h2_bok_dir)

        LOGGER.info(f"H2 engine initialized with {len(self.h2_materials)} H2-compatible materials")

    def _load_maptis_h2_data(self, metadata_path: Path):
        """Extract H2-related test records from MAPTIS metadata."""
        try:
            with open(metadata_path, 'r') as f:
                data = json.load(f)

            records = data.get('metadata', [])
            h2_keywords = ['hydrogen', ' h2', 'lh2', 'gh2', 'liquid hydrogen', 'gaseous hydrogen']

            for record in records:
                material_key = record.get('material_key')
                if not material_key:
                    continue

                payload = record.get('payload', {})
                payload_str = json.dumps(payload).lower()

                # Check if record mentions hydrogen
                has_h2 = any(keyword in payload_str for keyword in h2_keywords)

                if has_h2:
                    # Initialize material entry if not exists
                    if material_key not in self.h2_database:
                        self.h2_database[material_key] = {
                            'material_key': material_key,
                            'h2_test_count': 0,
                            'test_types': set(),
                            'ratings': [],
                            'temperature_range': {'min_f': None, 'max_f': None},
                            'pressure_psi': [],
                            'test_fluids': set(),
                            'embrittlement_risk': 'unknown',
                            'source_docs': set(),
                            'test_records': []
                        }

                    # Update material entry
                    mat_data = self.h2_database[material_key]
                    mat_data['h2_test_count'] += 1
                    mat_data['test_types'].add(record.get('contract_id', 'unknown'))
                    mat_data['test_records'].append(record.get('row_uid'))

                    # Extract test fluid if available
                    for key in ['arc_gasname', 'fluid_name', 'test_fluid', 'environment']:
                        if key in payload:
                            fluid = str(payload[key]).strip().upper()
                            if any(h2 in fluid for h2 in ['H2', 'HYDROGEN']):
                                mat_data['test_fluids'].add(fluid)

                    # Extract temperature range
                    for key in ['temperatureminimum', 'temp_min', 'temperaturemaximum', 'temp_max']:
                        if key in payload and payload[key]:
                            try:
                                temp = float(payload[key])
                                if 'min' in key.lower():
                                    if mat_data['temperature_range']['min_f'] is None or temp < mat_data['temperature_range']['min_f']:
                                        mat_data['temperature_range']['min_f'] = temp
                                else:
                                    if mat_data['temperature_range']['max_f'] is None or temp > mat_data['temperature_range']['max_f']:
                                        mat_data['temperature_range']['max_f'] = temp
                            except (ValueError, TypeError):
                                pass

                    # Extract rating if available
                    for key in ['rating', 'fluc_rating', 'test_rating', 'compatibility_rating']:
                        if key in payload and payload[key]:
                            rating = str(payload[key]).strip().upper()
                            if rating and rating not in ['NULL', 'NONE', '']:
                                mat_data['ratings'].append(rating[0] if rating else 'U')

                    # Add to H2 materials set
                    self.h2_materials.add(material_key)

            # Convert sets to lists for JSON serialization
            for mat_key in self.h2_database:
                self.h2_database[mat_key]['test_types'] = list(self.h2_database[mat_key]['test_types'])
                self.h2_database[mat_key]['test_fluids'] = list(self.h2_database[mat_key]['test_fluids'])
                self.h2_database[mat_key]['source_docs'] = list(self.h2_database[mat_key]['source_docs'])

            LOGGER.info(f"Extracted {len(self.h2_materials)} materials with H2 test data from MAPTIS")

        except Exception as e:
            LOGGER.error(f"Failed to load MAPTIS H2 data: {e}")

    def _load_h2_bok(self, h2_bok_dir: Path):
        """Load H2 Body of Knowledge FAISS index and metadata."""
        try:
            import faiss
            from sentence_transformers import SentenceTransformer

            index_file = h2_bok_dir / "h2_bok_faiss.index"
            metadata_file = h2_bok_dir / "h2_bok_faiss_metadata.json"
            text_lookup_file = h2_bok_dir / "h2_bok_text_lookup.json"

            if not all([f.exists() for f in [index_file, metadata_file, text_lookup_file]]):
                LOGGER.warning(f"H2 BOK files not found in {h2_bok_dir}. Run: python scripts/build_h2_bok_index.py")
                return

            # Load FAISS index
            self.h2_bok_index = faiss.read_index(str(index_file))

            # Load metadata
            with open(metadata_file, 'r', encoding='utf-8') as f:
                self.h2_bok_metadata = json.load(f)

            # Load text lookup
            with open(text_lookup_file, 'r', encoding='utf-8') as f:
                self.h2_bok_text_lookup = json.load(f)

            # Load embedding model
            self.h2_bok_model = SentenceTransformer('all-MiniLM-L6-v2')

            LOGGER.info(f"Loaded H2 BOK with {len(self.h2_bok_metadata)} sections from NSS 1740.16, SAND2012_7321, etc.")

        except ImportError as e:
            LOGGER.warning(f"Cannot load H2 BOK - missing dependencies: {e}")
        except Exception as e:
            LOGGER.error(f"Failed to load H2 BOK: {e}")

    def search_h2_bok(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Search H2 Body of Knowledge for relevant material compatibility info.

        Args:
            query: Natural language query (e.g., "stainless steel 316 hydrogen compatibility")
            k: Number of results to return

        Returns:
            List of relevant H2 BOK sections with metadata
        """
        if self.h2_bok_index is None or self.h2_bok_model is None:
            LOGGER.warning("H2 BOK not loaded - cannot search")
            return []

        try:
            # Embed query
            query_embedding = self.h2_bok_model.encode([query], convert_to_numpy=True)

            # Search FAISS index
            distances, indices = self.h2_bok_index.search(query_embedding.astype('float32'), k)

            # Gather results
            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx >= len(self.h2_bok_metadata):
                    continue

                meta = self.h2_bok_metadata[idx]
                doc_id = meta['doc_id']
                text = self.h2_bok_text_lookup.get(doc_id, "")

                results.append({
                    'doc_id': doc_id,
                    'source': meta['source_document'],
                    'page': meta['page_number'],
                    'section': meta['section'],
                    'title': meta['title'],
                    'text': text,
                    'tags': meta['tags'],
                    'distance': float(dist),
                    'relevance_score': 1.0 / (1.0 + float(dist))  # Convert distance to score
                })

            return results

        except Exception as e:
            LOGGER.error(f"H2 BOK search failed: {e}")
            return []

    def has_h2_test_data(self, material_key: int) -> bool:
        """Check if material has any hydrogen test data."""
        return material_key in self.h2_materials

    def get_h2_info(self, material_key: int) -> Optional[Dict[str, Any]]:
        """Get hydrogen compatibility info for a material."""
        return self.h2_database.get(material_key)

    def calculate_h2_score(self, material_key: int) -> float:
        """
        Calculate H2 compatibility score for a material (0.0 to 1.0).

        Scoring factors:
        - Has H2 test data: +0.5 base
        - Multiple test types: +0.1 per type (max +0.2)
        - Has rating: +0.2
        - Rating A: +0.3, B: +0.2, C: +0.1
        - Cryogenic tested (<-200F): +0.1

        Max score: 1.0
        """
        if material_key not in self.h2_database:
            return 0.0

        mat_data = self.h2_database[material_key]
        # WHY 0.5 base: Having ANY H2 test data is a positive signal (better
        # than 0.0 for untested materials). 0.5 = "we have data, but haven't
        # evaluated quality yet."
        score = 0.5

        # WHY 0.1 per test type, max 0.2: Multiple independent test types
        # (slow strain rate, disk rupture, permeation) indicate broader
        # characterization. Capped at 0.2 to prevent test-count inflation
        # from dominating the score.
        test_type_count = len(mat_data['test_types'])
        score += min(0.2, test_type_count * 0.1)

        # WHY rating weights (A=0.3, B=0.2, C=0.1): NASA-STD-6001B ratings
        # directly indicate H2 service suitability. "A" = fully compatible,
        # so it gets the largest boost. "D" or unrated gets nothing.
        if mat_data['ratings']:
            score += 0.1  # Has any rating at all
            best_rating = min(mat_data['ratings'])  # A < B < C < D
            if best_rating == 'A':
                score += 0.3
            elif best_rating == 'B':
                score += 0.2
            elif best_rating == 'C':
                score += 0.1

        # WHY -200°F threshold: Materials tested below -200°F have demonstrated
        # cryogenic toughness, relevant for LH2 service at -423°F.
        min_temp = mat_data['temperature_range'].get('min_f')
        if min_temp and min_temp < -200:
            score += 0.1

        return min(1.0, score)

    def filter_h2_compatible(
        self,
        candidates: List[Dict[str, Any]],
        require_test_data: bool = True,
        min_score: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Filter search results to H2-compatible materials.

        Args:
            candidates: List of material search results
            require_test_data: If True, only return materials with H2 test data
            min_score: Minimum H2 compatibility score (0.0 to 1.0)

        Returns:
            Filtered and H2-scored results
        """
        filtered = []

        for candidate in candidates:
            material_key = candidate.get('material_key')
            if not material_key:
                continue

            # Check if has H2 test data
            if require_test_data and material_key not in self.h2_materials:
                continue

            # Calculate H2 score
            h2_score = self.calculate_h2_score(material_key)

            # Apply minimum score filter
            if h2_score < min_score:
                continue

            # Add H2 info to candidate
            candidate['h2_score'] = h2_score
            candidate['h2_info'] = self.get_h2_info(material_key)
            candidate['has_h2_test_data'] = self.has_h2_test_data(material_key)

            filtered.append(candidate)

        # Sort by H2 score (descending)
        filtered.sort(key=lambda x: x.get('h2_score', 0.0), reverse=True)

        return filtered

    def boost_h2_compatible(
        self,
        candidates: List[Dict[str, Any]],
        h2_weight: float = 0.4
    ) -> List[Dict[str, Any]]:
        """
        Re-rank search results by combining original score with H2 score.

        Args:
            candidates: List of material search results with 'score' field
            h2_weight: Weight for H2 score (0.0 to 1.0), default 0.4

        Returns:
            Re-ranked results with combined score
        """
        for candidate in candidates:
            material_key = candidate.get('material_key')
            if not material_key:
                continue

            # Get original similarity score
            original_score = candidate.get('score', 0.0)

            # Calculate H2 score
            h2_score = self.calculate_h2_score(material_key)

            # Combine scores
            combined_score = (1 - h2_weight) * original_score + h2_weight * h2_score

            # Update candidate
            candidate['original_score'] = original_score
            candidate['h2_score'] = h2_score
            candidate['score'] = combined_score
            candidate['h2_info'] = self.get_h2_info(material_key)
            candidate['has_h2_test_data'] = self.has_h2_test_data(material_key)

        # Re-sort by combined score
        candidates.sort(key=lambda x: x.get('score', 0.0), reverse=True)

        return candidates

    def get_recommended_materials_from_bok(self, query: str = "recommended materials for hydrogen service") -> List[str]:
        """
        Extract recommended material names from H2 BOK.

        Searches H2 BOK for material recommendations and extracts specific material designations
        like "SS 316", "SS 321", "Inconel 625", etc.

        Args:
            query: Query to search H2 BOK

        Returns:
            List of material designations found in H2 BOK
        """
        if self.h2_bok_index is None:
            return self._get_evidence_derived_materials()

        # Search H2 BOK for both general recommendations and specific materials table
        queries = [
            query,
            "Table A5.2 recommended materials typical applications",
            "austenitic stainless steel 300 series hydrogen",
            "Inconel Monel nickel alloys hydrogen service"
        ]

        bok_results = []
        for q in queries:
            bok_results.extend(self.search_h2_bok(q, k=5))

        # Extract material names using pattern matching
        import re
        materials = set()

        # Common H2-compatible material patterns
        patterns = [
            r'\b(SS|stainless steel)\s*(\d{3}L?)\b',  # SS 316, SS 304L, etc.
            r'\b(Inconel|INCONEL)\s*(\d{3})\b',  # Inconel 625, 718
            r'\b(Hastelloy|HASTELLOY)\s*([A-Z]-?\d+)\b',  # Hastelloy C-276
            r'\b(Monel|MONEL)\s*(\d{3})\b',  # Monel 400
            r'\b(AL|aluminum)\s*(\d{4})\b',  # AL 6061, 2024
            r'\b(type|Type)\s*(\d{3}L?)\b',  # Type 316L
            r'\b(\d{3}L?)\s*(stainless|SS)\b',  # 316 stainless
        ]

        for result in bok_results:
            text = result.get('text', '')

            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    if len(match.groups()) >= 2:
                        prefix = match.group(1)
                        number = match.group(2)

                        # Normalize material designation
                        if prefix.upper() in ['SS', 'STAINLESS STEEL', 'TYPE']:
                            materials.add(f"SS {number}")
                        elif prefix.upper() == 'INCONEL':
                            materials.add(f"INCONEL {number}")
                        elif prefix.upper() == 'HASTELLOY':
                            materials.add(f"HASTELLOY {number}")
                        elif prefix.upper() == 'MONEL':
                            materials.add(f"MONEL {number}")
                        elif prefix.upper() in ['AL', 'ALUMINUM']:
                            materials.add(f"AL {number}")

        # If BOK extraction found nothing, fall back to evidence-derived list
        if not materials:
            return self._get_evidence_derived_materials()

        LOGGER.info(f"Extracted {len(materials)} material recommendations from H2 BOK: {sorted(materials)}")
        return list(materials)

    def _get_evidence_derived_materials(self) -> List[str]:
        """Derive recommended materials from the H2 evidence database.

        Instead of a hardcoded list, query the evidence records for materials
        with negligible or small HEE bands.
        """
        try:
            from mira.knowledge_twins.h2.engine_simple import H2Engine
            engine = H2Engine()
            return engine.get_all_materials()
        except Exception as e:
            LOGGER.warning(f"Could not derive materials from evidence: {e}")
            return []

    def enrich_with_h2_bok(self, material_name: str, k: int = 3) -> List[Dict[str, Any]]:
        """
        Search H2 BOK for context about a specific material.

        Args:
            material_name: Material name/designation (e.g., "SS 316", "Inconel 625")
            k: Number of BOK sections to return

        Returns:
            List of relevant H2 BOK sections about this material
        """
        if self.h2_bok_index is None:
            return []

        query = f"{material_name} hydrogen compatibility materials selection"
        return self.search_h2_bok(query, k=k)

    def explain_h2_compatibility(self, material_key: int, material_name: str = None) -> str:
        """
        Generate human-readable explanation of H2 compatibility.

        Args:
            material_key: MAPTIS material key
            material_name: Optional material name for H2 BOK enrichment

        Returns:
            Detailed explanation with MAPTIS test data and H2 BOK context
        """
        if material_key not in self.h2_database:
            explanation = "No hydrogen test data available for this material in MAPTIS."

            # Try H2 BOK if material name provided
            if material_name and self.h2_bok_index is not None:
                bok_results = self.enrich_with_h2_bok(material_name, k=1)
                if bok_results:
                    bok_text = bok_results[0]['text'][:300]
                    explanation += f"\n\nH2 BOK Context: {bok_text}... (Source: {bok_results[0]['source']}, p.{bok_results[0]['page']})"

            return explanation

        mat_data = self.h2_database[material_key]
        parts = []

        # Test data summary
        test_count = mat_data['h2_test_count']
        test_types = ', '.join(mat_data['test_types'])
        parts.append(f"Material has {test_count} hydrogen test record(s) in MAPTIS ({test_types}).")

        # Rating
        if mat_data['ratings']:
            best_rating = min(mat_data['ratings'])
            rating_desc = {
                'A': 'Excellent',
                'B': 'Good',
                'C': 'Fair',
                'D': 'Poor',
                'U': 'Unknown'
            }.get(best_rating, 'Unknown')
            parts.append(f"Best rating: {best_rating} ({rating_desc}).")

        # Temperature range
        min_temp = mat_data['temperature_range'].get('min_f')
        max_temp = mat_data['temperature_range'].get('max_f')
        if min_temp or max_temp:
            temp_str = f"{min_temp or 'N/A'}°F to {max_temp or 'N/A'}°F"
            parts.append(f"Tested temperature range: {temp_str}.")
            if min_temp and min_temp < -200:
                parts.append("Suitable for cryogenic hydrogen service (LH2).")

        # Test fluids
        if mat_data['test_fluids']:
            fluids = ', '.join(mat_data['test_fluids'])
            parts.append(f"Test fluids: {fluids}.")

        # H2 score
        h2_score = self.calculate_h2_score(material_key)
        parts.append(f"H2 compatibility score: {h2_score:.2f}/1.00.")

        explanation = ' '.join(parts)

        # Add H2 BOK context if available
        if material_name and self.h2_bok_index is not None:
            bok_results = self.enrich_with_h2_bok(material_name, k=1)
            if bok_results:
                bok_text = bok_results[0]['text'][:300]
                explanation += f"\n\nH2 BOK Context: {bok_text}... (Source: {bok_results[0]['source']}, p.{bok_results[0]['page']})"

        return explanation
