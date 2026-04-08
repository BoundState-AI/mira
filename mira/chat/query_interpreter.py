#!/usr/bin/env python3
"""
Module: Query Interpreter
Purpose: Two-stage intent + entity extraction + task classification for MIRA Chat.

Implements BS-SPEC-MIRA-CHAT-001-REV2 Sections 4-6:
  Stage 1 — Coarse intent classification (keyword/pattern matching)
  Stage 2 — Fine-grained entity & domain extraction
  Stage 3 — Task classification (answer_only / draft_artifact / review_existing)

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mira.chat.models import ChatMessage, TaskMode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ParsedQuery — the canonical return type
# ---------------------------------------------------------------------------


@dataclass
class ParsedQuery:
    """Result of the full query interpretation pipeline."""

    # Stage 1: coarse intent
    coarse_intent: str = "help"

    # Stage 2: fine routing target (e.g. "oca", "h2", "maptis_search", "bsmh")
    fine_routing: str = "bsmh"

    # Stage 3: task mode
    task_mode: TaskMode = TaskMode.ANSWER_ONLY

    # Extracted entities
    material_designation: Optional[str] = None
    second_material: Optional[str] = None
    gas_service: Optional[str] = None           # "oxygen" | "hydrogen" | None
    environment: Optional[str] = None          # galvanic environment key | None
    pressure: Optional[str] = None              # raw string with units
    pressure_value: Optional[float] = None      # numeric psi
    temperature: Optional[str] = None           # raw string with units
    temperature_value: Optional[float] = None   # numeric (Fahrenheit or Celsius, raw)
    standard_ref: Optional[str] = None          # e.g. "NASA-STD-6016C"
    dissimilar_metals: bool = False
    fracture_context: bool = False

    # Routing confidence (0.0–1.0)
    routing_confidence: float = 0.0
    explicit_engine_target: Optional[str] = None

    # Clarification
    clarification_needed: bool = False
    clarification_question: str = ""

    # History inheritance
    inherited_entities: Dict[str, Any] = field(default_factory=dict)

    # Raw query for downstream
    raw_query: str = ""


# ---------------------------------------------------------------------------
# Constants & thresholds
# ---------------------------------------------------------------------------

ROUTING_CONFIDENCE_THRESHOLDS: Dict[str, float] = {
    "compatibility_query": 0.85,
    "materials_query": 0.70,
    "document_lookup": 0.75,
    "test_report": 0.75,
    "comparison": 0.80,
    "help": 0.50,
    "default": 0.80,
}

# HIGH-RISK parameters — NEVER inherited from conversation history
_HIGH_RISK_PARAMS = frozenset({
    "crewed",
    "hardware_class",
    "mission_type",
    "fracture_critical",
    "approval_category",
})

# Pronoun / reference patterns that trigger entity inheritance
_ANAPHORA_PATTERNS = re.compile(
    r"\b(it|that material|the same|same thing|same material|that one|those|the material|this material)\b",
    re.IGNORECASE,
)
_FOLLOW_UP_PATTERNS = re.compile(
    r"\b(what about|how about|what if|and at|same pressure|same environment|same service)\b",
    re.IGNORECASE,
)
_HISTORY_LOOKBACK_MESSAGES = 10
_PAIRING_HINT_PATTERN = re.compile(
    r"\b(?:between|vs\.?|versus|against|paired\s+with|coupled\s+(?:to|with)|galvanic|dissimilar|anode|cathode)\b",
    re.IGNORECASE,
)
_MODULE_ENGINE_ALIASES: Dict[str, str] = {
    "oca": "oca",
    "h2": "h2",
    "galvanic": "galvanic",
    "fracture": "fracture",
    "gpcm": "gpcm",
    "compliance": "gpcm",
    "maptis": "maptis_search",
    "maptis_search": "maptis_search",
    "bsmh": "bsmh",
}
_EXPLICIT_ENGINE_PATTERNS: Dict[str, re.Pattern] = {
    "oca": re.compile(
        r"\b(?:oca|oxygen\s+compatibility|oxygen\s+service|GOX|LOX|O2)\b",
        re.IGNORECASE,
    ),
    "h2": re.compile(
        r"\b(?:h2|gh2|lh2|hydrogen\s+compatibility|hydrogen\s+service|hydrogen)\b",
        re.IGNORECASE,
    ),
    "galvanic": re.compile(
        r"\b(?:galvanic|dissimilar\s+metals?|anodic|cathodic|anode|cathode|corrosion\s+couple)\b",
        re.IGNORECASE,
    ),
    "fracture": re.compile(
        r"\b(?:fracture(?:\s+control)?|fracture-critical|crack(?:\s+growth)?|fatigue\s+crack|kic)\b",
        re.IGNORECASE,
    ),
    "maptis_search": re.compile(
        r"\b(?:maptis|outgassing|e595|test\s+evidence|test\s+data)\b",
        re.IGNORECASE,
    ),
    "gpcm": re.compile(
        r"\b(?:gpcm|nasa-std-6016|6016c|materials?\s+and\s+process(?:es)?\s+plan|mpr\b)\b",
        re.IGNORECASE,
    ),
}
_ENGINE_SWITCH_PATTERN = re.compile(
    r"\b(?:instead|rather\s+than|switch(?:ing)?\s+to|move\s+to|cross\s+over\s+to)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Stage 1: Coarse Intent Classification (keyword / pattern matching)
# ---------------------------------------------------------------------------

# Each intent maps to a list of (compiled_pattern, weight) pairs.
# Score = sum of matched weights; normalized to [0, 1] by dividing by max plausible sum.

_INTENT_PATTERNS: Dict[str, List[Tuple[re.Pattern, float]]] = {
    "compatibility_query": [
        # Explicit compatibility language
        (re.compile(r"\b(compatible|compatibility|approved|rated)\b", re.I), 4.0),
        (re.compile(r"\b(ok|okay|good)\s+(?:in|for|with)\s+(GOX|LOX|GH2|LH2|oxygen|hydrogen|O2|H2)\b", re.I), 4.5),
        # Gas service context
        (re.compile(r"\b(O2|oxygen|hydrogen|H2)\s*(service|compatible|safe|approved)\b", re.I), 5.0),
        (re.compile(r"\b(GOX|LOX|GH2|LH2)\s*(service|compatible|use)\b", re.I), 5.0),
        # Bare gas keywords (strong but not as strong as combined)
        (re.compile(r"\b(GOX|LOX|GH2|LH2|oxygen|hydrogen|O2|H2)\b", re.I), 3.0),
        # Pressure/temperature envelope implies compatibility check
        (re.compile(r"\b(?:at|for)\s+\d+\s*(?:psi|psia|bar|Pa|kPa|MPa)\b", re.I), 3.0),
        # "Can I use X in Y" pattern
        (re.compile(r"\bcan\s+(?:I|we)\s+use\b", re.I), 4.0),
        # "Is X suitable/acceptable for Y"
        (re.compile(r"\b(?:is|are)\s+\w+\s+(?:suitable|acceptable|allowed|permitted)\b", re.I), 4.0),
        # "safe for" / "safe in"
        (re.compile(r"\bsafe\s+(?:for|in)\b", re.I), 3.5),
    ],
    "materials_query": [
        # List/show/find materials
        (re.compile(r"\b(?:list|show|find|search|browse)\s+(?:all\s+)?(?:material|alloy|metal|polymer)s?\b", re.I), 4.0),
        (re.compile(r"\b(?:material|alloy|metal|polymer|composite)\b", re.I), 2.0),
        (re.compile(r"\b(?:tml|cvcm|outgassing|cryogenic)\b", re.I), 2.0),
        # "What materials are" pattern
        (re.compile(r"\bwhat\s+(?:material|alloy)s?\s+(?:are|is)\b", re.I), 3.0),
        # MAPTIS-specific
        (re.compile(r"\b(?:maptis|material\s+database)\b", re.I), 3.0),
    ],
    "document_lookup": [
        (re.compile(r"\b(?:NASA[-\s]?STD|MIL[-\s]?STD|ASTM|specification|procedure|standard)\b", re.I), 3.0),
        (re.compile(r"\bpdf\b", re.I), 1.5),
        (re.compile(r"\b(?:section|clause|paragraph|requirement)\s+\d+", re.I), 2.5),
        (re.compile(r"\b(?:what does|where does|cite|reference)\b", re.I), 2.0),
    ],
    "test_report": [
        (re.compile(r"\b(?:test|tested|testing)\s+(?:result|data|report|record)\b", re.I), 4.0),
        (re.compile(r"\b(?:test|result|pass(?:ed)?|fail(?:ed)?)\b", re.I), 2.0),
        (re.compile(r"\bASTM|E595|6001\b", re.I), 2.0),
        (re.compile(r"\b(?:latest|most recent)\s+test\b", re.I), 3.0),
    ],
    "comparison": [
        (re.compile(r"\b(?:compare|comparison)\b", re.I), 4.0),
        (re.compile(r"\b(?:versus|vs\.?)\b", re.I), 3.5),
        (re.compile(r"\b(?:better than|difference|which is better)\b", re.I), 3.0),
        (re.compile(r"\b(?:side[- ]by[- ]side)\b", re.I), 3.0),
    ],
    "help": [
        (re.compile(r"\b(?:how do I|help|can you|what can|what does MIRA)\b", re.I), 3.0),
        (re.compile(r"\b(?:hello|hi|hey|greet)\b", re.I), 2.0),
        (re.compile(r"\b(?:what is|what are)\s+(?:MIRA|you|this)\b", re.I), 2.5),
    ],
}

# Negative patterns that reduce scores
_NEGATIVE_PATTERNS: Dict[str, List[Tuple[re.Pattern, float]]] = {
    "materials_query": [
        (re.compile(r"\b(?:invoice|payment|contract|weather)\b", re.I), -3.0),
    ],
}

# Max plausible score for normalisation (sum of all positive weights per intent)
_MAX_SCORE_NORMALIZER = 10.0


def _classify_coarse_intent(text: str) -> Dict[str, float]:
    """Return {intent: score} dict with scores in [0.0, 1.0]."""
    scores: Dict[str, float] = {}
    for intent, patterns in _INTENT_PATTERNS.items():
        score = 0.0
        for pattern, weight in patterns:
            if pattern.search(text):
                score += weight
        for pattern, weight in _NEGATIVE_PATTERNS.get(intent, []):
            if pattern.search(text):
                score += weight  # weight is negative
        if score > 0:
            scores[intent] = min(1.0, max(0.0, score / _MAX_SCORE_NORMALIZER))
    return scores


# ---------------------------------------------------------------------------
# Stage 2: Entity / Domain Extraction
# ---------------------------------------------------------------------------

# Material designation patterns (reuses logic from bouncer)
_MATERIAL_PATTERNS: List[re.Pattern] = [
    # Common alloy families with numbers
    re.compile(r"\b(Inconel|Monel|Hastelloy|Haynes|Waspaloy)\s*[-\s]?([A-Za-z]?\d{2,4}[A-Za-z]?)\b", re.I),
    # Stainless/CRES shorthand (316L, 304, etc.)
    re.compile(r"\b(?:SS|CRES|stainless(?:\s+steel)?)\s*[-\s]?(\d{3,4}[Ll]?)\b", re.I),
    # Bare alloy numbers like 316L, 2219
    re.compile(r"\b(\d{3,5}[Ll]?(?:-[A-Z]\d{1,3})?)\b"),
    # Titanium notation
    re.compile(r"\bTi[-\s]?\d+[A-Za-z]*[-\s]?\d*[A-Za-z]*\b", re.I),
    # PH alloys (17-4 PH)
    re.compile(r"\b\d{1,2}\s*-\s*\d{1,2}\s*PH\b", re.I),
    # Aluminum shorthand
    re.compile(r"\b(?:Al|Aluminum)\s*[-\s]?(\d{4}[A-Za-z]?(?:-[A-Z]\d{1,3})?)\b", re.I),
    # Named polymers / elastomers
    re.compile(r"\b(PTFE|Viton|Kel-?F|PEEK|Kapton|Vespel|Teflon|Nylon|Kalrez|EPDM|Buna-?N|Fluorosilicone|Silicone|Polyimide)\b", re.I),
    # Copper alloys
    re.compile(r"\b(?:CDA|C)\s*\d{3,5}\b", re.I),
    # A-286, MP35N, etc.
    re.compile(r"\b[A-Z]-?\d{3,4}[A-Z]?\b"),
    re.compile(r"\bMP\d{2,3}N?\b", re.I),
]
_GENERIC_MATERIAL_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(?:is|are)\s+([A-Za-z][A-Za-z0-9._-]{2,})\s+(?:compatible|safe|acceptable|approved|rated)\b", re.I),
    re.compile(r"\buse\s+([A-Za-z][A-Za-z0-9._-]{2,})\s+(?:in|for|with)\b", re.I),
]
_NON_MATERIAL_CANDIDATES = {
    "compatible",
    "material",
    "materials",
    "oxygen",
    "hydrogen",
    "gox",
    "lox",
    "gh2",
    "lh2",
    "service",
    "system",
    "this",
    "that",
}
_MATERIAL_PREFIXES = re.compile(
    r"\b(?:SS|CRES|stainless(?:\s+steel)?|AL|Aluminum|Aluminium)\b",
    re.IGNORECASE,
)

# Gas service mapping
_GAS_SERVICE_MAP: Dict[str, str] = {
    "gox": "oxygen",
    "lox": "oxygen",
    "oxygen": "oxygen",
    "o2": "oxygen",
    "gh2": "hydrogen",
    "lh2": "hydrogen",
    "hydrogen": "hydrogen",
    "h2": "hydrogen",
}
_GAS_PATTERN = re.compile(
    r"\b(GOX|LOX|GH2|LH2|oxygen|hydrogen|O2|H2)\b", re.I
)
_ENVIRONMENT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bseawater(?:\s+proxy)?\b", re.I), "seawater_proxy"),
    (re.compile(r"\bsalt(?:\s+fog)?\b", re.I), "seawater_proxy"),
    (re.compile(r"\bcoastal(?:\s+condensing)?\b", re.I), "coastal_condensing"),
    (re.compile(r"\bindustrial(?:\s+atmospher(?:e|ic))?\b", re.I), "industrial_atm"),
    (re.compile(r"\brural(?:\s+atmospher(?:e|ic))?\b", re.I), "rural_atm"),
    (re.compile(r"\bcrew(?:\s+condensing)?\b", re.I), "crew_condensing"),
    (re.compile(r"\binterior\b", re.I), "crew_condensing"),
    (re.compile(r"\bdry(?:\s+indoor)?\b", re.I), "dry_indoor"),
    (re.compile(r"\bindoor\b", re.I), "dry_indoor"),
    (re.compile(r"\bcryo(?:genic)?(?:\s+ops)?\b", re.I), "cryogenic_ops"),
    (re.compile(r"\bspace(?:\s+vacuum)?\b", re.I), "space_vacuum"),
    (re.compile(r"\bvacuum\b", re.I), "space_vacuum"),
]

# Pressure extraction
_PRESSURE_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(psi|psia|bar|kPa|MPa|Pa|atm)\b", re.I
)

# Temperature extraction
_TEMPERATURE_PATTERN = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:°\s*|deg(?:rees?)?\s*)?([FfCcKk]|Fahrenheit|Celsius|Kelvin)\b",
    re.I,
)

# Standard reference extraction
_STANDARD_PATTERN = re.compile(
    r"\b((?:NASA|MIL|ASTM|SAE|AMS|ISO)[-\s]?(?:STD[-\s]?)?[A-Z0-9][-A-Z0-9.]*(?:\s*(?:Rev|REV)\s*[A-Z0-9]+)?)\b",
    re.I,
)

# Dissimilar metals flag
_DISSIMILAR_METALS_PATTERN = re.compile(
    r"\b(?:dissimilar\s+metal|galvanic(?:\s+(?:corrosion|couple|risk|compatibility|assessment|screen))?|bimetallic|mixed\s+metal)\b",
    re.I,
)

# Fracture context flag
_FRACTURE_PATTERN = re.compile(
    r"\b(?:fracture|crack|fatigue|flaw|damage\s+tolerance|K_?Ic|stress\s+intensity)\b",
    re.I,
)


def _extract_material(text: str) -> Optional[str]:
    """Extract the first plausible material designation from the query."""
    materials = _extract_materials(text)
    if materials:
        return materials[0]
    for pattern in _MATERIAL_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(0).strip()
            # Exclude pure numeric tokens that are probably pressures or temps
            if re.fullmatch(r"\d+", raw):
                continue
            return raw
    for pattern in _GENERIC_MATERIAL_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        candidate = m.group(1).strip(" .,;:!?()[]{}")
        if candidate.lower() not in _NON_MATERIAL_CANDIDATES:
            return candidate
    return None


def _material_key(value: str) -> str:
    normalized = _MATERIAL_PREFIXES.sub("", value)
    return re.sub(r"[^A-Z0-9]+", "", normalized.upper())


def _extract_materials(text: str) -> List[str]:
    """Extract plausible material mentions in their original order."""
    found: List[Tuple[int, str]] = []

    for pattern in _MATERIAL_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0).strip()
            if re.fullmatch(r"\d+", raw):
                continue
            found.append((match.start(), raw))

    for pattern in _GENERIC_MATERIAL_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip(" .,;:!?()[]{}")
            if candidate.lower() in _NON_MATERIAL_CANDIDATES:
                continue
            found.append((match.start(1), candidate))

    found.sort(key=lambda item: item[0])

    selected: List[str] = []
    for _, candidate in found:
        key = _material_key(candidate)
        if not key:
            continue

        duplicate_index: Optional[int] = None
        for idx, existing in enumerate(selected):
            existing_key = _material_key(existing)
            if key == existing_key or key in existing_key or existing_key in key:
                duplicate_index = idx
                break

        if duplicate_index is None:
            selected.append(candidate)
            continue

        if len(candidate) > len(selected[duplicate_index]):
            selected[duplicate_index] = candidate

    return selected


def _extract_gas_service(text: str) -> Optional[str]:
    """Map gas tokens to canonical 'oxygen' | 'hydrogen'."""
    m = _GAS_PATTERN.search(text)
    if m:
        token = m.group(1).lower()
        return _GAS_SERVICE_MAP.get(token)
    return None


def _extract_environment(text: str) -> Optional[str]:
    """Extract galvanic-style service environment from the query."""
    for pattern, canonical in _ENVIRONMENT_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def _extract_pressure(text: str) -> Tuple[Optional[str], Optional[float]]:
    """Return (raw_string, numeric_psi_value)."""
    m = _PRESSURE_PATTERN.search(text)
    if not m:
        return None, None
    raw = m.group(0)
    value = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    # Convert to psi for internal use
    psi_value = value
    if unit == "bar":
        psi_value = value * 14.5038
    elif unit == "kpa":
        psi_value = value * 0.145038
    elif unit == "mpa":
        psi_value = value * 145.038
    elif unit == "pa":
        psi_value = value * 0.000145038
    elif unit == "atm":
        psi_value = value * 14.696
    return raw, psi_value


def _extract_temperature(text: str) -> Tuple[Optional[str], Optional[float]]:
    """Return (raw_string, numeric_value)."""
    m = _TEMPERATURE_PATTERN.search(text)
    if not m:
        return None, None
    raw = m.group(0)
    value = float(m.group(1))
    return raw, value


def _extract_standard_ref(text: str) -> Optional[str]:
    """Extract a standards reference (e.g. NASA-STD-6016C)."""
    m = _STANDARD_PATTERN.search(text)
    if m:
        return re.sub(r"\s+", "-", m.group(1).strip().upper())
    return None


def _is_material_list_query(text: str) -> bool:
    return bool(
        re.search(r"\bwhat\s+materials?\s+are\s+compatible\b", text, re.I)
        or re.search(r"\blist\s+materials?\b", text, re.I)
    )


# ---------------------------------------------------------------------------
# Entity / Domain routing table
# ---------------------------------------------------------------------------

def _determine_fine_routing(
    coarse_intent: str,
    gas_service: Optional[str],
    dissimilar_metals: bool,
    fracture_context: bool,
    material: Optional[str],
    standard_ref: Optional[str],
) -> Tuple[str, float]:
    """
    Map coarse intent + extracted entities to a fine routing target.

    Returns (engine_id, confidence).
    """
    # Compatibility queries route by gas service
    if coarse_intent == "compatibility_query":
        # Dissimilar metals / galvanic takes priority within compatibility
        if dissimilar_metals:
            return "galvanic", 0.95
        if gas_service == "oxygen":
            return "oca", 0.95
        if gas_service == "hydrogen":
            return "h2", 0.95
        # No gas service specified — need to ask
        if material:
            # Material present but no gas — moderate confidence for generic compat
            return "bsmh", 0.60
        return "bsmh", 0.50

    # Material queries
    if coarse_intent == "materials_query":
        if gas_service == "hydrogen":
            return "h2", 0.85
        return "maptis_search", 0.85

    # Document lookup
    if coarse_intent == "document_lookup":
        return "bsmh", 0.80

    # Test report
    if coarse_intent == "test_report":
        return "maptis_search", 0.80

    # Comparison
    if coarse_intent == "comparison":
        if dissimilar_metals:
            return "galvanic", 0.92
        if gas_service == "oxygen":
            return "oca", 0.85
        if gas_service == "hydrogen":
            return "h2", 0.85
        return "maptis_search", 0.75

    # Dissimilar metals / galvanic — even if not primary intent
    if dissimilar_metals:
        return "galvanic", 0.90

    # Fracture context
    if fracture_context:
        return "fracture", 0.85

    # General help / fallback
    return "bsmh", 0.70


def _normalize_module_engine(module_name: str) -> str:
    """Map frontend module names to router engine IDs."""
    return _MODULE_ENGINE_ALIASES.get(module_name.lower(), module_name.lower())


def _detect_explicit_cross_domain_target(
    text: str,
    module_name: str,
) -> Optional[str]:
    """
    Return a non-module engine explicitly requested by the user, if any.

    Module chat should stay in-module by default, but clear cross-domain asks
    like "what about hydrogen?" from OCA or "check galvanic risk" from
    fracture should be allowed to escape the module lock.
    """
    current_engine = _normalize_module_engine(module_name)
    matches = [
        engine_id
        for engine_id, pattern in _EXPLICIT_ENGINE_PATTERNS.items()
        if pattern.search(text)
    ]
    if not matches:
        return None

    other_matches = [engine_id for engine_id in matches if engine_id != current_engine]
    if not other_matches:
        return None

    # If the current module and another engine are both named explicitly,
    # only escape the lock when the user clearly signals a switch.
    if current_engine in matches and len(matches) > 1:
        if len(other_matches) == 1 and _ENGINE_SWITCH_PATTERN.search(text):
            return other_matches[0]
        return None

    return other_matches[0] if len(other_matches) == 1 else None


# ---------------------------------------------------------------------------
# Stage 3: Task Classification
# ---------------------------------------------------------------------------

_DRAFT_VERBS = re.compile(
    r"\b(?:write|draft|generate|build|create|produce|compose|prepare)\b", re.I
)
_REVIEW_VERBS = re.compile(
    r"\b(?:check|review|evaluate|verify|validate|audit|assess)\b",
    re.I,
)
_ANSWER_ONLY_PATTERNS = re.compile(
    r"\b(?:what\s+does\s+this\s+mean|what\s+is|what's|how\s+do\s+i|how\s+do\s+we|"
    r"explain|tell\s+me\s+about|walk\s+me\s+through)\b",
    re.I,
)
_ARTIFACT_REVIEW_HINTS = re.compile(
    r"\b(?:document|artifact|file|pdf|report|drawing|spec(?:ification)?|attachment|upload)\b",
    re.I,
)
_QUESTION_MARKERS = re.compile(
    r"(?:\?|^(?:what|which|how|is|are|can|does|do|will|should|could|would)\b)", re.I
)


def _classify_task_mode(text: str) -> TaskMode:
    """Determine task mode from verb patterns in the query text."""
    if _DRAFT_VERBS.search(text):
        return TaskMode.DRAFT_ARTIFACT
    # Explanatory questions often embed page text such as "Review this requirement..."
    # and should stay answer-oriented unless the user is clearly asking to inspect an artifact.
    if _ANSWER_ONLY_PATTERNS.search(text) and not _ARTIFACT_REVIEW_HINTS.search(text):
        return TaskMode.ANSWER_ONLY
    if _REVIEW_VERBS.search(text) and _ARTIFACT_REVIEW_HINTS.search(text):
        return TaskMode.REVIEW_EXISTING
    # Questions and anything ambiguous default to answer_only
    return TaskMode.ANSWER_ONLY


# ---------------------------------------------------------------------------
# History-based entity resolution
# ---------------------------------------------------------------------------

def _resolve_from_history(
    history: List[ChatMessage],
    current_entities: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Inherit missing entities from the most recent turns in the session.

    HIGH-RISK parameters are NEVER inherited.

    Returns dict of inherited entity key→value (empty if no inheritance).
    """
    if not history:
        return {}

    inherited: Dict[str, Any] = {}
    for turn in reversed(history[-_HISTORY_LOOKBACK_MESSAGES:]):
        if not turn.entities:
            continue
        for key, value in turn.entities.items():
            if key in _HIGH_RISK_PARAMS:
                continue
            if key not in current_entities or current_entities[key] is None:
                inherited.setdefault(key, value)

    return inherited


def _detect_topic_switch(
    current_gas: Optional[str],
    history: List[ChatMessage],
) -> bool:
    """
    Detect if the domain shifted (e.g. oxygen -> hydrogen).

    If so, the caller should reset inherited entities.
    """
    if not history or current_gas is None:
        return False

    for turn in reversed(history[-_HISTORY_LOOKBACK_MESSAGES:]):
        if not turn.entities:
            continue
        prior_gas = turn.entities.get("gas_service")
        if prior_gas and prior_gas != current_gas:
            return True
        if prior_gas:
            break
    return False


# ---------------------------------------------------------------------------
# Public API: interpret()
# ---------------------------------------------------------------------------


def interpret(
    text: str,
    history: Optional[List[ChatMessage]] = None,
    module_context: Optional[dict[str, Any]] = None,
) -> ParsedQuery:
    """
    Full query interpretation pipeline.

    Parameters
    ----------
    text : str
        The raw user message.
    history : list[ChatMessage], optional
        Up to 5 previous turns for entity resolution.
    module_context : dict[str, Any], optional
        Module context from the frontend (e.g. module, case_id, material).

    Returns
    -------
    ParsedQuery
        Fully populated query interpretation result.
    """
    history = (history or [])[-_HISTORY_LOOKBACK_MESSAGES:]
    pq = ParsedQuery(raw_query=text)

    # ----- Stage 1: Coarse Intent -----
    intent_scores = _classify_coarse_intent(text)

    if intent_scores:
        best_intent = max(intent_scores, key=intent_scores.get)  # type: ignore[arg-type]
        best_score = intent_scores[best_intent]
    else:
        best_intent = "help"
        best_score = 0.3

    pq.coarse_intent = "materials_query" if _is_material_list_query(text) else best_intent

    logger.debug(
        "[INTERPRET] Stage 1: coarse_intent=%s (%.2f), all_scores=%s",
        best_intent, best_score, intent_scores,
    )

    # ----- Stage 2: Entity Extraction -----
    extracted_materials = _extract_materials(text)
    pq.material_designation = extracted_materials[0] if extracted_materials else None
    pq.second_material = extracted_materials[1] if len(extracted_materials) > 1 else None
    pq.gas_service = _extract_gas_service(text)
    pq.environment = _extract_environment(text)
    pq.pressure, pq.pressure_value = _extract_pressure(text)
    pq.temperature, pq.temperature_value = _extract_temperature(text)
    pq.standard_ref = _extract_standard_ref(text)
    pq.dissimilar_metals = bool(
        _DISSIMILAR_METALS_PATTERN.search(text)
        or (len(extracted_materials) > 1 and _PAIRING_HINT_PATTERN.search(text))
    )
    pq.fracture_context = bool(_FRACTURE_PATTERN.search(text))

    if module_context:
        pq.material_designation = pq.material_designation or module_context.get("material")
        if pq.second_material is None and module_context.get("material_b"):
            pq.second_material = str(module_context["material_b"])
        if pq.environment is None and module_context.get("environment"):
            pq.environment = str(module_context["environment"])
        if pq.gas_service is None:
            environment = str(module_context.get("environment") or "").lower()
            if "oxygen" in environment or "gox" in environment or "lox" in environment:
                pq.gas_service = "oxygen"
            elif "hydrogen" in environment or "gh2" in environment or "lh2" in environment:
                pq.gas_service = "hydrogen"
        if pq.pressure_value is None and module_context.get("pressure_psi") is not None:
            pq.pressure_value = float(module_context["pressure_psi"])
            pq.pressure = f"{pq.pressure_value:g} psi"

    # History-based inheritance
    current_entities = {
        "material_designation": pq.material_designation,
        "second_material": pq.second_material,
        "gas_service": pq.gas_service,
        "environment": pq.environment,
        "pressure": pq.pressure,
        "temperature": pq.temperature,
        "standard_ref": pq.standard_ref,
    }

    topic_switched = _detect_topic_switch(pq.gas_service, history)
    if topic_switched:
        logger.info("[INTERPRET] Topic switch detected — resetting inherited entities")
        # On topic switch, only carry over material designation if we don't have one
        inherited: Dict[str, Any] = {}
        if pq.material_designation is None and not _is_material_list_query(text):
            for turn in reversed(history[-_HISTORY_LOOKBACK_MESSAGES:]):
                if not turn.entities:
                    continue
                mat = turn.entities.get("material_designation")
                if mat:
                    inherited["material_designation"] = mat
                    break
    else:
        should_inherit = bool(
            history
            and (
                _ANAPHORA_PATTERNS.search(text)
                or _FOLLOW_UP_PATTERNS.search(text)
                or (pq.coarse_intent == "compatibility_query" and pq.material_designation is None)
                or (pq.coarse_intent == "compatibility_query" and pq.gas_service is None)
            )
        )
        inherited = _resolve_from_history(history, current_entities) if should_inherit else {}

    # Apply inherited entities
    if inherited:
        if "material_designation" in inherited and pq.material_designation is None:
            pq.material_designation = inherited["material_designation"]
        if "second_material" in inherited and pq.second_material is None:
            pq.second_material = inherited["second_material"]
        if "gas_service" in inherited and pq.gas_service is None:
            pq.gas_service = inherited["gas_service"]
        if "environment" in inherited and pq.environment is None:
            pq.environment = inherited["environment"]
        if "pressure" in inherited and pq.pressure is None:
            pq.pressure = inherited["pressure"]
            pq.pressure_value = inherited.get("pressure_value")
        if "temperature" in inherited and pq.temperature is None:
            pq.temperature = inherited["temperature"]
            pq.temperature_value = inherited.get("temperature_value")
        if "standard_ref" in inherited and pq.standard_ref is None:
            pq.standard_ref = inherited["standard_ref"]
        pq.inherited_entities = inherited

    if pq.second_material:
        pq.dissimilar_metals = True

    logger.debug(
        "[INTERPRET] Stage 2: material=%s, second_material=%s, gas=%s, environment=%s, "
        "pressure=%s, temp=%s, std=%s, dissimilar=%s, fracture=%s, inherited=%s",
        pq.material_designation, pq.second_material, pq.gas_service, pq.environment,
        pq.pressure, pq.temperature, pq.standard_ref, pq.dissimilar_metals, pq.fracture_context,
        pq.inherited_entities,
    )

    # ----- Stage 3: Task Mode -----
    pq.task_mode = _classify_task_mode(text)

    # ----- Fine routing -----
    base_routing, base_confidence = _determine_fine_routing(
        coarse_intent=pq.coarse_intent,
        gas_service=pq.gas_service,
        dissimilar_metals=pq.dissimilar_metals,
        fracture_context=pq.fracture_context,
        material=pq.material_designation,
        standard_ref=pq.standard_ref,
    )
    module_name = str(module_context.get("module")) if module_context else ""
    if module_name:
        explicit_target = _detect_explicit_cross_domain_target(text, module_name)
        pq.explicit_engine_target = explicit_target
        if explicit_target:
            pq.fine_routing = explicit_target
            pq.routing_confidence = max(base_confidence, 0.96)
        else:
            pq.fine_routing = _normalize_module_engine(module_name)
            pq.routing_confidence = 0.99
    else:
        pq.fine_routing = base_routing
        pq.routing_confidence = base_confidence

    # ----- Confidence threshold check -----
    threshold = ROUTING_CONFIDENCE_THRESHOLDS.get(
        pq.coarse_intent,
        ROUTING_CONFIDENCE_THRESHOLDS["default"],
    )

    if pq.coarse_intent == "compatibility_query" and pq.material_designation is None:
        pq.clarification_needed = True
        pq.clarification_question = _build_clarification(pq)
    elif pq.coarse_intent == "compatibility_query" and pq.gas_service is None:
        pq.clarification_needed = True
        pq.clarification_question = _build_clarification(pq)
    elif pq.routing_confidence < threshold and not module_name:
        # Confidence below threshold — generate a clarification question
        pq.clarification_needed = True
        pq.clarification_question = _build_clarification(pq)
        logger.info(
            "[INTERPRET] Confidence %.2f < threshold %.2f for %s — requesting clarification",
            pq.routing_confidence, threshold, pq.coarse_intent,
        )

    logger.info(
        "[INTERPRET] FINAL: intent=%s, routing=%s (%.2f), task=%s, clarify=%s",
        pq.coarse_intent, pq.fine_routing, pq.routing_confidence,
        pq.task_mode.value, pq.clarification_needed,
    )

    return pq


# ---------------------------------------------------------------------------
# Clarification question builder
# ---------------------------------------------------------------------------


def _build_clarification(pq: ParsedQuery) -> str:
    """Build a helpful clarification question based on what's missing."""
    if pq.coarse_intent == "compatibility_query" and pq.gas_service is None:
        if pq.material_designation:
            return (
                f"I can see you're asking about {pq.material_designation} compatibility. "
                "Which service environment are you interested in? "
                "(e.g., oxygen/GOX/LOX or hydrogen/GH2/LH2)"
            )
        return (
            "What material and service environment are you asking about? "
            "For example: 'Is 316L compatible with GOX at 4000 psi?'"
        )

    if pq.coarse_intent == "compatibility_query" and pq.material_designation is None:
        service = pq.gas_service or "the specified environment"
        return (
            f"Which material would you like to assess for {service} compatibility? "
            "Please provide a material designation (e.g., 316L, Inconel 718, PTFE)."
        )

    if pq.coarse_intent in ("materials_query", "test_report"):
        return (
            "Could you be more specific about what you're looking for? "
            "For example, you might ask about a specific material, test type, or property."
        )

    return (
        "I want to make sure I route your question correctly. "
        "Could you provide more detail about what you need?"
    )
