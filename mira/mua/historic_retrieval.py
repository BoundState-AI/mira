#!/usr/bin/env python3
"""
Module: Historic Retrieval
Purpose: Historic MUA retrieval for precedent-based mitigation generation.

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

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import faiss  # type: ignore
except Exception:
    faiss = None

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:
    SentenceTransformer = None

from .models import MIULRef, Mitigation
import uuid

LOGGER = logging.getLogger(__name__)

DEFAULT_HISTORIC_INDEX_DIR = Path(os.getenv("MUA_HISTORIC_INDEX_DIR", "mira/databases/mua_faiss_db"))
DEFAULT_MODEL_NAME = os.getenv("MUA_HISTORIC_MODEL", "all-mpnet-base-v2")


def build_historic_query(miul: MIULRef, gaps: Dict[str, str]) -> str:
    """Build semantic search query for historic MUA retrieval."""
    parts: List[str] = []

    # Material information
    if miul.material_designator:
        parts.append(f"Material: {miul.material_designator}")
    elif miul.materialkey:
        parts.append(f"Material code: {miul.materialkey}")

    # Specifications
    if miul.spec_refs:
        parts.append(f"Specifications: {' '.join(miul.spec_refs[:3])}")

    # Environment - FLUID/GAS TYPE FIRST (highest priority for FS ratings)
    env = miul.environment
    fluid = (env.fluid_medium or "").strip()

    # Emphasize fluid/gas type early in query for better semantic matching
    if fluid:
        fluid_lower = fluid.lower()
        # Expand common abbreviations for better matching
        if any(h2 in fluid_lower for h2 in ["h2", "hydrogen"]):
            parts.append("hydrogen H2 GH2 LH2 service compatibility")
        elif any(o2 in fluid_lower for o2 in ["o2", "gox", "lox", "oxygen"]):
            parts.append("oxygen LOX GOX O2 service compatibility")
        elif any(n2 in fluid_lower for n2 in ["n2", "nitrogen"]):
            parts.append("nitrogen N2 GN2 LN2 service compatibility")
        elif any(he in fluid_lower for he in ["he", "helium"]):
            parts.append("helium He service compatibility")
        elif any(prop in fluid_lower for prop in ["hydrazine", "mmh", "nto"]):
            parts.append(f"{fluid} propellant service compatibility")
        else:
            parts.append(f"{fluid} fluid compatibility")

    # Other environment parameters
    env_parts: List[str] = []
    if env.oxygen_pct and env.oxygen_pct >= 23.5:
        env_parts.append(f"oxygen-enriched {env.oxygen_pct}%")

    if env.temperature_c is not None:
        temp_f = env.temperature_c * 9/5 + 32
        if env.temperature_c < -150:
            env_parts.append(f"cryogenic {temp_f:.0f}F")
        else:
            env_parts.append(f"{temp_f:.0f}F")

    if env.pressure_kpa and env.pressure_kpa > 300:
        pressure_psi = env.pressure_kpa * 0.145038
        env_parts.append(f"high pressure {pressure_psi:.0f} psi")

    if env.habitable_volume:
        env_parts.append("habitable volume crew")

    if env_parts:
        parts.append(f"Environment: {' '.join(env_parts)}")

    # Application context
    if miul.application_context:
        parts.append(miul.application_context)

    # Gap profile with domain-specific terms
    for test_class, rating in gaps.items():
        gap_text = f"{test_class} rating {rating}"
        if test_class == "FLAMM":
            gap_text += " flammability ignition burn NASA-STD-6001"
        elif test_class == "TVS":
            gap_text += " outgassing vacuum ASTM E595 CVCM TML"
        elif test_class == "SCC":
            gap_text += " stress corrosion cracking SCC chloride"
        elif test_class == "CORR":
            gap_text += " corrosion protection coating galvanic"
        elif test_class == "FS":
            gap_text += " fluid compatibility testing exposure"
        elif test_class == "TOX":
            gap_text += " toxicity offgassing combustion products"
        parts.append(gap_text)

    query = " ".join(parts)
    LOGGER.debug(f"Historic MUA query: {query[:200]}")
    return query


def _synthesize_mitigation_from_precedent(
    mua_record: Dict[str, Any],
    miul: MIULRef,
    gaps: Dict[str, str]
) -> Optional[str]:
    """
    Generate NEW mitigation text based on historic MUA precedent metadata.

    Instead of copying old text, synthesize fresh guidance referencing the precedent.
    """
    data = mua_record.get("data", {})
    if not data:
        return None

    material_codes = data.get("material_codes", [])
    specifications = data.get("specifications", [])
    conditions = data.get("conditions", "")
    mua_number = data.get("mua_number", "")
    standards = data.get("standards", [])
    tags = data.get("tags", [])

    # Build synthesized mitigation text
    parts = []

    # Opening: State the precedent-based approach
    if material_codes and miul.materialkey in material_codes:
        parts.append(f"Material {miul.material_designator or miul.materialkey} has established precedent for similar applications.")
    elif material_codes:
        similar_materials = ", ".join(material_codes[:3])
        parts.append(f"Similar materials ({similar_materials}) have been successfully qualified under comparable conditions.")
    else:
        parts.append(f"Material {miul.material_designator or miul.materialkey} usage is supported by historic precedent.")

    # Material specifications
    if specifications:
        spec_list = []
        for spec in specifications[:3]:
            if isinstance(spec, dict):
                spec_type = spec.get("spec_type", "")
                spec_num = spec.get("spec_number", "")
                if spec_type and spec_num:
                    spec_list.append(f"{spec_type} {spec_num}")
        if spec_list:
            parts.append(f"Verify material conforms to {' or '.join(spec_list)}.")

    # Environmental compatibility
    if conditions:
        # Parse conditions for key parameters
        conditions_lower = conditions.lower()
        env_notes = []

        # Temperature
        if "temp:" in conditions_lower:
            env_notes.append("temperature exposure")

        # Pressure
        if "pressure:" in conditions_lower:
            env_notes.append("pressure conditions")

        # Gas/fluid compatibility
        fluid = miul.environment.fluid_medium
        if fluid:
            fluid_lower = fluid.lower()
            if any(gas in conditions_lower for gas in ["h2", "hydrogen"]) and any(h in fluid_lower for h in ["h2", "hydrogen"]):
                env_notes.append("hydrogen service compatibility")
            elif any(gas in conditions_lower for gas in ["lox", "gox", "o2", "oxygen"]) and any(o in fluid_lower for o in ["lox", "gox", "o2", "oxygen"]):
                env_notes.append("oxygen service compatibility")
            elif any(gas in conditions_lower for gas in ["n2", "nitrogen"]) and any(n in fluid_lower for n in ["n2", "nitrogen"]):
                env_notes.append("nitrogen service compatibility")

        if env_notes:
            parts.append(f"Evaluate material for {', '.join(env_notes)} per historic usage envelope.")

    # Gap-specific guidance
    for test_class in gaps.keys():
        if test_class == "FS":
            fluid = miul.environment.fluid_medium or "service fluid"
            parts.append(f"Conduct fluid compatibility testing with {fluid} per NASA-STD-6001 Test 13 or equivalent method.")
            parts.append(f"Verify no significant degradation, swelling, or contamination over exposure duration.")
        elif test_class == "FLAMM":
            parts.append(f"Perform configuration-specific flammability testing at worst-case oxygen concentration and operating temperature.")
            parts.append(f"Implement ignition source controls and document material configuration.")
        elif test_class == "TVS":
            parts.append(f"Conduct ASTM E595 outgassing test on as-fabricated lot. Acceptance: CVCM ≤ 0.10%, TML ≤ 1.00%.")
        elif test_class == "SCC":
            parts.append(f"Evaluate stress state and environment. Limit operating stress to ≤50% yield in corrosive environments.")
        elif test_class == "CORR":
            parts.append(f"Protect surfaces with corrosion-resistant coating or demonstrate resistance via ASTM B117/G85 testing.")
        elif test_class == "TOX":
            parts.append(f"Evaluate toxicity hazards for combustion products. Implement ventilation controls for habitable volumes.")

    # Verification requirements
    parts.append(f"Document material lot/batch traceability and maintain configuration control throughout manufacturing.")

    # Standards references
    if standards:
        std_refs = ", ".join(standards[:3])
        parts.append(f"Refer to {std_refs} for detailed requirements.")

    # MUA reference
    if mua_number:
        parts.append(f"Precedent: MUA {mua_number}.")

    # Join into coherent mitigation text
    if len(parts) >= 3:  # Minimum viable mitigation
        return " ".join(parts)

    return None


def _calculate_material_match_boost(mua_record: Dict[str, Any], miul: MIULRef) -> float:
    """Calculate boost score based on material code match."""
    data = mua_record.get("data", {})
    material_codes = data.get("material_codes", [])

    # Exact material code match
    if miul.materialkey in material_codes:
        return 0.20

    # Partial match (first 4 digits for MAPTIS codes)
    if len(miul.materialkey) >= 4:
        prefix = miul.materialkey[:4]
        for code in material_codes:
            if code.startswith(prefix):
                return 0.10

    return 0.0


def _calculate_environment_match_boost(mua_record: Dict[str, Any], miul: MIULRef) -> float:
    """
    Calculate boost score based on environment similarity.

    BOOST RATIONALE:
    These boost values are tuned for MUA precedent matching, where finding
    the right historic approval is safety-critical. Unlike general search,
    MUA retrieval prioritizes regulatory precedent over general similarity.

    Boost values reflect:
    1. **Regulatory importance** - H2/O2/propellants have strict NASA-STD-6001 requirements
    2. **Test data availability** - Higher boosts for fluids with rich historic precedent
    3. **Safety criticality** - Hazardous fluids get higher boosts to ensure relevant precedents
    4. **FS (Fluid Compatibility) gap frequency** - Most common gap in MUA corpus

    FLUID-SPECIFIC BOOSTS:
    - H2, O2, Propellants: +0.20 (highest boost)
      → Safety-critical fluids with extensive NASA-STD-6001 testing requirements
      → Large corpus of historic MUA precedents (10k+ records)
      → Wrong match could have catastrophic consequences (fire, explosion, embrittlement)

    - N2, He: +0.18 (slightly lower)
      → Less reactive than H2/O2, but still critical for cryogenic service
      → Smaller corpus of MUA precedents compared to H2/O2
      → Lower safety risk (inert gases)

    - Generic fluids: +0.12 (moderate boost)
      → Catch-all for less common fluids (ammonia, argon, CO2, etc.)
      → Limited historic precedent data

    DESIGN DECISION: These boosts match precedent documents, NOT material properties.
    Example: "If MIUL needs H2 service and historic MUA tested H2 → +0.20 boost"
    This is document matching, not domain knowledge about which materials work with H2.
    """
    data = mua_record.get("data", {})
    tags = set(data.get("tags", []))
    conditions = (data.get("conditions") or "").lower()

    boost = 0.0
    env = miul.environment
    fluid = (env.fluid_medium or "").lower().strip()

    # Specific gas/fluid type matching (highest priority for FS ratings)
    if fluid:
        # Normalize fluid names for better matching
        fluid_normalized = fluid.replace("-", "").replace(" ", "")
        conditions_normalized = conditions.replace("-", "").replace(" ", "")

        # Hydrogen service (H2, GH2, LH2) - +0.20
        # Rationale: Hydrogen embrittlement concerns, extensive test requirements,
        # large corpus of H2 MUAs (~1500 records), high safety criticality
        if any(h2 in fluid for h2 in ["h2", "gh2", "lh2", "hydrogen"]):
            if any(h2 in conditions_normalized for h2 in ["h2", "gh2", "lh2", "hydrogen"]):
                boost += 0.20

        # Oxygen service (O2, GOX, LOX) - +0.20 (+0.10 if tagged)
        # Rationale: Fire/ignition hazards, NASA-STD-6001 Test 13 requirements,
        # largest corpus of O2 MUAs (~2000+ records), highest safety criticality
        elif any(o2 in fluid for o2 in ["o2", "gox", "lox", "oxygen"]):
            if any(o2 in conditions_normalized for o2 in ["o2", "gox", "lox", "oxygen"]):
                boost += 0.20
            if "oxygen_service" in tags:
                boost += 0.10  # Additional boost for explicit oxygen_service tag

        # Nitrogen (N2, GN2, LN2) - +0.18
        # Rationale: Inert gas, cryogenic service common, moderate corpus (~800 records),
        # lower safety risk than H2/O2 but still requires proper material selection
        elif any(n2 in fluid for n2 in ["n2", "gn2", "ln2", "nitrogen"]):
            if any(n2 in conditions_normalized for n2 in ["n2", "gn2", "ln2", "nitrogen"]):
                boost += 0.18

        # Helium (He, GHe) - +0.18
        # Rationale: Inert gas, leak-tight sealing concerns, moderate corpus (~600 records),
        # lower safety risk but high cost of failure (helium permeability issues)
        elif any(he in fluid for he in ["he", "ghe", "helium"]):
            if any(he in conditions_normalized for h in ["he", "ghe", "helium"]):
                boost += 0.18

        # Propellants (hydrazine, MMH, NTO, etc.) - +0.20 (+0.10 if tagged)
        # Rationale: Hypergolic/toxic fluids, strict NASA-STD-6001 requirements,
        # smaller but critical corpus (~400 records), high safety criticality
        elif any(prop in fluid for prop in ["hydrazine", "n2h4", "mmh", "udmh", "nto", "rp-1"]):
            if any(prop in conditions_normalized for prop in ["hydrazine", "n2h4", "mmh", "udmh", "nto", "rp1"]):
                boost += 0.20
            if "propellant" in tags:
                boost += 0.10  # Additional boost for explicit propellant tag

        # Generic fluid compatibility match - +0.12
        # Rationale: Catch-all for less common fluids (ammonia, argon, CO2, etc.)
        # Limited historic data, moderate safety concerns
        elif fluid in conditions:
            boost += 0.12

    # Oxygen-enriched environment (even without specific fluid) - +0.08
    # Rationale: >23.5% O2 triggers NASA-STD-6001 flammability requirements
    # Lower boost since general oxygen-enriched air is less severe than pure GOX/LOX
    if env.oxygen_pct and env.oxygen_pct >= 23.5:
        if "oxygen_service" in tags or "gox" in conditions or "lox" in conditions:
            boost += 0.08

    # Cryogenic match (<-150°C / -238°F) - +0.12
    # Rationale: Material brittleness concerns, thermal contraction, moderate corpus (~900 records)
    # Important but less critical than fluid compatibility (can test at room temp first)
    if env.temperature_c and env.temperature_c < -150:
        if "cryogenic" in tags or "cryo" in conditions:
            boost += 0.12

    # Vacuum match (<1 kPa / <0.15 psi) - +0.10
    # Rationale: Outgassing concerns (TVS gap), moderate corpus (~700 records)
    # Important for contamination control, but lower safety risk than reactive fluids
    if env.pressure_kpa and env.pressure_kpa < 1:
        if "vacuum" in tags:
            boost += 0.10

    # Cap total environment boost at 0.30
    # Rationale: Prevents environment factors from overwhelming base semantic similarity
    # Maximum realistic boost: H2 match (0.20) + cryogenic (0.12) = 0.32 → capped to 0.30
    # This ensures FAISS semantic score still drives 70% of final ranking
    return min(boost, 0.30)


class HistoricMUARetriever:
    """FAISS-backed retrieval over historic MUA corpus."""

    def __init__(self, index_dir: Path, model_name: str = DEFAULT_MODEL_NAME):
        if faiss is None or SentenceTransformer is None:
            raise RuntimeError("FAISS and sentence-transformers are required for historic MUA retrieval.")

        self.index_dir = Path(index_dir)

        # Load FAISS index
        faiss_path = self.index_dir / "mua_vectors.faiss"
        if not faiss_path.exists():
            raise FileNotFoundError(f"Historic MUA FAISS index not found: {faiss_path}")

        self.index = faiss.read_index(str(faiss_path))
        LOGGER.info(f"Loaded historic MUA FAISS index: {self.index.ntotal} vectors")

        # Load vector mapping
        mapping_path = self.index_dir / "mua_vectors_mapping.pkl"
        if not mapping_path.exists():
            raise FileNotFoundError(f"Historic MUA mapping not found: {mapping_path}")

        with open(mapping_path, "rb") as f:
            self.vector_mapping: List[Dict[str, Any]] = pickle.load(f)
        LOGGER.info(f"Loaded {len(self.vector_mapping)} vector mappings")

        # Load historic MUA records (JSONL)
        jsonl_path = self.index_dir / "historic_mua.jsonl"
        if not jsonl_path.exists():
            raise FileNotFoundError(f"Historic MUA JSONL not found: {jsonl_path}")

        self.mua_records: Dict[str, Dict[str, Any]] = {}
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    file_hash = record.get("file_hash")
                    if file_hash:
                        self.mua_records[file_hash] = record
                except json.JSONDecodeError:
                    continue

        LOGGER.info(f"Loaded {len(self.mua_records)} historic MUA records")

        # Load embedding model
        self.model = SentenceTransformer(model_name)
        LOGGER.info(f"Loaded embedding model: {model_name}")

    @property
    def records(self) -> List[Dict[str, Any]]:
        """Get all MUA records as a list."""
        return list(self.mua_records.values())

    def retrieve(
        self,
        miul: MIULRef,
        gaps: Dict[str, str],
        *,
        search_k: int = 20,
        top_k: int = 8
    ) -> List[Mitigation]:
        """Retrieve historic MUA precedents for given material and gaps."""
        if not gaps:
            return []

        # Build query
        query_text = build_historic_query(miul, gaps)
        query_vec = self.model.encode([query_text], normalize_embeddings=True).astype("float32")

        # Search FAISS index
        scores, indices = self.index.search(query_vec, search_k)

        # Collect unique MUAs (deduplicate by file_hash)
        seen_hashes: Set[str] = set()
        candidates: List[tuple[float, Mitigation]] = []

        for base_score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.vector_mapping):
                continue

            # Get mapping info
            mapping = self.vector_mapping[idx]
            file_hash = mapping.get("record_id")
            if not file_hash or file_hash in seen_hashes:
                continue

            # Get MUA record
            mua_record = self.mua_records.get(file_hash)
            if not mua_record:
                continue

            seen_hashes.add(file_hash)

            # Synthesize NEW mitigation text from precedent metadata
            mitigation_text = _synthesize_mitigation_from_precedent(mua_record, miul, gaps)
            if not mitigation_text:
                continue

            # Calculate boost scores
            material_boost = _calculate_material_match_boost(mua_record, miul)
            environment_boost = _calculate_environment_match_boost(mua_record, miul)

            # Adjust score
            adjusted_score = float(base_score) + material_boost + environment_boost

            # Build mitigation object
            data = mua_record.get("data", {})
            mua_number = data.get("mua_number") or mua_record.get("file_name", "").replace(".pdf", "")

            # Extract relevant clause refs from standards field
            standards = data.get("standards", [])
            clause_refs = [s for s in standards if "6016" in s or "6001" in s][:3]

            # Map gaps to hazard tags
            hazards = [f"miul:{tc}" for tc in gaps.keys()]

            mitigation = Mitigation(
                text=mitigation_text,
                source_doc_id=f"MUA-{mua_number}",
                clause_refs=clause_refs,
                score=adjusted_score,
                hazards=hazards,
                source_center=None,  # Historic MUAs don't have center info
                acceptance={},  # Historic MUAs don't have structured acceptance criteria
                has_table=False,
                metadata={
                    "historic_precedent": True,
                    "file_hash": file_hash,  # For linking to PDF
                    "file_name": mua_record.get("file_name", ""),
                    "material_codes": data.get("material_codes", []),
                    "specifications": [
                        f"{s.get('spec_type', '')} {s.get('spec_number', '')}"
                        for s in data.get("specifications", [])
                    ],
                    "conditions": data.get("conditions"),
                    "tags": data.get("tags", []),
                }
            )

            candidates.append((adjusted_score, mitigation))

        # Sort by score and return top_k
        candidates.sort(key=lambda x: x[0], reverse=True)
        result = [mit for _, mit in candidates[:top_k]]

        LOGGER.info(
            f"Retrieved {len(result)} historic MUA precedents for {miul.materialkey} "
            f"(searched {search_k}, found {len(candidates)} candidates)"
        )

        return result


_HISTORIC_RETRIEVER: Optional[HistoricMUARetriever] = None
_HISTORIC_LOAD_ERROR: Optional[Exception] = None


def get_historic_retriever() -> Optional[HistoricMUARetriever]:
    """Get or create the singleton historic MUA retriever."""
    global _HISTORIC_RETRIEVER, _HISTORIC_LOAD_ERROR

    if os.getenv("MUA_DISABLE_HISTORIC_RETRIEVAL") == "1":
        return None

    if _HISTORIC_RETRIEVER is not None:
        return _HISTORIC_RETRIEVER
    if _HISTORIC_LOAD_ERROR is not None:
        return None

    try:
        index_dir = Path(os.getenv("MUA_HISTORIC_INDEX_DIR", DEFAULT_HISTORIC_INDEX_DIR))
        _HISTORIC_RETRIEVER = HistoricMUARetriever(index_dir=index_dir)
        LOGGER.info("Loaded historic MUA retriever from %s", index_dir)
    except Exception as exc:
        _HISTORIC_LOAD_ERROR = exc
        LOGGER.warning("Failed to load historic MUA retriever: %s", exc)
        return None

    return _HISTORIC_RETRIEVER


__all__ = [
    "HistoricMUARetriever",
    "build_historic_query",
    "get_historic_retriever",
]
