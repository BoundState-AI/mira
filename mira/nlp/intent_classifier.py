#!/usr/bin/env python3
"""
Module: Intent Classifier
Purpose: Hybrid heuristic intent classifier that augments the MAPTIS query parser.

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

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentClassificationResult:
    scores: Dict[str, float]
    evidence: List[str]

    def best(self) -> Tuple[str, float]:
        if not self.scores:
            return "unknown", 0.0
        intent, score = max(self.scores.items(), key=lambda item: item[1])
        return intent, score


class IntentClassifier:
    """Hybrid heuristic intent classifier that augments the MAPTIS query parser."""

    # Intent → [(pattern, weight)]
    PATTERNS: Dict[str, Iterable[Tuple[re.Pattern, float]]] = {
        "compatibility_query": [
            # Strong signals: explicit compatibility language
            (re.compile(r"\b(compatible|compatibility|approved|rated|safe)\b", re.IGNORECASE), 4.0),
            # Gas service context: O2/H2 + service terms
            (re.compile(r"\b(O2|oxygen|hydrogen|H2)\s*(service|compatible|safe|approved)\b", re.IGNORECASE), 5.0),
            (re.compile(r"\b(GOX|LOX|GH2|LH2)\s*(service|compatible|use)\b", re.IGNORECASE), 5.0),
            # Pressure/temperature envelope queries (imply compatibility check)
            (re.compile(r"\b(at|for)\s+\d+\s*(psi|psia|bar|Pa)\b", re.IGNORECASE), 3.0),
            # "Can I use X in Y" pattern
            (re.compile(r"\bcan\s+(i|we)\s+use\b", re.IGNORECASE), 4.0),
            # "Is X suitable for Y" pattern
            (re.compile(r"\b(is|are)\s+\w+\s+(suitable|acceptable|allowed)\b", re.IGNORECASE), 4.0),
        ],
        "materials_query": [
            # Material family searches (list/show/find materials)
            (re.compile(r"\b(list|show|find|search|browse)\s+(all\s+)?(material|alloy|metal|polymer)\b", re.IGNORECASE), 4.0),
            (re.compile(r"\b(material|alloy|metal|polymer|composite)\b", re.IGNORECASE), 3.0),
            (re.compile(r"\b(?:tml|cvcm|outgassing|hydrogen|cryogenic)\b", re.IGNORECASE), 2.0),
            # "What materials are" pattern (information seeking)
            (re.compile(r"\bwhat\s+(material|alloy)s?\s+(are|is)\b", re.IGNORECASE), 3.0),
        ],
        "document_lookup": [
            (re.compile(r"\b(NASA[-\s]?STD|MIL[-\s]?STD|specification|procedure)\b", re.IGNORECASE), 3.0),
            (re.compile(r"\bpdf\b"), 1.5),
        ],
        "test_report": [
            (re.compile(r"\b(test|result|pass|fail)\b", re.IGNORECASE), 2.5),
            (re.compile(r"\bASTM|E595|6001\b", re.IGNORECASE), 2.0),
        ],
        "comparison": [
            (re.compile(r"\bcompare|versus|vs\b", re.IGNORECASE), 3.0),
            (re.compile(r"\bbetter than|difference\b", re.IGNORECASE), 2.0),
        ],
        "help": [
            (re.compile(r"\bhow do i|help|can you\b", re.IGNORECASE), 2.5),
        ],
    }

    NEGATIVE_PATTERNS: Dict[str, Iterable[Tuple[re.Pattern, float]]] = {
        "materials_query": [
            (re.compile(r"\binvoice|payment|contract\b", re.IGNORECASE), -2.0),
        ],
    }

    def classify(
        self,
        text: str,
        *,
        structure_hints: Optional[Dict[str, str]] = None,
        modified_at: Optional[datetime] = None,
    ) -> IntentClassificationResult:
        scores: Dict[str, float] = {}
        cleaned = text or ""

        for intent, patterns in self.PATTERNS.items():
            score = 0.0
            for pattern, weight in patterns:
                if pattern.search(cleaned):
                    score += weight
            for pattern, weight in self.NEGATIVE_PATTERNS.get(intent, []):
                if pattern.search(cleaned):
                    score += weight
            if score > 0:
                scores[intent] = max(0.0, min(1.0, score / 5.0))

        evidence: List[str] = []
        if structure_hints:
            try:
                hints_joined = json.dumps(structure_hints).lower()
            except Exception:
                hints_joined = " ".join(structure_hints.values()).lower()
            if "materials" in hints_joined:
                scores["materials_query"] = max(scores.get("materials_query", 0.0), 0.6)
                evidence.append("hint:materials")
            if "document" in hints_joined:
                scores["document_lookup"] = max(scores.get("document_lookup", 0.0), 0.6)
                evidence.append("hint:document")

        if modified_at:
            age_years = max(0.0, (datetime.utcnow() - modified_at).days / 365.0)
            decay = max(0.5, 1.0 - 0.05 * age_years)
            for intent in scores:
                scores[intent] *= decay
            if decay < 1.0:
                evidence.append(f"age_decay:{decay:.2f}")

        if not scores:
            scores["unknown"] = 0.1

        return IntentClassificationResult(scores=scores, evidence=evidence[:8])
