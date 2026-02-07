#!/usr/bin/env python3
"""
Module: Mua Precedent Lookup
Purpose: MUA Precedent Lookup - Find similar historic MUAs for new MUA generation.

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

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# Path to extracted MUA data
MUA_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "mua_v6_parsed_results.jsonl"


@dataclass
class MUAPrecedent:
    """A historic MUA that can serve as precedent."""
    file: str
    material_designation: str
    environment: Optional[str]
    application: Optional[str]
    rationale: Optional[str]
    determination: str
    category: Optional[str]
    mua_number: Optional[str]
    match_score: float = 0.0


class MUAPrecedentLookup:
    """Find historic MUA precedents for material/environment combinations."""

    def __init__(self, data_path: Path = MUA_DATA_PATH):
        self.muas: List[Dict[str, Any]] = []
        self._load_data(data_path)

    def _load_data(self, data_path: Path):
        """Load extracted MUA data from JSONL."""
        if not data_path.exists():
            raise FileNotFoundError(f"MUA data not found: {data_path}")

        with open(data_path, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                # Only include successful extractions with materials
                if record.get("success") and record.get("material_designation"):
                    self.muas.append(record)

        print(f"Loaded {len(self.muas)} MUAs with material designations")

    def _normalize_material(self, material: str) -> str:
        """Normalize material name for matching."""
        if not material:
            return ""
        # Uppercase, remove extra spaces, common variations
        m = material.upper().strip()
        m = re.sub(r'\s+', ' ', m)
        # Normalize common variations
        m = m.replace("STAINLESS STEEL", "SST")
        m = m.replace("CRES", "SST")
        m = m.replace("INCONEL", "INC")
        m = m.replace("ALUMINUM", "AL")
        m = m.replace("ALUMINIUM", "AL")
        return m

    def _extract_alloy_numbers(self, material: str) -> List[str]:
        """Extract numeric alloy identifiers from material name."""
        if not material:
            return []
        # Find common patterns: 304, 316L, 7075, 625, 718, A286, etc.
        patterns = [
            r'\b(\d{3,4}[A-Z]?)\b',  # 304, 316L, 7075
            r'\bA-?(\d{3})\b',        # A286, A-286
            r'\bN\d{5}\b',            # N06625 (UNS)
            r'\bS\d{5}\b',            # S30400 (UNS)
        ]
        alloys = []
        for pattern in patterns:
            matches = re.findall(pattern, material.upper())
            alloys.extend(matches)
        return alloys

    def _calculate_match_score(
        self,
        query_material: str,
        query_env: Optional[str],
        mua: Dict[str, Any]
    ) -> float:
        """Calculate match score between query and historic MUA."""
        score = 0.0

        mua_material = mua.get("material_designation", "")
        mua_env = mua.get("environment", "")

        # Normalize
        q_mat = self._normalize_material(query_material)
        m_mat = self._normalize_material(mua_material)

        # Exact match
        if q_mat == m_mat:
            score += 1.0
        # Substring match
        elif q_mat in m_mat or m_mat in q_mat:
            score += 0.7
        else:
            # Alloy number match
            q_alloys = set(self._extract_alloy_numbers(query_material))
            m_alloys = set(self._extract_alloy_numbers(mua_material))
            if q_alloys and m_alloys and q_alloys & m_alloys:
                score += 0.5

        # Environment match bonus
        if query_env and mua_env:
            q_env = query_env.upper()
            m_env = mua_env.upper()
            if q_env in m_env or m_env in q_env:
                score += 0.3
            elif any(kw in m_env for kw in q_env.split()):
                score += 0.1

        # Bonus for having rationale (more useful precedent)
        if mua.get("rationale"):
            score += 0.1

        # Bonus for approved (safer precedent)
        if mua.get("determination") == "APPROVED":
            score += 0.05

        return score

    def find_precedents(
        self,
        material: str,
        environment: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
        min_score: float = 0.3
    ) -> List[MUAPrecedent]:
        """
        Find historic MUA precedents for a material/environment.

        Args:
            material: Material designation to search for
            environment: Optional environment (O2, vacuum, etc.)
            category: Optional MUA category (I, II, III)
            limit: Max number of results
            min_score: Minimum match score to include

        Returns:
            List of MUAPrecedent objects sorted by match score
        """
        results = []

        for mua in self.muas:
            # Filter by category if specified
            if category and mua.get("category") != category:
                continue

            score = self._calculate_match_score(material, environment, mua)

            if score >= min_score:
                results.append(MUAPrecedent(
                    file=mua.get("file", ""),
                    material_designation=mua.get("material_designation", ""),
                    environment=mua.get("environment"),
                    application=mua.get("application"),
                    rationale=mua.get("rationale"),
                    determination=mua.get("determination", "UNKNOWN"),
                    category=mua.get("category"),
                    mua_number=mua.get("mua_number"),
                    match_score=score,
                ))

        # Sort by score descending
        results.sort(key=lambda x: x.match_score, reverse=True)

        return results[:limit]

    def generate_rationale_draft(
        self,
        material: str,
        environment: str,
        application: str,
        precedents: List[MUAPrecedent]
    ) -> str:
        """
        Generate a draft rationale based on precedent MUAs.

        Returns a template that can be reviewed and customized.
        """
        if not precedents:
            return "No precedents found. Manual rationale required."

        # Find best precedent
        best = precedents[0]

        draft = f"""DRAFT RATIONALE (Based on {len(precedents)} precedent MUAs)

Primary Precedent: {best.file} (Score: {best.match_score:.2f})
  Material: {best.material_designation}
  Environment: {best.environment}
  Determination: {best.determination}

---
PRECEDENT RATIONALE:
{best.rationale or 'N/A'}
---

SUGGESTED APPROACH FOR NEW MUA:

1. Material: {material}
2. Environment: {environment}
3. Application: {application}

Based on precedent {best.file}, consider the following points:
- [Review precedent rationale above and adapt for current application]
- [Verify material compatibility data is current]
- [Check for any updated test requirements]

Additional Precedents for Reference:
"""
        for i, p in enumerate(precedents[1:4], 2):
            draft += f"\n{i}. {p.file} - {p.material_designation} ({p.determination})"

        return draft


# Convenience function
def find_mua_precedents(
    material: str,
    environment: Optional[str] = None,
    limit: int = 5
) -> List[MUAPrecedent]:
    """Quick lookup of MUA precedents."""
    lookup = MUAPrecedentLookup()
    return lookup.find_precedents(material, environment, limit=limit)


if __name__ == "__main__":
    # Test the lookup
    lookup = MUAPrecedentLookup()

    test_cases = [
        ("INCONEL 625", "Oxygen"),
        ("304 SST", "Vacuum"),
        ("A286 CRES", None),
        ("7075 Aluminum", None),
        ("Vespel SP-21", "Oxygen"),
    ]

    for material, env in test_cases:
        print(f"\n{'='*60}")
        print(f"Query: {material}" + (f" in {env}" if env else ""))
        print("="*60)

        precedents = lookup.find_precedents(material, env, limit=3)

        if not precedents:
            print("No precedents found")
            continue

        for i, p in enumerate(precedents, 1):
            print(f"\n{i}. {p.file} (Score: {p.match_score:.2f})")
            print(f"   Material: {p.material_designation}")
            print(f"   Environment: {p.environment}")
            print(f"   Determination: {p.determination}")
            if p.rationale:
                print(f"   Rationale: {p.rationale[:200]}...")
