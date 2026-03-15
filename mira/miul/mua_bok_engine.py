#!/usr/bin/env python3
"""
Module: Mua Bok Engine
Purpose: MUA BOK Engine V2 - Provenance-based MUA generation.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C, SWE-013 (Traceability)
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
from mira.core.safe_pickle import safe_pickle_load
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import uuid

logger = logging.getLogger(__name__)

# Default paths - use BoundState location first, fall back to maptis-nlp
DEFAULT_INDEX_PATH = Path(__file__).resolve().parents[2] / "databases" / "mua_bok_v2"

# Rating priority (NASA-STD-6016)
RATING_PRIORITY = ["FLAM", "TVS", "TOX", "SCC", "CORR", "FS"]

# Material family keywords (same as index builder)
MATERIAL_FAMILIES = {
    "stainless_steel": ["316", "304", "321", "347", "cres", "stainless", "ss"],
    "aluminum": ["aluminum", "al ", "6061", "7075", "2024", "2219"],
    "inconel": ["inconel", "625", "718", "alloy 625", "alloy 718"],
    "titanium": ["titanium", "ti-6al", "ti6al4v"],
    "copper": ["copper", "cu ", "monel", "bronze", "brass"],
    "polymer": ["teflon", "ptfe", "viton", "kalrez", "fluorocarbon", "elastomer", "rubber"],
    "adhesive": ["adhesive", "epoxy", "loctite", "eccobond", "sealant"],
    "lubricant": ["lubricant", "grease", "krytox", "braycote"],
    "composite": ["composite", "cfrp", "fiberglass", "kevlar"],
    "wire": ["wire", "cable", "harness", "insulation"],
}


@dataclass
class MUAPrecedent:
    """A historic MUA that serves as precedent."""
    mua_number: str
    material: str
    environment: str
    determination: str
    rationale: str
    score: float
    source_file: str
    category: Optional[str] = None
    issue: Optional[str] = None
    material_family: Optional[str] = None
    test_reports: List[str] = field(default_factory=list)
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class MUADraft:
    """Generated MUA draft with provenance."""
    material: str
    material_code: Optional[str]
    category: str
    gaps: Dict[str, str]
    rationale: str
    precedents: List[MUAPrecedent]
    provenance_summary: str
    confidence: float
    environment: Optional[str] = None
    application: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability



def classify_material_family(material: str) -> Optional[str]:
    """Classify material into a family."""
    if not material:
        return None
    material_lower = material.lower()
    for family, keywords in MATERIAL_FAMILIES.items():
        if any(kw in material_lower for kw in keywords):
            return family
    return "other"


class MUABOKEngine:
    """
    Main engine for MUA BOK operations.

    Provides:
    - Gap detection from enriched MIUL rows
    - Semantic search for MUA precedents
    - Draft generation with provenance citations
    """

    def __init__(self, index_path: Optional[Path] = None):
        """Initialize the MUA BOK engine."""
        self.index_path = Path(index_path or DEFAULT_INDEX_PATH)
        self.index = None
        self.metadata: List[Dict[str, Any]] = []
        self.embedder = None

        self._load_index()

    def _load_index(self):
        """Load FAISS index and metadata."""
        index_file = self.index_path / "mua_bok_v2.faiss"
        metadata_file = self.index_path / "mua_bok_v2_metadata.pkl"

        if not index_file.exists():
            logger.warning(f"MUA BOK index not found at {index_file}")
            logger.warning("Run: python scripts/build_mua_bok_index_v2.py")
            return

        try:
            import faiss
            self.index = faiss.read_index(str(index_file))
            logger.info(f"Loaded MUA BOK index: {self.index.ntotal} vectors")
        except ImportError:
            logger.error("faiss not installed")
            return
        except Exception as e:
            logger.error(f"Failed to load FAISS index: {e}")
            return

        if metadata_file.exists():
            self.metadata = safe_pickle_load(metadata_file)
            logger.info(f"Loaded {len(self.metadata)} metadata records")

    def _load_embedder(self):
        """Lazy load the sentence transformer."""
        if self.embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self.embedder = SentenceTransformer("all-mpnet-base-v2")
                logger.info("Loaded embedding model: all-mpnet-base-v2")
            except ImportError:
                logger.error("sentence-transformers not installed")

    def detect_gaps(self, miul_row: Dict[str, Any]) -> Dict[str, str]:
        """
        Find non-A ratings requiring MUA.

        Args:
            miul_row: Dictionary with rating columns (FLAM Rating, SCC Rating, etc.)

        Returns:
            Dict mapping gap type to rating value (e.g., {"FLAM": "B", "TVS": "C"})
        """
        gaps = {}
        for col in RATING_PRIORITY:
            # Try various column name patterns
            rating = None
            for key in [f"{col} Rating", f"{col}_Rating", col, f"{col.lower()}_rating"]:
                if key in miul_row:
                    rating = miul_row[key]
                    break

            if rating and str(rating).upper() not in ("A", "", "N/A", "NONE", "NAN"):
                gaps[col] = str(rating).upper()

        return gaps

    def _detect_issues_from_text(self, rationale: str, environment: str) -> List[str]:
        """Detect issue types from rationale and environment text.

        Since the BOK metadata doesn't have explicit 'issue' field,
        we infer issues from the rationale content.
        """
        detected = []
        text = (rationale + " " + environment).upper()

        # Issue detection patterns
        issue_patterns = {
            "FLAM": ["FLAMM", "FLAMMAB", "IGNIT", "BURN", "FIRE", "FLASH POINT", "OXYGEN INDEX"],
            "CORR": ["CORROS", "RUST", "OXIDAT", "GALVANIC", "PITTING"],
            "SCC": ["STRESS CORROSION", "SCC", "CRACKING", "HYDROGEN EMBRITTLEMENT"],
            "TVS": ["OUTGAS", "TML", "CVCM", "VACUUM STAB", "TVS", "OFFGAS"],
            "TOX": ["TOXIC", "COMBUSTION PRODUCT", "FUME", "POISON", "NHB 8060"],
            "FS": ["FLUID SERVICE", "FLUID COMPAT", "PROPELLANT", "HYDRAULIC"],
        }

        for issue, patterns in issue_patterns.items():
            if any(p in text for p in patterns):
                detected.append(issue)

        return detected

    def find_exact_precedents(
        self,
        material: str,
        issues: List[str],
        k: int = 20
    ) -> List[MUAPrecedent]:
        """
        Find MUAs for a specific material with specific issues.

        This does EXACT matching on material (substring) and issue type,
        NOT semantic search. For use in interactive workflow where user
        wants to see all precedents for "6061" with "CORR" issue.

        Args:
            material: Material to match (e.g., "6061", "316 SS")
            issues: List of issue types to match (e.g., ["CORR", "SCC"])
            k: Max results to return

        Returns:
            List of matching MUAPrecedents
        """
        if not self.metadata:
            logger.warning("No metadata loaded")
            return []

        material_lower = material.lower()
        issues_upper = [i.upper() for i in issues]

        results = []
        for meta in self.metadata:
            mua_material = (meta.get("material_designation") or "").lower()

            # Check material match (substring)
            if material_lower not in mua_material:
                continue

            # Get explicit issue field or detect from rationale
            mua_issue_explicit = (meta.get("issue") or "").upper()
            rationale = meta.get("rationale") or ""
            environment = meta.get("environment") or ""

            # Detect issues from text if not explicitly set
            if mua_issue_explicit:
                detected_issues = [mua_issue_explicit]
            else:
                detected_issues = self._detect_issues_from_text(rationale, environment)

            # Check issue match (any of the requested issues)
            issue_match = False
            if not issues:  # No issues specified = match all
                issue_match = True
            else:
                for issue in issues_upper:
                    # Check in detected issues
                    if issue in detected_issues:
                        issue_match = True
                        break

                    # Also check common variations against detected
                    issue_aliases = {
                        "CORR": ["CORR", "CORROSION"],
                        "SCC": ["SCC", "STRESS CORROSION"],
                        "FLAM": ["FLAM", "FLAMM", "FLAMMABILITY"],
                        "TVS": ["TVS", "OUTGAS", "OUTGASSING"],
                        "TOX": ["TOX", "TOXIC", "TOXICITY"],
                        "FS": ["FS", "FLUID", "COMPATIBILITY"],
                    }
                    for alias in issue_aliases.get(issue, []):
                        if alias in detected_issues:
                            issue_match = True
                            break
                    if issue_match:
                        break

            if not issue_match:
                continue

            # Build issue string for result
            issue_str = mua_issue_explicit if mua_issue_explicit else ", ".join(detected_issues)

            # Create precedent
            precedent = MUAPrecedent(
                mua_number=meta.get("mua_number") or meta.get("file", "UNKNOWN"),
                material=meta.get("material_designation") or "N/A",
                environment=meta.get("environment") or "N/A",
                determination=meta.get("determination") or "UNKNOWN",
                rationale=rationale,
                score=1.0,  # Exact match gets score 1.0
                source_file=meta.get("file") or "",
                category=meta.get("category"),
                issue=issue_str,
                material_family=meta.get("material_family"),
                test_reports=meta.get("test_reports") or [],
            )
            results.append(precedent)

        # Sort by MUA number for consistency
        results.sort(key=lambda x: x.mua_number)
        return results[:k]

    def summarize_rationale(self, rationale: str, max_length: int = 200) -> str:
        """Create a summary of rationale for user review."""
        if not rationale:
            return "No rationale available"

        # Take first N characters, break at sentence if possible
        if len(rationale) <= max_length:
            return rationale

        truncated = rationale[:max_length]
        # Try to break at last period
        last_period = truncated.rfind('.')
        if last_period > max_length // 2:
            return truncated[:last_period + 1]
        return truncated + "..."

    def generate_from_selected_precedents(
        self,
        material: str,
        material_code: Optional[str],
        environment: str,
        issues: Dict[str, str],
        selected_precedent_ids: List[str],
        application: Optional[str] = None,
    ) -> MUADraft:
        """
        Generate MUA draft from user-selected precedents.

        Args:
            material: Material designation
            material_code: MAPTIS code
            environment: Operating environment
            issues: Gap profile {issue: rating}
            selected_precedent_ids: List of MUA numbers user selected
            application: Application context

        Returns:
            MUADraft with rationale based on selected precedents
        """
        # Find the selected precedents
        selected = []
        for meta in self.metadata:
            mua_num = meta.get("mua_number") or meta.get("file", "")
            if mua_num in selected_precedent_ids:
                precedent = MUAPrecedent(
                    mua_number=mua_num,
                    material=meta.get("material_designation") or "N/A",
                    environment=meta.get("environment") or "N/A",
                    determination=meta.get("determination") or "UNKNOWN",
                    rationale=meta.get("rationale") or "",
                    score=1.0,
                    source_file=meta.get("file") or "",
                    category=meta.get("category"),
                    issue=meta.get("issue"),
                    material_family=meta.get("material_family"),
                    test_reports=meta.get("test_reports") or [],
                )
                selected.append(precedent)

        # Generate rationale from selected precedents
        rationale = self._build_rationale_from_selections(
            material=material,
            issues=issues,
            precedents=selected,
            environment=environment,
        )

        # Build provenance summary
        provenance = self._build_provenance_summary(selected)

        # Calculate confidence
        confidence = self._calculate_confidence(selected, issues)

        # Determine category
        category = self._route_category(environment, issues)

        return MUADraft(
            material=material,
            material_code=material_code,
            category=category,
            gaps=issues,
            rationale=rationale,
            precedents=selected,
            provenance_summary=provenance,
            confidence=confidence,
            environment=environment,
            application=application,
        )

    def _build_rationale_from_selections(
        self,
        material: str,
        issues: Dict[str, str],
        precedents: List[MUAPrecedent],
        environment: str,
    ) -> str:
        """Build rationale citing the user-selected precedents."""
        sections = []

        # Opening
        if precedents:
            mua_list = ", ".join(p.mua_number for p in precedents)
            sections.append(
                f"This Material Usage Agreement is supported by precedent analysis of "
                f"historic MUAs: {mua_list}.\n"
            )

        # Material/environment context
        sections.append(f"**Material:** {material}")
        if environment:
            sections.append(f"**Environment:** {environment}")
        sections.append("")

        # Issue-specific rationale with precedent citations
        for issue_type, rating in issues.items():
            sections.append(f"**{issue_type} ({rating}):**")

            # Find precedents with this issue
            relevant = [p for p in precedents if p.issue and issue_type in p.issue.upper()]

            if relevant:
                for p in relevant:
                    # Extract key rationale points
                    rat_summary = self.summarize_rationale(p.rationale, 300)
                    sections.append(
                        f"Per {p.mua_number} ({p.material}, {p.determination}):\n"
                        f"  \"{rat_summary}\""
                    )
            else:
                # Use template if no specific precedent
                sections.append(self._get_gap_rationale(issue_type, rating, precedents))
            sections.append("")

        # Precedent summary
        if precedents:
            sections.append("**Referenced Precedents:**")
            for p in precedents:
                sections.append(f"- {p.mua_number}: {p.material} ({p.determination})")

        return "\n".join(sections)

    def search_precedents(
        self,
        material: str,
        environment: str,
        gaps: Dict[str, str],
        k: int = 5
    ) -> List[MUAPrecedent]:
        """
        Search MUA BOK for similar precedents.

        Args:
            material: Material designation or name
            environment: Operating environment (e.g., "GOX", "vacuum", "habitable")
            gaps: Dict of gap types to ratings
            k: Number of precedents to return

        Returns:
            List of MUAPrecedent ranked by relevance (highest first)
        """
        if self.index is None or not self.metadata:
            logger.warning("No index loaded - returning empty results")
            return []

        # Build query
        query = self._build_search_query(material, environment, gaps)

        # Encode query
        self._load_embedder()
        if self.embedder is None:
            return []

        query_vec = self.embedder.encode([query], convert_to_numpy=True)

        # FAISS search - get more candidates for reranking
        n_candidates = min(k * 5, self.index.ntotal)
        distances, indices = self.index.search(query_vec, n_candidates)

        # Convert to precedents with boosting
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue

            meta = self.metadata[idx]
            base_score = float(1.0 / (1.0 + dist))

            # Apply boosts
            score = base_score
            score += self._material_match_boost(material, meta.get("material_designation"))
            score += self._environment_match_boost(environment, meta)
            score += self._gap_relevance_boost(gaps, meta.get("issue"))

            precedent = MUAPrecedent(
                mua_number=meta.get("mua_number") or meta.get("file", "UNKNOWN"),
                material=meta.get("material_designation") or "N/A",
                environment=meta.get("environment") or "N/A",
                determination=meta.get("determination") or "UNKNOWN",
                rationale=meta.get("rationale") or "",
                score=score,
                source_file=meta.get("file") or "",
                category=meta.get("category"),
                issue=meta.get("issue"),
                material_family=meta.get("material_family"),
                test_reports=meta.get("test_reports") or [],
            )
            results.append(precedent)

        # Sort by boosted score and return top-k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:k]

    def _build_search_query(
        self,
        material: str,
        environment: str,
        gaps: Dict[str, str]
    ) -> str:
        """Build semantic search query."""
        parts = []

        if material:
            parts.append(f"Material: {material}")

        if environment:
            parts.append(f"Environment: {environment}")

        if gaps:
            gap_str = ", ".join(f"{k}({v})" for k, v in gaps.items())
            parts.append(f"Issues: {gap_str}")

        return " | ".join(parts) if parts else "general material usage"

    def _material_match_boost(
        self,
        query_material: str,
        mua_material: Optional[str]
    ) -> float:
        """Calculate material match boost."""
        if not query_material or not mua_material:
            return 0.0

        q = query_material.lower()
        m = mua_material.lower()

        # Exact match
        if q == m:
            return 0.30

        # Partial match
        if q in m or m in q:
            return 0.20

        # Same material family
        q_family = classify_material_family(query_material)
        m_family = classify_material_family(mua_material)
        if q_family and q_family == m_family and q_family != "other":
            return 0.15

        return 0.0

    def _environment_match_boost(
        self,
        query_env: str,
        mua_meta: Dict[str, Any]
    ) -> float:
        """Calculate environment match boost."""
        if not query_env:
            return 0.0

        q = query_env.lower()
        env_flags = mua_meta.get("environment_flags", {})
        mua_env = (mua_meta.get("environment") or "").lower()

        boost = 0.0

        # H2/O2 service - highest priority
        h2_keywords = ["h2", "hydrogen", "gh2", "lh2"]
        o2_keywords = ["o2", "oxygen", "gox", "lox"]

        q_is_h2 = any(kw in q for kw in h2_keywords)
        q_is_o2 = any(kw in q for kw in o2_keywords)

        if q_is_h2 and env_flags.get("is_hydrogen"):
            boost += 0.25
        if q_is_o2 and env_flags.get("is_oxygen"):
            boost += 0.25

        # Cryogenic
        if "cryo" in q and env_flags.get("is_cryo"):
            boost += 0.15

        # Vacuum
        if ("vacuum" in q or "vac" in q) and env_flags.get("is_vacuum"):
            boost += 0.10

        # Habitable
        if ("habitable" in q or "cabin" in q) and env_flags.get("is_habitable"):
            boost += 0.10

        # Generic text match
        if q in mua_env or mua_env in q:
            boost += 0.05

        return boost

    def _gap_relevance_boost(
        self,
        query_gaps: Dict[str, str],
        mua_issue: Optional[str]
    ) -> float:
        """Boost if MUA addresses same issue type."""
        if not query_gaps or not mua_issue:
            return 0.0

        mua_issue_upper = mua_issue.upper()

        for gap_type in query_gaps.keys():
            if gap_type in mua_issue_upper:
                return 0.20

        # Check related keywords
        issue_keywords = {
            "FLAM": ["flamm", "ignition", "burn", "fire"],
            "TVS": ["outgas", "tvs", "vacuum", "cvcm", "tml"],
            "TOX": ["toxic", "tox", "combustion product"],
            "SCC": ["scc", "stress corrosion", "cracking"],
            "CORR": ["corrosion", "corr", "rust", "oxidation"],
            "FS": ["fluid", "compatibility", "service"],
        }

        for gap_type in query_gaps.keys():
            keywords = issue_keywords.get(gap_type, [])
            if any(kw in mua_issue.lower() for kw in keywords):
                return 0.15

        return 0.0

    def generate_mua_draft(
        self,
        miul_row: Dict[str, Any],
        precedents: Optional[List[MUAPrecedent]] = None
    ) -> MUADraft:
        """
        Generate MUA draft with provenance citations.

        Args:
            miul_row: Enriched MIUL row with ratings
            precedents: Pre-searched precedents (if None, will search)

        Returns:
            MUADraft with rationale and citations
        """
        # Extract material info
        material = (
            miul_row.get("designation") or
            miul_row.get("Designation") or
            miul_row.get("material_designation") or
            miul_row.get("Material") or
            "Unknown Material"
        )
        material_code = (
            miul_row.get("material_code") or
            miul_row.get("Material Code") or
            miul_row.get("materialkey")
        )
        environment = (
            miul_row.get("environment") or
            miul_row.get("Environment") or
            miul_row.get("fluid") or
            ""
        )
        application = miul_row.get("application") or miul_row.get("Application")

        # Detect gaps
        gaps = self.detect_gaps(miul_row)

        # Search for precedents if not provided
        if precedents is None:
            precedents = self.search_precedents(material, environment, gaps)

        # Determine category based on environment
        category = self._route_category(environment, gaps)

        # Build provenance summary
        provenance_summary = self._build_provenance_summary(precedents)

        # Synthesize rationale
        rationale = self._synthesize_rationale(
            material=material,
            gaps=gaps,
            precedents=precedents,
            environment=environment
        )

        # Calculate confidence
        confidence = self._calculate_confidence(precedents, gaps)

        return MUADraft(
            material=material,
            material_code=material_code,
            category=category,
            gaps=gaps,
            rationale=rationale,
            precedents=precedents,
            provenance_summary=provenance_summary,
            confidence=confidence,
            environment=environment,
            application=application,
        )

    def _route_category(self, environment: str, gaps: Dict[str, str]) -> str:
        """Route to MUA category based on environment and gaps."""
        env_lower = (environment or "").lower()

        # Category I: Limited life, non-critical
        # Category II: Critical but with mitigations
        # Category III: High risk, needs extensive justification

        has_flam = "FLAM" in gaps
        has_tox = "TOX" in gaps

        if any(kw in env_lower for kw in ["oxygen", "o2", "gox", "lox"]):
            return "II" if not has_flam else "III"

        if any(kw in env_lower for kw in ["hydrogen", "h2"]):
            return "II"

        if "habitable" in env_lower or "cabin" in env_lower:
            if has_flam or has_tox:
                return "II"
            return "I"

        return "II"  # Default to Category II

    def _build_provenance_summary(self, precedents: List[MUAPrecedent]) -> str:
        """Build human-readable provenance summary."""
        if not precedents:
            return "No historic precedents found in MUA BOK."

        approved = [p for p in precedents if p.determination == "APPROVED"]
        rejected = [p for p in precedents if p.determination != "APPROVED"]

        parts = [f"Found {len(precedents)} relevant MUA precedents:"]

        if approved:
            parts.append(f"  - {len(approved)} APPROVED")
        if rejected:
            parts.append(f"  - {len(rejected)} other dispositions")

        parts.append("\nTop precedents:")
        for i, p in enumerate(precedents[:3], 1):
            parts.append(f"  {i}. {p.mua_number}: {p.material} ({p.determination})")

        return "\n".join(parts)

    def _synthesize_rationale(
        self,
        material: str,
        gaps: Dict[str, str],
        precedents: List[MUAPrecedent],
        environment: str
    ) -> str:
        """
        Synthesize NEW rationale based on precedents.
        NOT copy/paste - generate fresh guidance with citations.
        """
        sections = []

        # Opening with precedent reference
        if precedents:
            best = precedents[0]
            sections.append(
                f"Based on review of {len(precedents)} historic MUA precedents, "
                f"including {best.mua_number} which approved {best.material} "
                f"under comparable conditions, the following rationale supports approval:"
            )
        else:
            sections.append(
                f"The following rationale supports approval of {material} "
                f"for the specified application:"
            )

        # Gap-specific rationale
        for gap_type, rating in gaps.items():
            gap_rationale = self._get_gap_rationale(gap_type, rating, precedents)
            sections.append(f"\n**{gap_type} ({rating}):** {gap_rationale}")

        # Citations
        if precedents:
            sections.append("\n**Precedent MUAs reviewed:**")
            for p in precedents[:5]:
                sections.append(f"- {p.mua_number}: {p.material} ({p.determination})")

        return "\n".join(sections)

    def _get_gap_rationale(
        self,
        gap_type: str,
        rating: str,
        precedents: List[MUAPrecedent]
    ) -> str:
        """Generate rationale for specific gap type."""
        # Find precedent with same issue type
        relevant = [p for p in precedents if p.issue and gap_type in p.issue.upper()]

        # Default rationale templates
        templates = {
            "FLAM": (
                "Material flammability has been assessed per NASA-STD-6001. "
                "Engineering controls and configuration limits mitigate fire risk."
            ),
            "TVS": (
                "Outgassing properties (TML, CVCM) per ASTM E595 are within acceptable limits "
                "or material is enclosed/protected from vacuum exposure."
            ),
            "TOX": (
                "Combustion products toxicity has been evaluated. Material volume "
                "and enclosure limits toxic byproduct generation potential."
            ),
            "SCC": (
                "Stress corrosion cracking susceptibility is mitigated through "
                "stress limits, protective coatings, or environmental controls."
            ),
            "CORR": (
                "Corrosion resistance is adequate for the service environment. "
                "Protective measures implemented as required."
            ),
            "FS": (
                "Fluid service compatibility verified through testing or "
                "engineering analysis for the specified operating conditions."
            ),
        }

        base = templates.get(gap_type, "Engineering analysis supports material suitability.")

        if relevant:
            # Add precedent reference
            p = relevant[0]
            citation = f" Per precedent {p.mua_number}, similar material/configuration was approved."
            return base + citation

        return base

    def _calculate_confidence(
        self,
        precedents: List[MUAPrecedent],
        gaps: Dict[str, str]
    ) -> float:
        """
        Calculate confidence based on precedent quality.

        Factors:
        - Number of precedents found
        - Best precedent score
        - All precedents APPROVED
        - Gap severity
        """
        if not precedents:
            return 0.30  # Low confidence without precedents

        base = 0.50

        # Precedent count bonus (max +0.15)
        base += min(len(precedents) * 0.03, 0.15)

        # Best score bonus (max +0.15)
        base += min(precedents[0].score * 0.15, 0.15)

        # All approved bonus
        if all(p.determination == "APPROVED" for p in precedents):
            base += 0.10

        # Penalty for high-risk gaps
        if "FLAM" in gaps and gaps.get("FLAM") in ("C", "D", "U"):
            base -= 0.10
        if "TOX" in gaps and gaps.get("TOX") in ("C", "D", "U"):
            base -= 0.05

        return max(0.20, min(base, 0.95))


# ============================================================================
# Convenience Functions
# ============================================================================

_ENGINE: Optional[MUABOKEngine] = None


def get_mua_bok_engine() -> MUABOKEngine:
    """Get or create singleton MUA BOK engine."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = MUABOKEngine()
    return _ENGINE


def search_mua_precedents(
    material: str,
    environment: str = "",
    gaps: Optional[Dict[str, str]] = None,
    k: int = 5
) -> List[MUAPrecedent]:
    """Search for MUA precedents."""
    engine = get_mua_bok_engine()
    return engine.search_precedents(material, environment, gaps or {}, k)


def generate_mua_draft(miul_row: Dict[str, Any]) -> MUADraft:
    """Generate MUA draft for MIUL row."""
    engine = get_mua_bok_engine()
    return engine.generate_mua_draft(miul_row)


# ============================================================================
# Testing
# ============================================================================

def test_mua_bok_engine():
    """Test the MUA BOK engine."""
    print("=" * 70)
    print("MUA BOK ENGINE V2 TEST")
    print("=" * 70)

    engine = MUABOKEngine()

    if engine.index is None:
        print("WARNING: No index loaded. Run build_mua_bok_index_v2.py first.")
        return

    # Test precedent search
    print("\n1. Testing precedent search for 316 SS in GOX...")
    precedents = engine.search_precedents(
        material="316 Stainless Steel",
        environment="GOX",
        gaps={"FLAM": "B", "SCC": "C"}
    )

    print(f"   Found {len(precedents)} precedents")
    for p in precedents[:3]:
        print(f"   - {p.mua_number}: {p.material} | Score: {p.score:.2f}")

    # Test draft generation
    print("\n2. Testing MUA draft generation...")
    test_row = {
        "Designation": "316L Stainless Steel",
        "Material Code": "12345",
        "FLAM Rating": "B",
        "SCC Rating": "C",
        "TVS Rating": "A",
        "Environment": "GOX 3000 psia",
        "Application": "Valve body"
    }

    draft = engine.generate_mua_draft(test_row)
    print(f"   Material: {draft.material}")
    print(f"   Category: {draft.category}")
    print(f"   Gaps: {draft.gaps}")
    print(f"   Confidence: {draft.confidence:.0%}")
    print(f"\n   Provenance:\n   {draft.provenance_summary}")
    print(f"\n   Rationale (first 500 chars):\n   {draft.rationale[:500]}...")

    print("\n" + "=" * 70)
    print("MUA BOK ENGINE TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    test_mua_bok_engine()
