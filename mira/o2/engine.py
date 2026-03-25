#!/usr/bin/env python3
"""
Module: Engine
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations
"""
Copyright: © 2025 BoundState AI. All Rights Reserved.
Classification: BoundState Proprietary
License: Evaluation Use Only - Authorized Pilot Program

NOTE: This file was ported from src/core/o2_engine.py. The public
entrypoint for new code is evaluate_o2_compatibility(); legacy functions
below can be refactored behind it.
"""
"""
Oxygen Compatibility Engine for MIRA

Provides O2-specific filtering and scoring for material search results.
Addresses promoted combustion hazards in oxygen-enriched environments.

Data Sources:
1. NASA-STD-6016 - Standard Materials & Processes Requirements
2. NASA-STD-6001B - Flammability, Offgassing, and Compatibility Requirements
3. NASA/TM-2007-213740 - Guide for Oxygen Compatibility Assessments
4. KSC-KTI-5210C - Kennedy Space Center Oxygen Compatibility
5. MAPTIS test records - Flammability test data (Test 1, promoted combustion)

Design Philosophy:
- Data-driven: Based on actual flammability test data and BOK standards
- Environment-aware: Accounts for O2 concentration, pressure, temperature
- Explainable: Shows user why a material is/isn't O2-compatible
- Maintainable: Separate from general search logic
- Safety-focused: Follows NASA human-rated requirements

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Sonnet 4 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import numpy as np
from collections import Counter

# DETERMINISM FIX: Set numpy random seed for reproducible results
# This ensures that any numpy operations with randomness are consistent
np.random.seed(42)

# Try to import BM25
try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    logging.warning("rank_bm25 not available - hybrid search will use TF-IDF fallback")

from .policy_engine import (
    O2PolicyEngine,
    O2EnvironmentSpec,
    SafetyClass,
    get_o2_policy_engine
)
from .models import O2CompatibilityRequest, O2CompatibilityResponse
from core.models.answer import AnswerSeverity, EvidenceItem
from mira.maptis.repository import (
    get_material_for_o2,
    MaterialFamily,
    MaterialRecord,
    O2_PROHIBITED_FAMILIES,
    O2_RESTRICTED_FAMILIES,
    get_o2_family_rule,
)

LOGGER = logging.getLogger(__name__)


def evaluate_o2_compatibility(request: O2CompatibilityRequest) -> O2CompatibilityResponse:
    """Evaluate oxygen compatibility for the given request.

    This wrapper uses the material repository to get structured material data
    and applies family-based classification rules.

    CRITICAL: Classification is based on material FAMILY (from repository),
    not string matching against material names. This prevents the "6061 bug"
    where aluminum at 200 psia GOX was incorrectly classified.

    Args:
        request: Structured O2 compatibility request with material_key,
                 pressure, temperature, and phase.

    Returns:
        O2CompatibilityResponse with classification, rationale, and evidence.
    """
    # Convert request parameters to O2EnvironmentSpec
    temp_f = (request.temperature_k - 273.15) * 9 / 5 + 32
    o2_pct = 100.0
    is_gox = request.phase.value == "gox"

    o2_env = O2EnvironmentSpec(
        o2_concentration_pct=o2_pct,
        pressure_psi=request.pressure_psia,
        temperature_f=temp_f,
    )

    # =========================================================================
    # STEP 1: Look up material from repository (NOT string matching)
    # =========================================================================
    material = get_material_for_o2(request.material_key)
    LOGGER.debug(f"[O2_EVAL] Material '{request.material_key}' -> family={material.family.value}, "
                 f"source={material.data_source}, confidence={material.confidence}")

    evidence_items = []

    # =========================================================================
    # STEP 2: Apply family-based classification rules
    # =========================================================================

    # HARD PROHIBITION: Titanium, Magnesium (any O2 environment)
    if material.family in O2_PROHIBITED_FAMILIES:
        rule = get_o2_family_rule(material.family)
        evidence_items.append(EvidenceItem(
            source_id=rule["bok_ref"],
            summary=f"Material family '{material.family.value}' prohibited"
        ))
        return O2CompatibilityResponse(
            classification=AnswerSeverity.PROHIBITED,
            rationale=rule["reason"],
            evidence=evidence_items,
            notes=f"Environment: {o2_pct}% O2, {request.pressure_psia} psi, {temp_f:.1f}°F"
        )

    # RESTRICTED: Aluminum (LOX only, NOT GOX at elevated pressure)
    # Per NASA-STD-6016 §4.2.6.3 and JSC-27301F §5.1.4:
    # - Aluminum is LIMITED to LOX (cryogenic) service only
    # - Aluminum is PROHIBITED in GOX at ~200 psia or above
    GOX_ALUMINUM_PRESSURE_LIMIT = 200.0  # psia per JSC-27301F

    if material.family == MaterialFamily.ALUMINUM:
        rule = get_o2_family_rule(material.family)

        # THE 6061 FIX: Aluminum in GOX at elevated pressure (>=200 psi) is PROHIBITED
        if is_gox and request.pressure_psia >= GOX_ALUMINUM_PRESSURE_LIMIT:
            evidence_items.append(EvidenceItem(
                source_id="NASA-STD-6016 §4.2.6.3, JSC-27301F §5.1.4",
                summary=f"Aluminum prohibited in GOX at {request.pressure_psia} psia (limit: {GOX_ALUMINUM_PRESSURE_LIMIT} psia)"
            ))
            return O2CompatibilityResponse(
                classification=AnswerSeverity.PROHIBITED,
                rationale=f"Aluminum alloys are PROHIBITED in GOX at {request.pressure_psia} psia. "
                          f"Per NASA-STD-6016 §4.2.6.3: aluminum is limited to LOX (cryogenic) service only. "
                          f"JSC-27301F §5.1.4 specifies ~{GOX_ALUMINUM_PRESSURE_LIMIT} psia limit for GOX.",
                evidence=evidence_items,
                notes=f"Environment: GOX {o2_pct}% O2, {request.pressure_psia} psi, {temp_f:.1f}°F - EXCEEDS ALUMINUM GOX LIMIT"
            )

        # Aluminum in GOX at low pressure (<200 psi) gets CAUTION
        if is_gox:
            evidence_items.append(EvidenceItem(
                source_id=rule["bok_ref"],
                summary="Aluminum restricted to LOX service - GOX use requires engineering review"
            ))
            return O2CompatibilityResponse(
                classification=AnswerSeverity.CAUTION,
                rationale=f"Aluminum alloys have restricted use in O2 service. {rule['reason']} "
                          f"GOX use below {GOX_ALUMINUM_PRESSURE_LIMIT} psia requires engineering review.",
                evidence=evidence_items,
                notes=f"Environment: GOX {o2_pct}% O2, {request.pressure_psia} psi - near aluminum limit"
            )

        # Aluminum in LOX (cryogenic) may be OK with caution
        evidence_items.append(EvidenceItem(
            source_id=rule["bok_ref"],
            summary="Aluminum permitted in LOX with restrictions"
        ))
        return O2CompatibilityResponse(
            classification=AnswerSeverity.CAUTION,
            rationale=f"Aluminum permitted in LOX (cryogenic) service with restrictions. {rule['reason']}",
            evidence=evidence_items,
            notes=f"Environment: LOX {o2_pct}% O2, {request.pressure_psia} psi, {temp_f:.1f}°F"
        )

    # APPROVED FAMILIES: Nickel alloys, austenitic steel, copper
    if material.family in {MaterialFamily.NICKEL_ALLOY, MaterialFamily.COPPER}:
        rule = get_o2_family_rule(material.family)
        evidence_items.append(EvidenceItem(
            source_id=rule["bok_ref"],
            summary=f"Material family '{material.family.value}' approved for O2"
        ))
        return O2CompatibilityResponse(
            classification=AnswerSeverity.OK,
            rationale=rule["reason"],
            evidence=evidence_items,
            notes=f"Environment: {o2_pct}% O2, {request.pressure_psia} psi, {temp_f:.1f}°F"
        )

    if material.family == MaterialFamily.AUSTENITIC_STEEL:
        rule = get_o2_family_rule(material.family)
        evidence_items.append(EvidenceItem(
            source_id=rule["bok_ref"],
            summary="Austenitic stainless approved with cautions"
        ))
        return O2CompatibilityResponse(
            classification=AnswerSeverity.CAUTION if request.pressure_psia > 1000 else AnswerSeverity.OK,
            rationale=rule["reason"],
            evidence=evidence_items,
            notes=f"Environment: {o2_pct}% O2, {request.pressure_psia} psi - precision cleaning required >1000 psi"
        )

    # =========================================================================
    # STEP 3: Unknown family - fall back to legacy policy engine
    # =========================================================================
    policy_engine = get_o2_policy_engine(safety_class=SafetyClass.CLASS_A)

    candidate = {
        'material_key': request.material_key,
        'material': {
            'material_key': request.material_key,
            'designation': material.designation,
            'material_type': material.material_type,
        },
        'similarity_score': 1.0,
        'o2_info': {
            'o2_test_count': material.o2_test_count,
            'flamm_ratings': [material.rating_flam] if material.rating_flam else [],
        }
    }

    admitted, excluded = policy_engine.apply_policy_gate([candidate], o2_env)

    if excluded:
        evidence_bundle = excluded[0]
        classification = AnswerSeverity.PROHIBITED
        rationale = "; ".join(evidence_bundle.exclusion_reasons) if evidence_bundle.exclusion_reasons else "Material excluded by O2 policy gate"
    elif admitted:
        evidence_bundle = admitted[0]
        compat = evidence_bundle.o2_compatibility.value
        if compat == "VERIFIED":
            classification = AnswerSeverity.OK
            rationale = f"Material verified for O2 service. Authority score: {evidence_bundle.f_authority:.2f}"
        elif compat == "CONDITIONAL":
            classification = AnswerSeverity.CAUTION
            rationale = "Material conditionally compatible. " + ("; ".join(evidence_bundle.warnings) if evidence_bundle.warnings else "Engineering review required.")
        else:
            classification = AnswerSeverity.UNKNOWN
            rationale = "O2 compatibility not verified - testing required per NASA-STD-6001"
    else:
        classification = AnswerSeverity.UNKNOWN
        rationale = "No evaluation result available - material family unknown"

    if admitted or excluded:
        bundle = excluded[0] if excluded else admitted[0]
        if bundle.bok_citations:
            for cite in bundle.bok_citations:
                evidence_items.append(EvidenceItem(
                    source_id=cite,
                    summary="BOK citation"
                ))

    return O2CompatibilityResponse(
        classification=classification,
        rationale=rationale,
        evidence=evidence_items,
        notes=f"Environment: {o2_pct}% O2, {request.pressure_psia} psi, {temp_f:.1f}°F ({o2_env.get_risk_level()} risk)"
    )

# O2 compatibility ratings based on NASA-STD-6016 and flammability test data
# A = Excellent (nickel alloys, copper alloys, precision-cleaned stainless)
# B = Good (some stainless steels with restrictions)
# C = Fair (limited use, requires engineering evaluation)
# D = Poor (not recommended for O2 service)
# X = Fail (prohibited - titanium, magnesium, organics)
# U = Unknown (insufficient flammability data)


class OxygenCompatibilityEngine:
    """
    Filter and score materials for oxygen service compatibility.

    Post-processes FAISS search results to prioritize materials with
    proven oxygen compatibility based on flammability test data and NASA standards.
    """

    def __init__(self,
                 maptis_metadata_path: Optional[Path] = None,
                 o2_bok_dir: Optional[Path] = None,
                 safety_class: SafetyClass = SafetyClass.CLASS_A):
        """
        Initialize O2 engine with MAPTIS flammability data and O2 BOK.

        Args:
            maptis_metadata_path: Path to MAPTIS FAISS metadata.json
            o2_bok_dir: Path to O2 BOK database directory
            safety_class: NASA safety classification (affects scoring weights)
        """
        self.o2_database: Dict[int, Dict[str, Any]] = {}
        self.o2_materials: Set[int] = set()

        # O2 BOK components (FAISS semantic search)
        self.o2_bok_index = None
        self.o2_bok_metadata = None
        self.o2_bok_text_lookup = None
        self.o2_bok_model = None
        self.o2_faiss_to_metadata = {}  # Map FAISS indices to metadata list indices

        # BM25 components (keyword search for hybrid retrieval)
        self.bm25 = None
        self.bm25_documents = []
        self.bm25_document_tokens = []
        self.bm25_vocab = set()
        self.bm25_idf_scores = {}

        # Initialize policy engine
        self.policy_engine = get_o2_policy_engine(o2_engine=self, safety_class=safety_class)

        # Load MAPTIS flammability test data if provided
        if maptis_metadata_path and maptis_metadata_path.exists():
            self._load_maptis_o2_data(maptis_metadata_path)

        # Load O2 BOK (NASA-STD-6016, 6001, KSC-KTI-5210C, etc.)
        if o2_bok_dir is None:
            # Try default paths
            possible_paths = [
                Path(__file__).parent.parent.parent / "mira" / "databases" / "o2_bok",
                Path(__file__).parent.parent.parent / "databases" / "o2_bok"
            ]
            for path in possible_paths:
                if path.exists():
                    o2_bok_dir = path
                    break

        # Always try to load O2 BOK - fallback will handle missing dir
        self._load_o2_bok(o2_bok_dir)

        LOGGER.info(f"O2 engine initialized with {len(self.o2_materials)} O2-tested materials")

    def _load_maptis_o2_data(self, metadata_path: Path):
        """Extract O2-related flammability test records from MAPTIS metadata."""
        try:
            with open(metadata_path, 'r') as f:
                data = json.load(f)

            # Handle both formats: direct metadata list or nested under source_metadata
            records = data.get('metadata', [])
            if not records and 'source_metadata' in data:
                records = data['source_metadata'].get('metadata', [])

            LOGGER.info(f"Loading O2 data from {len(records)} MAPTIS records...")
            o2_keywords = ['oxygen', ' o2', 'lox', 'gox', 'liquid oxygen', 'gaseous oxygen',
                          'flammability', 'promoted combustion', 'ignition', 'nasa-std-6001']

            for record in records:
                material_key = record.get('material_key')
                if not material_key:
                    continue

                payload = record.get('payload', {})
                payload_str = json.dumps(payload).lower()

                # Check if record is flammability/O2 test
                has_o2 = any(keyword in payload_str for keyword in o2_keywords)

                # Also check test_class field
                test_class = payload.get('test_class', '').lower()
                is_flamm_test = any(t in test_class for t in ['flamm', 'flammability', 'promoted', 'ignition'])

                if has_o2 or is_flamm_test:
                    # Initialize material entry if not exists
                    if material_key not in self.o2_database:
                        self.o2_database[material_key] = {
                            'material_key': material_key,
                            'o2_test_count': 0,
                            'test_types': set(),
                            'flamm_ratings': [],
                            'o2_concentration_pct': [],
                            'pressure_psi': [],
                            'temperature_range': {'min_f': None, 'max_f': None},
                            'test_environments': set(),
                            'combustion_risk': 'unknown',
                            'source_docs': set(),
                            'test_records': []
                        }

                    # Update material entry
                    mat_data = self.o2_database[material_key]
                    mat_data['o2_test_count'] += 1
                    mat_data['test_types'].add(record.get('contract_id', 'unknown'))
                    mat_data['test_records'].append(record.get('row_uid'))

                    # Extract O2 concentration if available
                    for key in ['o2_concentration', 'oxygen_percent', 'o2_pct', 'environment']:
                        if key in payload:
                            try:
                                o2_val = float(payload[key])
                                if 0 <= o2_val <= 100:
                                    mat_data['o2_concentration_pct'].append(o2_val)
                            except (ValueError, TypeError):
                                # Try extracting from environment string
                                env_str = str(payload[key]).upper()
                                if 'LOX' in env_str or '100% O2' in env_str:
                                    mat_data['o2_concentration_pct'].append(100.0)
                                elif 'GOX' in env_str:
                                    mat_data['o2_concentration_pct'].append(100.0)

                    # Extract pressure if available
                    for key in ['pressure_psi', 'test_pressure', 'pressure']:
                        if key in payload and payload[key]:
                            try:
                                pressure = float(payload[key])
                                if pressure > 0:
                                    mat_data['pressure_psi'].append(pressure)
                            except (ValueError, TypeError):
                                pass

                    # Extract temperature range
                    for key in ['temperatureminimum', 'temp_min', 'temperaturemaximum', 'temp_max',
                               'temperature', 'test_temp']:
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

                    # Extract flammability rating if available
                    for key in ['rating_flam', 'flamm_rating', 'rating', 'test_rating']:
                        if key in payload and payload[key]:
                            rating = str(payload[key]).strip().upper()
                            if rating and rating not in ['NULL', 'NONE', '', 'N/A']:
                                mat_data['flamm_ratings'].append(rating[0] if rating else 'U')

                    # Extract test environment description
                    for key in ['environment', 'test_environment', 'test_conditions']:
                        if key in payload and payload[key]:
                            env_str = str(payload[key]).strip()
                            if env_str and env_str not in ['NULL', 'NONE', '']:
                                mat_data['test_environments'].add(env_str)

                    # Add to O2 materials set
                    self.o2_materials.add(material_key)

            # Convert sets to lists for JSON serialization
            for mat_key in self.o2_database:
                self.o2_database[mat_key]['test_types'] = list(self.o2_database[mat_key]['test_types'])
                self.o2_database[mat_key]['test_environments'] = list(self.o2_database[mat_key]['test_environments'])
                self.o2_database[mat_key]['source_docs'] = list(self.o2_database[mat_key]['source_docs'])

            LOGGER.info(f"Extracted {len(self.o2_materials)} materials with O2/flammability test data from MAPTIS")

        except Exception as e:
            LOGGER.error(f"Failed to load MAPTIS O2 data: {e}")

    def _load_o2_bok(self, o2_bok_dir: Optional[Path]):
        """Load O2 Body of Knowledge (prioritize dedicated hierarchical index)."""
        try:
            import faiss
            from sentence_transformers import SentenceTransformer

            # OPTION 1: Try dedicated O2 BOK index with hierarchical chunking (PREFERRED!)
            if o2_bok_dir and o2_bok_dir.exists():
                index_file = o2_bok_dir / "o2_bok_faiss.index"
                metadata_file = o2_bok_dir / "o2_bok_faiss_metadata.json"
                text_lookup_file = o2_bok_dir / "o2_bok_text_lookup.json"

                if all([f.exists() for f in [index_file, metadata_file, text_lookup_file]]):
                    LOGGER.info("Loading O2 BOK from dedicated hierarchical index (Athena-style chunking)")

                    # Load FAISS index
                    self.o2_bok_index = faiss.read_index(str(index_file))

                    # Load metadata
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        self.o2_bok_metadata = json.load(f)

                    # Load text lookup
                    with open(text_lookup_file, 'r', encoding='utf-8') as f:
                        self.o2_bok_text_lookup = json.load(f)

                    # Load embedding model
                    self.o2_bok_model = SentenceTransformer('all-MiniLM-L6-v2')

                    LOGGER.info(f"Loaded O2 BOK with {len(self.o2_bok_metadata)} hierarchical chunks (JSC-27301F, NASA-STD-6001B, 6016, KSC-KTI-5210C, etc.)")

                    # Build BM25 index for hybrid search
                    self._build_bm25_index()

                    return

            # OPTION 2: Fall back to loading from full MAPTIS corpus (old approach)
            corpus_dir = Path(__file__).parent.parent.parent / "databases" / "permanent_embeddings"
            corpus_index = corpus_dir / "mira_master_corpus.faiss"
            corpus_metadata = corpus_dir / "mira_master_corpus_metadata.jsonl"

            if corpus_index.exists() and corpus_metadata.exists():
                LOGGER.info("Loading O2 BOK from full MAPTIS corpus (includes JSC-27301F + all standards)")

                # Load FAISS index
                self.o2_bok_index = faiss.read_index(str(corpus_index))

                # Load metadata from JSONL and filter to BOK-related sections
                self.o2_bok_metadata = []
                self.o2_bok_text_lookup = {}
                self.o2_faiss_to_metadata = {}  # Map FAISS index to metadata list index

                with open(corpus_metadata, 'r', encoding='utf-8') as f:
                    for faiss_idx, line in enumerate(f):
                        try:
                            doc = json.loads(line)
                            source_type = doc.get('source_type', '')
                            doc_id = doc.get('doc_id', '')

                            # Filter to O2-related BOK sections (NASA standards, O2 BOK, MUAs with O2 content)
                            if any(x in source_type.lower() for x in ['nasa_standard', 'o2_bok']) or \
                               any(x in doc_id for x in ['BOK_', 'O2_BOK_', 'JSC-27301']):

                                # Create unique key for this chunk (doc_id + chunk_id)
                                chunk_id = doc.get('chunk_id', faiss_idx)
                                unique_key = f"{doc_id}_{chunk_id}"

                                # Create metadata entry compatible with search_o2_bok()
                                metadata_idx = len(self.o2_bok_metadata)
                                metadata_entry = {
                                    'doc_id': unique_key,  # Use unique key instead of shared doc_id
                                    'source': doc.get('source_file', doc_id),
                                    'section': doc.get('section', ''),
                                    'tags': doc.get('tags', []),
                                }
                                self.o2_bok_metadata.append(metadata_entry)

                                # Map FAISS index to metadata list index
                                self.o2_faiss_to_metadata[faiss_idx] = metadata_idx

                                # Store text in lookup with unique key to avoid overwriting chunks
                                text = doc.get('content', doc.get('text', ''))
                                self.o2_bok_text_lookup[unique_key] = text

                        except json.JSONDecodeError:
                            continue

                # Load embedding model
                self.o2_bok_model = SentenceTransformer('all-MiniLM-L6-v2')

                LOGGER.info(f"Loaded O2 BOK with {len(self.o2_bok_metadata)} sections from full corpus (NASA-STD-6016, 6001, JSC-27301F, KSC-KTI-5210C, etc.)")

                # Build BM25 index for hybrid search
                self._build_bm25_index()

                return

            # OPTION 3: Warn if no O2 BOK found
            LOGGER.warning(
                "O2 BOK not found. Expected dedicated assets in mira/databases/o2_bok "
                "(o2_bok_faiss.index, o2_bok_faiss_metadata.json, o2_bok_text_lookup.json) "
                "or fallback corpus assets in databases/permanent_embeddings."
            )

        except ImportError as e:
            LOGGER.warning(f"Cannot load O2 BOK - missing dependencies: {e}")
        except Exception as e:
            LOGGER.error(f"Failed to load O2 BOK: {e}")

    def _build_bm25_index(self):
        """Build BM25 index for keyword search (hybrid retrieval component)."""
        if not self.o2_bok_metadata or not self.o2_bok_text_lookup:
            LOGGER.info("No O2 BOK sections available for BM25 indexing")
            return

        LOGGER.info(f"Building BM25 index for {len(self.o2_bok_metadata)} O2 BOK sections...")

        # Extract and tokenize text from each section
        self.bm25_documents = []
        self.bm25_document_tokens = []

        for metadata in self.o2_bok_metadata:
            doc_id = metadata.get('doc_id', '')
            text = self.o2_bok_text_lookup.get(doc_id, '')

            # Boost document ID and section (for exact term matching)
            source = metadata.get('source', '')
            section = metadata.get('section', '')
            boosted_text = f"{text} {source} {source} {section}"  # Repeat for boosting

            # Tokenize for BM25
            tokens = self._tokenize_for_bm25(boosted_text)

            self.bm25_documents.append(boosted_text)
            self.bm25_document_tokens.append(tokens)

        # Initialize BM25 or TF-IDF fallback
        if BM25_AVAILABLE and self.bm25_document_tokens:
            self.bm25 = BM25Okapi(self.bm25_document_tokens, k1=1.2, b=0.75)
            LOGGER.info("BM25 index built successfully for hybrid search")
        else:
            LOGGER.warning("BM25 not available, building TF-IDF fallback")
            self._build_tfidf_fallback()

    def _tokenize_for_bm25(self, text: str) -> List[str]:
        """Tokenize text for BM25 with aerospace-specific preprocessing."""
        # Convert to lowercase
        text = text.lower()

        # Preserve document IDs, pressure values, section numbers
        # Keep patterns like "jsc-27301", "6000 psia", "316l", "section 5.1.4"
        text = re.sub(r'([a-z])(\d)', r'\1 \2', text)  # word-number boundaries
        text = re.sub(r'(\d)([a-z])', r'\1 \2', text)  # number-word boundaries

        # Split on whitespace and punctuation
        tokens = re.findall(r'\b\w+\b', text)

        # Filter very short tokens and common stopwords
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
            'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be',
            'this', 'that', 'these', 'those', 'it', 'its', 'as', 'from'
        }

        tokens = [
            token for token in tokens
            if len(token) >= 2 and token not in stopwords
        ]

        return tokens

    def _build_tfidf_fallback(self):
        """Build simple TF-IDF fallback when BM25 is not available."""
        LOGGER.info("Building TF-IDF fallback index...")

        # Build vocabulary
        self.bm25_vocab = set()
        for tokens in self.bm25_document_tokens:
            self.bm25_vocab.update(tokens)

        # Calculate IDF scores
        total_docs = len(self.bm25_document_tokens)
        for term in self.bm25_vocab:
            doc_freq = sum(1 for tokens in self.bm25_document_tokens if term in tokens)
            # Add smoothing to avoid division by zero
            import math
            self.bm25_idf_scores[term] = math.log((total_docs + 1) / (doc_freq + 1))

        LOGGER.info(f"TF-IDF fallback built with {len(self.bm25_vocab)} terms")

    def _search_bm25(self, query: str, k: int = 50) -> List[Dict[str, Any]]:
        """Perform BM25 keyword search with safety-critical term boosting.

        DETERMINISM FIX: Uses stable sorting with doc_id as secondary key
        to ensure consistent ordering when scores are equal.
        """
        if not self.bm25_documents:
            return []

        # Tokenize query
        query_tokens = self._tokenize_for_bm25(query)
        if not query_tokens:
            return []

        # Compute BM25 scores
        if BM25_AVAILABLE and self.bm25:
            scores = self.bm25.get_scores(query_tokens)
        else:
            # TF-IDF fallback
            scores = self._compute_tfidf_scores(query_tokens)

        # Apply safety-critical term boosting
        scores = self._apply_safety_critical_boost(scores, query_tokens)

        # DETERMINISM FIX: Create (score, doc_id, idx) tuples for stable sorting
        # When scores are equal, sort by doc_id alphabetically for consistency
        scored_items = []
        for idx in range(len(scores)):
            if scores[idx] > 0:
                metadata = self.o2_bok_metadata[idx]
                doc_id = metadata.get('doc_id', f'doc_{idx}')
                scored_items.append((scores[idx], doc_id, idx))

        # Sort by score descending, then by doc_id ascending for deterministic tie-breaking
        scored_items.sort(key=lambda x: (-x[0], x[1]))

        # Take top k
        top_items = scored_items[:k]

        results = []
        for score, doc_id, idx in top_items:
            metadata = self.o2_bok_metadata[idx]
            text = self.o2_bok_text_lookup.get(doc_id, '')

            results.append({
                'metadata_idx': idx,
                'doc_id': doc_id,
                'text': text,
                'source': metadata.get('source', 'Unknown'),
                'section': metadata.get('section', ''),
                'bm25_score': float(score),
                'bm25_rank': len(results) + 1
            })

        return results

    def _apply_safety_critical_boost(self, scores: np.ndarray, query_tokens: List[str]) -> np.ndarray:
        """
        Boost BM25 scores for documents containing safety-critical terms.

        This is critical for materials safety queries where specific pressure limits,
        material names, and component types must be matched exactly.
        """
        boosted_scores = scores.copy()

        # Safety-critical terms that indicate specific guidance
        material_terms = {'aluminum', 'titanium', 'stainless', 'steel', 'inconel', 'monel', 'copper', 'brass'}
        pressure_terms = {'psi', 'psia', 'psig', 'mpa', 'kpa', '3000', '100', '500', '1000', '6000', '10000'}
        component_terms = {'valve', 'regulator', 'fitting', 'vessel', 'component', 'static', 'dynamic'}
        safety_terms = {'flammable', 'prohibited', 'approved', 'compatible', 'ignition', 'combustion'}

        # Check which safety-critical terms are in the query
        query_has_material = any(term in query_tokens for term in material_terms)
        query_has_pressure = any(term in query_tokens for term in pressure_terms)
        query_has_component = any(term in query_tokens for term in component_terms)

        # If query contains material + pressure, it's a critical safety query
        is_critical_query = query_has_material and (query_has_pressure or query_has_component)

        if not is_critical_query:
            return boosted_scores  # No boosting for general queries

        # Boost documents that contain multiple safety-critical terms
        for idx in range(len(self.bm25_document_tokens)):
            doc_tokens = set(self.bm25_document_tokens[idx])

            # Count how many safety-critical terms from query appear in document
            material_matches = sum(1 for term in material_terms if term in query_tokens and term in doc_tokens)
            pressure_matches = sum(1 for term in pressure_terms if term in query_tokens and term in doc_tokens)
            component_matches = sum(1 for term in component_terms if term in query_tokens and term in doc_tokens)
            safety_matches = sum(1 for term in safety_terms if term in query_tokens and term in doc_tokens)

            # Apply progressive boosting for documents with multiple critical term matches
            boost_factor = 1.0

            if material_matches > 0 and pressure_matches > 0:
                # Material + pressure combo is HIGHLY relevant
                boost_factor += 1.5

            if material_matches > 0 and component_matches > 0:
                # Material + component combo is also highly relevant
                boost_factor += 1.3

            if pressure_matches >= 2:
                # Multiple pressure values mentioned (e.g., "3000" and "100")
                boost_factor += 0.8

            if safety_matches > 0:
                # Safety terms present
                boost_factor += 0.5

            # Special boost for JSC-27301F (authoritative O2 compatibility MUA)
            doc_id = self.o2_bok_metadata[idx].get('doc_id', '')
            if 'jsc-27301' in doc_id.lower() or 'jsc 27301' in doc_id.lower():
                boost_factor += 0.7

            # Apply boost
            if boost_factor > 1.0:
                boosted_scores[idx] *= boost_factor

        return boosted_scores

    def _compute_tfidf_scores(self, query_tokens: List[str]) -> np.ndarray:
        """Compute TF-IDF scores for fallback."""
        scores = np.zeros(len(self.bm25_document_tokens))

        for doc_idx, doc_tokens in enumerate(self.bm25_document_tokens):
            doc_token_counts = Counter(doc_tokens)
            doc_length = len(doc_tokens)

            score = 0.0
            for term in query_tokens:
                if term in doc_token_counts:
                    tf = doc_token_counts[term] / doc_length if doc_length > 0 else 0
                    idf = self.bm25_idf_scores.get(term, 0)
                    score += tf * idf

            scores[doc_idx] = score

        return scores

    def _reciprocal_rank_fusion(self,
                                 semantic_results: List[Dict],
                                 bm25_results: List[Dict],
                                 rrf_k: int = 60) -> List[Dict]:
        """
        Apply Reciprocal Rank Fusion to combine semantic and keyword results.

        RRF score = sum(1/(k + rank_i)) for all result lists where doc appears

        DETERMINISM FIX: Uses stable sorting with doc_id as secondary key
        to ensure consistent ordering when RRF scores are equal.
        """
        doc_scores = {}

        # Process semantic (FAISS) results
        for rank, doc in enumerate(semantic_results, 1):
            doc_id = doc.get('doc_id', '')
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {
                    'doc': doc,
                    'semantic_rank': rank,
                    'bm25_rank': None,
                    'semantic_score': doc.get('relevance_score', 0),
                    'bm25_score': 0,
                    'rrf_score': 0
                }

            # Add RRF score from semantic ranking
            doc_scores[doc_id]['rrf_score'] += 1 / (rrf_k + rank)

        # Process BM25 (keyword) results
        for rank, doc in enumerate(bm25_results, 1):
            doc_id = doc.get('doc_id', '')

            if doc_id not in doc_scores:
                doc_scores[doc_id] = {
                    'doc': doc,
                    'semantic_rank': None,
                    'bm25_rank': rank,
                    'semantic_score': 0,
                    'bm25_score': doc.get('bm25_score', 0),
                    'rrf_score': 0
                }
            else:
                # Update BM25 info
                doc_scores[doc_id]['bm25_rank'] = rank
                doc_scores[doc_id]['bm25_score'] = doc.get('bm25_score', 0)

            # Add RRF score from BM25 ranking
            doc_scores[doc_id]['rrf_score'] += 1 / (rrf_k + rank)

        # Build final fused results
        fused_results = []
        for doc_id, doc_info in doc_scores.items():
            doc = doc_info['doc'].copy()
            doc.update({
                'doc_id': doc_id,  # Ensure doc_id is in the result
                'semantic_rank': doc_info['semantic_rank'],
                'bm25_rank': doc_info['bm25_rank'],
                'semantic_score': doc_info['semantic_score'],
                'bm25_score': doc_info['bm25_score'],
                'rrf_score': doc_info['rrf_score'],
                'relevance_score': doc_info['rrf_score']  # Use RRF as final relevance
            })
            fused_results.append(doc)

        # DETERMINISM FIX: Sort by RRF score descending, then doc_id ascending for stable ordering
        fused_results.sort(key=lambda x: (-x['rrf_score'], x.get('doc_id', '')))

        return fused_results

    def search_o2_bok(self, query: str, k: int = 5, use_hybrid: bool = True) -> List[Dict[str, Any]]:
        """
        Search O2 Body of Knowledge with hybrid retrieval (semantic + keyword).

        Args:
            query: Natural language query (e.g., "aluminum oxygen service 3000 psi")
            k: Number of final results to return
            use_hybrid: If True, use hybrid search (BM25 + semantic). If False, semantic only.

        Returns:
            List of BOK sections with text, citations, and relevance scores
        """
        if not self.o2_bok_index or not self.o2_bok_model:
            LOGGER.warning("O2 BOK not loaded - cannot search")
            return []

        try:
            # If hybrid search disabled or BM25 not available, fall back to semantic only
            if not use_hybrid or not (self.bm25 or self.bm25_vocab):
                return self._search_semantic_only(query, k)

            # HYBRID SEARCH: Combine BM25 (keyword) + FAISS (semantic)
            LOGGER.debug(f"Hybrid search: query='{query}', k={k}")

            # Expand query with material synonyms and related terms
            expanded_queries = self._expand_safety_query(query)

            # Get semantic results (100 candidates for fusion - increased to capture more diversity)
            semantic_results = []
            for exp_query in expanded_queries:
                results = self._search_semantic_only(exp_query, k=100 // len(expanded_queries))
                semantic_results.extend(results)

            # DETERMINISM FIX: Deduplicate semantic results by doc_id, keeping highest-scoring entry
            # First, sort by score descending so we keep the best score for each doc_id
            semantic_results.sort(key=lambda x: (-x.get('relevance_score', 0), x.get('doc_id', '')))

            seen_docs = set()
            unique_semantic = []
            for result in semantic_results:
                doc_id = result.get('doc_id', '')
                if doc_id not in seen_docs:
                    seen_docs.add(doc_id)
                    unique_semantic.append(result)

            # DETERMINISM FIX: Final sort to ensure consistent ordering
            unique_semantic.sort(key=lambda x: (-x.get('relevance_score', 0), x.get('doc_id', '')))
            semantic_results = unique_semantic[:100]  # Keep top 100

            # Get BM25 keyword results (100 candidates for fusion - increased for better coverage)
            bm25_results = self._search_bm25(query, k=100)

            LOGGER.debug(f"Retrieved {len(semantic_results)} semantic + {len(bm25_results)} BM25 results")

            # Apply Reciprocal Rank Fusion
            fused_results = self._reciprocal_rank_fusion(
                semantic_results,
                bm25_results,
                rrf_k=60
            )

            LOGGER.debug(f"Fused to {len(fused_results)} results, returning top {k}")

            # Return top k fused results
            return fused_results[:k]

        except Exception as e:
            LOGGER.error(f"Error in hybrid O2 BOK search: {e}", exc_info=True)
            # Fall back to semantic-only search
            return self._search_semantic_only(query, k)

    def _expand_safety_query(self, query: str) -> List[str]:
        """
        Expand query with material synonyms and related terms for better retrieval.

        Example: "aluminum oxygen" → ["aluminum oxygen", "aluminum alloys oxygen", "Al oxygen"]
        """
        queries = [query]  # Always include original query

        query_lower = query.lower()

        # Material synonym expansions
        material_expansions = {
            'aluminum': ['aluminum alloys', 'al alloys'],
            'stainless steel': ['ss', 'cres', 'stainless'],
            'titanium': ['ti alloys', 'ti'],
            'inconel': ['nickel alloys'],
            'monel': ['nickel copper alloys'],
        }

        # Apply expansions
        for material, synonyms in material_expansions.items():
            if material in query_lower:
                for synonym in synonyms:
                    expanded = query_lower.replace(material, synonym)
                    if expanded != query_lower:
                        queries.append(expanded)

        # Limit to 3 query variations to avoid over-expansion
        return queries[:3]

    def _search_semantic_only(self, query: str, k: int) -> List[Dict[str, Any]]:
        """Perform semantic-only search (FAISS) - fallback for hybrid search.

        DETERMINISM FIX: Re-sorts results by (score descending, doc_id ascending)
        to ensure consistent ordering when FAISS returns tied scores.
        """
        try:
            # Encode query
            query_embedding = self.o2_bok_model.encode([query], convert_to_numpy=True)

            # Search FAISS index (request more than k to allow for filtering)
            search_k = min(k * 2, self.o2_bok_index.ntotal) if self.o2_bok_index else k
            distances, indices = self.o2_bok_index.search(query_embedding, search_k)

            # Collect results with scores
            raw_results = []
            for i, (distance, faiss_idx) in enumerate(zip(distances[0], indices[0])):
                # Map FAISS index to metadata index (if using filtered corpus)
                if hasattr(self, 'o2_faiss_to_metadata') and self.o2_faiss_to_metadata:
                    # Using filtered corpus - need to map FAISS idx to metadata idx
                    metadata_idx = self.o2_faiss_to_metadata.get(int(faiss_idx))
                    if metadata_idx is None:
                        continue  # FAISS returned a non-BOK document
                else:
                    # Using dedicated O2 BOK index - direct mapping
                    metadata_idx = int(faiss_idx)

                if metadata_idx < len(self.o2_bok_metadata):
                    metadata = self.o2_bok_metadata[metadata_idx]
                    doc_id = metadata.get('doc_id', '')
                    text = self.o2_bok_text_lookup.get(doc_id, '')
                    relevance_score = float(1.0 - distance)

                    raw_results.append({
                        'doc_id': doc_id,
                        'relevance_score': relevance_score,
                        'text': text,
                        'source': metadata.get('source', 'Unknown'),
                        'section': metadata.get('section', ''),
                        'page': metadata.get('page'),
                        'tags': metadata.get('tags', [])
                    })

            # DETERMINISM FIX: Sort by score descending, then doc_id ascending for consistent tie-breaking
            raw_results.sort(key=lambda x: (-x['relevance_score'], x['doc_id']))

            # Take top k and add ranks
            results = []
            for i, result in enumerate(raw_results[:k]):
                result['rank'] = i + 1
                results.append(result)

            return results

        except Exception as e:
            LOGGER.error(f"Error in semantic O2 BOK search: {e}")
            return []

    def filter_by_o2_compatibility(self,
                                   search_results: List[Dict[str, Any]],
                                   o2_env: Optional[O2EnvironmentSpec] = None,
                                   min_confidence: float = 0.3) -> Dict[str, Any]:
        """
        Filter and re-rank materials by O2 compatibility.

        Args:
            search_results: Raw FAISS search results
            o2_env: O2 environment specification (pressure, concentration, temp)
            min_confidence: Minimum confidence threshold for inclusion

        Returns:
            {
                'o2_bok_verified': [...],     # Authoritative recommendations
                'other_candidates': [...],     # Semantic matches (verify before use)
                'excluded_materials': [...],   # Excluded due to safety concerns
                'environment': {...}           # O2 environment used
            }
        """
        if not search_results:
            return {
                'o2_bok_verified': [],
                'other_candidates': [],
                'excluded_materials': [],
                'environment': None
            }

        # Default to high-risk environment if not specified
        if o2_env is None:
            o2_env = O2EnvironmentSpec(
                o2_concentration_pct=100.0,
                pressure_psi=3000.0,
                temperature_f=70.0
            )

        # Enrich results with O2 data
        enriched_results = self.enrich_with_o2_data(search_results)

        # Apply policy gate
        admitted, excluded = self.policy_engine.apply_policy_gate(enriched_results, o2_env)

        # Rank admitted materials
        ranked = self.policy_engine.rank_materials(admitted)

        # Filter by minimum confidence
        final_ranked = [
            evidence for evidence in ranked
            if evidence.compute_final_score(self.policy_engine.weights) >= min_confidence
        ]

        # Format results with evidence
        formatted_results = self.policy_engine.format_results_with_evidence(
            final_ranked, excluded, o2_env
        )

        LOGGER.info(f"[O2 FILTER] {len(final_ranked)} candidates passed, "
                   f"{len(excluded)} excluded, "
                   f"{len(final_ranked) - len(formatted_results['o2_bok_verified'])} need review")

        return formatted_results

    def enrich_with_o2_data(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich search results with O2 compatibility data from MAPTIS tests.

        Args:
            search_results: Raw search results from FAISS

        Returns:
            Enriched results with o2_info field containing test data
        """
        enriched = []

        for result in search_results:
            material = result.get('material', {})
            original = result.get('original_material', {})
            material_key = material.get('material_key', original.get('material_key', 0))

            # Add O2 test data if available
            o2_info = {}
            has_flamm_data = False

            if material_key in self.o2_database:
                mat_data = self.o2_database[material_key]
                o2_info = {
                    'o2_test_count': mat_data['o2_test_count'],
                    'flamm_ratings': mat_data['flamm_ratings'],
                    'o2_concentration_pct': mat_data['o2_concentration_pct'],
                    'pressure_psi': mat_data['pressure_psi'],
                    'temperature_range': mat_data['temperature_range'],
                    'test_environments': mat_data['test_environments'],
                    'combustion_risk': mat_data['combustion_risk']
                }
                has_flamm_data = True

            # Create enriched result
            enriched_result = {
                **result,
                'o2_info': o2_info,
                'has_flamm_test_data': has_flamm_data
            }

            enriched.append(enriched_result)

        return enriched

    def get_o2_compatibility_summary(self, material_key: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed O2 compatibility summary for a specific material.

        Args:
            material_key: MAPTIS material key

        Returns:
            Dictionary with O2 compatibility details or None if not found
        """
        if material_key not in self.o2_database:
            return None

        mat_data = self.o2_database[material_key]

        # Compute average O2 concentration tested
        avg_o2_pct = (
            sum(mat_data['o2_concentration_pct']) / len(mat_data['o2_concentration_pct'])
            if mat_data['o2_concentration_pct'] else None
        )

        # Compute max pressure tested
        max_pressure = max(mat_data['pressure_psi']) if mat_data['pressure_psi'] else None

        # Determine most common rating
        rating_mode = None
        if mat_data['flamm_ratings']:
            from collections import Counter
            rating_counts = Counter(mat_data['flamm_ratings'])
            rating_mode = rating_counts.most_common(1)[0][0]

        return {
            'material_key': material_key,
            'o2_test_count': mat_data['o2_test_count'],
            'primary_rating': rating_mode,
            'all_ratings': mat_data['flamm_ratings'],
            'tested_o2_concentration_pct': avg_o2_pct,
            'max_pressure_tested_psi': max_pressure,
            'temperature_range': mat_data['temperature_range'],
            'test_environments': mat_data['test_environments'],
            'combustion_risk': mat_data['combustion_risk'],
            'test_record_count': len(mat_data['test_records'])
        }


# DETERMINISM FIX: Singleton instance for O2 engine to ensure consistent state
_O2_ENGINE_INSTANCE: Optional[OxygenCompatibilityEngine] = None
_O2_ENGINE_LOCK = threading.Lock()


def get_o2_engine(maptis_metadata_path: Optional[Path] = None,
                  o2_bok_dir: Optional[Path] = None,
                  safety_class: SafetyClass = SafetyClass.CLASS_A,
                  force_new: bool = False) -> OxygenCompatibilityEngine:
    """Factory function to get O2 engine instance.

    DETERMINISM FIX: Uses singleton pattern to ensure consistent state across
    requests. The same engine instance is reused unless force_new=True.

    Args:
        maptis_metadata_path: Path to MAPTIS metadata (ignored if using cached instance)
        o2_bok_dir: Path to O2 BOK directory (ignored if using cached instance)
        safety_class: NASA safety classification (ignored if using cached instance)
        force_new: If True, create a new instance instead of using cached one

    Returns:
        OxygenCompatibilityEngine instance (singleton unless force_new=True)
    """
    global _O2_ENGINE_INSTANCE

    if _O2_ENGINE_INSTANCE is None or force_new:
        with _O2_ENGINE_LOCK:
            if _O2_ENGINE_INSTANCE is None or force_new:
                _O2_ENGINE_INSTANCE = OxygenCompatibilityEngine(
                    maptis_metadata_path=maptis_metadata_path,
                    o2_bok_dir=o2_bok_dir,
                    safety_class=safety_class
                )
                LOGGER.info("[O2 ENGINE] Created new singleton instance")

    return _O2_ENGINE_INSTANCE
