#!/usr/bin/env python3
"""
Module: Search Engine
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

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

__version__ = "3.0.0"
__safety_critical__ = True  # Class B/C: Handles material safety data per NASA-STD-6016

# Standard library imports
import logging
import os
import re
from pathlib import Path
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
import numpy as np

# Local imports
from mira.core.models import Material
from mira.nlp.intent_classifier import IntentClassifier
from mira.core.robust_faiss_store import RobustMAPTISFaissStore
from mira.core.faiss_store_v2 import MAPTISFaissStoreV2
from mira.utils.config import get_config
from mira.utils.exceptions import (
    FAISSIndexError, ConfigurationError, DataIntegrityError,
    ValidationError, PerformanceError, raise_safety_error
)
from mira.utils.performance_logger import track_performance, track_performance_decorator
from mira.utils.logging_config import get_logger
from mira.utils.cache import cache_key_wrapper, get_cache
from mira.utils.profiling import profile_async

# Configure logger
logger = get_logger(__name__)



class SemanticSearchEngine:
    """AI-powered semantic search engine using FAISS.

    Uses Facebook's FAISS for battle-tested GPU-accelerated semantic search.
    Designed for sub-millisecond response times with 10K+ materials.

    Compliance: SWE-032 (Data validation with standardized models)
    """

    # ---- H2 category helpers (validated-only, no string matching) --------
    @staticmethod
    def _is_metal_from_validated_type(original_material: dict) -> bool:
        """
        Return True iff validated material_type_key says 'Metal'.
        We NEVER infer from names or strings.
        BoundState Compliance: Validated field only.
        """
        if not isinstance(original_material, dict):
            return False
        try:
            tkey = original_material.get("material_type_key", None)
            return int(tkey) == 235  # 235 == 'Metal' in MAPTIS types
        except (TypeError, ValueError):
            return False

    # Class-level cache for composition-based material lookups
    _fluorosilicone_material_keys: Optional[set] = None

    @classmethod
    def _get_fluorosilicone_material_keys(cls) -> set:
        """
        Get material_keys for materials with CompositionKey=833 (fluorosilicone).

        Queries PostgreSQL materials table for all materials where composition=833.
        Results are cached at class level to avoid repeated database queries.

        Returns:
            Set of material_key integers for fluorosilicone materials
        """
        if cls._fluorosilicone_material_keys is not None:
            return cls._fluorosilicone_material_keys

        try:
            from mira.core.db_config import get_db_connection_params
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn_params = get_db_connection_params()
            conn = psycopg2.connect(**conn_params)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # CompositionKey 833 = Fluorosilicone in MAPTIS
            # Use exact match to avoid matching 8339 (CYCOM composites)
            # composition column is float, so match both 833 and 833.0
            cursor.execute("""
                SELECT material_key FROM materials
                WHERE composition::text IN ('833', '833.0')
            """)

            results = cursor.fetchall()
            cls._fluorosilicone_material_keys = {int(r['material_key']) for r in results}

            cursor.close()
            conn.close()

            logger.info(f"[SEARCH] Loaded {len(cls._fluorosilicone_material_keys)} fluorosilicone material keys from database")
            return cls._fluorosilicone_material_keys

        except Exception as e:
            logger.warning(f"[SEARCH] Could not load fluorosilicone material keys from DB: {e}")
            cls._fluorosilicone_material_keys = set()  # Empty set, fall back to text matching
            return cls._fluorosilicone_material_keys

    @classmethod
    def _is_fluorosilicone_material(cls, material_key: Optional[int], designation: str, material_type_key: Optional[int] = None) -> bool:
        """
        Check if a material is fluorosilicone by composition key or designation.

        Args:
            material_key: MAPTIS material key (may be None)
            designation: Material designation text (lowercase)
            material_type_key: MAPTIS material type (239=Polymer, 723=Elastomer, 235=Metal)

        Returns:
            True if material is fluorosilicone (composition=833 OR has fluorosilicone/fvmq in name)
            AND is not classified as Metal (type 235) - safeguard against bad data
        """
        # Safeguard: Metals cannot be fluorosilicone (catches bad comp=833 data like AL 6061)
        if material_type_key == 235:
            return False

        # Check text-based match first (fast)
        if 'fluorosilicone' in designation or 'fvmq' in designation:
            return True

        # Check composition-based match (requires DB lookup, cached)
        if material_key is not None:
            fluoro_keys = cls._get_fluorosilicone_material_keys()
            if int(material_key) in fluoro_keys:
                return True

        return False

    # Class-level cache for fluorosilicone materials data
    _fluorosilicone_materials_cache: Optional[List[Dict]] = None

    @classmethod
    def _get_fluorosilicone_materials_from_db(cls) -> List[Dict]:
        """
        Get all fluorosilicone materials from database (composition=833).

        Returns materials in FAISS result format so they can be merged with FAISS results.
        Includes flammability ratings from silver_report_rows.
        Results are cached at class level.

        Returns:
            List of material dicts in FAISS result format
        """
        if cls._fluorosilicone_materials_cache is not None:
            return cls._fluorosilicone_materials_cache

        try:
            from mira.core.db_config import get_db_connection_params
            import psycopg2
            from psycopg2.extras import RealDictCursor
            from collections import defaultdict

            conn_params = get_db_connection_params()
            conn = psycopg2.connect(**conn_params)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get all fluorosilicone materials (composition=833)
            # Exclude metals (type_key=235) to guard against bad data like AL 6061 with comp=833
            # Use exact match to avoid matching 8339 (CYCOM composites)
            # composition column is float, so match both 833 and 833.0
            cursor.execute("""
                SELECT material_key, material_code, designation,
                       material_type_key, material_type_name,
                       use_temp_min_f, use_temp_max_f
                FROM materials
                WHERE composition::text IN ('833', '833.0')
                AND (material_type_key IS NULL OR material_type_key != 235)
            """)

            rows = cursor.fetchall()
            # Use material_code for joining with silver_report_rows (materialkey field stores material_code)
            mat_codes = [str(row['material_code']) for row in rows if row['material_code']]

            # Fetch flammability ratings for these materials
            ratings_map = defaultdict(dict)
            if mat_codes:
                cursor.execute("""
                    SELECT normalized_payload->>'materialkey' as mat_code,
                           normalized_payload->>'flam_rating' as flam_rating
                    FROM silver_report_rows
                    WHERE contract_id = 'flammability_report'
                    AND normalized_payload->>'materialkey' = ANY(%s)
                    AND normalized_payload->>'flam_rating' IS NOT NULL
                """, (mat_codes,))

                # Take worst-case rating per material
                RATING_SEVERITY = {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'I': 5, 'X': 9}
                for r in cursor.fetchall():
                    mat_code = r['mat_code']
                    rating = (r['flam_rating'] or '').strip().upper()
                    if rating and rating not in ('NULL', ''):
                        existing = ratings_map[mat_code].get('flamm_rating', '')
                        if not existing or RATING_SEVERITY.get(rating, 10) > RATING_SEVERITY.get(existing, 0):
                            ratings_map[mat_code]['flamm_rating'] = rating

            results = []
            for row in rows:
                mat_key = row['material_key']
                designation = row['designation'] or ''
                mat_code = row['material_code'] or str(mat_key)

                # Get flammability rating for this material (keyed by material_code)
                flamm_rating = ratings_map.get(mat_code, {}).get('flamm_rating')

                # Build result in FAISS format
                result = {
                    'id': mat_code,
                    'name': designation,
                    'score': 0.85,  # Default score for DB-injected materials
                    'category': 'elastomer',  # Fluorosilicones are elastomers
                    'original_material': {
                        'material_key': mat_key,
                        'material_code': mat_code,
                        'designation': designation,
                        'material_type_key': row.get('material_type_key') or 723,  # Elastomer
                        'material_type_name': row.get('material_type_name') or 'Elastomer',
                        'temperature_minimum': row.get('use_temp_min_f'),
                        'temperature_maximum': row.get('use_temp_max_f'),
                        'flamm_rating': flamm_rating,
                        'o2_rating': flamm_rating,  # O2 rating = flammability for elastomers
                    },
                    'provenance': 'DB_FLUOROSILICONE_INJECTION',
                }
                results.append(result)

            cursor.close()
            conn.close()

            # Log how many have ratings
            with_ratings = sum(1 for r in results if r['original_material'].get('flamm_rating'))
            logger.info(f"[SEARCH] Loaded {len(results)} fluorosilicone materials ({with_ratings} with flammability ratings)")

            cls._fluorosilicone_materials_cache = results
            return results

        except Exception as e:
            logger.warning(f"[SEARCH] Could not load fluorosilicone materials from DB: {e}")
            cls._fluorosilicone_materials_cache = []
            return []

    def __init__(self, nlp_parser=None, intent_classifier: IntentClassifier | None = None):
        """Initialize the FAISS-based semantic search engine.
        
        Args:
            nlp_parser: Optional NLP parser for query understanding
            
        Raises:
            ConfigurationError: If FAISS path configuration is invalid
            FAISSIndexError: If FAISS index cannot be loaded
        """
        self.last_search_time = 0
        self.vector_store = None
        self.initialized = False
        self.nlp_parser = nlp_parser
        self.intent_classifier = intent_classifier or IntentClassifier()
        
        # Load configuration
        try:
            config = get_config()
        except Exception as e:
            raise_safety_error(
                ConfigurationError,
                f"Failed to load configuration: {e}",
                config_key="general_config"
            )
        
        # Get the absolute path to the FAISS index from config
        try:
            faiss_path = config.get_absolute_path(config.faiss_index_path)
        except Exception as e:
            raise_safety_error(
                ConfigurationError,
                f"Invalid FAISS index path configuration: {e}",
                config_key="faiss_index_path",
                expected_type="valid_path"
            )
        
        logger.info(f"Loading FAISS index from: {faiss_path}")
        
        # Initialize vector store - prefer V2 when JSON mapping files exist
        try:
            # Prefer store with richer metadata when available (enables numeric filters)
            json_index_path = Path(faiss_path)
            has_lookup = (json_index_path / "materials_lookup.json").exists()
            has_idmap = (json_index_path / "material_id_mapping.json").exists()
            has_metadata = (json_index_path / "metadata.json").exists()
            if has_lookup and has_idmap:
                logger.info("Using MAPTISFaissStoreV2 (materials_lookup + id mapping detected)")
                self.vector_store = MAPTISFaissStoreV2(persist_directory=faiss_path)
            elif has_metadata:
                # Use robust store when only metadata.json is present
                logger.info("Using RobustMAPTISFaissStore (metadata.json detected)")
                self.vector_store = RobustMAPTISFaissStore(index_path=faiss_path)
            else:
                # Safe default
                logger.info("Using RobustMAPTISFaissStore (default)")
                self.vector_store = RobustMAPTISFaissStore(index_path=faiss_path)
        except Exception as e:
            raise_safety_error(
                FAISSIndexError,
                f"Failed to initialize FAISS vector store: {e}",
                index_operation="initialization",
                details={"faiss_path": str(faiss_path)}
            )
        
        # Load pre-built index
        try:
            with track_performance("faiss_index_load"):
                if not self.vector_store.load_index():
                    raise_safety_error(
                        FAISSIndexError,
                        "Pre-built FAISS index failed to load",
                        index_operation="load",
                        details={
                            "faiss_path": str(faiss_path),
                            "suggestion": "Run fix_faiss_indexing.py to rebuild index"
                        }
                    )

            # Alignment check: if index rows exceed mapping size, fallback to V2
            try:
                idx_total = getattr(getattr(self.vector_store, 'index', None), 'ntotal', 0)
                mapping_size = None
                if hasattr(self.vector_store, 'material_ids'):
                    mapping_size = len(getattr(self.vector_store, 'material_ids'))
                elif hasattr(self.vector_store, 'metadata') and isinstance(getattr(self.vector_store, 'metadata'), list):
                    mapping_size = len(getattr(self.vector_store, 'metadata'))

                if idx_total and mapping_size and idx_total > mapping_size and has_lookup and has_idmap:
                    logger.warning(
                        f"FAISS index size ({idx_total}) > mapping size ({mapping_size}). Falling back to MAPTISFaissStoreV2.")
                    self.vector_store = MAPTISFaissStoreV2(persist_directory=faiss_path)
                    if not self.vector_store.load_index():
                        raise_safety_error(
                            FAISSIndexError,
                            "Fallback V2 store failed to load index",
                            index_operation="load_v2_fallback",
                            details={"faiss_path": str(faiss_path)}
                        )
            except Exception as e:
                logger.warning(f"Vector store alignment check failed: {e}")
        except FAISSIndexError:
            raise
        except Exception as e:
            logger.error(f"[ERROR] CRITICAL: FAISS index loading failed: {e}")
            raise_safety_error(
                FAISSIndexError,
                f"FAISS index loading failed: {e}",
                index_operation="load",
                details={"faiss_path": str(faiss_path)}
            )
        
        self.initialized = True
        logger.info("[SUCCESS] FAISS semantic search engine loaded from pre-built index")
            
        # AI query understanding patterns
        self.oxygen_keywords = [
            'oxygen', 'o2', 'lox', 'liquid oxygen', 'gaseous oxygen',
            'oxygen service', 'oxygen compatible', 'oxygen safe',
            'nasa-std-6001', 'oxygen system'
        ]

        self.hydrogen_keywords = [
            'hydrogen', 'h2', 'lh2', 'gh2', 'liquid hydrogen', 'gaseous hydrogen',
            'hydrogen service', 'hydrogen compatible', 'hydrogen environment',
            'cryogenic hydrogen'
        ]
        
        # Expanded rating keyword patterns to match natural language queries
        # Based on ACTUAL MAPTIS data - 17 unique ratings across 16 test classes
        # See MAPTIS_ACTUAL_RATING_SCALES.md for per-test-class mappings
        self.rating_keywords = {
            'a': [
                'a rated', 'a-rated', 'rated a',
                'class a', 'grade a', 'a level',
                'rating of a', 'rating a', 'a rating',
                'toxicity rating of a', 'toxicity rating a',
                'flammability rating of a', 'flammability rating a',
                'flash fire rating of a', 'flash fire rating a',
                'oxygen rating of a', 'hydrogen rating of a'
            ],
            'b': [
                'b rated', 'b-rated', 'rated b',
                'class b', 'grade b', 'b level',
                'rating of b', 'rating b', 'b rating',
                'toxicity rating of b', 'toxicity rating b',
                'flammability rating of b', 'flammability rating b'
            ],
            'c': [
                'c rated', 'c-rated', 'rated c',
                'class c', 'grade c', 'c level',
                'rating of c', 'rating c', 'c rating',
                'toxicity rating of c', 'toxicity rating c',
                'flammability rating of c', 'flammability rating c'
            ],
            'd': [
                'd rated', 'd-rated', 'rated d',
                'class d', 'grade d', 'd level',
                'rating of d', 'rating d', 'd rating',
                'tensile rating of d', 'tensile rating d'
            ],
            'f': [
                'f rated', 'f-rated', 'rated f',
                'class f', 'grade f', 'f level',
                'rating of f', 'rating f', 'f rating',
                'vcm rating of f', 'optical rating f'
            ],
            'h': [
                'h rated', 'h-rated', 'rated h',
                'class h', 'grade h', 'h level',
                'rating of h', 'rating h', 'h rating',
                'toxicity rating of h', 'toxicity rating h'
            ],
            'i': [
                'i rated', 'i-rated', 'rated i',
                'class i', 'grade i', 'i level',
                'rating of i', 'rating i', 'i rating',
                'incompatible', 'rating incompatible', 'inconclusive'
            ],
            'k': [
                'k rated', 'k-rated', 'rated k',
                'class k', 'grade k', 'k level',
                'rating of k', 'rating k', 'k rating',
                'toxicity rating of k', 'toxicity rating k'
            ],
            'n': [
                'n rated', 'n-rated', 'rated n',
                'class n', 'grade n', 'n level',
                'rating of n', 'rating n', 'n rating',
                'not tested', 'no test', 'untested'
            ],
            'p': [
                'p rated', 'p-rated', 'rated p',
                'class p', 'grade p', 'p level',
                'rating of p', 'rating p', 'p rating',
                'vcm rating of p', 'optical rating p'
            ],
            's': [
                's rated', 's-rated', 'rated s',
                'class s', 'grade s', 's level',
                'rating of s', 'rating s', 's rating',
                'special', 'satisfactory'
            ],
            'u': [
                'u rated', 'u-rated', 'rated u',
                'class u', 'grade u', 'u level',
                'rating of u', 'rating u', 'u rating',
                'unknown', 'no data', 'rating unknown'
            ],
            'v': [
                'v rated', 'v-rated', 'rated v',
                'class v', 'grade v', 'v level',
                'rating of v', 'rating v', 'v rating',
                'toxicity rating of v', 'toxicity rating v'
            ],
            'x': [
                'x rated', 'x-rated', 'rated x',
                'class x', 'grade x', 'x level',
                'rating of x', 'rating x', 'x rating',
                'failed', 'test failed', 'failure'
            ],
            'z': [
                'z rated', 'z-rated', 'rated z',
                'class z', 'grade z', 'z level',
                'rating of z', 'rating z', 'z rating',
                'fungus rating of z', 'fungus rating z'
            ]
        }

        # Back-compat attributes used in some tests/utilities
        self.min_similarity = 0.3
        self.default_top_k = 10

        # Pre-load H2 engine to avoid lazy loading during search
        try:
            from mira.core.h2_engine import get_h2_engine
            logger.info("Pre-loading H2 compatibility engine...")
            self.h2_engine = get_h2_engine()
            if self.h2_engine:
                logger.info(f"H2 engine ready with {len(self.h2_engine.h2_materials)} H2-compatible materials")
        except Exception as e:
            logger.warning(f"H2 engine pre-load failed (non-critical): {e}")
            self.h2_engine = None

        # Pre-load O2 engine to avoid lazy loading during search
        try:
            from mira.core.o2_engine import OxygenCompatibilityEngine
            from pathlib import Path as O2Path
            logger.info("Pre-loading O2 compatibility engine...")

            # Find MAPTIS metadata for O2 engine
            maptis_metadata_path = None
            possible_metadata_paths = [
                O2Path(__file__).parent.parent.parent / "MIRA_V2" / "data" / "faiss_indexes" / "maptis_index_metadata.json",
                O2Path(__file__).parent.parent.parent / "data" / "faiss_indexes" / "maptis_index_metadata.json",
            ]
            for path in possible_metadata_paths:
                if path.exists():
                    maptis_metadata_path = path
                    logger.info(f"Found MAPTIS metadata at: {path}")
                    break

            self.o2_engine = OxygenCompatibilityEngine(maptis_metadata_path=maptis_metadata_path)
            if self.o2_engine:
                # Count BOK sections if available
                bok_count = 0
                if hasattr(self.o2_engine, 'o2_bok_metadata') and self.o2_engine.o2_bok_metadata:
                    bok_count = len(self.o2_engine.o2_bok_metadata)
                logger.info(f"O2 engine ready with {len(self.o2_engine.o2_materials)} O2-tested materials and {bok_count} BOK sections")
        except Exception as e:
            logger.warning(f"O2 engine pre-load failed (non-critical): {e}")
            self.o2_engine = None

        # Load domain synonyms map (optional)
        self.synonyms_map: Dict[str, List[str]] = {}
        try:
            cfg = get_config()
            syn_path = cfg.get_absolute_path(Path(cfg.data_path) / "materials_synonyms.json")
            if syn_path.exists():
                with open(syn_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # Normalize keys to lowercase for matching
                        self.synonyms_map = {str(k).lower(): [str(v) for v in (vals or [])]
                                             for k, vals in data.items()}
                        # Ensure a few default groups exist even if not present in file
                        default_groups: Dict[str, List[str]] = {
                            "plastic": [
                                "polymer", "plastics", "thermoplastic", "thermoset", "resin"
                            ],
                            "steel": [
                                "carbon steel", "alloy steel", "low alloy steel", "1018", "4140", "4340"
                            ],
                            "kevlar": [
                                "aramid", "para-aramid", "twaron", "ppta"
                            ],
                            "inconel": [
                                "nickel alloy", "alloy 625", "625", "718", "alloy 718", "ni-based superalloy"
                            ],
                        }
                        for k, vals in default_groups.items():
                            if k not in self.synonyms_map:
                                self.synonyms_map[k] = vals

                        # Alias-awareness: allow aliases to act as keys, pointing to the same expansion
                        try:
                            alias_expansions: Dict[str, List[str]] = {}
                            for base_key, aliases in list(self.synonyms_map.items()):
                                # Only build from original base keys, avoid infinite growth by iterating on a snapshot
                                if not isinstance(aliases, list):
                                    continue
                                combo = list(dict.fromkeys(list(aliases) + [base_key]))
                                for alias in aliases:
                                    ak = str(alias).strip().lower()
                                    if not ak:
                                        continue
                                    if ak not in self.synonyms_map and ak not in alias_expansions:
                                        alias_expansions[ak] = combo[:6]  # cap for safety
                            if alias_expansions:
                                self.synonyms_map.update(alias_expansions)
                        except Exception as _e:
                            logger.debug(f"Synonym alias expansion skipped: {_e}")

                        logger.info(f"Loaded {len(self.synonyms_map)} synonym groups from {syn_path}")
            else:
                logger.info(f"Synonyms file not found at {syn_path}; proceeding without synonym expansion")
        except Exception as e:
            logger.warning(f"Failed to load synonyms map (non-critical): {e}")

        # Load test-class synonyms (optional)
        self.testclass_map: Dict[str, Dict[str, List[str]]] = {}
        self.testclass_alias_index: Dict[str, str] = {}
        try:
            cfg = get_config()
            tc_path = cfg.get_absolute_path(Path(cfg.data_path) / "synonyms_testclasses.json")
            if tc_path.exists():
                with open(tc_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for cls_name, spec in data.items():
                        cls_key = str(cls_name).strip()
                        if not cls_key:
                            continue
                        aliases = [str(x).strip() for x in (spec.get('aliases') or []) if str(x).strip()]
                        acronyms = [str(x).strip() for x in (spec.get('acronyms') or []) if str(x).strip()]
                        tokens = [str(x).strip() for x in (spec.get('tokens') or []) if str(x).strip()]
                        self.testclass_map[cls_key] = {
                            'aliases': aliases,
                            'acronyms': acronyms,
                            'tokens': tokens,
                        }
                        for term in aliases + acronyms + tokens:
                            lk = term.lower()
                            if lk and lk not in self.testclass_alias_index:
                                self.testclass_alias_index[lk] = cls_key
                    logger.info(f"Loaded test-class synonyms for {len(self.testclass_map)} classes from {tc_path}")
            else:
                logger.info(f"Test-class synonyms file not found at {tc_path}; proceeding without class hints")
        except Exception as e:
            logger.warning(f"Failed to load test-class synonyms (non-critical): {e}")

    def _expand_query_with_synonyms(self, base_query: str, intent: Dict[str, Any]) -> str:
        """Expand query using loaded synonyms and detected intent.

        Keeps original terms intact; adds a compact list of known aliases to improve recall.
        """
        ql = base_query.lower()
        augmented = [base_query]

        # Intent-driven expansions
        try:
            if intent.get('oxygen_service'):
                for key in ['oxygen', 'cryogenic']:
                    vals = self.synonyms_map.get(key, [])
                    if vals:
                        augmented.append(" ".join(vals[:8]))
                    else:
                        augmented.append("GOX LOX oxygen O2 cryogenic")

            if intent.get('hydrogen_service'):
                for key in ['hydrogen', 'cryogenic']:
                    vals = self.synonyms_map.get(key, [])
                    if vals:
                        augmented.append(" ".join(vals[:8]))
                    else:
                        augmented.append("GH2 LH2 hydrogen H2 cryogenic austenitic")
        except Exception:
            pass

        # Keyword-driven expansions
        try:
            for key, aliases in self.synonyms_map.items():
                if key and key in ql:
                    augmented.append(" ".join(aliases[:6]))
        except Exception:
            pass

        # Expand by detected test classes (add acronyms/tokens)
        try:
            classes = intent.get('test_classes') or []
            for cls in classes[:2]:  # cap to first two classes
                spec = getattr(self, 'testclass_map', {}).get(cls)
                if not spec:
                    continue
                add_parts = []
                acr = spec.get('acronyms') or []
                toks = spec.get('tokens') or []
                if acr:
                    add_parts.append(" ".join(acr[:6]))
                if toks:
                    add_parts.append(" ".join(toks[:6]))
                if add_parts:
                    augmented.append(" ".join(add_parts))
        except Exception:
            pass

        return " ".join(augmented)

    def understand_query_intent(self, query: str) -> Dict[str, Any]:
        """
        AI-powered query intent understanding with oxygen service detection.
        
        Analyzes natural language queries to extract:
        - Material type hints (metals, plastics, composites)
        - Oxygen service requirements
        - Comparison requests
        - Rating requirements (A, B, C)
        
        Args:
            query: Natural language search query
            
        Returns:
            Dict containing query intent analysis
            
        Examples:
            >>> intent = engine.understand_query_intent("aluminum for oxygen service")
            >>> print(intent['oxygen_service'])  # True
            >>> print(intent['material_type_hint'])  # 'aluminum'
            
            >>> intent = engine.understand_query_intent("compare steel vs titanium")
            >>> print(intent['query_type'])  # 'comparison'
            >>> print(intent['materials_to_compare'])  # ['steel', 'titanium']
            
        Compliance: SWE-032 (Data validation), NASA-STD-6001 (Oxygen compatibility)
        """
        query_lower = query.lower()
        intent = {
            'primary_properties': [],
            'expected_forms': [],
            'incompatible_forms': [],
            'confidence': 0.8,
            'query_type': 'general',
            'oxygen_service': False,
            'hydrogen_service': False,
            'rating_required': None,
            'material_type_hint': None,
            'test_classes': []
        }

        # Hybrid intent classification (augments downstream rules)
        try:
            classification = self.intent_classifier.classify(query)
            intent['intent_scores'] = classification.scores
            if classification.evidence:
                intent['intent_evidence'] = classification.evidence
            best_intent, best_score = classification.best()
            if best_intent == 'comparison' and best_score >= 0.55:
                intent['query_type'] = 'comparison'
                intent['confidence'] = max(intent['confidence'], best_score)
            elif best_intent == 'document_lookup' and best_score >= 0.6:
                intent['query_type'] = 'document_lookup'
                intent['confidence'] = max(intent['confidence'], best_score)
            elif best_intent == 'help' and best_score >= 0.5:
                intent['query_type'] = 'help'
                intent['confidence'] = max(intent['confidence'], best_score)
        except Exception as exc:
            logger.debug(f"[INTENT] Hybrid classifier failed: {exc}")

        # Check for oxygen service intent
        for keyword in self.oxygen_keywords:
            if keyword in query_lower:
                intent['oxygen_service'] = True
                intent['query_type'] = 'oxygen_service'
                intent['confidence'] = 0.95
                logger.info(f"[DETECTED] Oxygen service query: '{keyword}'")
                break

        # Check for hydrogen service intent
        for keyword in self.hydrogen_keywords:
            if keyword in query_lower:
                intent['hydrogen_service'] = True
                intent['query_type'] = 'hydrogen_service'
                intent['confidence'] = 0.95
                logger.info(f"[DETECTED] Hydrogen service query: '{keyword}'")
                break
        
        # Check for comparison queries
        comparison_keywords = [
            'compare', 'comparison', 'versus', 'vs', 'vs.', 'against',
            'difference between', 'differences between', 'compare between',
            'side by side', 'side-by-side'
        ]
        for keyword in comparison_keywords:
            if keyword in query_lower:
                intent['query_type'] = 'comparison'
                intent['confidence'] = 0.9
                logger.info(f"[DETECTED] Comparison query: '{keyword}'")
                break
        
        if intent['query_type'] == 'comparison':
            # Extract materials to compare
            cleaned = re.sub(r'\b(compare|comparison|versus|vs|against|difference between|differences|between|side by side)\b', ' vs ', query_lower)
            parts = re.split(r'\s*(vs|to|and)\s*', cleaned)
            materials_to_compare = []
            for part in parts:
                stripped = part.strip()
                if stripped and stripped not in ['vs', 'to', 'and']:
                    materials_to_compare.append(stripped)
            if len(materials_to_compare) >= 2:
                intent['materials_to_compare'] = materials_to_compare[:2]
                logger.info(f"[DETECTED] Materials to compare: {materials_to_compare[0]} vs {materials_to_compare[1]}")
        
        # Check for rating requirements (stop at first match)
        # Use word boundaries to prevent false matches (e.g., "rated for" != "rated f")
        rating_found = False
        for rating, keywords in self.rating_keywords.items():
            for keyword in keywords:
                # Escape special regex chars and add word boundaries
                pattern = r'\b' + re.escape(keyword) + r'\b'
                if re.search(pattern, query_lower):
                    intent['rating_required'] = rating.upper()
                    logger.info(f"[DETECTED] Rating requirement: {rating.upper()}")
                    rating_found = True
                    break
            if rating_found:
                break

        # Regex fallback for rating detection if keywords didn't match
        if not intent['rating_required']:
            rating_patterns = [
                r"have\s+an?\s+\w+\s+rating\s+(?:of\s+)?([a-z])\b",  # "have a toxicity rating of A"
                r"with\s+\w+\s+rating\s+(?:of\s+)?([a-z])\b",        # "with toxicity rating of A"
                r"(?:toxicity|flammability|flash\s+fire|oxygen|hydrogen|shuttle|iss|emu|orion)\s+rating\s+(?:of\s+)?([a-z])\b",  # "[test type] rating of A"
                r"rating\s+(?:of\s+)?([a-z])\b",                     # "rating of A" or "rating A"
                r"\b([a-z])\s+rating\b",                             # "A rating"
                r"\brating\s*[:\-]\s*([a-z])\b",                     # "rating: A" or "rating - A"
            ]
            for pattern in rating_patterns:
                match = re.search(pattern, query_lower)
                if match:
                    intent['rating_required'] = match.group(1).upper()
                    logger.info(f"[DETECTED] Rating requirement (regex fallback): {intent['rating_required']}")
                    break

        # Detect material type hints with hierarchical matching
        # Prefer specific materials before broad categories to avoid false positives
        material_cats = {  # Broad categories; Compliance: SWE-032 (configurable for validation)
            'aluminum': ['aluminum', 'aluminium', 'al', 'al alloy'],
            'steel': ['steel', 'stainless', 'ss', 'carbon steel'],
            'titanium': ['titanium', 'ti'],
            'plastics': ['plastic', 'plastics', 'polymer', 'polymers'],
            'composite': ['composite', 'carbon fiber', 'fiberglass'],
            'metals': ['metal', 'metals', 'metallic', 'alloy', 'alloys']
        }
        material_subs = {  # Subtypes under categories
            'aluminum alloys': ['aluminum alloys', 'aluminium alloys', 'al alloy', 'al alloys'],
            'stainless steel': ['stainless steel', 'stainless', 'ss'],
            'carbon steel': ['carbon steel', 'carbon'],
            'peek': ['peek', 'polyetheretherketone'],
            'ptfe': ['ptfe', 'teflon', 'polytetrafluoroethylene'],
            'carbon fiber': ['carbon fiber', 'carbon fibre', 'cfrp'],
            # Silicone elastomers - fluorosilicone must be matched before silicone
            'fluorosilicone': ['fluorosilicone', 'fluorosilicones', 'fvmq'],
            'silicone': ['silicone', 'silicones', 'vmq']
        }
        
        # Check for grouping/organization requests first (these override material filtering)
        grouping_phrases = [
            'broken out by', 'grouped by', 'organized by', 'sorted by', 
            'breakdown by', 'group by', 'organize by', 'sort by',
            'categorized by', 'classified by', 'divided by'
        ]
        
        for phrase in grouping_phrases:
            if phrase in query_lower:
                intent['grouping_requested'] = True
                # Extract what to group by
                if 'class' in query_lower or 'type' in query_lower:
                    intent['group_by'] = 'material_type'
                elif 'subtype' in query_lower or 'category' in query_lower:
                    intent['group_by'] = 'material_subtype'
                else:
                    intent['group_by'] = 'material_type'  # Default
                logger.info(f"[SEARCH] Detected grouping request: {phrase} -> group by {intent['group_by']}")
                break
        
        # Only do material filtering if NOT requesting grouping
        if not intent.get('grouping_requested', False):
            # Match categories (use word boundaries for short tokens to avoid false matches)
            for mat_type, keywords in material_cats.items():
                for keyword in keywords:
                    # Use word boundary matching to avoid 'ss' matching in 'class'
                    if len(keyword) <= 2:  # Short keywords like 'ss', 'al', 'ti'
                        pattern = rf'\b{re.escape(keyword)}\b'
                        if re.search(pattern, query_lower):
                            intent['material_type_hint'] = mat_type
                            break
                    else:  # Longer keywords can use simple substring matching
                        if keyword in query_lower:
                            intent['material_type_hint'] = mat_type
                            break
                # Only break if we actually set a non-None hint
                if intent.get('material_type_hint') is not None:
                    break
            
            # Match specific subtypes (only if no grouping requested)
            for sub_type, keywords in material_subs.items():
                for keyword in keywords:
                    # Use word boundary matching for short keywords
                    if len(keyword) <= 2:
                        pattern = rf'\b{re.escape(keyword)}\b'
                        if re.search(pattern, query_lower):
                            intent['material_subtype_hint'] = sub_type
                            break
                    else:
                        if keyword in query_lower:
                            intent['material_subtype_hint'] = sub_type
                            break
                if 'material_subtype_hint' in intent:
                    break
        
        # Detect test class by synonyms/acronyms/tokens
        try:
            matched_classes: List[str] = []
            alias_index = getattr(self, 'testclass_alias_index', {}) or {}
            if alias_index:
                for alias, cls_name in alias_index.items():
                    if len(alias) <= 4:
                        pattern = rf"\b{re.escape(alias)}\b"
                        if re.search(pattern, query_lower):
                            matched_classes.append(cls_name)
                    else:
                        if alias in query_lower:
                            matched_classes.append(cls_name)
            if matched_classes:
                # Deduplicate preserve order
                seen = set()
                ordered = []
                for c in matched_classes:
                    if c not in seen:
                        seen.add(c)
                        ordered.append(c)
                intent['test_classes'] = ordered
                logger.info(f"[DETECTED] Test class hint(s): {ordered}")
        except Exception:
            pass

        return intent
    
    def index_materials(self, materials: List[Material]) -> None:
        """
        Index materials - NOT NEEDED with FAISS as it's already indexed.
        
        FAISS vector database is pre-built with 9,996 materials and ready to use.
        This method is kept for API compatibility but does nothing.
        
        Args:
            materials: List of Material objects (stored but not indexed)
            
        Examples:
            >>> materials = load_materials_from_json("data/materials.json")
            >>> engine.index_materials(materials)
            >>> # Materials are stored but FAISS index is pre-built
            
        Compliance: SWE-055 (Performance optimization)
        """
        logger.info(f"[SUCCESS] Using pre-indexed FAISS with materials ready for search")
        logger.info(f"   - FAISS contains 9,996+ materials with GPU acceleration")
        self.materials = materials

    @track_performance_decorator(operation_name="semantic_search", log_args=True)
    def search(
        self, 
        query: str, 
        top_k: Optional[int] = None, 
        min_similarity: Optional[float] = None
    ) -> List[Dict]:
        """Perform GPU-accelerated semantic search using FAISS.
        
        Args:
            query: Natural language search query
            top_k: Number of top results to return
            min_similarity: Minimum similarity score threshold
            
        Returns:
            List of search results with metadata
            
        Raises:
            ValidationError: If query or parameters are invalid
            FAISSIndexError: If FAISS operations fail
            PerformanceError: If search exceeds time limits
            
        Examples:
            >>> results = await engine.search("aluminum sheet")
            >>> results = await engine.search("oxygen compatible", top_k=10)
            
        Compliance: SWE-055 (async operations), SWE-032 (validation)
        """
        start_time = datetime.utcnow()
        
        # Validate inputs
        if not query or not query.strip():
            raise_safety_error(
                ValidationError,
                "Search query cannot be empty",
                field_errors={"query": ["Query is required"]}
            )
        
        if len(query) > 1000:
            raise_safety_error(
                ValidationError,
                f"Query too long: {len(query)} characters (max 1000)",
                field_errors={"query": ["Query exceeds maximum length"]}
            )
        
        # Load configuration defaults
        try:
            config = get_config()
            if top_k is None:
                top_k = config.default_search_limit
            if min_similarity is None:
                min_similarity = config.min_similarity_score
        except Exception as e:
            logger.warning(f"Failed to load config defaults, using hardcoded: {e}")
            top_k = top_k or 25
            min_similarity = min_similarity or 0.1
            
        # Validate parameters
        if top_k <= 0:
            raise_safety_error(
                ValidationError,
                f"Invalid top_k value: {top_k}",
                field_errors={"top_k": ["Must be positive integer"]}
            )
            
        # Cap top_k to max limit
        max_limit = getattr(config, 'max_search_limit', 100)
        if top_k > max_limit:
            logger.warning(f"Requested top_k ({top_k}) exceeds max limit ({max_limit}), capping to max")
            top_k = max_limit
        
        # Understand query intent
        try:
            query_intent = self.understand_query_intent(query)
            logger.info(f"[SEARCH] Search query: '{query}'")
            logger.info(f"[DETECTED] Query intent: {query_intent}")
        except Exception as e:
            logger.warning(f"Query intent understanding failed: {e}")
            query_intent = {"query_type": "general", "confidence": 0.5}
        
        # Parse query with NLP parser to extract structured filters
        property_filters = None
        try:
            if self.nlp_parser:
                with track_performance("nlp_parsing"):
                    nlp_result = self.nlp_parser.parse(query)
                    if isinstance(nlp_result, dict):
                        structured_intent = nlp_result.get("structured_intent", {})
                        property_filters = structured_intent.get("property_filters", {})
                        if property_filters:
                            logger.info(f"[DETECTED] NLP extracted filters: {property_filters}")
                    else:
                        logger.warning(f"NLP parser returned unexpected type: {type(nlp_result)}")
        except Exception as e:
            logger.warning(f"NLP parsing failed (non-critical): {e}")
        
        if not self.vector_store:
            raise_safety_error(
                FAISSIndexError,
                "Vector store not initialized",
                index_operation="search",
                details={"query": query[:50]}
            )
        
        try:
            # Build an augmented query using domain synonyms and intent
            augmented_query = self._expand_query_with_synonyms(query, query_intent)

            # Determine how many results to fetch from FAISS
            # Start with requested top_k; expand candidate pool for filtered/complex intents
            faiss_top_k = top_k
            if query_intent.get('material_type_hint') or query_intent.get('material_subtype_hint') or query_intent.get('rating_required'):
                faiss_top_k = min(top_k * 10, 250)
                logger.info(f"[SEARCH] Intent filters detected, fetching {faiss_top_k} results from FAISS for filtering")
            # Hydrogen-specific: widen candidate pool so stainless/nickel alloys are represented
            if query_intent.get('hydrogen_service'):
                widened = min(max(top_k * 20, faiss_top_k), 500)
                if widened != faiss_top_k:
                    faiss_top_k = widened
                    logger.info(f"[SEARCH][H2] Hydrogen intent detected, fetching {faiss_top_k} FAISS candidates")

            # Main FAISS search (no hard filters at vector stage)
            with track_performance("faiss_search"):
                faiss_results = self.vector_store.search(
                    query=augmented_query,
                    top_k=faiss_top_k,
                    filters=None
                )
            
            logger.info(f"[SEARCH] FAISS returned {len(faiss_results)} results")

            # If hydrogen service: inject BOK-recommended materials via secondary lookups
            try:
                if query_intent.get('hydrogen_service') and getattr(self, 'h2_engine', None):
                    bok_names = self.h2_engine.get_recommended_materials_from_bok(
                        "recommended materials for hydrogen service cryogenic"
                    ) or []
                    # Prefer austenitic stainless + nickel alloy seeds
                    prefer = [
                        n for n in bok_names
                        if any(t in n.lower() for t in ("316", "321", "304", "inconel", "625", "austenitic", "stainless"))
                    ]
                    # Ensure a few strong defaults in case parsing misses
                    for fallback in ["SS 316", "SS 321", "INCONEL 625"]:
                        if fallback not in prefer:
                            prefer.append(fallback)
                    # Cap seeds to control latency
                    seeds = prefer[:6]

                    injected: List[Dict[str, Any]] = []
                    for seed in seeds:
                        try:
                            q = f"{seed} hydrogen cryogenic"
                            hits = self.vector_store.search(q, top_k=3, filters=None) or []
                            for h in hits:
                                # Tag for provenance and give slight pre-boost before later re-ranking
                                h["score"] = float(h.get("score", 0.0) or 0.0) + 0.10
                                h["provenance"] = "H2_BOK_INJECTED"
                                injected.append(h)
                        except Exception:
                            continue

                    if injected:
                        before = len(faiss_results)
                        faiss_results.extend(injected)
                        logger.info(f"[H2 BOK] Injected {len(injected)} seed hits (FAISS pool {before} -> {len(faiss_results)})")
            except Exception as e:
                logger.warning(f"[H2 BOK] Injection step skipped: {e}")

            # Fluorosilicone materials: inject ALL composition=833 materials from database
            # This ensures trade-named materials (DOW CORNING 3452, L677-70, etc.) are included
            try:
                subtype = query_intent.get('material_subtype_hint', '').lower()
                if subtype == 'fluorosilicone' or 'fluorosilicone' in query.lower():
                    fluoro_results = self._get_fluorosilicone_materials_from_db()
                    if fluoro_results:
                        before = len(faiss_results)
                        faiss_results.extend(fluoro_results)
                        logger.info(f"[FLUORO] Injected {len(fluoro_results)} fluorosilicone materials from DB (pool {before} -> {len(faiss_results)})")
            except Exception as e:
                logger.warning(f"[FLUORO] Fluorosilicone injection failed (non-critical): {e}")

            # Handle comparison queries
            if query_intent['query_type'] == 'comparison' and 'materials_to_compare' in query_intent:
                faiss_results = self._handle_comparison_search(
                    query_intent['materials_to_compare'],
                    property_filters
                )
            
            # Lightweight boosting prior to conversion
            try:
                # Extract key tokens from original query for exact matching
                import re as _re
                q_lower = query.lower()
                q_tokens_orig = [t for t in _re.split(r"[^a-z0-9+\.\-]+", q_lower) if len(t) >= 2]

                # Precompute BM25-lite style token weights from the augmented query
                q_weights: Dict[str, float] = {}
                try:
                    aug_ql = (augmented_query or query).lower()
                    q_tokens = [t for t in _re.split(r"[^a-z0-9+\.\-]+", aug_ql) if len(t) >= 2]
                    # Rare/important tokens get a bit more weight
                    rare_boost = {
                        'tml': 1.6, 'cvcm': 1.6, 'e595': 1.6, 'astm': 1.2, 'ul94': 1.5, 'loi': 1.4,
                        'gox': 1.6, 'lox': 1.6, 'nasa-std-6001': 1.7, '6001': 1.2, 'mmod': 1.4,
                    }
                    for tok in q_tokens:
                        base = 1.0
                        wt = rare_boost.get(tok, base)
                        # Accumulate to favor repeated presence
                        q_weights[tok] = q_weights.get(tok, 0.0) + wt
                    # Normalize to small magnitudes
                    s = sum(q_weights.values()) or 1.0
                    for k in list(q_weights.keys()):
                        q_weights[k] = q_weights[k] / s
                except Exception:
                    q_weights = {}
                boosted: List[Dict[str, Any]] = []
                for r in faiss_results:
                    score = float(r.get('score', 0.0) or 0.0)
                    orig = r.get('original_material', {}) if isinstance(r, dict) else {}
                    payload = orig.get('payload', {}) if isinstance(orig, dict) else {}

                    # Get material name for exact match boosting
                    material_name = (r.get('name', '') or orig.get('name', '') or orig.get('designation', '')).lower()

                    text_blob = ''
                    try:
                        text_blob = json.dumps(payload).lower() if payload else ''
                    except Exception:
                        text_blob = ''

                    # EXACT MATCH BOOSTING: Heavily boost if material designation contains exact query tokens
                    # This ensures "304 stainless steel" ranks 304 above 316
                    exact_match_boost = 0.0
                    for tok in q_tokens_orig:
                        # For numeric tokens (like "304", "316", "6061"), require exact match
                        if tok.isdigit() or _re.match(r'^[0-9]+[a-z]?$', tok):
                            # Use word boundary for exact match
                            if _re.search(rf'\b{_re.escape(tok)}\b', material_name):
                                exact_match_boost += 0.15  # Strong boost for exact designation match
                        # For text tokens, check if present
                        elif len(tok) >= 3 and tok in material_name:
                            exact_match_boost += 0.05

                    score += exact_match_boost

                    # Oxygen intent: boost rows mentioning GOX/LOX/OXYGEN
                    if query_intent.get('oxygen_service'):
                        if any(tok in text_blob for tok in ('gox', 'lox', 'oxygen')):
                            score += 0.05
                        # Small extra boost for high pressure (>=3000 psi) if present
                        try:
                            import re as _re
                            m = _re.search(r"(\b|_)(psi|press|pressure)[a-z_]*\":?\s*([0-9.,]+)", text_blob)
                            if m:
                                val = float(m.group(3).replace(',', ''))
                                if val >= 3000:
                                    score += 0.03
                        except Exception:
                            pass

                    # Hydrazine queries: boost explicit mentions
                    if 'hydrazine' in (query.lower()):
                        if 'hydrazine' in text_blob:
                            score += 0.05

                    # Cryogenic queries: boost LN2/cryo/low-temp cues
                    ql = query.lower()
                    if any(tok in ql for tok in ('cryogenic', 'cryo', 'ln2', '-320', 'low temperature', '-196c', '77k')):
                        if any(tok in text_blob for tok in ('cryogenic', 'cryo', 'ln2', 'liquid nitrogen', '-320', '-196c', '77k', 'low-temperature')):
                            score += 0.04

                    # Vacuum/outgassing: ASTM E595, TML/CVCM
                    if any(tok in ql for tok in ('vacuum', 'e595', 'outgassing', 'tml', 'cvcm')):
                        if any(tok in text_blob for tok in ('vacuum', 'astm e595', 'e595', 'tml', 'cvcm', 'outgassing')):
                            score += 0.04

                    # NASA-STD-6001 oxygen flammability standard
                    if any(tok in ql for tok in ('nasa-std-6001', '6001')):
                        if any(tok in text_blob for tok in ('nasa-std-6001', '6001')):
                            score += 0.03

                    # Hydrogen service cues (GH2/LH2)
                    if any(tok in ql for tok in ('hydrogen', 'h2', 'gh2', 'lh2')):
                        if any(tok in text_blob for tok in ('hydrogen', 'h2', 'gh2', 'lh2', 'gaseous hydrogen', 'liquid hydrogen')):
                            score += 0.04

                    # Rating preference when user implies A-rated
                    try:
                        if query_intent.get('rating_required', '').upper() == 'A' or any(x in ql for x in ('a rated', 'class a', 'a-rated')):
                            # Heuristic: look for rating fields with 'a'
                            if re.search(r"rating\s*[:=]\s*\"?a\b", text_blob) or re.search(r"\bclass\s*a\b", text_blob):
                                score += 0.02
                    except Exception:
                        pass

                    # BM25-lite token overlap boosting (cap total addition)
                    try:
                        if q_weights and text_blob:
                            overlap = 0.0
                            for tok, wt in q_weights.items():
                                if tok and tok in text_blob:
                                    overlap += wt
                            # Scale and cap the contribution
                            score += min(0.08, overlap * 0.6)
                    except Exception:
                        pass

                    r['score'] = score
                    boosted.append(r)
                faiss_results = sorted(boosted, key=lambda x: x.get('score', 0.0), reverse=True)
            except Exception:
                pass

            # Convert FAISS results to expected format
            results = self._convert_faiss_results(faiss_results)

            # PHASE 1 FIX: Enrich results with material types from FAISS metadata
            # Do this BEFORE H2 policy so types are preserved through reformatting
            try:
                # Use absolute import to avoid relative import issues
                import sys
                from pathlib import Path
                scripts_path = Path(__file__).parent.parent.parent / "scripts"
                if str(scripts_path) not in sys.path:
                    sys.path.insert(0, str(scripts_path))
                from load_material_types_from_faiss import enrich_search_results_with_types
                results = enrich_search_results_with_types(results)
                logger.info(f"[ENRICH] Added material type classifications from FAISS metadata ({len(results)} results)")

                # TRACE: Log ONLY problematic materials (polymers, non-metals)
                polymer_keywords = ['NYLATRON', 'MICARTA', 'PELLETHANE', 'PEBAX', 'HOSTAPOR', 'HOSTYREN', 'HOSTALIT', 'VALOX', 'LOCTITE']
                for i, r in enumerate(results[:50]):
                    orig = r.get('original_material', {})
                    mat = r.get('material', {})
                    desig = mat.get('designation', orig.get('designation', 'Unknown'))

                    # Only log if it matches polymer keywords
                    if any(kw in desig.upper() for kw in polymer_keywords):
                        mk = orig.get('material_key')
                        tk_orig = orig.get('material_type_key')
                        tn_orig = orig.get('material_type_name')
                        tk_mat = mat.get('material_type_key')

                        logger.debug(f"[ENRICH POLYMER] {desig[:50]}")
                        logger.debug(f"[ENRICH POLYMER]   material_key: {mk}")
                        logger.debug(f"[ENRICH POLYMER]   original_material.type_key: {tk_orig} ({tn_orig})")
                        logger.debug(f"[ENRICH POLYMER]   material.type_key: {tk_mat}")
            except Exception as enrich_error:
                logger.warning(f"[H2 ENRICH] Material type enrichment failed (non-critical): {enrich_error}")
                import traceback
                logger.debug(f"[H2 ENRICH] Traceback: {traceback.format_exc()}")

            # SMART PRE-FILTER: For hydrogen metals queries, remove non-metals BEFORE H2 policy
            # This catches polymers immediately based on material_type_key
            if query_intent.get('hydrogen_service') and query_intent.get('material_type_hint') == 'metals':
                pre_filter_count = len(results)
                filtered_results = []
                for result in results:
                    orig = result.get('original_material', {})
                    material_type_key = orig.get('material_type_key')
                    designation = (result.get('material', {}).get('designation') or '').lower()

                    # If it's a metal (235) or unknown (None), keep it
                    if material_type_key == 235:
                        filtered_results.append(result)
                    # If it's a known non-metal type, exclude it immediately
                    elif material_type_key in [239, 229, 231, 232, 233, 723]:
                        logger.debug(f"[SMART FILTER] Excluding {designation} - type_key={material_type_key} is non-metal")
                    # If unknown type, use simple keyword check
                    elif material_type_key is None or material_type_key == -1 or material_type_key == 1:
                        # Check if it has ANY metal indicator
                        metal_indicators = ['steel', 'stainless', 'cres', 'aluminum', 'aluminium', 'titanium',
                                          'inconel', 'monel', 'hastelloy', 'nickel', 'copper', 'bronze', 'brass',
                                          'magnesium', 'alloy', 'metal']
                        if any(indicator in designation for indicator in metal_indicators):
                            filtered_results.append(result)
                        else:
                            logger.debug(f"[SMART FILTER] Excluding {designation} - no metal keywords (type_key={material_type_key})")
                    else:
                        # Unknown type_key, keep it to be safe
                        filtered_results.append(result)

                results = filtered_results
                logger.info(f"[SMART FILTER] Pre-filtered for hydrogen metals: {pre_filter_count} -> {len(results)} results")

            # Apply hydrogen compatibility policy-gated ranking if hydrogen service detected
            if query_intent.get('hydrogen_service'):
                try:
                    # DEBUG: Check if MICARTA is in results BEFORE H2 policy
                    for r in results:
                        designation = r.get('material', {}).get('designation', '')
                        if 'MICARTA' in designation.upper() or 'PELLETHANE' in designation.upper():
                            logger.debug(f"[DEBUG BEFORE H2] {designation[:50]} IS IN RESULTS")
                            logger.debug(f"[DEBUG BEFORE H2]   type_key={r.get('original_material', {}).get('material_type_key')}")

                    # Import H2PolicyEngine
                    from mira.core.h2_policy_engine import get_h2_policy_engine, SafetyClass

                    # Use pre-loaded H2 engine
                    h2_engine = getattr(self, 'h2_engine', None)

                    if h2_engine:
                        logger.info("[H2 POLICY] Applying evidence-based H2 policy ranking")

                        # FRAN'S FIX #3: Store enriched results with normalized int keys for later lookup
                        pre_h2_enriched_results = {}
                        for r in results:
                            mk_raw = r.get('original_material', {}).get('material_key')
                            try:
                                mk = int(mk_raw) if mk_raw is not None else None
                                if mk is not None:
                                    pre_h2_enriched_results[mk] = r
                                    # DEBUG: Log enriched type for polymers
                                    orig = r.get('original_material', {})
                                    designation = r.get('material', {}).get('designation', '')
                                    if 'MICARTA' in designation.upper() or 'PELLETHANE' in designation.upper():
                                        logger.debug(f"[DEBUG PRE-H2] {designation[:50]}")
                                        logger.debug(f"[DEBUG PRE-H2]   material_key={mk}")
                                        logger.debug(f"[DEBUG PRE-H2]   type_key={orig.get('material_type_key')}")
                                        logger.debug(f"[DEBUG PRE-H2]   type_name={orig.get('material_type_name')}")
                            except (TypeError, ValueError):
                                continue

                        # Initialize policy engine (Class A = human-rated, highest authority weight)
                        policy_engine = get_h2_policy_engine(
                            h2_engine=h2_engine,
                            safety_class=SafetyClass.CLASS_A
                        )

                        # Apply policy gate (filters incompatible materials)
                        admitted, excluded = policy_engine.apply_policy_gate(results)
                        logger.info(f"[H2 GATE] Admitted {len(admitted)} materials, excluded {len(excluded)}")

                        # Rank by evidence-weighted score
                        ranked = policy_engine.rank_materials(admitted)

                        # Format results with full traceability
                        structured_results = policy_engine.format_results_with_evidence(ranked, excluded)

                        # Store structured results for API consumers
                        # But flatten for backward compatibility with current UI
                        all_materials = (
                            structured_results['h2_bok_verified'] +
                            structured_results['other_candidates']
                        )

                        # Convert back to search result format
                        results = []
                        for mat in all_materials:
                            # ENRICHMENT FIX: Find MaterialEvidence object to access original enriched result
                            evidence_obj = next(
                                (r for r in admitted if r.material_key == mat['material_key']),
                                None
                            )

                            # Extract enriched material_type fields from the stored original_result
                            material_type_key = None
                            material_type_name = None

                            if evidence_obj and evidence_obj.original_result:
                                # evidence_obj.original_result IS the enriched result dict from Phase 1
                                # It already has original_material.material_type_key set
                                orig = evidence_obj.original_result.get('original_material', {})
                                material_type_key = orig.get('material_type_key')
                                material_type_name = orig.get('material_type_name')
                                logger.debug(f"[ENRICH RESTORE] {mat['material_name'][:50]} - type_key={material_type_key} ({material_type_name})")

                            # Build result dict with evidence
                            result = {
                                'material': {
                                    'material_id': mat['material_code'] or 'N/A',
                                    'name': mat['material_name'] or 'Unknown',
                                    'designation': mat['material_name'] or 'Unknown',
                                    'material_code': mat['material_code'] or 'N/A'
                                },
                                'original_material': {
                                    'material_key': mat['material_key'],
                                    'name': mat['material_name'],
                                    'material_code': mat['material_code'],
                                    # ENRICHMENT FIX: Get material_type from stored original_result
                                    'material_type_key': material_type_key,
                                    'material_type_name': material_type_name
                                },
                                'similarity_score': mat['final_score'],
                                'h2_compatibility': mat['h2_compatibility'],
                                'h2_score': mat['evidence']['authority_score'],
                                'has_h2_test_data': mat['h2_test_count'] > 0,
                                'h2_info': {
                                    'h2_test_count': mat['h2_test_count'],
                                    'evidence_breakdown': mat['evidence'],
                                    'citations': mat['citations'],
                                    'warnings': mat['warnings']
                                }
                            }

                            # --- FINAL GUARDRAIL: enforce metals-only when intent demands it
                            # BoundState Rule: Use validated material_type_key ONLY. No string matching.
                            # If type is unknown, exclude (do not guess from name).
                            if query_intent.get("material_type_hint") in ("metals", "metal"):
                                tkey = result["original_material"].get("material_type_key")
                                designation = result['material'].get('designation', 'Unknown')
                                logger.debug(f"[GUARD CHECK] {designation[:60]} - type_key={tkey}")
                                if not self._is_metal_from_validated_type(result["original_material"]):
                                    logger.debug(f"[GUARD] ✗ EXCLUDING {designation[:60]} - type_key={tkey} is not validated Metal (235)")
                                    continue
                                else:
                                    logger.debug(f"[GUARD] ✓ KEEPING {designation[:60]} - type_key=235 (Metal)")
                            results.append(result)

                        # Add metadata about policy-gated ranking
                        if results:
                            results[0]['_h2_policy_applied'] = True
                            results[0]['_h2_structured_results'] = structured_results

                        logger.info(f"[H2 POLICY] Re-ranked {len(results)} results using evidence-based scoring")
                        logger.info(f"[H2 POLICY] H2 BOK Verified: {len(structured_results['h2_bok_verified'])}, "
                                  f"Other Candidates: {len(structured_results['other_candidates'])}, "
                                  f"Excluded: {len(structured_results['excluded_materials'])}")
                    else:
                        logger.warning("[H2 POLICY] H2 engine not available, skipping policy ranking")
                except Exception as e:
                    logger.warning(f"[H2 POLICY] Policy ranking failed (non-critical): {e}")
                    import traceback
                    logger.debug(f"[H2 POLICY] Traceback: {traceback.format_exc()}")

            # Apply post-filtering based on detected intent
            if query_intent.get('material_type_hint') or query_intent.get('material_subtype_hint') or query_intent.get('rating_required'):
                if query_intent.get('hydrogen_service'):
                    # For H2 queries: Use smart category-based filtering instead of material_type_key
                    # This preserves H2-ranked materials while still respecting user's material type request
                    results = self._apply_h2_category_filter(results, query_intent)
                else:
                    # For non-H2 queries: Apply standard filters
                    results = self._apply_intent_filters(results, query_intent)
                # Take only top_k after filtering
                results = results[:top_k]

            # Check performance
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.last_search_time = elapsed_ms
            
            if elapsed_ms > 5000:  # 5 second threshold
                logger.warning(f"Slow search detected: {elapsed_ms:.0f}ms for query: {query[:50]}")
                if elapsed_ms > 10000:  # 10 second hard limit
                    raise_safety_error(
                        PerformanceError,
                        f"Search exceeded time limit: {elapsed_ms:.0f}ms",
                        operation="semantic_search",
                        elapsed_time=elapsed_ms/1000,
                        threshold=10.0
                    )
            
            return results
            
        except (FAISSIndexError, PerformanceError, ValidationError):
            # Re-raise our custom errors
            raise
        except Exception as e:
            logger.error(f"FAISS search failed: {e}")
            # Try fallback keyword search
            try:
                logger.info("Attempting fallback keyword search")
                return self._keyword_search(query, query_intent, top_k)
            except Exception as fallback_error:
                logger.error(f"Fallback search also failed: {fallback_error}")
                raise_safety_error(
                    FAISSIndexError,
                    f"Search operation failed: {e}",
                    index_operation="search",
                    details={"query": query[:50], "fallback_error": str(fallback_error)}
                )
    
    def _handle_comparison_search(self, materials_to_compare: List[str], property_filters: Optional[Dict]) -> List[Dict]:
        """Handle material comparison searches.
        
        Args:
            materials_to_compare: List of material names to compare
            property_filters: Optional property filters
            
        Returns:
            Combined search results for comparison
        """
        if len(materials_to_compare) < 2:
            logger.warning(f"Comparison search requires 2 materials, got {len(materials_to_compare)}")
            return []
            
        mat1, mat2 = materials_to_compare[:2]
        logger.info(f"[COMPARISON] Performing separate searches for {mat1} and {mat2}")
        
        # Normalize material names for better matching
        from mira.api.main import normalize_material_identifier
        mat1_query = normalize_material_identifier(mat1)[0] if normalize_material_identifier(mat1) else mat1
        mat2_query = normalize_material_identifier(mat2)[0] if normalize_material_identifier(mat2) else mat2
        logger.info(f"[COMPARISON] Normalized queries: {mat1_query} and {mat2_query}")
        
        try:
            mat1_results = self.vector_store.search(mat1_query, top_k=10, filters=property_filters)
            mat2_results = self.vector_store.search(mat2_query, top_k=10, filters=property_filters)
            
            # Get available forms from mat1 results
            mat1_forms = {r.get('form', '').lower() for r in mat1_results if r.get('form')}
            if mat1_forms:
                logger.info(f"[COMPARISON] Mat1 forms: {mat1_forms}")
                # Filter mat2 to matching forms
                mat2_filtered = [
                    r for r in mat2_results 
                    if r.get('form', '').lower() in mat1_forms
                ]
                if mat2_filtered:
                    mat2_results = sorted(mat2_filtered, key=lambda x: x['score'], reverse=True)
                    logger.info(f"[COMPARISON] Found {len(mat2_results)} matching forms for mat2")
                else:
                    logger.warning("[COMPARISON] No matching forms found, using all mat2 results")
            
            # Combine top results (take top 1 for each for comparison)
            return mat1_results[:1] + mat2_results[:1]
            
        except Exception as e:
            logger.error(f"Comparison search failed: {e}")
            return []
    
    def _convert_faiss_results(self, faiss_results: List[Dict]) -> List[Dict]:
        """
        Convert FAISS results to standardized format with enriched metadata.

        Args:
            faiss_results: Raw results from FAISS vector search

        Returns:
            List of formatted material dictionaries with similarity scores

        Examples:
            >>> faiss_results = [{"id": "MAT-001", "name": "Al 6061", "score": 0.95}]
            >>> formatted = engine._convert_faiss_results(faiss_results)
            >>> print(formatted[0]['similarity_score'])  # 0.95
            >>> print(formatted[0]['material']['designation'])  # "Al 6061"

        Compliance: SWE-049 (Standardized response models), SWE-032 (Data validation)
        """
        # First pass: collect all results by material_id, keeping the best score for each
        material_results = {}  # material_id -> best result for that material

        for i, result in enumerate(faiss_results):
            # Use original material data from FAISS result
            original_material = result.get("original_material", {}) or {}

            # FRAN'S FIX #2: Normalize and inject material_key into original_material if present elsewhere
            mk_raw = (original_material.get("material_key")
                      or result.get("material_key")
                      or result.get("MaterialKey")
                      or (result.get("payload") or {}).get("material_key"))
            try:
                if mk_raw is not None:
                    normalized_mk = int(mk_raw)
                    if "material_key" not in original_material:
                        original_material["material_key"] = normalized_mk
                        logger.debug(f"[CONVERT] Injected material_key={normalized_mk} into original_material for result {i}")
            except (TypeError, ValueError) as e:
                logger.debug(f"[CONVERT] Failed to normalize material_key={mk_raw} for result {i}: {e}")

            # Preserve payload for later policy/rating checks
            if "payload" not in original_material and isinstance(result.get("payload"), dict):
                original_material["payload"] = result["payload"]

            # Create field mapping for case normalization
            field_mappings = {
                'MaterialID': 'material_id',
                'material_id': 'material_id',
                'Name': 'name',
                'name': 'name',
                'Designation': 'designation',
                'designation': 'designation',
                'Composition': 'composition',
                'composition': 'composition',
                'Category': 'category',
                'category': 'category',
                'MaterialType': 'material_type',
                'material_type': 'material_type',
                'MaterialSubtype': 'material_subtype',
                'material_subtype': 'material_subtype',
                'Manufacturer': 'manufacturer',
                'manufacturer': 'manufacturer',
                'Specification': 'specification',
                'specification': 'specification',
                'Form': 'form',
                'form': 'form',
                'TestReports': 'test_reports',
                'test_reports': 'test_reports'
            }
            
            # Build the material dict carefully to avoid overwrites
            material_dict = {
                "material_id": result["id"],  # This should be the correct ID
                "name": result["name"],  # Also include name field
                "designation": result["name"],
                "composition": result.get("description", ""),
                "category": result.get("category", ""),
                "material_type": None,  # Will be populated from original_material
                "material_subtype": None,  # Will be populated from original_material
                "manufacturer": result.get("manufacturer", ""),
                "specification": result.get("specification", ""),
            }
            
            # Add any additional fields from original_material that aren't already set
            # Apply field mapping to normalize field names
            for key, value in original_material.items():
                normalized_key = field_mappings.get(key, key)
                if normalized_key not in material_dict:
                    material_dict[normalized_key] = value
            
            # Override category with classified type to ensure accuracy
            material_dict['category'] = self.vector_store.classify_material_type(material_dict['designation'])
            
            # Get material ID for grouping
            mid = material_dict.get("material_id")
            if not mid:
                continue

            # Keep the best scoring result for each material
            current_score = result["score"]
            if mid not in material_results or current_score > material_results[mid]["similarity_score"]:
                material_results[mid] = {
                    "material": material_dict,
                    "similarity_score": current_score,
                    "original_material": original_material if isinstance(original_material, dict) else {}
                }

        # Second pass: sort by score and return results
        results = sorted(material_results.values(), key=lambda x: x["similarity_score"], reverse=True)

        # Debug logging for top results
        for i, result in enumerate(results[:3]):
            logger.info(f"[SEARCH] Result {i}: ID={result['material']['material_id']}, Name={result['material']['name']}, Score={result['similarity_score']:.4f}")

        return results

    def _apply_intent_filters(self, results: List[Dict], query_intent: Dict) -> List[Dict]:
        """
        Apply post-filtering based on query intent (material type, rating, test class).

        Args:
            results: Search results from FAISS
            query_intent: Detected query intent

        Returns:
            Filtered results matching intent
        """
        filtered = []

        material_type_hint = query_intent.get('material_type_hint')
        rating_required = query_intent.get('rating_required')

        for result in results:
            material = result.get('material', {})
            original = result.get('original_material', {})
            designation = (material.get('designation') or '').lower()
            category = (material.get('category') or '').lower()

            # Get official material type from metadata (added during FAISS index build)
            material_type_key = original.get('material_type_key')
            material_type_name = (original.get('material_type_name') or '').lower()

            # Filter by material type if specified (use official classification as top-level filter)
            if material_type_hint:
                hint_lower = material_type_hint.lower()

                # Map user intent to official MAPTIS material types
                # Type 235 = Metal, Type 239 = Polymer, Type 723 = Elastomer, Type 231 = Coating
                if hint_lower == 'steel' or hint_lower == 'aluminum' or hint_lower == 'titanium' or hint_lower == 'metals':
                    # Filter by Metal type (235)
                    is_metal = (material_type_key == 235)

                    if not is_metal:
                        logger.debug(f"[FILTER] Excluding {designation} - not classified as Metal (type={material_type_key})")
                        continue

                    # Further refine by specific metal type using designation keywords
                    if hint_lower == 'steel' and 'steel' not in designation:
                        logger.debug(f"[FILTER] Excluding {designation} - Metal but not steel")
                        continue
                    elif hint_lower == 'aluminum' and not any(x in designation for x in ['aluminum', 'aluminium', 'alumin', ' al ', 'al ']):
                        logger.debug(f"[FILTER] Excluding {designation} - Metal but not aluminum")
                        continue
                    elif hint_lower == 'titanium' and 'titanium' not in designation and 'ti-' not in designation:
                        logger.debug(f"[FILTER] Excluding {designation} - Metal but not titanium")
                        continue

                elif hint_lower == 'plastics' or hint_lower == 'polymer':
                    # Filter by Polymer/Elastomer types (239, 723)
                    is_polymer = (material_type_key in [239, 723])

                    if not is_polymer:
                        logger.debug(f"[FILTER] Excluding {designation} - not classified as Polymer/Elastomer (type={material_type_key})")
                        continue

                elif hint_lower == 'fluorosilicone' or hint_lower == 'fluorosilicones':
                    # Filter for fluorosilicone materials - check by composition key (833) OR designation
                    is_elastomer = (material_type_key in [239, 723])  # Polymer/Elastomer types
                    material_key = original.get('material_key')
                    is_fluoro = self._is_fluorosilicone_material(material_key, designation, material_type_key)

                    if not (is_elastomer and is_fluoro):
                        logger.debug(f"[FILTER] Excluding {designation} - not fluorosilicone (type={material_type_key})")
                        continue

                elif hint_lower == 'silicone' or hint_lower == 'silicones':
                    # Filter for silicone materials - must be elastomer AND contain silicone in designation
                    # Note: also matches fluorosilicone since it contains 'silicone' substring
                    is_elastomer = (material_type_key in [239, 723])  # Polymer/Elastomer types
                    has_silicone = 'silicone' in designation or 'vmq' in designation

                    if not (is_elastomer and has_silicone):
                        logger.debug(f"[FILTER] Excluding {designation} - not silicone (type={material_type_key})")
                        continue

            # Filter by material subtype if specified (e.g., fluorosilicone, silicone)
            material_subtype_hint = query_intent.get('material_subtype_hint')
            if material_subtype_hint:
                subtype_lower = material_subtype_hint.lower()

                if subtype_lower == 'fluorosilicone':
                    # Check by composition key (833) OR designation text
                    material_key = original.get('material_key')
                    if not self._is_fluorosilicone_material(material_key, designation, material_type_key):
                        logger.debug(f"[FILTER] Excluding {designation} - not fluorosilicone")
                        continue

                elif subtype_lower == 'silicone':
                    # Must contain silicone in designation
                    if 'silicone' not in designation and 'vmq' not in designation:
                        logger.debug(f"[FILTER] Excluding {designation} - not silicone")
                        continue

            # Filter for O2 compatibility: require flammability rating when oxygen_service requested
            if query_intent.get('oxygen_service'):
                # Check for flammability rating (O2 compatibility indicator)
                o2_rating = original.get('o2_rating') or original.get('flamm_rating')
                if not o2_rating or str(o2_rating).upper() in ('', 'NULL', 'NONE'):
                    logger.debug(f"[FILTER] Excluding {designation} - no O2/flammability rating")
                    continue

            # Filter by rating if specified
            if rating_required:
                payload = original.get('payload', {})
                # Check all possible rating fields (toxicity-specific fields FIRST for ISS priority)
                rating_fields = [
                    # Toxicity program-specific fields (priority order: ISS -> Shuttle -> EMU -> Orion)
                    'tox_spacestationrating', 'tox_spacestationrtg', 'tox_shuttlerating',
                    'tox_emurating', 'tox_orionrating', 'tox_rtg', 'tox_rating',
                    # Other test-specific rating fields
                    'rating', 'rtg', 'flam_rtg', 'fla_rating', 'pneu_rating', 'mech_rating',
                    'partimp_rating', 'prom_rating', 'cor_rating', 'elo_rating', 'ewi_rating',
                    'fluid_rating', 'fung_rating', 'odor_rating', 'stress_rating', 'tens_rating',
                    'tvs_rating', 'vcm_rating', 'arc_rating', 'lowcyc_rating',
                    'highcyc_rating', 'fri_rating', 'crk_rating', 'frac_rating', 'crp_rating'
                ]

                found_rating = None
                for field in rating_fields:
                    val = payload.get(field)
                    if val and str(val).strip() and str(val).strip().upper() != 'NULL':
                        found_rating = str(val).strip().upper()
                        break

                if not found_rating or rating_required.upper() not in found_rating:
                    logger.debug(f"[FILTER] Excluding {designation} - rating {found_rating} != {rating_required}")
                    continue

            filtered.append(result)

        logger.info(f"[FILTER] Applied intent filters: {len(results)} -> {len(filtered)} results")
        return filtered

    def _apply_h2_category_filter(self, results: List[Dict], query_intent: Dict) -> List[Dict]:
        """
        Apply smart category-based filtering for H2 queries.

        Uses official MAPTIS material_type_key (235=Metal, 239=Polymer, etc.) when available,
        falls back to keyword matching for materials without type classification.

        Args:
            results: H2-ranked search results
            query_intent: Detected query intent

        Returns:
            Filtered results matching material type hint (metals, plastics, etc.)
        """
        filtered = []
        material_type_hint = query_intent.get('material_type_hint')
        rating_required = query_intent.get('rating_required')

        for result in results:
            material = result.get('material', {})
            original = result.get('original_material', {})
            designation = (material.get('designation') or '').lower()

            # Get official material type from MAPTIS lookup (added during indexing)
            material_type_key = original.get('material_type_key')
            material_type_name = (original.get('material_type_name') or '').lower()

            # Filter by material type
            if material_type_hint:
                hint_lower = material_type_hint.lower()

                if hint_lower == 'metals':
                    # Step 1: Keep officially classified metals
                    if material_type_key == 235 or material_type_name == 'metal':
                        pass  # Keep it - officially classified as metal
                    # Step 2: EXPLICITLY EXCLUDE known non-metal types FIRST
                    elif material_type_key in [239, 229, 231, 232, 233, 723]:  # Polymer, Adhesive, Coating, Composite, Foam, Elastomer
                        logger.debug(f"[H2 FILTER] Excluding {designation} - type_key={material_type_key} is non-metal")
                        continue
                    # Step 3: For unknown types (None or -1), use keyword fallback
                    else:
                        metal_indicators = ['steel', 'stainless', 'cres', 'aluminum', 'aluminium',
                                           'titanium', 'ti-', 'inconel', 'monel', 'hastelloy',
                                           'nickel', 'copper', 'bronze', 'brass', 'magnesium',
                                           'alloy', 'al ', 'ss ', 'ti ']
                        if not any(indicator in designation for indicator in metal_indicators):
                            logger.debug(f"[H2 FILTER] Excluding {designation} - no metal keywords found (type_key={material_type_key})")
                            continue

                elif hint_lower == 'steel':
                    if material_type_key == 235 or material_type_name == 'metal':
                        # Is a metal, check if it's steel
                        if 'steel' not in designation and 'cres' not in designation:
                            logger.debug(f"[H2 FILTER] Excluding {designation} - Metal but not steel")
                            continue
                    else:
                        logger.debug(f"[H2 FILTER] Excluding {designation} - not classified as Metal")
                        continue

                elif hint_lower == 'aluminum':
                    if material_type_key == 235 or material_type_name == 'metal':
                        # Is a metal, check if it's aluminum
                        if 'aluminum' not in designation and 'aluminium' not in designation and not designation.startswith('al '):
                            logger.debug(f"[H2 FILTER] Excluding {designation} - Metal but not aluminum")
                            continue
                    else:
                        logger.debug(f"[H2 FILTER] Excluding {designation} - not classified as Metal")
                        continue

                elif hint_lower == 'titanium':
                    if material_type_key == 235 or material_type_name == 'metal':
                        # Is a metal, check if it's titanium
                        if 'titanium' not in designation and 'ti-' not in designation:
                            logger.debug(f"[H2 FILTER] Excluding {designation} - Metal but not titanium")
                            continue
                    else:
                        logger.debug(f"[H2 FILTER] Excluding {designation} - not classified as Metal")
                        continue

                elif hint_lower == 'plastics' or hint_lower == 'polymer':
                    # Prefer official classification (material_type_key=239 Polymer, 723 Elastomer)
                    if material_type_key in [239, 723] or material_type_name in ['polymer', 'elastomer']:
                        pass  # Keep it - officially classified as polymer/elastomer
                    else:
                        # Fallback: Check designation keywords
                        plastic_indicators = ['plastic', 'polymer', 'poly', 'nylon', 'teflon', 'ptfe',
                                             'peek', 'pps', 'ultem', 'torlon', 'vespel', 'micarta',
                                             'kapton', 'epoxy', 'resin']
                        if not any(indicator in designation for indicator in plastic_indicators):
                            logger.debug(f"[H2 FILTER] Excluding {designation} - not classified as Polymer (type_key={material_type_key})")
                            continue

                elif hint_lower == 'fluorosilicone' or hint_lower == 'fluorosilicones':
                    # Filter for fluorosilicone materials - check composition key (833) OR designation
                    is_elastomer = (material_type_key in [239, 723])  # Polymer/Elastomer
                    material_key = original.get('material_key')
                    is_fluoro = self._is_fluorosilicone_material(material_key, designation, material_type_key)

                    if not (is_elastomer and is_fluoro):
                        # Fallback: keep if unclassified but is fluorosilicone by composition/name
                        if material_type_key is None and is_fluoro:
                            pass  # Keep it
                        else:
                            logger.debug(f"[H2 FILTER] Excluding {designation} - not fluorosilicone (type_key={material_type_key})")
                            continue

                elif hint_lower == 'silicone' or hint_lower == 'silicones':
                    # Filter for silicone materials
                    is_elastomer = (material_type_key in [239, 723])  # Polymer/Elastomer
                    has_silicone = 'silicone' in designation or 'vmq' in designation

                    if not (is_elastomer and has_silicone):
                        # Fallback: designation check only if no type classification
                        if material_type_key is None and has_silicone:
                            pass  # Keep it
                        else:
                            logger.debug(f"[H2 FILTER] Excluding {designation} - not silicone (type_key={material_type_key})")
                            continue

            # Filter by material subtype if specified (e.g., fluorosilicone, silicone)
            material_subtype_hint = query_intent.get('material_subtype_hint')
            if material_subtype_hint:
                subtype_lower = material_subtype_hint.lower()

                if subtype_lower == 'fluorosilicone':
                    material_key = original.get('material_key')
                    if not self._is_fluorosilicone_material(material_key, designation, material_type_key):
                        logger.debug(f"[H2 FILTER] Excluding {designation} - not fluorosilicone (subtype filter)")
                        continue

                elif subtype_lower == 'silicone':
                    if 'silicone' not in designation and 'vmq' not in designation:
                        logger.debug(f"[H2 FILTER] Excluding {designation} - not silicone (subtype filter)")
                        continue

            # Filter by rating if specified
            if rating_required:
                payload = original.get('payload', {})
                # Check all possible rating fields (toxicity-specific fields FIRST for ISS priority)
                rating_fields = [
                    # Toxicity program-specific fields (priority order: ISS -> Shuttle -> EMU -> Orion)
                    'tox_spacestationrating', 'tox_spacestationrtg', 'tox_shuttlerating',
                    'tox_emurating', 'tox_orionrating', 'tox_rtg', 'tox_rating',
                    # Other test-specific rating fields
                    'rating', 'rtg', 'flam_rtg', 'fla_rating', 'pneu_rating', 'mech_rating',
                    'partimp_rating', 'prom_rating', 'cor_rating', 'elo_rating', 'ewi_rating',
                    'fluid_rating', 'fung_rating', 'odor_rating', 'stress_rating', 'tens_rating',
                    'tvs_rating', 'vcm_rating', 'arc_rating', 'lowcyc_rating',
                    'highcyc_rating', 'fri_rating', 'crk_rating', 'frac_rating', 'crp_rating'
                ]

                found_rating = None
                for field in rating_fields:
                    val = payload.get(field)
                    if val and str(val).strip() and str(val).strip().upper() != 'NULL':
                        found_rating = str(val).strip().upper()
                        break

                if not found_rating or rating_required.upper() not in found_rating:
                    logger.debug(f"[H2 FILTER] Excluding {designation} - rating {found_rating} != {rating_required}")
                    continue

            filtered.append(result)

        logger.info(f"[H2 FILTER] Applied H2 category filter: {len(results)} -> {len(filtered)} results")
        return filtered

    def _keyword_search(self, query: str, query_intent: Dict, top_k: int) -> List[Dict]:
        """Fallback keyword search when embeddings aren't available.
        
        Args:
            query: Search query
            query_intent: Query intent analysis
            top_k: Number of results to return
            
        Returns:
            List of search results
            
        Raises:
            DataIntegrityError: If materials data is corrupted
        """
        try:
            query_lower = query.lower()
            results = []
            
            # Check if we have materials to search
            if not hasattr(self, 'materials') or not self.materials:
                logger.warning("No materials available for keyword search fallback")
                raise_safety_error(
                    DataIntegrityError,
                    "No materials data available for keyword search",
                    data_type="materials",
                    affected_records=0
                )
            
            for i, m in enumerate(self.materials):
                try:
                    score = 0.0
                    material_dict = m.model_dump()
                    
                    # Check composition match
                    if m.composition and query_lower in m.composition.lower():
                        score += 0.5
                    
                    # Check for oxygen test match if looking for oxygen materials
                    if query_intent.get('oxygen_service', False):
                        for test in m.test_reports:
                            if 'oxygen' in str(test.test_type).lower() and test.test_result == 'PASS':
                                score += 1.0
                                break
                    
                    if score > 0:
                        results.append({
                            "material": material_dict,
                            "similarity_score": min(score, 1.0)
                        })
                except Exception as e:
                    logger.warning(f"Error processing material {i}: {e}")
                    continue
            
            results.sort(key=lambda x: x["similarity_score"], reverse=True)
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            raise_safety_error(
                DataIntegrityError,
                f"Keyword search failed: {e}",
                data_type="materials",
                validation_errors=[str(e)]
            )

    def get_similar_materials(self, material_idx: int, limit: int = 10) -> List[Tuple[int, float]]:
        """
        Find materials similar to the given material index.
        
        Args:
            material_idx: Index of the reference material
            limit: Number of similar materials to return
            
        Returns:
            List of tuples (material_index, similarity_score)
            
        Examples:
            >>> similar = engine.get_similar_materials(42, limit=5)
            >>> for idx, score in similar:
            ...     print(f"Material {idx}: {score:.2f} similarity")
            
        Compliance: SWE-055 (Performance optimization)
        """
        # Real cosine/embedding similarity is not implemented here (the vectors
        # live in FAISS). Do NOT return fabricated uniform 0.5 "similarity"
        # scores that look computed — fail loudly so callers don't trust them.
        raise NotImplementedError(
            "get_similar_materials requires FAISS embedding lookup, which is not "
            "implemented. Use the FAISS-backed semantic search path instead of "
            "relying on placeholder similarity scores."
        )
    
    async def search_cached(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None
    ) -> List[Dict]:
        """
        Cached version of search for async contexts.
        
        Args:
            query: Search query
            top_k: Number of results
            min_similarity: Minimum similarity score
            
        Returns:
            Search results
            
        Examples:
            >>> results = await engine.search_cached("aluminum")
            
        Compliance: SWE-055 (async operations)
        """
        # Check cache first
        cache = await get_cache()
        cache_key = {
            "query": query.lower().strip(),
            "top_k": top_k,
            "min_similarity": min_similarity
        }
        
        # Try to get from cache
        cached_result = await cache.get("search", cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for query: {query}")
            return cached_result
        
        # Perform search
        result = self.search(query, top_k, min_similarity)
        
        # Cache the result
        await cache.set("search", cache_key, result, ttl=3600)
        
        return result
    
    @cache_key_wrapper(
        namespace="intent",
        ttl=7200,
        key_func=lambda self, query: {"query": query.lower().strip()}
    )
    async def detect_query_intent(self, query: str) -> Dict[str, Any]:
        """
        Cached version of understand_query_intent for async contexts.
        
        Args:
            query: Search query
            
        Returns:
            Query intent analysis
            
        Compliance: SWE-055, SWE-032
        """
        return self.understand_query_intent(query)
