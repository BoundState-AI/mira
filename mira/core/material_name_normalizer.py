#!/usr/bin/env python3
"""
Module: Material Name Normalizer
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

import re
from difflib import SequenceMatcher
from typing import List, Dict, Set
import unicodedata

class MaterialNameNormalizer:
    """Handles all variations of material names"""
    
    def __init__(self):
        # Common material name variations and aliases
        self.aliases = {
            'kapton': ['kapton', 'kapton hn', 'kapton-hn', 'dupont kapton', 'polyimide kapton'],
            'teflon': ['teflon', 'ptfe', 'polytetrafluoroethylene', 'teflon ptfe'],
            'viton': ['viton', 'fkm', 'fluoroelastomer', 'viton fluoroelastomer'],
            'peek': ['peek', 'polyetheretherketone', 'victrex peek'],
            'delrin': ['delrin', 'pom', 'acetal', 'polyoxymethylene'],
            'nylon': ['nylon', 'pa', 'polyamide', 'nylon 6', 'nylon 66', 'nylon 6/6'],
            'buna-n': ['buna-n', 'buna n', 'nbr', 'nitrile', 'nitrile rubber', 'acrylonitrile butadiene'],
        }
        
        # Build reverse mapping
        self.name_to_canonical = {}
        for canonical, variations in self.aliases.items():
            for var in variations:
                self.name_to_canonical[self.normalize_basic(var)] = canonical
    
    def normalize_basic(self, text: str) -> str:
        """Basic normalization: lowercase, remove special chars, collapse spaces"""
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove apostrophes and quotes
        text = text.replace("'", "").replace('"', '')
        
        # Replace hyphens and underscores with spaces
        text = text.replace('-', ' ').replace('_', ' ')
        
        # Remove other special characters but keep alphanumeric and spaces
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        
        # Collapse multiple spaces
        text = ' '.join(text.split())
        
        return text.strip()
    
    def normalize_advanced(self, text: str) -> str:
        """Advanced normalization with unicode handling"""
        # Handle unicode
        text = unicodedata.normalize('NFKD', text)
        text = text.encode('ascii', 'ignore').decode('ascii')
        
        # Basic normalization
        text = self.normalize_basic(text)
        
        # Remove common suffixes/prefixes
        text = re.sub(r'\b(inc|corp|corporation|company|co)\b', '', text)
        text = re.sub(r'\b(tm|®|©)\b', '', text)
        
        return ' '.join(text.split()).strip()
    
    def get_canonical_name(self, material_name: str) -> str:
        """Get the canonical version of a material name"""
        normalized = self.normalize_basic(material_name)
        
        # Check exact match first
        if normalized in self.name_to_canonical:
            return self.name_to_canonical[normalized]
        
        # Check partial matches
        for norm_var, canonical in self.name_to_canonical.items():
            if norm_var in normalized or normalized in norm_var:
                return canonical
        
        # Return original if no match found
        return material_name
    
    def calculate_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two material names"""
        # Normalize both
        norm1 = self.normalize_advanced(name1)
        norm2 = self.normalize_advanced(name2)
        
        # Exact match after normalization
        if norm1 == norm2:
            return 1.0
        
        # Check if they map to same canonical name
        canon1 = self.get_canonical_name(name1)
        canon2 = self.get_canonical_name(name2)
        if canon1 == canon2:
            return 0.95
        
        # Token-based similarity
        tokens1 = set(norm1.split())
        tokens2 = set(norm2.split())
        
        if tokens1 and tokens2:
            intersection = len(tokens1 & tokens2)
            union = len(tokens1 | tokens2)
            jaccard = intersection / union if union > 0 else 0
            
            # Boost score if key material words match
            key_materials = {'kapton', 'teflon', 'viton', 'peek', 'nylon', 'delrin'}
            if (tokens1 & key_materials) == (tokens2 & key_materials) and (tokens1 & key_materials):
                jaccard = min(1.0, jaccard + 0.2)
            
            # Use combination of Jaccard and sequence matching
            sequence_sim = SequenceMatcher(None, norm1, norm2).ratio()
            return 0.6 * jaccard + 0.4 * sequence_sim
        
        # Fallback to sequence matching
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def find_matches(self, query: str, candidates: List[str], threshold: float = 0.8) -> List[tuple]:
        """Find all candidates that match the query above threshold"""
        matches = []
        for candidate in candidates:
            score = self.calculate_similarity(query, candidate)
            if score >= threshold:
                matches.append((candidate, score))
        
        # Sort by score descending
        return sorted(matches, key=lambda x: x[1], reverse=True)


# Integration with FAISS search
class RobustMaterialSearch:
    def __init__(self, normalizer: MaterialNameNormalizer):
        self.normalizer = normalizer
    
    def preprocess_query(self, query: str) -> List[str]:
        """Generate query variations for better matching"""
        normalized = self.normalizer.normalize_basic(query)
        canonical = self.normalizer.get_canonical_name(query)
        
        # Generate variations
        variations = [query, normalized]
        if canonical != query:
            variations.append(canonical)
        
        # Add known aliases
        for canon, aliases in self.normalizer.aliases.items():
            if self.normalizer.normalize_basic(canon) == normalized:
                variations.extend(aliases)
        
        return list(set(variations))
    
    def search(self, query: str, faiss_store, top_k: int = 10) -> List[Dict]:
        """Search with query expansion and fuzzy matching"""
        all_results = []
        seen_ids = set()
        
        # Try each query variation
        for variation in self.preprocess_query(query):
            results = faiss_store.search(variation, top_k=top_k * 2)
            
            for result in results:
                if result['id'] not in seen_ids:
                    # Recalculate similarity with our robust matcher
                    result['robust_score'] = self.normalizer.calculate_similarity(
                        query, result['name']
                    )
                    all_results.append(result)
                    seen_ids.add(result['id'])
        
        # Sort by robust score
        all_results.sort(key=lambda x: x['robust_score'], reverse=True)
        
        # Filter by threshold and return top_k
        threshold = 0.7  # Adjust as needed
        filtered = [r for r in all_results if r['robust_score'] >= threshold]
        
        return filtered[:top_k]


# Test the system
def test_robust_matching():
    normalizer = MaterialNameNormalizer()
    
    test_cases = [
        ("KAPTON", "kapton"),
        ("Kapton", "KAPTON HN"),
        ("KaPtOn", "DuPont Kapton"),
        ("kapton polyimide", "Kapton"),
        ("TEFLON", "PTFE"),
        ("Teflon PTFE", "teflon"),
        ("Viton®", "VITON FLUOROELASTOMER"),
        ("Buna N", "Buna-N"),
        ("buna-n", "NBR"),
        ("Delrin", "POM"),
    ]
    
    print("Material Name Matching Tests:")
    print("=" * 60)
    
    for name1, name2 in test_cases:
        score = normalizer.calculate_similarity(name1, name2)
        canon1 = normalizer.get_canonical_name(name1)
        canon2 = normalizer.get_canonical_name(name2)
        
        print(f"\n'{name1}' vs '{name2}':")
        print(f"  Similarity: {score:.3f}")
        print(f"  Canonical: '{canon1}' vs '{canon2}'")
        print(f"  Match: {'[OK]' if score > 0.8 else '[FAIL]'}")


if __name__ == "__main__":
    test_robust_matching()
