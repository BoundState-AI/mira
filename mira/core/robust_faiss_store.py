#!/usr/bin/env python3
"""
Module: Robust Faiss Store
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

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
import os
import numpy as np
from typing import List, Dict, Any, Optional
import re

logger = logging.getLogger(__name__)

try:
    import faiss
    from sentence_transformers import SentenceTransformer
    HAS_FAISS = True
except ImportError:
    faiss = None
    SentenceTransformer = None
    HAS_FAISS = False

from mira.core.material_name_normalizer import MaterialNameNormalizer, RobustMaterialSearch

class RobustMAPTISFaissStore:
    def __init__(self, index_path: str = "maptis_faiss_db"):
        self.index_path = index_path
        self.index = None
        self.metadata = None
        self.model = None
        
        # Initialize robust name matching
        self.name_normalizer = MaterialNameNormalizer()
        self.robust_search = RobustMaterialSearch(self.name_normalizer)
        
        self.metal_patterns = [
            r'\b(aluminum|aluminium)\b', r'\btitanium\b', r'\bsteel\b', r'\bcopper\b',
            r'\bberyllium\b', r'\bnickel\b', r'\biron\b', r'\bbronze\b', r'\bbrass\b',
            r'\binconel\b', r'\bhastelloy\b', r'\bmonel\b', r'\balloy\b',
            r'\bss\s*\d+\b', r'\bal\s*\d+\b', r'\bti\s*\d+\b'
        ]
        
        self.polymer_patterns = [
            r'\bpolyimide\b', r'\bkapton\b', r'\bptfe\b', r'\bteflon\b', r'\bviton\b',
            r'\brubber\b', r'\bsilicone\b', r'\bpeek\b', r'\bpolyethylene\b', r'\bpvc\b',
            r'\bepr\b', r'\bkalrez\b', r'\bfep\b', r'\bpfa\b', r'\bpolymer\b'
        ]
        
        self.outgassing_keywords = [
            'outgas', 'outgassing', 'tml', 'cvcm', 'vcm', 'vacuum', 'space',
            'volatile', 'condensable', 'mass loss', 'low emission'
        ]
        
        self.thermal_keywords = [
            'thermal', 'conductivity', 'insulation', 'insulative', 'heat'
        ]
        
        self.mechanical_keywords = [
            'strength', 'tensile', 'mechanical', 'impact', 'fatigue', 'fracture'
        ]
        
    def load_index(self):
        try:
            index_file = os.path.join(self.index_path, "index.faiss")
            if os.path.exists(index_file):
                self.index = faiss.read_index(index_file)
                logger.info("Loaded FAISS index with %d vectors", self.index.ntotal)
            else:
                logger.error("FAISS index not found: %s", index_file)
                return False
            
            metadata_file = os.path.join(self.index_path, "metadata.json")
            if os.path.exists(metadata_file):
                with open(metadata_file, "r") as f:
                    self.metadata = json.load(f)
                # Handle wrapped format: {"metadata": [...]}
                if isinstance(self.metadata, dict) and "metadata" in self.metadata:
                    wrapped = self.metadata.get("metadata")
                    if isinstance(wrapped, list):
                        self.metadata = wrapped
                logger.info("Loaded metadata for %s materials", len(self.metadata) if isinstance(self.metadata, list) else "unknown")
            else:
                # Fallback: construct metadata from available lookup and id mapping
                lookup_file = os.path.join(self.index_path, "materials_lookup.json")
                id_map_file = os.path.join(self.index_path, "material_id_mapping.json")
                if os.path.exists(lookup_file) and os.path.exists(id_map_file):
                    try:
                        with open(lookup_file, "r") as f:
                            lookup = json.load(f)
                        with open(id_map_file, "r") as f:
                            id_map = json.load(f)
                        ids = id_map.get("material_ids") or []
                        if not isinstance(ids, list) or not ids:
                            raise ValueError("material_id_mapping.json missing 'material_ids' list")
                        # Build list aligned to FAISS rows; ensure each entry is a dict
                        built = []
                        for mid in ids:
                            rec = lookup.get(mid) if isinstance(lookup, dict) else None
                            if isinstance(rec, dict):
                                built.append(rec)
                            else:
                                built.append({"material_id": mid, "name": mid})
                        self.metadata = built
                        logger.warning(
                            "metadata.json not found; built metadata from lookup + id map: %d entries",
                            len(self.metadata),
                        )
                    except Exception as e:
                        logger.error("Failed to build metadata from fallbacks: %s", e)
                        return False
                else:
                    logger.error("Metadata not found and no fallbacks present: %s", metadata_file)
                    return False
            
            self.model = SentenceTransformer("all-mpnet-base-v2")
            logger.info("Loaded embedding model")

            return True

        except Exception as e:
            logger.error("Error loading index: %s", e)
            return False
    
    def classify_material_type(self, material_name: str, test_types: List[str] = None) -> str:
        if not material_name:
            return 'unknown'
            
        name_lower = material_name.lower()
        
        # Superalloy specific check
        superalloy_keywords = ['inconel', 'hastelloy', 'monel', 'superalloy', 'in718', 'in 718', 'in-718', 'ni-based']
        if any(word in name_lower for word in superalloy_keywords):
            return 'ni-based superalloy'
        
        # Aluminum alloy specific
        if 'aluminum' in name_lower or 'aluminium' in name_lower or re.search(r'\b[2-7]\d{3}\b', name_lower):
            return 'aluminum alloy'
        
        # Titanium alloy
        if 'titanium' in name_lower or re.search(r'\bti[-\s]\d', name_lower):
            return 'titanium alloy'
        
        # Steel alloy
        if 'steel' in name_lower or 'stainless' in name_lower or 'ss' in name_lower or 'carbon steel' in name_lower:
            return 'steel alloy'
        
        # Other metals
        for pattern in self.metal_patterns:
            if re.search(pattern, name_lower, re.IGNORECASE):
                return 'metal'
        
        for pattern in self.polymer_patterns:
            if re.search(pattern, name_lower, re.IGNORECASE):
                return 'polymer'
        
        if any(word in name_lower for word in ['composite', 'fiber', 'carbon', 'glass', 'graphite']):
            return 'composite'
        
        if any(word in name_lower for word in ['ceramic', 'alumina', 'zirconia', 'carbide']):
            return 'ceramic'
        
        if test_types:
            if any('outgassing' in test_type for test_type in test_types):
                return 'polymer'
            elif any(test in test_types for test in ['corrosion', 'stress_corrosion_cracking']):
                return 'metal'
        
        return 'unknown'
    
    def detect_query_context(self, query: str) -> str:
        query_lower = query.lower()
        
        if any(keyword in query_lower for keyword in self.outgassing_keywords):
            return 'outgassing'
        
        if any(keyword in query_lower for keyword in self.thermal_keywords):
            return 'thermal'
        
        if any(keyword in query_lower for keyword in self.mechanical_keywords):
            return 'mechanical'
        
        if any(keyword in query_lower for keyword in ['electrical', 'dielectric', 'insulation', 'arc']):
            return 'electrical'
        
        return 'general'
    
    def should_exclude_material(self, material: Dict, query_context: str) -> bool:
        material_name = material.get('name') or material.get('designation') or material.get('Designation') or ''
        material_type = self.classify_material_type(material_name)

        if query_context == 'outgassing':
            # Don't exclude VCM Optical test records - they're valid outgassing-related tests
            test_type = material.get('test_type', '')
            if 'vcm' in test_type.lower():
                return False

            # Exclude metals and ceramics from outgassing queries (they don't outgas)
            if material_type in ['metal', 'ceramic']:
                return True

            # Check if material has ANY outgassing-related data
            # TVS outgassing tests use different field names: tvs_mlw, tvs_cvcm, tvs_rating, etc.
            payload = material.get('payload', {}) if isinstance(material.get('payload'), dict) else {}

            # Check for standard field names (tml_pct, cvcm_pct)
            has_standard_fields = (
                material.get('tml_pct') is not None or
                material.get('cvcm_pct') is not None
            )

            # Check for TVS-specific field names in payload
            has_tvs_fields = (
                payload.get('tvs_mlw') is not None or
                payload.get('tvs_cvcm') is not None or
                payload.get('tvs_rating') is not None or
                payload.get('tvs_wvr') is not None or
                payload.get('tml') is not None or
                payload.get('cvcm') is not None
            )

            # Only exclude if NEITHER standard NOR TVS fields are present
            if not has_standard_fields and not has_tvs_fields:
                return True

        elif query_context == 'thermal':
            pass

        elif query_context == 'mechanical':
            pass

        return False
    
    def search_robust(self, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """Search with robust name matching and query expansion"""
        if not self.index or not self.metadata or not self.model:
            print("[ERROR] Index not loaded. Call load_index() first.")
            return []
        
        # Use robust search with query expansion
        results = self.robust_search.search(query, self, top_k)
        
        # Apply filters if provided (lenient: missing values do not auto-exclude)
        if filters:
            filtered_results = []
            for result in results:
                meets_criteria = True
                for field, constraint in filters.items():
                    # Skip criterion if field is missing/unknown
                    rv = result.get(field)
                    if rv is None or rv == "" or (isinstance(rv, str) and rv.upper() == "NULL"):
                        continue

                    # Coerce numeric comparisons where possible
                    op = constraint.get("op", "=")
                    value = constraint.get("value")
                    rnum = rv
                    vnum = value
                    try:
                        if isinstance(rv, str):
                            rnum = float(rv)
                        if isinstance(value, str):
                            vnum = float(value)
                    except Exception:
                        # If cannot coerce, skip this criterion
                        continue

                    if op == "<" and not (rnum < vnum):
                        meets_criteria = False
                        break
                    elif op == "<=" and not (rnum <= vnum):
                        meets_criteria = False
                        break
                    elif op == ">" and not (rnum > vnum):
                        meets_criteria = False
                        break
                    elif op == ">=" and not (rnum >= vnum):
                        meets_criteria = False
                        break
                    elif op == "=" and not (rnum == vnum):
                        meets_criteria = False
                        break
                if meets_criteria:
                    filtered_results.append(result)
            return filtered_results[:top_k]
        
        return results

    def search(self, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        if not self.index or not self.metadata or not self.model:
            print("[ERROR] Index not loaded. Call load_index() first.")
            return []
        
        try:
            query_context = self.detect_query_context(query)
            print(f"[SEARCH] Detected query context: {query_context}")
            
            # Normalize query embedding for better IP/L2 compatibility
            try:
                query_embedding = self.model.encode(query, normalize_embeddings=True)
            except TypeError:
                query_embedding = self.model.encode(query)
                q = np.array([query_embedding], dtype="float32")
                try:
                    import faiss as _fa
                    _fa.normalize_L2(q)
                    query_embedding = q[0]
                except Exception:
                    pass
            query_vector = np.array([query_embedding], dtype="float32")
            
            if filters:
                search_k = min(self.index.ntotal, 1000)
            else:
                search_k = min(top_k * 10, self.index.ntotal)
            distances, indices = self.index.search(query_vector, search_k)
            
            print("[SEARCH] Top raw indices from FAISS:", indices[0][:5])
            print("[SEARCH] Top distances from FAISS:", distances[0][:5])
            def _safe_name(entry: Dict[str, Any]) -> str:
                return (
                    entry.get('name')
                    or entry.get('designation')
                    or entry.get('Designation')
                    or entry.get('composition')
                    or str(entry.get('material_id', 'Unknown'))
                )
            # Debug names print disabled due to Unicode issues on Windows
            # debug_names = [
            #     _safe_name(self.metadata[int(idx)]) if 0 <= int(idx) < len(self.metadata) else 'Invalid idx'
            #     for idx in indices[0][:5]
            # ]
            # print("[SEARCH] Top names from metadata lookup:", debug_names)
            
            candidates = []
            excluded_count = 0
            
            for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
                idx = int(idx)
                if 0 <= idx < len(self.metadata):
                    material = self.metadata[idx].copy()
                    
                    if self.should_exclude_material(material, query_context):
                        excluded_count += 1
                        continue
                    
                    # FIX: Convert L2 distance to similarity score (0 to 1)
                    # FAISS returns L2 distances. For normalized vectors, max distance is 2.0
                    # Convert to cosine similarity: distance² = 2(1 - cosine_similarity)
                    # So: cosine_similarity ≈ 1 - (distance² / 2)
                    try:
                        import faiss as _fa
                        is_ip = hasattr(self.index, 'metric_type') and self.index.metric_type == _fa.METRIC_INNER_PRODUCT
                    except Exception:
                        is_ip = False
                    if is_ip:
                        similarity = float(distance)
                        similarity = max(0.0, min(1.0, similarity))
                    else:
                        similarity = float(1.0 - (distance * distance / 2.0))
                        similarity = max(0.0, min(1.0, similarity))  # Clamp to [0, 1]
                    
                    material["similarity"] = similarity
                    material["rank"] = i
                    candidates.append(material)
                else:
                    print(f"[ERROR] Invalid index from FAISS: {idx}")
            
            print(f"[SEARCH] Found {len(candidates)} candidates ({excluded_count} excluded by context)")
            
            # Sort by similarity (highest first) before filtering
            candidates.sort(key=lambda x: x["similarity"], reverse=True)

            # Select top_k unique materials (avoid flooding with many rows of same material)
            unique_candidates = []
            seen_materials = set()
            for cand in candidates:
                mid = (
                    str(cand.get("material_id") or
                        cand.get("MaterialID") or
                        cand.get("material_key") or
                        (cand.get("payload", {}).get("materialkey") if isinstance(cand.get("payload"), dict) else None) or
                        "")
                ).strip()
                if not mid:
                    continue
                if mid in seen_materials:
                    continue
                seen_materials.add(mid)
                unique_candidates.append(cand)
                if len(unique_candidates) >= top_k:
                    break

            # If uniqueness filtering ended up empty (unlikely), fall back to top_k raw
            if not unique_candidates:
                unique_candidates = candidates[:top_k]

            # DEBUG: Check what happens after selecting uniques (disabled due to Unicode issues on Windows)
            # for i, cand in enumerate(unique_candidates[:5]):
            #     print(f"  {i}: {cand.get('name')} (similarity: {cand.get('similarity', 0):.4f})")
            
            if filters:
                filtered_candidates = []
                print(f"[SEARCH] Applying filters to {len(candidates)} candidates: {filters}")
                
                for candidate in candidates:
                    meets_criteria = True
                    debug_info = []
                    
                    for field, constraint in filters.items():
                        if field not in candidate or candidate[field] is None:
                            meets_criteria = False
                            debug_info.append(f"{field}: NULL")
                            break
                        
                        op = constraint.get("op", "=")
                        value = constraint.get("value")
                        candidate_value = candidate[field]
                        
                        if op == "<" and not (candidate_value < value):
                            meets_criteria = False
                            debug_info.append(f"{field}: {candidate_value} NOT < {value}")
                            break
                        elif op == "<=" and not (candidate_value <= value):
                            meets_criteria = False
                            debug_info.append(f"{field}: {candidate_value} NOT <= {value}")
                            break
                        elif op == ">" and not (candidate_value > value):
                            meets_criteria = False
                            debug_info.append(f"{field}: {candidate_value} NOT > {value}")
                            break
                        elif op == ">=" and not (candidate_value >= value):
                            meets_criteria = False
                            debug_info.append(f"{field}: {candidate_value} NOT >= {value}")
                            break
                        elif op == "=" and not (candidate_value == value):
                            meets_criteria = False
                            debug_info.append(f"{field}: {candidate_value} NOT = {value}")
                            break
                        else:
                            debug_info.append(f"{field}: {candidate_value} {op} {value} [OK]")
                    
                    if meets_criteria:
                        filtered_candidates.append(candidate)
                        # Debug printing disabled due to Unicode issues on Windows
                
                print(f"[SUCCESS] {len(filtered_candidates)} materials passed filters")
                candidates = filtered_candidates
            
            # Take top_k results
            candidates = candidates[:top_k]
        
            results = []
            for candidate in unique_candidates:
                # USE MATERIAL_CODE AS PRIMARY ID (not material_key!)
                # material_code is the stable 5-digit MAPTIS identifier
                # material_key is PostgreSQL internal ID - DO NOT USE
                material_id = (
                    candidate.get("material_code")
                    or candidate.get("MaterialCode")
                    or candidate.get("material_id")
                    or candidate.get("MaterialID")
                    or candidate.get("materialId")
                    or candidate.get("row_uid")
                    or candidate.get("id")
                    or "Unknown"
                )

                # Best-effort human-readable name
                material_name = (
                    candidate.get("name")
                    or candidate.get("designation")
                    or (candidate.get("preview") if isinstance(candidate.get("preview"), str) else None)
                    or candidate.get("test_type")
                    or candidate.get("composition", "Unknown Material")
                )
                if isinstance(material_name, str):
                    material_name = material_name[:100]
                
                def extract_property(obj, prop_name):
                    if not obj or not isinstance(obj, dict):
                        return None
                    
                    if prop_name in obj and obj[prop_name] is not None:
                        return obj[prop_name]
                    
                    for nested_field in ["test_results", "properties", "measured_values", "results"]:
                        if nested_field in obj and isinstance(obj[nested_field], dict):
                            nested = obj[nested_field]
                            if prop_name in nested and nested[prop_name] is not None:
                                return nested[prop_name]
                    
                    if "test_reports" in obj and isinstance(obj["test_reports"], list):
                        for report in obj["test_reports"]:
                            if isinstance(report, dict):
                                if prop_name in report and report[prop_name] is not None:
                                    return report[prop_name]
                                for nested_field in ["results", "measured_values", "data"]:
                                    if nested_field in report and isinstance(report[nested_field], dict):
                                        nested = report[nested_field]
                                        if prop_name in nested and nested[prop_name] is not None:
                                            return nested[prop_name]
                    
                    return None
                
                tml_pct = extract_property(candidate, "tml_pct")
                cvcm_pct = extract_property(candidate, "cvcm_pct")
                density = extract_property(candidate, "density_g_cm3")
                thermal_cond = extract_property(candidate, "thermal_conductivity_w_mk")
                
                result = {
                    "id": material_id,
                    "name": material_name,
                    "description": candidate.get("description") or candidate.get("original_text", ""),
                    "category": candidate.get("category") or candidate.get("material_type", ""),
                    "manufacturer": candidate.get("manufacturer", ""),
                    "specification": candidate.get("specification", ""),
                    "score": candidate.get("similarity", 0.0),
                    "test_reports": candidate.get("test_reports", []),
                    "original_material": {
                        **candidate,
                        "tml_pct": tml_pct,
                        "cvcm_pct": cvcm_pct,
                        "density_g_cm3": density,
                        "thermal_conductivity_w_mk": thermal_cond
                    }
                }

                # Derive common numeric properties for filtering when available
                try:
                    payload = candidate.get("payload") if isinstance(candidate, dict) else None
                    min_temp_c = None
                    if isinstance(payload, dict):
                        # Common field from silver payloads
                        if payload.get("temperatureminimum") not in (None, "", "NULL"):
                            try:
                                min_temp_c = float(payload.get("temperatureminimum"))
                            except Exception:
                                min_temp_c = None
                        # Fallback: Fahrenheit fields -> convert to C
                        if min_temp_c is None:
                            f_val = None
                            for k in ("temp_min_f", "temperature_minimum_f", "temperature_minimumF"):
                                if payload.get(k) not in (None, "", "NULL"):
                                    f_val = payload.get(k)
                                    break
                            if f_val is not None:
                                try:
                                    min_temp_c = (float(f_val) - 32.0) * 5.0 / 9.0
                                except Exception:
                                    min_temp_c = None
                    if min_temp_c is not None:
                        result["min_temp_c"] = min_temp_c
                except Exception:
                    pass
                
                if tml_pct is not None:
                    result["tml_pct"] = tml_pct
                if cvcm_pct is not None:
                    result["cvcm_pct"] = cvcm_pct
                if density is not None:
                    result["density_g_cm3"] = density
                if thermal_cond is not None:
                    result["thermal_conductivity_w_mk"] = thermal_cond
                    
                results.append(result)
            
            return results
            
        except Exception as e:
            print(f"[ERROR] Search error: {e}")
            import traceback
            traceback.print_exc()
            return []

def test_robust_search():
    print("[TEST] Testing Robust Search with Real-World Data Issues")
    print("=" * 65)
    
    store = RobustMAPTISFaissStore()
    
    if not store.load_index():
        print("[ERROR] Failed to load index")
        return
    
    test_cases = [
        {
            "query": "low outgassing materials",
            "description": "Should exclude metals like BeCu",
            "filters": None
        },
        {
            "query": "TML < 1.0%, CVCM < 0.1%",
            "description": "Explicit outgassing filters",
            "filters": {"tml_pct": {"op": "<", "value": 1.0}, "cvcm_pct": {"op": "<", "value": 0.1}}
        },
        {
            "query": "thermal conductivity materials",
            "description": "Should include metals (they have thermal properties)",
            "filters": None
        },
        {
            "query": "mechanical strength materials", 
            "description": "Should include metals and composites",
            "filters": None
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        query = test_case["query"]
        description = test_case["description"]
        filters = test_case["filters"]
        
        print(f"\n--- Test {i}: {description} ---")
        print(f"Query: '{query}'")
        
        results = store.search(query, top_k=5, filters=filters)
        print(f"Results: {len(results)} materials found")
        
        becu_found = any('beryllium' in result.get('name', '').lower() for result in results)
        
        if 'outgassing' in query.lower() and becu_found:
            print("[ERROR] PROBLEM: BeCu found in outgassing query!")
        elif 'outgassing' in query.lower() and not becu_found:
            print("[SUCCESS] SUCCESS: BeCu excluded from outgassing query")
        
        for j, result in enumerate(results[:3]):
            name = result.get('name', 'Unknown')
            similarity = result.get('similarity', 0)
            material_type = store.classify_material_type(name)
            print(f"  {j+1}. {name} ({material_type}) - sim: {similarity:.3f}")

if __name__ == "__main__":
    test_robust_search()
