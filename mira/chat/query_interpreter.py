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
    gas_service: Optional[str] = None           # "oxygen" | "hydrogen" | None
    pressure: Optional[str] = None              # raw string with units
    pressure_value: Optional[float] = None      # numeric psi
    temperature: Optional[str] = None           # raw string with units
    temperature_value: Optional[float] = None   # numeric (Fahrenheit or Celsius, raw)
    standard_ref: Optional[str] = None          # e.g. "NASA-STD-6016C"
    dissimilar_metals: bool = False
    fracture_context: bool = False

    # Routing confidence (0.0–1.0)
    routing_confidence: float = 0.0

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


# ---------------------------------------------------------------------------
# Stage 1: Coarse Intent Classification (keyword / pattern matching)
# ---------------------------------------------------------------------------

# Each intent maps to a list of (compiled_pattern, weight) pairs.
# Score = sum of matched weights; normalized to [0, 1] by dividing by max plausible sum.

_INTENT_PATTERNS: Dict[str, List[Tuple[re.Pattern, float]]] = {
    "compatibility_query": [
        # Explicit compatibility language
        (re.compile(r"\b(compatible|compatibility|approved|rated)\b", re.I), 4.0),
        # Gas service context
        (re.compile(r"\b(O2|oxygen|hydrogen|H2)\s*(service|compatible|safe|approved)\b", re.I), 5.0),
        (re.compile(r"\b(GOX|LOX|GH2|LH2)\s*(service|compatible|use)\b", re.I), 5.0),
        # Bare gas keywords (strong but not as strong as combined)
        (re.compile(r"\b(GOX|LOX|GH2|LH2|oxygen|hydrogen)\b", re.I), 3.0),
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
    r"\b(?:dissimilar\s+metal|galvanic\s+(?:corrosion|couple)|bimetallic|mixed\s+metal)\b",
    re.I,
)

# Fracture context flag
_FRACTURE_PATTERN = re.compile(
    r"\b(?:fracture|crack|fatigue|flaw|damage\s+tolerance|K_?Ic|stress\s+intensity)\b",
    re.I,
)


def _extract_material(text: str) -> Optional[str]:
    """Extract the first plausible material designation from the query."""
    for pattern in _MATERIAL_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(0).strip()
            # Exclude pure numeric tokens that are probably pressures or temps
            if re.fullmatch(r"\d+", raw):
                continue
            return raw
    return None


def _extract_gas_service(text: str) -> Optional[str]:
    """Map gas tokens to canonical 'oxygen' | 'hydrogen'."""
    m = _GAS_PATTERN.search(text)
    if m:
        token = m.group(1).lower()
        return _GAS_SERVICE_MAP.get(token)
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
        return "maptis_search", 0.85

    # Document lookup
    if coarse_intent == "document_lookup":
        return "bsmh", 0.80

    # Test report
    if coarse_intent == "test_report":
        return "maptis_search", 0.80

    # Comparison
    if coarse_intent == "comparison":
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
        return "bsmh", 0.75

    # General help / fallback
    return "bsmh", 0.70


# ---------------------------------------------------------------------------
# Stage 3: Task Classification
# ---------------------------------------------------------------------------

_DRAFT_VERBS = re.compile(
    r"\b(?:write|draft|generate|build|create|produce|compose|prepare)\b", re.I
)
_REVIEW_VERBS = re.compile(
    r"\b(?:check|review|evaluate|verify|validate|audit|is\s+this\s+compliant|assess)\b",
    re.I,
)
_QUESTION_MARKERS = re.compile(
    r"(?:\?|^(?:what|which|how|is|are|can|does|do|will|should|could|would)\b)", re.I
)


def _classify_task_mode(text: str) -> TaskMode:
    """Determine task mode from verb patterns in the query text."""
    if _DRAFT_VERBS.search(text):
        return TaskMode.DRAFT_ARTIFACT
    if _REVIEW_VERBS.search(text):
        return TaskMode.REVIEW_EXISTING
    # Questions and anything ambiguous default to answer_only
    return TaskMode.ANSWER_ONLY


# ---------------------------------------------------------------------------
# History-based entity resolution
# ---------------------------------------------------------------------------

def _resolve_from_history(
    text: str,
    history: List[ChatMessage],
    current_entities: Dict[str, Any],
) -> Dict[str, Any]:
    """
    If the query references prior context ("it", "that material", etc.),
    inherit entities from the most recent assistant turn.

    HIGH-RISK parameters are NEVER inherited.

    Returns dict of inherited entity key→value (empty if no inheritance).
    """
    if not _ANAPHORA_PATTERNS.search(text):
        return {}
    if not history:
        return {}

    # Walk backwards up to 5 turns looking for the most recent assistant turn
    # with entities attached.
    inherited: Dict[str, Any] = {}
    for turn in reversed(history[-5:]):
        if turn.role == "assistant" and turn.entities:
            for key, value in turn.entities.items():
                # Never inherit high-risk parameters
                if key in _HIGH_RISK_PARAMS:
                    continue
                # Only inherit if we don't already have a value
                if key not in current_entities or current_entities[key] is None:
                    inherited[key] = value
            break  # Only inherit from the most recent assistant turn

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

    for turn in reversed(history[-5:]):
        if turn.role == "assistant" and turn.entities:
            prior_gas = turn.entities.get("gas_service")
            if prior_gas and prior_gas != current_gas:
                return True
            break
    return False


# ---------------------------------------------------------------------------
# Public API: interpret()
# ---------------------------------------------------------------------------


def interpret(
    text: str,
    history: Optional[List[ChatMessage]] = None,
    module_context: Optional[str] = None,
) -> ParsedQuery:
    """
    Full query interpretation pipeline.

    Parameters
    ----------
    text : str
        The raw user message.
    history : list[ChatMessage], optional
        Up to 5 previous turns for entity resolution.
    module_context : str, optional
        Module hint from the frontend (e.g. "oca", "h2").

    Returns
    -------
    ParsedQuery
        Fully populated query interpretation result.
    """
    history = history or []
    pq = ParsedQuery(raw_query=text)

    # ----- Stage 1: Coarse Intent -----
    intent_scores = _classify_coarse_intent(text)

    if intent_scores:
        best_intent = max(intent_scores, key=intent_scores.get)  # type: ignore[arg-type]
        best_score = intent_scores[best_intent]
    else:
        best_intent = "help"
        best_score = 0.3

    pq.coarse_intent = best_intent

    logger.debug(
        "[INTERPRET] Stage 1: coarse_intent=%s (%.2f), all_scores=%s",
        best_intent, best_score, intent_scores,
    )

    # ----- Stage 2: Entity Extraction -----
    pq.material_designation = _extract_material(text)
    pq.gas_service = _extract_gas_service(text)
    pq.pressure, pq.pressure_value = _extract_pressure(text)
    pq.temperature, pq.temperature_value = _extract_temperature(text)
    pq.standard_ref = _extract_standard_ref(text)
    pq.dissimilar_metals = bool(_DISSIMILAR_METALS_PATTERN.search(text))
    pq.fracture_context = bool(_FRACTURE_PATTERN.search(text))

    # History-based inheritance
    current_entities = {
        "material_designation": pq.material_designation,
        "gas_service": pq.gas_service,
        "pressure": pq.pressure,
        "temperature": pq.temperature,
        "standard_ref": pq.standard_ref,
    }

    topic_switched = _detect_topic_switch(pq.gas_service, history)
    if topic_switched:
        logger.info("[INTERPRET] Topic switch detected — resetting inherited entities")
        # On topic switch, only carry over material designation if we don't have one
        inherited: Dict[str, Any] = {}
        if pq.material_designation is None:
            for turn in reversed(history[-5:]):
                if turn.role == "assistant" and turn.entities:
                    mat = turn.entities.get("material_designation")
                    if mat:
                        inherited["material_designation"] = mat
                    break
    else:
        inherited = _resolve_from_history(text, history, current_entities)

    # Apply inherited entities
    if inherited:
        if "material_designation" in inherited and pq.material_designation is None:
            pq.material_designation = inherited["material_designation"]
        if "gas_service" in inherited and pq.gas_service is None:
            pq.gas_service = inherited["gas_service"]
        if "pressure" in inherited and pq.pressure is None:
            pq.pressure = inherited["pressure"]
            pq.pressure_value = inherited.get("pressure_value")
        if "temperature" in inherited and pq.temperature is None:
            pq.temperature = inherited["temperature"]
            pq.temperature_value = inherited.get("temperature_value")
        if "standard_ref" in inherited and pq.standard_ref is None:
            pq.standard_ref = inherited["standard_ref"]
        pq.inherited_entities = inherited

    logger.debug(
        "[INTERPRET] Stage 2: material=%s, gas=%s, pressure=%s, temp=%s, std=%s, "
        "dissimilar=%s, fracture=%s, inherited=%s",
        pq.material_designation, pq.gas_service, pq.pressure, pq.temperature,
        pq.standard_ref, pq.dissimilar_metals, pq.fracture_context,
        pq.inherited_entities,
    )

    # ----- Fine routing -----
    # Module context override: if the frontend tells us which module, trust it
    if module_context:
        pq.fine_routing = module_context
        pq.routing_confidence = 0.99
    else:
        pq.fine_routing, pq.routing_confidence = _determine_fine_routing(
            coarse_intent=pq.coarse_intent,
            gas_service=pq.gas_service,
            dissimilar_metals=pq.dissimilar_metals,
            fracture_context=pq.fracture_context,
            material=pq.material_designation,
            standard_ref=pq.standard_ref,
        )

    # ----- Confidence threshold check -----
    threshold = ROUTING_CONFIDENCE_THRESHOLDS.get(
        pq.coarse_intent,
        ROUTING_CONFIDENCE_THRESHOLDS["default"],
    )

    if pq.routing_confidence < threshold and not module_context:
        # Confidence below threshold — generate a clarification question
        pq.clarification_needed = True
        pq.clarification_question = _build_clarification(pq)
        logger.info(
            "[INTERPRET] Confidence %.2f < threshold %.2f for %s — requesting clarification",
            pq.routing_confidence, threshold, pq.coarse_intent,
        )

    # ----- Stage 3: Task Mode -----
    pq.task_mode = _classify_task_mode(text)

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
