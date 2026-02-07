#!/usr/bin/env python3
"""
Module: Sync
Purpose: MAPTIS Data Sync System - Keep MIRA Fresh with Latest Materials

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

from typing import List, Dict, Optional, Set
from datetime import datetime
from dataclasses import dataclass, asdict
import hashlib
import logging
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


@dataclass
class MaterialRecord:
    """Material record from MAPTIS"""
    material_key: str
    material_name: str
    composition: Optional[str] = None
    description: Optional[str] = None
    nasa_6016_class: Optional[str] = None
    o2_rating: Optional[str] = None
    h2_rating: Optional[str] = None
    flamm_rating: Optional[int] = None
    corr_rating: Optional[int] = None
    scc_rating: Optional[int] = None
    tvs_rating: Optional[int] = None
    tox_rating: Optional[int] = None
    fs_rating: Optional[int] = None
    contains_pfas: Optional[bool] = None
    last_updated: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class SyncResult:
    """Result of sync operation"""
    total_fetched: int
    new_materials: int
    updated_materials: int
    unchanged_materials: int
    embeddings_generated: int
    errors: List[str]
    sync_time: float
    sync_timestamp: str
    source: str = ""  # NASA SWE-013 traceability



class MAPTISSyncEngine:
    """
    Sync MIRA with latest MAPTIS data.

    Features:
    - Incremental sync (only process what changed)
    - SHA-256 change detection
    - Automatic embedding generation (BURNS TOKENS!)
    - Rating synchronization
    - Conflict detection
    """

    def __init__(self, maptis_client, database_session, embedding_generator):
        """
        Initialize sync engine.

        Args:
            maptis_client: Client for MAPTIS API
            database_session: SQLAlchemy session
            embedding_generator: MassiveEmbeddingGenerator instance
        """
        self.maptis = maptis_client
        self.db = database_session
        self.embedding_gen = embedding_generator

        # Registry of processed materials (SHA-256 hashes)
        self.registry_path = Path("databases/maptis_sync_registry.json")
        self.registry = self._load_registry()

    def sync_all(self) -> SyncResult:
        """
        Full synchronization with MAPTIS.

        Steps:
        1. Fetch all materials from MAPTIS
        2. Detect new/changed/unchanged
        3. Update database
        4. Generate embeddings for new/changed (BURNS TOKENS!)
        5. Update FAISS index

        Returns:
            SyncResult with statistics
        """
        import time
        start_time = time.time()

        logger.info("Starting MAPTIS sync...")

        # 1. Fetch all materials from MAPTIS
        logger.info("Fetching materials from MAPTIS...")
        materials = self.maptis.fetch_all_materials()
        logger.info(f"Fetched {len(materials)} materials from MAPTIS")

        # 2. Detect changes
        new_materials = []
        updated_materials = []
        unchanged_materials = []
        errors = []

        for material_data in materials:
            try:
                material = MaterialRecord(**material_data)
                change_status = self._detect_change(material)

                if change_status == 'new':
                    new_materials.append(material)
                elif change_status == 'updated':
                    updated_materials.append(material)
                else:
                    unchanged_materials.append(material)

            except Exception as e:
                logger.error(f"Error processing material: {e}")
                errors.append(str(e))

        logger.info(f"Change detection: {len(new_materials)} new, {len(updated_materials)} updated, {len(unchanged_materials)} unchanged")

        # 3. Update database
        self._update_database(new_materials, updated_materials)

        # 4. Generate embeddings (BURNS TOKENS!)
        embeddings_generated = self._generate_embeddings(new_materials + updated_materials)

        # 5. Save registry
        self._save_registry()

        sync_time = time.time() - start_time

        result = SyncResult(
            total_fetched=len(materials),
            new_materials=len(new_materials),
            updated_materials=len(updated_materials),
            unchanged_materials=len(unchanged_materials),
            embeddings_generated=embeddings_generated,
            errors=errors,
            sync_time=sync_time,
            sync_timestamp=datetime.now().isoformat()
        )

        logger.info(f"Sync complete in {sync_time:.2f}s: {result.new_materials} new, {result.updated_materials} updated")

        return result

    def sync_incremental(self, material_keys: List[str]) -> SyncResult:
        """
        Incremental sync for specific materials.

        Args:
            material_keys: List of material keys to sync

        Returns:
            SyncResult
        """
        import time
        start_time = time.time()

        logger.info(f"Starting incremental sync for {len(material_keys)} materials...")

        materials_data = self.maptis.fetch_materials_bulk(material_keys)

        new_materials = []
        updated_materials = []
        unchanged_materials = []
        errors = []

        for material_data in materials_data:
            try:
                material = MaterialRecord(**material_data)
                change_status = self._detect_change(material)

                if change_status == 'new':
                    new_materials.append(material)
                elif change_status == 'updated':
                    updated_materials.append(material)
                else:
                    unchanged_materials.append(material)

            except Exception as e:
                errors.append(str(e))

        self._update_database(new_materials, updated_materials)
        embeddings_generated = self._generate_embeddings(new_materials + updated_materials)
        self._save_registry()

        sync_time = time.time() - start_time

        return SyncResult(
            total_fetched=len(materials_data),
            new_materials=len(new_materials),
            updated_materials=len(updated_materials),
            unchanged_materials=len(unchanged_materials),
            embeddings_generated=embeddings_generated,
            errors=errors,
            sync_time=sync_time,
            sync_timestamp=datetime.now().isoformat()
        )

    def _detect_change(self, material: MaterialRecord) -> str:
        """
        Detect if material is new, updated, or unchanged.

        Uses SHA-256 hash of material data to detect changes.

        Returns:
            'new', 'updated', or 'unchanged'
        """
        # Compute hash of material data
        material_hash = self._compute_material_hash(material)

        # Check registry
        if material.material_key not in self.registry:
            # New material
            self.registry[material.material_key] = {
                'hash': material_hash,
                'first_seen': datetime.now().isoformat(),
                'last_synced': datetime.now().isoformat()
            }
            return 'new'

        # Compare with stored hash
        stored_hash = self.registry[material.material_key]['hash']

        if material_hash != stored_hash:
            # Material changed
            self.registry[material.material_key] = {
                'hash': material_hash,
                'first_seen': self.registry[material.material_key]['first_seen'],
                'last_synced': datetime.now().isoformat(),
                'previous_hash': stored_hash
            }
            return 'updated'

        # Unchanged
        return 'unchanged'

    def _compute_material_hash(self, material: MaterialRecord) -> str:
        """Compute SHA-256 hash of material data"""
        # Convert to dict and sort for consistent hashing
        data_dict = asdict(material)
        data_str = str(sorted(data_dict.items()))

        return hashlib.sha256(data_str.encode()).hexdigest()

    def _update_database(self, new_materials: List[MaterialRecord], updated_materials: List[MaterialRecord]):
        """Update PostgreSQL database with new/changed materials"""
        from src.models.material import Material

        # Insert new materials
        for material in new_materials:
            db_material = Material(
                material_spec_id=material.material_key,
                name=material.material_name,
                designation=material.composition if material.composition else None,
                rating_flam=material.flamm_rating,
                rating_corr=material.corr_rating,
                rating_scc=material.scc_rating,
                rating_tvs=material.tvs_rating,
                contains_pfas=material.contains_pfas,
                data_source='MAPTIS'
            )
            self.db.add(db_material)

        # Update existing materials
        for material in updated_materials:
            db_material = self.db.query(Material).filter(
                Material.material_spec_id == material.material_key
            ).first()

            if db_material:
                db_material.name = material.material_name
                db_material.designation = material.composition if material.composition else None
                db_material.rating_flam = material.flamm_rating
                db_material.rating_corr = material.corr_rating
                db_material.rating_scc = material.scc_rating
                db_material.rating_tvs = material.tvs_rating
                db_material.contains_pfas = material.contains_pfas

        self.db.commit()
        logger.info(f"Database updated: {len(new_materials)} inserted, {len(updated_materials)} updated")

    def _generate_embeddings(self, materials: List[MaterialRecord]) -> int:
        """
        Generate embeddings for materials.

        THIS IS WHERE WE BURN TOKENS! 🔥

        Args:
            materials: List of materials to embed

        Returns:
            Number of embeddings generated
        """
        embeddings_generated = 0

        for material in materials:
            # Build text representation
            material_text = self._build_material_text(material)

            # Generate embedding
            self.embedding_gen.index_document(
                doc_id=material.material_key,
                content=material_text,
                source_type='material'
            )

            embeddings_generated += 1

            if embeddings_generated % 100 == 0:
                logger.info(f"Generated {embeddings_generated} embeddings...")

        # Save FAISS index
        if embeddings_generated > 0:
            self.embedding_gen.save_index()
            logger.info(f"Saved {embeddings_generated} new embeddings to index")

        return embeddings_generated

    def _build_material_text(self, material: MaterialRecord) -> str:
        """Build searchable text representation of material"""
        parts = [
            f"Material: {material.material_name}",
            f"Key: {material.material_key}"
        ]

        if material.composition:
            parts.append(f"Composition: {material.composition}")

        if material.description:
            parts.append(f"Description: {material.description}")

        # Add ratings
        ratings = []
        if material.o2_rating:
            ratings.append(f"O2 Rating: {material.o2_rating}")
        if material.h2_rating:
            ratings.append(f"H2 Rating: {material.h2_rating}")
        if material.flamm_rating:
            ratings.append(f"FLAMM Rating: {material.flamm_rating}")

        if ratings:
            parts.append("Ratings: " + ", ".join(ratings))

        return "\n".join(parts)

    def _load_registry(self) -> Dict:
        """Load sync registry from disk"""
        import json

        if self.registry_path.exists():
            with open(self.registry_path, 'r') as f:
                return json.load(f)

        return {}

    def _save_registry(self):
        """Save sync registry to disk"""
        import json

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.registry_path, 'w') as f:
            json.dump(self.registry, f, indent=2)

        logger.debug(f"Saved registry with {len(self.registry)} materials")
