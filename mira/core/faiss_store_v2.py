#!/usr/bin/env python3
"""
Module: Faiss Store V2
Purpose: [LEGACY] This module is deprecated and will be replaced by boundstate.core.rag.engine.

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

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

import numpy as np

try:
    import torch
    import faiss
    from sentence_transformers import SentenceTransformer
    HAS_DEPS = True
except ImportError:
    torch = None
    faiss = None
    SentenceTransformer = None
    HAS_DEPS = False

from mira.utils.exceptions import raise_safety_error, DataIntegrityError

logger = logging.getLogger(__name__)


class MAPTISFaissStoreV2:
    """Updated FAISS store that uses JSON format from rebuild_faiss.py"""
    
    def __init__(self, persist_directory: str = "./maptis_faiss_db"):
        self.persist_directory = Path(persist_directory)
        self.index = None
        self.materials = {}
        self.material_ids = []
        self.model = None
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.gpu_resources = None
        
        # Load the index and data
        self.load_index()
    
    def load_index(self) -> bool:
        """Load FAISS index and materials from new JSON format."""
        try:
            # Check if new format files exist
            index_path = self.persist_directory / "index.faiss"
            materials_path = self.persist_directory / "materials_lookup.json"
            mappings_path = self.persist_directory / "material_id_mapping.json"
            
            if not all(p.exists() for p in [index_path, materials_path, mappings_path]):
                logger.error(f"Missing files in {self.persist_directory}")
                raise_safety_error(
                    DataIntegrityError,
                    f"FAISS index files not found in {self.persist_directory}",
                    data_type="faiss_index",
                    validation_errors=["Missing index.faiss, materials_lookup.json, or material_id_mapping.json"]
                )
            
            logger.info(f"Loading FAISS index from {self.persist_directory}...")
            
            # Load materials lookup
            with open(materials_path, 'r', encoding='utf-8') as f:
                self.materials = json.load(f)
            
            # Load mappings
            with open(mappings_path, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
                self.material_ids = mappings['material_ids']
                self.embedding_dim = mappings['embedding_dim']
                self.model_name = mappings['model_name']
            
            # Load FAISS index
            self.index = faiss.read_index(str(index_path))
            
            # Initialize embedding model
            self.model = SentenceTransformer(self.model_name, device=str(self.device))
            
            # Transfer index to GPU if available
            if torch.cuda.is_available() and hasattr(faiss, 'StandardGpuResources'):
                try:
                    self.gpu_resources = faiss.StandardGpuResources()
                    self.index = faiss.index_cpu_to_gpu(self.gpu_resources, 0, self.index)
                    logger.info("✅ FAISS GPU index loaded")
                except Exception as e:
                    logger.warning(f"Failed to load GPU index: {e}")
                    self.gpu_resources = None
            
            logger.info(f"✅ Loaded {len(self.materials)} materials")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            return False
    
    def search(self, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Search using the new index format."""
        if not self.index or not self.materials:
            return []
        
        try:
            # Encode query - IMPORTANT: normalize for IndexFlatIP
            query_embedding = self.model.encode([query], normalize_embeddings=True)
            
            # Search (IndexFlatIP returns similarity scores, not distances)
            similarities, indices = self.index.search(query_embedding, min(top_k, len(self.material_ids)))
            
            results = []
            for idx, similarity in zip(indices[0], similarities[0]):
                if idx >= len(self.material_ids) or idx < 0:
                    continue
                
                mat_id = self.material_ids[idx]
                material = self.materials.get(mat_id, {})
                
                # Apply filters if provided
                if filters:
                    # Check material type filter
                    if 'material_type' in filters:
                        mat_type = material.get('material_type', '').upper()
                        filter_type = filters['material_type'].upper()
                        if mat_type != filter_type:
                            continue
                    
                    # Check form filter
                    if 'form' in filters:
                        mat_form = material.get('form', '').upper()
                        filter_form = filters['form'].upper()
                        if filter_form not in mat_form:
                            continue
                
                # Build result compatible with the API
                result = {
                    "id": mat_id,  # For compatibility with existing code
                    "material_id": mat_id,
                    "MaterialID": mat_id,  # Both formats for compatibility
                    "designation": material.get('designation', ''),
                    "Designation": material.get('designation', ''),
                    "name": material.get('designation', ''),
                    "description": material.get('composition', ''),  # For backward compatibility
                    "composition": material.get('composition', ''),
                    "Composition": material.get('composition', ''),
                    "form": material.get('form', ''),
                    "Form": material.get('form', ''),
                    "manufacturer": material.get('manufacturer', ''),
                    "Manufacturer": material.get('manufacturer', ''),
                    "material_type": material.get('material_type', ''),
                    "MaterialType": material.get('material_type', ''),
                    "category": material.get('material_type', ''),  # For compatibility
                    "test_reports": material.get('test_reports', []),
                    "TestReports": material.get('test_reports', []),
                    "similarity_score": float(similarity),  # Already a similarity score
                    "SimilarityScore": float(similarity),
                    "score": float(similarity)  # For backward compatibility
                }
                
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def classify_material_type(self, designation: str) -> str:
        """Classify material type based on designation."""
        # Simple classification logic - can be enhanced
        designation_lower = designation.lower()
        
        if any(metal in designation_lower for metal in ['aluminum', 'steel', 'titanium', 'copper', 'nickel', 'iron']):
            return 'METAL'
        elif any(polymer in designation_lower for polymer in ['kapton', 'teflon', 'viton', 'polyimide', 'rubber', 'plastic']):
            return 'POLYMER'
        elif any(ceramic in designation_lower for ceramic in ['ceramic', 'glass', 'silica']):
            return 'CERAMIC'
        elif any(comp in designation_lower for comp in ['composite', 'carbon fiber', 'fiberglass']):
            return 'COMPOSITE'
        else:
            return 'OTHER'
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the index."""
        return {
            "total_materials": len(self.materials),
            "index_size": self.index.ntotal if self.index else 0,
            "embedding_dim": getattr(self, 'embedding_dim', None),
            "model_name": getattr(self, 'model_name', None),
            "gpu_enabled": self.gpu_resources is not None
        }